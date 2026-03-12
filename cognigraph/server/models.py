"""Pydantic request/response models for the CogniGraph API server."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReasonRequest(BaseModel):
    """Request body for POST /reason."""

    query: str = Field(..., description="The reasoning query")
    max_rounds: int = Field(5, description="Max message-passing rounds")
    strategy: str | None = Field(None, description="Activation strategy (reads from config if not set)")
    stream: bool = Field(False, description="Enable streaming response")
    node_ids: list[str] | None = Field(None, description="Specific nodes to activate")


class ReasonResponse(BaseModel):
    """Response body for POST /reason."""

    answer: str
    confidence: float
    rounds_completed: int
    node_count: int
    cost_usd: float
    latency_ms: float
    metadata: dict = Field(default_factory=dict)


class StreamChunkResponse(BaseModel):
    """SSE chunk for streaming responses."""

    type: str  # "node_result", "round_complete", "final_answer"
    node_id: str | None = None
    round_num: int = 0
    content: str = ""
    confidence: float = 0.0


class BatchReasonRequest(BaseModel):
    """Request body for POST /reason/batch."""

    queries: list[str] = Field(..., description="List of queries")
    max_rounds: int = Field(5, description="Max rounds per query")
    strategy: str | None = Field(None, description="Activation strategy (reads from config if not set)")
    max_concurrent: int = Field(5, description="Max concurrent queries")


class GraphInfoResponse(BaseModel):
    """Response for GET /graph/stats."""

    total_nodes: int
    total_edges: int
    avg_degree: float
    density: float
    connected_components: int
    hub_nodes: list[str]


class HealthResponse(BaseModel):
    """Response for GET /health."""

    status: str = "ok"
    version: str = ""
    graph_loaded: bool = False
    node_count: int = 0
