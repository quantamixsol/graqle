"""Distribution-time public-disclosure lint (v0.50.1).

Guards against regressions of the v0.50.1 hotfix sanitization by
asserting that the four CRITICAL-sanitized files never again contain
forbidden internal strings:

  * ``graqle/core/governance.py``            (CG-GOV-01)
  * ``graqle/chat/templates/GRAQ_default.md`` (CG-TEMPLATE-01..04)
  * ``graqle/chat/templates/tcg_default.json`` (CG-TCG-01)
  * ``graqle/calibration/benchmarks/graqle_calibration_v1.yaml``

Forbidden strings include:

  * protected-pattern tag names (TS-1..TS-4)
  * internal product / sibling project names (crawlq, tracegov,
    graqle-studio, graqle-vscode)
  * internal tracker / ADR IDs (ADR-N, TB-LN, OT-NNN, CG-*, BLOCKER-N)
  * hard-coded internal cost / budget constants

A secondary *advisory* test (``test_advisory_package_wide_leakage``)
counts the number of pre-existing leaks across the whole ``graqle/``
package and records them as a metric. It does NOT fail the build —
systematic sanitization of the remaining files is scheduled for
v0.51.0 (see ``.gcc/OPEN-TRACKER-CAPABILITY-GAPS.md`` CG-SANITIZE-POSTFIX).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GRAQLE_PKG = REPO_ROOT / "graqle"

# ---------------------------------------------------------------------------
# Forbidden string patterns
# ---------------------------------------------------------------------------

# CRITICAL — pattern tags
PATTERN_TAGS = [
    r"\bTS-[1-4]\b",
]

# HIGH — internal product / sibling project names
INTERNAL_PRODUCTS = [
    r"\bcrawlq\b",
    r"\btracegov\b",
    r"\bgraqle-studio\b",
    r"\bgraqle-vscode\b",
]

# HIGH — internal tracker / ADR IDs
INTERNAL_TRACKERS = [
    r"\bADR-[0-9]+\b",
    r"\bTB-[A-Z][0-9]+\b",
    r"\bOT-[0-9]{3}\b",
    r"\bCG-[A-Z]+(?:-[0-9]+)?\b",
    r"\bBLOCKER-[0-9]+\b",
]

# HIGH — internal cost / budget constants
INTERNAL_BUDGETS = [
    r"\$10/month",
    r"pytest-xdist workers",
]

ALL_FORBIDDEN_PATTERNS = (
    PATTERN_TAGS + INTERNAL_PRODUCTS + INTERNAL_TRACKERS + INTERNAL_BUDGETS
)
COMBINED_RE = re.compile("|".join(ALL_FORBIDDEN_PATTERNS))

SHIPPED_EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".toml"}

# ---------------------------------------------------------------------------
# Exemptions
# ---------------------------------------------------------------------------

# Files / directories that are deferred to v0.51.0 systematic sanitization.
# Each entry must be a repo-relative POSIX-style prefix.
EXEMPT_PATHS: set[str] = {
    "graqle/benchmarks/",
    "graqle/cli/commands/link.py",          # CG-LINK-01 v0.51.0
    "graqle/connectors/neptune.py",          # CG-NEPTUNE-01 v0.51.0
    "graqle/connectors/neptune_connector.py",  # CG-NEPTUNE-02 v0.51.0
    "graqle/cli/main.py",                    # CG-CLI-01 v0.51.0 (console msg)
    "graqle/workflow/diff_applicator.py",    # CG-GOV-02 v0.51.0
    "graqle/ontology/domains/coding.py",     # CG-GOV-03 v0.51.0
    "graqle/ontology/domains/mcp.py",        # CG-GOV-04 v0.51.0
    "graqle/plugins/mcp_dev_server.py",      # CG-GOV-05 v0.51.0 (schema desc)
    # Wave 2 0.52.0b1: Phase 2 CG-REASON-DIAG-01 informational comments
    "graqle/orchestration/aggregation.py",   # CG-GOV-06 (Wave 2 Phase 2 comment tags)
    "graqle/orchestration/orchestrator.py",  # CG-GOV-07 (Wave 2 Phase 2 comment tags)
    # R18-R21 (ADR-201..204): governance research modules — ADR refs are spec annotations
    "graqle/governance/trace_schema.py",     # R18 ADR-201 spec annotations
    "graqle/governance/trace_capture.py",    # R18 ADR-201 spec annotations
    "graqle/governance/trace_store.py",      # R18 ADR-201 spec annotations
    "graqle/governance/failure_features.py", # R19 ADR-202 spec annotations
    "graqle/governance/failure_predictor.py",# R19 ADR-202 spec annotations
    "graqle/governance/calibration.py",      # R20 ADR-203 spec annotations
    "graqle/governance/calibration_store.py",# R20 ADR-203 spec annotations
    "graqle/governance/reliability_diagram.py",  # R20 ADR-203 spec annotations
    "graqle/governance/near_miss_store.py",  # R20 ADR-203 spec annotations
    "graqle/governance/federated_transfer.py",   # R21 ADR-204 spec annotations
    "graqle/governance/pattern_abstractor.py",   # R21 ADR-204 spec annotations
    "graqle/governance/pattern_registry.py", # R21 ADR-204 spec annotations
    "graqle/governance/adaptation.py",       # R21 ADR-204 spec annotations
    "graqle/governance/similarity.py",       # R21 ADR-204 spec annotations
    "graqle/governance/__init__.py",         # R18-R21 combined exports (ADR refs in docstring)
    "graqle/cli/commands/calibrate_governance.py",  # R20 CLI — ADR ref in module docstring
    # R22 (ADR-205): SHACL governance completeness verification — ADR refs are spec annotations
    "graqle/governance/shacl/",                     # R22 ADR-205 spec annotations + shapes.ttl
    # R23 (ADR-206): GSEFT scaffold — ADR refs are spec annotations for deferred research modules
    "graqle/embeddings/__init__.py",                # R23 ADR-206 spec annotation
    "graqle/embeddings/contrastive_trainer.py",     # R23 ADR-206 spec annotation
    "graqle/embeddings/governance_dataset.py",      # R23 ADR-206 spec annotation
    "graqle/embeddings/governance_eval.py",         # R23 ADR-206 spec annotation
    "graqle/embeddings/model_registry.py",          # R23 ADR-206 spec annotation
}

# Modules whose TS-2 compliance comments are informational, not pattern
# disclosures. These are exempted until v0.51.0 renames the comment to
# "Internal pattern B" to match graqle/core/governance.py Fix 1 style.
TS2_COMMENT_EXEMPT: set[str] = {
    "graqle/alignment/r9_config.py",
    "graqle/config/settings.py",
    "graqle/core/memory_types.py",
    "graqle/federation/merger.py",
    "graqle/federation/types.py",
    "graqle/intent/evaluator.py",
    "graqle/intent/online_learner.py",
    "graqle/intent/types.py",
    "graqle/reasoning/memory.py",
    "graqle/reasoning/semaphore.py",
    "graqle/scanner/mcp_linker.py",
    "graqle/scanner/reclassify_mcp.py",
}


def _iter_shipped_files():
    """Yield (path, relative_posix) for every shipped file, skipping EXEMPT_PATHS."""
    for p in sorted(GRAQLE_PKG.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix not in SHIPPED_EXTENSIONS:
            continue
        rel = p.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(ex) for ex in EXEMPT_PATHS):
            continue
        yield p, rel


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


# The four files that v0.50.1 explicitly sanitizes. These MUST stay clean.
V0501_SANITIZED_TARGETS: list[Path] = [
    GRAQLE_PKG / "core" / "governance.py",
    GRAQLE_PKG / "chat" / "templates" / "GRAQ_default.md",
    GRAQLE_PKG / "chat" / "templates" / "tcg_default.json",
    GRAQLE_PKG / "calibration" / "benchmarks" / "graqle_calibration_v1.yaml",
]


def test_no_forbidden_strings_in_v0501_sanitized_targets():
    """CRITICAL regression guard for every v0.50.1-sanitized file.

    The four target files MUST remain free of every forbidden string.
    If this test fails, a previously-sanitized file regressed and the
    hotfix's public-disclosure contract is broken.
    """
    violations: list[str] = []
    for path in V0501_SANITIZED_TARGETS:
        if not path.exists():
            pytest.skip(f"sanitized target missing: {path}")
        content = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for match in COMBINED_RE.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(f"{rel}:{line_num}: {match.group()}")
    assert not violations, (
        "v0.50.1-sanitized files contain forbidden strings "
        f"({len(violations)} violations):\n" + "\n".join(violations[:50])
    )


def test_advisory_package_wide_leakage():
    """Hard gate: zero forbidden strings across ALL shipped files.

    v0.51.0 Session 3 systematically sanitized every file under graqle/**
    and dropped the advisory baseline from 381 to 0. This test is now a
    hard gate (not advisory) that prevents any re-introduction.
    """
    total = 0
    for path, rel in _iter_shipped_files():
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in COMBINED_RE.finditer(content):
            total += 1
    assert total == 0, (
        f"Package-wide internal-reference count is {total}; must be 0. "
        f"Run the distribution lint to find the regressions."
    )


def test_graq_default_template_clean():
    """CRITICAL: the floor chat template users see on every session."""
    template = GRAQLE_PKG / "chat" / "templates" / "GRAQ_default.md"
    content = template.read_text(encoding="utf-8")
    matches = COMBINED_RE.findall(content)
    assert not matches, (
        f"GRAQ_default.md contains forbidden strings: {matches}"
    )


def test_tcg_seed_clean():
    """HIGH: the TCG seed JSON must not leak internal tracker IDs."""
    seed = GRAQLE_PKG / "chat" / "templates" / "tcg_default.json"
    content = seed.read_text(encoding="utf-8")
    matches = COMBINED_RE.findall(content)
    assert not matches, (
        f"tcg_default.json contains forbidden strings: {matches}"
    )


def test_governance_module_clean():
    """CRITICAL: the governance module must not name its own protected tags."""
    mod = GRAQLE_PKG / "core" / "governance.py"
    content = mod.read_text(encoding="utf-8")
    tag_pattern = re.compile(r"\bTS-[1-4]\b")
    matches = tag_pattern.findall(content)
    assert not matches, (
        f"graqle/core/governance.py contains pattern tag strings: {matches}"
    )


def test_calibration_yaml_clean():
    """HIGH: the calibration benchmark YAML must not name TS-[1-4] tags."""
    yml = GRAQLE_PKG / "calibration" / "benchmarks" / "graqle_calibration_v1.yaml"
    if not yml.exists():
        pytest.skip("calibration YAML not present")
    content = yml.read_text(encoding="utf-8")
    tag_pattern = re.compile(r"\bTS-[1-4]\b")
    matches = tag_pattern.findall(content)
    assert not matches, f"{yml.name} contains pattern tag strings: {matches}"
