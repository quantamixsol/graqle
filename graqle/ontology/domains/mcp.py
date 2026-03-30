"""MCP Protocol domain — first-class protocol-typed knowledge graph nodes.

R3 Research Handoff (ADR-128): Represents MCP protocol entities as typed KG nodes
enabling protocol-aware reasoning, schema validation at reasoning time, and
cross-domain blast radius analysis.

Entity types (8): MCP_TOOL, MCP_REQUEST, MCP_RESPONSE, MCP_NOTIFICATION,
                  MCP_SERVER, MCP_CLIENT, MCP_TRANSPORT, MCP_SCHEMA

Relationships (7): EXPOSES_TOOL, CALLS_TOOL, HANDLES_REQUEST, RETURNS_RESPONSE,
                   ROUTES_TO, HAS_PARAM_SCHEMA, ALIASES

Skills (4): PROTOCOL_TRACE, SCHEMA_VALIDATE, RPC_LINEAGE, TRANSPORT_CONSTRAINT_CHECK

Output Gates (3): validate_rpc_trace, validate_schema_params, validate_transport_config
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.mcp
# risk: LOW (new domain — zero existing consumers)
# consumers: mcp_dev_server (all graq_*/kogni_* tools), skill_pipeline
# constraints: NEVER expose weight values or formula internals (TS-1..TS-4)
# research: R3 Functional Specification (graq_predict 72%+89.5%, novelty 0.82+0.91)
# adr: ADR-128
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import TYPE_CHECKING

from graqle.ontology.skill_resolver import Skill

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry


# ---------------------------------------------------------------------------
# OWL Class Hierarchy
# ---------------------------------------------------------------------------
# ZERO overlap with coding.py — verified by test_mcp_coding_hierarchy_disjoint
# Parent "Mcp" → 8 MCP entity types. No scanner aliases needed (MCP nodes
# are created by reclassification, not by file scanning).

MCP_CLASS_HIERARCHY: dict[str, str] = {
    "Mcp": "Thing",
    "MCP_TOOL": "Mcp",
    "MCP_REQUEST": "Mcp",
    "MCP_RESPONSE": "Mcp",
    "MCP_NOTIFICATION": "Mcp",
    "MCP_SERVER": "Mcp",
    "MCP_CLIENT": "Mcp",
    "MCP_TRANSPORT": "Mcp",
    "MCP_SCHEMA": "Mcp",
}


# ---------------------------------------------------------------------------
# Entity Shapes
# ---------------------------------------------------------------------------

MCP_ENTITY_SHAPES: dict[str, dict] = {
    "MCP_TOOL": {
        "required": ["name", "description"],
        "optional": [
            "input_schema", "output_schema", "group", "is_alias",
            "alias_target", "transport_support", "rpc_method",
            "side_effects", "idempotent", "cost_tier", "timeout_ms",
        ],
    },
    "MCP_REQUEST": {
        "required": ["method"],
        "optional": [
            "params", "request_id", "jsonrpc_version",
            "timestamp", "caller_id",
        ],
    },
    "MCP_RESPONSE": {
        "required": ["request_id"],
        "optional": [
            "result", "error_code", "error_message",
            "content_type", "is_error", "is_streaming",
            "latency_ms",
        ],
    },
    "MCP_NOTIFICATION": {
        "required": ["method"],
        "optional": [
            "params", "severity", "timestamp", "source",
        ],
    },
    "MCP_SERVER": {
        "required": ["name"],
        "optional": [
            "transport_type", "host", "port", "auth_required",
            "version", "capabilities", "tool_count",
        ],
    },
    "MCP_CLIENT": {
        "required": ["name"],
        "optional": [
            "client_type", "version", "supported_transports",
            "auth_method",
        ],
    },
    "MCP_TRANSPORT": {
        "required": ["transport_type"],
        "optional": [
            "latency_profile", "auth_constraints",
            "framing", "max_message_size",
        ],
    },
    "MCP_SCHEMA": {
        "required": ["name", "json_schema"],
        "optional": [
            "required_params", "param_of", "schema_format",
            "schema_version",
        ],
    },
}


# ---------------------------------------------------------------------------
# Relationship Shapes
# ---------------------------------------------------------------------------

MCP_RELATIONSHIP_SHAPES: dict[str, dict] = {
    "EXPOSES_TOOL": {
        "domain": {"MCP_SERVER"},
        "range": {"MCP_TOOL"},
    },
    "CALLS_TOOL": {
        "domain": {"MCP_CLIENT"},
        "range": {"MCP_TOOL"},
    },
    "HANDLES_REQUEST": {
        "domain": {"MCP_TOOL"},
        "range": {"CodeFunction", "Function"},
    },
    "RETURNS_RESPONSE": {
        "domain": {"CodeFunction", "Function"},
        "range": {"MCP_RESPONSE"},
    },
    "ROUTES_TO": {
        "domain": {"MCP_SERVER"},
        "range": {"MCP_TOOL"},
    },
    "HAS_PARAM_SCHEMA": {
        "domain": {"MCP_TOOL"},
        "range": {"MCP_SCHEMA"},
    },
    "ALIASES": {
        "domain": {"MCP_TOOL"},
        "range": {"MCP_TOOL"},
    },
}


# ---------------------------------------------------------------------------
# Skill Map
# ---------------------------------------------------------------------------

MCP_SKILL_MAP: dict[str, list[str]] = {
    # Branch level — all MCP entities
    "Mcp": ["PROTOCOL_TRACE", "RPC_LINEAGE"],
    # Tool level
    "MCP_TOOL": [
        "PROTOCOL_TRACE", "SCHEMA_VALIDATE", "RPC_LINEAGE",
        "TRANSPORT_CONSTRAINT_CHECK",
    ],
    "MCP_REQUEST": ["PROTOCOL_TRACE", "RPC_LINEAGE"],
    "MCP_RESPONSE": ["PROTOCOL_TRACE", "RPC_LINEAGE"],
    "MCP_NOTIFICATION": ["RPC_LINEAGE"],
    "MCP_SERVER": [
        "PROTOCOL_TRACE", "TRANSPORT_CONSTRAINT_CHECK",
    ],
    "MCP_CLIENT": ["PROTOCOL_TRACE", "TRANSPORT_CONSTRAINT_CHECK"],
    "MCP_TRANSPORT": ["TRANSPORT_CONSTRAINT_CHECK"],
    "MCP_SCHEMA": ["SCHEMA_VALIDATE"],
}


# ---------------------------------------------------------------------------
# Skill Objects
# ---------------------------------------------------------------------------

MCP_SKILLS: dict[str, Skill] = {
    "PROTOCOL_TRACE": Skill(
        name="PROTOCOL_TRACE",
        description=(
            "Follow MCP RPC chains through the knowledge graph: "
            "CLIENT →[CALLS_TOOL]→ TOOL →[HANDLES_REQUEST]→ HANDLER "
            "→[RETURNS_RESPONSE]→ RESPONSE. "
            "Annotates reasoning with transport context and latency estimates."
        ),
        handler_prompt=(
            "You are a protocol trace analyst with access to the MCP knowledge graph. "
            "Given a query involving MCP tools or protocol elements: "
            "(1) identify the relevant MCP_TOOL node, "
            "(2) trace the RPC chain: CALLS_TOOL → HANDLES_REQUEST → RETURNS_RESPONSE, "
            "(3) resolve kogni_* aliases via ALIASES edges at zero cost, "
            "(4) annotate each step with transport context "
            "(stdio: near_zero latency, process_level auth; "
            "SSE: network_variable latency, token_or_oauth auth), "
            "(5) validate parameters against MCP_SCHEMA nodes via HAS_PARAM_SCHEMA, "
            "(6) produce a protocol trace with estimated total latency. "
            "Output a structured ProtocolTrace with chain steps and transport annotations."
        ),
    ),
    "SCHEMA_VALIDATE": Skill(
        name="SCHEMA_VALIDATE",
        description=(
            "Validate MCP tool parameters against their JSON Schema definitions. "
            "Detects breaking changes, missing required params, and type mismatches."
        ),
        handler_prompt=(
            "You are a schema validation assistant for MCP tools. "
            "Given a tool invocation and its MCP_SCHEMA nodes: "
            "(1) validate all required parameters are present, "
            "(2) check parameter types match JSON Schema definitions, "
            "(3) detect breaking changes (removed required params, type changes), "
            "(4) flag deprecated parameters. "
            "Output a structured SchemaValidationResult with: "
            "valid (bool), errors (list), warnings (list), breaking_changes (list)."
        ),
    ),
    "RPC_LINEAGE": Skill(
        name="RPC_LINEAGE",
        description=(
            "Trace the full lineage of an MCP request from client to server to handler "
            "and back, producing an audit trail of every hop."
        ),
        handler_prompt=(
            "You are an RPC lineage tracer. "
            "Given an MCP request or tool call: "
            "(1) identify the originating MCP_CLIENT, "
            "(2) trace through MCP_SERVER → ROUTES_TO → MCP_TOOL, "
            "(3) follow HANDLES_REQUEST to the handler function, "
            "(4) trace RETURNS_RESPONSE back to the client, "
            "(5) record timestamp, latency, and auth context at each hop. "
            "Output a structured RpcLineage with ordered hop list and total latency."
        ),
    ),
    "TRANSPORT_CONSTRAINT_CHECK": Skill(
        name="TRANSPORT_CONSTRAINT_CHECK",
        description=(
            "Verify that MCP transport configuration matches deployment constraints: "
            "stdio for local, SSE for remote, auth requirements, message size limits."
        ),
        handler_prompt=(
            "You are a transport constraint checker for MCP deployments. "
            "Given an MCP_SERVER or MCP_CLIENT node and its transport configuration: "
            "(1) verify transport type matches deployment mode "
            "(stdio for local CLI, SSE for remote/cloud), "
            "(2) check auth requirements are satisfied, "
            "(3) validate message size limits for the transport, "
            "(4) flag mismatches between client and server transport expectations. "
            "Output a structured TransportCheckResult with: "
            "compatible (bool), issues (list), recommendations (list)."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Output Gates
# ---------------------------------------------------------------------------

MCP_OUTPUT_GATES: dict[str, dict] = {
    "validate_rpc_trace": {
        "description": (
            "Verify a protocol trace contains: "
            "non-empty chain_steps list, "
            "each step has from_node/to_node/edge_type, "
            "total_estimated_latency is non-negative. "
            "Reject if chain is broken (missing HANDLES_REQUEST or RETURNS_RESPONSE)."
        ),
        "required": ["chain_steps", "total_estimated_latency"],
    },
    "validate_schema_params": {
        "description": (
            "Verify schema validation output contains: "
            "valid (bool), errors list (may be empty), "
            "warnings list (may be empty). "
            "Reject if valid is True but errors list is non-empty."
        ),
        "required": ["valid", "errors"],
    },
    "validate_transport_config": {
        "description": (
            "Verify transport check output contains: "
            "compatible (bool), issues list, recommendations list. "
            "Reject if compatible is True but issues list is non-empty."
        ),
        "required": ["compatible", "issues"],
    },
}


# ---------------------------------------------------------------------------
# Registration Function
# ---------------------------------------------------------------------------

def register_mcp_domain(registry: DomainRegistry) -> None:
    """Register the MCP protocol domain into the given DomainRegistry."""
    registry.register_domain(
        name="mcp",
        class_hierarchy=MCP_CLASS_HIERARCHY,
        entity_shapes=MCP_ENTITY_SHAPES,
        relationship_shapes=MCP_RELATIONSHIP_SHAPES,
        skill_map=MCP_SKILL_MAP,
        output_shapes=MCP_OUTPUT_GATES,
    )
