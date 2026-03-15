"""Tool config extractor — tsconfig.json, .eslintrc.json, .prettierrc.json.

Produces ``ToolRule`` nodes with ``APPLIES_TO`` edges.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.extractors.tool_config
# risk: LOW (impact radius: 1 modules)
# consumers: test_tool_config
# dependencies: __future__, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Any

from graqle.scanner.extractors.base import (
    BaseExtractor,
    ExtractedNode,
    ExtractionResult,
)


class ToolConfigExtractor(BaseExtractor):
    """Extract tool configuration rules."""

    def extract(
        self,
        data: dict[str, Any],
        file_path: str,
        *,
        rel_path: str = "",
    ) -> ExtractionResult:
        result = ExtractionResult()
        source = rel_path or file_path
        fname = source.rsplit("/", 1)[-1].lower() if "/" in source else source.lower()

        # Detect tool type
        if "compilerOptions" in data:
            self._extract_tsconfig(data, source, result)
        elif "rules" in data or "extends" in data:
            self._extract_lint_config(data, source, fname, result)
        else:
            # Generic tool config — extract top-level keys
            self._extract_generic(data, source, fname, result)

        return result

    def _extract_tsconfig(
        self, data: dict, source: str, result: ExtractionResult
    ) -> None:
        compiler = data.get("compilerOptions", {})
        important_keys = {
            "strict", "target", "module", "moduleResolution", "jsx",
            "esModuleInterop", "skipLibCheck", "outDir", "rootDir",
            "baseUrl", "paths", "lib", "allowJs", "declaration",
        }

        for key, value in compiler.items():
            if key not in important_keys:
                continue
            rule_id = f"rule::typescript::{key}"
            val_str = str(value)
            result.nodes.append(ExtractedNode(
                id=rule_id,
                label=f"ts.{key}={val_str[:40]}",
                entity_type="TOOL_RULE",
                description=f"TypeScript compiler option '{key}' set to {val_str}",
                properties={
                    "tool": "typescript",
                    "key": key,
                    "value": value if isinstance(value, (str, bool, int, float)) else val_str,
                    "source": source,
                },
            ))

    def _extract_lint_config(
        self, data: dict, source: str, fname: str, result: ExtractionResult
    ) -> None:
        # Determine tool name
        tool = "eslint"
        if "prettier" in fname:
            tool = "prettier"
        elif "stylelint" in fname:
            tool = "stylelint"

        rules = data.get("rules", {})
        for rule_name, value in list(rules.items())[:30]:
            # Normalize value
            if isinstance(value, list):
                severity = value[0] if value else "off"
            else:
                severity = value

            rule_id = f"rule::{tool}::{rule_name}"
            result.nodes.append(ExtractedNode(
                id=rule_id,
                label=f"{tool}.{rule_name}",
                entity_type="TOOL_RULE",
                description=f"{tool} rule '{rule_name}' set to {severity}",
                properties={
                    "tool": tool,
                    "rule": rule_name,
                    "severity": str(severity),
                    "source": source,
                },
            ))

    def _extract_generic(
        self, data: dict, source: str, fname: str, result: ExtractionResult
    ) -> None:
        # Extract as a single config node with top-level keys summarized
        tool_name = fname.replace(".", "_").replace("rc", "").strip("_")
        node_id = f"config::tool::{tool_name}"
        keys = list(data.keys())[:20]

        result.nodes.append(ExtractedNode(
            id=node_id,
            label=f"Tool: {fname}",
            entity_type="TOOL_RULE",
            description=f"Tool configuration from {source} with keys: {', '.join(keys)}",
            properties={
                "tool": tool_name,
                "keys": keys,
                "source": source,
            },
        ))
