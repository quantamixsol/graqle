# Changelog

All notable changes to Graqle are documented in this file.

---

## v0.29.0 — Cloud Sync + Multi-Project Dashboard (2026-03-17)

**Push your knowledge graph to Graqle Cloud. View it anywhere. Share with your team.**

The cloud release: `graq cloud push` sends your knowledge graph to [graqle.com/dashboard](https://graqle.com/dashboard). Pull it on any machine. See all your projects in one control plane.

### Cloud CLI (`graq cloud`)

New command group for managing your knowledge graph in the cloud:

```bash
graq login --api-key grq_your_key    # Connect (get key at graqle.com/account)
graq cloud push                       # Upload graph + scorecard + intelligence
graq cloud pull                       # Download graph to any machine
graq cloud status                     # List cloud projects + connection info
```

- **Auto-detects project name** from `graqle.yaml`, `package.json`, `pyproject.toml`, or directory name
- **Uploads to S3** at `graphs/{email_hash}/{project}/` — graqle.json, scorecard, insights, metadata
- **Neptune sync** for Team tier — graphs synced to production Neptune for cross-project queries
- **Pull** downloads the latest graph from cloud to your local project

### Enhanced Login

`graq login --api-key grq_xxx` now validates the key against the Graqle Cloud API:
- Returns email, plan tier, and validation status
- Falls back gracefully when offline — key saved locally
- Key format validation (`grq_` prefix required)

### API Key Management (Studio)

New Account page at [graqle.com/dashboard/account](https://graqle.com/dashboard/account):
- **Generate API keys** (up to 5 per user) — `grq_` + 64-char hex
- **Key shown once** — copy button, then masked forever
- **Revoke keys** (soft-delete) — immediate invalidation
- **Connected Projects** — see all pushed projects with node count, health, last push time
- **Validation endpoint** — `POST /api/keys/validate` (used by `graq login`)

### Project Selector (Studio)

TopBar project dropdown — switch between projects pushed to cloud:
- Auto-fetches from S3 on auth
- Loads project-specific graph in explorer
- Per-user, per-project graph loading with fallback

### Control Plane — Cloud Integration

`/dashboard/control` now merges local backend instances with cloud projects:
- Local instances from `graq serve` + cloud instances from S3
- Deduplicated by project name
- Health status, node/edge counts, last scan time

### Lambda — Neptune-Aware Loading

Lambda handler (`cognigraph-api`) now checks `NEPTUNE_ENDPOINT`:
- If set: passes `neptune_enabled=True` to create_app — serves from Neptune
- If not: falls back to S3 JSON (existing behavior)
- Warm container caching preserved

### Cloud Gateway

`CloudGateway.upload_graph()` upgraded from stub to real S3 upload:
- Uploads `graqle.json` and optional `scorecard.json`
- Returns S3 prefix for verification
- Error handling with logging

### Tests

**2,009 tests passing.** No regressions from v0.28.0.

### Files Changed

| File | Change |
|------|--------|
| `graqle/cli/commands/cloud.py` | NEW — `graq cloud push/pull/status` |
| `graqle/cli/commands/login.py` | Enhanced — API key validation against cloud |
| `graqle/cli/main.py` | Added — `cloud` command group registration |
| `graqle/cloud/gateway.py` | Upgraded — real `upload_graph()` method |
| `graqle/server/lambda_handler.py` | Enhanced — Neptune-aware graph loading |

### Breaking Changes

None. All new features are additive. Existing configs work unchanged.

---

## v0.22.0 — Multi-Provider LLM + Task-Based Routing (2026-03-14)

**Use any LLM provider. Route tasks to the right model.** The biggest backend expansion since launch — 10+ providers, task-based routing, and Google Gemini native support.

### Multi-Provider LLM Support

7 new OpenAI-compatible providers added via **provider presets** — named configurations that auto-resolve to `CustomBackend` with the correct endpoint, env var, and per-model pricing. No new dependencies required (all use `httpx`).

| Provider | Env Var | Default Model | Cost/1K tokens |
|----------|---------|---------------|----------------|
| **Groq** | `GROQ_API_KEY` | llama-3.3-70b-versatile | $0.00059 |
| **DeepSeek** | `DEEPSEEK_API_KEY` | deepseek-chat | $0.00014 |
| **Together** | `TOGETHER_API_KEY` | Llama-3.3-70B-Instruct-Turbo | $0.00088 |
| **Mistral** | `MISTRAL_API_KEY` | mistral-small-latest | $0.00020 |
| **OpenRouter** | `OPENROUTER_API_KEY` | llama-3.3-70b-instruct | $0.00050 |
| **Fireworks** | `FIREWORKS_API_KEY` | llama-v3p3-70b-instruct | $0.00090 |
| **Cohere** | `COHERE_API_KEY` | command-r-plus | $0.00300 |

**Usage — one line in `graqle.yaml`:**
```yaml
model:
  backend: groq
  model: llama-3.3-70b-versatile
```

**Or via SDK:**
```python
from graqle.backends.providers import create_provider_backend
backend = create_provider_backend("groq", model="llama-3.3-70b-versatile")
graph.set_default_backend(backend)
```

**Files:**
- `graqle/backends/providers.py` — Provider preset registry with `PROVIDER_PRESETS`, `create_provider_backend()`, `get_provider_names()`, `get_provider_env_var()`
- `graqle/backends/registry.py` — 15 new entries in `BUILTIN_BACKENDS`
- `graqle/backends/__init__.py` — Lazy imports for new exports
- `graqle/core/graph.py` — `_auto_create_backend()` handles provider presets
- `graqle/cli/commands/doctor.py` — Detects all provider API keys

### Google Gemini Backend

Gemini uses Google's own `generateContent` API format (not OpenAI-compatible), so it gets its own backend class with proper request/response translation.

- Supports `GEMINI_API_KEY` and `GOOGLE_API_KEY` env vars
- Per-model pricing: Gemini 2.5 Pro, 2.5 Flash, 2.0 Flash, 2.0 Flash-Lite, 1.5 Pro, 1.5 Flash
- Retry with backoff (shared with other API backends)

**Files:**
- `graqle/backends/gemini.py` — `GeminiBackend` class with `GEMINI_PRICING`

### Task-Based Model Routing

Users define rules that map task types to providers — never auto-assigned, always explicit opt-in.

**8 task types:** `context`, `reason`, `preflight`, `impact`, `lessons`, `learn`, `code`, `docs`

**Built-in recommendations** suggest which providers suit which tasks, with reasoning:
- Context lookups → fast/cheap (Groq, Gemini, DeepSeek)
- Reasoning → smart/thorough (Anthropic, OpenAI, DeepSeek)
- Preflight checks → reliable (Anthropic, Mistral)
- Impact analysis → fast/structured (Groq, Together, Fireworks)
- Document tasks → long-context (Gemini, Anthropic, Together)

**Configuration:**
```yaml
routing:
  default_provider: groq
  rules:
    - task: reason
      provider: anthropic
      model: claude-sonnet-4-6
      reason: "Reasoning needs strong multi-step logic"
    - task: context
      provider: groq
      model: llama-3.1-8b-instant
      reason: "Context lookups are simple — use fast model"
```

**Files:**
- `graqle/routing.py` — `TaskRouter`, `RoutingRule`, `TASK_RECOMMENDATIONS`, `MCP_TOOL_TO_TASK`
- `graqle/config/settings.py` — `RoutingConfig`, `RoutingRuleConfig` added to `GraqleConfig`
- `graqle/core/graph.py` — `areason()` and `reason()` accept `task_type` parameter
- `graqle/plugins/mcp_dev_server.py` — `_handle_reason()` passes `task_type="reason"`
- `graqle/plugins/mcp_server.py` — Same

### Config Changes

New `routing` section in `graqle.yaml`:
```yaml
routing:
  default_provider: null         # fallback provider if no task rule matches
  default_model: null             # fallback model
  rules: []                       # list of {task, provider, model, reason}
```

New `endpoint` field on `ModelConfig`:
```yaml
model:
  endpoint: https://my-proxy.example.com/v1/chat/completions  # for custom/self-hosted
```

### Tests

**1,655 tests passing.** Up from 1,627 in v0.21.2.

| Area | New Tests | What |
|------|-----------|------|
| Routing | 27 | TaskRouter, RoutingRule, recommendations, RoutingConfig, YAML validation |
| Providers | 19 | Preset structure, endpoint validation, create_provider_backend |
| Gemini | 11 | Init, pricing, API key resolution, request body, response parsing |

### Breaking Changes

None. All new features are additive. Existing configs work unchanged.

---

## v0.21.2 — Bugfix Release (2026-03-14)

- DF-005: Fixed `graq scan docs` crash when no doc manifest exists
- DF-006: Fixed background scan state file not being cleaned up

---

## v0.20.0 — Document Intelligence + Auto-Scaling (2026-03-14)

**The biggest release since v0.9.0.** Graqle now understands documents, JSON configs, and code in a single unified graph — and auto-scales to Neo4j when your graph grows past 5,000 nodes.

### Document-Aware Scanning (Phases 1-4)

Graqle is now the first tool that connects code intelligence to document intelligence in one graph. 8 out of 10 real developer questions hit documents, not code — now those answers are in the graph.

- **6-format parser pipeline:** Markdown, plain text, PDF, DOCX, PPTX, XLSX. Zero-dependency for MD/TXT; optional `pip install graqle[docs]` for rich formats.
- **Heading-aware document chunker:** Preserves document structure (heading hierarchy, page numbers, code blocks, tables). Configurable chunk sizes with overlap.
- **Auto-linking engine:** 4 levels — exact match (free), fuzzy match (free, Levenshtein + token overlap), semantic match (opt-in, embeddings), LLM-assisted (opt-in, budget-controlled).
- **Privacy redaction:** PII/secrets stripped before graph ingestion (API keys, passwords, tokens, emails, phone numbers). Configurable patterns.
- **Incremental manifest:** SHA-256 + mtime tracking in `.graqle-doc-manifest.json`. Unchanged files skip on rescan.
- **Background scanning:** `graq scan all .` runs code scan (foreground) then doc scan (background daemon thread). State file for cross-invocation progress tracking.

**CLI commands:**
```bash
graq scan all .              # Code + JSON + docs (background)
graq scan docs .             # Documents only
graq scan file report.pdf    # Single document
graq learn doc spec.pdf      # On-demand ingestion with linking
graq learn doc ./heavy-docs/ # Bulk directory ingestion
graq scan status             # Background progress
graq scan wait               # Block until done
graq scan cancel             # Stop background scan
```

**New node types:** Document, Section, Decision, Requirement, Procedure, Definition, Stakeholder, Timeline.
**New edge types:** DESCRIBES, DECIDED_BY, CONSTRAINED_BY, IMPLEMENTS, REFERENCED_IN, SECTION_OF, OWNED_BY, SUPERSEDES.

### JSON-Aware Graph Ingestion (Phase 5)

JSON files are the configuration layer that bridges documents to code. They scan after code but before documents — small, fast, highly structured, knowledge-dense.

- **Auto-classification:** Detects category by filename + content structure:
  - `DEPENDENCY_MANIFEST` — package.json, Pipfile, composer.json
  - `API_SPEC` — openapi.json, swagger.json (OpenAPI 3.x + Swagger 2.0)
  - `INFRA_CONFIG` — cdk.json, SAM templates, serverless.json, CloudFormation
  - `TOOL_CONFIG` — tsconfig.json, .eslintrc.json, .prettierrc.json
  - `APP_CONFIG` — config/*.json, settings.json
  - `SCHEMA_FILE` — *.schema.json
  - `DATA_FILE` — large files (>50KB) — skipped by default

- **Category-specific extractors:** Each produces typed nodes:
  - `DependencyExtractor` — npm deps/devDeps/scripts, Pipfile, Composer
  - `APISpecExtractor` — endpoints (method/route/params/tags), schemas, RETURNS/ACCEPTS edges
  - `InfraExtractor` — CloudFormation resources, `Ref`/`Fn::GetAtt` cross-resource edges
  - `ToolConfigExtractor` — compiler options, linting rules
  - `AppConfigExtractor` — flat/nested config values (secrets auto-filtered)

**CLI command:**
```bash
graq scan json .             # Scan only JSON files
```

**New node types:** Dependency, Script, Endpoint, Schema, Resource, ToolRule, Config.
**New edge types:** DEPENDS_ON, RETURNS, ACCEPTS, IMPLEMENTED_BY, CONSUMED_BY, TRIGGERS, READS_FROM, APPLIES_TO, INVOKES.

### Cross-Source Deduplication Engine (Phase 6)

Without deduplication, multi-source scanning produces a noisy graph where the same entity appears as 3-7 disconnected nodes. Now Graqle unifies them automatically.

- **3-layer deduplication pipeline:**
  1. **Canonical IDs** — Deterministic SHA-256 hashing by type+source. Re-scanning produces same IDs, so nodes update instead of duplicating. Supports: FUNCTION, CLASS, MODULE, ENDPOINT, CONFIG, DEPENDENCY, SECTION, DECISION, DOCUMENT, RESOURCE, SCHEMA, TOOL_RULE, SCRIPT.
  2. **Entity Unification** — Name variant registry matches across different source types. Generates variants: `verify_token` ↔ `verifyToken` ↔ `VerifyToken` ↔ `verify-token` ↔ `verify token`. Only matches cross-source (code ↔ doc, not code ↔ code).
  3. **Contradiction Detection** — Finds conflicting information across sources: numeric mismatches (config says 3600, doc says 1800), boolean mismatches, value mismatches. Case-insensitive comparison for strings.

- **Merge engine:** Source priority: Code > API spec > JSON config > User-taught > Documents. Longer description kept, properties fill gaps (no overwrite), provenance tracked.
- **Decision persistence:** User merge accept/reject decisions stored in `.graqle/merge_decisions.json`. Never asked the same question twice.

### Frictionless UX Layer (Phase 7)

Value before configuration. Always.

- **Document quality gate:** Auto-rejects low-value documents before scanning — too short (<50 chars), binary/garbled (>50% non-ASCII), no structure (0 sections), test fixtures, duplicate by hash. Quality score (0.0-1.0) for accepted docs.
- **Environment auto-detection:** DETECT don't ASK.
  - Backend: AWS credentials → Bedrock; `ANTHROPIC_API_KEY` → Anthropic; `OPENAI_API_KEY` → OpenAI; nothing → local
  - Languages: Python, TypeScript, JavaScript, Go, Rust, Java, C#, Ruby (from file extensions + config files)
  - Frameworks: Next.js, React, Django, CDK, Serverless, Terraform, Express, Vue, Angular (from config + package.json)
  - IDE: VS Code, Cursor, JetBrains (from project dirs)
  - Machine capacity: minimal (<4GB), standard (<8GB), capable (<16GB), powerful (16GB+)
- **Smart excludes:** Auto-generated based on detected languages (node_modules, __pycache__, dist, target, .gradle, etc.)
- **MCP config suggestion:** Auto-generates `.mcp.json` for detected IDE.
- **Natural language query routing:** Zero-LLM-cost keyword classifier routes free-text queries to the right tool:
  - `"what depends on auth?"` → impact
  - `"is it safe to change payment.py?"` → impact
  - `"before I deploy, what should I check?"` → preflight
  - `"what went wrong last time?"` → lessons
  - `"explain the auth system"` → context
  - `"how many nodes are there?"` → inspect
  - Complex multi-hop questions → reason (full graph reasoning)

### Pluggable Graph Backend with Auto-Upgrade (Phase 8)

- **Auto-shift to Neo4j at 5,000 nodes.** Don't ask, just do it and notify. The system detects when your graph outgrows JSON/NetworkX and recommends migration. Also triggers on >5s load latency.
- **Migration Cypher generation:** UNWIND batch pattern (same as TAMR+ pipeline). Creates constraints, indexes, and batch-inserts nodes and edges.
- **`migrate_json_to_neo4j()`** — Full migration function: loads JSON, creates Neo4j schema, batch inserts, backs up original file.
- **`check_neo4j_available()`** — Verifies driver installed before attempting migration.
- **Neptune support** — Configuration ready for AWS Neptune (teams). Backend detection skips upgrade for already-scalable backends.

### Configuration

New settings in `graqle.yaml`:

```yaml
scan:
  docs:
    enabled: true
    background: true
    extensions: [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"]
    max_file_size_mb: 50.0
    chunk_max_chars: 1500
    linking:
      exact: true
      fuzzy: true
      semantic: false        # opt-in (needs embeddings)
      llm_assisted: false    # opt-in (costs tokens)
    redaction:
      enabled: true
      redact_api_keys: true
      redact_passwords: true
  json:
    enabled: true
    auto_detect: true
    max_file_size_mb: 10.0
    categories:
      DEPENDENCY_MANIFEST: true
      API_SPEC: true
      TOOL_CONFIG: true
      APP_CONFIG: true
      INFRA_CONFIG: true
      SCHEMA_FILE: true
      DATA_FILE: false
```

### Tests

**1,484 tests passing.** Up from 976 in v0.19.0.

| Phase | Tests | What |
|-------|-------|------|
| 1-4 | 287 | Parsers, chunker, privacy, manifest, linker, doc scanner, background, CLI |
| 5 | 72 | JSON classifier, 5 extractors, scanner integration |
| 6 | 77 | Canonical IDs, unifier, merge engine, contradictions, decisions, orchestrator |
| 7 | 57 | Quality gate, auto-detection, NL router |
| 8 | 15 | Upgrade advisor, Cypher generation, threshold logic |

### Dependencies

New optional dependency group:

```bash
pip install graqle[docs]     # PDF, DOCX, PPTX, XLSX support
```

Adds: `pdfplumber>=0.9`, `python-docx>=0.8`, `python-pptx>=0.6`, `openpyxl>=3.1`.

---

## v0.19.0 — Multi-Agent Intelligence + Universal Fixes (2026-03-14)

**Multi-Agent Graph Access (P1-7 — the big unlock):**
- `graq context --json` — Structured JSON output, no ANSI codes, no embeddings. Subagents parse via Bash.
- `graq mcp serve --read-only` — Blocks mutation tools (`graq_learn`, `graq_reload`). Safe for subagents.
- `graq serve --read-only` — HTTP server with read-only mode (403 on write endpoints).
- **File locking** — Cross-platform (`msvcrt`/`fcntl`) file locking on `graqle.json` writes.
- `--caller <agent-id>` — Query logging with per-caller attribution in metrics.

**Windows Unicode (P0 — ADR-107):**
- Universal three-layer fix: UTF-8 stream reconfiguration, `force_terminal=True`, ASCII fallbacks.

**Region-Agnostic Backends (P1-4):**
- Removed hardcoded regions. Resolution: config → `AWS_DEFAULT_REGION` → `AWS_REGION` → `us-east-1`.

**Bedrock Model Validation (P1-5):**
- `graq doctor` validates model ID against Bedrock's available models with suggestions.

---

## v0.18.0 — Cloud Connect + Ontology Intelligence (2026-03-13)

- Graqle Cloud (`graq login` / `graq logout`) — optional, zero signup for local features
- OntologyRefiner — analyzes activation memory to suggest ontology improvements
- GitHub Action workflow (`graqle-scan.yml`)
- Studio Cloud Connect panel

## v0.17.0 — Field-Tested Release (2026-03-13)

- `edges`/`links` JSON key mismatch fix (P0)
- `entity_type` not loading from JSON fix (P0)
- Windows Unicode crash fix (P0)
- Impact analysis precision fix (skip structural edges)
- `graq learned`, `graq self-update`, `graq --version`
- `.graqle-ignore` support
- 901 tests passing

## v0.16.0 — Graqle Rebrand (2026-03-13)

- CogniGraph → Graqle. `pip install graqle`, CLI: `graq`, MCP: `graq_*`
- Backward compat: `pip install cognigraph` auto-installs graqle

## v0.15.0

- MCP hot-reload, confidence recalibration, business entity support
- Multi-project CLI (`graq link merge/edge/stats`)
- 797 tests passing

## v0.12.0

- Observer overhaul, adaptive activation, cross-query learning
- Call-graph edges, embedding cache (11K nodes: 30s → <1s)

## v0.10.0

- ChunkScorer replaces PCST as default activation
- Bedrock auth detection fix

## v0.9.0

- Neo4j backend (`from_neo4j()` / `to_neo4j()`)
- CypherActivation, chunk-aware scoring
- 736 tests passing
