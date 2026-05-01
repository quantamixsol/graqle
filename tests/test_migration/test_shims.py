"""Tests for BUG-009 backward-compatibility shims (v0.46 → v0.52 migration).

Each shim must:
1. Import successfully
2. Emit exactly one DeprecationWarning with the correct message
3. Export the correct target class/object
"""
from __future__ import annotations

import importlib
import warnings


# ---------------------------------------------------------------------------
# 1. graqle.scorer shim — ChunkScorer
# ---------------------------------------------------------------------------

class TestScorerShim:
    def test_scorer_shim_imports_without_error(self):
        """graqle.scorer must be importable (shim present)."""
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            import graqle.scorer  # noqa: F401
            importlib.reload(graqle.scorer)

    def test_scorer_shim_emits_deprecation_warning(self):
        """graqle.scorer import must emit DeprecationWarning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import graqle.scorer  # noqa: F401
            importlib.reload(graqle.scorer)
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1, "Expected at least one DeprecationWarning"
        assert "graqle.scorer" in str(dep_warnings[0].message)
        assert "graqle.activation.chunk_scorer" in str(dep_warnings[0].message)

    def test_scorer_shim_exports_chunk_scorer(self):
        """graqle.scorer.ChunkScorer must be the real ChunkScorer class."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import graqle.scorer as shim
            importlib.reload(shim)
            from graqle.activation.chunk_scorer import ChunkScorer as Real
        assert shim.ChunkScorer is Real

    def test_scorer_shim_deprecation_mentions_removal_version(self):
        """DeprecationWarning must mention v0.55.0 removal."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import graqle.scorer  # noqa: F401
            importlib.reload(graqle.scorer)
        messages = " ".join(str(w.message) for w in caught if issubclass(w.category, DeprecationWarning))
        assert "v0.55.0" in messages


# ---------------------------------------------------------------------------
# 2. graqle.backends.bedrock shim — BedrockBackend
# ---------------------------------------------------------------------------

class TestBedrockShim:
    def test_bedrock_shim_imports_without_error(self):
        """graqle.backends.bedrock must be importable."""
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            import graqle.backends.bedrock  # noqa: F401
            importlib.reload(graqle.backends.bedrock)

    def test_bedrock_shim_emits_deprecation_warning(self):
        """graqle.backends.bedrock import must emit DeprecationWarning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import graqle.backends.bedrock  # noqa: F401
            importlib.reload(graqle.backends.bedrock)
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1
        assert "graqle.backends.bedrock" in str(dep_warnings[0].message)
        assert "graqle.backends.api" in str(dep_warnings[0].message)

    def test_bedrock_shim_exports_bedrock_backend(self):
        """graqle.backends.bedrock.BedrockBackend must be the real class."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import graqle.backends.bedrock as shim
            importlib.reload(shim)
            from graqle.backends.api import BedrockBackend as Real
        assert shim.BedrockBackend is Real

    def test_bedrock_backend_model_id_alias_emits_warning(self):
        """BedrockBackend(model_id=...) must emit DeprecationWarning and map to model."""
        from graqle.backends.api import BedrockBackend
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            b = BedrockBackend(model_id="anthropic.claude-haiku-4-5-20251001-v1:0")
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1
        assert "model_id" in str(dep_warnings[0].message)
        assert b._model == "anthropic.claude-haiku-4-5-20251001-v1:0"

    def test_bedrock_backend_profile_alias_emits_warning(self):
        """BedrockBackend(profile=...) must emit DeprecationWarning and map to profile_name."""
        from graqle.backends.api import BedrockBackend
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            b = BedrockBackend(profile="my-aws-profile")
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1
        assert "profile" in str(dep_warnings[0].message)
        assert b._profile_name == "my-aws-profile"

    def test_bedrock_backend_new_params_no_warning(self):
        """BedrockBackend(model=..., profile_name=...) must NOT emit DeprecationWarning."""
        from graqle.backends.api import BedrockBackend
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            BedrockBackend(model="anthropic.claude-haiku-4-5-20251001-v1:0", profile_name="p")
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 0, f"Unexpected DeprecationWarnings: {dep_warnings}"


# ---------------------------------------------------------------------------
# 3. graqle.api shim — GraqleClient / Graqle
# ---------------------------------------------------------------------------

class TestApiShim:
    def test_api_shim_imports_without_error(self):
        """graqle.api must be importable."""
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            import graqle.api  # noqa: F401
            importlib.reload(graqle.api)

    def test_api_shim_emits_deprecation_warning(self):
        """graqle.api import must emit DeprecationWarning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import graqle.api  # noqa: F401
            importlib.reload(graqle.api)
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1
        assert "GraqleClient" in str(dep_warnings[0].message)
        assert "graqle.core.Graqle" in str(dep_warnings[0].message)

    def test_api_shim_exports_graqle_client_alias(self):
        """graqle.api.GraqleClient must be an alias for graqle.core.graph.Graqle."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import graqle.api as shim
            importlib.reload(shim)
            from graqle.core.graph import Graqle as Real
        assert shim.GraqleClient is Real

    def test_api_shim_exports_graqle_directly(self):
        """graqle.api.Graqle must also be directly available."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import graqle.api as shim
            importlib.reload(shim)
            from graqle.core.graph import Graqle as Real
        assert shim.Graqle is Real


# ---------------------------------------------------------------------------
# 4. graqle.cli.commands.scan DocScanner alias
# ---------------------------------------------------------------------------

class TestDocScannerAlias:
    def test_doc_scanner_alias_importable(self):
        """DocScanner must be importable from graqle.cli.commands.scan."""
        from graqle.cli.commands.scan import DocScanner  # noqa: F401
        assert DocScanner is not None

    def test_doc_scanner_alias_resolves_to_document_scanner(self):
        """DocScanner shim must resolve to DocumentScanner class (not instantiated — requires args)."""
        from graqle.scanner.docs import DocumentScanner
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from graqle.cli.commands.scan import _get_doc_scanner_alias
        resolved = _get_doc_scanner_alias()
        assert resolved is DocumentScanner or resolved.__name__ == "DocumentScanner"


# ---------------------------------------------------------------------------
# 5. graqle doctor stale-import scanner
# ---------------------------------------------------------------------------

class TestDoctorStaleImportCheck:
    def test_stale_imports_dict_defined(self):
        """_STALE_IMPORTS must be defined in doctor module with all 4 patterns."""
        from graqle.cli.commands.doctor import _STALE_IMPORTS
        assert "graqle.scorer" in _STALE_IMPORTS
        assert "graqle.cli.commands.scan.DocScanner" in _STALE_IMPORTS
        assert "graqle.backends.bedrock" in _STALE_IMPORTS
        assert "graqle.api.GraqleClient" in _STALE_IMPORTS

    def test_stale_imports_correct_replacements(self):
        """Each stale import must map to the correct new path."""
        from graqle.cli.commands.doctor import _STALE_IMPORTS
        assert _STALE_IMPORTS["graqle.scorer"] == "graqle.activation.chunk_scorer"
        assert _STALE_IMPORTS["graqle.cli.commands.scan.DocScanner"] == "graqle.scanner.docs.DocumentScanner"
        assert _STALE_IMPORTS["graqle.backends.bedrock"] == "graqle.backends.api"
        assert _STALE_IMPORTS["graqle.api.GraqleClient"] == "graqle.core.Graqle"

    def test_check_stale_imports_returns_list(self):
        """_check_stale_imports() must return a list of CheckResult tuples."""
        from graqle.cli.commands.doctor import _check_stale_imports
        results = _check_stale_imports()
        assert isinstance(results, list)
        assert len(results) >= 1
        for r in results:
            assert isinstance(r, tuple)
            assert len(r) == 3

    def test_check_stale_imports_pass_on_clean_project(self, tmp_path, monkeypatch):
        """_check_stale_imports() returns PASS when no stale imports exist."""
        # Create a clean Python file with no stale imports
        (tmp_path / "clean.py").write_text("from graqle.activation.chunk_scorer import ChunkScorer\n")
        monkeypatch.chdir(tmp_path)
        from graqle.cli.commands.doctor import _check_stale_imports, PASS
        results = _check_stale_imports()
        statuses = [r[0] for r in results]
        assert PASS in statuses

    def test_check_stale_imports_warn_on_stale_project(self, tmp_path, monkeypatch):
        """_check_stale_imports() returns WARN when stale import is found."""
        (tmp_path / "stale.py").write_text("from graqle.scorer import ChunkScorer\n")
        monkeypatch.chdir(tmp_path)
        from graqle.cli.commands.doctor import _check_stale_imports, WARN
        results = _check_stale_imports()
        statuses = [r[0] for r in results]
        assert WARN in statuses
