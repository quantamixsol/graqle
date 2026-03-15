"""Tests for graqle.scanner.extractors.tool_config — tool config extractor."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_extractors.test_tool_config
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, tool_config
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.scanner.extractors.tool_config import ToolConfigExtractor


def test_tsconfig_rules() -> None:
    extractor = ToolConfigExtractor()
    data = {
        "compilerOptions": {
            "strict": True,
            "target": "es2020",
            "module": "esnext",
            "jsx": "react-jsx",
            "randomUnknown": "value",  # not in important_keys
        }
    }
    result = extractor.extract(data, "tsconfig.json")
    rules = [n for n in result.nodes if n.entity_type == "TOOL_RULE"]
    assert len(rules) >= 3  # strict, target, module, jsx
    assert any("strict" in n.id for n in rules)
    assert any("target" in n.id for n in rules)


def test_eslint_rules() -> None:
    extractor = ToolConfigExtractor()
    data = {
        "extends": ["eslint:recommended"],
        "rules": {
            "no-console": "warn",
            "semi": ["error", "always"],
            "no-unused-vars": "error",
        },
    }
    result = extractor.extract(data, ".eslintrc.json")
    rules = [n for n in result.nodes if n.entity_type == "TOOL_RULE"]
    assert len(rules) == 3
    assert any("eslint" in n.id for n in rules)


def test_prettier_config() -> None:
    extractor = ToolConfigExtractor()
    data = {
        "rules": {"printWidth": 100, "tabWidth": 2},
    }
    result = extractor.extract(data, ".prettierrc.json", rel_path=".prettierrc.json")
    rules = [n for n in result.nodes if n.entity_type == "TOOL_RULE"]
    assert len(rules) == 2
    assert any("prettier" in n.id for n in rules)


def test_generic_tool_config() -> None:
    extractor = ToolConfigExtractor()
    data = {"key1": "value1", "key2": 42}
    result = extractor.extract(data, "custom-tool.json")
    assert len(result.nodes) >= 1


def test_eslint_rule_severity() -> None:
    extractor = ToolConfigExtractor()
    data = {"rules": {"no-console": ["warn", {"allow": ["error"]}]}}
    result = extractor.extract(data, ".eslintrc.json")
    rule = result.nodes[0]
    assert rule.properties["severity"] == "warn"


def test_empty_rules() -> None:
    extractor = ToolConfigExtractor()
    data = {"rules": {}}
    result = extractor.extract(data, ".eslintrc.json")
    assert len(result.nodes) == 0
