# Changelog

All notable changes to GraQle are documented in this file.

---

## v0.42.3 — 2026-04-04

### Fixed
- **graq_generate task routing** — `_handle_generate` now uses `task_type="generate"` instead of `"reason"`, enabling proper model routing when task-based rules are configured in `graqle.yaml`. Cost reduction of 5-18x when routing code generation to a cheaper model.
- **graq_generate KG sync** — after non-dry-run file generation, new files are automatically synced into the knowledge graph (mirrors `_handle_edit` behavior). Subsequent `graq_reason`/`graq_context` calls about generated files now have full graph coverage.
- **graq_generate file resolution** — graceful handling for non-existent target file paths (graq_generate creates new files).

### Added
- **`context` parameter for graq_generate** — optional parameter to pipe `graq_reason` output as advisory design constraints into the generation prompt. XML-delimited, sanitized, capped at 4096 characters. Enables `graq_reason` → `graq_generate` pipeline for architecture-first code generation.

---

## v0.42.1 — 2026-04-03

### Added
- **Content security architecture** — 5-layer detection pipeline (property-key matching, 200+ regex patterns, Shannon entropy analysis, AST credential detection, semantic placeholder) classifies every node with a sensitivity level before content enters reasoning.
- **7 exit gates** — content redaction enforced at every path from KG to external APIs: LLM reasoning, chunk synthesis, description enrichment, embedding, code generation, code review/debug, and query reformulation.
- **Cryptographic audit trail** — SHA-256 content hashes (pre/post redaction), append-only JSONL security audit log, dry-run mode for verification before sending.
- **Sensitivity-aware embedding** — typed placeholders (e.g., `<API_KEY_VALUE>`) preserve vector quality while redacting actual values. SECRET content blocked from cloud embedding entirely.
- **Shannon entropy detector** — catches novel/custom secret formats not matching known regex patterns.
- `graqle/security/` package — sensitivity classifier, content gate, audit, entropy detector (932 lines).
- `graqle/core/redaction.py` — property-level redaction utilities (145 lines).
- 85 new tests (47 security architecture + 38 redaction).

### Security
- All 7 gates fail-CLOSED: if security module fails to load, content is NOT sent to external providers.
- Deep-copy node isolation prevents concurrent reasoning calls from corrupting each other's state.
- SECURITY.md updated with accurate description of content security architecture.
- Send-time overhead: ~7ms (negligible against 500ms-5s LLM API latency).

---

## v0.42.0 — 2026-04-03

### Added
- **GenerateResult dataclass** — all 14 backends now return structured results with truncation detection (`truncated`, `stop_reason`, `tokens_used`, `model`). Full str backward-compat via 30+ proxied methods.
- **Continuation loop** — `CogniNode.reason()` auto-continues truncated responses with configurable `max_continuations` (default 3) and seam deduplication.
- **Format-aware validation** — advisory output validation for `graq_generate`: balanced delimiters, SUMMARY marker, diff hunk integrity. Non-blocking.
- **Model output limits** — `model_limits.py` with 70+ model token limits, prefix matching, LRU cache.
- **File visibility fixes** — `graq_edit` auto-syncs written files into KG (OT-031/ADR-134), `graq_review` resolves relative paths (OT-033), abbreviated diff detection (OT-034).
- 60 new tests across 3 test modules.

### Changed
- **BREAKING:** `Aggregator.aggregate()` returns `tuple[str, dict]` instead of `str`. The dict contains `synthesis_truncated` and `synthesis_stop_reason`. Only 1 internal caller (Orchestrator).
- `OrchestrationConfig` gains `max_continuations` (default 3) and `continuation_overlap_lines` (default 15).
- `Message` dataclass gains `metadata: dict` field (default empty dict).

### Fixed
- OT-028: `graq_reason` responses no longer silently truncated at ~4000 chars.
- OT-030: `graq_generate` produces complete output for files >300 lines via continuation.
- OT-031: Newly edited files are auto-scanned into the KG (ADR-134).
- OT-032: Correction cost reduced from $2.50/call to ~$0.05 via continuation loop.
- OT-033: `graq_review` finds files regardless of working directory.
- OT-034: `graq_review` warns on abbreviated diffs instead of producing false positives.
- OT-035: Format validation catches structural incompleteness in generated code.

---

## v0.41.0 — 2026-04-02

### Added
- PR Guardian MVP — automated governance checks on pull requests.

---

## v0.40.7 — 2026-04-02

### Fixed
- **4 BLOCKERs + 3 MAJORs in debate_evidence.py** — found by `graq_review` dogfooding. Includes type safety, edge case handling, and error propagation fixes.

---

## v0.40.6 — 2026-04-02

### Fixed
- **4 wrong class names in debate_evidence.py** — import references corrected. All 10 research module imports now pass.
- KG stats updated after incremental rescan.

---

## v0.40.5 — 2026-04-01

### Fixed
- **OT-018: File reader truncation** — `graq_read` default limit raised from 200 to 500 lines. `max_chunks` raised from 5 to 15.
- **Windows env var fallback** — `_get_env_with_win_fallback()` reads Windows Credential Manager when environment variables are absent.

---

## v0.40.4 — 2026-04-01

### Added
- **R15 Multi-Backend Debate** — optional multi-LLM debate mode (`mode=off|debate|ensemble`). Governance-first design with cost ceiling, audit events, and TS-2 clearance. 4 patent claims (R11-R14).
  - `DebateConfig` in settings.py with panelist validation
  - `DebateTrace` / `DebateTurn` dataclasses in types.py
  - GPT-5.4 cost entries in OpenAI backend
  - 3 live OpenAI debate evidence runs completed

### Fixed
- **6 trade secret violations** remediated from research team review (3-round PR process).
- Test constant `decay_factor=0.75` replaced with `_TEST_DECAY` to avoid coinciding with internal values.

---

## v0.40.3 — 2026-04-01

### Added
- **R11 Confidence Calibration** — 200-question benchmark (7 confidence bands), ECE/MCE/Brier metrics, temperature/Platt/isotonic calibration, CalibrationWrapper. ADR-138.

---

## v0.40.1 — 2026-03-31

### Added
- **Research Sprint Complete** — R2 Bridge Edges, R3 MCP Domain, R5 Cross-Language Linker, R6 Learned Intent, R9 Federated Activation, R10 Embedding Alignment. 7 specs, 8 patent claims.

### Fixed
- IP Protection Gate live (ADR-140). HMAC rotated, TS-1..TS-6 externalized, branch protection enforced.

---

## v0.39.0 — 2026-03-28

### Added
- **ADR-123 KG Sync** — 6-phase S3 pull-before-read + push-after-write. Makes S3 single source of truth. 35 tests.

---

## v0.38.0 — 2026-03-27

### Added
- **Phase 10 SOC2/ISO27001 Compliance** — 5-layer governance gate, 201-pattern secret scanner, RBAC actor identity, policy DSL, adversarial test suite. 303 tests.

---

## v0.35.4 — 2026-03-26

### Fixed
- **Auto-grow hook now installed on `graq scan repo`** — previously the post-commit git hook
  that keeps the KG in sync with every commit was only installed by `graq init`. Public users
  who ran `graq scan repo .` directly never got the hook, causing their graph to go stale after
  commits. The hook is now silently installed at the end of every `graq scan repo` run.
  (`graqle/cli/commands/scan.py`)

---

## v0.35.1 — graq_predict v1.4 Hotfix + PSE Sprint (2026-03-26)

**Unblocks `fold_back=True`.** Two blocking bugs in `graq_predict` meant the core write-back mechanism never worked in v0.34.0. Both are now fixed. Four additional improvements ship in the same release.

### Fixed (v1.4 Hotfix — BLOCKING)

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `fold_back=True` always returned `SKIPPED_GENERATION_ERROR` | `areason()` calls `node.deactivate()` which sets `node.backend = None` before returning. The backend lookup loop always found `None`. | Replaced loop with `_get_backend_for_node(active_nodes[0], task_type="predict")` — uses 3-tier task routing, never returns `None` silently. |
| JSON extraction raised `re.error: unterminated character set` on LLM outputs containing `[`, `(`, or `*` in string values | `re.search(r"\{.*\}", raw, re.DOTALL)` crashes on regex metacharacters inside JSON string values | Added `_extract_json_from_llm()` module-level helper using brace-counting + trailing-comma strip. Handles all valid JSON regardless of string content. |

### Improved (v0.35.0 Sprint)

**`graq rebuild --re-embed` safety gate** (`graqle/core/graph.py`)
- Added `skip_validation=False` parameter to `Graqle.from_json()`. Default `False` — all existing callers unchanged.
- When `re_embed=True`, rebuild loads graph with `skip_validation=True` to bypass the embedding dimension check that would otherwise block recovery.

**Stricter agreement threshold** (`graqle/plugins/mcp_server.py`)
- Internal agreement threshold raised to reduce false write-backs caused by boilerplate token overlap between node responses.

**Embedding model transparency** (`graqle/plugins/mcp_server.py`)
- `graq_predict` output now includes `"embedding_model": "<model-name>"` field. Lets callers detect mid-session model changes that would cause a dimension mismatch on subsequent graph loads.

**`graq predict` CI gate** (`graqle/cli/main.py`)
- `--fail-below-threshold` exits with code 1 when `answer_confidence < confidence_threshold`. Use in GitHub Actions to gate deployments on reasoning confidence.
- Example:
```yaml
- name: graq_predict deployment gate
  run: |
    graq predict "$(git diff HEAD~1 --stat | head -20)" \
      --no-fold-back \
      --confidence-threshold 0.80 \
      --fail-below-threshold
```

### Patent Notice

European Patent **EP26167849.4** was filed 2026-03-25. The following features are patent-protected:
- `fold_back=True` confidence-gated graph write-back
- `_compute_answer_confidence()` cross-node agreement scoring
- Two-stage deduplication (content hashing + semantic similarity)
- `graq predict --fail-below-threshold` CI gate
- STG 4-class hierarchy + fold-back disable mode

### Files Changed

- `graqle/plugins/mcp_server.py` — FB-004 fix, FB-005 fix, stricter agreement threshold, `_get_active_embedding_model()`, `embedding_model` output field
- `graqle/core/graph.py` — `skip_validation` parameter on `from_json()`
- `tests/test_plugins/test_mcp_server.py` — 11 new tests (3 v1.4 hotfix + 8 v0.35.0)
- `tests/test_plugins/test_mcp_predict.py` — wired `_get_backend_for_node` in mock graph fixture

---

## v0.33.1 — Fix: Hardcoded US Bedrock Model IDs Break Non-US Users (2026-03-22)

**P1 Security/Config Fix.** Phantom Vision and SCORCH Visual audit were completely broken for any user in a non-US AWS region (eu-central-1, eu-west-1, ap-northeast-1, etc.) due to hardcoded `us.anthropic.*` model IDs.

### Fixed

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `ValidationException: The provided model identifier is invalid` on all Vision calls | `us.anthropic.claude-sonnet-4-6-20250514-v1:0` hardcoded in 4 files | Dynamic region resolution from `graqle.yaml` → `model.region` |
| `us.anthropic.claude-opus-4-6-20250514-v1:0` invalid even in US | Versioned Opus 4.6 ID doesn't exist | Changed to `{prefix}.anthropic.claude-opus-4-6-v1` |
| SCORCH default_config.json hardcoded to US | Template shipped with `us-east-1` | Empty defaults → auto-resolved at runtime |

### How It Works Now

Phantom and SCORCH configs auto-resolve Bedrock model IDs at runtime:
1. Read `model.region` from `graqle.yaml` (same as reasoning engine)
2. Fall back to `AWS_DEFAULT_REGION` or `AWS_REGION` env var
3. Derive region prefix: `eu-*` → `eu.`, `us-*` → `us.`
4. Build model ID: `{prefix}.anthropic.claude-sonnet-4-6`

No hardcoded model IDs remain in the plugin configs.

### Files Changed

- `graqle/plugins/phantom/config.py` — Added `_detect_region()`, `_resolve_vision_model()`, auto-resolution in `BedrockConfig.model_post_init()`
- `graqle/plugins/phantom/core/analyzer.py` — Removed hardcoded fallbacks, uses resolver
- `graqle/plugins/scorch/config.py` — `BedrockConfig.model_post_init()` delegates to phantom resolver
- `graqle/plugins/scorch/templates/default_config.json` — Empty defaults (resolved at runtime)

### Lesson Learned

> **NEVER hardcode region-prefixed Bedrock model IDs.** Always derive the prefix from the user's configured region. Hardcoded `us.` model IDs silently break ALL non-US users with a confusing `ValidationException` that appears to be an AWS issue, not a GraQle bug. This was recorded as a KG lesson (`lesson_20260322T210920`).

---

## v0.33.0 — Zero-Friction Install: Auto-Cache, Smart Venv Detection, Security Hardening (2026-03-22)

**Addresses community feedback on first-run experience.** Eliminates the #1 pain point (slow queries without embedding cache) and prevents virtualenv pollution, API key leaks, and silent init failures.

### Fixed

| Issue | What Changed |
|-------|-------------|
| **Embedding cache not auto-built** (CRITICAL) | `graq scan repo .` now auto-builds `.graqle/chunk_embeddings.npz` after scanning. No more manual `graq rebuild --embeddings` step. Queries go from ~30s to <1s automatically. |
| **Virtual environments scanned** | Scanner now auto-detects venvs by `pyvenv.cfg` marker file + name suffixes (`*_env`, `*-env`, `*_venv`, `*-venv`). Catches arbitrarily-named venvs like `yugyog_env/`. |
| **API keys at risk of git commit** | `graq init` now auto-adds `graqle.yaml` and `.graqle/` to `.gitignore`. Prevents accidental plaintext API key leaks. |
| **Silent init failure** | `graq init` now shows a yellow warning panel (not green success) when the graph has 0 nodes, with guidance on how to fix it. |
| **Doc scanner venv pollution** | Document scanner (`graq scan docs`) now excludes `env/`, `.conda/`, `site-packages/`, and venvs detected by suffix/marker. |

### Technical Details

- **scan.py**: Added `_is_virtualenv()` function with `pyvenv.cfg` detection + `_VENV_SUFFIXES` matching. Added auto-build cache block with `try/except` fallback.
- **docs.py**: Extended skip-names set and added suffix-based venv detection in `os.walk` loop.
- **init.py**: Added `.gitignore` auto-update after `graqle.yaml` creation. Added conditional success/warning panel based on `node_total`.
- **No API changes.** All fixes are in CLI commands — SDK API is untouched.

### Impact

- 168 tests pass (4 pre-existing patent-stub failures unchanged)
- E2E validated: fresh repo with fake venvs, binary files, edge-case code → clean 18-node graph
- Backward compatible — no breaking changes

---

## v0.31.3 — SCORCH Extended Skills: 10 New Audit Modules (2026-03-20)

**SCORCH v3 grows from 3 to 13 specialized audit skills.** Each skill is available as an MCP tool, CLI command, and Python SDK method.

### New Skills

| Skill | What It Audits |
|-------|----------------|
| `graq_scorch_a11y` | WCAG 2.1 AA/AAA: contrast, aria-labels, focus order, headings, landmarks |
| `graq_scorch_perf` | Core Web Vitals: LCP, CLS, FID, render-blocking, DOM size, images |
| `graq_scorch_seo` | Meta tags, Open Graph, Twitter Cards, JSON-LD, canonical, heading hierarchy |
| `graq_scorch_mobile` | Touch targets (44px), viewport, text readability, horizontal scroll, pinch-zoom |
| `graq_scorch_i18n` | html lang, RTL support, hardcoded strings, date/currency formatting |
| `graq_scorch_security` | CSP headers, exposed API keys (13 patterns), XSS, mixed content, HSTS |
| `graq_scorch_conversion` | CTA inventory/placement, form quality, trust signals, pricing clarity |
| `graq_scorch_brand` | Color palette compliance, typography, spacing, button/heading uniformity |
| `graq_scorch_auth_flow` | Login/signup/dashboard flows, auth vs unauth comparison |
| `graq_scorch_diff` | Before/after report comparison: resolved/new/persistent issues, improvement % |

### CLI

All skills available via `graq scorch <skill>`:
```bash
graq scorch a11y --url http://localhost:3000 --page / --page /pricing
graq scorch security --url https://myapp.com
graq scorch diff --previous ./old-report.json
```

### MCP

56 total tools (29 `graq_*` + 27 `kogni_*` aliases). All new skills auto-generate `kogni_scorch_*` backward-compatible aliases.

### Tests

**1,657 tests passing.** No regressions.

### Files Changed

| File | Change |
|------|--------|
| `graqle/plugins/scorch/phases/a11y.py` | NEW — Accessibility audit |
| `graqle/plugins/scorch/phases/perf.py` | NEW — Performance audit |
| `graqle/plugins/scorch/phases/seo.py` | NEW — SEO audit |
| `graqle/plugins/scorch/phases/mobile.py` | NEW — Mobile audit |
| `graqle/plugins/scorch/phases/i18n.py` | NEW — i18n audit |
| `graqle/plugins/scorch/phases/security.py` | NEW — Security audit |
| `graqle/plugins/scorch/phases/conversion.py` | NEW — Conversion funnel analysis |
| `graqle/plugins/scorch/phases/brand.py` | NEW — Brand consistency audit |
| `graqle/plugins/scorch/phases/auth_flow.py` | NEW — Auth flow audit |
| `graqle/plugins/scorch/phases/diff.py` | NEW — Before/after comparison |
| `graqle/plugins/scorch/engine.py` | Added 10 `run_*()` methods |
| `graqle/plugins/mcp_dev_server.py` | Added 10 tool definitions + 10 handlers |
| `graqle/cli/commands/scorch.py` | Added 10 CLI subcommands |
| `README.md` | Updated SCORCH CLI reference + MCP tools table |

### Breaking Changes

None. All changes are additive.

---

## v0.31.2 — Codex Audit Fixes: Observability, Smoke Tests, Windows Robustness (2026-03-20)

**Community-reported issues validated and fixed.** The Codex team tested graqle==0.31.1 on Windows Python 3.10 and reported 10 issues. We validated each against the actual codebase — 7 confirmed real, 2 were design decisions (patent stubs), 1 was false (no encoding artifacts). This release fixes the 5 zero-regression-risk items.

### New: `graq config` command

See your fully resolved configuration at a glance — backend, model, routing rules, graph connector, embeddings, cost budget. No more guessing what GraQle will use at runtime.

```bash
graq config              # Rich formatted output
graq config --json       # Machine-readable for CI/scripting
```

**File:** `graqle/cli/commands/config_show.py` (NEW)

### Enhanced: `graq doctor` reasoning smoke test

Doctor now verifies that your graph file actually loads and is ready for reasoning — not just that config files exist. Catches the case where `graq doctor` passes but `graq run` fails because the graph is empty or corrupt.

```
OK   Smoke: graph loads    396 nodes from graqle.json — ready for reasoning
```

**File:** `graqle/cli/commands/doctor.py` — added `_check_reasoning_smoke()`

### Fixed: Windows file lock fd leak

The Windows `msvcrt.locking()` retry path in `_acquire_lock()` could leak a file descriptor if all 10 lock attempts failed. Now wrapped in `try/except BaseException` to guarantee `fd.close()` on any failure path.

**File:** `graqle/core/graph.py` lines 43-57

### New: Fresh-install smoke test in CI

Added a `smoke` job to GitHub Actions that builds the wheel from source and installs it in a clean environment (no editable install, no dev deps). Runs on both Ubuntu and Windows. Validates `graq --version`, `graq --help`, `graq doctor`, and `graq config`.

**File:** `.github/workflows/ci.yml` — added `smoke` job

### Docs: Config field names + Bedrock auth clarification

- **Config fields:** Routing uses `default_provider` / `default_model` (not `fallback_*`). Added note in README.
- **Bedrock auth:** Documented that AWS Bedrock uses the standard boto3 credential chain (env vars, `~/.aws/credentials`, SSO, instance profiles). No GraQle-specific profile config needed.
- **CLI reference:** Added `graq config` and `graq config --json` to the command table.

### Codex Audit — Full Validation Matrix

| # | Reported Issue | Verdict | Action |
|---|----------------|---------|--------|
| 1 | Empty modules in wheel | Design — patent stubs | No change needed |
| 2 | Missing ConstraintGraph, PCSTActivation | Design — unreleased IP | No change needed |
| 3 | fallback_* config keys missing | Misidentified — fields are `default_*` | Docs clarified |
| 4 | Bedrock auth/profile implicit | True — implicit via boto3 | Docs clarified |
| 5 | Doctor passes but run fails | **Fixed** | Smoke test added |
| 6 | No fresh-venv smoke suite | **Fixed** | CI smoke job added |
| 7 | Windows fd leak in file lock | **Fixed** | `fd.close()` guaranteed |
| 8 | Encoding artifacts | False — no mojibake found | No change needed |
| 9 | No circuit-breaker on Bedrock | True — deferred to v0.32 | Tracked |
| 10 | Config-to-runtime observability | **Fixed** | `graq config` command |

### Tests

**1,700+ tests passing.** No regressions from v0.31.1.

### Files Changed

| File | Change |
|------|--------|
| `graqle/cli/commands/config_show.py` | NEW — `graq config` / `graq config --json` |
| `graqle/cli/commands/doctor.py` | Added `_check_reasoning_smoke()` |
| `graqle/cli/main.py` | Registered `config` command |
| `graqle/core/graph.py` | Fixed Windows fd leak in `_acquire_lock()` |
| `.github/workflows/ci.yml` | Added `smoke` job (Ubuntu + Windows) |
| `README.md` | Config field docs, Bedrock auth, CLI reference |

### Breaking Changes

None. All changes are additive or fix-only.

---

## v0.31.1 — GraQle Branding (2026-03-20)

- Capital Q branding applied across 134 files (Graqle → GraQle in prose/docstrings/console output)
- No code logic changes — branding only

---

## v0.31.0 — Adoption Friction Fixes (2026-03-20)

**5 real-world adoption issues fixed in one release:**

1. **`[all]` extras fixed for Windows** — removed `gpu`/`vllm` from `[all]`, added `[all-gpu]` for GPU users
2. **Upper-bound pins** — `sentence-transformers<3.0`, `torch<2.5`, `transformers<4.50`, `peft<0.14`
3. **`graq migrate` command** — renames `cognigraph.yaml/json` → `graqle.yaml/json`, updates CLAUDE.md and `.mcp.json`
4. **kogni_ → graq_ in AI instructions** — 45 tool name references updated in init.py
5. **PATH fallback in README** — `python -m graqle.cli.main mcp serve` for when `graq` isn't on PATH
6. **`graq doctor` PATH check** — warns if `graq` binary isn't on PATH with MCP fallback suggestion

### Tests

**1,700+ tests passing.**

---

## v0.29.0 — Cloud Sync + Multi-Project Dashboard (2026-03-17)

**Push your knowledge graph to GraQle Cloud. View it anywhere. Share with your team.**

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

`graq login --api-key grq_xxx` now validates the key against the GraQle Cloud API:
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

**The biggest release since v0.9.0.** GraQle now understands documents, JSON configs, and code in a single unified graph — and auto-scales to Neo4j when your graph grows past 5,000 nodes.

### Document-Aware Scanning (Phases 1-4)

GraQle is now the first tool that connects code intelligence to document intelligence in one graph. 8 out of 10 real developer questions hit documents, not code — now those answers are in the graph.

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

Without deduplication, multi-source scanning produces a noisy graph where the same entity appears as 3-7 disconnected nodes. Now GraQle unifies them automatically.

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

- GraQle Cloud (`graq login` / `graq logout`) — optional, zero signup for local features
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

## v0.16.0 — GraQle Rebrand (2026-03-13)

- CogniGraph → GraQle. `pip install graqle`, CLI: `graq`, MCP: `graq_*`
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
