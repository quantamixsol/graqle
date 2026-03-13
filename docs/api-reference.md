# Graqle API Reference

Graqle can be queried from **any tool, any language, any IDE** through 4 interfaces.
Pick whichever fits your workflow:

| Interface | Best For | Setup |
|-----------|----------|-------|
| **REST API** | Any HTTP client (Copilot, Postman, custom tools, CI/CD) | `graq serve` |
| **Python SDK** | Python scripts, notebooks, pipelines | `from graqle import Graqle` |
| **CLI** | Terminal, shell scripts, any IDE terminal | `graq run "query"` |
| **MCP Server** | Claude Code, Cursor, VS Code (MCP-compatible IDEs) | `graq init --ide <ide>` |

---

## 1. REST API (Universal — works with everything)

Start the server:
```bash
graq serve                          # localhost:8000
graq serve --port 9000              # custom port
graq serve --host 0.0.0.0 --port 8000 --workers 4  # production
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
graq serve
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
from graqle import Graqle
from graqle.backends.api import AnthropicBackend

# Load graph
graph = Graqle.from_json("graqle.json")
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
!pip install graqle[api]

from graqle import Graqle
graph = Graqle.from_json("graqle.json")
# ... query as above
```

### Use in CI/CD (GitHub Actions)
```yaml
- name: Check architecture
  run: |
    pip install graqle[api]
    graq run "Are there any circular dependencies?" --format json
```

---

## 3. CLI

```bash
# Reasoning query
graq run "What depends on the auth service?"

# Focused context (500 tokens)
graq context auth-service

# Graph statistics
graq inspect --stats

# Re-scan codebase
graq scan repo .

# Health check
graq doctor

# Backend setup help
graq setup-guide
```

Works in any terminal: VS Code, JetBrains, Replit, Codex, plain bash/zsh.

---

## 4. MCP Server (for AI-powered IDEs)

MCP (Model Context Protocol) is supported by Claude Code, Cursor, VS Code, and Windsurf.
Graqle auto-configures the right MCP file for your IDE:

```bash
graq init                    # Auto-detect IDE
graq init --ide cursor       # .cursor/mcp.json
graq init --ide vscode       # .vscode/mcp.json
graq init --ide claude       # .mcp.json + CLAUDE.md
graq init --ide windsurf     # .mcp.json + .windsurfrules
```

MCP tools available inside your IDE:
| Tool | What it does |
|------|-------------|
| `graq_context` | 500-token focused context for any entity |
| `graq_reason` | Multi-agent graph reasoning |
| `graq_inspect` | Graph structure inspection |
| `graq_preflight` | Pre-change safety check ("is this safe to change?") |
| `graq_impact` | Impact analysis ("what breaks if I change X?") |
| `graq_lessons` | Surface past mistakes before you repeat them |
| `graq_learn` | Teach the graph new knowledge |

---

## Integration Examples

### GitHub Copilot (via REST API)
1. Start `graq serve` in your project
2. Copilot Chat can reference the API via custom instructions
3. Or use the Copilot Extensions API to wrap Graqle

### JetBrains AI Assistant
1. `graq init --ide generic`
2. Use CLI in the built-in terminal: `graq run "query"`
3. Or start `graq serve` and query via HTTP

### Replit
1. `pip install graqle[api]`
2. `graq init --ide generic`
3. Use CLI or Python SDK in your Replit shell

### OpenAI Codex
1. `pip install graqle[api]`
2. Use the Python SDK in your Codex environment
3. Or `graq serve` + HTTP queries

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
