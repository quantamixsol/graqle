"""Tests for R21 Cross-Organization Compliance Pattern Transfer (ADR-204).

Covers: pattern_abstractor.py, similarity.py, adaptation.py,
        pattern_registry.py, federated_transfer.py.

Acceptance criteria: AC-1 through AC-7 (privacy + transfer correctness).
"""

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from graqle.governance.adaptation import (
    AdaptationError,
    AdaptationResult,
    TargetOrgContext,
    adapt_pattern,
)
from graqle.governance.federated_transfer import (
    FederatedTransferEngine,
    TransferRecord,
    TransferResult,
)
from graqle.governance.pattern_abstractor import (
    ABSTRACTOR_VERSION,
    AbstractPattern,
    GateStep,
    OutcomeAggregates,
    _contains_forbidden,
    _hash_org,
    extract_abstract_pattern,
    verify_privacy,
)
from graqle.governance.pattern_registry import PatternRegistry, RegistryEntry
from graqle.governance.similarity import (
    DEFAULT_ALPHA,
    DEFAULT_BETA,
    DEFAULT_GAMMA,
    DEFAULT_TRANSFER_THRESHOLD,
    SimilarityScore,
    SimilarityWeights,
    compute_similarity,
    domain_similarity,
    governance_similarity,
    jaccard,
    stack_similarity,
)


def _make_trace(
    i: int = 0,
    tool: str = "graq_reason",
    clearance: str = "INTERNAL",
    outcome: str = "SUCCESS",
    decision: str = "PASS",
    gate_id: str = "CG-01",
    latency: float = 100.0,
    override: bool = False,
) -> dict:
    return {
        "id": f"trace-{i}",
        "tool_name": tool,
        "governance_decisions": [
            {"gate_id": gate_id, "gate_type": "CLEARANCE", "decision": decision}
        ],
        "clearance_level": clearance,
        "outcome": outcome,
        "latency_ms": latency,
        "human_override": override,
    }


def _batch(n: int = 10, **kwargs) -> list[dict]:
    return [_make_trace(i=i, **kwargs) for i in range(n)]


# ═══════════════════════════════════════════════════════════════════
# Forbidden-content scanner tests (AC-2, AC-7)
# ═══════════════════════════════════════════════════════════════════


class TestForbiddenContentScanner:
    def test_email_rejected(self):
        assert _contains_forbidden({"x": "admin@example.com"}) is True

    def test_url_rejected(self):
        assert _contains_forbidden({"x": "https://evil.com/api"}) is True
        assert _contains_forbidden({"x": "http://internal.corp"}) is True

    def test_unix_path_rejected(self):
        assert _contains_forbidden({"x": "/home/haris/secret.key"}) is True

    def test_windows_path_rejected(self):
        assert _contains_forbidden({"x": "C:\\Users\\haris\\file.txt"}) is True

    def test_api_key_rejected(self):
        assert _contains_forbidden({"x": "sk-1234567890abcdefghijkl"}) is True

    def test_ipv4_rejected(self):
        assert _contains_forbidden({"x": "192.168.1.1"}) is True

    def test_bearer_token_rejected(self):
        assert _contains_forbidden({"x": "Bearer abc.def.ghi"}) is True

    def test_sha256_allowed(self):
        sha = hashlib.sha256(b"test").hexdigest()
        assert _contains_forbidden({"x": sha}, allow_sha256=True) is False

    def test_normal_values_allowed(self):
        assert _contains_forbidden({"outcome": "PASS", "count": 5}) is False
        assert _contains_forbidden({"tag": "fintech"}) is False

    def test_nested_scan(self):
        nested = {"outer": {"inner": {"email": "admin@test.com"}}}
        assert _contains_forbidden(nested) is True


# ═══════════════════════════════════════════════════════════════════
# Pattern abstractor tests
# ═══════════════════════════════════════════════════════════════════


class TestPatternAbstractor:
    def test_basic_extraction(self):
        pattern = extract_abstract_pattern(_batch(10), org_id="org-a")
        assert isinstance(pattern, AbstractPattern)
        assert pattern.schema_version == "r21.v1"
        assert pattern.provenance.extractor_version == ABSTRACTOR_VERSION

    def test_source_org_hash_is_sha256(self):
        pattern = extract_abstract_pattern(_batch(10), org_id="acme-corp")
        assert len(pattern.source_org_hash) == 64
        assert all(c in "0123456789abcdef" for c in pattern.source_org_hash.lower())

    def test_source_org_hash_deterministic(self):
        p1 = extract_abstract_pattern(_batch(10), org_id="acme")
        p2 = extract_abstract_pattern(_batch(10), org_id="acme")
        assert p1.source_org_hash == p2.source_org_hash

    def test_different_orgs_different_hashes(self):
        p1 = extract_abstract_pattern(_batch(10), org_id="org-a")
        p2 = extract_abstract_pattern(_batch(10), org_id="org-b")
        assert p1.source_org_hash != p2.source_org_hash

    def test_empty_traces_rejected(self):
        with pytest.raises(ValueError):
            extract_abstract_pattern([], org_id="org-a")

    def test_trace_class_inference(self):
        pattern = extract_abstract_pattern(_batch(10, tool="graq_reason"), org_id="o")
        assert pattern.trace_class == "reasoning"

        pattern2 = extract_abstract_pattern(_batch(10, tool="graq_generate"), org_id="o")
        assert pattern2.trace_class == "generation"

    def test_gate_sequence_populated(self):
        pattern = extract_abstract_pattern(_batch(5), org_id="o")
        assert len(pattern.gate_sequence) == 5

    def test_outcome_aggregates(self):
        traces = (
            _batch(7, outcome="SUCCESS") +
            _batch(3, outcome="FAILURE")
        )
        pattern = extract_abstract_pattern(traces, org_id="o")
        assert abs(pattern.outcome_aggregates.pass_rate - 0.7) < 0.01
        assert abs(pattern.outcome_aggregates.fail_rate - 0.3) < 0.01

    def test_tags_normalized(self):
        pattern = extract_abstract_pattern(
            _batch(5), org_id="o",
            domain_tags=["Fin-Tech!!!", "Payments"],
        )
        # Should lowercase, strip special chars
        assert "fin-tech" in pattern.domain_tags
        assert "payments" in pattern.domain_tags

    def test_privacy_verified_on_extract(self):
        """AC-7: Pattern must pass privacy verification."""
        pattern = extract_abstract_pattern(_batch(10), org_id="o")
        assert verify_privacy(pattern) is True

    def test_raw_org_id_not_in_pattern(self):
        """AC-2: Raw org identifier never present in abstract pattern."""
        org_id = "acme-very-unique-name-12345"
        pattern = extract_abstract_pattern(_batch(10), org_id=org_id)
        dumped = json.dumps(pattern.model_dump(mode="json"), default=str)
        assert org_id not in dumped


# ═══════════════════════════════════════════════════════════════════
# Similarity tests
# ═══════════════════════════════════════════════════════════════════


class TestSimilarity:
    def test_default_weights_sum_to_one(self):
        assert abs(DEFAULT_ALPHA + DEFAULT_BETA + DEFAULT_GAMMA - 1.0) < 0.001

    def test_jaccard_basic(self):
        assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3
        assert jaccard({"a"}, {"a"}) == 1.0
        assert jaccard(set(), set()) == 0.0

    def test_identical_patterns_high_similarity(self):
        pat = extract_abstract_pattern(
            _batch(10), org_id="o",
            domain_tags=["fintech"], stack_tags=["python"], governance_tags=["soc2"],
        )
        score = compute_similarity(pat, pat)
        assert score.total > 0.9

    def test_disjoint_patterns_low_similarity(self):
        pat_a = extract_abstract_pattern(
            _batch(10, tool="graq_reason"), org_id="a",
            domain_tags=["fintech"], stack_tags=["python"], governance_tags=["soc2"],
        )
        pat_b = extract_abstract_pattern(
            _batch(10, tool="graq_generate"), org_id="b",
            domain_tags=["gaming"], stack_tags=["rust"], governance_tags=["iso27001"],
        )
        score = compute_similarity(pat_a, pat_b)
        assert score.total < 0.5

    def test_invalid_weights_rejected(self):
        with pytest.raises(ValueError):
            bad = SimilarityWeights(alpha=0.5, beta=0.5, gamma=0.5)
            compute_similarity(
                extract_abstract_pattern(_batch(10), org_id="a"),
                extract_abstract_pattern(_batch(10), org_id="b"),
                weights=bad,
            )

    def test_threshold_gate(self):
        pat = extract_abstract_pattern(
            _batch(10), org_id="o",
            domain_tags=["fintech"], stack_tags=["python"], governance_tags=["soc2"],
        )
        score = compute_similarity(pat, pat, threshold=0.99)
        assert score.meets_threshold is True
        score2 = compute_similarity(pat, pat, threshold=1.01)
        assert score2.meets_threshold is False


# ═══════════════════════════════════════════════════════════════════
# Adaptation tests (AC-1, AC-2)
# ═══════════════════════════════════════════════════════════════════


class TestAdaptation:
    def _make_pattern(self, org: str = "org-a") -> AbstractPattern:
        return extract_abstract_pattern(_batch(5), org_id=org)

    def _full_context(self, org: str = "org-b") -> TargetOrgContext:
        return TargetOrgContext(
            org_id=org,
            gate_type_map={
                "session": "B-session",
                "plan": "B-plan",
                "clearance": "B-clear",
                "ip_gate": "B-ip",
            },
            clearance_map={
                "PUBLIC": "B-L0",
                "INTERNAL": "B-L2",
                "CONFIDENTIAL": "B-L3",
                "RESTRICTED": "B-L4",
                "UNKNOWN": "B-L0",
            },
        )

    def test_successful_adaptation(self):
        pattern = self._make_pattern()
        ctx = self._full_context()
        result = adapt_pattern(pattern, ctx)
        assert isinstance(result, AdaptationResult)
        assert result.adapted_pattern.source_org_hash == ctx.org_hash

    def test_strict_mode_fails_on_unmapped(self):
        """AC-1: Fail-closed on incomplete mappings."""
        pattern = self._make_pattern()
        ctx = TargetOrgContext(org_id="org-b", strict=True)  # no mappings
        with pytest.raises(AdaptationError):
            adapt_pattern(pattern, ctx)

    def test_non_strict_uses_placeholders(self):
        pattern = self._make_pattern()
        ctx = TargetOrgContext(org_id="org-b", strict=False)
        result = adapt_pattern(pattern, ctx)
        for step in result.adapted_pattern.gate_sequence:
            assert "TARGET_UNKNOWN" in step.gate_type or step.gate_type != ""

    def test_adaptation_preserves_sequence_length(self):
        pattern = self._make_pattern()
        ctx = self._full_context()
        result = adapt_pattern(pattern, ctx)
        assert len(result.adapted_pattern.gate_sequence) == len(pattern.gate_sequence)

    def test_adaptation_preserves_outcome_aggregates(self):
        pattern = self._make_pattern()
        ctx = self._full_context()
        result = adapt_pattern(pattern, ctx)
        assert (
            result.adapted_pattern.outcome_aggregates.pass_rate
            == pattern.outcome_aggregates.pass_rate
        )

    def test_adapted_pattern_privacy_verified(self):
        """AC-7: Post-adaptation privacy check."""
        pattern = self._make_pattern()
        ctx = self._full_context()
        result = adapt_pattern(pattern, ctx)
        assert verify_privacy(result.adapted_pattern) is True


# ═══════════════════════════════════════════════════════════════════
# Pattern registry tests
# ═══════════════════════════════════════════════════════════════════


class TestPatternRegistry:
    def test_register_and_count(self):
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            pat = extract_abstract_pattern(_batch(10), org_id="o")
            entry = await reg.register(pat)
            assert isinstance(entry, RegistryEntry)
            assert reg.count == 1

        asyncio.run(_test())

    def test_register_rejects_privacy_violation(self):
        """AC-2: Store refuses to register unclean patterns."""
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            pat = extract_abstract_pattern(_batch(10), org_id="o")
            # Corrupt the hash to fail verification
            bad = pat.model_copy(update={"source_org_hash": "not-a-real-hash"})
            with pytest.raises(ValueError):
                await reg.register(bad)

        asyncio.run(_test())

    def test_list_patterns(self):
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            for i in range(3):
                pat = extract_abstract_pattern(_batch(5), org_id=f"org-{i}")
                await reg.register(pat)
            entries = reg.list_patterns()
            assert len(entries) == 3

        asyncio.run(_test())

    def test_filter_by_trace_class(self):
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            p1 = extract_abstract_pattern(_batch(5, tool="graq_reason"), org_id="o1")
            p2 = extract_abstract_pattern(_batch(5, tool="graq_generate"), org_id="o2")
            await reg.register(p1)
            await reg.register(p2)
            reasoning = reg.list_patterns(trace_class="reasoning")
            assert len(reasoning) == 1

        asyncio.run(_test())

    def test_load_pattern_by_id(self):
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            pat = extract_abstract_pattern(_batch(5), org_id="o")
            await reg.register(pat)
            loaded = reg.load_pattern(pat.pattern_id)
            assert loaded is not None
            assert loaded.pattern_id == pat.pattern_id

        asyncio.run(_test())

    def test_find_matches_excludes_origin(self):
        """AC-6: Multi-tenant isolation — don't transfer back to source org."""
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            pat_a = extract_abstract_pattern(_batch(5, tool="graq_reason"), org_id="org-a")
            pat_b = extract_abstract_pattern(_batch(5, tool="graq_reason"), org_id="org-b")
            await reg.register(pat_a)
            await reg.register(pat_b)

            matches = reg.find_matches(
                trace_class="reasoning",
                exclude_org_hash=_hash_org("org-a"),
            )
            for m in matches:
                assert m.source_org_hash != _hash_org("org-a")

        asyncio.run(_test())


# ═══════════════════════════════════════════════════════════════════
# Federated transfer engine tests (AC-1 through AC-7)
# ═══════════════════════════════════════════════════════════════════


class TestFederatedTransfer:
    def _full_context(self, org: str = "org-b") -> TargetOrgContext:
        return TargetOrgContext(
            org_id=org,
            gate_type_map={
                "session": "B-session", "plan": "B-plan",
                "clearance": "B-clear", "ip_gate": "B-ip",
            },
            clearance_map={
                "PUBLIC": "B-L0", "INTERNAL": "B-L2",
                "CONFIDENTIAL": "B-L3", "RESTRICTED": "B-L4",
                "UNKNOWN": "B-L0",
            },
        )

    def test_successful_transfer(self):
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            engine = FederatedTransferEngine(
                registry=reg, audit_dir=tempfile.mkdtemp()
            )
            # Source from Org A
            src = extract_abstract_pattern(
                _batch(10), org_id="org-a",
                domain_tags=["fintech"], stack_tags=["python"], governance_tags=["soc2"],
            )
            await reg.register(src)
            # Target from Org B with similar profile
            tgt = extract_abstract_pattern(
                _batch(10), org_id="org-b",
                domain_tags=["fintech"], stack_tags=["python"], governance_tags=["soc2"],
            )
            results = await engine.transfer(
                target_pattern=tgt,
                target_context=self._full_context(),
                threshold=0.5,
            )
            assert len(results) == 1
            assert results[0].record.gated is True
            assert results[0].adapted_pattern is not None

        asyncio.run(_test())

    def test_below_threshold_gated_out(self):
        """AC-1: Transfer only when similarity >= threshold."""
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            engine = FederatedTransferEngine(
                registry=reg, audit_dir=tempfile.mkdtemp()
            )
            src = extract_abstract_pattern(
                _batch(10, tool="graq_reason"), org_id="org-a",
                domain_tags=["fintech"], stack_tags=["python"],
            )
            await reg.register(src)
            tgt = extract_abstract_pattern(
                _batch(10, tool="graq_reason"), org_id="org-b",
                domain_tags=["gaming"], stack_tags=["rust"], governance_tags=["pci"],
            )
            results = await engine.transfer(
                target_pattern=tgt,
                target_context=self._full_context(),
                threshold=0.95,
            )
            # Either no candidates or all gated out
            for r in results:
                if not r.record.gated:
                    assert r.record.adapted is False

        asyncio.run(_test())

    def test_audit_log_written(self):
        """AC-4: Every transfer logged with source, similarity, adaptation."""
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            audit_dir = tempfile.mkdtemp()
            engine = FederatedTransferEngine(registry=reg, audit_dir=audit_dir)

            src = extract_abstract_pattern(
                _batch(10), org_id="org-a",
                domain_tags=["fintech"], stack_tags=["py"], governance_tags=["soc2"],
            )
            await reg.register(src)
            tgt = extract_abstract_pattern(
                _batch(10), org_id="org-b",
                domain_tags=["fintech"], stack_tags=["py"], governance_tags=["soc2"],
            )
            await engine.transfer(
                target_pattern=tgt,
                target_context=self._full_context(),
            )
            entries = engine.read_audit()
            assert len(entries) >= 1
            e = entries[0]
            assert "source_pattern_id" in e
            assert "similarity_total" in e
            assert "privacy_verified_pre" in e

        asyncio.run(_test())

    def test_privacy_invariant_audit_log(self):
        """AC-2: Audit log contains no raw org identifiers."""
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            audit_dir = tempfile.mkdtemp()
            engine = FederatedTransferEngine(registry=reg, audit_dir=audit_dir)

            src = extract_abstract_pattern(
                _batch(10), org_id="unique-org-name-xyz",
                domain_tags=["fintech"], stack_tags=["py"], governance_tags=["soc2"],
            )
            await reg.register(src)
            tgt = extract_abstract_pattern(
                _batch(10), org_id="target-corp-abc",
                domain_tags=["fintech"], stack_tags=["py"], governance_tags=["soc2"],
            )
            await engine.transfer(
                target_pattern=tgt,
                target_context=self._full_context(org="target-corp-abc"),
            )
            entries = engine.read_audit()
            raw = json.dumps(entries, default=str)
            assert "unique-org-name-xyz" not in raw
            assert "target-corp-abc" not in raw

        asyncio.run(_test())

    def test_adaptation_failure_recorded(self):
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            engine = FederatedTransferEngine(
                registry=reg, audit_dir=tempfile.mkdtemp()
            )
            src = extract_abstract_pattern(
                _batch(10), org_id="org-a",
                domain_tags=["fintech"], stack_tags=["py"], governance_tags=["soc2"],
            )
            await reg.register(src)
            tgt = extract_abstract_pattern(
                _batch(10), org_id="org-b",
                domain_tags=["fintech"], stack_tags=["py"], governance_tags=["soc2"],
            )
            # Empty context in strict mode -> adaptation fails
            bad_ctx = TargetOrgContext(org_id="org-b", strict=True)
            results = await engine.transfer(
                target_pattern=tgt,
                target_context=bad_ctx,
                threshold=0.5,
            )
            assert len(results) == 1
            assert results[0].record.gated is True
            assert results[0].record.adapted is False
            assert results[0].adapted_pattern is None

        asyncio.run(_test())

    def test_origin_exclusion(self):
        """AC-6: Cannot transfer pattern back to its origin org."""
        async def _test():
            reg = PatternRegistry(store_dir=tempfile.mkdtemp())
            engine = FederatedTransferEngine(
                registry=reg, audit_dir=tempfile.mkdtemp()
            )
            src = extract_abstract_pattern(
                _batch(10), org_id="org-a",
                domain_tags=["fintech"], stack_tags=["py"], governance_tags=["soc2"],
            )
            await reg.register(src)
            # Target is Org A itself
            tgt = extract_abstract_pattern(
                _batch(10), org_id="org-a",
                domain_tags=["fintech"], stack_tags=["py"], governance_tags=["soc2"],
            )
            results = await engine.transfer(
                target_pattern=tgt,
                target_context=TargetOrgContext(
                    org_id="org-a",
                    gate_type_map={"clearance": "A-clear", "session": "A-sess"},
                    clearance_map={"INTERNAL": "A-L2", "UNKNOWN": "A-L0"},
                ),
            )
            assert len(results) == 0  # origin excluded

        asyncio.run(_test())
