"""Insert _handle_config_audit method into mcp_dev_server.py.

Uses a mojibake-safe anchor (no box-drawing chars). Idempotent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = ROOT / "graqle" / "plugins" / "mcp_dev_server.py"

text = MCP.read_text(encoding="utf-8")

# Idempotency check
if "async def _handle_config_audit" in text:
    print("SKIP  _handle_config_audit: already present")
    sys.exit(0)

# Anchor: the LAST two lines of _handle_audit + blank line + start of next method.
# We don't include the decorator comment line (has mojibake); we match the
# blank line between methods instead.
ANCHOR = '''        return json.dumps(report, indent=2)

'''

# Find the occurrence that's immediately followed (within 500 chars) by
# `async def _handle_runtime` — uniquely identifies the _handle_audit tail.
count = text.count(ANCHOR)
if count == 0:
    print("FAIL  anchor not found at all", file=sys.stderr)
    sys.exit(1)

# Now locate the specific one followed by _handle_runtime
found = -1
start = 0
while True:
    idx = text.find(ANCHOR, start)
    if idx == -1:
        break
    lookahead = text[idx + len(ANCHOR) : idx + len(ANCHOR) + 500]
    if "async def _handle_runtime" in lookahead:
        found = idx
        break
    start = idx + 1

if found == -1:
    print("FAIL  could not locate _handle_audit tail followed by _handle_runtime", file=sys.stderr)
    sys.exit(2)

# Insert the new handler method AFTER the anchor.
NEW_HANDLER_BLOCK = '''    # -- 9b. graq_config_audit (CG-14) --------------------------------

    async def _handle_config_audit(self, args: dict[str, Any]) -> str:
        """CG-14 config drift audit.

        Validates request shape, delegates to ConfigDriftAuditor, wraps
        every typed exception in a stable error envelope. Never leaks
        raw paths or stack traces (see build_error_envelope sanitization).
        """
        from graqle.governance.config_drift import (
            BaselineCorruptedError,
            ConfigDriftAuditor,
            FileReadError,
            build_accept_response,
            build_audit_response,
            build_error_envelope,
        )

        # Step 1: validate request shape (handler responsibility)
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

        # Step 2: invoke auditor, map typed exceptions to envelopes
        try:
            root = None
            if getattr(self, "_graph_file", None):
                from pathlib import Path as _Path
                root = _Path(self._graph_file).resolve().parent
            auditor = ConfigDriftAuditor(root=root)

            if action == "audit":
                records = auditor.audit()
                return json.dumps(build_audit_response(records))

            # action == "accept"
            try:
                auditor.accept(file, approver)
            except ValueError as exc:
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

'''

# Insertion point: right after the ANCHOR (return json.dumps + blank line),
# before the "# == 10. graq_runtime" comment.
insert_at = found + len(ANCHOR)
new_text = text[:insert_at] + NEW_HANDLER_BLOCK + text[insert_at:]

MCP.write_text(new_text, encoding="utf-8", newline="\n")

# Disk-verify
rb = MCP.read_text(encoding="utf-8")
if "async def _handle_config_audit" not in rb:
    print("FAIL  disk-verify failed: _handle_config_audit not in file", file=sys.stderr)
    sys.exit(3)
if rb.count("async def _handle_config_audit") != 1:
    print(f"FAIL  disk-verify: _handle_config_audit appears {rb.count('async def _handle_config_audit')} times", file=sys.stderr)
    sys.exit(4)

print("OK    _handle_config_audit: inserted + disk-verified")
print(f"      inserted {len(NEW_HANDLER_BLOCK)} bytes at offset {insert_at}")
