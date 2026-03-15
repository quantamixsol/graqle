"""Tests for graqle.scanner.extractors.api_spec — OpenAPI/Swagger extractor."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_extractors.test_api_spec
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, api_spec
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.scanner.extractors.api_spec import APISpecExtractor


def _openapi_data() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/api/auth/login": {
                "post": {
                    "summary": "User login",
                    "operationId": "login",
                    "tags": ["auth"],
                    "parameters": [
                        {"name": "tenant", "in": "header", "required": True}
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/LoginRequest"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AuthResponse"}
                                }
                            }
                        }
                    },
                }
            },
            "/api/users": {
                "get": {
                    "summary": "List users",
                    "responses": {"200": {}},
                }
            },
        },
        "components": {
            "schemas": {
                "AuthResponse": {
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                        "user_id": {"type": "integer"},
                    },
                    "required": ["token"],
                },
                "LoginRequest": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "password": {"type": "string"},
                    },
                },
            }
        },
    }


def test_endpoints_extracted() -> None:
    extractor = APISpecExtractor()
    result = extractor.extract(_openapi_data(), "openapi.json")
    endpoints = [n for n in result.nodes if n.entity_type == "ENDPOINT"]
    assert len(endpoints) == 2
    labels = {n.label for n in endpoints}
    assert "POST /api/auth/login" in labels
    assert "GET /api/users" in labels


def test_schemas_extracted() -> None:
    extractor = APISpecExtractor()
    result = extractor.extract(_openapi_data(), "openapi.json")
    schemas = [n for n in result.nodes if n.entity_type == "SCHEMA"]
    assert len(schemas) == 2
    names = {n.label for n in schemas}
    assert "AuthResponse" in names
    assert "LoginRequest" in names


def test_returns_edge() -> None:
    extractor = APISpecExtractor()
    result = extractor.extract(_openapi_data(), "openapi.json")
    returns = [e for e in result.edges if e.relationship == "RETURNS"]
    assert len(returns) == 1
    assert returns[0].target_id == "schema::AuthResponse"


def test_accepts_edge() -> None:
    extractor = APISpecExtractor()
    result = extractor.extract(_openapi_data(), "openapi.json")
    accepts = [e for e in result.edges if e.relationship == "ACCEPTS"]
    assert len(accepts) == 1
    assert accepts[0].target_id == "schema::LoginRequest"


def test_endpoint_properties() -> None:
    extractor = APISpecExtractor()
    result = extractor.extract(_openapi_data(), "openapi.json")
    login = [n for n in result.nodes if "login" in n.label.lower()][0]
    assert login.properties["method"] == "POST"
    assert login.properties["route"] == "/api/auth/login"
    assert login.properties["operation_id"] == "login"
    assert "auth" in login.properties["tags"]


def test_schema_fields() -> None:
    extractor = APISpecExtractor()
    result = extractor.extract(_openapi_data(), "openapi.json")
    auth_schema = [n for n in result.nodes if n.label == "AuthResponse"][0]
    assert "token" in auth_schema.properties["fields"]
    assert "token" in auth_schema.properties["required_fields"]


def test_swagger_2_definitions() -> None:
    """Swagger 2.x uses 'definitions' instead of 'components/schemas'."""
    extractor = APISpecExtractor()
    data = {
        "swagger": "2.0",
        "info": {"title": "Legacy API", "version": "1.0"},
        "paths": {},
        "definitions": {
            "User": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            }
        },
    }
    result = extractor.extract(data, "swagger.json")
    schemas = [n for n in result.nodes if n.entity_type == "SCHEMA"]
    assert len(schemas) == 1
    assert schemas[0].label == "User"


def test_empty_paths() -> None:
    extractor = APISpecExtractor()
    data = {"openapi": "3.0.0", "info": {}, "paths": {}}
    result = extractor.extract(data, "api.json")
    assert len(result.nodes) == 0


def test_endpoint_with_no_schema_ref() -> None:
    extractor = APISpecExtractor()
    data = {
        "openapi": "3.0.0",
        "paths": {
            "/health": {"get": {"summary": "Health check", "responses": {"200": {}}}}
        },
    }
    result = extractor.extract(data, "api.json")
    endpoints = [n for n in result.nodes if n.entity_type == "ENDPOINT"]
    assert len(endpoints) == 1
    assert len(result.edges) == 0  # no schema ref → no returns edge
