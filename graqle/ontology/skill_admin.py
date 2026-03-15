"""Skill Admin — hybrid runtime skill assignment for node agents.

Assigns domain-specific skills to nodes at activation time using a
three-layer fused scoring system:

1. **Regex exact match** (first pass): Code patterns like @app.get, useState,
   SELECT * FROM get guaranteed skill assignments. Precision: 100%.
2. **Semantic similarity** (second pass): Embeds query+context via Titan V2
   (best embedding model), cosine similarity fills remaining slots.
3. **Type mapping** (structural boost): entity_type -> guaranteed skills,
   boosted in final ranking.

The hybrid approach beats either method alone:
- Regex catches exact code patterns that embeddings might miss
- Semantic catches intent/conceptual queries that regex can't handle
- Fused scoring combines both signals for optimal skill selection

Skill condensation: Top-2 skills get full handler_prompt (detailed HOW),
skills 3-5 get summary-only (saves ~60% tokens on skill injection).

Cost: One Titan V2 embedding per query (~$0.0001), zero LLM calls.
Inspired by VoltAgent/awesome-agent-skills taxonomy (549+ skills).
"""

# ── graqle:intelligence ──
# module: graqle.ontology.skill_admin
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, logging, re, typing, numpy +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

import numpy as np

from graqle.ontology.skill_resolver import Skill

logger = logging.getLogger("graqle.ontology.skill_admin")


# ---------------------------------------------------------------------------
# Domain Skill Library (25 skills across 9 domains)
# ---------------------------------------------------------------------------
# Each skill has a semantic_text used for embedding: a natural language
# description of WHEN this skill should be used (not just what it does).
# This is the key to semantic matching quality.

SKILL_LIBRARY: dict[str, Skill] = {
    # -- Frontend & UI -------------------------------------------------------
    "analyze_react_component": Skill(
        name="analyze_react_component",
        description="Analyze React component structure: props, state, hooks, render logic, child components",
        handler_prompt=(
            "Identify the component's props interface, state management (useState/useReducer/context), "
            "hooks used, event handlers, and child component tree. Note any performance concerns "
            "(missing memo, inline functions in render, large re-renders)."
        ),
    ),
    "trace_state_flow": Skill(
        name="trace_state_flow",
        description="Trace data/state flow through frontend components and stores",
        handler_prompt=(
            "Map how data flows: props drilling, context providers, store subscriptions, "
            "API calls (fetch/axios/SWR/React Query). Identify the source of truth for each piece of state."
        ),
    ),
    "identify_ui_patterns": Skill(
        name="identify_ui_patterns",
        description="Identify UI/UX patterns: layouts, navigation, forms, accessibility",
        handler_prompt=(
            "Identify design patterns used: page layouts, navigation structure, form handling, "
            "responsive breakpoints, accessibility attributes (aria-*, role, tabIndex). "
            "Flag missing alt text, keyboard traps, or color contrast issues."
        ),
    ),
    "analyze_css_styles": Skill(
        name="analyze_css_styles",
        description="Analyze styling approach: CSS modules, Tailwind, styled-components, theme system",
        handler_prompt=(
            "Identify the styling methodology and any theme/design-token system. "
            "Note class naming conventions, responsive patterns, and dark mode support."
        ),
    ),

    # -- Backend & API -------------------------------------------------------
    "analyze_api_endpoint": Skill(
        name="analyze_api_endpoint",
        description="Analyze API endpoint: route, method, auth, request/response schema, error handling",
        handler_prompt=(
            "For each endpoint, identify: HTTP method, route path, authentication/authorization "
            "requirements, request validation, response format, error codes returned, and rate limiting. "
            "Check for missing input validation or error handling."
        ),
    ),
    "trace_data_flow": Skill(
        name="trace_data_flow",
        description="Trace data flow through backend: input -> processing -> storage -> response",
        handler_prompt=(
            "Map the complete data path: where data enters (request body, query params, headers), "
            "how it's validated/transformed, where it's stored (DB, cache, queue), "
            "and what response is returned. Identify any data loss or transformation gaps."
        ),
    ),
    "check_error_handling": Skill(
        name="check_error_handling",
        description="Analyze error handling: try/catch, error codes, logging, user-facing messages",
        handler_prompt=(
            "Check for: unhandled exceptions, generic catch-all blocks, missing error logging, "
            "stack traces leaking to users, inconsistent error response formats. "
            "Verify errors are actionable (not just 'Something went wrong')."
        ),
    ),
    "analyze_middleware": Skill(
        name="analyze_middleware",
        description="Analyze middleware chain: auth, logging, CORS, rate limiting, error handling",
        handler_prompt=(
            "Map the middleware execution order and what each layer does. "
            "Check for: missing auth middleware on protected routes, CORS misconfiguration, "
            "request size limits, and logging gaps."
        ),
    ),

    # -- Data & Database -----------------------------------------------------
    "analyze_schema": Skill(
        name="analyze_schema",
        description="Analyze database schema: tables, relationships, indexes, constraints",
        handler_prompt=(
            "Identify tables/collections, primary/foreign keys, indexes, unique constraints, "
            "and cascade rules. Flag missing indexes on frequently queried columns, "
            "N+1 query patterns, or denormalization opportunities."
        ),
    ),
    "trace_query_pattern": Skill(
        name="trace_query_pattern",
        description="Trace database query patterns: ORM usage, raw SQL, query optimization",
        handler_prompt=(
            "Identify how the code queries the database: ORM methods, raw SQL, query builders. "
            "Check for N+1 queries, missing pagination, unbounded SELECT *, "
            "and opportunities for batch operations."
        ),
    ),
    "check_data_integrity": Skill(
        name="check_data_integrity",
        description="Check data integrity: validation, sanitization, type safety, constraints",
        handler_prompt=(
            "Verify data is validated before storage, types are enforced, "
            "and business rules are checked at the data layer (not just API layer). "
            "Check for orphaned records and referential integrity gaps."
        ),
    ),

    # -- Infrastructure & DevOps --------------------------------------------
    "analyze_deployment": Skill(
        name="analyze_deployment",
        description="Analyze deployment config: Docker, CI/CD, environment setup, scaling",
        handler_prompt=(
            "Analyze the deployment pipeline: build steps, environment variables, "
            "container configuration, health checks, scaling policies, and rollback strategy. "
            "Flag hardcoded secrets, missing health endpoints, or single points of failure."
        ),
    ),
    "check_env_config": Skill(
        name="check_env_config",
        description="Check environment configuration: env vars, secrets, config files, defaults",
        handler_prompt=(
            "Map all environment variables: which are required, which have defaults, "
            "which contain secrets. Check for: missing vars that would cause runtime crashes, "
            "secrets in code/config files, and env-specific overrides."
        ),
    ),
    "trace_service_deps": Skill(
        name="trace_service_deps",
        description="Trace service dependencies: external APIs, databases, queues, caches",
        handler_prompt=(
            "Map all external dependencies this code relies on: databases, caches, "
            "message queues, third-party APIs, file systems. For each dependency, "
            "note: connection method, failure behavior, timeout settings, retry logic."
        ),
    ),
    "analyze_iac": Skill(
        name="analyze_iac",
        description="Analyze infrastructure-as-code: Terraform, CloudFormation, CDK patterns",
        handler_prompt=(
            "Analyze IaC resources: what's provisioned, dependencies between resources, "
            "security groups, IAM policies, and networking. Flag overly permissive policies, "
            "missing encryption, or resources without tags."
        ),
    ),

    # -- Security ------------------------------------------------------------
    "check_injection_risk": Skill(
        name="check_injection_risk",
        description="Check for injection vulnerabilities: SQL, XSS, command, path traversal",
        handler_prompt=(
            "Scan for: unsanitized user input in SQL/NoSQL queries, HTML output without escaping, "
            "command execution with user data, file path construction from user input. "
            "Check for parameterized queries and input validation."
        ),
    ),
    "audit_auth_flow": Skill(
        name="audit_auth_flow",
        description="Audit authentication/authorization: login, tokens, sessions, permissions",
        handler_prompt=(
            "Trace the auth flow: how users authenticate, token generation/validation, "
            "session management, permission checks. Flag: missing auth on endpoints, "
            "weak token generation, session fixation risks, privilege escalation paths."
        ),
    ),
    "flag_secrets": Skill(
        name="flag_secrets",
        description="Detect hardcoded secrets, API keys, passwords, and sensitive data exposure",
        handler_prompt=(
            "Search for: hardcoded API keys, passwords, tokens, connection strings, "
            "private keys. Check if secrets are loaded from environment/vault. "
            "Flag any sensitive data in logs, error messages, or client-visible responses."
        ),
    ),
    "check_dependency_risk": Skill(
        name="check_dependency_risk",
        description="Assess dependency security: known vulnerabilities, outdated packages, supply chain",
        handler_prompt=(
            "Check package versions against known vulnerability databases. "
            "Flag: outdated packages with known CVEs, unnecessary dependencies, "
            "packages with low maintenance, and lock file integrity."
        ),
    ),

    # -- Testing & Quality ---------------------------------------------------
    "identify_test_gaps": Skill(
        name="identify_test_gaps",
        description="Identify missing tests: uncovered paths, edge cases, error scenarios",
        handler_prompt=(
            "Analyze what's tested and what's not. For each untested code path, "
            "suggest a specific test case. Prioritize: error handling paths, "
            "boundary conditions, auth checks, and data validation."
        ),
    ),
    "suggest_edge_cases": Skill(
        name="suggest_edge_cases",
        description="Suggest edge cases and boundary conditions for testing",
        handler_prompt=(
            "For the code under analysis, identify edge cases: empty inputs, null values, "
            "max/min boundaries, unicode, concurrent access, timeout scenarios, "
            "and invalid state transitions. Prioritize by impact."
        ),
    ),
    "analyze_test_quality": Skill(
        name="analyze_test_quality",
        description="Analyze test quality: coverage, isolation, determinism, mock usage",
        handler_prompt=(
            "Evaluate test quality: are tests isolated? Deterministic? Do they test behavior "
            "or implementation? Are mocks appropriate or over-used? "
            "Flag flaky patterns (time-dependent, order-dependent, shared state)."
        ),
    ),

    # -- Documentation & Content ---------------------------------------------
    "analyze_documentation": Skill(
        name="analyze_documentation",
        description="Analyze code documentation: comments, docstrings, README, API docs",
        handler_prompt=(
            "Assess documentation quality: are public APIs documented? "
            "Are complex algorithms explained? Are setup instructions complete? "
            "Flag: outdated comments, missing parameter descriptions, undocumented side effects."
        ),
    ),

    # -- ML/AI ---------------------------------------------------------------
    "analyze_ml_pipeline": Skill(
        name="analyze_ml_pipeline",
        description="Analyze ML pipeline: data loading, preprocessing, training, evaluation, serving",
        handler_prompt=(
            "Map the ML pipeline stages: data ingestion, feature engineering, "
            "model architecture, training loop, evaluation metrics, model serving. "
            "Check for: data leakage, missing validation splits, reproducibility issues."
        ),
    ),
    "check_prompt_engineering": Skill(
        name="check_prompt_engineering",
        description="Analyze LLM prompt construction: system prompts, few-shot examples, output parsing",
        handler_prompt=(
            "Analyze prompt quality: clear instructions, appropriate few-shot examples, "
            "output format specification, token efficiency. Flag: prompt injection risks, "
            "missing output validation, excessive token usage."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Semantic matching texts — richer than name+description for embedding
# ---------------------------------------------------------------------------
# These describe WHEN to use each skill in natural language,
# optimized for embedding similarity matching.

SKILL_SEMANTIC_TEXTS: dict[str, str] = {
    "analyze_react_component": (
        "React component analysis: JSX, props, state management, hooks like useState "
        "useEffect useContext, event handlers, component tree, re-renders, memo, "
        "functional components, class components, UI rendering, virtual DOM"
    ),
    "trace_state_flow": (
        "Frontend state management: data flow, props drilling, context API, Redux, "
        "Zustand, MobX, store subscriptions, state updates, reactivity, computed values, "
        "derived state, global state, local state, lifting state up"
    ),
    "identify_ui_patterns": (
        "User interface design patterns: page layout, navigation menu, sidebar, "
        "form validation, responsive design, mobile-first, grid system, "
        "accessibility a11y WCAG aria roles keyboard navigation screen reader"
    ),
    "analyze_css_styles": (
        "CSS styling analysis: Tailwind utility classes, CSS modules, styled-components, "
        "CSS-in-JS, theme tokens, dark mode, responsive breakpoints, animations, "
        "flexbox, grid layout, design system, color palette, typography"
    ),
    "analyze_api_endpoint": (
        "REST API endpoint analysis: HTTP GET POST PUT DELETE PATCH, route parameters, "
        "query strings, request body validation, response schema, status codes, "
        "authentication headers, rate limiting, pagination, versioning"
    ),
    "trace_data_flow": (
        "Backend data flow tracing: request processing pipeline, input validation, "
        "business logic, data transformation, serialization, storage operations, "
        "response construction, data mapping between layers"
    ),
    "check_error_handling": (
        "Error handling analysis: try catch exception handling, error boundaries, "
        "error codes, logging errors, user-facing error messages, graceful degradation, "
        "retry logic, timeout handling, circuit breaker pattern"
    ),
    "analyze_middleware": (
        "Middleware analysis: request pipeline, authentication middleware, "
        "CORS configuration, logging middleware, rate limiter, body parser, "
        "compression, helmet security headers, request validation"
    ),
    "analyze_schema": (
        "Database schema analysis: table design, column types, primary key, "
        "foreign key relationships, indexes, unique constraints, migrations, "
        "normalization, denormalization, entity relationship diagram"
    ),
    "trace_query_pattern": (
        "Database query analysis: SQL queries, ORM patterns, query builder, "
        "N+1 problem, eager loading, lazy loading, query optimization, "
        "index usage, full table scan, pagination cursor offset"
    ),
    "check_data_integrity": (
        "Data integrity validation: input sanitization, type checking, "
        "constraint enforcement, referential integrity, orphaned records, "
        "data consistency, transaction boundaries, ACID properties"
    ),
    "analyze_deployment": (
        "Deployment and DevOps: Docker container, CI/CD pipeline, build process, "
        "environment setup, health checks, scaling configuration, rollback strategy, "
        "zero-downtime deployment, blue-green, canary release"
    ),
    "check_env_config": (
        "Environment configuration: environment variables, .env files, secrets, "
        "config management, feature flags, runtime configuration, "
        "missing required variables, default values, secret rotation"
    ),
    "trace_service_deps": (
        "Service dependency mapping: external API calls, database connections, "
        "cache (Redis, Memcached), message queue (SQS, RabbitMQ, Kafka), "
        "file storage (S3), third-party integrations, timeout and retry"
    ),
    "analyze_iac": (
        "Infrastructure as code: Terraform HCL, CloudFormation YAML, AWS CDK, "
        "Pulumi, resource provisioning, IAM policies, security groups, "
        "VPC networking, S3 buckets, Lambda functions, ECS tasks"
    ),
    "check_injection_risk": (
        "Injection vulnerability audit: SQL injection, XSS cross-site scripting, "
        "command injection, path traversal, SSRF, NoSQL injection, "
        "template injection, LDAP injection, input sanitization, parameterized queries"
    ),
    "audit_auth_flow": (
        "Authentication and authorization audit: login flow, JWT tokens, OAuth, "
        "session management, RBAC role-based access, permission checks, "
        "password hashing, MFA multi-factor, token refresh, session fixation"
    ),
    "flag_secrets": (
        "Secret detection: hardcoded API keys, passwords in source code, "
        "exposed credentials, private keys, connection strings, tokens, "
        "secrets in logs, environment variable leakage, git history secrets"
    ),
    "check_dependency_risk": (
        "Dependency security: vulnerable packages, CVE, outdated dependencies, "
        "supply chain attack, typosquatting, license compliance, "
        "package lock file, dependency audit, transitive dependencies"
    ),
    "identify_test_gaps": (
        "Test coverage gaps: untested code paths, missing test cases, "
        "error handling not tested, edge cases not covered, "
        "integration tests missing, critical paths without tests"
    ),
    "suggest_edge_cases": (
        "Edge case identification: null values, empty strings, boundary values, "
        "zero, negative numbers, very large inputs, unicode characters, "
        "concurrent access, race conditions, timeout, network failure"
    ),
    "analyze_test_quality": (
        "Test quality analysis: test isolation, deterministic tests, "
        "appropriate mocking, test coverage, test naming, AAA pattern, "
        "flaky tests, test speed, integration vs unit, fixtures"
    ),
    "analyze_documentation": (
        "Documentation analysis: code comments, docstrings, README, "
        "API documentation, changelog, architecture docs, setup guide, "
        "inline comments, JSDoc, type annotations, examples"
    ),
    "analyze_ml_pipeline": (
        "Machine learning pipeline: data loading, preprocessing, feature engineering, "
        "model training, hyperparameter tuning, evaluation metrics, model serving, "
        "data leakage, train/test split, cross-validation, MLOps"
    ),
    "check_prompt_engineering": (
        "LLM prompt analysis: system prompt design, few-shot examples, "
        "output format specification, prompt injection prevention, "
        "token optimization, chain of thought, Claude Anthropic OpenAI API"
    ),
}


# ---------------------------------------------------------------------------
# Type -> Skill Mapping (structural knowledge, always applied)
# ---------------------------------------------------------------------------

TYPE_SKILL_MAP: dict[str, list[str]] = {
    "JavaScriptModule": ["analyze_react_component", "trace_state_flow", "identify_ui_patterns"],
    "ReactComponent": ["analyze_react_component", "trace_state_flow", "analyze_css_styles"],
    "PythonModule": ["trace_data_flow", "check_error_handling"],
    "Function": ["trace_data_flow", "check_error_handling"],
    "APIEndpoint": ["analyze_api_endpoint", "audit_auth_flow", "check_injection_risk"],
    "DatabaseModel": ["analyze_schema", "trace_query_pattern", "check_data_integrity"],
    "Config": ["check_env_config", "trace_service_deps"],
    "CIPipeline": ["analyze_deployment", "check_env_config"],
    "DockerService": ["analyze_deployment", "trace_service_deps"],
    "TestFile": ["analyze_test_quality", "identify_test_gaps", "suggest_edge_cases"],
    "TestModule": ["analyze_test_quality", "identify_test_gaps", "suggest_edge_cases"],
    "EnvVar": ["check_env_config", "flag_secrets"],
    "Class": ["trace_data_flow", "check_error_handling"],
    "Directory": ["trace_service_deps"],
}


# ---------------------------------------------------------------------------
# Regex fallback patterns (used ONLY when no embedding model available)
# ---------------------------------------------------------------------------

_REGEX_QUERY_BOOSTERS: dict[str, list[str]] = {
    r"\bsecur|\bvuln|\binject|xss|csrf|\bauth\b|\bhack|\bpenetrat|owasp": [
        "check_injection_risk", "audit_auth_flow", "flag_secrets", "check_dependency_risk",
    ],
    r"\bperf|\bslow|\boptim|\bfast|\blatenc|\bcache|\bspeed|bottleneck": [
        "trace_query_pattern", "trace_data_flow",
    ],
    r"\btest|\bcover|\bspec\b|\bassert|\bmock|\bfixture|edge.case": [
        "identify_test_gaps", "suggest_edge_cases", "analyze_test_quality",
    ],
    r"\bdeploy|\bdocker|ci.?cd|\bpipeline|\binfra|\bterraform|\bcloud": [
        "analyze_deployment", "check_env_config", "analyze_iac",
    ],
    r"\bdatabas|\bschema|\bmigrat|\bquery\b|\bsql\b|\borm\b|\btable\b|\bindex\b": [
        "analyze_schema", "trace_query_pattern", "check_data_integrity",
    ],
    r"\bapi\b|\bendpoint|\broute|\brequest|\bresponse|\brest\b|graphql|\bcors": [
        "analyze_api_endpoint", "analyze_middleware",
    ],
    r"\bcomponent|\breact|\bui\b|\bux\b|\brender|\bstate\b|\bhook|\bstyle|\bcss|\blayout": [
        "analyze_react_component", "trace_state_flow", "identify_ui_patterns",
    ],
    r"\btrain|\binference|\bprompt\b|\bllm\b|\bembedding|\bml\b|\bai\b": [
        "analyze_ml_pipeline", "check_prompt_engineering",
    ],
    r"\bdoc\b|\breadme|\bcomment|\bexplain|\bdocument": [
        "analyze_documentation",
    ],
}

_COMPILED_REGEX_BOOSTERS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(pattern, re.IGNORECASE), skills)
    for pattern, skills in _REGEX_QUERY_BOOSTERS.items()
]

_REGEX_CONTENT_SIGNALS: dict[str, list[str]] = {
    r"@app\.(get|post|put|delete)|router\.|express|fastapi|flask": [
        "analyze_api_endpoint", "analyze_middleware",
    ],
    r"useState|useEffect|useContext|useMemo|useCallback|useReducer": [
        "analyze_react_component", "trace_state_flow",
    ],
    r"os\.environ|process\.env|getenv|\.env": [
        "check_env_config", "flag_secrets",
    ],
    r"SELECT\s|INSERT\s|UPDATE\s|DELETE\s|CREATE\sTABLE|ALTER\sTABLE": [
        "analyze_schema", "trace_query_pattern",
    ],
    r"\bjwt\b|token|session|cookie|bcrypt|hash.*password|\bauth": [
        "audit_auth_flow", "flag_secrets",
    ],
    r"FROM\s+\w+.*\n.*(?:RUN|CMD|ENTRYPOINT)|docker-compose|services:": [
        "analyze_deployment",
    ],
    r"terraform|resource\s+\"|aws_|google_|azurerm_": [
        "analyze_iac", "check_env_config",
    ],
    r"describe\(|it\(|test\(|expect\(|\bassert\b|pytest|jest": [
        "analyze_test_quality", "identify_test_gaps",
    ],
    r"anthropic|openai|bedrock|ollama|ChatCompletion|messages\.create": [
        "check_prompt_engineering",
    ],
}

_COMPILED_REGEX_CONTENT: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(pattern, re.IGNORECASE), skills)
    for pattern, skills in _REGEX_CONTENT_SIGNALS.items()
]


# ---------------------------------------------------------------------------
# Skill Admin — the smart assignment engine
# ---------------------------------------------------------------------------

class SkillAdmin:
    """Hybrid skill administrator for graph-of-agents reasoning.

    Uses a three-layer fused scoring approach:
    1. Regex exact match (guaranteed precision for code patterns)
    2. Semantic similarity via Titan V2 (best quality for intent matching)
    3. Type mapping boost (structural domain knowledge)

    Prefers Titan V2 for embeddings (production quality, 1024-dim).
    Falls back to sentence-transformers, then hash-based if neither available.

    Skill condensation: top-2 get full handler_prompt, 3-5 get summary only.
    """

    def __init__(
        self,
        *,
        max_skills_per_node: int = 5,
        embedding_fn: Callable[[str], np.ndarray] | None = None,
        custom_skills: dict[str, Skill] | None = None,
        use_titan: bool = True,
    ) -> None:
        self.max_skills_per_node = max_skills_per_node
        self._embedding_fn = embedding_fn

        # Build skill library
        self._library: dict[str, Skill] = dict(SKILL_LIBRARY)
        if custom_skills:
            self._library.update(custom_skills)

        # Skill embedding index (lazy, computed on first hybrid assign)
        self._skill_embeddings: dict[str, np.ndarray] | None = None
        self._semantic_ready = False
        self._use_titan = use_titan
        self._embedding_logged = False  # log backend selection only once

        # Auto-initialize Titan V2 if requested and no embedding_fn provided
        if self._embedding_fn is None and use_titan:
            self._try_init_titan()

    def _try_init_titan(self) -> None:
        """Try to initialize Titan V2 as the embedding backend."""
        try:
            from graqle.activation.embeddings import TitanV2Engine
            titan = TitanV2Engine()
            titan._load()  # Test that AWS credentials work
            self._embedding_fn = titan.embed
            if not self._embedding_logged:
                logger.info("SkillAdmin: using Titan V2 embeddings (1024-dim, best quality)")
                self._embedding_logged = True
        except Exception as exc:
            logger.debug("SkillAdmin: Titan V2 not available (%s), trying sentence-transformers", exc)
            try:
                from graqle.activation.embeddings import EmbeddingEngine
                engine = EmbeddingEngine()
                self._embedding_fn = engine.embed
                if not self._embedding_logged:
                    logger.info("SkillAdmin: using sentence-transformers embeddings (384-dim)")
                    self._embedding_logged = True
            except Exception:
                if not self._embedding_logged:
                    logger.info("SkillAdmin: no embedding model available, using regex-only mode")
                    self._embedding_logged = True

    def set_embedding_fn(self, fn: Callable[[str], np.ndarray]) -> None:
        """Set embedding function and invalidate cache."""
        self._embedding_fn = fn
        self._skill_embeddings = None
        self._semantic_ready = False

    def _ensure_skill_embeddings(self) -> bool:
        """Build skill embedding index if not already built. Returns True if ready."""
        if self._semantic_ready:
            return True
        if self._embedding_fn is None:
            return False

        try:
            self._skill_embeddings = {}
            for name, text in SKILL_SEMANTIC_TEXTS.items():
                if name in self._library:
                    self._skill_embeddings[name] = self._embedding_fn(text)
            self._semantic_ready = True
            logger.info(
                "SkillAdmin: built embedding index for %d skills (one-time cost)",
                len(self._skill_embeddings),
            )
            return True
        except Exception as exc:
            logger.warning("SkillAdmin: embedding index failed: %s", exc)
            self._skill_embeddings = None
            self._semantic_ready = False
            return False

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _compute_regex_scores(
        self,
        entity_type: str,
        description: str,
        query: str,
        chunks: list[Any] | None = None,
    ) -> dict[str, float]:
        """Compute regex-based scores for all skills.

        Returns normalized scores (0-1 range) for each matched skill.
        Skills with exact code pattern matches get the highest scores.
        """
        raw_scores: dict[str, float] = {}

        # Layer 1: Content signals — exact code patterns (highest precision)
        content_text = description or ""
        if chunks:
            for chunk in chunks[:3]:
                if isinstance(chunk, dict):
                    content_text += " " + chunk.get("text", "")[:500]
                elif isinstance(chunk, str):
                    content_text += " " + chunk[:500]

        for pattern, skill_names in _COMPILED_REGEX_CONTENT:
            if pattern.search(content_text):
                for name in skill_names:
                    raw_scores[name] = raw_scores.get(name, 0) + 3.0  # strong signal

        # Layer 2: Query keyword boosters
        for pattern, skill_names in _COMPILED_REGEX_BOOSTERS:
            if pattern.search(query):
                for name in skill_names:
                    raw_scores[name] = raw_scores.get(name, 0) + 2.0

        # Normalize to 0-1 range
        if not raw_scores:
            return {}
        max_score = max(raw_scores.values())
        if max_score > 0:
            return {k: v / max_score for k, v in raw_scores.items()}
        return {}

    def _compute_semantic_scores(
        self,
        entity_type: str,
        description: str,
        query: str,
        chunks: list[Any] | None = None,
    ) -> dict[str, float]:
        """Compute semantic similarity scores for all skills.

        Returns cosine similarity (0-1 range) for each skill.
        """
        if not self._skill_embeddings or not self._embedding_fn:
            return {}

        # Build composite context for embedding
        context_parts = [query]
        if description:
            context_parts.append(description[:300])
        if entity_type:
            context_parts.append(f"This is a {entity_type} node.")
        if chunks:
            for chunk in chunks[:2]:
                if isinstance(chunk, dict):
                    context_parts.append(chunk.get("text", "")[:200])
                elif isinstance(chunk, str):
                    context_parts.append(chunk[:200])

        context_text = " ".join(context_parts)

        try:
            context_emb = self._embedding_fn(context_text)
        except Exception:
            return {}

        scores: dict[str, float] = {}
        for name, skill_emb in self._skill_embeddings.items():
            scores[name] = self._cosine_similarity(context_emb, skill_emb)

        return scores

    def _hybrid_assign(
        self,
        entity_type: str,
        description: str,
        query: str,
        chunks: list[Any] | None = None,
    ) -> list[Skill]:
        """Hybrid skill assignment: regex first, then semantic, fused scoring.

        Strategy:
        1. Compute regex scores (exact pattern matches)
        2. Compute semantic scores (embedding similarity)
        3. Fuse: regex_score * 0.4 + semantic_score * 0.4 + type_boost * 0.2
        4. Skills with regex exact match get a guaranteed floor score
        5. Rank by fused score, pick top-K above threshold
        """
        regex_scores = self._compute_regex_scores(
            entity_type, description, query, chunks
        )
        semantic_scores = self._compute_semantic_scores(
            entity_type, description, query, chunks
        )

        # Get type-mapped skills
        type_skills = set(TYPE_SKILL_MAP.get(entity_type, []))

        # Fuse scores for all skills
        all_skill_names = set(self._library.keys())
        fused: dict[str, float] = {}

        for name in all_skill_names:
            r_score = regex_scores.get(name, 0.0)
            s_score = semantic_scores.get(name, 0.0)
            t_boost = 1.0 if name in type_skills else 0.0

            # Weighted fusion
            # - Regex exact match is gold: 40% weight
            # - Semantic is the intent catcher: 40% weight
            # - Type mapping is structural knowledge: 20% weight
            fused_score = (r_score * 0.4) + (s_score * 0.4) + (t_boost * 0.2)

            # Guaranteed floor: if regex found an exact code pattern match,
            # ensure this skill gets at least 0.5 fused score
            if r_score > 0.5:
                fused_score = max(fused_score, 0.5)

            fused[name] = fused_score

        # Rank and pick top-K
        ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        assigned: list[Skill] = []

        for name, score in ranked[:self.max_skills_per_node]:
            if score < 0.1:  # minimum threshold
                break
            skill = self._library.get(name)
            if skill:
                assigned.append(skill)

        logger.debug(
            "SkillAdmin (hybrid): %d skills for %s | top: %s | "
            "regex_hits=%d semantic_ready=%s",
            len(assigned),
            entity_type,
            [(n, f"{s:.3f}") for n, s in ranked[:5]],
            len(regex_scores),
            self._semantic_ready,
        )

        return assigned

    def _regex_only_assign(
        self,
        entity_type: str,
        description: str,
        query: str,
        chunks: list[Any] | None = None,
    ) -> list[Skill]:
        """Pure regex assignment (fallback when no embedding model available)."""
        scores: dict[str, float] = {}

        # Type mapping
        for name in TYPE_SKILL_MAP.get(entity_type, []):
            scores[name] = scores.get(name, 0) + 2.0

        # Content signals
        content_text = description or ""
        if chunks:
            for chunk in chunks[:3]:
                if isinstance(chunk, dict):
                    content_text += " " + chunk.get("text", "")[:500]
                elif isinstance(chunk, str):
                    content_text += " " + chunk[:500]

        for pattern, skill_names in _COMPILED_REGEX_CONTENT:
            if pattern.search(content_text):
                for name in skill_names:
                    scores[name] = scores.get(name, 0) + 1.5

        # Query boosters
        for pattern, skill_names in _COMPILED_REGEX_BOOSTERS:
            if pattern.search(query):
                for name in skill_names:
                    scores[name] = scores.get(name, 0) + 1.0

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        assigned: list[Skill] = []

        for name, score in ranked[:self.max_skills_per_node]:
            skill = self._library.get(name)
            if skill:
                assigned.append(skill)

        logger.debug(
            "SkillAdmin (regex-only): %d skills for %s | top: %s",
            len(assigned),
            entity_type,
            [(n, f"{s:.1f}") for n, s in ranked[:3]],
        )

        return assigned

    def assign(
        self,
        entity_type: str,
        description: str,
        query: str,
        chunks: list[Any] | None = None,
    ) -> list[Skill]:
        """Assign skills using hybrid fused scoring.

        When embeddings are available: regex + semantic + type = fused score.
        When no embeddings: regex + type only (still good for exact patterns).
        """
        # Build embedding index if not ready
        self._ensure_skill_embeddings()

        # If we have semantic capability, use full hybrid
        if self._semantic_ready:
            return self._hybrid_assign(entity_type, description, query, chunks)

        # Otherwise, regex-only
        return self._regex_only_assign(entity_type, description, query, chunks)

    def assign_to_node(
        self,
        node: Any,
        query: str,
    ) -> str:
        """Assign skills to a CogniNode and return formatted skills_text.

        Uses skill condensation:
        - Top 2 skills: full handler_prompt (detailed HOW instructions)
        - Skills 3-5: summary only (name + description, saves ~60% tokens)
        """
        chunks = node.properties.get("chunks", [])
        skills = self.assign(
            entity_type=node.entity_type,
            description=node.description,
            query=query,
            chunks=chunks,
        )

        if not skills:
            return ""

        lines = ["YOUR SKILLS (use these capabilities in your analysis):"]

        for i, skill in enumerate(skills):
            if i < 2:
                # Top 2: full detail with handler_prompt
                lines.append(f"- **{skill.name}**: {skill.description}")
                lines.append(f"  HOW: {skill.handler_prompt}")
            else:
                # Skills 3-5: condensed (name + description only)
                lines.append(f"- {skill.name}: {skill.description}")

        return "\n".join(lines)

    def get_skill(self, name: str) -> Skill | None:
        """Look up a skill by name."""
        return self._library.get(name)

    def register_skill(
        self, skill: Skill, semantic_text: str | None = None,
    ) -> None:
        """Add a custom skill to the library with optional semantic text."""
        self._library[skill.name] = skill
        if semantic_text:
            SKILL_SEMANTIC_TEXTS[skill.name] = semantic_text
            # Invalidate embedding cache
            self._skill_embeddings = None
            self._semantic_ready = False

    @property
    def skill_count(self) -> int:
        return len(self._library)

    @property
    def mode(self) -> str:
        """Current matching mode."""
        if self._semantic_ready:
            return "hybrid (regex + semantic)"
        if self._embedding_fn is not None:
            return "hybrid (pending index build)"
        return "regex-only"
