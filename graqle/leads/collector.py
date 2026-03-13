"""Graqle lead capture and anonymous usage telemetry.

Captures opt-in developer registrations and anonymous usage signals.
All data is stored locally first (offline-safe), then synced to the
Graqle lead endpoint when connectivity is available.

Privacy guarantees:
- No source code, queries, or secrets are ever transmitted
- Anonymous telemetry is opt-in only (set during graq init or graq register)
- Registration email is opt-in only
- All data stored in ~/.graqle/profile.json (user-inspectable)
- Sync endpoint is configurable (default: https://api.graqle.dev/leads)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.leads")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROFILE_DIR = Path.home() / ".graqle"
PROFILE_PATH = PROFILE_DIR / "profile.json"
EVENTS_PATH = PROFILE_DIR / "events.jsonl"

DEFAULT_LEAD_ENDPOINT = "https://api.graqle.dev/leads"
DEFAULT_EVENTS_ENDPOINT = "https://api.graqle.dev/events"

# Milestones that trigger a soft upsell nudge
USAGE_MILESTONES = [50, 100, 250, 500, 1000]


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------


def _ensure_dir() -> None:
    """Create ~/.graqle/ if needed."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def load_profile() -> dict[str, Any]:
    """Load the local developer profile. Returns empty dict if none exists."""
    if not PROFILE_PATH.exists():
        return {}
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_profile(profile: dict[str, Any]) -> None:
    """Persist the developer profile to ~/.graqle/profile.json."""
    _ensure_dir()
    PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, default=str), encoding="utf-8"
    )


def get_install_id() -> str:
    """Return a stable anonymous install ID (UUID stored in profile).

    This is NOT tied to any personal information — it's a random UUID
    generated once per machine to deduplicate anonymous telemetry.
    """
    profile = load_profile()
    if "install_id" not in profile:
        profile["install_id"] = str(uuid.uuid4())
        save_profile(profile)
    return profile["install_id"]


def is_registered() -> bool:
    """Return True if the developer has completed registration."""
    profile = load_profile()
    return bool(profile.get("email"))


def is_telemetry_enabled() -> bool:
    """Return True if anonymous telemetry is opted in."""
    profile = load_profile()
    return profile.get("telemetry_opt_in", False)


# ---------------------------------------------------------------------------
# Registration (lead capture)
# ---------------------------------------------------------------------------


def register(
    email: str,
    name: str = "",
    company: str = "",
    telemetry_opt_in: bool = True,
    source: str = "cli",
) -> dict[str, Any]:
    """Register a developer (lead capture).

    Saves locally and queues for sync to the lead endpoint.

    Parameters
    ----------
    email:
        Developer's email address.
    name:
        Optional display name.
    company:
        Optional company/organisation name.
    telemetry_opt_in:
        Whether to send anonymous usage telemetry.
    source:
        Where the registration came from (cli, init, web).

    Returns
    -------
    dict
        The updated profile.
    """
    profile = load_profile()
    profile.update({
        "install_id": profile.get("install_id") or str(uuid.uuid4()),
        "email": email,
        "name": name,
        "company": company,
        "telemetry_opt_in": telemetry_opt_in,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "platform": platform.system(),
        "python_version": platform.python_version(),
    })

    # Add project context (non-sensitive)
    profile["projects"] = profile.get("projects", [])

    save_profile(profile)

    # Queue lead for async sync
    _queue_event("registration", {
        "email": email,
        "name": name,
        "company": company,
        "source": source,
        "platform": platform.system(),
    })

    # Try immediate sync (best-effort, non-blocking)
    _try_sync_leads()

    return profile


# ---------------------------------------------------------------------------
# Project tracking (non-sensitive metadata only)
# ---------------------------------------------------------------------------


def track_project_init(
    project_path: str,
    node_count: int,
    edge_count: int,
    backend: str,
    ide: str,
) -> None:
    """Record that graq init was run on a project.

    Only stores a hash of the project path (not the path itself),
    plus non-sensitive metadata about the graph size and backend.
    """
    profile = load_profile()
    projects = profile.get("projects", [])

    # Hash the project path for privacy
    path_hash = hashlib.sha256(project_path.encode()).hexdigest()[:12]

    project_entry = {
        "path_hash": path_hash,
        "node_count": node_count,
        "edge_count": edge_count,
        "backend": backend,
        "ide": ide,
        "init_at": datetime.now(timezone.utc).isoformat(),
    }

    # Update existing or append
    existing = next((p for p in projects if p.get("path_hash") == path_hash), None)
    if existing:
        existing.update(project_entry)
    else:
        projects.append(project_entry)

    profile["projects"] = projects
    save_profile(profile)

    if is_telemetry_enabled():
        _queue_event("project_init", {
            "path_hash": path_hash,
            "node_count": node_count,
            "edge_count": edge_count,
            "backend": backend,
            "ide": ide,
        })


def track_usage(event_type: str, metadata: dict[str, Any] | None = None) -> None:
    """Track a usage event (query, context lookup, etc.).

    Increments local counters. If telemetry is enabled, queues
    an anonymous event for sync.
    """
    profile = load_profile()
    counters = profile.get("usage_counters", {})
    counters[event_type] = counters.get(event_type, 0) + 1
    profile["usage_counters"] = counters
    profile["last_active"] = datetime.now(timezone.utc).isoformat()
    save_profile(profile)

    if is_telemetry_enabled():
        _queue_event("usage", {
            "event_type": event_type,
            "count": counters[event_type],
            **(metadata or {}),
        })


def check_milestone() -> int | None:
    """Check if a usage milestone was just reached.

    Returns the milestone number if just crossed, else None.
    Used to trigger soft upsell nudges at natural touchpoints.
    """
    profile = load_profile()
    counters = profile.get("usage_counters", {})
    total = sum(counters.values())
    shown = set(profile.get("milestones_shown", []))

    for milestone in USAGE_MILESTONES:
        if total >= milestone and milestone not in shown:
            shown.add(milestone)
            profile["milestones_shown"] = sorted(shown)
            save_profile(profile)
            return milestone

    return None


# ---------------------------------------------------------------------------
# Event queue (offline-safe)
# ---------------------------------------------------------------------------


def _queue_event(event_type: str, data: dict[str, Any]) -> None:
    """Append an event to the local event queue for later sync."""
    _ensure_dir()
    event = {
        "type": event_type,
        "install_id": get_install_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    try:
        with open(EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except OSError:
        pass  # Silently fail — telemetry is never critical


def _try_sync_leads() -> bool:
    """Best-effort sync of queued events to the lead endpoint.

    Returns True if sync succeeded, False otherwise.
    Never raises — telemetry failures are silent.
    """
    if not EVENTS_PATH.exists():
        return True

    endpoint = os.environ.get("COGNIGRAPH_LEAD_ENDPOINT", DEFAULT_LEAD_ENDPOINT)

    try:
        events = EVENTS_PATH.read_text(encoding="utf-8").strip().splitlines()
        if not events:
            return True

        payload = {
            "install_id": get_install_id(),
            "events": [json.loads(line) for line in events],
        }

        # Use httpx if available, else urllib (stdlib)
        try:
            import httpx
            resp = httpx.post(
                endpoint,
                json=payload,
                timeout=5.0,
                headers={"User-Agent": _user_agent()},
            )
            if resp.status_code in (200, 201, 202):
                EVENTS_PATH.unlink(missing_ok=True)
                return True
        except ImportError:
            import urllib.request
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": _user_agent(),
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status in (200, 201, 202):
                        EVENTS_PATH.unlink(missing_ok=True)
                        return True
            except Exception:
                pass

    except Exception:
        pass  # Never fail on telemetry

    return False


def _user_agent() -> str:
    """Build a User-Agent string for telemetry requests."""
    try:
        from graqle.__version__ import __version__
        return f"graqle/{__version__} ({platform.system()}; Python {platform.python_version()})"
    except ImportError:
        return f"graqle/unknown ({platform.system()})"


# ---------------------------------------------------------------------------
# Nudge messages (for CLI integration)
# ---------------------------------------------------------------------------


def get_registration_nudge() -> str | None:
    """Return a registration nudge message, or None if already registered."""
    if is_registered():
        return None
    return (
        "[dim]Get updates and priority support: [bold]graq register[/bold][/dim]"
    )


def get_milestone_nudge(milestone: int) -> str:
    """Return a milestone celebration + soft upsell message."""
    if milestone >= 500:
        return (
            f"[bold green]Milestone: {milestone} queries![/bold green] "
            f"Your team could share this knowledge graph. "
            f"See [bold]graq billing[/bold] for Team features."
        )
    elif milestone >= 100:
        return (
            f"[bold cyan]Milestone: {milestone} queries![/bold cyan] "
            f"Graqle is saving you time. "
            f"[dim]Share feedback: graq register[/dim]"
        )
    else:
        return (
            f"[dim]{milestone} queries and counting. "
            f"Get tips & updates: graq register[/dim]"
        )
