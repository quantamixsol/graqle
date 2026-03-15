"""Tests for graqle.scanner.extractors.infra — infrastructure extractor."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_extractors.test_infra
# risk: LOW (impact radius: 1 modules)
# consumers: background
# dependencies: __future__, infra
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.scanner.extractors.infra import InfraExtractor


def test_cfn_lambda_resource() -> None:
    extractor = InfraExtractor()
    data = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "AuthHandler": {
                "Type": "AWS::Lambda::Function",
                "Properties": {
                    "Runtime": "python3.11",
                    "Handler": "handler.main",
                    "MemorySize": 256,
                },
            }
        },
    }
    result = extractor.extract(data, "template.json")
    resources = [n for n in result.nodes if n.entity_type == "RESOURCE"]
    assert len(resources) == 1
    r = resources[0]
    assert "Lambda" in r.label or "Function" in r.label
    assert r.properties["runtime"] == "python3.11"
    assert r.properties["handler"] == "handler.main"


def test_cfn_dynamodb_table() -> None:
    extractor = InfraExtractor()
    data = {
        "Resources": {
            "UsersTable": {
                "Type": "AWS::DynamoDB::Table",
                "Properties": {"TableName": "users"},
            }
        },
    }
    result = extractor.extract(data, "stack.json")
    resources = [n for n in result.nodes if n.entity_type == "RESOURCE"]
    assert len(resources) == 1
    assert "users" in resources[0].description.lower()


def test_cfn_ref_creates_edge() -> None:
    extractor = InfraExtractor()
    data = {
        "Resources": {
            "MyFunc": {
                "Type": "AWS::Lambda::Function",
                "Properties": {
                    "Environment": {
                        "Variables": {
                            "TABLE_NAME": {"Ref": "UsersTable"}
                        }
                    }
                },
            },
            "UsersTable": {
                "Type": "AWS::DynamoDB::Table",
                "Properties": {},
            },
        },
    }
    result = extractor.extract(data, "template.json")
    edges = [e for e in result.edges if e.relationship == "READS_FROM"]
    assert len(edges) >= 1


def test_serverless_functions() -> None:
    extractor = InfraExtractor()
    data = {
        "service": "my-api",
        "provider": {"runtime": "nodejs18.x"},
        "functions": {
            "auth": {"handler": "src/auth.handler", "memorySize": 128},
            "users": {"handler": "src/users.handler"},
        },
    }
    result = extractor.extract(data, "serverless.json")
    resources = [n for n in result.nodes if n.entity_type == "RESOURCE"]
    assert len(resources) == 2


def test_cdk_context() -> None:
    extractor = InfraExtractor()
    data = {"app": "npx ts-node bin/app.ts", "context": {"env": "prod"}}
    result = extractor.extract(data, "cdk.json")
    configs = [n for n in result.nodes if n.entity_type == "CONFIG"]
    assert len(configs) == 1


def test_empty_resources() -> None:
    extractor = InfraExtractor()
    data = {"AWSTemplateFormatVersion": "2010-09-09", "Resources": {}}
    result = extractor.extract(data, "empty.json")
    assert len(result.nodes) == 0


def test_multiple_resources_and_refs() -> None:
    extractor = InfraExtractor()
    data = {
        "Resources": {
            "Lambda1": {
                "Type": "AWS::Lambda::Function",
                "Properties": {"Runtime": "python3.11", "Handler": "h.main"},
            },
            "Lambda2": {
                "Type": "AWS::Lambda::Function",
                "Properties": {
                    "Runtime": "python3.11",
                    "Handler": "h2.main",
                    "Environment": {"Variables": {"FN1": {"Fn::GetAtt": ["Lambda1", "Arn"]}}},
                },
            },
            "Bucket": {
                "Type": "AWS::S3::Bucket",
                "Properties": {"BucketName": "my-bucket"},
            },
        },
    }
    result = extractor.extract(data, "stack.json")
    assert len(result.nodes) == 3
    # Lambda2 refs Lambda1 via Fn::GetAtt
    ref_edges = [e for e in result.edges if e.relationship == "READS_FROM"]
    assert len(ref_edges) >= 1
