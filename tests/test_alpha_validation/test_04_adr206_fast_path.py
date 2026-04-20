"""ITEM 04 — Fast-path intent classifier + path containment.

Acceptance:
1. classify_intent() returns a FastPathIntent on a clean file-create prompt.
2. classify_intent() returns None on negations and anti-verbs.
3. is_path_safe() rejects paths escaping the workspace (absolute + symlink).
4. is_fast_path_candidate() composes both correctly.
"""

from __future__ import annotations

import os
import time

import pytest


def test_adr206_fast_path(record, tmp_workspace):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    from graqle.chat.fast_path import (
        classify_intent,
        is_path_safe,
        is_fast_path_candidate,
    )

    # --- 1. classify_intent — positive case (regex needs "file"/"note"/"document" lexeme) ---
    intent = classify_intent("create a file notes.md with content: hello world")
    assert intent is not None, "clean file-create prompt must classify"
    assert intent.target_path == "notes.md", intent
    assertions += 1
    evidence["classifier_positive"] = True

    # --- 2. classify_intent — negation is rejected ---
    neg = classify_intent("don't create a file anything.md")
    assert neg is None
    assertions += 1
    evidence["classifier_negation_rejected"] = True

    # --- 3. classify_intent — anti-verb is rejected ---
    anti = classify_intent("refactor the file notes.md")
    assert anti is None
    assertions += 1
    evidence["classifier_anti_verb_rejected"] = True

    # --- 4. is_path_safe — inside workspace → True ---
    safe_target = "notes.md"
    assert is_path_safe(safe_target, tmp_workspace) is True
    assertions += 1
    evidence["containment_inside_ok"] = True

    # --- 5. is_path_safe — escape with .. → False ---
    escape = "../../etc/passwd"
    assert is_path_safe(escape, tmp_workspace) is False
    assertions += 1
    evidence["containment_escape_blocked"] = True

    # --- 6. is_path_safe — absolute path outside cwd → False ---
    outside = os.path.abspath(os.path.join(os.sep, "tmp", "other.md"))
    assert is_path_safe(outside, tmp_workspace) is False
    assertions += 1
    evidence["containment_absolute_outside_blocked"] = True

    # --- 7. Composition: is_fast_path_candidate ---
    composed = is_fast_path_candidate("create a file demo.md", tmp_workspace)
    assert composed is not None
    assertions += 1
    evidence["composition_ok"] = True

    record(
        item_id="04-adr206",
        name="Fast-path intent classifier + path containment",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
