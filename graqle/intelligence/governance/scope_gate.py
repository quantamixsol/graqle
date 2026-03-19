# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ──────────────────────────────────────────────────────────────────

"""Scope Boundary Validation — Prevents AI tools from exceeding change scope.

Mapped from TAMR+ semantic_shacl_gate.py.
Validates that proposed changes stay within declared scope boundaries.

When an AI tool is about to modify code, the scope gate checks:
1. Is this module within the declared task scope?
2. Does the change respect module ownership boundaries?
3. Are cross-module side effects acknowledged?

See ADR-105 §Governance Layer: semantic_shacl_gate.py → governance/scope_gate.py.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.governance.scope_gate
# risk: LOW (impact radius: 2 modules)
# consumers: __init__, test_scope_gate
# dependencies: __future__, json, logging, pathlib, typing +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("graqle.intelligence.governance.scope_gate")


class ScopeRule(BaseModel):
    """A single scope boundary rule."""

    rule_id: str
    type: Literal["include", "exclude", "readonly", "owner"]
    pattern: str              # glob or module pattern
    reason: str = ""          # why this boundary exists
    owner: str = ""           # team or person who owns this boundary


class ScopeViolation(BaseModel):
    """A detected scope boundary violation."""

    rule: ScopeRule
    target: str               # module or file that violated the rule
    severity: Literal["BLOCK", "WARN"] = "WARN"
    message: str = ""


class ScopeDeclaration(BaseModel):
    """Declares the scope for a task — what modules can be touched."""

    task: str                  # "Modify auth middleware"
    declared_modules: list[str] = Field(default_factory=list)
    rules: list[ScopeRule] = Field(default_factory=list)

    def add_include(self, pattern: str, reason: str = "") -> None:
        """Declare a module pattern as in-scope."""
        self.rules.append(ScopeRule(
            rule_id=f"include-{len(self.rules)}",
            type="include",
            pattern=pattern,
            reason=reason,
        ))

    def add_exclude(self, pattern: str, reason: str = "") -> None:
        """Declare a module pattern as out-of-scope."""
        self.rules.append(ScopeRule(
            rule_id=f"exclude-{len(self.rules)}",
            type="exclude",
            pattern=pattern,
            reason=reason,
        ))

    def add_readonly(self, pattern: str, reason: str = "") -> None:
        """Mark a module pattern as read-only (can read, can't modify)."""
        self.rules.append(ScopeRule(
            rule_id=f"readonly-{len(self.rules)}",
            type="readonly",
            pattern=pattern,
            reason=reason,
        ))


class ScopeGate:
    """Validates proposed changes against declared scope boundaries.

    The gate reads scope rules from .graqle/governance/scope/ and
    validates that file changes stay within boundaries.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.scope_dir = root / ".graqle" / "governance" / "scope"

    def _ensure_dir(self) -> None:
        self.scope_dir.mkdir(parents=True, exist_ok=True)

    def validate_changes(
        self,
        changed_files: list[str],
        declaration: ScopeDeclaration | None = None,
    ) -> list[ScopeViolation]:
        """Validate a set of changed files against scope rules.

        If no declaration provided, loads default rules from disk.
        """
        rules = declaration.rules if declaration else self._load_default_rules()
        if not rules:
            return []  # No scope rules = everything is in scope

        violations: list[ScopeViolation] = []

        for fpath in changed_files:
            normalized = fpath.replace("\\", "/")
            file_violations = self._check_file(normalized, rules)
            violations.extend(file_violations)

        return violations

    def _check_file(
        self,
        file_path: str,
        rules: list[ScopeRule],
    ) -> list[ScopeViolation]:
        """Check a single file against all scope rules."""
        violations: list[ScopeViolation] = []

        # Check exclude rules first (they block)
        for rule in rules:
            if rule.type == "exclude" and self._matches(file_path, rule.pattern):
                violations.append(ScopeViolation(
                    rule=rule,
                    target=file_path,
                    severity="BLOCK",
                    message=f"File '{file_path}' matches exclude pattern '{rule.pattern}'. {rule.reason}",
                ))

            elif rule.type == "readonly" and self._matches(file_path, rule.pattern):
                violations.append(ScopeViolation(
                    rule=rule,
                    target=file_path,
                    severity="WARN",
                    message=f"File '{file_path}' is marked read-only: '{rule.pattern}'. {rule.reason}",
                ))

        # Check if file is within any include scope
        include_rules = [r for r in rules if r.type == "include"]
        if include_rules:
            in_scope = any(
                self._matches(file_path, r.pattern) for r in include_rules
            )
            if not in_scope:
                violations.append(ScopeViolation(
                    rule=include_rules[0],
                    target=file_path,
                    severity="WARN",
                    message=f"File '{file_path}' is outside declared scope.",
                ))

        return violations

    @staticmethod
    def _matches(file_path: str, pattern: str) -> bool:
        """Check if a file path matches a scope pattern.

        Supports:
        - Exact match: "graqle/core/graph.py"
        - Prefix match: "graqle/core/*"
        - Contains match: "*graph*"
        - Module dot notation: "graqle.core.graph"
        """
        # Normalize both to forward slashes
        fp = file_path.replace("\\", "/")
        pat = pattern.replace("\\", "/")

        # Convert dot notation to path
        if "." in pat and "/" not in pat and "*" not in pat:
            pat = pat.replace(".", "/")
            # Check with common extensions
            for ext in (".py", ".js", ".ts", ".jsx", ".tsx", ""):
                if fp == pat + ext or fp.startswith(pat + "/"):
                    return True
            return False

        # Wildcard matching
        if pat.endswith("/*"):
            prefix = pat[:-2]
            return fp.startswith(prefix + "/") or fp == prefix

        if pat.startswith("*") and pat.endswith("*"):
            return pat[1:-1] in fp

        if pat.endswith("*"):
            return fp.startswith(pat[:-1])

        if pat.startswith("*"):
            return fp.endswith(pat[1:])

        return fp == pat

    def save_declaration(self, declaration: ScopeDeclaration) -> None:
        """Persist a scope declaration to disk."""
        self._ensure_dir()
        safe_name = declaration.task.replace(" ", "_").lower()[:50]
        fpath = self.scope_dir / f"{safe_name}.json"
        fpath.write_text(
            json.dumps(declaration.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )

    def load_declaration(self, task_name: str) -> ScopeDeclaration | None:
        """Load a scope declaration from disk."""
        safe_name = task_name.replace(" ", "_").lower()[:50]
        fpath = self.scope_dir / f"{safe_name}.json"
        if not fpath.exists():
            return None
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return ScopeDeclaration(**data)

    def _load_default_rules(self) -> list[ScopeRule]:
        """Load default scope rules from .graqle/governance/scope/default.json."""
        fpath = self.scope_dir / "default.json"
        if not fpath.exists():
            return []
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            return [ScopeRule(**r) for r in data.get("rules", [])]
        except (json.JSONDecodeError, OSError):
            return []

    def save_default_rules(self, rules: list[ScopeRule]) -> None:
        """Persist default scope rules."""
        self._ensure_dir()
        fpath = self.scope_dir / "default.json"
        fpath.write_text(
            json.dumps(
                {"rules": [r.model_dump() for r in rules]},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
