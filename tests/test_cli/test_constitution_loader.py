"""P1 (ADR-222): tests for the constitution single-source-of-truth loader.

The governance constitution lives as ordered .md fragments under
``graqle/data/constitution/`` and is assembled by
``graqle.cli.commands.init._load_constitution``. These tests assert:

1. The loader returns the assembled package-data text (NOT the fallback).
2. Every required section is present (core, tools, workflows, cost,
   workarounds, EU AI Act).
3. Fragments are concatenated in sorted filename order.
4. The loader degrades to ``_FALLBACK_INSTRUCTIONS`` on any failure.
5. ``AI_INSTRUCTIONS_SECTION`` is wired to the loader output.
"""

from __future__ import annotations

from graqle.cli.commands import init as init_mod


# Each marker must be UNIQUE to its fragment so first-occurrence position
# reflects true fragment order. (Note: the phrase "EU AI Act" also appears in
# 10-tools' compliance row, so the 50- fragment is keyed on its config block.)
REQUIRED_MARKERS = [
    "senior developer",        # 00-core
    "tool inventory",          # 10-tools
    "Governed workflows",      # 20-workflows
    "Cost-optimisation",       # 30-cost
    "Known workarounds",       # 40-workarounds
    "eu_ai_act:",              # 50-eu-ai-act (unique config key)
]


def test_loader_returns_package_data_not_fallback() -> None:
    text = init_mod._load_constitution()
    assert text
    assert text != init_mod._FALLBACK_INSTRUCTIONS
    # Comprehensive rulebook is substantial.
    assert len(text) > 5000


def test_loader_contains_all_required_sections() -> None:
    text = init_mod._load_constitution()
    for marker in REQUIRED_MARKERS:
        assert marker in text, f"missing constitution section: {marker!r}"


def test_fragments_assembled_in_sorted_order() -> None:
    text = init_mod._load_constitution()
    # core (00) precedes tools (10) precedes workflows (20) precedes eu-ai-act (50)
    positions = [text.index(m) for m in REQUIRED_MARKERS]
    assert positions == sorted(positions), "fragments not in NN- sorted order"


def test_public_section_is_wired_to_loader() -> None:
    assert init_mod.AI_INSTRUCTIONS_SECTION == init_mod._load_constitution()
    # Backward-compat alias preserved.
    assert init_mod.CLAUDE_MD_SECTION == init_mod.AI_INSTRUCTIONS_SECTION


def test_loader_falls_back_when_package_missing(monkeypatch) -> None:
    # Force resources.files to raise -> loader must return the fallback,
    # never crash, so a stripped wheel still lets `graq init` run.
    import importlib.resources as _res

    def _boom(_pkg):
        raise ModuleNotFoundError("simulated stripped wheel")

    monkeypatch.setattr(_res, "files", _boom)
    text = init_mod._load_constitution()
    assert text == init_mod._FALLBACK_INSTRUCTIONS


def test_loader_falls_back_when_no_fragments(monkeypatch, tmp_path) -> None:
    # An empty constitution dir (no .md) -> fallback, not an empty string.
    import importlib.resources as _res

    monkeypatch.setattr(_res, "files", lambda _pkg: tmp_path)
    text = init_mod._load_constitution()
    assert text == init_mod._FALLBACK_INSTRUCTIONS
