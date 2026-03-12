# CogniGraph API Reference

CogniGraph can be queried from **any tool, any language, any IDE** through 4 interfaces.
Pick whichever fits your workflow:

| Interface | Best For | Setup |
|-----------|----------|-------|
| **REST API** | Any HTTP client (Copilot, Postman, custom tools, CI/CD) | `kogni serve` |
| **Python SDK** | Python scripts, notebooks, pipelines | `from cognigraph import CogniGraph` |
| **CLI** | Terminal, shell scripts, any IDE terminal | `kogni run "query"` |
| **MCP Server** | Claude Code, Cursor, VS Code (MCP-compatible IDEs) | `kogni init --ide <ide>` |

---

## 1. REST API (Universal — works with everything)

Start the server:
```bash
kogni serve                          # localhost:8000
kogni serve --port 9000              # custom port
kogni serve --host 0.0.0.0 --port 8000 --workers 4  # production
```

Interactive docs available at: `http://localhost:8000/docs` (Swagger UI)

### Endpoints

#### `GET /health` — Health check
```bash
curl http://localhost:8000/health
```
```json
{
  "status": "ok",
  "version": "0.7.5",
  "graph_loaded": true,
  "node_count": 314
}
```

#### `POST /reason` — Query the knowledge graph
```bash
curl -X POST http://localhost:8000/reason \
  -H "Content-Type: application/json" \
  -d '{"query": "What depends on the auth service?"}'
```
```json
{
  "answer": "The auth service is depended on by...",
  "confidence": 0.87,
  "rounds_completed": 3,
  "node_count": 12,
  "cost_usd": 0.0023,
  "latency_ms": 1250.5,
  "metadata": {}
}
```

**Parameters:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | required | Your question |
| `max_rounds` | int | 5 | Max message-passing rounds (1-20) |
| `strategy` | string | "pcst" | Activation strategy: "pcst", "top_k", "full" |
| `stream` | bool | false | Enable SSE streaming |
| `node_ids` | list[str] | null | Specific nodes to activate |

#### `POST /reason/batch` — Batch queries
```bash
curl -X POST http://localhost:8000/reason/batch \
  -H "Content-Type: application/json" \
  -d '{
    "queries": [
      "What depends on auth?",
      "What calls the payment API?",
      "Which services use DynamoDB?"
    ],
    "max_concurrent": 5
  }'
```

#### `GET /graph/stats` — Graph statistics
```bash
curl http://localhost:8000/graph/stats
```
```json
{
  "total_nodes": 314,
  "total_edges": 178,
  "avg_degree": 1.13,
  "density": 0.0036,
  "connected_components": 45,
  "hub_nodes": ["auth-service", "api-gateway", "user-store"]
}
```

#### `GET /nodes/{node_id}` — Node details
```bash
curl http://localhost:8000/nodes/auth-service
```
```json
{
  "id": "auth-service",
  "label": "Auth Service",
  "type": "SERVICE",
  "description": "Handles JWT verification and session management",
  "degree": 12,
  "properties": {},
  "neighbors": ["user-store", "api-gateway", "cognito-pool"]
}
```

### Authentication

Set an API key to protect your server:
```bash
export COGNIGRAPH_API_KEY=your-secret-key
kogni serve
```

Then include it in requests:
```bash
curl -H "X-API-Key: your-secret-key" http://localhost:8000/reason \
  -X POST -H "Content-Type: application/json" \
  -d '{"query": "your question"}'
```

Or use Bearer token:
```bash
curl -H "Authorization: Bearer your-secret-key" ...
```

### Rate Limiting

Default: 10 requests/second, 20 burst. Configure via:
```bash
export COGNIGRAPH_RATE_LIMIT=20    # requests per second
export COGNIGRAPH_RATE_BURST=50    # burst capacity
```

### Streaming (SSE)

For long-running queries, use streaming to get partial results:
```bash
curl -N -X POST http://localhost:8000/reason \
  -H "Content-Type: application/json" \
  -d '{"query": "Analyze all service dependencies", "stream": true}'
```

Returns Server-Sent Events:
```
data: {"type": "node_result", "node_id": "auth-service", "content": "...", "confidence": 0.85}
data: {"type": "round_complete", "round_num": 1}
data: {"type": "final_answer", "content": "...", "confidence": 0.87}
data: [DONE]
```

---

## 2. Python SDK

```python
from cognigraph import CogniGraph
from cognigraph.backends.api import AnthropicBackend

# Load graph
graph = CogniGraph.from_json("cognigraph.json")
graph.set_default_backend(AnthropicBackend(model="claude-haiku-4-5-20251001"))

# Single query
result = graph.reason("What depends on the auth service?")
print(result.answer)
print(f"Confidence: {result.confidence:.2f}")
print(f"Cost: ${result.cost_usd:.4f}")

# Async
result = await graph.areason("query")

# Batch
results = await graph.areason_batch(
    ["query1", "query2", "query3"],
    max_concurrent=5,
)

# Get focused context (500 tokens instead of 20-60K)
context = graph.get_context("auth-service")
print(context)

# Graph stats
stats = graph.stats
print(f"Nodes: {stats.total_nodes}, Edges: {stats.total_edges}")
```

### Use in Jupyter Notebooks
```python
# In a cell:
!pip install cognigraph[api]

from cognigraph import CogniGraph
graph = CogniGraph.from_json("cognigraph.json")
# ... query as above
```

### Use in CI/CD (GitHub Actions)
```yaml
- name: Check architecture
  run: |
    pip install cognigraph[api]
    kogni run "Are there any circular dependencies?" --format json
```

---

## 3. CLI

```bash
# Reasoning query
kogni run "What depends on the auth service?"

# Focused context (500 tokens)
kogni context auth-service

# Graph statistics
kogni inspect --stats

# Re-scan codebase
kogni scan repo .

# Health check
kogni doctor

# Backend setup help
kogni setup-guide
```

Works in any terminal: VS Code, JetBrains, Replit, Codex, plain bash/zsh.

---

## 4. MCP Server (for AI-powered IDEs)

MCP (Model Context Protocol) is supported by Claude Code, Cursor, VS Code, and Windsurf.
CogniGraph auto-configures the right MCP file for your IDE:

```bash
kogni init                    # Auto-detect IDE
kogni init --ide cursor       # .cursor/mcp.json
kogni init --ide vscode       # .vscode/mcp.json
kogni init --ide claude       # .mcp.json + CLAUDE.md
kogni init --ide windsurf     # .mcp.json + .windsurfrules
```

MCP tools available inside your IDE:
| Tool | What it does |
|------|-------------|
| `kogni_context` | 500-token focused context for any entity |
| `kogni_reason` | Multi-agent graph reasoning |
| `kogni_inspect` | Graph structure inspection |
| `kogni_preflight` | Pre-change safety check ("is this safe to change?") |
| `kogni_impact` | Impact analysis ("what breaks if I change X?") |
| `kogni_lessons` | Surface past mistakes before you repeat them |
| `kogni_learn` | Teach the graph new knowledge |

---

## Integration Examples

### GitHub Copilot (via REST API)
1. Start `kogni serve` in your project
2. Copilot Chat can reference the API via custom instructions
3. Or use the Copilot Extensions API to wrap CogniGraph

### JetBrains AI Assistant
1. `kogni init --ide generic`
2. Use CLI in the built-in terminal: `kogni run "query"`
3. Or start `kogni serve` and query via HTTP

### Replit
1. `pip install cognigraph[api]`
2. `kogni init --ide generic`
3. Use CLI or Python SDK in your Replit shell

### OpenAI Codex
1. `pip install cognigraph[api]`
2. Use the Python SDK in your Codex environment
3. Or `kogni serve` + HTTP queries

### Custom Tools / Bots / Slack
```python
import httpx

response = httpx.post("http://localhost:8000/reason", json={
    "query": "What's the deployment architecture?"
})
print(response.json()["answer"])
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COGNIGRAPH_API_KEY` | none | API key for REST server auth |
| `COGNIGRAPH_RATE_LIMIT` | 10 | Requests per second per client |
| `COGNIGRAPH_RATE_BURST` | 20 | Burst capacity |
| `ANTHROPIC_API_KEY` | none | Anthropic Claude API key |
| `OPENAI_API_KEY` | none | OpenAI API key |
| `AWS_ACCESS_KEY_ID` | none | AWS Bedrock credentials |
| `COGNIGRAPH_LICENSE_KEY` | none | Team/Enterprise license (solo devs don't need this) |
