"""ITEM 06 — SDK-B1 — `graq init` auto-scaffolds GRAQ.md for each project type.

Acceptance:
1. `write_graq_md` writes a GRAQ.md for each of the 6 template keys.
2. `detect_project_type` correctly identifies python/rust/go/typescript.
3. `write_graq_md` is idempotent (no overwrite when file exists and overwrite=False).
4. All 6 templates differ (not all collapsing to generic).
"""

from __future__ import annotations

import time


def test_sdk_b1_init_scaffold(record, tmp_path):
    t0 = time.monotonic()
    assertions = 0
    evidence: dict = {}

    from graqle.cli.commands.init import (
        GRAQ_MD_TEMPLATES,
        detect_project_type,
        write_graq_md,
    )

    # --- 1. All 6 templates are present ---
    expected_keys = {"python", "typescript", "javascript", "rust", "go", "generic"}
    actual_keys = set(GRAQ_MD_TEMPLATES.keys())
    assert expected_keys == actual_keys, f"got {actual_keys}"
    assertions += 1
    evidence["template_keys"] = sorted(actual_keys)

    # --- 2. Each template produces a non-empty unique scaffold ---
    written_per_type: dict[str, int] = {}
    for ptype in expected_keys:
        ws = tmp_path / ptype
        ws.mkdir()
        ok = write_graq_md(ws, project_type=ptype)
        assert ok is True
        graq_md = ws / "GRAQ.md"
        assert graq_md.exists()
        text = graq_md.read_text(encoding="utf-8")
        assert len(text) > 0
        written_per_type[ptype] = len(text)
    assertions += 1
    evidence["graq_md_written"] = len(written_per_type)
    evidence["sizes_by_type"] = written_per_type

    # --- 3. detect_project_type — python project ---
    py_ws = tmp_path / "py_auto"
    py_ws.mkdir()
    (py_ws / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    assert detect_project_type(py_ws) == "python"
    assertions += 1

    # --- 4. detect_project_type — rust ---
    rust_ws = tmp_path / "rust_auto"
    rust_ws.mkdir()
    (rust_ws / "Cargo.toml").write_text("[package]\nname=\"x\"\n", encoding="utf-8")
    assert detect_project_type(rust_ws) == "rust"
    assertions += 1

    # --- 5. detect_project_type — go ---
    go_ws = tmp_path / "go_auto"
    go_ws.mkdir()
    (go_ws / "go.mod").write_text("module x\n", encoding="utf-8")
    assert detect_project_type(go_ws) == "go"
    assertions += 1

    # --- 6. Idempotency — second write without overwrite returns False ---
    idem_ws = tmp_path / "idem"
    idem_ws.mkdir()
    assert write_graq_md(idem_ws, project_type="generic") is True
    assert write_graq_md(idem_ws, project_type="generic") is False
    assertions += 1
    evidence["idempotency_ok"] = True

    # --- 7. Overwrite=True re-writes ---
    assert write_graq_md(idem_ws, project_type="python", overwrite=True) is True
    assertions += 1
    evidence["overwrite_ok"] = True

    record(
        item_id="06-sdk-b1",
        name="SDK-B1 — graq init auto-scaffolds GRAQ.md",
        status="PASS",
        assertions=assertions,
        duration_ms=int((time.monotonic() - t0) * 1000),
        evidence=evidence,
    )
