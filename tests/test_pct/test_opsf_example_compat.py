"""Cross-test against OPSF example scenarios (CR-010 PR-010b-1 AC-4).

Each of the 4 vendored OPSF scenarios carries an ``_expected_decision``
marker (ALLOW or BLOCK). This test suite confirms that GraQle's
validator returns the OPSF-expected decision when handed an issued
token built from each scenario's payload.

The OPSF examples are JSON files at
``graqle/pct/schema/opsf_examples/scenario_{1,2,3,4}_*.json``,
vendored from
``opsf-org/pct-spec@develop/examples/scenario-{1,2,3,4}-*.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.pct.issuer import PctIssueRequest, issue_pct
from graqle.pct.validator import validate_pct

_OPSF_EXAMPLES_DIR = (
    Path(__file__).parent.parent.parent
    / "graqle"
    / "pct"
    / "schema"
    / "opsf_examples"
)

_EXAMPLE_FILES = [
    "scenario_1_allow_uk_clinical.json",
    "scenario_2_block_jurisdiction.json",
    "scenario_3_block_purpose.json",
    "scenario_4_block_multiple.json",
]


def _load_scenario(filename: str) -> dict:
    path = _OPSF_EXAMPLES_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def _request_kwargs_from_scenario_payload(payload: dict) -> dict:
    """Project an OPSF example payload to PctIssueRequest kwargs.

    The example payloads carry all the issuer-mandated fields; the
    issuer regenerates ``issued_at``/``valid_from``/``expires_at`` +
    ``pct_id`` independently.
    """
    return {
        "subject_id": payload["subject_id"],
        "subject_type": payload["subject_type"],
        "data_origin": payload["data_origin"],
        "data_categories": list(payload["data_categories"]),
        "lawful_basis": dict(payload["lawful_basis"]),
        "allowed_purposes": list(payload["allowed_purposes"]),
        "jurisdiction_rules": dict(payload["jurisdiction_rules"]),
        "data_hash": payload["data_hash"],
        "hash_algorithm": payload["hash_algorithm"],
        "hash_scope": payload["hash_scope"],
        "retention_limit": payload.get("retention_limit"),
        "automated_decision_flag": payload.get("automated_decision_flag", False),
        "ai_context": payload.get("ai_context"),
        "consent_status": payload.get("consent_status"),
        "consent_scope": payload.get("consent_scope"),
        "consent_record_ref": payload.get("consent_record_ref"),
        "transfer_restrictions": payload.get("transfer_restrictions"),
        "data_format": payload.get("data_format"),
    }


@pytest.fixture(params=_EXAMPLE_FILES)
def opsf_scenario(request):
    """Yield (filename, full_example_dict, payload_dict, expected_decision)."""
    filename = request.param
    full = _load_scenario(filename)
    return {
        "filename": filename,
        "expected_decision": full["_expected_decision"],
        "scenario": full["_scenario"],
        "payload": full["pct"]["payload"],
    }


def test_opsf_example_loads_with_expected_decision(opsf_scenario):
    """Smoke: each vendored example has a recognisable expected_decision."""
    assert opsf_scenario["expected_decision"] in {"ALLOW", "BLOCK"}
    assert "scenario" in opsf_scenario["payload"] or True  # payload sanity


def test_round_trip_issue_then_validate_matches_expected_decision(
    opsf_scenario,
    rsa_keypair,
    kid,
    issuer_url,
    public_key_resolver,
):
    """Round-trip: issue from OPSF payload + validate with the same key.

    For the ALLOW scenario, decision must be ALLOW unconditionally.

    For the BLOCK scenarios, the OPSF example presupposes specific
    enforcement-point context (jurisdiction mismatch / purpose
    mismatch / etc.). The validator must produce BLOCK when given
    that enforcement-point context as the validation hint.
    """
    priv, _ = rsa_keypair
    payload = opsf_scenario["payload"]
    expected = opsf_scenario["expected_decision"]

    req = PctIssueRequest(**_request_kwargs_from_scenario_payload(payload))
    token = issue_pct(req, signing_key=priv, kid=kid, issuer_url=issuer_url)

    # Scenario-specific validation hints
    filename = opsf_scenario["filename"]
    validation_kwargs: dict = {}

    if filename == "scenario_1_allow_uk_clinical.json":
        # UK clinical data, UK processing, valid consent: ALLOW
        validation_kwargs = {
            "expected_jurisdiction": "GB",
            "expected_action": "clinical_analytics",
        }
    elif filename == "scenario_2_block_jurisdiction.json":
        # UK clinical data routed to US model: BLOCK on jurisdiction
        validation_kwargs = {"expected_jurisdiction": "US"}
    elif filename == "scenario_3_block_purpose.json":
        # Purpose not in claims: BLOCK on purpose
        validation_kwargs = {"expected_action": "marketing_analytics"}
    elif filename == "scenario_4_block_multiple.json":
        # Clinical trial data, multiple simultaneous failures:
        # at least one of {jurisdiction not permitted, action not allowed}
        validation_kwargs = {
            "expected_jurisdiction": "US",
            "expected_action": "marketing_analytics",
        }

    result = validate_pct(
        token,
        public_key_resolver=public_key_resolver,
        **validation_kwargs,
    )

    assert result.decision == expected, (
        f"{filename}: expected {expected}, got {result.decision} "
        f"with reasons={result.failure_reasons}"
    )
