"""Coding domain — governed AI code generation ontology.

Phase 4 (v0.38.0): Expanded from 25% → 80%+ completeness per .
Phase 6 (v0.38.0): +GOAL_DECOMPOSITION skill, +ExecutionPlan entity, +PLANNED_BY relationship,
                   +validate_plan_format gate → agent planning capability.
Phase 7 (v0.38.0): +PERFORMANCE_PROFILING skill, +validate_profile_output gate
                   → governance enforcement + performance observability.

Skills (14): CODE_GENERATION, REFACTOR, COMPLETION, TEST_GENERATION,
             CODE_REVIEW, DEBUG, SECURITY_AUDIT, DEPENDENCY_ANALYSIS,
             COMPLEXITY_ANALYSIS, DEAD_CODE_DETECTION, DOCUMENTATION, MIGRATION,
             GOAL_DECOMPOSITION, PERFORMANCE_PROFILING

Entity types (15): CodeModule, CodeClass, CodeFunction, CodeAPI, CodeTest,
                   CodeDependency, CodeConfig, CodeInterface, CodeException,
                   CodeDecorator, CodeChange, CodeSchema, CodeVariable,
                   CodeMetric, ExecutionPlan

Relationships (17): GENERATES, MODIFIES, TESTS, REFACTORS,
                    DEPENDS_ON, IMPORTS, CALLS, INHERITS_FROM, IMPLEMENTS,
                    TESTED_BY, RAISES, HANDLES, CONFIGURES, OVERRIDES,
                    DOCUMENTS, DECORATES, PLANNED_BY

Output Gates (12): validate_diff_format, check_file_path_exists,
                   check_no_secret_exposure, validate_syntax, validate_test_format,
                   validate_review_format, validate_diagnostic_list,
                   validate_complexity_metrics, validate_security_report,
                   test_coverage_gate, validate_plan_format, validate_profile_output
"""

# ── graqle:intelligence ──
# module: graqle.ontology.domains.coding
# risk: LOW (impact radius: 0 existing consumers — new domain)
# consumers: mcp_dev_server (graq_generate, graq_review, graq_debug, graq_scaffold, graq_workflow)
# constraints: NEVER expose weight values or formula internals (internal-pattern-A..internal-pattern-D)
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import TYPE_CHECKING

from graqle.ontology.skill_resolver import Skill

if TYPE_CHECKING:
    from graqle.ontology.domain_registry import DomainRegistry


# ---------------------------------------------------------------------------
# OWL Class Hierarchy
# ---------------------------------------------------------------------------

CODING_CLASS_HIERARCHY: dict[str, str] = {
    "Coding": "Thing",
    # Primary code entity types
    "CodeModule": "Coding",
    "CodeClass": "CodeModule",
    "CodeFunction": "CodeModule",
    "CodeAPI": "Coding",
    "CodeTest": "Coding",
    # Phase 4: new entity types
    "CodeDependency": "Coding",
    "CodeConfig": "Coding",
    "CodeInterface": "Coding",
    "CodeException": "Coding",
    "CodeDecorator": "Coding",
    "CodeChange": "Coding",
    "CodeSchema": "Coding",
    "CodeVariable": "CodeModule",
    # Phase 5: test metrics
    "CodeMetric": "Coding",
    # Phase 6: agent planning
    "ExecutionPlan": "Coding",
    # Scanner-produced aliases (map to canonical types)
    "Function": "CodeFunction",
    "Class": "CodeClass",
    "Module": "CodeModule",
    "API": "CodeAPI",
    "Test": "CodeTest",
    "PythonModule": "CodeModule",
    "PythonClass": "CodeClass",
    "PythonFunction": "CodeFunction",
    "TestFile": "CodeTest",
}

# ---------------------------------------------------------------------------
# Entity Shapes
# ---------------------------------------------------------------------------

CODING_ENTITY_SHAPES: dict[str, dict] = {
    # Phase 1 entities
    "CodeModule": {
        "required": ["name", "file_path"],
        "optional": ["language", "imports", "exports", "line_count"],
    },
    "CodeClass": {
        "required": ["name", "file_path"],
        "optional": ["methods", "attributes", "base_classes", "docstring"],
    },
    "CodeFunction": {
        "required": ["name", "file_path"],
        "optional": ["parameters", "return_type", "docstring", "line_start", "line_end"],
    },
    "CodeAPI": {
        "required": ["path", "method"],
        "optional": ["auth", "request_schema", "response_schema", "handler"],
    },
    "CodeTest": {
        "required": ["name", "file_path"],
        "optional": ["targets", "test_type", "framework"],
    },
    # Phase 5 entity
    "CodeMetric": {
        "required": ["name", "metric_type"],
        "optional": ["value", "unit", "target", "file_path", "timestamp", "status"],
    },
    # Phase 6 entity: agent planning
    "ExecutionPlan": {
        "required": ["goal", "plan_id"],
        "optional": [
            "steps", "checkpoints", "risk_level", "estimated_cost_usd",
            "affected_files", "affected_modules", "requires_approval",
            "decomposition_confidence", "total_steps", "high_risk_steps",
        ],
    },
    # Phase 4 entities
    "CodeDependency": {
        "required": ["name", "version"],
        "optional": ["package_manager", "is_dev", "license", "latest_version", "has_vulnerability"],
    },
    "CodeConfig": {
        "required": ["name", "file_path"],
        "optional": ["format", "keys", "environment", "is_secret"],
    },
    "CodeInterface": {
        "required": ["name", "file_path"],
        "optional": ["methods", "properties", "implemented_by"],
    },
    "CodeException": {
        "required": ["name"],
        "optional": ["base_class", "file_path", "raised_by", "handled_by", "message_template"],
    },
    "CodeDecorator": {
        "required": ["name"],
        "optional": ["file_path", "targets", "parameters", "purpose"],
    },
    "CodeChange": {
        "required": ["file_path", "change_type"],
        "optional": ["diff", "author", "timestamp", "commit_hash", "review_status"],
    },
    "CodeSchema": {
        "required": ["name"],
        "optional": ["fields", "file_path", "format", "version", "validators"],
    },
    "CodeVariable": {
        "required": ["name", "file_path"],
        "optional": ["type", "scope", "is_constant", "initial_value", "line_number"],
    },
}

# ---------------------------------------------------------------------------
# Relationship Shapes
# ---------------------------------------------------------------------------

CODING_RELATIONSHIP_SHAPES: dict[str, dict] = {
    # Phase 1 relationships
    "GENERATES": {
        "domain": {"graq_generate", "graq_edit"},
        "range": {"CodeModule", "CodeClass", "CodeFunction"},
    },
    "MODIFIES": {
        "domain": {"graq_edit"},
        "range": {"CodeModule", "CodeClass", "CodeFunction", "CodeTest"},
    },
    "TESTS": {
        "domain": {"CodeTest"},
        "range": {"CodeModule", "CodeClass", "CodeFunction", "CodeAPI"},
    },
    "REFACTORS": {
        "domain": {"graq_generate"},
        "range": {"CodeClass", "CodeFunction", "CodeModule"},
    },
    # Phase 4 relationships
    "DEPENDS_ON": {
        "domain": {"CodeModule", "CodeClass", "CodeFunction"},
        "range": {"CodeDependency", "CodeModule"},
    },
    "IMPORTS": {
        "domain": {"CodeModule", "CodeClass"},
        "range": {"CodeModule", "CodeFunction", "CodeClass"},
    },
    "CALLS": {
        "domain": {"CodeFunction", "CodeClass"},
        "range": {"CodeFunction", "CodeAPI"},
    },
    "INHERITS_FROM": {
        "domain": {"CodeClass"},
        "range": {"CodeClass", "CodeInterface"},
    },
    "IMPLEMENTS": {
        "domain": {"CodeClass"},
        "range": {"CodeInterface"},
    },
    "TESTED_BY": {
        "domain": {"CodeModule", "CodeClass", "CodeFunction", "CodeAPI"},
        "range": {"CodeTest"},
    },
    "RAISES": {
        "domain": {"CodeFunction", "CodeClass"},
        "range": {"CodeException"},
    },
    "HANDLES": {
        "domain": {"CodeFunction", "CodeClass"},
        "range": {"CodeException"},
    },
    "CONFIGURES": {
        "domain": {"CodeConfig"},
        "range": {"CodeModule", "CodeAPI", "CodeClass"},
    },
    "OVERRIDES": {
        "domain": {"CodeClass"},
        "range": {"CodeFunction"},
    },
    "DOCUMENTS": {
        "domain": {"CodeModule"},
        "range": {"CodeClass", "CodeFunction", "CodeAPI"},
    },
    "DECORATES": {
        "domain": {"CodeDecorator"},
        "range": {"CodeFunction", "CodeClass"},
    },
    # Phase 6 relationship: agent planning
    "PLANNED_BY": {
        "domain": {"CodeModule", "CodeFunction", "CodeClass", "CodeChange"},
        "range": {"ExecutionPlan"},
    },
}

# ---------------------------------------------------------------------------
# Skill Map
# ---------------------------------------------------------------------------

CODING_SKILL_MAP: dict[str, list[str]] = {
    # Branch level — all coding entities
    "Coding": ["CODE_GENERATION", "REFACTOR", "CODE_REVIEW", "DEAD_CODE_DETECTION"],
    # Module level
    "CodeModule": [
        "CODE_GENERATION", "REFACTOR", "COMPLETION", "TEST_GENERATION",
        "CODE_REVIEW", "DOCUMENTATION", "DEAD_CODE_DETECTION", "MIGRATION",
    ],
    "CodeClass": [
        "CODE_GENERATION", "REFACTOR", "COMPLETION", "TEST_GENERATION",
        "CODE_REVIEW", "DEBUG", "DOCUMENTATION",
    ],
    "CodeFunction": [
        "CODE_GENERATION", "COMPLETION", "TEST_GENERATION", "REFACTOR",
        "CODE_REVIEW", "DEBUG", "COMPLEXITY_ANALYSIS", "DOCUMENTATION",
    ],
    "CodeAPI": ["CODE_GENERATION", "TEST_GENERATION", "SECURITY_AUDIT", "DOCUMENTATION"],
    "CodeTest": ["TEST_GENERATION", "CODE_REVIEW"],
    # Phase 4 entity types
    "CodeDependency": ["DEPENDENCY_ANALYSIS", "SECURITY_AUDIT", "MIGRATION"],
    "CodeConfig": ["SECURITY_AUDIT", "DOCUMENTATION"],
    "CodeInterface": ["CODE_GENERATION", "DOCUMENTATION", "CODE_REVIEW"],
    "CodeException": ["DEBUG", "DOCUMENTATION"],
    "CodeDecorator": ["CODE_REVIEW", "DOCUMENTATION"],
    "CodeChange": ["CODE_REVIEW", "MIGRATION"],
    "CodeSchema": ["CODE_GENERATION", "DOCUMENTATION", "SECURITY_AUDIT"],
    "CodeVariable": ["CODE_REVIEW", "DEAD_CODE_DETECTION"],
    # Phase 5
    "CodeMetric": ["COMPLEXITY_ANALYSIS", "PERFORMANCE_PROFILING"],
    # Phase 6
    "ExecutionPlan": ["GOAL_DECOMPOSITION"],
    # Scanner-type aliases
    "Function": [
        "CODE_GENERATION", "COMPLETION", "TEST_GENERATION", "REFACTOR",
        "CODE_REVIEW", "DEBUG", "COMPLEXITY_ANALYSIS",
    ],
    "Class": [
        "CODE_GENERATION", "REFACTOR", "COMPLETION", "TEST_GENERATION",
        "CODE_REVIEW", "DEBUG",
    ],
    "Module": [
        "CODE_GENERATION", "REFACTOR", "COMPLETION", "TEST_GENERATION",
        "CODE_REVIEW", "DOCUMENTATION", "DEAD_CODE_DETECTION",
    ],
    "API": ["CODE_GENERATION", "TEST_GENERATION", "SECURITY_AUDIT"],
    "Test": ["TEST_GENERATION", "CODE_REVIEW"],
    "PythonModule": [
        "CODE_GENERATION", "REFACTOR", "COMPLETION", "TEST_GENERATION",
        "CODE_REVIEW", "DOCUMENTATION", "DEAD_CODE_DETECTION", "MIGRATION",
    ],
    "PythonClass": [
        "CODE_GENERATION", "REFACTOR", "COMPLETION", "TEST_GENERATION",
        "CODE_REVIEW", "DEBUG",
    ],
    "PythonFunction": [
        "CODE_GENERATION", "COMPLETION", "TEST_GENERATION", "REFACTOR",
        "CODE_REVIEW", "DEBUG", "COMPLEXITY_ANALYSIS",
    ],
    "TestFile": ["TEST_GENERATION", "CODE_REVIEW"],
}

# ---------------------------------------------------------------------------
# Skill Objects
# ---------------------------------------------------------------------------

CODING_SKILLS: dict[str, Skill] = {
    # ── Phase 1 skills ──────────────────────────────────────────────────────
    "CODE_GENERATION": Skill(
        name="CODE_GENERATION",
        description="Generate syntactically valid, governance-checked code patches as unified diffs.",
        handler_prompt=(
            "You are a governed code generation assistant. "
            "Given a description and optional file context from the Graqle knowledge graph, "
            "produce a unified diff patch. "
            "Rules: (1) output ONLY valid unified diff format, "
            "(2) never expose secrets or credentials, "
            "(3) respect existing code style, "
            "(4) add docstrings only when explicitly requested."
        ),
    ),
    "REFACTOR": Skill(
        name="REFACTOR",
        description="Propose refactoring changes as a unified diff, preserving all existing tests.",
        handler_prompt=(
            "You are a refactoring assistant with access to the full dependency graph. "
            "Propose refactoring changes that improve code quality while keeping all existing tests green. "
            "Output a unified diff. Never rename public API surfaces without checking impact radius first."
        ),
    ),
    "COMPLETION": Skill(
        name="COMPLETION",
        description="Complete partial code (function stubs, missing methods) using graph context.",
        handler_prompt=(
            "You are a code completion assistant. "
            "Given partial code and graph context showing related modules and patterns, "
            "complete the implementation. "
            "Match existing code style exactly. Output only the completed function/method body."
        ),
    ),
    "TEST_GENERATION": Skill(
        name="TEST_GENERATION",
        description="Generate pytest test cases for a given module, class, or function.",
        handler_prompt=(
            "You are a test generation assistant. "
            "Given a module/class/function and its graph context (callers, dependencies), "
            "generate comprehensive pytest test cases. "
            "Include: happy path, edge cases, and error conditions. "
            "Use existing test patterns from the codebase. "
            "Never mock the database unless the existing tests already do so."
        ),
    ),
    # ── Phase 4 skills ──────────────────────────────────────────────────────
    "CODE_REVIEW": Skill(
        name="CODE_REVIEW",
        description="Perform structured code review: correctness, style, security, test coverage, complexity.",
        handler_prompt=(
            "You are a senior code reviewer with access to the full dependency graph. "
            "Review the provided code changes for: "
            "(1) correctness and logic errors, "
            "(2) security vulnerabilities (OWASP Top 10), "
            "(3) code style and naming conventions, "
            "(4) test coverage gaps, "
            "(5) complexity hotspots. "
            "Output structured review comments with severity: BLOCKER, MAJOR, MINOR, INFO. "
            "Never approve code that exposes credentials or has SQL injection risks."
        ),
    ),
    "DEBUG": Skill(
        name="DEBUG",
        description="Diagnose bugs from stack traces, logs, or error descriptions using graph context.",
        handler_prompt=(
            "You are a debugging assistant with access to the full call graph. "
            "Given an error message, stack trace, or symptom description: "
            "(1) identify the root cause using graph context (callers, dependencies, known failure patterns), "
            "(2) propose a minimal fix as a unified diff, "
            "(3) suggest a test that would catch this bug. "
            "Prefer graph-informed analysis over guessing."
        ),
    ),
    "SECURITY_AUDIT": Skill(
        name="SECURITY_AUDIT",
        description="Audit code for OWASP Top 10 vulnerabilities, exposed secrets, and unsafe patterns.",
        handler_prompt=(
            "You are a security auditor. "
            "Scan the provided code for: "
            "(1) OWASP Top 10 vulnerabilities (injection, XSS, broken auth, etc.), "
            "(2) exposed API keys, tokens, passwords in code or config, "
            "(3) unsafe subprocess/shell calls, "
            "(4) unvalidated external input, "
            "(5) insecure dependencies. "
            "Output findings with severity: CRITICAL, HIGH, MEDIUM, LOW. "
            "Include remediation guidance for each finding."
        ),
    ),
    "DEPENDENCY_ANALYSIS": Skill(
        name="DEPENDENCY_ANALYSIS",
        description="Analyse dependency graph for circular imports, outdated packages, and vulnerability exposure.",
        handler_prompt=(
            "You are a dependency analysis assistant. "
            "Given the dependency graph context: "
            "(1) identify circular import chains, "
            "(2) flag outdated packages (if version info available), "
            "(3) detect unused dependencies (imports not referenced in code), "
            "(4) identify transitive vulnerability exposure paths. "
            "Output a structured dependency report."
        ),
    ),
    "COMPLEXITY_ANALYSIS": Skill(
        name="COMPLEXITY_ANALYSIS",
        description="Calculate cyclomatic complexity and identify refactoring candidates.",
        handler_prompt=(
            "You are a complexity analysis assistant. "
            "Given code and its graph context: "
            "(1) estimate cyclomatic complexity for each function, "
            "(2) flag functions with complexity > 10 as REFACTOR candidates, "
            "(3) identify deeply nested conditionals (depth > 4), "
            "(4) find long functions (> 50 lines) with multiple responsibilities. "
            "Output a complexity report with refactoring priorities."
        ),
    ),
    "DEAD_CODE_DETECTION": Skill(
        name="DEAD_CODE_DETECTION",
        description="Find unreachable code, unused exports, and orphaned modules using graph reachability.",
        handler_prompt=(
            "You are a dead code detection assistant. "
            "Using the knowledge graph reachability data: "
            "(1) find functions/classes with zero callers in the graph, "
            "(2) identify modules with no consumers, "
            "(3) flag exported symbols that are never imported elsewhere, "
            "(4) detect unreachable code branches (code after return/raise). "
            "Output a dead code report with confidence scores (HIGH/MEDIUM/LOW). "
            "Never flag __init__.py exports as dead — they are public API."
        ),
    ),
    "DOCUMENTATION": Skill(
        name="DOCUMENTATION",
        description="Generate or improve docstrings, README sections, and API documentation.",
        handler_prompt=(
            "You are a documentation assistant. "
            "Given a module/class/function and its graph context: "
            "(1) generate Google-style docstrings for undocumented functions, "
            "(2) add parameter types and return type documentation, "
            "(3) include usage examples for public API functions, "
            "(4) add :raises: documentation for known exception types. "
            "Output only docstrings or documentation blocks — no code changes."
        ),
    ),
    "MIGRATION": Skill(
        name="MIGRATION",
        description="Plan and execute code migrations: framework upgrades, API renames, Python version bumps.",
        handler_prompt=(
            "You are a migration assistant with access to the full impact graph. "
            "Given a migration target (e.g., 'upgrade from Python 3.9 to 3.12'): "
            "(1) identify all affected modules using the impact graph, "
            "(2) produce an ordered migration plan (leaf nodes first, then dependents), "
            "(3) generate unified diff patches for each file, "
            "(4) flag any breaking changes that require manual review. "
            "Output a structured migration plan with risk ratings."
        ),
    ),
    # ── Phase 7 skills ──────────────────────────────────────────────────────
    "PERFORMANCE_PROFILING": Skill(
        name="PERFORMANCE_PROFILING",
        description=(
            "Profile the performance of a reasoning invocation: per-step latency, "
            "token cost, and confidence at each phase. Identifies bottleneck steps, "
            "flags slow or expensive nodes, and writes CodeMetric KG nodes for "
            "future threshold calibration."
        ),
        handler_prompt=(
            "You are a performance analysis assistant. "
            "Given a profiling trace with per-step records: "
            "(1) identify the step with the highest latency (bottleneck), "
            "(2) flag steps where latency_ms > 2000 or tokens_used > 4000, "
            "(3) assess whether final_confidence >= 0.65 (acceptable), "
            "(4) recommend specific tuning actions: "
            "    - If ANCHOR is slow: consider narrowing confidence_threshold, "
            "    - If GENERATE is slow: consider reducing max_rounds, "
            "    - If VALIDATE is slow: consider pre-filtering with graq_preflight, "
            "    - If confidence < 0.65: recommend graq_learn to enrich the graph. "
            "(5) output a structured ProfileSummary with total_latency_ms, total_tokens, "
            "    final_confidence, bottleneck_step, and recommendations list. "
            "Write the trace as a CodeMetric node so future reasoning can detect "
            "performance regressions across sessions."
        ),
    ),
    # ── Phase 6 skills ──────────────────────────────────────────────────────
    "GOAL_DECOMPOSITION": Skill(
        name="GOAL_DECOMPOSITION",
        description=(
            "Decompose a high-level goal into a governance-gated DAG execution plan. "
            "Uses graph topology (impact_radius, CALLS/IMPORTS edges, causal tiers) "
            "to order steps and insert governance checkpoints before high-risk operations."
        ),
        handler_prompt=(
            "You are a planning assistant with access to the full dependency and impact graph. "
            "Given a high-level goal: "
            "(1) identify all files and modules affected using graq_impact, "
            "(2) decompose the goal into atomic, independently revertable steps, "
            "(3) order steps by dependency (leaf modules first, then dependents), "
            "(4) assign risk_level (LOW/MEDIUM/HIGH/CRITICAL) to each step based on: "
            "    - impact_radius of affected modules, "
            "    - presence in _WRITE_TOOLS, "
            "    - number of downstream consumers, "
            "(5) insert GovernanceCheckpoint before any HIGH or CRITICAL step, "
            "(6) estimate cost using cost_per_1k_tokens × estimated_tokens_per_step, "
            "(7) flag steps requiring human approval (requires_approval=True) when: "
            "    - step modifies a module with impact_radius > 10, "
            "    - step deletes files, "
            "    - step runs git commit or push. "
            "Output an ExecutionPlan as a JSON object. "
            "Never start executing — planning and execution are separate phases."
        ),
    ),
}

# ---------------------------------------------------------------------------
# Output Gates
# ---------------------------------------------------------------------------

CODING_OUTPUT_GATES: dict[str, dict] = {
    # Phase 1 gates
    "validate_diff_format": {
        "description": (
            "Verify the output is a valid unified diff: "
            "starts with '--- ' and '+++ ' headers, "
            "contains at least one '@@' hunk header, "
            "and all changed lines start with '+' or '-'."
        ),
        "required": ["unified_diff"],
    },
    "check_file_path_exists": {
        "description": (
            "If a file_path was specified, verify it exists in the knowledge graph "
            "or as a real file before applying the patch."
        ),
        "required": ["file_path"],
    },
    "check_no_secret_exposure": {
        "description": (
            "Scan the generated diff for patterns matching: "
            "API keys, tokens, passwords, connection strings, AWS credentials. "
            "Reject if any are found."
        ),
        "required": ["unified_diff"],
    },
    "validate_syntax": {
        "description": (
            "Verify the generated code has valid Python syntax using ast.parse(). "
            "Reject if SyntaxError is raised."
        ),
        "required": ["code"],
    },
    "validate_test_format": {
        "description": (
            "Verify the generated tests use pytest conventions: "
            "test functions start with 'test_', "
            "assertions use 'assert', "
            "no unittest.TestCase unless existing tests use it."
        ),
        "required": ["code"],
    },
    # Phase 4 gates
    "validate_review_format": {
        "description": (
            "Verify code review output contains structured comments with: "
            "severity field (BLOCKER/MAJOR/MINOR/INFO), "
            "file_path reference, "
            "line_number or line_range, "
            "and a clear description."
        ),
        "required": ["review_comments"],
    },
    "validate_diagnostic_list": {
        "description": (
            "Verify debug diagnostic output contains: "
            "root_cause field (non-empty string), "
            "affected_files list, "
            "proposed_fix as unified diff or description. "
            "Reject if root_cause is empty."
        ),
        "required": ["root_cause", "affected_files"],
    },
    "validate_complexity_metrics": {
        "description": (
            "Verify complexity analysis output contains: "
            "per-function cyclomatic complexity scores, "
            "hotspot list (complexity > 10), "
            "overall module complexity rating."
        ),
        "required": ["complexity_scores"],
    },
    "validate_security_report": {
        "description": (
            "Verify security audit output contains: "
            "findings list with severity (CRITICAL/HIGH/MEDIUM/LOW), "
            "each finding has: type, file_path, line_number, description, remediation. "
            "Reject if any CRITICAL finding has no remediation."
        ),
        "required": ["findings"],
    },
    # Phase 6 gate: agent planning
    "validate_plan_format": {
        "description": (
            "Verify an ExecutionPlan is well-formed before execution: "
            "plan_id is non-empty, goal is non-empty, steps list is non-empty, "
            "each step has step_id/tool/description, "
            "depends_on references valid step_ids only, "
            "no circular dependencies in the DAG, "
            "estimated_cost_usd is non-negative. "
            "Reject if any HIGH/CRITICAL step has no preceding GovernanceCheckpoint."
        ),
        "required": ["plan_id", "goal", "steps"],
    },
    # Phase 7 gate
    "validate_profile_output": {
        "description": (
            "Verify a ProfileSummary is well-formed: "
            "trace_id is non-empty, total_latency_ms is non-negative, "
            "final_confidence is in [0.0, 1.0], "
            "bottleneck_step is a non-empty string, "
            "recommendations is a non-empty list. "
            "Warn if total_latency_ms > 10000 or final_confidence < 0.60."
        ),
        "required": ["trace_id", "total_latency_ms", "final_confidence", "bottleneck_step"],
    },
    # Phase 5 gate
    "test_coverage_gate": {
        "description": (
            "Verify test coverage meets the required threshold: "
            "coverage_pct >= threshold (default: 80%). "
            "Reject if test run has any failures (failed > 0). "
            "Report: pass/fail counts, coverage_pct, failing_tests list."
        ),
        "required": ["passed", "failed", "coverage_pct"],
    },
}


# ---------------------------------------------------------------------------
# Registration Function
# ---------------------------------------------------------------------------

def register_coding_domain(registry: DomainRegistry) -> None:
    """Register the coding domain into the given DomainRegistry."""
    registry.register_domain(
        name="coding",
        class_hierarchy=CODING_CLASS_HIERARCHY,
        entity_shapes=CODING_ENTITY_SHAPES,
        relationship_shapes=CODING_RELATIONSHIP_SHAPES,
        skill_map=CODING_SKILL_MAP,
        output_shapes=CODING_OUTPUT_GATES,
    )
