"""Shared fixtures for graqle.pct test suite."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="session")
def rsa_keypair():
    """Generate a deterministic-per-session RSA-2048 keypair."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key()
    return priv, pub


@pytest.fixture
def kid() -> str:
    return "test-key-2026-05-23"


@pytest.fixture
def issuer_url() -> str:
    return "https://test-issuer.example.com"


@pytest.fixture
def public_key_resolver(rsa_keypair, kid):
    """A resolver that returns the test public key for `kid`; None otherwise."""
    _, pub = rsa_keypair

    def resolver(kid_in: str):
        if kid_in == kid:
            return pub
        return None

    return resolver


@pytest.fixture
def minimal_issue_request_kwargs() -> dict:
    """Smallest valid PctIssueRequest kwargs that passes schema validation."""
    return {
        "subject_id": "dataset:test-2026-05",
        "subject_type": "ai_interaction",
        "data_origin": "DE",
        "data_categories": ["personal"],
        "lawful_basis": {"bases": ["legitimate_interests"], "framework": "GDPR"},
        "allowed_purposes": ["ai_inference"],
        "jurisdiction_rules": {
            "permitted_regions": ["DE", "FR", "NL"],
            "residency_required": False,
        },
        "data_hash": "n4bQgYhMfWWaL-qgxVrQFaO_TxsrC4Is0V1sFbDwCgg",
        "hash_algorithm": "sha-256",
        "hash_scope": "full_payload",
    }
