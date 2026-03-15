"""Dependency manifest extractor — package.json, Pipfile, composer.json.

Produces ``Dependency`` and ``Script`` nodes with ``DEPENDS_ON`` and
``INVOKES`` edges.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.extractors.dependency
# risk: LOW (impact radius: 1 modules)
# consumers: test_dependency
# dependencies: __future__, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Any

from graqle.scanner.extractors.base import (
    BaseExtractor,
    ExtractedEdge,
    ExtractedNode,
    ExtractionResult,
)


class DependencyExtractor(BaseExtractor):
    """Extract dependencies and scripts from package manifests."""

    def extract(
        self,
        data: dict[str, Any],
        file_path: str,
        *,
        rel_path: str = "",
    ) -> ExtractionResult:
        result = ExtractionResult()
        source = rel_path or file_path

        # Detect manifest type
        if "dependencies" in data or "devDependencies" in data or "scripts" in data:
            self._extract_npm(data, source, result)
        elif "packages" in data or "dev-packages" in data:
            self._extract_pipfile(data, source, result)
        elif "require" in data:
            self._extract_composer(data, source, result)

        return result

    def _extract_npm(
        self, data: dict, source: str, result: ExtractionResult
    ) -> None:
        project_name = data.get("name", source)

        # Production dependencies
        for name, version in data.get("dependencies", {}).items():
            dep_id = f"dep::npm::{name}"
            result.nodes.append(ExtractedNode(
                id=dep_id,
                label=name,
                entity_type="DEPENDENCY",
                description=f"npm dependency {name}@{version}",
                properties={
                    "version": str(version),
                    "manager": "npm",
                    "dep_type": "production",
                    "source": source,
                },
            ))
            result.edges.append(ExtractedEdge(
                source_id=f"json::{source}",
                target_id=dep_id,
                relationship="DEPENDS_ON",
            ))

        # Dev dependencies
        for name, version in data.get("devDependencies", {}).items():
            dep_id = f"dep::npm::{name}"
            result.nodes.append(ExtractedNode(
                id=dep_id,
                label=name,
                entity_type="DEPENDENCY",
                description=f"npm dev dependency {name}@{version}",
                properties={
                    "version": str(version),
                    "manager": "npm",
                    "dep_type": "development",
                    "source": source,
                },
            ))
            result.edges.append(ExtractedEdge(
                source_id=f"json::{source}",
                target_id=dep_id,
                relationship="DEPENDS_ON",
            ))

        # Scripts
        for name, command in data.get("scripts", {}).items():
            script_id = f"script::npm::{name}"
            result.nodes.append(ExtractedNode(
                id=script_id,
                label=f"npm run {name}",
                entity_type="SCRIPT",
                description=f"npm script '{name}': {command}",
                properties={
                    "command": str(command),
                    "manager": "npm",
                    "source": source,
                },
            ))
            result.edges.append(ExtractedEdge(
                source_id=script_id,
                target_id=f"json::{source}",
                relationship="INVOKES",
            ))

    def _extract_pipfile(
        self, data: dict, source: str, result: ExtractionResult
    ) -> None:
        for name, version in data.get("packages", {}).items():
            ver_str = version if isinstance(version, str) else str(version)
            dep_id = f"dep::pip::{name}"
            result.nodes.append(ExtractedNode(
                id=dep_id,
                label=name,
                entity_type="DEPENDENCY",
                description=f"pip dependency {name} {ver_str}",
                properties={
                    "version": ver_str,
                    "manager": "pip",
                    "dep_type": "production",
                    "source": source,
                },
            ))
            result.edges.append(ExtractedEdge(
                source_id=f"json::{source}",
                target_id=dep_id,
                relationship="DEPENDS_ON",
            ))

        for name, version in data.get("dev-packages", {}).items():
            ver_str = version if isinstance(version, str) else str(version)
            dep_id = f"dep::pip::{name}"
            result.nodes.append(ExtractedNode(
                id=dep_id,
                label=name,
                entity_type="DEPENDENCY",
                description=f"pip dev dependency {name} {ver_str}",
                properties={
                    "version": ver_str,
                    "manager": "pip",
                    "dep_type": "development",
                    "source": source,
                },
            ))
            result.edges.append(ExtractedEdge(
                source_id=f"json::{source}",
                target_id=dep_id,
                relationship="DEPENDS_ON",
            ))

    def _extract_composer(
        self, data: dict, source: str, result: ExtractionResult
    ) -> None:
        for name, version in data.get("require", {}).items():
            dep_id = f"dep::composer::{name}"
            result.nodes.append(ExtractedNode(
                id=dep_id,
                label=name,
                entity_type="DEPENDENCY",
                description=f"Composer dependency {name} {version}",
                properties={
                    "version": str(version),
                    "manager": "composer",
                    "dep_type": "production",
                    "source": source,
                },
            ))
            result.edges.append(ExtractedEdge(
                source_id=f"json::{source}",
                target_id=dep_id,
                relationship="DEPENDS_ON",
            ))
