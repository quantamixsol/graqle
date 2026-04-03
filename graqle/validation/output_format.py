"""Layer 3 — Format-aware output validation for graq_generate (OT-028/030/035).

Validates structural completeness of generated output. Never mutates output
or triggers continuation — that's Layer 2's responsibility. Returns
diagnostics for callers to act on.

Validates and reports only — never auto-fixes (advisory layer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class FormatDiagnostic:
    check: str
    severity: Literal["error", "warning"]
    message: str
    line: int | None = None


@dataclass
class FormatValidation:
    valid: bool = True
    diagnostics: list[FormatDiagnostic] = field(default_factory=list)
    truncation_suspected: bool = False

    def to_dict(self) -> dict:
        return {
            "format_valid": self.valid,
            "format_warnings": [
                {"check": d.check, "severity": d.severity, "message": d.message}
                for d in self.diagnostics
            ],
            "truncation_suspected": self.truncation_suspected,
        }


def validate_generate_output(
    content: str,
    *,
    output_format: str = "auto",
    expect_summary: bool = True,
) -> FormatValidation:
    """Run all format checks on generated output.

    Args:
        content: The raw generated text.
        output_format: "code", "diff", or "auto" (detect from content).
        expect_summary: Whether SUMMARY: marker is required.

    Returns:
        FormatValidation with diagnostics. Never raises.
    """
    result = FormatValidation()

    if not content or not content.strip():
        result.valid = False
        result.diagnostics.append(FormatDiagnostic(
            check="empty_output", severity="error", message="Empty output",
        ))
        result.truncation_suspected = True
        return result

    # Auto-detect format
    if output_format == "auto":
        if content.lstrip().startswith(("---", "diff ")) or "@@" in content[:500]:
            output_format = "diff"
        else:
            output_format = "code"

    # ── Check 1: Balanced delimiters (OT-028) ──
    _check_balanced_delimiters(content, result)

    # ── Check 2: SUMMARY marker (OT-030) ──
    if expect_summary:
        _check_summary_marker(content, result)

    # ── Check 3: Diff hunk integrity (OT-030) ──
    if output_format == "diff":
        _check_diff_hunks(content, result)

    # ── Check 4: Formula divergence flag (OT-035) ──
    _check_formula_markers(content, result)

    return result


def _check_balanced_delimiters(content: str, result: FormatValidation) -> None:
    """Stack-based delimiter matching, ignoring string literals and comments."""
    cleaned = _strip_strings_and_comments(content)

    pairs = {"{": "}", "[": "]", "(": ")"}
    closing_to_opening = {v: k for k, v in pairs.items()}
    stack: list[tuple[str, int]] = []

    for i, ch in enumerate(cleaned):
        if ch in pairs:
            stack.append((ch, i))
        elif ch in closing_to_opening:
            if not stack or stack[-1][0] != closing_to_opening[ch]:
                line = content[:i].count("\n") + 1
                result.diagnostics.append(FormatDiagnostic(
                    check="balanced_delimiters",
                    severity="error",
                    message=f"Unexpected closing '{ch}' without matching opener",
                    line=line,
                ))
                result.valid = False
                return
            stack.pop()

    if stack:
        opener, pos = stack[-1]
        line = content[:pos].count("\n") + 1
        result.diagnostics.append(FormatDiagnostic(
            check="balanced_delimiters",
            severity="error",
            message=(
                f"Unclosed '{opener}' at line {line} "
                f"({len(stack)} unclosed delimiter(s) total)"
            ),
            line=line,
        ))
        result.valid = False
        result.truncation_suspected = True


def _strip_strings_and_comments(content: str) -> str:
    """Replace string literals and comments with spaces to avoid
    false delimiter matches."""
    patterns = [
        r'"""[\s\S]*?"""',       # Python triple-double
        r"'''[\s\S]*?'''",       # Python triple-single
        r'"(?:[^"\\]|\\.)*"',    # Double-quoted string
        r"'(?:[^'\\]|\\.)*'",    # Single-quoted string
        r"`(?:[^`\\]|\\.)*`",    # Template literal
        r"//[^\n]*",             # Line comment
        r"#[^\n]*",              # Hash comment
        r"/\*[\s\S]*?\*/",       # Block comment
    ]
    combined = "|".join(patterns)
    return re.sub(combined, lambda m: " " * len(m.group()), content)


# Heuristic constants for summary marker detection
_SUMMARY_SEARCH_TAIL = 500  # chars to search from end for SUMMARY: marker
_SUMMARY_MIN_CONTENT_LEN = 200  # skip check on short outputs (avoid false negatives)


def _check_summary_marker(content: str, result: FormatValidation) -> None:
    """Check for SUMMARY: marker in the tail of the output."""
    if len(content) < _SUMMARY_MIN_CONTENT_LEN:
        return

    tail = content[-_SUMMARY_SEARCH_TAIL:] if len(content) > _SUMMARY_SEARCH_TAIL else content
    if not re.search(r"SUMMARY\s*:", tail, re.IGNORECASE):
        result.diagnostics.append(FormatDiagnostic(
            check="summary_marker",
            severity="error",
            message="Missing SUMMARY: marker at end of generated output",
        ))
        result.valid = False
        result.truncation_suspected = True


def _check_diff_hunks(content: str, result: FormatValidation) -> None:
    """Check that each @@ hunk header is followed by content lines."""
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("@@"):
            continue
        # Scan up to next @@ or 10 lines for diff content
        following = []
        for j in range(i + 1, min(i + 11, len(lines))):
            if lines[j].startswith("@@"):
                break
            following.append(lines[j])
        has_content = any(
            fl.startswith(("+", "-", " ")) for fl in following if fl.strip()
        )
        if not has_content:
            result.diagnostics.append(FormatDiagnostic(
                check="diff_hunk_integrity",
                severity="error",
                message=f"Empty diff hunk at line {i + 1}: no +/- content after @@ header",
                line=i + 1,
            ))
            result.valid = False
            result.truncation_suspected = True


# OT-035: Configurable spec-sensitive identifiers — empty by default (opt-in)
# Override via graqle.yaml validation.formula_markers or at call time
SPEC_SENSITIVE_IDENTIFIERS: frozenset[str] = frozenset()


def _check_formula_markers(
    content: str,
    result: FormatValidation,
    markers: frozenset[str] | None = None,
) -> None:
    """OT-035: Flag generated content containing spec-sensitive constants."""
    check_set = markers if markers is not None else SPEC_SENSITIVE_IDENTIFIERS
    if not check_set:
        return  # No markers configured — skip check
    found = [s for s in check_set if s in content]
    if found:
        result.diagnostics.append(FormatDiagnostic(
            check="formula_divergence_risk",
            severity="warning",
            message=(
                f"Output contains spec-sensitive identifiers {found} — "
                f"review against specification required"
            ),
        ))
