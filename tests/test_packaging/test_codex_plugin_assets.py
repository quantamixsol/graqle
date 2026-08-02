"""CR-DIST-06: every asset a directory listing references must actually exist.

`plugin.json` declares a logo and screenshots by relative path. Nothing verified those
paths resolved, so a typo — or a screenshot referenced before the file was added — would
ship a manifest pointing at nothing. A directory reviewer fetching a 404 image is a
rejection, and it is invisible until someone else looks.

`screenshots` is allowed to be EMPTY (assets not supplied yet) but every entry that IS
listed must resolve to a real file. That distinction is deliberate: it lets the paths be
wired ahead of the images without the guard producing a false failure, while still
catching the case the guard exists for.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

PLUGINS = [
    "plugins/codex/graqle/.codex-plugin/plugin.json",
    "plugins/claude-code/graqle/.claude-plugin/plugin.json",
]


def _manifests():
    for rel in PLUGINS:
        p = ROOT / rel
        if p.exists():
            yield rel, p, json.loads(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("rel", PLUGINS)
def test_manifest_parses(rel):
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    json.loads(path.read_text(encoding="utf-8"))


def test_referenced_assets_exist():
    """Logo and every listed screenshot must resolve, relative to the plugin dir."""
    checked = 0
    for rel, path, data in _manifests():
        # Structure (verified identical for both plugins):
        #   plugins/<channel>/graqle/.<channel>-plugin/plugin.json
        #   plugins/<channel>/graqle/assets/...
        # so the asset root is two levels up from the manifest.
        base = path.parent.parent
        iface = data.get("interface", {})

        logo = iface.get("logo")
        if logo:
            assert (base / logo).exists(), (
                f"{rel}: interface.logo -> {logo!r} does not exist at {base / logo}. "
                "A directory reviewer would fetch a 404."
            )
            checked += 1

        for shot in iface.get("screenshots", []):
            # Accept either a bare path or an object carrying one, so the guard keeps
            # working if the schema shape changes.
            candidate = shot if isinstance(shot, str) else shot.get("path", "")
            assert candidate, f"{rel}: a screenshot entry has no path: {shot!r}"
            assert (base / candidate).exists(), (
                f"{rel}: screenshot -> {candidate!r} is referenced but missing at "
                f"{base / candidate}. Add the file or remove the entry — never ship a "
                "manifest pointing at an image that does not exist."
            )
            checked += 1

    if checked == 0:
        # SKIP, not fail. A sparse checkout without plugins/ is a legitimate
        # environment, not a defect, and failing there produces a cryptic red CI for a
        # reason unrelated to the code. Skipping keeps the signal honest: this test
        # reports on assets it can see, and says plainly when it can see none.
        pytest.skip("no plugin manifests found — plugins/ not checked out")


def test_screenshots_populated_before_submission():
    """Guards the gap that allowing ``screenshots: []`` creates.

    An empty list is correct during development, but a submission with zero screenshots
    would sail past every other check here and only be caught by a human reviewer —
    i.e. a rejection. This test is SKIPPED by default and armed by setting
    ``GRAQLE_SUBMISSION_CHECK=1`` immediately before packaging a directory submission.

    It is deliberately not always-on: failing it today would make the whole suite red
    for an asset that is legitimately still being produced.
    """
    if not os.environ.get("GRAQLE_SUBMISSION_CHECK"):
        pytest.skip("set GRAQLE_SUBMISSION_CHECK=1 to arm the pre-submission gate")

    for rel, _path, data in _manifests():
        shots = data.get("interface", {}).get("screenshots", [])
        assert shots, (
            f"{rel}: interface.screenshots is empty. A directory submission needs "
            "screenshots — see plugins/codex/graqle/assets/README.md for the three "
            "required images and their specs."
        )


def test_screenshot_files_are_real_pngs():
    """A .png that is not a PNG fails silently in a directory listing."""
    png_magic = b"\x89PNG\r\n\x1a\n"
    for rel, path, data in _manifests():
        base = path.parent.parent
        iface = data.get("interface", {})
        refs = [iface["logo"]] if iface.get("logo") else []
        refs += [s if isinstance(s, str) else s.get("path", "")
                 for s in iface.get("screenshots", [])]

        for ref in refs:
            f = base / ref
            if not f.exists() or not ref.lower().endswith(".png"):
                continue
            assert f.read_bytes()[:8] == png_magic, (
                f"{rel}: {ref} has a .png extension but is not a PNG file."
            )
