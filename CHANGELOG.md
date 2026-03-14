# Changelog

All notable changes to Graqle are documented in this file.

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
