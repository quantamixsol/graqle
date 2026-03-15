"""Tests for graqle.scanner.extractors.app_config — app config extractor."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_extractors.test_app_config
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, app_config
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.scanner.extractors.app_config import AppConfigExtractor


def test_flat_config() -> None:
    extractor = AppConfigExtractor()
    data = {"debug": True, "port": 8080, "host": "localhost"}
    result = extractor.extract(data, "config.json", rel_path="config/app.json")
    configs = [n for n in result.nodes if n.entity_type == "CONFIG"]
    assert len(configs) == 3
    assert any("debug" in n.properties.get("key", "") for n in configs)


def test_nested_config() -> None:
    extractor = AppConfigExtractor()
    data = {
        "auth": {
            "token_expiry": 3600,
            "algorithm": "RS256",
        },
        "database": {
            "host": "localhost",
        },
    }
    result = extractor.extract(data, "settings.json")
    configs = [n for n in result.nodes if n.entity_type == "CONFIG"]
    assert len(configs) >= 3
    keys = {n.properties.get("key", "") for n in configs}
    assert "auth.token_expiry" in keys
    assert "auth.algorithm" in keys


def test_secrets_skipped() -> None:
    extractor = AppConfigExtractor()
    data = {
        "api_key": "sk-secret-123",
        "password": "hunter2",
        "host": "localhost",
    }
    result = extractor.extract(data, "config.json")
    configs = [n for n in result.nodes if n.entity_type == "CONFIG"]
    # Only host should remain
    assert len(configs) == 1
    assert configs[0].properties["key"] == "host"


def test_list_values() -> None:
    extractor = AppConfigExtractor()
    data = {"allowed_origins": ["http://localhost", "https://app.example.com"]}
    result = extractor.extract(data, "cors.json")
    configs = [n for n in result.nodes if n.entity_type == "CONFIG"]
    assert len(configs) == 1
    assert configs[0].properties["value_type"] == "list"


def test_large_list_skipped() -> None:
    extractor = AppConfigExtractor()
    data = {"big_array": list(range(50))}
    result = extractor.extract(data, "data.json")
    configs = [n for n in result.nodes if n.entity_type == "CONFIG"]
    assert len(configs) == 0  # >10 items → skipped


def test_max_depth() -> None:
    extractor = AppConfigExtractor()
    data = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
    result = extractor.extract(data, "deep.json")
    configs = [n for n in result.nodes if n.entity_type == "CONFIG"]
    # Should not go deeper than 3 levels
    keys = {n.properties.get("key", "") for n in configs}
    assert not any("e" in k for k in keys)


def test_empty_data() -> None:
    extractor = AppConfigExtractor()
    result = extractor.extract({}, "empty.json")
    assert len(result.nodes) == 0


def test_value_types_preserved() -> None:
    extractor = AppConfigExtractor()
    data = {"flag": True, "count": 42, "rate": 0.5, "name": "test"}
    result = extractor.extract(data, "types.json")
    configs = {n.properties["key"]: n for n in result.nodes}
    assert configs["flag"].properties["value"] is True
    assert configs["count"].properties["value"] == 42
    assert configs["rate"].properties["value"] == 0.5
    assert configs["name"].properties["value"] == "test"
