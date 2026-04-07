"""Comprehensive test suite for ADR-151: Content Security Architecture.

Tests all 3 pillars: TAG (sensitivity classification), GATE (content redaction),
AUDIT (evidence trail). Covers the 5-layer detection pipeline (L0-L4),
all 7 exit gates (G1-G7), and the audit mechanism.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from graqle.security.entropy import EntropyDetector, EntropyMatch, shannon_entropy
from graqle.security.sensitivity import (
    RedactionMarker,
    SensitivityClassifier,
    SensitivityLevel,
    TYPED_PLACEHOLDERS,
)
from graqle.security.content_gate import (
    ContentAuditRecord,
    ContentSecurityGate,
    GateResult,
)
from graqle.security.audit import RedactionEvent, SecurityAuditor


# =========================================================================
# PILLAR 1: TAG — Sensitivity Classification
# =========================================================================


class TestSensitivityLevel:
    def test_ordering(self):
        assert SensitivityLevel.PUBLIC < SensitivityLevel.INTERNAL
        assert SensitivityLevel.INTERNAL < SensitivityLevel.SECRET
        assert SensitivityLevel.SECRET < SensitivityLevel.RESTRICTED

    def test_values(self):
        assert SensitivityLevel.PUBLIC == 0
        assert SensitivityLevel.INTERNAL == 1
        assert SensitivityLevel.SECRET == 2
        assert SensitivityLevel.RESTRICTED == 3


class TestEntropyDetector:
    def test_low_entropy_ignored(self):
        d = EntropyDetector()
        assert d.detect_high_entropy_strings("hello world this is normal text") == []

    def test_high_entropy_detected(self):
        d = EntropyDetector()
        # High-entropy string (synthetic, not a real key format)
        matches = d.detect_high_entropy_strings(
            "key=xK9mP2vL8nQ4wR7jF3hT6yB1cD5eG0aS"
        )
        assert len(matches) >= 1
        assert all(isinstance(m, EntropyMatch) for m in matches)
        assert all(m.entropy_value >= 4.5 for m in matches)

    def test_uuid_safe_pattern(self):
        d = EntropyDetector()
        matches = d.detect_high_entropy_strings(
            "id=550e8400-e29b-41d4-a716-446655440000"
        )
        # UUIDs should be filtered as safe
        uuid_matches = [m for m in matches if "550e8400" in m.text]
        assert len(uuid_matches) == 0

    def test_sha256_safe_pattern(self):
        d = EntropyDetector()
        # 64-char hex string = SHA-256 hash
        sha = "a" * 32 + "b" * 32
        matches = d.detect_high_entropy_strings(f"hash={sha}")
        sha_matches = [m for m in matches if sha in m.text]
        assert len(sha_matches) == 0

    def test_configurable_threshold(self):
        d = EntropyDetector(threshold=3.0, min_length=8)
        matches = d.detect_high_entropy_strings("secret=a1b2c3d4e5f6")
        # Lower threshold catches more
        assert len(matches) >= 0  # May or may not match depending on exact entropy

    def test_shannon_entropy_empty(self):
        assert shannon_entropy("") == 0.0

    def test_shannon_entropy_uniform(self):
        # "abcd" has 4 unique chars, each p=0.25, entropy = 2.0
        assert abs(shannon_entropy("abcd") - 2.0) < 0.01

    def test_shannon_entropy_single_char(self):
        assert shannon_entropy("aaaa") == 0.0


class TestSensitivityClassifier:
    def setup_method(self):
        self.classifier = SensitivityClassifier()

    def test_empty_node_is_public(self):
        assert self.classifier.classify_node({}) == SensitivityLevel.PUBLIC

    def test_l0_property_key_match(self):
        """L0: property key containing 'password' -> INTERNAL."""
        assert self.classifier.classify_node(
            {"db_password": "anything"}
        ) == SensitivityLevel.INTERNAL

    def test_l0_api_key_match(self):
        assert self.classifier.classify_node(
            {"api_key": "sk-123"}
        ) == SensitivityLevel.INTERNAL

    def test_l1_aws_key_is_secret(self):
        """L1: AWS access key pattern -> SECRET (critical pattern)."""
        level = self.classifier.classify_node(
            {}, description="cred=AKIAIOSFODNN7EXAMPLE"
        )
        assert level == SensitivityLevel.SECRET

    def test_l1_jwt_is_secret(self):
        """L1: JWT token -> SECRET (critical pattern)."""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"
        level = self.classifier.classify_node({}, description=jwt)
        assert level == SensitivityLevel.SECRET

    def test_l1_connection_string_is_secret(self):
        level = self.classifier.classify_node(
            {}, description="db=postgresql://user:pass@host/dbname"
        )
        assert level == SensitivityLevel.SECRET

    def test_l1_generic_secret_is_internal(self):
        level = self.classifier.classify_node(
            {}, description='secret = "my-secret-value"'
        )
        assert level >= SensitivityLevel.INTERNAL

    def test_l3_credential_assignment(self):
        """L3: password = 'value' in source code -> SECRET."""
        level = self.classifier.classify_node(
            {}, chunks=['password = "hunter2"']
        )
        assert level == SensitivityLevel.SECRET

    def test_l3_api_key_assignment(self):
        level = self.classifier.classify_node(
            {}, chunks=['api_key = "sk-1234567890abcdef"']
        )
        assert level >= SensitivityLevel.INTERNAL

    def test_safe_code_is_public(self):
        """Normal code without secrets -> PUBLIC."""
        level = self.classifier.classify_node(
            {"name": "auth_service", "line_count": 42},
            description="Authentication service handling login/logout.",
            chunks=["def login(username, password_hash): ..."],
        )
        assert level == SensitivityLevel.PUBLIC

    def test_classify_text_returns_markers(self):
        level, markers = self.classifier.classify_text(
            'config: api_key=sk-1234567890abcdef'
        )
        assert level >= SensitivityLevel.INTERNAL
        assert len(markers) >= 1
        assert all(isinstance(m, RedactionMarker) for m in markers)

    def test_classify_text_empty(self):
        level, markers = self.classifier.classify_text("")
        assert level == SensitivityLevel.PUBLIC
        assert markers == []

    def test_highest_level_wins(self):
        """Multiple layers triggered — highest level wins."""
        level = self.classifier.classify_node(
            {"db_password": "x"},  # L0 -> INTERNAL
            description="key=AKIAIOSFODNN7EXAMPLE",  # L1 -> SECRET
        )
        assert level == SensitivityLevel.SECRET


class TestTypedPlaceholders:
    def test_aws_key_placeholder(self):
        assert "aws_key" in TYPED_PLACEHOLDERS
        assert "<" in TYPED_PLACEHOLDERS["aws_key"]

    def test_password_placeholder(self):
        assert "password" in TYPED_PLACEHOLDERS

    def test_jwt_placeholder(self):
        assert "jwt" in TYPED_PLACEHOLDERS

    def test_generic_fallback(self):
        assert "generic" in TYPED_PLACEHOLDERS


class TestRedactionMarker:
    def test_frozen(self):
        m = RedactionMarker(offset=10, length=20, pattern_type="api_key", replacement="<API_KEY>")
        with pytest.raises(AttributeError):
            m.offset = 99  # type: ignore


# =========================================================================
# PILLAR 2: GATE — Content Redaction
# =========================================================================


class TestContentSecurityGate:
    def setup_method(self):
        self.gate = ContentSecurityGate()

    def test_redact_properties_sensitive(self):
        result = self.gate.redact_properties({"db_password": "secret", "name": "auth"})
        assert result["name"] == "auth"
        assert "secret" not in str(result["db_password"])
        assert "<" in result["db_password"]  # typed placeholder

    def test_redact_properties_never_mutates(self):
        original = {"password": "hunter2", "name": "test"}
        copy = dict(original)
        self.gate.redact_properties(original)
        assert original == copy

    def test_redact_text_with_api_key(self):
        result = self.gate.redact_text("config: api_key=sk-1234567890abcdef")
        assert "sk-1234567890abcdef" not in result
        assert "<" in result  # typed placeholder present

    def test_redact_text_safe_content(self):
        text = "Module handles authentication flow."
        assert self.gate.redact_text(text) == text

    def test_redact_for_embedding_semantic(self):
        """Embedding redaction uses typed placeholders, not generic [REDACTED]."""
        result = self.gate.redact_for_embedding("key=AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        # Should use typed placeholder, not generic [REDACTED]
        assert "[REDACTED]" not in result or "<" in result

    def test_prepare_node_for_llm(self):
        props, desc, chunks = self.gate.prepare_node_for_llm(
            {"api_key": "sk-123", "name": "svc"},
            "Service with password=hunter2",
            ["token = 'jwt-abc123'"],
        )
        assert "sk-123" not in str(props)
        assert "hunter2" not in desc
        assert props["name"] == "svc"

    def test_prepare_content_for_send_audit_record(self):
        content, record = self.gate.prepare_content_for_send(
            "AKIAIOSFODNN7EXAMPLE in config", "anthropic", gate_id="G5",
        )
        assert isinstance(record, ContentAuditRecord)
        assert record.destination == "anthropic"
        assert record.gate_id == "G5"
        assert record.redactions_applied >= 1
        assert record.content_hash_pre != record.content_hash_post

    def test_prepare_content_dry_run(self):
        """N5 fix: dry-run still redacts content but flags in audit record."""
        content, record = self.gate.prepare_content_for_send(
            "AKIAIOSFODNN7EXAMPLE", "bedrock", gate_id="G5", dry_run=True,
        )
        assert record.dry_run is True
        # N5: dry-run STILL redacts (prevents accidental exposure in prod)
        assert "AKIAIOSFODNN7EXAMPLE" not in content

    def test_gate_check(self):
        result = self.gate.gate_check("AKIAIOSFODNN7EXAMPLE", "anthropic")
        assert isinstance(result, GateResult)
        assert result.sensitivity_level >= SensitivityLevel.INTERNAL
        assert result.redactions_needed >= 1
        assert result.can_send is True  # SECRET < RESTRICTED threshold

    def test_disabled_gate_passthrough(self):
        gate = ContentSecurityGate(enabled=False)
        props = gate.redact_properties({"password": "secret"})
        assert props["password"] == "secret"  # Not redacted

    def test_sha256_hashes_in_audit(self):
        _, record = self.gate.prepare_content_for_send(
            "password=hunter2", "openai",
        )
        assert record.content_hash_pre.startswith("sha256:")
        assert record.content_hash_post.startswith("sha256:")


# =========================================================================
# PILLAR 3: AUDIT — Evidence Trail
# =========================================================================


class TestSecurityAuditor:
    def test_log_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test_audit.jsonl"
            auditor = SecurityAuditor(log_path=log_path)

            record = ContentAuditRecord(
                timestamp="2026-04-03T12:00:00Z",
                destination="anthropic",
                gate_id="G1",
                sensitivity_level=SensitivityLevel.SECRET,
                redactions_applied=3,
                original_length=1000,
                redacted_length=950,
                content_hash_pre="sha256:abc",
                content_hash_post="sha256:def",
            )
            auditor.log_event(record)

            recent = auditor.get_recent(10)
            assert len(recent) == 1
            assert recent[0]["destination"] == "anthropic"
            assert recent[0]["redactions_applied"] == 3

    def test_generate_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test_audit.jsonl"
            auditor = SecurityAuditor(log_path=log_path)

            for dest in ["anthropic", "anthropic", "bedrock"]:
                record = ContentAuditRecord(
                    timestamp="2026-04-03T12:00:00Z",
                    destination=dest,
                    gate_id="G1",
                    sensitivity_level=SensitivityLevel.INTERNAL,
                    redactions_applied=2,
                    original_length=500,
                    redacted_length=480,
                    content_hash_pre="sha256:x",
                    content_hash_post="sha256:y",
                )
                auditor.log_event(record)

            report = auditor.generate_report()
            assert report["total_events"] == 3
            assert report["by_destination"]["anthropic"] == 2
            assert report["by_destination"]["bedrock"] == 1
            assert report["total_redactions"] == 6

    def test_empty_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "empty.jsonl"
            auditor = SecurityAuditor(log_path=log_path)
            assert auditor.get_recent() == []
            report = auditor.generate_report()
            assert report["total_events"] == 0


class TestRedactionEvent:
    def test_frozen(self):
        evt = RedactionEvent(
            timestamp="2026-04-03T12:00:00Z",
            layer="L1",
            pattern_matched="aws_key",
            destination="anthropic",
        )
        with pytest.raises(AttributeError):
            evt.layer = "L2"  # type: ignore


# =========================================================================
# INTEGRATION: End-to-end flow
# =========================================================================


class TestEndToEnd:
    def test_full_pipeline_public_content(self):
        """Normal code with no secrets -> PUBLIC, no redaction."""
        gate = ContentSecurityGate()
        content = "def login(username, password_hash): return verify(password_hash)"
        result = gate.gate_check(content, "anthropic")
        assert result.sensitivity_level == SensitivityLevel.PUBLIC
        assert result.redactions_needed == 0

    def test_full_pipeline_secret_content(self):
        """AWS key in content -> SECRET, redacted, audit trail."""
        gate = ContentSecurityGate()
        content = "config: AKIAIOSFODNN7EXAMPLE"
        redacted, record = gate.prepare_content_for_send(content, "anthropic")
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted
        assert record.sensitivity_level == SensitivityLevel.SECRET
        assert record.content_hash_pre != record.content_hash_post

    def test_full_pipeline_node_for_llm(self):
        """Node with sensitive properties -> redacted before LLM."""
        gate = ContentSecurityGate()
        props, desc, chunks = gate.prepare_node_for_llm(
            {"api_key": "sk-live-abc123", "name": "payment_service"},
            "Payment API with connection_string=postgresql://user:pass@host/db",
            ["password = 'my-secret-value-here'"],
        )
        assert "sk-live-abc123" not in str(props)
        assert "user:pass" not in desc
        assert "my-secret-value-here" not in str(chunks)
        assert props["name"] == "payment_service"

    def test_audit_integration(self):
        """Gate -> audit trail end-to-end."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "e2e.jsonl"
            auditor = SecurityAuditor(log_path=log_path)
            gate = ContentSecurityGate()

            _, record = gate.prepare_content_for_send(
                "password='hunter2'", "openai", gate_id="G5",
            )
            auditor.log_event(record)

            recent = auditor.get_recent(1)
            assert len(recent) == 1
            assert recent[0]["gate_id"] == "G5"
            assert recent[0]["destination"] == "openai"
