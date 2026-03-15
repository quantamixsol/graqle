"""Inline Intelligence Headers — Layer B of the Quality Gate.

Injects/ejects bounded intelligence comment blocks into source files.
The AI reads the file → sees intelligence → makes better decisions.
No tool call required. No latency added. Cannot be bypassed.

Markers:
  Python:  # ── graqle:intelligence ──
# module: graqle.intelligence.headers
# risk: LOW (impact radius: 3 modules)
# consumers: compile, __init__, test_headers
# dependencies: __future__, logging, re, pathlib, typing +1 more
# constraints: none
# ── /graqle:intelligence ──
  JS/TS:   // ── graqle:intelligence ──  ...  // ── /graqle:intelligence ──

See ADR-105 §Layer B: Embedded Intelligence.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from graqle.intelligence.models import ModulePacket

logger = logging.getLogger("graqle.intelligence.headers")

# Marker patterns for different languages
_MARKERS = {
    ".py": ("# ", "# ── graqle:intelligence ──", "# ── /graqle:intelligence ──"),
    ".js": ("// ", "// ── graqle:intelligence ──", "// ── /graqle:intelligence ──"),
    ".ts": ("// ", "// ── graqle:intelligence ──", "// ── /graqle:intelligence ──"),
    ".jsx": ("// ", "// ── graqle:intelligence ──", "// ── /graqle:intelligence ──"),
    ".tsx": ("// ", "// ── graqle:intelligence ──", "// ── /graqle:intelligence ──"),
}

# Max header size (bytes) to avoid bloating source files
MAX_HEADER_BYTES = 600


def generate_header(packet: ModulePacket, ext: str) -> str:
    """Generate an intelligence header string for a given file extension.

    Returns empty string for unsupported extensions.
    """
    if ext not in _MARKERS:
        return ""

    prefix, open_marker, close_marker = _MARKERS[ext]

    lines = [open_marker]

    # Module name
    lines.append(f"{prefix}module: {packet.module}")

    # Risk
    lines.append(f"{prefix}risk: {packet.risk_level} (impact radius: {packet.impact_radius} modules)")

    # Consumers (top 5)
    if packet.consumers:
        consumer_names = [c.module.rsplit(".", 1)[-1] for c in packet.consumers[:5]]
        suffix = f" +{len(packet.consumers) - 5} more" if len(packet.consumers) > 5 else ""
        lines.append(f"{prefix}consumers: {', '.join(consumer_names)}{suffix}")

    # Dependencies (top 5)
    if packet.dependencies:
        dep_names = [d.module.rsplit(".", 1)[-1] for d in packet.dependencies[:5]]
        suffix = f" +{len(packet.dependencies) - 5} more" if len(packet.dependencies) > 5 else ""
        lines.append(f"{prefix}dependencies: {', '.join(dep_names)}{suffix}")

    # Constraints
    if packet.constraints:
        for c in packet.constraints[:3]:
            lines.append(f"{prefix}constraint: {c}")
    else:
        lines.append(f"{prefix}constraints: none")

    # Incidents
    if packet.incidents:
        for inc in packet.incidents[:2]:
            lines.append(f"{prefix}incident: {inc[:80]}")

    lines.append(close_marker)

    header = "\n".join(lines)

    # Enforce size limit
    if len(header.encode("utf-8")) > MAX_HEADER_BYTES:
        # Truncate to essential lines only
        lines = [open_marker]
        lines.append(f"{prefix}module: {packet.module}")
        lines.append(f"{prefix}risk: {packet.risk_level} (impact: {packet.impact_radius})")
        if packet.consumers:
            lines.append(f"{prefix}consumers: {len(packet.consumers)} modules")
        lines.append(close_marker)
        header = "\n".join(lines)

    return header


def inject_header(file_path: Path, header: str) -> bool:
    """Inject intelligence header into a source file.

    If markers already exist, replaces content between them.
    If not, inserts after any shebang/encoding/docstring at top.
    Returns True if file was modified.
    """
    if not header:
        return False

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return False

    ext = file_path.suffix.lower()
    if ext not in _MARKERS:
        return False

    _, open_marker, close_marker = _MARKERS[ext]

    # Check if markers already exist
    if open_marker in content:
        # Replace between markers
        pattern = re.escape(open_marker) + r".*?" + re.escape(close_marker)
        new_content = re.sub(pattern, header, content, count=1, flags=re.DOTALL)
        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8")
            return True
        return False

    # Insert header at appropriate position
    insert_pos = _find_insert_position(content, ext)
    new_content = content[:insert_pos] + header + "\n\n" + content[insert_pos:]
    file_path.write_text(new_content, encoding="utf-8")
    return True


def eject_header(file_path: Path) -> bool:
    """Remove intelligence header from a source file.

    Returns True if file was modified.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return False

    ext = file_path.suffix.lower()
    if ext not in _MARKERS:
        return False

    _, open_marker, close_marker = _MARKERS[ext]

    if open_marker not in content:
        return False

    # Remove header block including surrounding blank lines
    pattern = r"\n?" + re.escape(open_marker) + r".*?" + re.escape(close_marker) + r"\n?\n?"
    new_content = re.sub(pattern, "\n", content, count=1, flags=re.DOTALL)

    if new_content != content:
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False


def has_header(file_path: Path) -> bool:
    """Check if a file already has an intelligence header."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return False

    ext = file_path.suffix.lower()
    if ext not in _MARKERS:
        return False

    _, open_marker, _ = _MARKERS[ext]
    return open_marker in content


def _find_insert_position(content: str, ext: str) -> int:
    """Find the best position to insert the header.

    For Python: after shebang, encoding declaration, and module docstring.
    For JS/TS: after any 'use strict' or initial comments.
    """
    pos = 0

    if ext == ".py":
        lines = content.split("\n")
        line_idx = 0

        # Skip shebang
        if lines and lines[0].startswith("#!"):
            line_idx = 1

        # Skip encoding declaration
        if line_idx < len(lines) and "coding" in lines[line_idx]:
            line_idx += 1

        # Skip blank lines
        while line_idx < len(lines) and not lines[line_idx].strip():
            line_idx += 1

        # Skip module docstring
        if line_idx < len(lines):
            line = lines[line_idx].strip()
            if line.startswith('"""') or line.startswith("'''"):
                quote = line[:3]
                if line.count(quote) >= 2 and len(line) > 6:
                    # Single-line docstring
                    line_idx += 1
                else:
                    # Multi-line docstring — find closing
                    line_idx += 1
                    while line_idx < len(lines) and quote not in lines[line_idx]:
                        line_idx += 1
                    if line_idx < len(lines):
                        line_idx += 1  # skip closing line

        # Skip blank lines after docstring
        while line_idx < len(lines) and not lines[line_idx].strip():
            line_idx += 1

        pos = sum(len(lines[i]) + 1 for i in range(line_idx))

    elif ext in (".js", ".ts", ".jsx", ".tsx"):
        lines = content.split("\n")
        line_idx = 0

        # Skip 'use strict'
        if lines and "'use strict'" in lines[0]:
            line_idx = 1

        # Skip initial comment block
        while line_idx < len(lines) and (
            lines[line_idx].strip().startswith("//") or
            lines[line_idx].strip().startswith("/*") or
            lines[line_idx].strip().startswith("*")
        ):
            line_idx += 1

        # Skip blank lines
        while line_idx < len(lines) and not lines[line_idx].strip():
            line_idx += 1

        pos = sum(len(lines[i]) + 1 for i in range(line_idx))

    return pos
