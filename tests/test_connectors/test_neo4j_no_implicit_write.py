"""T01 (v0.51.6) — Graqle.from_neo4j must not write to disk by default.

Acceptance criteria for the read-only from_neo4j contract:
- Default call creates ZERO files in cwd
- No UserWarning emitted on default path
- mirror_to=<path> with file present and mirror_overwrite=False raises FileExistsError
- mirror_to="" raises ValueError
- mirror_overwrite=True allows overwrite
"""
from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from graqle.core.graph import Graqle


def _mock_neo4j_module():
    """Build a minimal mock neo4j driver returning a tiny 2-node graph."""
    mock_module = MagicMock()
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__ = lambda self: mock_session
    mock_driver.session.return_value.__exit__ = lambda *a: None
    mock_module.GraphDatabase.driver.return_value = mock_driver

    # Mock the Cypher results that Neo4jConnector.load() consumes
    def _run(query, **kwargs):
        result = MagicMock()
        if "MATCH (n)" in query and "RETURN" in query and "id" in query.lower():
            # Node fetch
            n1 = MagicMock(); n1.__getitem__ = lambda s, k: {"id": "a", "label": "A", "type": "Entity"}.get(k)
            n1.get = lambda k, d=None: {"id": "a", "label": "A", "type": "Entity"}.get(k, d)
            result.__iter__ = lambda s: iter([])  # no nodes for the no-write test
        else:
            result.__iter__ = lambda s: iter([])
        result.single.return_value = None
        return result

    mock_session.run.side_effect = _run
    return mock_module, mock_driver


def _patched_neo4j_load(monkeypatch):
    """Stub Neo4jConnector.load + load_chunks so we don't need a live DB."""
    from graqle.connectors import neo4j as neo4j_mod

    monkeypatch.setattr(
        neo4j_mod.Neo4jConnector,
        "__init__",
        lambda self, **kw: None,
    )
    monkeypatch.setattr(
        neo4j_mod.Neo4jConnector,
        "load",
        lambda self: ({}, {}),
    )
    monkeypatch.setattr(
        neo4j_mod.Neo4jConnector,
        "load_chunks",
        lambda self: {},
    )


class TestFromNeo4jWritesZeroFilesByDefault:
    """The headline T01 acceptance: default from_neo4j is read-only."""

    def test_default_call_creates_no_files(self, tmp_path: Path, monkeypatch):
        """The whole point of T01: zero new files on disk after a default call."""
        _patched_neo4j_load(monkeypatch)
        monkeypatch.chdir(tmp_path)

        before = sorted(p.name for p in tmp_path.iterdir())
        Graqle.from_neo4j(uri="bolt://stub:7687")  # no mirror_to passed
        after = sorted(p.name for p in tmp_path.iterdir())

        assert before == after, (
            f"from_neo4j wrote files to cwd! Before={before} After={after}. "
            f"T01 (v0.51.6) requires zero implicit writes."
        )

    def test_default_call_emits_no_user_warning(self, tmp_path: Path, monkeypatch):
        """The pre-T01 'graqle.json is STALE' UserWarning must be gone."""
        _patched_neo4j_load(monkeypatch)
        monkeypatch.chdir(tmp_path)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Graqle.from_neo4j(uri="bolt://stub:7687")

        stale_warnings = [w for w in caught if "STALE" in str(w.message)]
        assert not stale_warnings, (
            f"from_neo4j emitted STALE warning on default path: {stale_warnings}"
        )


class TestFromNeo4jOptInMirror:
    """Explicit mirror_to= still works (just opt-in instead of opt-out)."""

    def test_explicit_mirror_to_writes_file(self, tmp_path: Path, monkeypatch):
        _patched_neo4j_load(monkeypatch)
        target = tmp_path / "snapshot.json"

        Graqle.from_neo4j(uri="bolt://stub:7687", mirror_to=str(target))

        assert target.exists(), "explicit mirror_to should still write"

    def test_existing_file_without_overwrite_raises(self, tmp_path: Path, monkeypatch):
        _patched_neo4j_load(monkeypatch)
        target = tmp_path / "existing.json"
        target.write_text("{}", encoding="utf-8")

        with pytest.raises(FileExistsError, match="mirror_overwrite=True"):
            Graqle.from_neo4j(uri="bolt://stub:7687", mirror_to=str(target))

    def test_existing_file_with_overwrite_succeeds(self, tmp_path: Path, monkeypatch):
        _patched_neo4j_load(monkeypatch)
        target = tmp_path / "existing.json"
        target.write_text("{}", encoding="utf-8")
        original_mtime = target.stat().st_mtime

        Graqle.from_neo4j(
            uri="bolt://stub:7687",
            mirror_to=str(target),
            mirror_overwrite=True,
        )

        assert target.exists()
        # File was rewritten, content is now a graph snapshot, not "{}"
        assert target.read_text(encoding="utf-8") != "{}"

    def test_empty_string_mirror_to_raises(self, tmp_path: Path, monkeypatch):
        """mirror_to='' is the dangerous Path('') = cwd footgun. Must raise."""
        _patched_neo4j_load(monkeypatch)
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError, match="non-empty path"):
            Graqle.from_neo4j(uri="bolt://stub:7687", mirror_to="")
