"""
graqle.core.kg_sync
~~~~~~~~~~~~~~~~~~~
Knowledge Graph synchronisation layer — S3 as single source of truth.

Implements every local write pushes to S3 (background, non-blocking,
debounced); every server startup pulls from S3 if cloud version is newer.

Public API
----------
pull_if_newer(local_path, project, creds, *, timeout=3.0) -> PullResult
    Pull graqle.json from S3 if the cloud version is newer than the local file.
    Merges learned nodes so nothing is lost.  Silent on network failure.

schedule_push(local_path, project, creds)
    Fire-and-forget: pushes local graqle.json to S3 in a daemon thread.
    Debounced: at most one push per PUSH_DEBOUNCE_SECS per path.

is_offline() -> bool
    Returns True when GRAQLE_OFFLINE=1 env var is set.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.kg_sync")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PUSH_DEBOUNCE_SECS: float = 5.0   # max one push per path per N seconds
PULL_TIMEOUT_SECS: float = 3.0    # max seconds to wait for S3 on startup
S3_BUCKET = "graqle-graphs-eu"

# Session-scoped AccessDenied dedupe.
# Goal: log AccessDenied ONCE per process at WARNING, not per occurrence.
# Other S3 errors continue to be logged at ERROR per occurrence.
_access_denied_logged: bool = False


def _is_access_denied(exc: BaseException) -> bool:
    """Return True iff exc is a botocore ClientError with AccessDenied code."""
    try:
        import botocore.exceptions
        if not isinstance(exc, botocore.exceptions.ClientError):
            return False
        code = exc.response.get("Error", {}).get("Code", "")
        return code in ("AccessDenied", "AccessDeniedException", "403")
    except Exception:
        return False


def _log_s3_error(operation: str, exc: BaseException) -> None:
    """Log an S3 error with AccessDenied dedupe.

    AccessDenied: WARNING once per process, then silenced.
    Other errors: ERROR per occurrence.
    """
    global _access_denied_logged
    if _is_access_denied(exc):
        if not _access_denied_logged:
            logger.warning(
                "KG %s: S3 AccessDenied. Check IAM permissions for bucket %s. Further AccessDenied warnings suppressed for this process. Error: %s",
                operation, S3_BUCKET, exc,
            )
            _access_denied_logged = True
    else:
        logger.error("KG %s failed: %s", operation, exc)


def _reset_access_denied_dedupe() -> None:
    """Reset the dedupe sentinel. For tests only."""
    global _access_denied_logged
    _access_denied_logged = False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PullResult:
    pulled: bool = False
    nodes_added: int = 0
    nodes_total: int = 0
    reason: str = ""


@dataclass
class _PushState:
    """Per-path debounce state."""
    last_push: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


# ---------------------------------------------------------------------------
# Module-level debounce registry
# ---------------------------------------------------------------------------

_push_states: dict[str, _PushState] = {}
_push_states_lock = threading.Lock()


def _get_push_state(path: str) -> _PushState:
    with _push_states_lock:
        if path not in _push_states:
            _push_states[path] = _PushState()
        return _push_states[path]


# ---------------------------------------------------------------------------
# Offline guard
# ---------------------------------------------------------------------------

def is_offline() -> bool:
    """Returns True when GRAQLE_OFFLINE=1 — skips all S3 operations."""
    return os.environ.get("GRAQLE_OFFLINE", "").strip() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# S3 path helper (must match Studio's getUserGraphKey)
# ---------------------------------------------------------------------------

def _s3_key(email_hash: str, project: str, filename: str = "graqle.json") -> str:
    return f"graphs/{email_hash}/{project}/{filename}"


def _email_hash(email: str) -> str:
    import hashlib
    return hashlib.sha256(email.lower().encode()).hexdigest()


# ---------------------------------------------------------------------------
# Credentials helper
# ---------------------------------------------------------------------------

def _load_creds() -> Any | None:
    """Load cloud credentials. Returns None if not authenticated."""
    try:
        from graqle.cloud.credentials import load_credentials
        creds = load_credentials()
        return creds if creds.is_authenticated else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Phase 1 — Pull-before-read
# ---------------------------------------------------------------------------

def pull_if_newer(
    local_path: str | Path,
    project: str | None = None,
    *,
    timeout: float = PULL_TIMEOUT_SECS,
    merge_learned: bool = True,
) -> PullResult:
    """Pull graqle.json from S3 if the cloud version is newer than local.

    Called at every server/CLI startup before loading the local graph.
    Never raises — on any failure, returns PullResult(pulled=False, reason=...).

    Args:
        local_path: Path to local graqle.json
        project:    Project name (auto-detected from directory if None)
        timeout:    Max seconds to wait for S3 (default 3s)
        merge_learned: If True, preserve local LESSON/KNOWLEDGE/ENTITY nodes
                       that are not in the cloud version (default True)
    """
    if is_offline():
        return PullResult(reason="offline mode")

    creds = _load_creds()
    if creds is None:
        return PullResult(reason="not authenticated")

    local_path = Path(local_path)
    if project is None:
        project = _detect_project_name(local_path.parent if local_path.is_file() else local_path)

    email_h = _email_hash(creds.email)
    s3_key = _s3_key(email_h, project)

    try:
        import boto3
        import botocore.exceptions

        s3 = boto3.client("s3")

        # Check S3 object's last-modified without downloading body
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                return PullResult(reason="not in cloud yet")
            return PullResult(reason=f"S3 head error: {code}")

        s3_last_modified: float = head["LastModified"].timestamp()
        local_mtime: float = local_path.stat().st_mtime if local_path.exists() else 0.0

        # Detect corrupt/empty local graph — pull regardless of timestamp.
        # Fix (graq_predict 88%): read file ONCE here to avoid TOCTOU race and
        # reuse the parsed content below for merge_learned (eliminates second read).
        # Detection logic: 0 nodes AND JSON is structurally valid (not a fresh init).
        # A fresh init has valid JSON with nodes=[] and no extra metadata — we
        # distinguish it from corruption by checking if any other keys exist beyond
        # the bare skeleton (directed/multigraph/graph/nodes/links).
        local_json: dict | None = None
        local_nodes_parsed: list[dict] = []
        local_is_corrupt = False

        if local_path.exists():
            try:
                raw_text = local_path.read_text(encoding="utf-8")
                local_json = json.loads(raw_text)
                local_nodes_parsed = local_json.get("nodes", [])
                _SKELETON_KEYS = {"directed", "multigraph", "graph", "nodes", "links"}
                _extra_keys = set(local_json.keys()) - _SKELETON_KEYS
                # Corrupt: 0 nodes but has extra metadata keys (was a real graph before)
                if len(local_nodes_parsed) == 0 and _extra_keys:
                    local_is_corrupt = True
                    logger.warning(
                        "Local graqle.json has 0 nodes but extra keys %s "
                        "(corrupt/emptied after git op?) — forcing pull from S3",
                        _extra_keys,
                    )
            except (json.JSONDecodeError, OSError):
                local_is_corrupt = True
                logger.warning("Local graqle.json unreadable — forcing pull from S3")

        if s3_last_modified <= local_mtime and not local_is_corrupt:
            return PullResult(reason="local is up to date")

        # S3 is newer (or local is corrupt) — download
        if local_is_corrupt:
            logger.info("Pulling KG from S3 (local graph corrupt/empty)")
        else:
            logger.info("Pulling KG from S3 (cloud newer by %.0fs)", s3_last_modified - local_mtime)
        response = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        cloud_data = json.loads(response["Body"].read().decode("utf-8"))

        cloud_nodes: list[dict] = cloud_data.get("nodes", [])
        cloud_links: list[dict] = cloud_data.get("links", [])

        # Fix (graq_predict): circuit-breaker — if S3 also has 0 nodes, don't
        # overwrite local with empty. Log and return without writing to avoid
        # infinite pull loops when both local and cloud are empty.
        if len(cloud_nodes) == 0:
            logger.warning(
                "S3 graph also has 0 nodes — skipping overwrite to avoid empty→empty loop. "
                "Run 'graq scan' to rebuild from source."
            )
            return PullResult(reason="S3 graph is also empty — skipping overwrite")

        if merge_learned and local_json is not None:
            # Reuse already-parsed local content (no second file read — TOCTOU fix)
            try:
                cloud_ids = {n.get("id") for n in cloud_nodes}
                learned_types = {"LESSON", "KNOWLEDGE", "ENTITY", "BUSINESS_OUTCOME"}
                extra = [
                    n for n in local_nodes_parsed
                    if n.get("id") not in cloud_ids
                    and n.get("entity_type", n.get("type", "")).upper() in learned_types
                ]
                if extra:
                    cloud_nodes = cloud_nodes + extra
                    cloud_data["nodes"] = cloud_nodes
                    logger.info("Merged %d local learned nodes into cloud pull", len(extra))
            except Exception as merge_err:
                logger.warning("Learned-node merge skipped: %s", merge_err)

        # Write merged result to local
        from graqle.core.graph import _write_with_lock
        _write_with_lock(str(local_path), json.dumps(cloud_data, indent=2, default=str))
        logger.info("KG pull complete: %d nodes, %d links", len(cloud_nodes), len(cloud_links))

        return PullResult(
            pulled=True,
            nodes_added=len(cloud_nodes) - (len(local_nodes_parsed) if merge_learned and local_json is not None else 0),
            nodes_total=len(cloud_nodes),
            reason="pulled from S3",
        )

    except ImportError:
        return PullResult(reason="boto3 not available")
    except Exception as exc:
        # dedupe AccessDenied at WARNING, log other errors at ERROR
        _log_s3_error("pull", exc)
        return PullResult(reason=f"error: {exc}")


# ---------------------------------------------------------------------------
# Phase 2 — Push-after-write (background, debounced)
# ---------------------------------------------------------------------------

def schedule_push(
    local_path: str | Path,
    project: str | None = None,
    *,
    retry_on_error: bool = True,
) -> None:
    """Schedule a background S3 push. Debounced: max 1 push per PUSH_DEBOUNCE_SECS.

    Args:
        local_path:     Path to local graqle.json
        project:        Project name (auto-detected if None)
        retry_on_error: If True (default), retry once after 1s on failure.
                        Set False in CI/test paths for fast-fail behavior.
    """
    if is_offline():
        return

    local_path = Path(local_path)
    state = _get_push_state(str(local_path))

    with state.lock:
        now = time.monotonic()
        if now - state.last_push < PUSH_DEBOUNCE_SECS:
            logger.debug("KG push debounced (%.1fs since last push)", now - state.last_push)
            return
        state.last_push = now

    t = threading.Thread(
        target=_push_worker,
        args=(local_path, project, retry_on_error),
        daemon=True,
        name=f"graqle-kg-push-{local_path.name}",
    )
    t.start()


def _push_worker(local_path: Path, project: str | None, retry_on_error: bool = True) -> None:
    """Background worker: push local graqle.json to S3."""
    creds = _load_creds()
    if creds is None:
        return

    if not local_path.exists():
        return

    if project is None:
        project = _detect_project_name(
            local_path.parent if local_path.is_file() else local_path
        )

    email_h = _email_hash(creds.email)
    s3_key = _s3_key(email_h, project)

    for attempt in (1, 2) if retry_on_error else (1,):
        try:
            import boto3
            data = local_path.read_bytes()
            s3 = boto3.client("s3")
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=data,
                ContentType="application/json",
            )
            node_count = len(json.loads(data).get("nodes", []))
            logger.info(
                "KG pushed to S3: %s (%d nodes, attempt %d)", s3_key, node_count, attempt
            )
            return
        except ImportError:
            return  # boto3 not available — skip silently
        except Exception as exc:
            # dedupe AccessDenied at WARNING, log other errors at ERROR
            if attempt == 1 and retry_on_error:
                _log_s3_error("push (retrying)", exc)
                time.sleep(1.0)
            else:
                _suffix = " after 2 attempts" if retry_on_error else ""
                _log_s3_error("push" + _suffix, exc)


# ---------------------------------------------------------------------------
# Conflict detection helper (used by cloud push CLI)
# ---------------------------------------------------------------------------

def check_push_conflict(
    local_path: str | Path,
    project: str,
    email_hash: str,
) -> tuple[bool, str]:
    """Check whether S3 is newer than local before a manual push.

    Returns (conflict: bool, reason: str).
    If conflict=True, the caller should warn the user and abort unless --force.
    """
    if is_offline():
        return False, "offline mode"

    local_path = Path(local_path)
    local_mtime = local_path.stat().st_mtime if local_path.exists() else 0.0
    s3_key = _s3_key(email_hash, project)

    try:
        import boto3
        import botocore.exceptions
        s3 = boto3.client("s3")
        head = s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
        s3_mtime = head["LastModified"].timestamp()
        if s3_mtime > local_mtime + 10:  # 10s grace window for clock skew
            delta = s3_mtime - local_mtime
            return True, (
                f"Cloud version is {delta:.0f}s newer than local. "
                f"Run 'graq cloud pull --merge' first, or use --force to overwrite."
            )
        return False, ""
    except ImportError:
        return False, "boto3 not available"
    except Exception as exc:
        return False, f"conflict check failed: {exc}"


# ---------------------------------------------------------------------------
# Direct download helper (used by graq cloud pull)
# ---------------------------------------------------------------------------

def download_graph(
    local_path: str | Path,
    project: str,
    email_hash: str,
    *,
    merge: bool = True,
) -> tuple[bool, str, int]:
    """Download graqle.json from S3 to local_path.

    Args:
        local_path:   Destination path
        project:      Project name
        email_hash:   SHA-256 of user email
        merge:        If True, preserve local learned nodes not in S3

    Returns:
        (success: bool, message: str, node_count: int)
    """
    if is_offline():
        return False, "offline mode", 0

    local_path = Path(local_path)
    s3_key = _s3_key(email_hash, project)

    try:
        import boto3
        import botocore.exceptions
        s3 = boto3.client("s3")

        try:
            response = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                return False, f"Project '{project}' not found in cloud", 0
            return False, f"S3 error: {code}", 0

        cloud_data = json.loads(response["Body"].read().decode("utf-8"))
        cloud_nodes: list[dict] = cloud_data.get("nodes", [])

        if merge and local_path.exists():
            try:
                local_data = json.loads(local_path.read_text(encoding="utf-8"))
                local_nodes: list[dict] = local_data.get("nodes", [])
                cloud_ids = {n.get("id") for n in cloud_nodes}
                learned_types = {"LESSON", "KNOWLEDGE", "ENTITY", "BUSINESS_OUTCOME"}
                extra = [
                    n for n in local_nodes
                    if n.get("id") not in cloud_ids
                    and n.get("entity_type", n.get("type", "")).upper() in learned_types
                ]
                if extra:
                    cloud_nodes = cloud_nodes + extra
                    cloud_data["nodes"] = cloud_nodes
            except Exception:
                pass  # merge failure is non-fatal — use cloud as-is

        from graqle.core.graph import _write_with_lock
        _write_with_lock(str(local_path), json.dumps(cloud_data, indent=2, default=str))

        node_count = len(cloud_nodes)
        return True, f"Downloaded {node_count} nodes from cloud", node_count

    except ImportError:
        return False, "boto3 not available — install with: pip install graqle[cloud]", 0
    except Exception as exc:
        return False, f"Download failed: {exc}", 0


# ---------------------------------------------------------------------------
# Project name helper (standalone, no CLI deps)
# ---------------------------------------------------------------------------

def _detect_project_name(root: Path) -> str:
    """Detect project name from graqle.yaml, pyproject.toml, or directory name."""
    for yaml_name in ("graqle.yaml", "graqle.yml"):
        p = root / yaml_name
        if p.exists():
            try:
                import yaml
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                name = (data or {}).get("project", {}).get("name", "")
                if name:
                    return name
            except Exception:
                pass

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            for line in pyproject.read_text(encoding="utf-8").split("\n"):
                if line.strip().startswith("name") and "=" in line:
                    name = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if name:
                        return name
        except Exception:
            pass

    pkg = root / "package.json"
    if pkg.exists():
        try:
            name = json.loads(pkg.read_text(encoding="utf-8")).get("name", "")
            if name:
                return name
        except Exception:
            pass

    return root.resolve().name
