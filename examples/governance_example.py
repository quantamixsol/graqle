"""Graqle Governance Example — SHACL constraints for a codebase KG.

This example shows how to apply governance constraints to a software
engineering knowledge graph. The constraints ensure that:
1. Security-related nodes only produce security-relevant reasoning
2. Test nodes stay within testing scope
3. API nodes respect API contract boundaries
4. Cross-domain references are properly attributed

Usage:
    python examples/governance_example.py

Requirements:
    pip install graqle
    export ANTHROPIC_API_KEY=...  (or use Ollama for local)
"""

import asyncio
from graqle.core.graph import Graqle
from graqle.config.settings import GraqleConfig


def build_example_graph() -> dict:
    """Build a small codebase KG with governance-relevant structure."""
    return {
        "nodes": [
            {
                "id": "auth_service",
                "label": "AuthService",
                "type": "SecurityModule",
                "description": "Handles JWT authentication, password hashing, and session management",
                "properties": {
                    "chunks": [
                        {"type": "function", "text": "def verify_jwt(token): Validates JWT token, checks expiry and signature"},
                        {"type": "function", "text": "def hash_password(password): Uses bcrypt with 12 rounds for password hashing"},
                        {"type": "function", "text": "def create_session(user_id): Creates authenticated session with CSRF token"},
                    ],
                },
            },
            {
                "id": "user_api",
                "label": "UserAPI",
                "type": "APIEndpoint",
                "description": "REST API for user CRUD operations with input validation",
                "properties": {
                    "chunks": [
                        {"type": "function", "text": "def create_user(data): POST /users — creates new user with email validation"},
                        {"type": "function", "text": "def get_user(user_id): GET /users/:id — returns user profile (no password)"},
                        {"type": "function", "text": "def update_user(user_id, data): PUT /users/:id — updates user fields with schema validation"},
                    ],
                },
            },
            {
                "id": "payment_service",
                "label": "PaymentService",
                "type": "BusinessLogic",
                "description": "Stripe integration for subscription billing and invoice management",
                "properties": {
                    "chunks": [
                        {"type": "function", "text": "def create_subscription(user_id, plan): Creates Stripe subscription with webhook"},
                        {"type": "function", "text": "def process_invoice(invoice_id): Processes and records Stripe invoice payment"},
                    ],
                },
            },
            {
                "id": "test_auth",
                "label": "TestAuth",
                "type": "TestSuite",
                "description": "Unit and integration tests for authentication flows",
                "properties": {
                    "chunks": [
                        {"type": "function", "text": "def test_jwt_verify(): Tests valid/invalid/expired JWT tokens"},
                        {"type": "function", "text": "def test_password_hash(): Tests bcrypt hashing and verification"},
                        {"type": "function", "text": "def test_session_creation(): Tests session lifecycle with mocked database"},
                    ],
                },
            },
            {
                "id": "database",
                "label": "DatabaseLayer",
                "type": "Infrastructure",
                "description": "PostgreSQL connection pool, migrations, and query builder",
                "properties": {
                    "chunks": [
                        {"type": "function", "text": "def get_connection(): Returns pooled PostgreSQL connection with retry"},
                        {"type": "function", "text": "def run_migration(version): Applies database schema migration with rollback"},
                    ],
                },
            },
        ],
        "links": [
            {"source": "user_api", "target": "auth_service", "relationship": "DEPENDS_ON"},
            {"source": "user_api", "target": "database", "relationship": "DEPENDS_ON"},
            {"source": "payment_service", "target": "auth_service", "relationship": "DEPENDS_ON"},
            {"source": "payment_service", "target": "database", "relationship": "DEPENDS_ON"},
            {"source": "test_auth", "target": "auth_service", "relationship": "TESTS"},
            {"source": "auth_service", "target": "database", "relationship": "DEPENDS_ON"},
        ],
    }


def register_codebase_governance(graph: Graqle) -> None:
    """Register governance constraints for a software codebase.

    This demonstrates how SHACL-style constraints work outside
    the regulatory domain — enforcing software engineering best
    practices through the reasoning pipeline.
    """
    try:
        from graqle.ontology.semantic_shacl_gate import (
            SemanticSHACLGate,
            SemanticConstraint,
        )
        from graqle.ontology.domain_registry import DomainRegistry, DomainOntology

        # Create domain registry
        registry = DomainRegistry()

        # Register a "software engineering" domain
        sw_domain = DomainOntology(
            name="software_engineering",
            entity_types=["SecurityModule", "APIEndpoint", "BusinessLogic",
                          "TestSuite", "Infrastructure"],
            constraints={
                "SecurityModule": SemanticConstraint(
                    own_framework_markers=["authentication", "authorization",
                                           "JWT", "session", "CSRF", "encryption",
                                           "hashing", "security"],
                    other_framework_markers={
                        "testing": ["test", "mock", "fixture", "assert"],
                        "business_logic": ["payment", "subscription", "billing"],
                    },
                    in_scope_topics=["authentication", "authorization",
                                     "session management", "token validation",
                                     "password security", "CSRF protection"],
                    out_of_scope_topics=["UI rendering", "CSS styling",
                                         "marketing copy", "analytics"],
                    reasoning_rules=[
                        "Security modules must cite specific security patterns (JWT, bcrypt, CSRF)",
                        "Cross-references to testing should clarify test vs production context",
                        "Never suggest disabling security features even for 'simplicity'",
                    ],
                ),
                "APIEndpoint": SemanticConstraint(
                    own_framework_markers=["REST", "API", "endpoint", "route",
                                           "HTTP", "request", "response",
                                           "validation", "schema"],
                    other_framework_markers={
                        "security": ["auth", "JWT", "token", "permission"],
                        "database": ["SQL", "query", "migration", "schema"],
                    },
                    in_scope_topics=["request handling", "input validation",
                                     "response formatting", "error handling",
                                     "API versioning", "rate limiting"],
                    out_of_scope_topics=["database internals", "deployment",
                                         "monitoring", "logging infrastructure"],
                    reasoning_rules=[
                        "API endpoints must specify HTTP methods and paths",
                        "Input validation rules must be mentioned for mutation endpoints",
                        "Security requirements (auth, rate limiting) must be stated",
                    ],
                ),
                "TestSuite": SemanticConstraint(
                    own_framework_markers=["test", "assert", "mock", "fixture",
                                           "setup", "teardown", "coverage"],
                    other_framework_markers={},
                    in_scope_topics=["test coverage", "test patterns",
                                     "mocking strategies", "test data"],
                    out_of_scope_topics=["production deployment",
                                         "user-facing features",
                                         "business requirements"],
                    reasoning_rules=[
                        "Test nodes should focus on test coverage and test strategy",
                        "References to production code should specify what is being tested",
                        "Test recommendations should include both positive and negative cases",
                    ],
                ),
            },
        )
        registry.register(sw_domain)

        print("Governance constraints registered for software engineering domain")
        print(f"  Entity types: {sw_domain.entity_types}")
        print(f"  Constrained types: {list(sw_domain.constraints.keys())}")

    except ImportError as e:
        print(f"Governance module not available: {e}")
        print("Install with: pip install graqle")


async def main():
    """Demonstrate governance-constrained reasoning on a codebase KG."""
    print("=" * 60)
    print("Graqle Governance Example — Codebase KG")
    print("=" * 60)

    # Build the graph
    graph_data = build_example_graph()
    print(f"\nGraph: {len(graph_data['nodes'])} nodes, {len(graph_data['links'])} edges")

    # Load into Graqle
    config = GraqleConfig.default()
    config.activation.max_nodes = 5  # Small graph, use all nodes
    config.observer.enabled = True   # v0.12: on by default

    graph = Graqle(config=config)

    # Add nodes and edges
    from graqle.core.node import CogniNode
    from graqle.core.types import Edge
    for node_data in graph_data["nodes"]:
        node = CogniNode(
            id=node_data["id"],
            label=node_data["label"],
            entity_type=node_data["type"],
            description=node_data["description"],
            properties=node_data.get("properties", {}),
        )
        graph.add_node(node)

    for link in graph_data["links"]:
        edge = Edge(
            id=f"{link['source']}->{link['target']}",
            source_id=link["source"],
            target_id=link["target"],
            relationship=link["relationship"],
        )
        graph.add_edge(edge)

    # Register governance constraints
    register_codebase_governance(graph)

    print(f"\nGraph loaded: {len(graph)} nodes")
    print("\nExample queries you can run:")
    print("  1. 'How does AuthService handle password security?'")
    print("  2. 'What are the security implications of the UserAPI?'")
    print("  3. 'How should TestAuth be structured to cover edge cases?'")
    print("\nWith governance, SecurityModule nodes will stay focused on")
    print("security topics and properly attribute cross-domain references.")

    # Note: actual reasoning requires a backend (Anthropic, Ollama, etc.)
    # Uncomment below to run with a real backend:
    #
    # from graqle.backends.api import AnthropicBackend
    # backend = AnthropicBackend(model="claude-haiku-4-5-20251001")
    # graph.set_default_backend(backend)
    # result = await graph.areason("How does AuthService handle password security?")
    # print(f"\nAnswer: {result.answer}")
    # print(f"Confidence: {result.confidence:.0%}")
    # print(f"Health: {result.metadata.get('health_score', 'N/A')}")


if __name__ == "__main__":
    asyncio.run(main())
