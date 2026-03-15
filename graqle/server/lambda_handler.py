"""AWS Lambda handler for Graqle API.

Wraps the existing FastAPI application with Mangum for API Gateway / Function URL.
Graph is loaded once per warm Lambda container and reused across invocations.

Deploy with:
  - Lambda Function URL (recommended for SSE streaming)
  - API Gateway v2 (HTTP API) for custom domain

Environment variables:
  COGNIGRAPH_GRAPH_PATH   — S3 URI or local path to graqle.json
  COGNIGRAPH_CONFIG_PATH  — S3 URI or local path to graqle.yaml
  ANTHROPIC_API_KEY       — For Claude-based reasoning
  AWS_BEDROCK_MODEL       — Alternative: use Bedrock instead
  COGNIGRAPH_API_KEY      — Optional: API key auth
  COGNIGRAPH_S3_BUCKET    — S3 bucket for graph/config storage
"""

# ── graqle:intelligence ──
# module: graqle.server.lambda_handler
# risk: LOW (impact radius: 0 modules)
# dependencies: json, logging, os, tempfile, pathlib
# constraints: none
# ── /graqle:intelligence ──

import logging
import os
import tempfile

logger = logging.getLogger("graqle.lambda")
logger.setLevel(logging.INFO)

# Cached app instance (warm Lambda reuse)
_app = None
_handler = None


def _download_from_s3(s3_uri: str, local_path: str) -> str:
    """Download s3://bucket/key to local_path. Returns local path."""
    import boto3

    if not s3_uri.startswith("s3://"):
        return s3_uri  # Already a local path

    parts = s3_uri[5:].split("/", 1)
    bucket, key = parts[0], parts[1]

    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")
    s3.download_file(bucket, key, local_path)
    logger.info("Downloaded %s → %s", s3_uri, local_path)
    return local_path


def _ensure_graph_local() -> tuple[str, str]:
    """Ensure graph and config files are available locally.

    Downloads from S3 if paths are s3:// URIs.
    Returns (graph_path, config_path).
    """
    tmp = tempfile.gettempdir()

    graph_path = os.environ.get("COGNIGRAPH_GRAPH_PATH", "graqle.json")
    config_path = os.environ.get("COGNIGRAPH_CONFIG_PATH", "graqle.yaml")

    if graph_path.startswith("s3://"):
        local_graph = os.path.join(tmp, "graqle.json")
        if not os.path.exists(local_graph):  # Cache across warm invocations
            _download_from_s3(graph_path, local_graph)
        graph_path = local_graph

    if config_path.startswith("s3://"):
        local_config = os.path.join(tmp, "graqle.yaml")
        if not os.path.exists(local_config):
            _download_from_s3(config_path, local_config)
        config_path = local_config

    return graph_path, config_path


def _get_app():
    """Create or return cached FastAPI app."""
    global _app
    if _app is not None:
        return _app

    graph_path, config_path = _ensure_graph_local()

    from graqle.server.app import create_app

    _app = create_app(
        graph_path=graph_path,
        config_path=config_path,
    )
    return _app


def _get_handler():
    """Create or return cached Mangum handler."""
    global _handler
    if _handler is not None:
        return _handler

    try:
        from mangum import Mangum
    except ImportError:
        raise ImportError(
            "mangum is required for Lambda deployment. "
            "Install with: pip install mangum"
        )

    app = _get_app()
    _handler = Mangum(app, lifespan="auto")
    return _handler


def handler(event, context):
    """AWS Lambda entry point.

    Works with:
    - Lambda Function URL (direct HTTP)
    - API Gateway v2 (HTTP API)
    - API Gateway v1 (REST API)
    """
    mangum_handler = _get_handler()
    return mangum_handler(event, context)


# Alias for SAM/CDK templates
lambda_handler = handler
