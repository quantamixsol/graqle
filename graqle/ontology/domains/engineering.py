"""Engineering domain — expanded skills for code, architecture, infra, security.

45 skills organized by engineering function (expands the 25 in skill_admin.py):
- Code Quality (8)
- Architecture (6)
- API & Integration (5)
- Data & Database (5)
- Infrastructure & DevOps (6)
- Security (6)
- Testing (5)
- Performance (4)
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.engineering
# risk: LOW (impact radius: 1 modules)
# consumers: sdk_self_audit
# dependencies: __future__, typing, skill_resolver
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import TYPE_CHECKING

from graqle.ontology.skill_resolver import Skill

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry


# ---------------------------------------------------------------------------
# OWL Class Hierarchy
# ---------------------------------------------------------------------------

ENGINEERING_CLASS_HIERARCHY: dict[str, str] = {
    "Engineering": "Thing",
    # Code entities (OWL canonical types)
    "MODULE": "Engineering",
    "CLASS": "MODULE",
    "FUNCTION": "MODULE",
    "COMPONENT": "MODULE",
    "ReactComponent": "COMPONENT",
    "APIEndpoint": "Engineering",
    "MIDDLEWARE": "Engineering",
    "HANDLER": "Engineering",
    # Data
    "DATABASE": "Engineering",
    "SCHEMA": "DATABASE",
    "MIGRATION": "DATABASE",
    "QUERY": "DATABASE",
    # Infra
    "SERVICE": "Engineering",
    "LAMBDA": "SERVICE",
    "CONTAINER": "SERVICE",
    "CDN": "SERVICE",
    "QUEUE": "SERVICE",
    # Config
    "CONFIG": "Engineering",
    "ENV_VAR": "CONFIG",
    "SECRET": "CONFIG",
    # CI/CD
    "PIPELINE": "Engineering",
    "DEPLOYMENT": "PIPELINE",
    "BUILD": "PIPELINE",
    # Testing
    "TEST_SUITE": "Engineering",
    "TEST_CASE": "TEST_SUITE",
    # ── Scanner-produced aliases (map to canonical OWL types) ──
    # These ensure skills resolve for types emitted by `graq scan repo .`
    "Function": "MODULE",          # scanner emits Function → inherits MODULE skills
    "Class": "MODULE",             # scanner emits Class → inherits MODULE skills
    "PythonModule": "MODULE",      # scanner emits PythonModule → IS a MODULE
    "PythonClass": "MODULE",       # scanner emits PythonClass
    "PythonFunction": "MODULE",    # scanner emits PythonFunction
    "TestFile": "TEST_SUITE",      # scanner emits TestFile → inherits TEST_SUITE skills
    "Config": "CONFIG",            # scanner emits Config → IS CONFIG
    "EnvVar": "ENV_VAR",           # scanner emits EnvVar → IS ENV_VAR
    "Dependency": "Engineering",   # scanner emits Dependency
    "Directory": "Engineering",    # scanner emits Directory
    "DatabaseModel": "DATABASE",   # scanner emits DatabaseModel → inherits DATABASE skills
    "DockerService": "CONTAINER",  # scanner emits DockerService → inherits CONTAINER skills
    "CIPipeline": "PIPELINE",      # scanner emits CIPipeline → inherits PIPELINE skills
    "JavaScriptModule": "MODULE",  # scanner emits JavaScriptModule → IS MODULE
}

# ---------------------------------------------------------------------------
# Entity Shapes
# ---------------------------------------------------------------------------

ENGINEERING_ENTITY_SHAPES: dict[str, dict] = {
    "MODULE": {"required": ["name"], "optional": ["file_path", "language", "imports", "exports"]},
    "APIEndpoint": {"required": ["path", "method"], "optional": ["auth", "rate_limit", "request_schema", "response_schema"]},
    "DATABASE": {"required": ["name", "engine"], "optional": ["tables", "connection_string"]},
    "SERVICE": {"required": ["name"], "optional": ["runtime", "region", "url", "env_vars"]},
    "LAMBDA": {"required": ["name", "handler"], "optional": ["runtime", "memory", "timeout", "env_vars", "layers"]},
}

# ---------------------------------------------------------------------------
# Relationship Shapes
# ---------------------------------------------------------------------------

ENGINEERING_RELATIONSHIP_SHAPES: dict[str, dict] = {
    "IMPORTS": {"domain": {"MODULE", "CLASS", "FUNCTION", "COMPONENT"}, "range": {"MODULE", "CLASS", "FUNCTION"}},
    "CALLS": {"domain": {"MODULE", "FUNCTION", "HANDLER"}, "range": {"APIEndpoint", "FUNCTION", "SERVICE"}},
    "DEPENDS_ON": {"domain": {"SERVICE", "LAMBDA"}, "range": {"SERVICE", "DATABASE", "QUEUE"}},
    "READS_FROM": {"domain": {"MODULE", "SERVICE", "HANDLER"}, "range": {"DATABASE", "CONFIG", "QUEUE"}},
    "WRITES_TO": {"domain": {"MODULE", "SERVICE", "HANDLER"}, "range": {"DATABASE", "QUEUE"}},
    "DEPLOYS_TO": {"domain": {"DEPLOYMENT"}, "range": {"SERVICE", "LAMBDA", "CONTAINER"}},
    "TESTS": {"domain": {"TEST_CASE", "TEST_SUITE"}, "range": {"MODULE", "FUNCTION", "APIEndpoint"}},
    "CONTAINS": {"domain": {"MODULE"}, "range": {"CLASS", "FUNCTION"}},
    "CONFIGURES": {"domain": {"CONFIG", "ENV_VAR"}, "range": {"SERVICE", "LAMBDA"}},
}

# ---------------------------------------------------------------------------
# Skill Map
# ---------------------------------------------------------------------------

ENGINEERING_SKILL_MAP: dict[str, list[str]] = {
    # Branch level (all engineering entities)
    "Engineering": ["analyze_dependencies", "check_error_handling", "trace_data_flow"],
    # Code
    "MODULE": ["code_review", "complexity_analysis", "dead_code_detection", "naming_convention_check"],
    "CLASS": ["code_review", "class_design_review", "inheritance_analysis"],
    "FUNCTION": ["code_review", "complexity_analysis", "input_validation_check"],
    "COMPONENT": ["analyze_react_component", "trace_state_flow", "accessibility_check"],
    "ReactComponent": ["analyze_react_component", "trace_state_flow", "analyze_css_styles", "performance_profiling"],
    # API
    "APIEndpoint": ["analyze_api_endpoint", "api_contract_check", "rate_limit_review", "audit_auth_flow", "check_injection_risk"],
    "MIDDLEWARE": ["middleware_chain_analysis", "audit_auth_flow"],
    "HANDLER": ["error_handling_review", "input_validation_check", "check_injection_risk"],
    # Data
    "DATABASE": ["analyze_schema", "query_optimization", "index_analysis"],
    "SCHEMA": ["analyze_schema", "migration_safety_check"],
    "MIGRATION": ["migration_safety_check", "rollback_plan_check"],
    "QUERY": ["query_optimization", "check_injection_risk"],
    # Infra
    "SERVICE": ["service_health_check", "analyze_deployment", "check_env_config"],
    "LAMBDA": ["lambda_config_review", "cold_start_analysis", "check_env_config"],
    "CONTAINER": ["container_config_review", "resource_limit_check"],
    "CDN": ["cache_policy_review", "origin_shield_check"],
    # Config
    "CONFIG": ["check_env_config", "secret_rotation_check"],
    "ENV_VAR": ["check_env_config", "flag_secrets"],
    "SECRET": ["flag_secrets", "secret_rotation_check"],
    # CI/CD
    "PIPELINE": ["pipeline_efficiency", "deploy_safety_check"],
    "DEPLOYMENT": ["deploy_safety_check", "rollback_plan_check"],
    # Testing
    "TEST_SUITE": ["identify_test_gaps", "test_coverage_analysis"],
    "TEST_CASE": ["suggest_edge_cases", "analyze_test_quality"],
    # ── Scanner-produced type aliases ──
    # Skills resolve for types emitted by `graq scan repo .`
    "Function": ["code_review", "complexity_analysis", "input_validation_check"],
    "Class": ["code_review", "class_design_review", "inheritance_analysis"],
    "PythonModule": ["code_review", "complexity_analysis", "dead_code_detection", "naming_convention_check"],
    "PythonClass": ["code_review", "class_design_review", "inheritance_analysis"],
    "PythonFunction": ["code_review", "complexity_analysis", "input_validation_check"],
    "TestFile": ["identify_test_gaps", "test_coverage_analysis", "analyze_test_quality"],
    "Config": ["check_env_config", "secret_rotation_check"],
    "EnvVar": ["check_env_config", "flag_secrets"],
    "DatabaseModel": ["analyze_schema", "check_data_integrity"],
    "DockerService": ["container_config_review", "resource_limit_check"],
    "CIPipeline": ["pipeline_efficiency", "deploy_safety_check"],
    "JavaScriptModule": ["code_review", "complexity_analysis", "dead_code_detection"],
    "Dependency": ["check_dependency_risk"],
}

# ---------------------------------------------------------------------------
# Skill Definitions (45 skills)
# ---------------------------------------------------------------------------

ENGINEERING_SKILLS: dict[str, Skill] = {
    # -- Code Quality --
    "code_review": Skill(
        name="code_review",
        description="Review code for correctness, style, and best practices",
        handler_prompt=(
            "Review the code for: correctness, readability, error handling, naming conventions, "
            "SOLID principles, and language idioms. Flag anti-patterns."
        ),
    ),
    "complexity_analysis": Skill(
        name="complexity_analysis",
        description="Analyze code complexity (cyclomatic, cognitive)",
        handler_prompt="Assess cyclomatic and cognitive complexity. Flag functions >10 complexity. Suggest decomposition.",
    ),
    "dead_code_detection": Skill(
        name="dead_code_detection",
        description="Detect unreachable or unused code",
        handler_prompt="Identify unused imports, unreachable branches, dead functions, and commented-out code.",
    ),
    "naming_convention_check": Skill(
        name="naming_convention_check",
        description="Check naming conventions consistency",
        handler_prompt="Verify naming follows project conventions: camelCase/snake_case, prefixes, file naming patterns.",
    ),
    "class_design_review": Skill(
        name="class_design_review",
        description="Review class design and responsibility",
        handler_prompt="Check Single Responsibility, interface segregation, composition over inheritance. Flag god classes.",
    ),
    "inheritance_analysis": Skill(
        name="inheritance_analysis",
        description="Analyze class inheritance hierarchy",
        handler_prompt="Review inheritance depth, diamond inheritance, Liskov substitution compliance.",
    ),
    "input_validation_check": Skill(
        name="input_validation_check",
        description="Check input validation at system boundaries",
        handler_prompt="Verify all external inputs (user, API, file) are validated, sanitized, and typed.",
    ),
    "error_handling_review": Skill(
        name="error_handling_review",
        description="Review error handling completeness",
        handler_prompt="Check: catch specificity, error propagation, user-facing messages, logging, recovery paths.",
    ),
    # -- Architecture --
    "analyze_dependencies": Skill(
        name="analyze_dependencies",
        description="Analyze dependency graph and coupling",
        handler_prompt="Map dependencies. Flag circular deps, tight coupling, and unstable dependencies.",
    ),
    "trace_data_flow": Skill(
        name="trace_data_flow",
        description="Trace data flow through the system",
        handler_prompt="Map how data flows from input to output: transformations, validations, storage, and output format.",
    ),
    "check_error_handling": Skill(
        name="check_error_handling",
        description="Check system-wide error handling strategy",
        handler_prompt="Review error boundaries, fallback strategies, circuit breakers, and graceful degradation.",
    ),
    "middleware_chain_analysis": Skill(
        name="middleware_chain_analysis",
        description="Analyze middleware/interceptor chain order and correctness",
        handler_prompt="Verify middleware order: auth before business logic, logging at edges, error handler last.",
    ),
    "accessibility_check": Skill(
        name="accessibility_check",
        description="Check component accessibility (WCAG compliance)",
        handler_prompt="Check ARIA labels, keyboard navigation, color contrast, screen reader compatibility.",
    ),
    "analyze_react_component": Skill(
        name="analyze_react_component",
        description="Analyze React component structure and patterns",
        handler_prompt=(
            "Review props, state management, hooks, event handlers, child tree. "
            "Flag missing memo, inline functions in render, excessive re-renders."
        ),
    ),
    # -- API & Integration --
    "analyze_api_endpoint": Skill(
        name="analyze_api_endpoint",
        description="Analyze API endpoint design and implementation",
        handler_prompt="Review: HTTP method, path design, request/response schema, auth, error responses, versioning.",
    ),
    "api_contract_check": Skill(
        name="api_contract_check",
        description="Verify API contract compliance (OpenAPI/schema)",
        handler_prompt="Check request/response matches documented schema. Flag breaking changes.",
    ),
    "rate_limit_review": Skill(
        name="rate_limit_review",
        description="Review rate limiting configuration",
        handler_prompt="Check rate limits: per-user, per-endpoint, burst handling, response headers (429, Retry-After).",
    ),
    "trace_state_flow": Skill(
        name="trace_state_flow",
        description="Trace state flow through frontend components",
        handler_prompt="Map data flow: props, context, stores, URL state. Identify unnecessary re-renders.",
    ),
    "analyze_css_styles": Skill(
        name="analyze_css_styles",
        description="Analyze CSS/styling patterns and issues",
        handler_prompt="Check: specificity conflicts, unused styles, responsive breakpoints, CSS-in-JS performance.",
    ),
    # -- Data & Database --
    "analyze_schema": Skill(
        name="analyze_schema",
        description="Analyze database schema design",
        handler_prompt="Review normalization, relationships, indexes, constraints, and naming conventions.",
    ),
    "query_optimization": Skill(
        name="query_optimization",
        description="Optimize database queries for performance",
        handler_prompt="Analyze query plan. Check: N+1 queries, missing indexes, full table scans, join order.",
    ),
    "index_analysis": Skill(
        name="index_analysis",
        description="Analyze database index usage and recommendations",
        handler_prompt="Review existing indexes vs query patterns. Identify missing and unused indexes.",
    ),
    "migration_safety_check": Skill(
        name="migration_safety_check",
        description="Check database migration safety",
        handler_prompt="Verify: backwards compatibility, zero-downtime strategy, rollback plan, data preservation.",
    ),
    "check_data_integrity": Skill(
        name="check_data_integrity",
        description="Check data integrity constraints and validation",
        handler_prompt="Verify foreign keys, unique constraints, check constraints, and application-level validation.",
    ),
    # -- Infrastructure --
    "analyze_deployment": Skill(
        name="analyze_deployment",
        description="Analyze deployment configuration and strategy",
        handler_prompt="Review: deployment strategy (blue-green, canary), rollback plan, health checks, env separation.",
    ),
    "check_env_config": Skill(
        name="check_env_config",
        description="Check environment variable configuration",
        handler_prompt="Verify all required env vars are set, secrets are not hardcoded, defaults are safe.",
    ),
    "lambda_config_review": Skill(
        name="lambda_config_review",
        description="Review Lambda function configuration",
        handler_prompt="Check: memory, timeout, handler path, layers, env vars, VPC config, concurrency limits.",
    ),
    "cold_start_analysis": Skill(
        name="cold_start_analysis",
        description="Analyze serverless cold start impact",
        handler_prompt="Estimate cold start time. Check: package size, init code, provisioned concurrency, keep-warm.",
    ),
    "container_config_review": Skill(
        name="container_config_review",
        description="Review container/Docker configuration",
        handler_prompt="Check: base image, multi-stage build, security scanning, resource limits, health check.",
    ),
    "resource_limit_check": Skill(
        name="resource_limit_check",
        description="Check compute resource limits and quotas",
        handler_prompt="Verify CPU/memory limits, auto-scaling config, service quotas, and burst capacity.",
    ),
    # -- Security --
    "audit_auth_flow": Skill(
        name="audit_auth_flow",
        description="Audit authentication and authorization flow",
        handler_prompt="Review: auth mechanism, token handling, session management, RBAC, privilege escalation risks.",
    ),
    "check_injection_risk": Skill(
        name="check_injection_risk",
        description="Check for injection vulnerabilities (SQL, XSS, command)",
        handler_prompt="Scan for: SQL injection, XSS, command injection, template injection, path traversal.",
    ),
    "flag_secrets": Skill(
        name="flag_secrets",
        description="Flag hardcoded secrets and credentials",
        handler_prompt="Scan for: API keys, passwords, tokens, connection strings in code. Check .gitignore.",
    ),
    "secret_rotation_check": Skill(
        name="secret_rotation_check",
        description="Check secret rotation policy and implementation",
        handler_prompt="Verify: rotation schedule, automated rotation, zero-downtime rotation, audit trail.",
    ),
    "check_dependency_risk": Skill(
        name="check_dependency_risk",
        description="Check dependency vulnerabilities and supply chain risk",
        handler_prompt="Check: known CVEs, outdated deps, abandoned packages, typosquatting risk, lock file.",
    ),
    "cache_policy_review": Skill(
        name="cache_policy_review",
        description="Review caching policy and invalidation strategy",
        handler_prompt="Check: cache headers, TTL, invalidation strategy, stale-while-revalidate, cache keys.",
    ),
    # -- Testing --
    "identify_test_gaps": Skill(
        name="identify_test_gaps",
        description="Identify gaps in test coverage",
        handler_prompt="Identify untested: edge cases, error paths, boundary conditions, integration points.",
    ),
    "suggest_edge_cases": Skill(
        name="suggest_edge_cases",
        description="Suggest edge cases for testing",
        handler_prompt="Suggest edge cases: null/empty, boundary values, concurrent access, error cascades.",
    ),
    "analyze_test_quality": Skill(
        name="analyze_test_quality",
        description="Analyze test quality and reliability",
        handler_prompt="Review: assertion quality, test isolation, flakiness risk, setup/teardown, naming.",
    ),
    "test_coverage_analysis": Skill(
        name="test_coverage_analysis",
        description="Analyze test coverage patterns",
        handler_prompt="Map coverage: unit vs integration vs e2e balance, critical path coverage, mock boundaries.",
    ),
    "rollback_plan_check": Skill(
        name="rollback_plan_check",
        description="Verify rollback plan exists and is tested",
        handler_prompt="Check: rollback steps documented, tested in staging, data rollback strategy, communication plan.",
    ),
    # -- Performance --
    "performance_profiling": Skill(
        name="performance_profiling",
        description="Profile performance bottlenecks",
        handler_prompt="Identify: render bottlenecks, memory leaks, unnecessary computations, bundle size issues.",
    ),
    "pipeline_efficiency": Skill(
        name="pipeline_efficiency",
        description="Analyze CI/CD pipeline efficiency",
        handler_prompt="Review: build time, parallelization, caching, artifact reuse, flaky test handling.",
    ),
    "deploy_safety_check": Skill(
        name="deploy_safety_check",
        description="Pre-deployment safety verification",
        handler_prompt="Verify: all tests pass, no breaking changes, env vars set, rollback ready, monitoring configured.",
    ),
    "service_health_check": Skill(
        name="service_health_check",
        description="Check service health and monitoring",
        handler_prompt="Verify: health endpoint, liveness/readiness probes, alerting, logging, metrics collection.",
    ),
}


def register_engineering_domain(registry: DomainRegistry) -> None:
    """Register the engineering domain with a DomainRegistry."""
    registry.register_domain(
        name="engineering",
        class_hierarchy=ENGINEERING_CLASS_HIERARCHY,
        entity_shapes=ENGINEERING_ENTITY_SHAPES,
        relationship_shapes=ENGINEERING_RELATIONSHIP_SHAPES,
        skill_map=ENGINEERING_SKILL_MAP,
    )
