"""Tests for graqle.intelligence.governance.scope_gate — Scope Boundary Validation."""

# ── graqle:intelligence ──
# module: tests.test_intelligence.test_scope_gate
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pathlib, pytest, scope_gate
# constraints: none
# ── /graqle:intelligence ──

import json
from pathlib import Path

import pytest

from graqle.intelligence.governance.scope_gate import (
    ScopeDeclaration,
    ScopeGate,
    ScopeRule,
    ScopeViolation,
)


# ── ScopeRule / ScopeDeclaration ────────────────────────────────────


class TestScopeDeclaration:
    def test_creates_declaration(self):
        decl = ScopeDeclaration(task="Modify auth middleware")
        assert decl.task == "Modify auth middleware"
        assert decl.rules == []

    def test_add_include(self):
        decl = ScopeDeclaration(task="Test")
        decl.add_include("graqle/intelligence/*", "Working on intelligence layer")
        assert len(decl.rules) == 1
        assert decl.rules[0].type == "include"
        assert decl.rules[0].pattern == "graqle/intelligence/*"

    def test_add_exclude(self):
        decl = ScopeDeclaration(task="Test")
        decl.add_exclude("graqle/core/*", "Core is frozen")
        assert decl.rules[0].type == "exclude"

    def test_add_readonly(self):
        decl = ScopeDeclaration(task="Test")
        decl.add_readonly("graqle/config/*", "Config is stable")
        assert decl.rules[0].type == "readonly"

    def test_mixed_rules(self):
        decl = ScopeDeclaration(task="Complex task")
        decl.add_include("graqle/intelligence/*")
        decl.add_exclude("graqle/intelligence/governance/*")
        decl.add_readonly("graqle/core/*")
        assert len(decl.rules) == 3


# ── ScopeGate._matches ─────────────────────────────────────────────


class TestScopeGateMatching:
    def test_exact_match(self):
        assert ScopeGate._matches("graqle/core/graph.py", "graqle/core/graph.py")

    def test_prefix_wildcard(self):
        assert ScopeGate._matches("graqle/core/graph.py", "graqle/core/*")
        assert ScopeGate._matches("graqle/core/utils.py", "graqle/core/*")
        assert not ScopeGate._matches("graqle/cli/main.py", "graqle/core/*")

    def test_suffix_wildcard(self):
        assert ScopeGate._matches("graqle/core/graph.py", "*.py")
        assert not ScopeGate._matches("graqle/core/graph.js", "*.py")

    def test_contains_wildcard(self):
        assert ScopeGate._matches("graqle/core/graph.py", "*graph*")
        assert not ScopeGate._matches("graqle/core/utils.py", "*graph*")

    def test_dot_notation(self):
        assert ScopeGate._matches("graqle/core/graph.py", "graqle.core.graph")
        assert ScopeGate._matches("graqle/core/graph/utils.py", "graqle.core.graph")

    def test_no_match(self):
        assert not ScopeGate._matches("graqle/cli/main.py", "graqle/core/graph.py")

    def test_backslash_normalization(self):
        assert ScopeGate._matches("graqle\\core\\graph.py", "graqle/core/graph.py")


# ── ScopeGate.validate_changes ──────────────────────────────────────


class TestScopeGateValidation:
    def test_no_rules_no_violations(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        violations = gate.validate_changes(["graqle/anything.py"])
        assert violations == []

    def test_exclude_blocks(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        decl = ScopeDeclaration(task="Test")
        decl.add_exclude("graqle/core/*", "Core is frozen")

        violations = gate.validate_changes(
            ["graqle/core/graph.py", "graqle/intelligence/gate.py"],
            declaration=decl,
        )
        assert len(violations) == 1
        assert violations[0].severity == "BLOCK"
        assert "core/graph.py" in violations[0].target

    def test_readonly_warns(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        decl = ScopeDeclaration(task="Test")
        decl.add_readonly("graqle/config/*", "Config stable")

        violations = gate.validate_changes(
            ["graqle/config/settings.py"],
            declaration=decl,
        )
        assert len(violations) == 1
        assert violations[0].severity == "WARN"

    def test_include_scope_warns_outside(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        decl = ScopeDeclaration(task="Test")
        decl.add_include("graqle/intelligence/*")

        violations = gate.validate_changes(
            ["graqle/intelligence/gate.py", "graqle/cli/main.py"],
            declaration=decl,
        )
        # cli/main.py is outside scope
        assert len(violations) == 1
        assert "cli/main.py" in violations[0].target

    def test_include_and_exclude_combined(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        decl = ScopeDeclaration(task="Test")
        decl.add_include("graqle/intelligence/*")
        decl.add_exclude("graqle/intelligence/governance/*")

        violations = gate.validate_changes(
            [
                "graqle/intelligence/gate.py",           # in scope, not excluded
                "graqle/intelligence/governance/audit.py",  # in scope but excluded
                "graqle/cli/main.py",                     # out of scope
            ],
            declaration=decl,
        )
        # governance/audit.py → BLOCK (exclude), cli/main.py → WARN (outside include)
        assert len(violations) == 2
        severities = {v.severity for v in violations}
        assert "BLOCK" in severities
        assert "WARN" in severities

    def test_no_violations_when_all_in_scope(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        decl = ScopeDeclaration(task="Test")
        decl.add_include("graqle/intelligence/*")

        violations = gate.validate_changes(
            ["graqle/intelligence/gate.py", "graqle/intelligence/pipeline.py"],
            declaration=decl,
        )
        assert violations == []


# ── ScopeGate persistence ──────────────────────────────────────────


class TestScopeGatePersistence:
    def test_save_and_load_declaration(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        decl = ScopeDeclaration(task="Modify auth")
        decl.add_include("graqle/auth/*")
        decl.add_exclude("graqle/core/*")

        gate.save_declaration(decl)
        loaded = gate.load_declaration("Modify auth")

        assert loaded is not None
        assert loaded.task == "Modify auth"
        assert len(loaded.rules) == 2

    def test_load_nonexistent(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        assert gate.load_declaration("nonexistent") is None

    def test_save_and_load_default_rules(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        rules = [
            ScopeRule(rule_id="r1", type="exclude", pattern="graqle/core/*", reason="Frozen"),
            ScopeRule(rule_id="r2", type="readonly", pattern="graqle/config/*", reason="Stable"),
        ]
        gate.save_default_rules(rules)

        # Now validate using default rules (no declaration)
        violations = gate.validate_changes(["graqle/core/graph.py"])
        assert len(violations) == 1
        assert violations[0].severity == "BLOCK"

    def test_default_rules_empty_dir(self, tmp_path: Path):
        gate = ScopeGate(tmp_path)
        # No default.json exists
        rules = gate._load_default_rules()
        assert rules == []
