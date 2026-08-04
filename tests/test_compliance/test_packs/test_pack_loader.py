"""Tests for graqle.compliance.packs (CR-010.R3).

Covers the data-driven pack loader: happy path, the fail-closed posture on
every malformation, and AC-3 — that a framework pack is authorable as
schema + YAML with no Python and no engine change.
"""

from __future__ import annotations

import json
import shutil

import pytest
import yaml

from graqle.compliance.claim_limits.taxonomy import is_valid_claim_limit
from graqle.compliance.packs import (
    CompliancePack,
    CompliancePackError,
    discover_packs,
    load_all_packs,
    load_pack,
)
from graqle.compliance.packs import _loader


class TestShippedSoxPack:
    def test_x_sox_is_discoverable(self):
        assert "x_sox" in discover_packs()

    def test_loads(self):
        pack = load_pack("x_sox")
        assert isinstance(pack, CompliancePack)
        assert pack.namespace == "x-sox"
        assert pack.pack_version == "1.0"
        assert "Sarbanes-Oxley" in pack.framework

    def test_declares_required_control_fields(self):
        pack = load_pack("x_sox")
        for required in (
            "control_id",
            "assertion",
            "reporting_period_start",
            "reporting_period_end",
            "management_review_status",
        ):
            assert required in pack.fields, required

    def test_qualify_matches_extension_emit_shape(self):
        assert load_pack("x_sox").qualify("control_id") == "x-sox:control_id"

    def test_load_all_keys_by_namespace(self):
        assert "x-sox" in load_all_packs()

    def test_pseudonym_fields_declare_pii_classification(self):
        # An offline auditor must be able to tell a pseudonymous field from a
        # plain string without holding the operator's identity mapping.
        pack = load_pack("x_sox")
        for name in ("preparer_token", "reviewer_token"):
            assert pack.fields[name]["pii_classification"] == "pseudonymous"


class TestClaimLimitIntegration:
    """The load-bearing fact behind AC-3: no taxonomy edit is needed."""

    def test_pack_claim_limits_pass_existing_taxonomy_unmodified(self):
        pack = load_pack("x_sox")
        assert pack.claim_limits, "pack contributes no claim limits"
        for value in pack.claim_limits:
            assert is_valid_claim_limit(value), value


@pytest.fixture()
def temp_pack_root(tmp_path, monkeypatch):
    """Point the loader at a temporary packs root.

    Lets the negative cases build deliberately-broken packs without writing
    into the installed package.
    """
    monkeypatch.setattr(_loader, "_packs_root", lambda: tmp_path)
    return tmp_path


def _write_pack(root, name, manifest, schema=None):
    """Write a pack dir; defaults to the real x-sox schema."""
    pack_dir = root / name
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.yaml").write_text(
        yaml.safe_dump(manifest), encoding="utf-8"
    )
    if schema is None:
        real = _loader._packs_root  # noqa: SLF001 — restored real root below
        del real
        from importlib.resources import files as _files

        src = _files("graqle.compliance.packs") / "x_sox" / "schema.json"
        schema_text = src.read_text(encoding="utf-8")
    else:
        schema_text = json.dumps(schema)
    (pack_dir / "schema.json").write_text(schema_text, encoding="utf-8")
    return pack_dir


def _valid_manifest(**overrides):
    # Deliberately NOT a reserved namespace: x-sox and x-ai-eu are reserved
    # for their first-party owners, so fixtures use a neutral test namespace.
    manifest = {
        "namespace": "x-testpack",
        "pack_version": "1.0",
        "framework": "Test framework",
        "fields": {
            "control_id": {"type": "string", "required": True},
            "assertion": {
                "type": "enum",
                "required": True,
                "values": ["existence"],
            },
            "reporting_period_start": {"type": "date", "required": True},
            "reporting_period_end": {"type": "date", "required": True},
            "management_review_status": {
                "type": "enum",
                "required": True,
                "values": ["not_required"],
            },
        },
    }
    manifest.update(overrides)
    return manifest


class TestAuthorableAsDataOnly:
    """AC-3: a pack is loadable from data alone — no Python, no engine change."""

    def test_pack_created_only_from_data_files_loads(self, temp_pack_root):
        # Written as data alone — no Python, no engine change.
        schema = {
            "type": "object",
            "required": ["namespace", "pack_version", "framework", "fields"],
            "properties": {"pack_version": {"type": "string"}},
        }
        _write_pack(temp_pack_root, "x_demo", _valid_manifest(), schema=schema)
        pack = load_pack("x_demo")
        assert pack.namespace == "x-testpack"
        assert pack.fields["control_id"]["required"] is True

    def test_new_namespace_needs_no_taxonomy_edit(self, temp_pack_root):
        manifest = _valid_manifest(
            namespace="x-nist-ai-rmf",
            claim_limits=["x-nist-govern-1-1"],
        )
        schema = {
            "type": "object",
            "required": ["namespace", "pack_version", "framework", "fields"],
            "properties": {"namespace": {"type": "string"}},
        }
        _write_pack(temp_pack_root, "x_nist", manifest, schema=schema)
        pack = load_pack("x_nist")
        assert pack.namespace == "x-nist-ai-rmf"
        assert is_valid_claim_limit("x-nist-govern-1-1")


class TestFailClosed:
    """A malformed pack raises. It is never skipped with a warning."""

    def test_missing_pack_raises(self, temp_pack_root):
        with pytest.raises(CompliancePackError, match="not found"):
            load_pack("does_not_exist")

    def test_missing_schema_file_raises(self, temp_pack_root):
        pack_dir = temp_pack_root / "x_broken"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            yaml.safe_dump(_valid_manifest()), encoding="utf-8"
        )
        with pytest.raises(CompliancePackError, match="incomplete|schema.json"):
            load_pack("x_broken")

    def test_missing_manifest_file_raises(self, temp_pack_root):
        pack_dir = temp_pack_root / "x_broken"
        pack_dir.mkdir()
        (pack_dir / "schema.json").write_text("{}", encoding="utf-8")
        with pytest.raises(CompliancePackError, match="not found|incomplete"):
            load_pack("x_broken")

    def test_malformed_yaml_raises(self, temp_pack_root):
        pack_dir = temp_pack_root / "x_broken"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            "namespace: [unclosed\n", encoding="utf-8"
        )
        (pack_dir / "schema.json").write_text("{}", encoding="utf-8")
        with pytest.raises(CompliancePackError, match="not valid YAML"):
            load_pack("x_broken")

    def test_malformed_json_schema_raises(self, temp_pack_root):
        pack_dir = temp_pack_root / "x_broken"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            yaml.safe_dump(_valid_manifest()), encoding="utf-8"
        )
        (pack_dir / "schema.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(CompliancePackError, match="not valid JSON"):
            load_pack("x_broken")

    def test_yaml_scalar_top_level_raises(self, temp_pack_root):
        pack_dir = temp_pack_root / "x_broken"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text("just a string\n", encoding="utf-8")
        (pack_dir / "schema.json").write_text("{}", encoding="utf-8")
        with pytest.raises(CompliancePackError, match="mapping"):
            load_pack("x_broken")

    @pytest.mark.parametrize("missing", ["namespace", "pack_version", "framework"])
    def test_missing_required_key_raises(self, temp_pack_root, missing):
        manifest = _valid_manifest()
        del manifest[missing]
        schema = {"type": "object"}
        _write_pack(temp_pack_root, "x_broken", manifest, schema=schema)
        with pytest.raises(CompliancePackError, match="missing required key"):
            load_pack("x_broken")

    @pytest.mark.parametrize(
        "bad_ns",
        [
            "X-SOX",            # uppercase
            "sox",              # no x- prefix
            "x-",               # prefix only
            "x-" + "a" * 65,    # over the 64-char limit
            "x-sox!",           # illegal char
            "x-sox space",      # space
        ],
    )
    def test_invalid_namespace_raises(self, temp_pack_root, bad_ns):
        manifest = _valid_manifest(namespace=bad_ns)
        schema = {"type": "object"}
        _write_pack(temp_pack_root, "x_broken", manifest, schema=schema)
        with pytest.raises(CompliancePackError, match="not a valid extension namespace"):
            load_pack("x_broken")

    def test_manifest_violating_own_schema_raises(self, temp_pack_root):
        # The check proof-spec v1.0 structurally cannot perform (SPEC.md 8.1).
        manifest = _valid_manifest(pack_version="not-a-version")
        _write_pack(temp_pack_root, "x_broken", manifest)
        with pytest.raises(CompliancePackError, match="does not validate"):
            load_pack("x_broken")

    def test_invalid_schema_raises(self, temp_pack_root):
        manifest = _valid_manifest()
        _write_pack(
            temp_pack_root,
            "x_broken",
            manifest,
            schema={"type": "not-a-real-type"},
        )
        with pytest.raises(CompliancePackError, match="not a valid JSON Schema"):
            load_pack("x_broken")

    def test_invalid_claim_limit_raises(self, temp_pack_root):
        manifest = _valid_manifest(claim_limits=["not_x_prefixed"])
        schema = {"type": "object"}
        _write_pack(temp_pack_root, "x_broken", manifest, schema=schema)
        with pytest.raises(CompliancePackError, match="invalid claim_limits"):
            load_pack("x_broken")

    def test_claim_limits_wrong_type_raises(self, temp_pack_root):
        manifest = _valid_manifest(claim_limits="x-sox-oops")
        schema = {"type": "object"}
        _write_pack(temp_pack_root, "x_broken", manifest, schema=schema)
        with pytest.raises(CompliancePackError, match="claim_limits must be a list"):
            load_pack("x_broken")

    @pytest.mark.parametrize("reserved", ["x-ai-eu", "x-sox"])
    def test_reserved_namespace_cannot_be_shadowed(self, temp_pack_root, reserved):
        """Sentinel F-5 (CONFIRMED): x-ai-eu is a well-formed x- namespace.

        The extension regex alone does not protect first-party vocabularies,
        so an operator pack could otherwise declare namespace: x-ai-eu and
        silently replace the EU AI Act definitions compliance reporting reads.
        """
        manifest = _valid_manifest(namespace=reserved)
        schema = {"type": "object"}
        _write_pack(temp_pack_root, "x_impostor", manifest, schema=schema)
        with pytest.raises(CompliancePackError, match="RESERVED"):
            load_pack("x_impostor")

    def test_owning_pack_may_declare_its_reserved_namespace(self, temp_pack_root):
        # x_sox owns x-sox — the reservation must not lock out the owner.
        manifest = _valid_manifest(namespace="x-sox")
        schema = {"type": "object"}
        _write_pack(temp_pack_root, "x_sox", manifest, schema=schema)
        assert load_pack("x_sox").namespace == "x-sox"

    def test_shipped_sox_pack_still_loads_under_reservation(self):
        # Guards against the reservation breaking the real packaged pack.
        assert load_pack("x_sox").namespace == "x-sox"

    def test_duplicate_namespace_raises(self, temp_pack_root):
        schema = {"type": "object"}
        _write_pack(temp_pack_root, "x_one", _valid_manifest(), schema=schema)
        _write_pack(temp_pack_root, "x_two", _valid_manifest(), schema=schema)
        with pytest.raises(CompliancePackError, match="duplicate"):
            load_all_packs()

    def test_directory_without_manifest_is_not_a_pack(self, temp_pack_root):
        (temp_pack_root / "__pycache__").mkdir()
        assert "__pycache__" not in discover_packs()


class TestEncodingRobustness:
    """graq_predict chain 5 (CONFIRMED): a UTF-8 BOM is fatal to json.loads.

    yaml.safe_load tolerates a BOM but json.loads raises
    "Unexpected UTF-8 BOM", so a schema.json saved by a Windows editor would
    fail as "not valid JSON" while its pack.yaml sibling loaded fine.
    """

    def test_bom_in_both_files_is_tolerated(self, temp_pack_root):
        pack_dir = temp_pack_root / "x_bom"
        pack_dir.mkdir()
        manifest = yaml.safe_dump(_valid_manifest())
        schema = json.dumps({"type": "object"})
        # utf-8-sig writes the BOM, exactly as a Windows editor would.
        (pack_dir / "pack.yaml").write_text(manifest, encoding="utf-8-sig")
        (pack_dir / "schema.json").write_text(schema, encoding="utf-8-sig")
        pack = load_pack("x_bom")
        assert pack.namespace == "x-testpack"

    def test_non_ascii_content_round_trips(self, temp_pack_root):
        manifest = _valid_manifest(framework="Directive — “quoted” 指令")
        _write_pack(temp_pack_root, "x_uni", manifest, schema={"type": "object"})
        assert "指令" in load_pack("x_uni").framework


class TestNoEagerLoadingAtImport:
    """graq_predict chains 3+4: a pack error must never break the package.

    If load_all_packs() were called at module scope, a single malformed
    pack.yaml would raise CompliancePackError during
    `import graqle.compliance` and take down every consumer of the package —
    turning a recoverable data problem into an unrecoverable import failure.
    Loading is lazy by design; this test pins that.
    """

    def test_importing_compliance_does_not_load_packs(self):
        import subprocess
        import sys

        # Fresh interpreter: if any module-scope call existed, patching the
        # loader to explode would surface it as a non-zero exit.
        code = (
            "import graqle.compliance.packs._loader as L\n"
            "def boom(*a, **k): raise AssertionError('eager load at import')\n"
            "L.load_all_packs = boom\n"
            "L.load_pack = boom\n"
            "import importlib\n"
            "importlib.import_module('graqle.compliance')\n"
            "print('OK')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert "OK" in proc.stdout, proc.stderr[-500:]

    def test_loader_has_no_module_scope_load_calls(self):
        import pathlib

        text = pathlib.Path(_loader.__file__).read_text(encoding="utf-8")
        for line in text.splitlines():
            # A load call at column 0 would run at import time.
            assert not line.startswith("load_all_packs("), line
            assert not line.startswith("PACK_REGISTRY = load"), line


class TestWheelSafety:
    """AC-7: pack data must resolve the same way it will from a wheel."""

    def test_packs_root_is_a_traversable_not_a_derived_path(self):
        """The root must come from the package, not from __file__ arithmetic.

        Asserted behaviourally rather than by grepping the source: the
        module docstring legitimately *mentions* Path(__file__).parents[N]
        while explaining why it is wrong, so a text search reports a false
        positive on the explanation itself.
        """
        from importlib.resources import files as _files

        root = _loader._packs_root()  # noqa: SLF001 — asserting the seam
        expected = _files("graqle.compliance.packs")
        # Same resolved location, obtained the importlib way.
        assert str(root) == str(expected)
        assert (root / "x_sox" / "pack.yaml").is_file()

    def test_loader_does_not_import_entry_point_machinery(self):
        """AC-8: entry-point plugin discovery is R10 scope, not R3."""
        source_path = shutil.os.path.join(
            shutil.os.path.dirname(_loader.__file__), "_loader.py"
        )
        text = open(source_path, encoding="utf-8").read()
        # Match real imports, not prose in the docstring explaining the choice.
        assert "import importlib.metadata" not in text
        assert "from importlib.metadata" not in text
        assert "import pkg_resources" not in text
        assert "entry_points(" not in text

    def test_resolves_through_package_traversable(self):
        from importlib.resources import files as _files

        root = _files("graqle.compliance.packs")
        assert (root / "x_sox" / "pack.yaml").is_file()
        assert (root / "x_sox" / "schema.json").is_file()
