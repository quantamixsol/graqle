"""CR-010.R1 — the frozen proof spec + its conformance corpus.

Three things are under test here, and they are deliberately different in kind:

1. **The published spec is loadable and well-formed** — including from an
   installed wheel, via ``importlib.resources`` rather than ``__file__``.
2. **The corpus classifies exactly as declared** — every case in
   ``corpus-manifest.json`` is driven through the real verifier and must produce
   the declared failure, exit code, and present/absent check keys.
3. **The corpus cannot silently drift** — a new ``VerifyFailure`` member with no
   fixture fails the suite, and a fixture mutated away from its declared case
   must stop matching.

The manifest expectations are **empirically derived** from the reference
implementation, not hand-authored, so a disagreement between this suite and the
verifier is a real regression rather than a stale guess.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from graqle.governance.tamper_evidence.verifier import VerifyFailure
from graqle.pct.schema import (
    PROOF_SPEC_SCHEMAS,
    SPEC_VERSION,
    load_proof_schema,
    proof_schema_text,
)
from graqle.verify import EXIT_FAILED, EXIT_OK, EXIT_USAGE, VerifyUsageError, run_verify


def _conformance_root() -> Path:
    """Locate the corpus via importlib.resources, NOT a __file__ path walk.

    Sentinel pass 1, blocker (f): a ``Path(__file__).parents[N]`` walk silently
    resolves to the wrong directory once the package is installed
    (``site-packages/graqle/pct`` rather than the repo root), so a third party
    running the corpus from an installed wheel got FileNotFoundError — which
    defeats the entire point of shipping a portable corpus. Reproduced against a
    real installed wheel before fixing. Resolving through the package makes the
    source tree and the installed wheel behave identically.
    """
    from importlib.resources import files

    return Path(str(files("graqle.pct.schema.conformance")))


_CONFORMANCE = _conformance_root()
_MANIFEST_PATH = _CONFORMANCE / "corpus-manifest.json"
_ALL_CHECKS = ("leaf", "merkle", "signature", "rekor")


def _manifest() -> dict[str, Any]:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _cases() -> list[dict[str, Any]]:
    return _manifest()["cases"]


def _resolve(rel: str) -> Path:
    return (_CONFORMANCE / rel).resolve()


def _case_ids() -> list[str]:
    return [c["id"] for c in _cases()]


# --------------------------------------------------------------------------
# 1. The published spec
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROOF_SPEC_SCHEMAS)
def test_each_published_schema_is_valid_json_schema(name: str) -> None:
    """Every published schema parses AND is itself a legal JSON Schema."""
    schema = load_proof_schema(name)
    # Raises SchemaError if the schema itself is malformed.
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$id"].endswith(f"proof-spec/v{SPEC_VERSION}/{name}.schema.json")


def test_spec_version_is_decoupled_from_sdk_version() -> None:
    """The spec version must NOT track the SDK version (R1 acceptance criterion).

    A third party pins to the spec version; if these were the same string, every
    SDK release would look like a spec change.
    """
    from graqle.__version__ import __version__ as sdk_version

    assert SPEC_VERSION != sdk_version


def test_schema_lookup_failure_names_what_it_looked_for() -> None:
    """An unknown schema/version raises FileNotFoundError naming the miss."""
    with pytest.raises(FileNotFoundError) as exc:
        proof_schema_text("no-such-schema")
    message = str(exc.value)
    assert "no-such-schema" in message
    assert f"v{SPEC_VERSION}" in message

    with pytest.raises(FileNotFoundError):
        proof_schema_text("bundle", version="99.99")


def test_schemas_load_via_importlib_not_file_path() -> None:
    """Schemas must resolve through importlib.resources so a zipped wheel works.

    Reading through the package API (rather than the source tree) is what proves
    the wheel-packaged path is exercised.
    """
    assert proof_schema_text("bundle").strip().startswith("{")


def test_failure_enum_in_schema_matches_the_implementation() -> None:
    """The published failure enum must equal the real VerifyFailure enum.

    This is the anti-drift binding between spec and code: if someone adds a
    member to VerifyFailure without republishing the spec, this fails.
    """
    published = set(load_proof_schema("verify-result")["properties"]["failure"]["enum"])
    implemented = {member.value for member in VerifyFailure}
    assert published == implemented


# --------------------------------------------------------------------------
# 2. The corpus classifies as declared
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", _cases(), ids=_case_ids())
def test_corpus_case_classifies_as_declared(case: dict[str, Any]) -> None:
    """Each corpus case must produce exactly its declared classification."""
    expect = case["expect"]
    bundle = _resolve(case["bundle"])
    keyring = _resolve(case["keyring"])

    if expect.get("usage_error"):
        # "I could not attempt this" — distinct from "this proof is bad".
        with pytest.raises(VerifyUsageError):
            run_verify(bundle_path=bundle, keys_path=keyring)
        assert expect["exit_code"] == EXIT_USAGE
        return

    exit_code, result = run_verify(bundle_path=bundle, keys_path=keyring)

    assert result["failure"] == expect["failure"], f"{case['id']}: wrong failure"
    assert exit_code == expect["exit_code"], f"{case['id']}: wrong exit code"
    assert result["ok"] is expect["ok"], f"{case['id']}: wrong ok"
    assert result["rekor_checked"] is expect["rekor_checked"]

    # absent-vs-false is the subtle interop rule — assert both directions.
    for key in expect["checks_present"]:
        assert key in result["checks"], f"{case['id']}: {key} should be present"
    for key in expect["checks_absent"]:
        assert key not in result["checks"], (
            f"{case['id']}: {key} must be ABSENT (not False) — a check that did "
            f"not run is omitted, not recorded as failed"
        )


@pytest.mark.parametrize("case", _cases(), ids=_case_ids())
def test_corpus_result_validates_against_published_schema(case: dict[str, Any]) -> None:
    """A verifier's JSON output must validate against verify-result.schema.json."""
    if case["expect"].get("usage_error"):
        pytest.skip("usage errors produce no VerifyResult")

    _, result = run_verify(
        bundle_path=_resolve(case["bundle"]), keys_path=_resolve(case["keyring"])
    )
    jsonschema.validate(result, load_proof_schema("verify-result"))


@pytest.mark.parametrize("case", _cases(), ids=_case_ids())
def test_valid_bundles_validate_against_bundle_schema(case: dict[str, Any]) -> None:
    """Structurally-valid fixtures must satisfy bundle.schema.json.

    The malformed and non-JSON fixtures are exempt by construction: TC-002 exists
    precisely to be schema-invalid.
    """
    if case["expect"].get("usage_error"):
        pytest.skip("not a JSON bundle by construction")
    if case["expect"].get("failure") == "MALFORMED_BUNDLE":
        pytest.skip("deliberately malformed — exercises the negative path")

    bundle = json.loads(_resolve(case["bundle"]).read_text(encoding="utf-8"))
    jsonschema.validate(bundle, load_proof_schema("bundle"))


def test_every_keyring_fixture_validates_against_keyring_schema() -> None:
    """Every keyring the corpus ships must satisfy keyring.schema.json."""
    keyrings = {_resolve(c["keyring"]) for c in _cases()}
    assert keyrings, "corpus declares no keyrings"
    schema = load_proof_schema("keyring")
    for path in sorted(keyrings):
        jsonschema.validate(
            json.loads(path.read_text(encoding="utf-8")), schema
        )


@pytest.mark.parametrize(
    "mutate_record, expected",
    [
        (False, "UNTRUSTED_KID"),
        (True, "TAMPERED_LEAF"),
    ],
    ids=["bundle-version-only", "bundle-and-record-version"],
)
def test_arbitrary_proof_format_version_still_fails_closed(
    tmp_path: Path, mutate_record: bool, expected: str
) -> None:
    """Refutation pin for sentinel pass-1 finding (a).

    The sentinel argued that leaving ``proof_format_version`` value-unconstrained
    lets a producer emit anything and still claim conformance. Measured: it does
    not. The field is inside BOTH the signed preimage and the leaf hash, so
    forging it fails closed either way:

    * change it in the wrapper only -> the signature no longer validates
      (UNTRUSTED_KID);
    * change it in wrapper AND record -> the leaf hash no longer matches
      (TAMPERED_LEAF).

    Cryptography already constrains this field, which is exactly why a schema
    ``enum`` would add no security while breaking the legitimate divergent
    values that exist in-tree today. Pinned so the reasoning cannot regress.
    """
    bundle = json.loads(_resolve("fixtures/tc001_valid.json").read_text("utf-8"))
    bundle["proof_format_version"] = "garbage"
    if mutate_record:
        bundle["record"]["proof_format_version"] = "garbage"

    path = tmp_path / "forged.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")

    exit_code, result = run_verify(
        bundle_path=path, keys_path=_resolve("fixtures/keyring_default.json")
    )
    assert result["failure"] == expected
    assert exit_code == EXIT_FAILED


def test_every_corpus_keyring_is_marked_test_only() -> None:
    """Sentinel pass-1 finding (b): corpus keyrings must be machine-readably test-only.

    The corpus signing key comes from a fixed, publicly-known seed, so anyone
    can forge signatures that satisfy these keyrings. A grep-able ``_test_only``
    flag means CI can prove no conformance keyring ever lands in a real trust
    store — a human-readable kid alone would not.
    """
    keyrings = {_resolve(c["keyring"]) for c in _cases()}
    for path in sorted(keyrings):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("_test_only") is True, f"{path.name} lacks the _test_only marker"
        assert "NOT FOR PRODUCTION" in data.get("_warning", "")


def test_malformed_fixture_is_actually_schema_invalid() -> None:
    """TC-002 must genuinely violate the bundle schema, not merely be odd.

    Guards against the negative fixture quietly becoming valid after a schema
    edit — which would make the MALFORMED_BUNDLE case vacuous.
    """
    bundle = json.loads(_resolve("fixtures/tc002_malformed.json").read_text("utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bundle, load_proof_schema("bundle"))


# --------------------------------------------------------------------------
# 3. Anti-drift
# --------------------------------------------------------------------------


def test_every_verify_failure_member_is_covered_by_the_corpus() -> None:
    """Completeness: each VerifyFailure member needs at least one fixture.

    THIS is the guarantee that keeps the corpus honest over time. Add a member
    to VerifyFailure without adding a vector and the suite fails, so an
    unspecified failure mode cannot ship silently.
    """
    covered = {c["expect"]["failure"] for c in _cases() if "failure" in c["expect"]}
    missing = {m.value for m in VerifyFailure} - covered
    assert not missing, f"VerifyFailure members with no conformance vector: {missing}"


def test_corpus_covers_all_three_exit_codes() -> None:
    """0, 1 and 2 must each be exercised — exit 2 is easy to forget."""
    codes = {c["expect"]["exit_code"] for c in _cases()}
    assert codes == {EXIT_OK, EXIT_FAILED, EXIT_USAGE}


def test_tampering_with_a_fixture_changes_its_classification(tmp_path: Path) -> None:
    """A mutated fixture must STOP matching its declared expectation.

    Proves the corpus actually discriminates rather than passing everything.
    """
    original = json.loads(_resolve("fixtures/tc001_valid.json").read_text("utf-8"))
    mutated = json.loads(json.dumps(original))
    root = mutated["merkle"]["merkle_root"]
    mutated["merkle"]["merkle_root"] = root[:-1] + ("1" if root[-1] != "1" else "2")

    path = tmp_path / "mutated.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    exit_code, result = run_verify(
        bundle_path=path, keys_path=_resolve("fixtures/keyring_default.json")
    )
    assert result["failure"] != "OK"
    assert exit_code == EXIT_FAILED


def test_every_published_spec_file_is_importlib_accessible() -> None:
    """Wheel-content smoke test (sentinel pass-2 non-blocking recommendation).

    ``[tool.hatch.build] artifacts`` inheritance by the wheel target was verified
    empirically against a real installed wheel, but it is build-tool behaviour
    that could regress silently on a Hatchling upgrade. Asserting every published
    file is reachable *through the package* (not the source tree) turns that into
    a loud failure: if a future build stops shipping the spec, this breaks.
    """
    from importlib.resources import files

    spec_root = files("graqle.pct.schema")
    for name in PROOF_SPEC_SCHEMAS:
        assert spec_root.joinpath(
            f"proof-spec/v{SPEC_VERSION}/{name}.schema.json"
        ).is_file(), f"{name}.schema.json is not shipped"
    assert spec_root.joinpath(f"proof-spec/v{SPEC_VERSION}/SPEC.md").is_file()

    corpus = files("graqle.pct.schema.conformance")
    assert corpus.joinpath("corpus-manifest.json").is_file()
    for case in _cases():
        for key in ("bundle", "keyring"):
            assert corpus.joinpath(case[key]).is_file(), (
                f"{case['id']}: {case[key]} is not shipped in the package"
            )


def test_corpus_is_locatable_through_the_package_not_a_file_path_walk() -> None:
    """Regression pin for sentinel pass-1 blocker (f).

    The corpus MUST be reachable via importlib.resources so it resolves
    identically from the source tree and from an installed wheel. A
    ``Path(__file__).parents[N]`` walk silently pointed at a non-existent
    directory once installed, which broke the portable-corpus promise.
    """
    from importlib.resources import files

    root = Path(str(files("graqle.pct.schema.conformance")))
    assert (root / "corpus-manifest.json").is_file()
    assert (root / "fixtures").is_dir()
    # The resolved root must be the conformance package itself.
    assert root.name == "conformance"


def test_committed_fixtures_match_the_generator(tmp_path: Path) -> None:
    """Committed fixtures must be exactly what the generator produces.

    Sentinel pass-1 finding (c), second path: the anti-drift test proves every
    failure mode HAS a vector, but a committed fixture could still go stale if
    someone changes the generator and forgets to re-run it. Regenerating into a
    temp dir and diffing closes that hole — stale golden vectors are caught here
    rather than shipping as a silently-wrong published corpus.
    """
    import shutil

    from graqle.pct.schema.conformance import generate_fixtures as gen

    live = _CONFORMANCE / "fixtures"
    staging = tmp_path / "fixtures"
    shutil.copytree(live, staging)

    original = gen.FIXTURES
    try:
        gen.FIXTURES = staging
        gen.main()
    finally:
        gen.FIXTURES = original

    for committed in sorted(live.iterdir()):
        regenerated = staging / committed.name
        assert regenerated.is_file(), f"generator no longer emits {committed.name}"
        assert regenerated.read_bytes() == committed.read_bytes(), (
            f"{committed.name} is STALE — re-run "
            f"`python -m graqle.pct.schema.conformance.generate_fixtures`"
        )


def test_manifest_declares_every_shipped_fixture() -> None:
    """No orphan fixtures: everything in fixtures/ is referenced by the manifest.

    An unreferenced fixture is dead weight a third party would have to guess at.
    """
    referenced = set()
    for case in _cases():
        referenced.add(_resolve(case["bundle"]))
        referenced.add(_resolve(case["keyring"]))
    on_disk = {p.resolve() for p in (_CONFORMANCE / "fixtures").iterdir() if p.is_file()}
    assert on_disk == referenced, (
        f"orphan fixtures: {on_disk - referenced}; "
        f"missing fixtures: {referenced - on_disk}"
    )


# --------------------------------------------------------------------------
# 4. Third-party runnability (subprocess + JSON boundary)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", _cases(), ids=_case_ids())
def test_corpus_runs_over_a_subprocess_json_boundary(case: dict[str, Any]) -> None:
    """Drive each case exactly as a foreign implementation would.

    This is the real interop assertion: a separate process, real exit codes, and
    stdout parsed as JSON — no in-process Python objects, no GraQle imports on
    the consuming side.
    """
    expect = case["expect"]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "graqle.verify",
            str(_resolve(case["bundle"])),
            "--keys",
            str(_resolve(case["keyring"])),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == expect["exit_code"], (
        f"{case['id']}: expected exit {expect['exit_code']}, got "
        f"{proc.returncode}. stderr={proc.stderr[:400]}"
    )

    if expect.get("usage_error"):
        # A usage error emits a DIFFERENT shape: {"ok": false, "error": "..."}
        # with no failure/checks keys, because no verification was attempted.
        # The exit code above is the primary contract; the payload is a
        # diagnostic. Some runners surface it on stderr, so accept either and
        # only assert the shape when a payload is actually present.
        raw = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if raw.startswith("{"):
            payload = json.loads(raw)
            assert payload["ok"] is False
            assert "error" in payload
            assert "failure" not in payload
        return

    payload = json.loads(proc.stdout)

    # A plain string compare — the whole point of failure being a str enum.
    assert payload["failure"] == expect["failure"]
    for key in expect["checks_absent"]:
        assert key not in payload["checks"]
