"""Infrastructure config extractor — CDK, SAM, CloudFormation, Serverless.

Produces ``Resource`` nodes with ``READS_FROM`` and ``TRIGGERS`` edges.
"""

# ── graqle:intelligence ──
# module: graqle.scanner.extractors.infra
# risk: LOW (impact radius: 2 modules)
# consumers: background, test_infra
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


class InfraExtractor(BaseExtractor):
    """Extract infrastructure resources from IaC JSON configs."""

    def extract(
        self,
        data: dict[str, Any],
        file_path: str,
        *,
        rel_path: str = "",
    ) -> ExtractionResult:
        result = ExtractionResult()
        source = rel_path or file_path

        # CloudFormation / SAM
        if "Resources" in data or "AWSTemplateFormatVersion" in data:
            self._extract_cfn(data, source, result)
        # Serverless Framework
        elif "service" in data and "functions" in data:
            self._extract_serverless(data, source, result)
        # CDK context
        elif "app" in data or "context" in data:
            # CDK context files are minimal — just record the config
            self._extract_cdk(data, source, result)

        return result

    def _extract_cfn(
        self, data: dict, source: str, result: ExtractionResult
    ) -> None:
        resources = data.get("Resources", {})
        resource_ids: dict[str, str] = {}  # logical_id → node_id

        for logical_id, resource in resources.items():
            if not isinstance(resource, dict):
                continue
            res_type = resource.get("Type", "Unknown")
            props = resource.get("Properties", {})

            node_id = f"resource::{logical_id}"
            resource_ids[logical_id] = node_id

            # Build description
            short_type = res_type.split("::")[-1] if "::" in res_type else res_type
            desc = f"AWS {short_type} resource '{logical_id}'"

            extra: dict[str, Any] = {"aws_type": res_type, "source": source}

            # Lambda-specific
            if "Lambda" in res_type and "Function" in res_type:
                runtime = props.get("Runtime", "")
                handler = props.get("Handler", "")
                memory = props.get("MemorySize", "")
                desc = f"Lambda function '{logical_id}' ({runtime}, handler={handler})"
                extra.update({"runtime": runtime, "handler": handler, "memory": memory})

            # DynamoDB
            if "DynamoDB" in res_type and "Table" in res_type:
                table_name = props.get("TableName", logical_id)
                desc = f"DynamoDB table '{table_name}'"
                extra["table_name"] = table_name

            # S3
            if "S3" in res_type and "Bucket" in res_type:
                bucket_name = props.get("BucketName", logical_id)
                desc = f"S3 bucket '{bucket_name}'"
                extra["bucket_name"] = bucket_name

            result.nodes.append(ExtractedNode(
                id=node_id,
                label=f"{short_type}:{logical_id}",
                entity_type="RESOURCE",
                description=desc,
                properties=extra,
            ))

        # Infer resource relationships from Ref / Fn::GetAtt
        for logical_id, resource in resources.items():
            if logical_id not in resource_ids:
                continue
            src_id = resource_ids[logical_id]
            refs = self._find_refs(resource)
            for ref_id in refs:
                if ref_id in resource_ids and ref_id != logical_id:
                    tgt_id = resource_ids[ref_id]
                    result.edges.append(ExtractedEdge(
                        source_id=src_id,
                        target_id=tgt_id,
                        relationship="READS_FROM",
                    ))

    def _extract_serverless(
        self, data: dict, source: str, result: ExtractionResult
    ) -> None:
        service_name = data.get("service", "service")
        for fn_name, fn_config in data.get("functions", {}).items():
            if not isinstance(fn_config, dict):
                continue
            handler = fn_config.get("handler", "")
            runtime = fn_config.get("runtime", data.get("provider", {}).get("runtime", ""))
            memory = fn_config.get("memorySize", "")
            events = fn_config.get("events", [])

            node_id = f"resource::sls::{fn_name}"
            desc = f"Serverless function '{fn_name}' (handler={handler})"

            result.nodes.append(ExtractedNode(
                id=node_id,
                label=f"Lambda:{fn_name}",
                entity_type="RESOURCE",
                description=desc,
                properties={
                    "service": service_name,
                    "handler": handler,
                    "runtime": str(runtime),
                    "memory": str(memory),
                    "event_count": len(events),
                    "source": source,
                },
            ))

    def _extract_cdk(
        self, data: dict, source: str, result: ExtractionResult
    ) -> None:
        node_id = f"config::cdk::{source}"
        result.nodes.append(ExtractedNode(
            id=node_id,
            label="CDK Config",
            entity_type="CONFIG",
            description=f"CDK configuration from {source}",
            properties={"source": source, "keys": list(data.keys())[:20]},
        ))

    @staticmethod
    def _find_refs(obj: Any) -> list[str]:
        """Recursively find all Ref and Fn::GetAtt references."""
        refs: list[str] = []
        if isinstance(obj, dict):
            if "Ref" in obj and isinstance(obj["Ref"], str):
                refs.append(obj["Ref"])
            if "Fn::GetAtt" in obj:
                att = obj["Fn::GetAtt"]
                if isinstance(att, list) and att:
                    refs.append(str(att[0]))
            for v in obj.values():
                refs.extend(InfraExtractor._find_refs(v))
        elif isinstance(obj, list):
            for item in obj:
                refs.extend(InfraExtractor._find_refs(item))
        return refs
