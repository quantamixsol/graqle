"""CR-DIST-06: distribution manifests must not drift from the shipped version.

The defect this pins: three manifests carried a hand-maintained version string that
nothing updated. They reached ``0.80.0`` while PyPI served ``0.83.0`` — three releases
stale. Not a paywall leak (the plugins invoke ``graq`` from the user's own environment
and pin no version) but a listing that advertises a version we no longer ship.

``server.json`` was a subtler case: the registry workflow rewrote it *inside the CI
checkout* before publishing, so the published entry was always right while the file in
git stayed stale forever. Correct artifact, wrong repo — the two must now agree.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "sync_manifest_versions.py"

MANIFESTS = [
    ("server.json", ["version", "packages.0.version"]),
    ("plugins/claude-code/graqle/.claude-plugin/plugin.json", ["version"]),
    ("plugins/codex/graqle/.codex-plugin/plugin.json", ["version"]),
    (".claude-plugin/marketplace.json", ["plugins.0.version"]),
    (".agents/plugins/marketplace.json", ["plugins.0.version"]),
]


def _sdk_version() -> str:
    ns: dict = {}
    exec((ROOT / "graqle" / "__version__.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def _dig(obj, dotted: str):
    cur = obj
    for p in dotted.split("."):
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    return cur


@pytest.mark.parametrize("rel,keys", MANIFESTS, ids=[m[0] for m in MANIFESTS])
def test_manifest_matches_sdk_version(rel, keys):
    """Every manifest version must equal graqle.__version__.

    This is the guard that would have caught the 0.80.0 drift three releases earlier.
    """
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not present in this checkout")

    data = json.loads(path.read_text(encoding="utf-8"))
    expected = _sdk_version()
    for key in keys:
        assert _dig(data, key) == expected, (
            f"{rel}:{key} is {_dig(data, key)!r} but the SDK ships {expected!r}. "
            f"Run: python scripts/ci/sync_manifest_versions.py {expected}"
        )


def test_sync_script_check_mode_detects_drift(tmp_path):
    """--check must EXIT NON-ZERO on drift.

    A checker that cannot fail is decoration. Build a deliberately stale manifest and
    assert the script rejects it.
    """
    (tmp_path / "server.json").write_text(
        json.dumps({"version": "0.1.0", "packages": [{"version": "0.1.0"}]}, indent=2),
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "9.9.9", "--check", "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1, f"stale manifest passed --check (rc={r.returncode})\n{r.stdout}"
    assert "DRIFT" in r.stdout


def test_sync_script_writes_and_then_passes(tmp_path):
    """A sync makes --check pass, and touches only the version fields."""
    original = {
        "name": "io.github.quantamixsol/graqle",
        "version": "0.1.0",
        "packages": [{"registryType": "pypi", "identifier": "graqle", "version": "0.1.0"}],
    }
    p = tmp_path / "server.json"
    p.write_text(json.dumps(original, indent=2), encoding="utf-8")

    w = subprocess.run(
        [sys.executable, str(SCRIPT), "9.9.9", "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert w.returncode == 0, w.stderr

    after = json.loads(p.read_text(encoding="utf-8"))
    assert after["version"] == "9.9.9"
    assert after["packages"][0]["version"] == "9.9.9"
    # Non-version fields must survive untouched — a sync is not a rewrite.
    assert after["name"] == original["name"]
    assert after["packages"][0]["identifier"] == "graqle"

    c = subprocess.run(
        [sys.executable, str(SCRIPT), "9.9.9", "--check", "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert c.returncode == 0, c.stdout


def test_sync_script_rejects_malformed_version(tmp_path):
    """A bad version must never reach a public listing."""
    (tmp_path / "server.json").write_text(
        json.dumps({"version": "0.1.0", "packages": [{"version": "0.1.0"}]}), encoding="utf-8"
    )
    for bad in ("not-a-version", "1.2", "", "v1.2.3.4.5"):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), bad, "--root", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert r.returncode == 2, f"accepted malformed version {bad!r}"


def test_leading_v_is_stripped(tmp_path):
    """The workflow passes a git tag; 'v0.83.0' and '0.83.0' must behave identically."""
    p = tmp_path / "server.json"
    p.write_text(json.dumps({"version": "0.1.0", "packages": [{"version": "0.1.0"}]}),
                 encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "v9.9.9", "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(p.read_text(encoding="utf-8"))["version"] == "9.9.9"
