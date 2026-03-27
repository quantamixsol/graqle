"""GraQle API server — FastAPI application.

Exposes GraQle reasoning as a REST API with streaming support.
Start with: `graq serve` or `uvicorn graqle.server.app:create_app`

Production features:
- API key authentication (X-API-Key or Bearer token)
- Per-client rate limiting (token bucket)
- Request validation (query length, max_rounds, batch size)
- CORS middleware

NOTE: Do NOT use ``from __future__ import annotations`` in this module.
FastAPI/Pydantic needs real type objects at route-registration time;
PEP 563 deferred annotations break TypeAdapter resolution.
"""

# ── graqle:intelligence ──
# module: graqle.server.app
# risk: LOW (impact radius: 0 modules)
# dependencies: json, logging, os, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.server")


def _create_backend_from_config(cfg: Any) -> Any:
    """Create a real model backend from GraqleConfig.

    Mirrors the logic in cli/main.py._create_backend_from_config but
    without Rich console output (server mode).
    """
    from graqle.backends.mock import MockBackend

    backend_name = cfg.model.backend
    model_name = cfg.model.model
    api_key = cfg.model.api_key

    # Resolve env var references like ${ANTHROPIC_API_KEY}
    if api_key and api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        api_key = os.environ.get(env_var)

    try:
        if backend_name == "anthropic":
            from graqle.backends.api import AnthropicBackend
            if not api_key:
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                logger.warning("ANTHROPIC_API_KEY not set — using mock backend")
                return MockBackend(is_fallback=True, fallback_reason="ANTHROPIC_API_KEY not set")
            return AnthropicBackend(model=model_name, api_key=api_key)

        elif backend_name == "openai":
            from graqle.backends.api import OpenAIBackend
            if not api_key:
                api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set — using mock backend")
                return MockBackend(is_fallback=True, fallback_reason="OPENAI_API_KEY not set")
            return OpenAIBackend(model=model_name, api_key=api_key)

        elif backend_name == "bedrock":
            from graqle.backends.api import BedrockBackend
            region = getattr(cfg.model, "region", None) or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
            return BedrockBackend(model=model_name, region=region)

        elif backend_name == "ollama":
            from graqle.backends.api import OllamaBackend
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
    config_path: str = "graqle.yaml",
    graph_path: str | None = None,
    neptune_enabled: bool = False,
) -> Any:
    """Create the FastAPI application.

    Args:
        config_path: Path to graqle.yaml configuration
        graph_path: Path to graph JSON file (overrides config)
        neptune_enabled: If True, enable Neptune as graph backend

    Returns:
        FastAPI application instance
    """
    # When launched via uvicorn factory, pick up config path + CWD forwarded by CLI
    env_config = os.environ.get("GRAQLE_CONFIG_PATH")
    env_cwd = os.environ.get("GRAQLE_SERVE_CWD")
    if env_cwd:
        os.chdir(env_cwd)
    if env_config:
        config_path = env_config
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import StreamingResponse
    except ImportError as exc:
        raise ImportError(
            f"FastAPI import failed: {exc}. Install with: pip install graqle[server]"
        ) from exc

    from graqle.__version__ import __version__
    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle
    from graqle.server.middleware import (
        MAX_BATCH_SIZE,
        MAX_QUERY_LENGTH,
        MAX_ROUNDS,
        setup_auth_middleware,
        setup_rate_limit_middleware,
    )
    from graqle.server.models import (
        BatchReasonRequest,
        GraphInfoResponse,
        HealthResponse,
        ReasonRequest,
        ReasonResponse,
        StreamChunkResponse,
    )

    # Rebuild Pydantic models to resolve any forward references
    for model_cls in (ReasonRequest, ReasonResponse, BatchReasonRequest,
                      GraphInfoResponse, HealthResponse, StreamChunkResponse):
        model_cls.model_rebuild()

    app = FastAPI(
        title="GraQle API",
        description="Graph-of-Agents reasoning engine",
        version=__version__,
    )

    # GZip compression — critical for large graph responses (2.87MB → ~200KB)
    from starlette.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # CORS middleware — skip on Lambda where Function URL handles CORS (ADR-056)
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
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
        from graqle.server.stripe_webhook import router as stripe_router
        if stripe_router is not None:
            app.include_router(stripe_router, prefix="/webhooks")
    except Exception:
        pass  # Stripe integration is optional

    # State
    state: dict = {"graph": None, "config": None}

    def _load_graph_from_config(cfg: Any, fallback_path: str = "graqle.json") -> Any:
        """Load graph using config-aware backend selection (Neptune, Neo4j or JSON)."""
        connector = getattr(getattr(cfg, "graph", None), "connector", "networkx")

        # Neptune backend — load from Neptune cluster
        if neptune_enabled or connector == "neptune":
            try:
                from graqle.connectors.neptune import get_visualization, check_neptune_available
                if check_neptune_available():
                    # Determine project_id from env or config
                    project_id = os.environ.get("NEPTUNE_PROJECT_ID", "default")
                    viz = get_visualization(project_id)
                    if viz and viz.get("nodes"):
                        g = Graqle(config=cfg)
                        # Build graph from Neptune data
                        for node in viz["nodes"]:
                            g.add_node(
                                node_id=node.get("id", ""),
                                label=node.get("label", ""),
                                entity_type=node.get("type", "Thing"),
                                description=node.get("description", ""),
                            )
                        for edge in viz.get("links", []):
                            src = edge.get("source", "")
                            tgt = edge.get("target", "")
                            rel = edge.get("type", "RELATES_TO")
                            if src and tgt:
                                g.add_edge(src, tgt, rel)
                        logger.info("Loaded graph from Neptune: %d nodes, project=%s", len(g), project_id)
                        state["neptune_project_id"] = project_id
                        return g
                    else:
                        logger.info("Neptune has no data for project=%s, falling back", project_id)
                else:
                    logger.warning("Neptune dependencies not available, falling back to JSON")
            except Exception as exc:
                logger.warning("Neptune load failed (%s), falling back to JSON", exc)

        if connector == "neo4j":
            graph_cfg = cfg.graph
            try:
                g = Graqle.from_neo4j(
                    uri=getattr(graph_cfg, "uri", None) or "bolt://localhost:7687",
                    username=getattr(graph_cfg, "username", None) or "neo4j",
                    password=getattr(graph_cfg, "password", None) or "",
                    database=getattr(graph_cfg, "database", None) or "neo4j",
                    config=cfg,
                )
                logger.info("Loaded graph from Neo4j: %d nodes", len(g))
                return g
            except Exception as exc:
                logger.warning("Neo4j load failed (%s), falling back to JSON", exc)

        # Fallback: JSON/NetworkX
        # Prefer: explicit arg > config.graph.path > default fallback
        config_path_val = getattr(getattr(cfg, "graph", None), "path", None)
        gpath = graph_path or config_path_val or fallback_path
        if Path(gpath).exists():
            g = Graqle.from_json(gpath, config=cfg)
            logger.info("Loaded graph from %s: %d nodes", gpath, len(g))
            return g

        logger.warning("No graph found (connector=%s, path=%s)", connector, gpath)
        return None

    @app.on_event("startup")
    async def startup() -> None:
        # Load config
        if Path(config_path).exists():
            state["config"] = GraqleConfig.from_yaml(config_path)
        else:
            state["config"] = GraqleConfig.default()

        # Load graph (config-aware: Neptune, Neo4j or JSON)
        graph = _load_graph_from_config(state["config"])
        if graph is not None:
            state["graph"] = graph
            backend = _create_backend_from_config(state["config"])
            state["graph"].set_default_backend(backend)

            # Track Neptune availability for cross-project queries
            state["neptune_enabled"] = neptune_enabled or state.get("neptune_project_id") is not None

            # Initialize Neo4j traversal engine if Neo4j is configured
            connector = getattr(getattr(state["config"], "graph", None), "connector", "networkx")
            if connector == "neo4j":
                try:
                    from graqle.connectors.neo4j_traversal import Neo4jTraversal
                    graph_cfg = state["config"].graph
                    state["neo4j_traversal"] = Neo4jTraversal(
                        uri=getattr(graph_cfg, "uri", None) or "bolt://localhost:7687",
                        username=getattr(graph_cfg, "username", None) or "neo4j",
                        password=getattr(graph_cfg, "password", None) or "",
                        database=getattr(graph_cfg, "database", None) or "neo4j",
                    )
                    logger.info("Neo4j traversal engine initialized")
                except Exception as te:
                    logger.warning("Neo4j traversal engine not available: %s", te)
        else:
            logger.warning("No graph loaded")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        graph = state.get("graph")
        if graph is not None:
            ctx = graph.project_context()
            return HealthResponse(
                status="ok",
                version=__version__,
                graph_loaded=True,
                node_count=ctx["node_count"],
                edge_count=ctx["edge_count"],
                project_name=ctx["project_name"] or None,
                graph_path=ctx["graph_path"],
            )
        # No graph loaded — still return project name from CWD
        from pathlib import Path as _Path
        return HealthResponse(
            status="ok",
            version=__version__,
            graph_loaded=False,
            node_count=0,
            edge_count=0,
            project_name=_Path.cwd().name,
            graph_path=None,
        )

    @app.get("/project-context")
    async def project_context() -> Any:
        """Return full project identity for the Studio TopBar and Dashboard card."""
        from fastapi.responses import JSONResponse
        graph = state.get("graph")
        if graph is not None:
            ctx = graph.project_context()
        else:
            from pathlib import Path as _Path
            ctx = {
                "project_name": _Path.cwd().name,
                "source_mode": "local",
                "graph_path": None,
                "node_count": 0,
                "edge_count": 0,
            }
        ctx["graph_loaded"] = graph is not None
        return JSONResponse(content=ctx)

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

    # Read-only mode: check env var set by CLI
    _read_only = os.environ.get("GRAQLE_READ_ONLY", "").strip() in ("1", "true", "yes")

    @app.post("/reload")
    async def reload_graph() -> dict:
        """Hot-reload the knowledge graph from disk without restarting the server.

        FEEDBACK: MCP server doesn't hot-reload KG — after swapping graqle.json,
        must restart. This endpoint fixes that.
        """
        if _read_only:
            raise HTTPException(status_code=403, detail="Server is in read-only mode. /reload is disabled.")

        old_count = len(state["graph"]) if state.get("graph") else 0
        graph = _load_graph_from_config(state["config"])
        if graph is None:
            raise HTTPException(status_code=404, detail="No graph source available (check config)")
        state["graph"] = graph
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
        - GraQle activates relevant skills autonomously
        - The graph discovers new areas users can't think of

        Body:
          nodes: [{id, label, type, description, properties}]
          edges: [{source, target, relation}]
          auto_connect: bool (default true) — auto-discover edges to existing nodes
        """
        if _read_only:
            raise HTTPException(status_code=403, detail="Server is in read-only mode. /learn is disabled.")
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
        gpath = graph_path or "graqle.json"
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
            from graqle.server.stripe_webhook import _store_lead
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

    async def _stream_reason(graph: Graqle, request: ReasonRequest):
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
        from graqle.studio.app import mount_studio

        # Load metrics engine
        metrics = None
        try:
            from graqle.metrics.engine import MetricsEngine
            metrics = MetricsEngine()
        except Exception:
            pass

        state["metrics"] = metrics
        mount_studio(app, state)
    except ImportError:
        logger.debug("Studio not available (install graqle[studio] for dashboard)")

    return app
