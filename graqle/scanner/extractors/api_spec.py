"""OpenAPI / Swagger extractor — the single most valuable JSON file.

Produces ``Endpoint`` and ``Schema`` nodes with ``RETURNS`` edges.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.extractors.api_spec
# risk: LOW (impact radius: 1 modules)
# consumers: test_api_spec
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


class APISpecExtractor(BaseExtractor):
    """Extract endpoints and schemas from OpenAPI/Swagger specs."""

    def extract(
        self,
        data: dict[str, Any],
        file_path: str,
        *,
        rel_path: str = "",
    ) -> ExtractionResult:
        result = ExtractionResult()
        source = rel_path or file_path

        # Extract info
        info = data.get("info", {})
        api_title = info.get("title", "API")
        api_version = info.get("version", "")

        # OpenAPI 3.x paths
        paths = data.get("paths", {})
        for route, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if method.startswith("x-") or method == "parameters":
                    continue
                if not isinstance(operation, dict):
                    continue
                self._extract_endpoint(
                    method, route, operation, source, api_title, result,
                )

        # Schemas (OpenAPI 3.x: components/schemas, Swagger 2: definitions)
        schemas = {}
        if "components" in data and "schemas" in data["components"]:
            schemas = data["components"]["schemas"]
        elif "definitions" in data:
            schemas = data["definitions"]

        for schema_name, schema_def in schemas.items():
            if not isinstance(schema_def, dict):
                continue
            self._extract_schema(schema_name, schema_def, source, result)

        return result

    def _extract_endpoint(
        self,
        method: str,
        route: str,
        operation: dict,
        source: str,
        api_title: str,
        result: ExtractionResult,
    ) -> None:
        method_upper = method.upper()
        endpoint_id = f"endpoint::{method_upper}::{route}"
        summary = operation.get("summary", "")
        description = operation.get("description", summary)
        operation_id = operation.get("operationId", "")
        tags = operation.get("tags", [])

        # Extract parameters
        params = []
        for p in operation.get("parameters", []):
            if isinstance(p, dict):
                params.append({
                    "name": p.get("name", ""),
                    "in": p.get("in", ""),
                    "required": p.get("required", False),
                })

        # Extract request body schema ref
        request_body = operation.get("requestBody", {})
        req_schema_ref = self._get_schema_ref(request_body)

        # Extract response schema ref
        responses = operation.get("responses", {})
        resp_schema_ref = None
        for code, resp in responses.items():
            if code.startswith("2") and isinstance(resp, dict):
                resp_schema_ref = self._get_schema_ref(resp)
                if resp_schema_ref:
                    break

        result.nodes.append(ExtractedNode(
            id=endpoint_id,
            label=f"{method_upper} {route}",
            entity_type="ENDPOINT",
            description=description[:500] if description else f"{method_upper} {route}",
            properties={
                "method": method_upper,
                "route": route,
                "summary": summary,
                "operation_id": operation_id,
                "tags": tags,
                "parameters": params,
                "source": source,
                "api_title": api_title,
            },
        ))

        # Edge: endpoint → response schema
        if resp_schema_ref:
            schema_id = f"schema::{resp_schema_ref}"
            result.edges.append(ExtractedEdge(
                source_id=endpoint_id,
                target_id=schema_id,
                relationship="RETURNS",
            ))

        # Edge: request body schema → endpoint
        if req_schema_ref:
            schema_id = f"schema::{req_schema_ref}"
            result.edges.append(ExtractedEdge(
                source_id=endpoint_id,
                target_id=schema_id,
                relationship="ACCEPTS",
            ))

    def _extract_schema(
        self,
        name: str,
        schema_def: dict,
        source: str,
        result: ExtractionResult,
    ) -> None:
        schema_id = f"schema::{name}"
        schema_type = schema_def.get("type", "object")
        properties = schema_def.get("properties", {})
        required_fields = schema_def.get("required", [])

        field_names = list(properties.keys())[:20]
        desc = f"Schema '{name}' ({schema_type})"
        if field_names:
            desc += f" with fields: {', '.join(field_names)}"

        result.nodes.append(ExtractedNode(
            id=schema_id,
            label=name,
            entity_type="SCHEMA",
            description=desc,
            properties={
                "schema_type": schema_type,
                "fields": field_names,
                "required_fields": required_fields,
                "source": source,
            },
        ))

    @staticmethod
    def _get_schema_ref(body: dict) -> str | None:
        """Extract schema name from a $ref in request/response body."""
        if not isinstance(body, dict):
            return None

        # OpenAPI 3.x: content -> application/json -> schema -> $ref
        content = body.get("content", {})
        for media_type in ("application/json", "application/xml", "*/*"):
            media = content.get(media_type, {})
            if isinstance(media, dict):
                schema = media.get("schema", {})
                if isinstance(schema, dict):
                    ref = schema.get("$ref", "")
                    if ref:
                        return ref.rsplit("/", 1)[-1]

        # Swagger 2.x: schema -> $ref
        schema = body.get("schema", {})
        if isinstance(schema, dict):
            ref = schema.get("$ref", "")
            if ref:
                return ref.rsplit("/", 1)[-1]

        return None
