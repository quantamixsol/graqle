"""Tests for graqle.scanner.extractors.dependency — dependency manifest extractor."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_extractors.test_dependency
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, dependency
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.scanner.extractors.dependency import DependencyExtractor


def test_npm_dependencies() -> None:
    extractor = DependencyExtractor()
    data = {
        "name": "my-app",
        "dependencies": {"react": "^18.2.0", "next": "^14.0.0"},
        "devDependencies": {"typescript": "^5.0.0"},
    }
    result = extractor.extract(data, "package.json", rel_path="package.json")
    dep_nodes = [n for n in result.nodes if n.entity_type == "DEPENDENCY"]
    assert len(dep_nodes) == 3
    prod = [n for n in dep_nodes if n.properties.get("dep_type") == "production"]
    dev = [n for n in dep_nodes if n.properties.get("dep_type") == "development"]
    assert len(prod) == 2
    assert len(dev) == 1


def test_npm_scripts() -> None:
    extractor = DependencyExtractor()
    data = {
        "scripts": {"build": "next build", "test": "jest", "dev": "next dev"},
    }
    result = extractor.extract(data, "package.json", rel_path="package.json")
    script_nodes = [n for n in result.nodes if n.entity_type == "SCRIPT"]
    assert len(script_nodes) == 3
    assert any("next build" in n.description for n in script_nodes)


def test_npm_depends_on_edges() -> None:
    extractor = DependencyExtractor()
    data = {"dependencies": {"react": "^18"}}
    result = extractor.extract(data, "package.json", rel_path="package.json")
    dep_edges = [e for e in result.edges if e.relationship == "DEPENDS_ON"]
    assert len(dep_edges) == 1
    assert dep_edges[0].target_id == "dep::npm::react"


def test_npm_invokes_edges() -> None:
    extractor = DependencyExtractor()
    data = {"scripts": {"build": "webpack"}}
    result = extractor.extract(data, "package.json", rel_path="package.json")
    inv_edges = [e for e in result.edges if e.relationship == "INVOKES"]
    assert len(inv_edges) == 1


def test_pipfile_packages() -> None:
    extractor = DependencyExtractor()
    data = {
        "packages": {"flask": "*", "requests": ">=2.28"},
        "dev-packages": {"pytest": "*"},
    }
    result = extractor.extract(data, "Pipfile", rel_path="Pipfile")
    dep_nodes = [n for n in result.nodes if n.entity_type == "DEPENDENCY"]
    assert len(dep_nodes) == 3
    assert any(n.properties.get("manager") == "pip" for n in dep_nodes)


def test_composer_require() -> None:
    extractor = DependencyExtractor()
    data = {"require": {"php": "^8.1", "laravel/framework": "^10.0"}}
    result = extractor.extract(data, "composer.json", rel_path="composer.json")
    dep_nodes = [n for n in result.nodes if n.entity_type == "DEPENDENCY"]
    assert len(dep_nodes) == 2
    assert any(n.properties.get("manager") == "composer" for n in dep_nodes)


def test_node_ids_are_unique() -> None:
    extractor = DependencyExtractor()
    data = {"dependencies": {"react": "^18", "next": "^14"}}
    result = extractor.extract(data, "package.json", rel_path="package.json")
    ids = [n.id for n in result.nodes]
    assert len(ids) == len(set(ids))


def test_empty_data_no_crash() -> None:
    extractor = DependencyExtractor()
    result = extractor.extract({}, "empty.json", rel_path="empty.json")
    assert len(result.nodes) == 0
    assert len(result.edges) == 0
