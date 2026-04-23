"""G5 (Wave 2 Phase 7): VS Code extension gate-install target.

Scaffolds workspace governance files under `.vscode/` + root `.mcp.json`
from package data in ``graqle/data/vscode_gate/``.

Merge semantics preserve user keys:
  - ``.vscode/settings.json`` — deep-merge (user keys win on collision)
  - ``.vscode/tasks.json``    — append tasks by label, skip duplicates
  - ``.vscode/extensions.json`` — append to recommendations, dedupe
  - ``.mcp.json``             — merge ``mcpServers`` dict, skip if
                                ``graqle`` key present unless force=True

Called from :func:`graqle.cli.main.gate_install_command` when
``--target=vscode-extension`` (or ``--target=all``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _probe_python_interpreter_vscode() -> str:
    """Return the python command VS Code should use for the MCP server.

    Mirrors the claude-target probe but does NOT couple to it.
    Falls back to ``sys.executable`` if detection fails.
    """
    import sys
    return sys.executable


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    """Return parsed JSON from ``path``, or None on parse error. Missing
    file returns the string sentinel ``"__missing__"`` so callers can
    distinguish missing from corrupt."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "__corrupt__"  # type: ignore[return-value]


def _write_json_atomic(path: Path, data: Any) -> None:
    """Atomic write: tempfile + os.replace. Creates parent dirs."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
        tmp_path = None  # replaced successfully
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _deep_merge_preserve_user(template: dict, existing: dict) -> dict:
    """Deep-merge template INTO existing. User keys always win.

    - Dict: recurse; user keys preserved.
    - List: user wins (template does not extend lists here).
    - Scalar: user wins.
    - Missing key in existing: copy from template.
    """
    merged = dict(existing)
    for key, val in template.items():
        if key not in merged:
            merged[key] = val
        elif isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_preserve_user(val, merged[key])
        # else: user value wins, no action
    return merged


def _merge_tasks_by_label(
    template_tasks: list[dict], existing_tasks: list[dict],
) -> list[dict]:
    """Append template tasks into existing by label. Duplicate labels skipped.

    Labels starting with ``"graq:"`` are owned by us; if an existing
    task has that label, it's considered already-installed (no overwrite).
    """
    existing_labels = {
        t.get("label") for t in existing_tasks
        if isinstance(t, dict) and isinstance(t.get("label"), str)
    }
    result = list(existing_tasks)
    for t in template_tasks:
        if not isinstance(t, dict):
            continue
        label = t.get("label")
        if label in existing_labels:
            continue
        result.append(t)
    return result


def _merge_extensions(
    template_recs: list[str], existing_recs: list[str],
) -> list[str]:
    """Append template recommendations, dedupe preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in list(existing_recs) + list(template_recs):
        if not isinstance(item, str):
            continue
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def install_vscode_extension_target(
    root: Path,
    pkg_data_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    interpreter_cmd: str | None = None,
) -> dict[str, Any]:
    """Scaffold VS Code workspace governance files.

    Returns a dict describing actions taken:
      {
        "target": "vscode-extension",
        "actions": [{"file": "...", "status": "created|merged|skipped|would-write", "reason"?: "..."}],
        "dry_run": bool,
      }
    """
    actions: list[dict[str, Any]] = []

    interp = interpreter_cmd or _probe_python_interpreter_vscode()

    # ── Load all 4 templates from package data ──
    template_map = {
        ".vscode/settings.json": pkg_data_dir / "settings.json",
        ".vscode/tasks.json": pkg_data_dir / "tasks.json",
        ".vscode/extensions.json": pkg_data_dir / "extensions.json",
        ".mcp.json": pkg_data_dir / "mcp.json",
    }
    templates: dict[str, Any] = {}
    for rel, src in template_map.items():
        if not src.exists():
            actions.append({
                "file": rel, "status": "error",
                "reason": f"template missing: {src}",
            })
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            actions.append({
                "file": rel, "status": "error",
                "reason": f"template corrupt: {exc}",
            })
            continue
        # Substitute {{PYTHON_INTERPRETER}} in mcp.json command field
        if rel == ".mcp.json":
            servers = data.get("mcpServers", {})
            for name, cfg in servers.items():
                if isinstance(cfg, dict) and cfg.get("command") == "{{PYTHON_INTERPRETER}}":
                    cfg["command"] = interp
        templates[rel] = data

    if any(a["status"] == "error" for a in actions):
        return {"target": "vscode-extension", "actions": actions, "dry_run": dry_run}

    # ── Process each file ──
    for rel, template_data in templates.items():
        dst = root / rel
        existing = _load_json(dst)

        if existing == "__corrupt__":
            if force:
                new_data = template_data
                merged_note = "overwritten (corrupt; --force)"
            else:
                actions.append({
                    "file": rel, "status": "error",
                    "reason": "existing JSON is corrupt; re-run with --force",
                })
                continue
        elif existing is None:
            new_data = template_data
            merged_note = "created"
        else:
            # Merge logic per file
            if rel == ".vscode/settings.json":
                if isinstance(existing, dict):
                    new_data = _deep_merge_preserve_user(template_data, existing)
                    merged_note = "merged (user keys preserved)"
                else:
                    new_data = template_data
                    merged_note = "overwritten (existing was not dict)"
            elif rel == ".vscode/tasks.json":
                if isinstance(existing, dict):
                    existing_tasks = existing.get("tasks", [])
                    if not isinstance(existing_tasks, list):
                        existing_tasks = []
                    merged_tasks = _merge_tasks_by_label(
                        template_data.get("tasks", []),
                        existing_tasks,
                    )
                    new_data = dict(existing)
                    new_data["tasks"] = merged_tasks
                    if "version" not in new_data:
                        new_data["version"] = template_data.get("version", "2.0.0")
                    merged_note = "tasks appended (skipped duplicates)"
                else:
                    new_data = template_data
                    merged_note = "overwritten (malformed)"
            elif rel == ".vscode/extensions.json":
                if isinstance(existing, dict):
                    existing_recs = existing.get("recommendations", [])
                    if not isinstance(existing_recs, list):
                        existing_recs = []
                    new_recs = _merge_extensions(
                        template_data.get("recommendations", []),
                        existing_recs,
                    )
                    new_data = dict(existing)
                    new_data["recommendations"] = new_recs
                    merged_note = "recommendations merged (deduped)"
                else:
                    new_data = template_data
                    merged_note = "overwritten (malformed)"
            elif rel == ".mcp.json":
                if isinstance(existing, dict):
                    existing_servers = existing.get("mcpServers", {})
                    if not isinstance(existing_servers, dict):
                        existing_servers = {}
                    template_servers = template_data.get("mcpServers", {})
                    new_servers = dict(existing_servers)
                    for name, cfg in template_servers.items():
                        if name in new_servers and not force:
                            actions.append({
                                "file": rel, "status": "skipped",
                                "reason": f"mcpServers.{name} already present; use --force to overwrite",
                            })
                            continue
                        new_servers[name] = cfg
                    new_data = dict(existing)
                    new_data["mcpServers"] = new_servers
                    merged_note = "mcpServers merged"
                else:
                    new_data = template_data
                    merged_note = "overwritten (malformed)"
            else:
                new_data = template_data
                merged_note = "created"

        if dry_run:
            actions.append({
                "file": rel, "status": "would-write", "reason": merged_note,
            })
        else:
            try:
                _write_json_atomic(dst, new_data)
                actions.append({
                    "file": rel, "status": "ok", "reason": merged_note,
                })
            except OSError as exc:
                actions.append({
                    "file": rel, "status": "error",
                    "reason": f"write failed: {type(exc).__name__}",
                })

    return {"target": "vscode-extension", "actions": actions, "dry_run": dry_run}
