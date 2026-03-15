"""Tests for AdapterAutoSelector — automatic LoRA adapter selection."""

# ── graqle:intelligence ──
# module: tests.test_adapters.test_auto_select
# risk: LOW (impact radius: 0 modules)
# dependencies: dataclasses, mock, pytest, auto_select
# constraints: none
# ── /graqle:intelligence ──

from dataclasses import dataclass
from unittest.mock import MagicMock

from graqle.adapters.auto_select import AdapterAutoSelector


@dataclass
class FakeNode:
    """Minimal CogniNode stand-in for testing."""
    id: str
    entity_type: str = "Entity"
    properties: dict = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


@dataclass
class FakeAdapterConfig:
    """Minimal AdapterConfig stand-in for testing."""
    adapter_id: str
    name: str
    domain: str


def test_explicit_mapping():
    """Register explicit mapping and verify exact match."""
    selector = AdapterAutoSelector()
    selector.register_mapping("GOV_REQUIREMENT", "governance/eu-ai-act-v1")

    node = FakeNode(id="n1", entity_type="GOV_REQUIREMENT")
    result = selector.select(node)

    assert result.adapter_id == "governance/eu-ai-act-v1"
    assert result.match_type == "exact"
    assert result.confidence == 1.0
    assert result.node_id == "n1"
    assert result.entity_type == "GOV_REQUIREMENT"


def test_domain_fallback():
    """Register domain mapping and verify domain-level fallback."""
    selector = AdapterAutoSelector()
    selector.register_domain("gov", "governance/general-v1")

    node = FakeNode(id="n2", entity_type="GOV_REQUIREMENT")
    result = selector.select(node)

    assert result.adapter_id == "governance/general-v1"
    assert result.match_type == "domain"
    assert result.confidence == 0.7


def test_fuzzy_match():
    """Mock registry with adapter containing entity type in name."""
    mock_registry = MagicMock()
    mock_registry.list_adapters.return_value = [
        FakeAdapterConfig(
            adapter_id="custom/gdpr-expert",
            name="GDPR_COMPLIANCE_EXPERT",
            domain="legal",
        ),
    ]

    selector = AdapterAutoSelector(registry=mock_registry)
    node = FakeNode(id="n3", entity_type="GDPR_COMPLIANCE")

    result = selector.select(node)

    assert result.adapter_id == "custom/gdpr-expert"
    assert result.match_type == "fuzzy"
    assert result.confidence == 0.5


def test_no_match():
    """No mapping, no registry -> none result."""
    selector = AdapterAutoSelector()
    node = FakeNode(id="n4", entity_type="UNKNOWN_TYPE")

    result = selector.select(node)

    assert result.adapter_id is None
    assert result.match_type == "none"
    assert result.confidence == 0.0


def test_cache():
    """Same node selected twice uses cache."""
    selector = AdapterAutoSelector()
    selector.register_mapping("LEGAL_CLAUSE", "legal/clause-v1")

    node = FakeNode(id="n5", entity_type="LEGAL_CLAUSE")

    result1 = selector.select(node)
    result2 = selector.select(node)

    assert result1 is result2  # Same object from cache
    assert result1.adapter_id == "legal/clause-v1"


def test_batch_select():
    """select_batch returns correct count of results."""
    selector = AdapterAutoSelector()
    selector.register_mapping("TYPE_A", "adapters/a-v1")
    selector.register_mapping("TYPE_B", "adapters/b-v1")

    nodes = [
        FakeNode(id="n1", entity_type="TYPE_A"),
        FakeNode(id="n2", entity_type="TYPE_B"),
        FakeNode(id="n3", entity_type="TYPE_C"),
    ]

    results = selector.select_batch(nodes)

    assert len(results) == 3
    assert results[0].adapter_id == "adapters/a-v1"
    assert results[1].adapter_id == "adapters/b-v1"
    assert results[2].adapter_id is None  # no mapping for TYPE_C
