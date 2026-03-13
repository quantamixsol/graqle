"""Tests for OntologyGenerator — mock-based, no API calls."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from graqle.ontology.ontology_generator import OntologyGenerator
from graqle.ontology.semantic_shacl_gate import SemanticConstraint


MOCK_GENERATION_RESPONSE = json.dumps({
    "owl_hierarchy": {
        "GOV_FRAMEWORK": "Governance",
        "GOV_REQUIREMENT": "Governance",
        "GOV_ENFORCEMENT": "Governance",
        "GOV_ACTOR": "Governance",
    },
    "semantic_constraints": [
        {
            "entity_type": "GOV_FRAMEWORK",
            "framework": "Test Regulation",
            "own_framework_markers": ["Test Regulation", "Reg 2024/001"],
            "scope_description": "Overall framework structure",
            "in_scope_topics": ["framework overview", "scope of application"],
            "out_of_scope_topics": ["enforcement penalties", "actor obligations"],
            "reasoning_rules": [
                "This regulation applies to AI systems in the EU market.",
                "Do not confuse framework scope with individual requirements.",
                "Framework-level analysis covers structure, not penalties.",
            ],
            "cross_reference_rules": {
                "GDPR": "Note GDPR as a separate regulation for personal data."
            },
        },
        {
            "entity_type": "GOV_REQUIREMENT",
            "framework": "Test Regulation",
            "own_framework_markers": ["Test Regulation"],
            "scope_description": "Specific requirements and obligations",
            "in_scope_topics": ["compliance obligations", "technical standards"],
            "out_of_scope_topics": ["enforcement mechanisms"],
            "reasoning_rules": [
                "Requirements are binding obligations, not recommendations.",
                "Each requirement maps to a specific article number.",
            ],
            "cross_reference_rules": {},
        },
    ],
})


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    backend.generate = AsyncMock(return_value=MOCK_GENERATION_RESPONSE)
    backend.total_cost_usd = 0.05
    return backend


@pytest.fixture
def generator(mock_backend):
    return OntologyGenerator(backend=mock_backend)


class TestGenerateFromText:
    @pytest.mark.asyncio
    async def test_generates_owl_hierarchy(self, generator):
        owl, constraints = await generator.generate_from_text(
            text="Sample regulation text about AI systems.",
            domain_name="test_regulation",
        )
        assert isinstance(owl, dict)
        assert "GOV_FRAMEWORK" in owl
        assert owl["GOV_FRAMEWORK"] == "Governance"

    @pytest.mark.asyncio
    async def test_generates_semantic_constraints(self, generator):
        owl, constraints = await generator.generate_from_text(
            text="Sample regulation text.",
            domain_name="test_regulation",
        )
        assert isinstance(constraints, dict)
        assert "GOV_FRAMEWORK" in constraints
        assert isinstance(constraints["GOV_FRAMEWORK"], SemanticConstraint)

    @pytest.mark.asyncio
    async def test_constraint_has_reasoning_rules(self, generator):
        _, constraints = await generator.generate_from_text(
            text="Test text.", domain_name="test",
        )
        fw = constraints["GOV_FRAMEWORK"]
        assert len(fw.reasoning_rules) >= 3
        assert "AI systems" in fw.reasoning_rules[0]

    @pytest.mark.asyncio
    async def test_constraint_has_cross_refs(self, generator):
        _, constraints = await generator.generate_from_text(
            text="Test text.", domain_name="test",
        )
        fw = constraints["GOV_FRAMEWORK"]
        assert "GDPR" in fw.cross_reference_rules

    @pytest.mark.asyncio
    async def test_truncates_long_text(self, generator, mock_backend):
        long_text = "x " * 100000
        await generator.generate_from_text(
            text=long_text, domain_name="test", max_text_length=1000,
        )
        call_args = mock_backend.generate.call_args
        prompt = call_args[0][0]
        assert "[... truncated ...]" in prompt

    @pytest.mark.asyncio
    async def test_tracks_cost(self, generator):
        await generator.generate_from_text(text="Test.", domain_name="test")
        assert generator.generation_cost >= 0.0


class TestGenerateFromChunks:
    @pytest.mark.asyncio
    async def test_compiles_chunks_to_document(self, generator, mock_backend):
        chunks = [
            {"text": "Article 1: Scope", "type": "article", "label": "Art. 1"},
            {"text": "Article 2: Definitions", "type": "article", "label": "Art. 2"},
        ]
        owl, constraints = await generator.generate_from_chunks(
            chunks=chunks, domain_name="test",
        )
        assert isinstance(owl, dict)
        call_args = mock_backend.generate.call_args
        prompt = call_args[0][0]
        assert "Art. 1" in prompt
        assert "Article 1: Scope" in prompt


class TestParseResponse:
    def test_handles_markdown_code_block(self, generator):
        response = f"```json\n{MOCK_GENERATION_RESPONSE}\n```"
        owl, constraints = generator._parse_response(response, "test")
        assert "GOV_FRAMEWORK" in owl

    def test_handles_raw_json(self, generator):
        owl, constraints = generator._parse_response(MOCK_GENERATION_RESPONSE, "test")
        assert len(owl) == 4

    def test_handles_malformed_json(self, generator):
        owl, constraints = generator._parse_response("not valid json at all", "test")
        assert owl == {}
        assert constraints == {}


class TestSerialization:
    def test_constraints_roundtrip(self):
        original = {
            "GOV_FRAMEWORK": SemanticConstraint(
                entity_type="GOV_FRAMEWORK",
                framework="Test",
                reasoning_rules=["Rule 1", "Rule 2"],
                cross_reference_rules={"GDPR": "Note separately"},
            ),
        }
        serialized = OntologyGenerator.constraints_to_dict(original)
        assert isinstance(serialized, list)
        assert serialized[0]["entity_type"] == "GOV_FRAMEWORK"

        deserialized = OntologyGenerator.constraints_from_dict(serialized)
        assert "GOV_FRAMEWORK" in deserialized
        assert deserialized["GOV_FRAMEWORK"].framework == "Test"
        assert len(deserialized["GOV_FRAMEWORK"].reasoning_rules) == 2
