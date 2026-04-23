"""CG-14 Config Drift Auditor deterministic applier.

Three exact-string replacements in graqle/plugins/mcp_dev_server.py:
  1. TOOL_DEFINITIONS entry (near existing graq_audit at ~line 590)
  2. Handler routing (near "graq_audit": self._handle_audit at ~line 3995)
  3. _handle_config_audit method (after _handle_audit at ~line 6084)

Idempotent: detects already-applied state and skips.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = ROOT / "graqle" / "plugins" / "mcp_dev_server.py"
if not MCP.exists():
    print(f"ERROR: mcp_dev_server.py not found at {MCP}", file=sys.stderr)
    sys.exit(1)


def _replace_exact(path: Path, old: str, new: str, *, context: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text and old not in text:
        print(f"SKIP  {context}: already applied")
        return
    count = text.count(old)
    if count == 0:
        print(f"FAIL  {context}: old_content not found in {path.name}", file=sys.stderr)
        sys.exit(2)
    if count > 1:
        print(f"FAIL  {context}: matches {count} times (need 1)", file=sys.stderr)
        sys.exit(3)
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    if new not in path.read_text(encoding="utf-8"):
        print(f"FAIL  {context}: disk-verify failed", file=sys.stderr)
        sys.exit(4)
    print(f"OK    {context}: applied + disk-verified")


# ─────────────────────────────────────────────────────────────────────────
# 1. TOOL_DEFINITIONS — insert graq_config_audit entry BEFORE graq_audit
# ─────────────────────────────────────────────────────────────────────────
# Anchor: the object literal for graq_audit at line 589
MCP_OLD_TOOL_DEF = '''    {
        "name": "graq_audit",
        "description": (
            "Deep health audit of knowledge graph chunk coverage. "
            "Goes beyond validate (which checks descriptions) to audit "
            "the actual evidence chunks that reasoning agents depend on. "
            "Catches hollow KGs where nodes have descriptions but no chunks. "
            "Returns health status: CRITICAL, WARNING, MODERATE, or HEALTHY."
        ),'''

MCP_NEW_TOOL_DEF = '''    {
        "name": "graq_config_audit",
        "description": (
            "CG-14: Audit protected config files (graqle.yaml, pyproject.toml, "
            ".mcp.json, .claude/settings.json) for drift via SHA-256 "
            "fingerprinting. action='audit' returns drift records; "
            "action='accept' marks a file's current state as approved. "
            "Shared primitive for CG-15 KG-write gate and G4 "
            "protected_paths policy. Single-process thread-safe."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["audit", "accept"],
                    "default": "audit",
                    "description": "Audit for drift, or accept a file's current state.",
                },
                "file": {
                    "type": "string",
                    "description": (
                        "Protected file path (relative to repo root). "
                        "Required for action='accept'; ignored for action='audit'."
                    ),
                },
                "approver": {
                    "type": "string",
                    "description": (
                        "Identifier of human reviewer. Required for action='accept'."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "graq_audit",
        "description": (
            "Deep health audit of knowledge graph chunk coverage. "
            "Goes beyond validate (which checks descriptions) to audit "
            "the actual evidence chunks that reasoning agents depend on. "
            "Catches hollow KGs where nodes have descriptions but no chunks. "
            "Returns health status: CRITICAL, WARNING, MODERATE, or HEALTHY."
        ),'''

_replace_exact(MCP, MCP_OLD_TOOL_DEF, MCP_NEW_TOOL_DEF, context="mcp_dev_server.py :: TOOL_DEFINITIONS")


# ─────────────────────────────────────────────────────────────────────────
# 2. Handler routing — insert after graq_audit
# ─────────────────────────────────────────────────────────────────────────

MCP_OLD_ROUTING = '''            "graq_audit": self._handle_audit,
            "graq_runtime": self._handle_runtime,'''

MCP_NEW_ROUTING = '''            "graq_audit": self._handle_audit,
            "graq_config_audit": self._handle_config_audit,
            "graq_runtime": self._handle_runtime,'''

_replace_exact(MCP, MCP_OLD_ROUTING, MCP_NEW_ROUTING, context="mcp_dev_server.py :: handler routing")


# ─────────────────────────────────────────────────────────────────────────
# 3. _handle_config_audit method — insert after _handle_audit's closing brace
# ─────────────────────────────────────────────────────────────────────────
# Anchor: the "# ── 10. graq_runtime ──..." comment that follows _handle_audit
MCP_OLD_HANDLER = '''        return json.dumps(report, indent=2)

    # ── 10. graq_runtime ────────────────────────────────────────────────

    async def _handle_runtime(self, args: dict[str, Any]) -> str:'''

MCP_NEW_HANDLER = '''        return json.dumps(report, indent=2)

    # ── 9b. graq_config_audit (CG-14) ────────────────────────────────────

    async def _handle_config_audit(self, args: dict[str, Any]) -> str:
        """CG-14 config drift audit.

        Validates request shape, delegates to ConfigDriftAuditor, wraps
        every typed exception in a stable error envelope. Never leaks
        raw paths or stack traces (see build_error_envelope sanitization).
        """
        from dataclasses import asdict

        from graqle.governance.config_drift import (
            BaselineCorruptedError,
            ConfigDriftAuditor,
            FileReadError,
            build_accept_response,
            build_audit_response,
            build_error_envelope,
        )

        # ── Step 1: validate request shape (handler responsibility) ──
        action = args.get("action", "audit")
        if action not in ("audit", "accept"):
            return json.dumps(build_error_envelope(
                "CG-14_INVALID_ACTION",
                f"action must be 'audit' or 'accept', got {action!r}",
            ))

        file = args.get("file") or ""
        approver = args.get("approver") or ""
        if action == "accept":
            if not isinstance(file, str) or not file.strip():
                return json.dumps(build_error_envelope(
                    "CG-14_VALIDATION",
                    "action=accept requires non-empty 'file'",
                    field="file",
                ))
            if not isinstance(approver, str) or not approver.strip():
                return json.dumps(build_error_envelope(
                    "CG-14_VALIDATION",
                    "action=accept requires non-empty 'approver'",
                    field="approver",
                ))
            file = file.strip()
            approver = approver.strip()

        # ── Step 2: invoke auditor, map typed exceptions to envelopes ──
        try:
            # Project root: use graph file's parent if available, else cwd
            root = None
            if getattr(self, "_graph_file", None):
                root = Path(self._graph_file).resolve().parent
            auditor = ConfigDriftAuditor(root=root)

            if action == "audit":
                records = auditor.audit()
                return json.dumps(build_audit_response(records))

            # action == "accept"
            try:
                auditor.accept(file, approver)
            except ValueError as exc:
                # unknown file (not in protected_files) or bad approver
                return json.dumps(build_error_envelope(
                    "CG-14_UNKNOWN_FILE",
                    str(exc),
                    file=file,
                ))
            except FileNotFoundError:
                return json.dumps(build_error_envelope(
                    "CG-14_FILE_MISSING",
                    f"protected file not found: {file}",
                    file=file,
                ))
            except FileReadError as exc:
                return json.dumps(build_error_envelope(
                    "CG-14_FILE_UNREADABLE",
                    str(exc),
                    file=file,
                ))
            except BaselineCorruptedError as exc:
                return json.dumps(build_error_envelope(
                    "CG-14_BASELINE_CORRUPTED",
                    str(exc),
                ))
            except OSError as exc:
                return json.dumps(build_error_envelope(
                    "CG-14_BASELINE_IO",
                    f"{type(exc).__name__}: {exc}",
                ))
            return json.dumps(build_accept_response(file, approver))

        except Exception as exc:
            logger.error(
                "graq_config_audit unexpected failure: %s", exc, exc_info=True
            )
            return json.dumps(build_error_envelope(
                "CG-14_RUNTIME",
                f"{type(exc).__name__}: {exc}",
            ))

    # ── 10. graq_runtime ────────────────────────────────────────────────

    async def _handle_runtime(self, args: dict[str, Any]) -> str:'''

_replace_exact(MCP, MCP_OLD_HANDLER, MCP_NEW_HANDLER, context="mcp_dev_server.py :: _handle_config_audit")


print("\n=== CG-14 applier: ALL STEPS COMPLETE ===")
