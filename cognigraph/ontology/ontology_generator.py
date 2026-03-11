"""Ontology Auto-Generator — high-end model reads documents, generates OWL + SHACL.

The expensive step: Sonnet/Opus reads regulation text ONCE and produces
structured OWL hierarchy + SemanticConstraint definitions.
The output is stored and reused forever — cheap nodes reason within these constraints.

Usage:
    generator = OntologyGenerator(backend=BedrockBackend("eu.anthropic.claude-sonnet-4-6"))
    owl, constraints = await generator.generate_from_text(
        text="EU AI Act full text...",
        domain="eu_ai_act",
    )
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from cognigraph.ontology.semantic_shacl_gate import SemanticConstraint

logger = logging.getLogger("cognigraph.ontology.generator")

# Prompt template for ontology generation
ONTOLOGY_GENERATION_PROMPT = """You are an ontology engineer. Read the following regulatory/governance document
and generate a structured ontology with semantic constraints.

DOCUMENT:
{document_text}

DOMAIN NAME: {domain_name}

Generate the following as valid JSON:

1. "owl_hierarchy": A dict mapping entity type names to their parent types.
   Use these upper types: Governance, Entity, Agent, Process, Risk, Control.
   Entity types should be UPPERCASE_WITH_UNDERSCORES (e.g., "GOV_REQUIREMENT").
   Include at least: framework-level types, requirement types, enforcement types, actor types.

2. "semantic_constraints": A list of constraint objects, one per entity type, each with:
   - "entity_type": The type name (matches owl_hierarchy key)
   - "framework": The framework name (e.g., "EU AI Act")
   - "own_framework_markers": List of strings that identify this framework (titles, regulation numbers)
   - "scope_description": What this entity type covers
   - "in_scope_topics": List of specific topics this type IS authorized to discuss
   - "out_of_scope_topics": List of topics that belong to OTHER entity types (not this one)
   - "reasoning_rules": List of deep semantic rules like:
     * "Prohibited practices are BANNED, not 'high-risk'. Do not confuse the two."
     * "Penalties for this provision are Art. 99(1): up to 35M EUR or 7% turnover"
     * "This applies to providers, NOT to deployers (deployers are covered by Art. 26)"
   - "cross_reference_rules": Dict of framework_name -> how to reference it
     * e.g., {{"GDPR": "If mentioning GDPR, note it as a separate legal basis under Regulation 2016/679"}}

IMPORTANT:
- Focus on SEMANTIC rules, not format rules. No word limits, no regex patterns.
- Each reasoning_rule should encode a governance truth that prevents misattribution.
- out_of_scope_topics should list what OTHER nodes handle, to prevent scope creep.
- cross_reference_rules should explain HOW to properly cite other frameworks.
- Generate at least 3 reasoning_rules per entity type.
- Generate at least 2 out_of_scope_topics per entity type.

Output ONLY valid JSON, no markdown formatting:
"""


class OntologyGenerator:
    """Generate OWL + SHACL from documents using a high-end model.

    This is a one-time expensive operation. The output is stored
    and reused for all subsequent queries.

    .. note:: Requires CogniGraph Pro license (``ontology_generator`` feature).
    """

    def __init__(self, backend: Any) -> None:
        """Initialize with a model backend (typically Bedrock Sonnet/Opus)."""
        from cognigraph.licensing.manager import check_license
        check_license("ontology_generator")
        self._backend = backend
        self._generation_cost = 0.0

    @property
    def generation_cost(self) -> float:
        """Cost of the last generation run."""
        return self._generation_cost

    async def generate_from_text(
        self,
        text: str,
        domain_name: str,
        max_text_length: int = 50000,
    ) -> Tuple[Dict[str, str], Dict[str, SemanticConstraint]]:
        """Read document text and generate OWL hierarchy + semantic constraints.

        Args:
            text: The full document text (regulation, policy, etc.)
            domain_name: Name for the domain (e.g., "eu_ai_act")
            max_text_length: Truncate text to this length to fit context window

        Returns:
            Tuple of (owl_hierarchy, semantic_constraints)
        """
        # Truncate if needed
        if len(text) > max_text_length:
            text = text[:max_text_length] + "\n\n[... truncated ...]"

        prompt = ONTOLOGY_GENERATION_PROMPT.format(
            document_text=text,
            domain_name=domain_name,
        )

        # Track cost
        cost_before = 0.0
        if hasattr(self._backend, "total_cost_usd"):
            cost_before = self._backend.total_cost_usd

        logger.info(f"Generating ontology for domain '{domain_name}' "
                    f"({len(text)} chars, ~{len(text.split())} words)")

        response = await self._backend.generate(prompt, max_tokens=4096, temperature=0.2)

        # Track cost
        if hasattr(self._backend, "total_cost_usd"):
            self._generation_cost = self._backend.total_cost_usd - cost_before

        # Parse JSON from response
        owl_hierarchy, constraints = self._parse_response(response, domain_name)

        logger.info(
            f"Generated ontology: {len(owl_hierarchy)} types, "
            f"{len(constraints)} constraints, cost=${self._generation_cost:.4f}"
        )

        return owl_hierarchy, constraints

    async def generate_from_chunks(
        self,
        chunks: List[Dict[str, str]],
        domain_name: str,
        framework_name: str = "",
    ) -> Tuple[Dict[str, str], Dict[str, SemanticConstraint]]:
        """Generate ontology from KG chunks (already structured).

        Useful when the KG already has parsed regulation chunks.
        Compiles chunk summaries into a document for ontology generation.
        """
        # Build document from chunks
        doc_parts = []
        for chunk in chunks:
            text = chunk.get("text", "")
            ctype = chunk.get("type", "content")
            label = chunk.get("label", "")
            if text:
                header = f"[{label}]" if label else f"[{ctype}]"
                doc_parts.append(f"{header}\n{text}")

        document_text = "\n\n".join(doc_parts)
        return await self.generate_from_text(document_text, domain_name)

    def _parse_response(
        self,
        response: str,
        domain_name: str,
    ) -> Tuple[Dict[str, str], Dict[str, SemanticConstraint]]:
        """Parse the model's JSON response into OWL + SHACL structures."""
        # Extract JSON from response (handle markdown code blocks)
        json_text = response.strip()
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0].strip()
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse ontology JSON, attempting repair")
            data = self._repair_json(json_text)

        # Extract OWL hierarchy
        owl_hierarchy = data.get("owl_hierarchy", {})
        if not isinstance(owl_hierarchy, dict):
            owl_hierarchy = {}

        # Extract semantic constraints
        raw_constraints = data.get("semantic_constraints", [])
        constraints: Dict[str, SemanticConstraint] = {}

        if isinstance(raw_constraints, list):
            for rc in raw_constraints:
                if isinstance(rc, dict) and "entity_type" in rc:
                    constraint = SemanticConstraint(
                        entity_type=rc["entity_type"],
                        framework=rc.get("framework", ""),
                        own_framework_markers=rc.get("own_framework_markers", []),
                        scope_description=rc.get("scope_description", ""),
                        in_scope_topics=rc.get("in_scope_topics", []),
                        out_of_scope_topics=rc.get("out_of_scope_topics", []),
                        reasoning_rules=rc.get("reasoning_rules", []),
                        cross_reference_rules=rc.get("cross_reference_rules", {}),
                    )
                    constraints[rc["entity_type"]] = constraint

        return owl_hierarchy, constraints

    @staticmethod
    def _repair_json(text: str) -> Dict:
        """Attempt to repair malformed JSON."""
        # Try to find the outermost braces
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        # Last resort: return empty structure
        logger.error("Could not repair JSON, returning empty ontology")
        return {"owl_hierarchy": {}, "semantic_constraints": []}

    @staticmethod
    def constraints_to_dict(
        constraints: Dict[str, SemanticConstraint],
    ) -> List[Dict[str, Any]]:
        """Serialize constraints to JSON-compatible dicts."""
        return [asdict(c) for c in constraints.values()]

    @staticmethod
    def constraints_from_dict(
        data: List[Dict[str, Any]],
    ) -> Dict[str, SemanticConstraint]:
        """Deserialize constraints from JSON dicts."""
        result = {}
        for d in data:
            c = SemanticConstraint(**{
                k: v for k, v in d.items()
                if k in SemanticConstraint.__dataclass_fields__
            })
            result[c.entity_type] = c
        return result
