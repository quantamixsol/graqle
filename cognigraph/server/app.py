"""CogniGraph API server — FastAPI application.

Exposes CogniGraph reasoning as a REST API with streaming support.
Start with: `kogni serve` or `uvicorn cognigraph.server.app:create_app`

Production features:
- API key authentication (X-API-Key or Bearer token)
- Per-client rate limiting (token bucket)
- Request validation (query length, max_rounds, batch size)
- CORS middleware

NOTE: Do NOT use ``from __future__ import annotations`` in this module.
FastAPI/Pydantic needs real type objects at route-registration time;
PEP 563 deferred annotations break TypeAdapter resolution.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger("cognigraph.server")


def _create_backend_from_config(cfg: Any) -> Any:
    """Create a real model backend from CogniGraphConfig.

    Mirrors the logic in cli/main.py._create_backend_from_config but
    without Rich console output (server mode).
    """
    from cognigraph.backends.mock import MockBackend

    backend_name = cfg.model.backend
    model_name = cfg.model.model
    api_key = cfg.model.api_key

    # Resolve env var references like ${ANTHROPIC_API_KEY}
    if api_key and api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        api_key = os.environ.get(env_var)

    try:
        if backend_name == "anthropic":
            from cognigraph.backends.api import AnthropicBackend
            if not api_key:
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                logger.warning("ANTHROPIC_API_KEY not set — using mock backend")
                return MockBackend(is_fallback=True, fallback_reason="ANTHROPIC_API_KEY not set")
            return AnthropicBackend(model=model_name, api_key=api_key)

        elif backend_name == "openai":
            from cognigraph.backends.api import OpenAIBackend
            if not api_key:
                api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set — using mock backend")
                return MockBackend(is_fallback=True, fallback_reason="OPENAI_API_KEY not set")
            return OpenAIBackend(model=model_name, api_key=api_key)

        elif backend_name == "bedrock":
            from cognigraph.backends.api import BedrockBackend
            region = getattr(cfg.model, "region", None) or os.environ.get(
                "AWS_DEFAULT_REGION", "eu-central-1"
            )
            return BedrockBackend(model=model_name, region=region)

        elif backend_name == "ollama":
            from cognigraph.backends.api import OllamaBackend
            host = getattr(cfg.model, "host", None) or "http://localhost:11434"
            return OllamaBackend(model=model_name, host=host)

        else:
            logger.warning("Unknown backend '%s' — using mock", backend_name)
            return MockBackend(is_fallback=True, fallback_reason=f"Unknown backend: {backend_name}")

    except ImportError as e:
        logger.warning("Missing package for backend: %s", e)
        return MockBackend(is_fallback=True, fallback_reason=str(e))
    except Exception as e:
        logger.warning("Backend init failed: %s", e)
        return MockBackend(is_fallback=True, fallback_reason=str(e))


def create_app(
    config_path: str = "cognigraph.yaml",
    graph_path: Optional[str] = None,
) -> Any:
    """Create the FastAPI application.

    Args:
        config_path: Path to cognigraph.yaml configuration
        graph_path: Path to graph JSON file (overrides config)

    Returns:
        FastAPI application instance
    """
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import StreamingResponse
    except ImportError:
        raise ImportError(
            "FastAPI not installed. Install with: pip install cognigraph[server]"
        )

    from cognigraph.__version__ import __version__
    from cognigraph.config.settings import CogniGraphConfig
    from cognigraph.core.graph import CogniGraph
    from cognigraph.server.middleware import (
        setup_auth_middleware,
        setup_rate_limit_middleware,
        MAX_QUERY_LENGTH,
        MAX_ROUNDS,
        MAX_BATCH_SIZE,
    )
    from cognigraph.server.models import (
        ReasonRequest,
        ReasonResponse,
        BatchReasonRequest,
        GraphInfoResponse,
        HealthResponse,
        StreamChunkResponse,
    )

    # Rebuild Pydantic models to resolve any forward references
    for model_cls in (ReasonRequest, ReasonResponse, BatchReasonRequest,
                      GraphInfoResponse, HealthResponse, StreamChunkResponse):
        model_cls.model_rebuild()

    app = FastAPI(
        title="CogniGraph API",
        description="Graph-of-Agents reasoning engine",
        version=__version__,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth + rate limiting middleware
    setup_auth_middleware(app)
    setup_rate_limit_middleware(app)

    # Stripe webhook router (if STRIPE_WEBHOOK_SECRET is set)
    try:
        from cognigraph.server.stripe_webhook import router as stripe_router
        if stripe_router is not None:
            app.include_router(stripe_router, prefix="/webhooks")
    except Exception:
        pass  # Stripe integration is optional

    # State
    state: dict = {"graph": None, "config": None}

    @app.on_event("startup")
    async def startup() -> None:
        # Load config
        if Path(config_path).exists():
            state["config"] = CogniGraphConfig.from_yaml(config_path)
        else:
            state["config"] = CogniGraphConfig.default()

        # Load graph
        gpath = graph_path or "cognigraph.json"
        if Path(gpath).exists():
            state["graph"] = CogniGraph.from_json(gpath, config=state["config"])
            # Bug 3 fix: Create real backend from config instead of MockBackend
            backend = _create_backend_from_config(state["config"])
            state["graph"].set_default_backend(backend)
            logger.info("Loaded graph from %s: %d nodes", gpath, len(state["graph"]))
        else:
            logger.warning("No graph file found at %s", gpath)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        graph = state.get("graph")
        return HealthResponse(
            status="ok",
            version=__version__,
            graph_loaded=graph is not None,
            node_count=len(graph) if graph else 0,
        )

    @app.post("/reason", response_model=ReasonResponse)
    async def reason(request: ReasonRequest) -> Any:
        graph = state.get("graph")
        if graph is None:
            raise HTTPException(status_code=503, detail="No graph loaded")

        # T63: Request validation
        if len(request.query) > MAX_QUERY_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Query too long ({len(request.query)} chars). Max: {MAX_QUERY_LENGTH}",
            )
        if request.max_rounds > MAX_ROUNDS:
            raise HTTPException(
                status_code=422,
                detail=f"max_rounds={request.max_rounds} exceeds limit of {MAX_ROUNDS}",
            )
        if request.node_ids:
            missing = [nid for nid in request.node_ids if nid not in graph.nodes]
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown node IDs: {missing[:5]}",
                )

        if request.stream:
            return StreamingResponse(
                _stream_reason(graph, request),
                media_type="text/event-stream",
            )

        result = await graph.areason(
            request.query,
            max_rounds=request.max_rounds,
            strategy=request.strategy,
            node_ids=request.node_ids,
        )

        return ReasonResponse(
            answer=result.answer,
            confidence=result.confidence,
            rounds_completed=result.rounds_completed,
            node_count=result.node_count,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            metadata=result.metadata,
        )

    @app.post("/reason/batch")
    async def reason_batch(request: BatchReasonRequest) -> list:
        graph = state.get("graph")
        if graph is None:
            raise HTTPException(status_code=503, detail="No graph loaded")

        # T63: Batch validation
        if len(request.queries) > MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"Batch too large ({len(request.queries)}). Max: {MAX_BATCH_SIZE}",
            )
        for i, q in enumerate(request.queries):
            if len(q) > MAX_QUERY_LENGTH:
                raise HTTPException(
                    status_code=422,
                    detail=f"Query [{i}] too long ({len(q)} chars). Max: {MAX_QUERY_LENGTH}",
                )
        if request.max_rounds > MAX_ROUNDS:
            raise HTTPException(
                status_code=422,
                detail=f"max_rounds={request.max_rounds} exceeds limit of {MAX_ROUNDS}",
            )

        results = await graph.areason_batch(
            request.queries,
            max_rounds=request.max_rounds,
            strategy=request.strategy,
            max_concurrent=request.max_concurrent,
        )

        return [
            ReasonResponse(
                answer=r.answer,
                confidence=r.confidence,
                rounds_completed=r.rounds_completed,
                node_count=r.node_count,
                cost_usd=r.cost_usd,
                latency_ms=r.latency_ms,
                metadata=r.metadata,
            )
            for r in results
        ]

    @app.get("/graph/stats", response_model=GraphInfoResponse)
    async def graph_stats() -> GraphInfoResponse:
        graph = state.get("graph")
        if graph is None:
            raise HTTPException(status_code=503, detail="No graph loaded")

        s = graph.stats
        return GraphInfoResponse(
            total_nodes=s.total_nodes,
            total_edges=s.total_edges,
            avg_degree=s.avg_degree,
            density=s.density,
            connected_components=s.connected_components,
            hub_nodes=s.hub_nodes,
        )

    @app.get("/nodes/{node_id:path}")
    async def get_node(node_id: str) -> dict:
        graph = state.get("graph")
        if graph is None:
            raise HTTPException(status_code=503, detail="No graph loaded")

        node = graph.nodes.get(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

        return {
            "id": node.id,
            "label": node.label,
            "type": node.entity_type,
            "description": node.description,
            "degree": node.degree,
            "properties": node.properties,
            "neighbors": graph.get_neighbors(node_id),
        }

    @app.post("/reload")
    async def reload_graph() -> dict:
        """Hot-reload the knowledge graph from disk without restarting the server.

        FEEDBACK: MCP server doesn't hot-reload KG — after swapping cognigraph.json,
        must restart. This endpoint fixes that.
        """
        gpath = graph_path or "cognigraph.json"
        if not Path(gpath).exists():
            raise HTTPException(status_code=404, detail=f"Graph file not found: {gpath}")

        old_count = len(state["graph"]) if state.get("graph") else 0
        state["graph"] = CogniGraph.from_json(gpath, config=state["config"])
        backend = _create_backend_from_config(state["config"])
        state["graph"].set_default_backend(backend)
        new_count = len(state["graph"])
        logger.info("Reloaded graph: %d → %d nodes", old_count, new_count)
        return {
            "status": "reloaded",
            "previous_nodes": old_count,
            "current_nodes": new_count,
        }

    @app.post("/learn")
    async def learn(request_data: dict) -> dict:
        """Add new knowledge to the graph — nodes, edges, or business concepts.

        FEEDBACK: Code-heavy KGs lack business concepts. This lets users add
        PRODUCT, BUSINESS_OUTCOME, CLIENT, and other high-level nodes manually.

        The graph becomes self-discovering and self-evolving:
        - Users add business-level nodes
        - CogniGraph activates relevant skills autonomously
        - The graph discovers new areas users can't think of

        Body:
          nodes: [{id, label, type, description, properties}]
          edges: [{source, target, relation}]
          auto_connect: bool (default true) — auto-discover edges to existing nodes
        """
        graph = state.get("graph")
        if graph is None:
            raise HTTPException(status_code=503, detail="No graph loaded")

        nodes_added = 0
        edges_added = 0

        # Add nodes
        for node_data in request_data.get("nodes", []):
            node_id = node_data.get("id")
            if not node_id:
                continue
            graph.add_node_simple(
                node_id,
                label=node_data.get("label", node_id),
                entity_type=node_data.get("type", "CONCEPT"),
                description=node_data.get("description", ""),
                properties=node_data.get("properties", {}),
            )
            nodes_added += 1

        # Add edges
        for edge_data in request_data.get("edges", []):
            src = edge_data.get("source")
            tgt = edge_data.get("target")
            rel = edge_data.get("relation", "RELATES_TO")
            if src and tgt and src in graph.nodes and tgt in graph.nodes:
                graph.add_edge_simple(src, tgt, relation=rel)
                edges_added += 1

        # Auto-connect: find related nodes by description similarity
        if request_data.get("auto_connect", True) and nodes_added > 0:
            new_ids = [n["id"] for n in request_data.get("nodes", []) if n.get("id")]
            auto_edges = graph.auto_connect(new_ids) if hasattr(graph, "auto_connect") else 0
            edges_added += auto_edges

        # Persist to disk
        gpath = graph_path or "cognigraph.json"
        graph.to_json(gpath)

        return {
            "status": "learned",
            "nodes_added": nodes_added,
            "edges_added": edges_added,
            "total_nodes": len(graph),
        }

    @app.post("/leads")
    async def capture_lead(request_data: dict) -> dict:
        """Receive anonymous telemetry and lead registrations from SDK installs."""
        try:
            from cognigraph.server.stripe_webhook import _store_lead
            _store_lead({
                "email": request_data.get("email", ""),
                "tier": "free",
                "holder": request_data.get("name", ""),
                "stripe_session_id": "",
                "stripe_customer_id": "",
            })
        except Exception:
            pass
        return {"status": "ok"}

    async def _stream_reason(graph: CogniGraph, request: ReasonRequest):
        """SSE generator for streaming reasoning."""
        async for chunk in graph.areason_stream(
            request.query,
            max_rounds=request.max_rounds,
            strategy=request.strategy,
            node_ids=request.node_ids,
        ):
            data = json.dumps(chunk.to_dict())
            yield f"data: {data}\n\n"
        yield "data: [DONE]\n\n"

    # Mount Studio dashboard (optional — only if studio package is available)
    try:
        from cognigraph.studio.app import mount_studio

        # Load metrics engine
        metrics = None
        try:
            from cognigraph.metrics.engine import MetricsEngine
            metrics = MetricsEngine()
        except Exception:
            pass

        state["metrics"] = metrics
        mount_studio(app, state)
    except ImportError:
        logger.debug("Studio not available (install cognigraph[studio] for dashboard)")

    return app
