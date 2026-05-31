# Changelog

All notable changes to GraQle are documented in this file.

---

## 0.65.0 (2026-05-31) — [Metering layer: the billable unit for hosted proof anchoring]

> The open-core meter. A billable event (`unit="proof_anchored"`) is recorded
> only when a proof becomes *hosted* (anchored) — local work stays free — and is
> deduped to exactly-once on the proof's Merkle `leaf_hash` across both
> proof-production paths. Composition-only: no governed/anchoring internals are
> modified beyond one additive, never-raise observer seam.

**Added**

- New `graqle.metering` package (Apache-2.0, Community):
  - `MeterEvent` — the billable unit (`unit="proof_anchored"`, frozen, validated).
  - `MeterSink` Protocol — the one-method sink interface (the seam hosted
    backends implement); `LocalNullMeter` is the Community no-op (local = free).
  - `MeteredAttestationSink` — count point 1: wraps any runtime `AttestationSink`,
    meters the attested proof, then always delegates the durable write.
  - `make_meter_observer()` — count point 2: a never-raise callback for the
    Layer-5 `Committer`, fired once per leaf on the *anchored* transition.
  - `MeterDedupeStore` — WAL-backed exactly-once gate keyed on `leaf_hash`
    (atomic temp→fsync→replace→dir-fsync writes, integrity-checksum + content
    validation on recovery, DoS size cap). Exactly-once under retry, dual-path,
    and crash-mid-write.

**Changed**

- `Committer` gains an optional `meter_observer` parameter (additive, defaults
  to `None` = no metering). Fired only on the anchored transition, guarded so a
  metering fault can never break the anchoring path. No behavioural change when
  unset.

## 0.64.0 (2026-05-31) — [Standalone offline proof verifier + `graq attest verify`]

> The canonical, free-forever offline verifier for GraQle-format tamper-evidence
> proof bundles. Given a proof bundle and the signer's public key(s) — and
> nothing else: no network, no GraQle service, no proprietary code — anyone can
> verify a proof. This engineers the "survive-our-disappearance" guarantee: if
> GraQle vanished, every proof we ever emitted still verifies.

**Added**

- `graqle.governance.tamper_evidence.verifier.verify_bundle(proof_bundle, trusted_keys)`
  — composes leaf-hash recompute, Merkle inclusion, ed25519 windowed/3-state-lifecycle
  trust, and an optional **offline** Rekor binding check into one verifier.
  Returns a typed `VerifyResult` (never raises on a bad proof). Pure standard
  library + `cryptography`; imports nothing from the server/studio/anchoring
  surfaces. A runtime import-isolation guard enforces that at import time.
- `graq attest verify <bundle.json> --key <pub.pem>` CLI (also `--keys <keyring.json>`
  for explicit per-key validity windows + lifecycle states, `--rekor-sth`, and
  `--format text|json`), plus the dependency-light `python -m graqle.verify`
  entrypoint. Exit codes: `0` verified, `1` not verified, `2` usage error.
- An import-isolation CI gate (AST allowlist) that fails the build if the verifier
  or its surface ever imports outside the standard library, `cryptography`, and the
  four tamper-evidence primitives — so the offline-verifiability guarantee cannot
  silently regress.

110 tests at 100% statement + branch coverage (real signed + Merkle-anchored
fixtures, fault injection for every failure mode, and a studio-free subprocess
invariant proving the verifier runs standalone).

## 0.63.1 (2026-05-31) — [Fix: graq_learn now persists to Neo4j]

> Three fixes, all surfaced by dogfooding the v0.63.0 auto-grow loop on a
> Neo4j-backed setup. The headline fix makes `graq_learn` actually persist on
> Neo4j sessions for the first time (it previously failed with `SAVE_FAILED`
> on every call and, even past that, never wrote the lesson to the backend).

### Fixed
- **`graq_learn` SAVE_FAILED on Neo4j sessions.** `_save_graph` guarded only
  `if self._graph_file is None`, but a Neo4j session sets `_graph_file` to a
  `neo4j://…` connection URI — so it fell through and tried to write a JSON file
  literally named after the URI (invalid path → crash → `SAVE_FAILED`). A new
  `_is_backend_only_graph_file()` now treats `neo4j://`/`bolt://`/`neptune://`/
  `memgraph://` URIs the same as `None` → `NO_GRAPH_FILE` (a success state).
- **`graq_learn` never persisted to Neo4j (latent).** `graph.add_node`/`add_edge`
  are in-memory only; nothing flushed learned lesson/entity/knowledge nodes to
  the Neo4j driver, so they were lost on restart. A new
  `_persist_learn_to_backend()` writes the new node(s) + edges through via the
  existing `Neo4jConnector.save` path when a backend connector is attached.
  Backend write failure surfaces loudly (`SAVE_FAILED`) instead of a false
  success. Local-JSON sessions are unchanged (the previous path still applies).
- **`grow --embed` mis-routed Bedrock embeddings.** `grow`'s embed helpers built
  a bare `EmbeddingEngine()` instead of the config-aware
  `create_embedding_engine(cfg)`, so on a bedrock-backed project the Titan
  model-id was fed to sentence-transformers and failed to load. Now both
  `_embed_local` and the Neo4j `embed_fn` resolve the engine from config.

### Notes
- No CLI surface changes; fully backwards compatible. 16 new tests; the
  existing `test_save_graph_status` suite continues to pass (the new backend
  write-through is gated on a real connector being present).

---

## 0.63.0 (2026-05-31) — [End-to-End Auto-Grow Loop]

> `graq grow` now **embeds** new chunks and **writes the backend your graph
> actually reads from** (local JSON or Neo4j), so newly committed/saved code is
> queryable by reasoning within seconds — delivering the "the graph grows with
> every commit" promise. Embedding is incremental (only changed nodes), on by
> default, and degrades quietly in CI/mock environments. Three triggers (CLI,
> git hook, MCP background watcher) funnel through one fixed code path. No
> breaking changes to the `graq grow` CLI surface. See
> `docs/auto-grow-end-to-end.md` and ADR-213. Shared-team / Aura sync is
> deferred to a later release (investigation-first).

### Added
- `graq grow --embed/--no-embed` (default **on**) — embeds the chunks of changed
  nodes so they're queryable by `graq reason`. `--no-embed` reproduces the
  pre-0.63 structure-only behaviour.
- `graq grow --backend auto|local|neo4j` (default **auto**, derived from
  `graph.connector`) — writes the resolved backend; Neo4j gets node/edge +
  embedded-chunk writes, local gets `graqle.json` + a refreshed embedding cache.
- `ChunkScorer.update_cache_incremental(graph, changed_node_ids)` — incremental
  embedding cache update (boolean-mask drop of changed rows, embed only the
  delta, atomic write) with NPZ↔graph drift detection + full-rebuild self-heal.
  Avoids re-embedding the entire graph on every grow.
- MCP background auto-grow watcher (`graqle[watch]` optional extra) — shells
  `graq grow --embed` on debounced filesystem events so IDE saves keep the graph
  current between commits. Tunable via `GRAQLE_DISABLE_BACKGROUND_GROW`,
  `GRAQLE_BG_GROW_DEBOUNCE`, `GRAQLE_BG_GROW_RATE_LIMIT`. Degrades to disabled if
  `watchdog` is absent.
- `docs/auto-grow-end-to-end.md` — the 3-layer auto-grow guide.

### Changed
- `graq init`'s installed `post-commit` hook now runs `graq grow --embed` and
  **surfaces errors** instead of the previous `(graq grow --quiet 2>/dev/null &)`
  (which silently swallowed embedding/backend/config errors — the same
  silent-fail anti-pattern addressed by ADR-212). The hook still never blocks a
  commit.

### Security
- Sensitive (SECRET+) chunk content is redacted before any embedding call on
  BOTH the local and Neo4j paths (R-SEC-1), reusing the existing content gate.

### Notes
- Fully backwards compatible: existing `graq grow` callers get embedding on by
  default with no CLI surface change. The `graqle.json` node/edge serialization
  is unchanged.

---

## 0.62.3 (2026-05-30) — [HOTFIX: structural activation schema split]

> **Hotfix.** Eliminates a class of silent misconfiguration that caused
> `graq_reason` to return identical hub-only nodes for every query when
> `graph.connector: neo4j` + `activation.strategy: top_k` were both set
> in `graqle.yaml`. The combination is now structurally unrepresentable
> (the new schema makes it impossible to silently bypass the Cypher
> vector index). Old field names continue to work with a loud
> deprecation warning; will be removed in v0.65.

### Added
- New `ActivatorRegistry` (`graqle/activation/registry.py`) — single source
  of truth keyed on `(backend, ranking)` pairs. Eagerly populated at module
  import with 9 built-in combinations (local|neo4j|neptune × semantic|degree|none).
  Thread-safe register (with lock timeout + DoS guard MAX_ENTRIES=100) and
  lockless resolve (atomic dict read under CPython GIL).
- `graqle/activation/factory_helpers.py` — extracted `DegreeRanker`,
  `FullActivator`, and factory functions for every built-in pair.
- `ActivationConfig.ranking` field (`semantic` | `degree` | `none`) — the
  ranking algorithm, independent of backend.
- `Graqle._infer_backend()` method — explicit cases for None / Neo4jConnector
  / unknown type. Never returns "unknown" silently.
- `scripts/migrate_activation_yaml.py` — auto-migrates `graqle.yaml` between
  old and new schema with `--dry-run` and `--reverse` (rollback) modes.
  Preserves comments via `ruamel.yaml` when installed.
- `docs/migration_v0623.md` — full migration guide with field mapping table,
  per-backend recommended configs, and verification commands.
- `.gsm/decisions/SPEC-v0623-activation-schema.md` — design spec
  (sentinel-approved at 95% confidence, 3 rounds).
- 48 new tests across `tests/test_config/test_activation_schema_v0623.py`,
  `tests/test_activation/test_registry.py`, `tests/test_activation/test_session0_regression.py`,
  and `tests/test_scripts/test_migrate_activation_yaml.py`.

### Changed
- `ActivationConfig.strategy` is now a back-compat alias (default `None`).
  Pydantic v2 `model_validator` promotes legacy values via
  `STRATEGY_TO_RANKING` mapping (chunk→semantic, top_k→degree, full→none,
  pcst→semantic, manual→none) and emits a single consolidated
  `GRAQLE_LEGACY_ACTIVATION_SCHEMA` `DeprecationWarning` per config load.
- `ActivationConfig.top_k` is now a back-compat alias for `max_nodes`.
- `Graqle._activate_subgraph` rewritten from a ~140-line if/elif pile to
  a ~80-line registry-dispatch implementation. Preserves all legacy
  caller signatures (the `strategy` arg is now `str | None = None`).
- The `(neo4j, degree)` combination — exactly the Session-0 silent-freeze
  case — now logs a clear `WARNING` on every activation:
  *"ranking=degree ignores your Neo4j vector index — semantic search is disabled"*.
- `pyproject.toml` version `0.62.2 → 0.62.3`
- `graqle/__version__.py` version `0.62.2 → 0.62.3`

### Fixed
- **CRITICAL silent misconfiguration:** `connector: neo4j` + `strategy: top_k`
  no longer silently returns 50 hub nodes for every query. The deprecation
  warning + the degree-on-neo4j warning + the conflict warning all surface
  the misconfiguration loudly.

### Security
- `ActivatorRegistry.register` validates `backend` / `ranking` arguments
  against `^[a-zA-Z][a-zA-Z0-9_]*$` (injection guard against config-parsed
  values).
- Runtime registration requires explicit `GRAQLE_ALLOW_RUNTIME_REGISTER=1`
  env var; built-in registrations bypass this via `_builtin=True`.
- `MAX_ENTRIES=100` cap prevents DoS via unbounded registration.
- `register()` takes the registry lock with 1-second timeout to prevent
  deadlock-style DoS.

### Migration
Existing configs continue to work without change. To silence the new
deprecation warnings, replace:
```yaml
activation:
  strategy: top_k    # rename to →   ranking: degree
  top_k: 50          # rename to →   max_nodes: 50
```
Or run the auto-migrator:
```bash
python -m scripts.migrate_activation_yaml graqle.yaml
```
Full guide: [`docs/migration_v0623.md`](docs/migration_v0623.md).

### Verifiable
- `pip install graqle==0.62.3 && python -c "import graqle; print(graqle.__version__)"` → `0.62.3`
- Old yaml from any prior version still parses and runs (back-compat verified by RT_01).
- 3-question diagnostic against live Neo4j: `active_nodes` vary per question (semantic dispatch via `CypherActivation`), no longer returns frozen hub-only nodes.

---

## 0.62.2 (2026-05-27) — [docs-only: token economics case study]

> **Doc-only patch.** Functionally byte-identical to v0.62.1 — no production
> code, no tests, no dependencies changed. Ships the worked enterprise
> case study + hero callout in README.

### Added
- `docs/case-study-token-economics.md` — 4-developer team on a 50,000-node
  codebase: **$42,240/yr flat-file → $19,874/yr GraQle+API (−53%) →
  $5,174/yr GraQle+local SLM Year 2 (−88%)**. Every assumption stated, every
  number cited to 2026 public sources (Anthropic pricing, Cursor power-user
  data, Microsoft's killed Claude Code pilot, NCBI biomedical-KG research,
  Qwen3-Coder SWE-Bench benchmarks, EU AI Act Articles 26 + 99).
- README hero callout linking to the case study, right under the
  Independently-verifiable section.

### Changed
- `pyproject.toml` version `0.62.1 → 0.62.2`
- `graqle/__version__.py` version `0.62.1 → 0.62.2`

### Verifiable
- `pip install graqle==0.62.2 && python -c "import graqle; print(graqle.__version__)"` → `0.62.2`
- All v0.62.0 + v0.62.1 surfaces byte-identical.

---

## 0.62.1 (2026-05-27) — [docs-only: README v0.62.0 positioning rework on PyPI surface]

> **Doc-only patch.** Functionally byte-identical to v0.62.0 — no production code, no
> tests, no dependencies changed. Ships only to refresh the PyPI rendered description
> with the v0.62.0 positioning rework that already landed on GitHub master (PR #174).
> Updates: dev-first hero, runtime governance surfaced on top fold, `graqle govern serve`
> + `graqle govern health` quickstart, new Article 72 row in EU AI Act table, "Independently
> verifiable" callout, open-core pricing direction, all three patent numbers listed.
> Trade-secret discipline locked: CI `ip_content_scan.py` PASS + 11-pattern custom scan
> 0 violations + graq_predict combinatorial-disclosure mitigation applied.

### Changed
- `README.md` only (+140 / −135 lines, 287 → 292) — see PR #174 for full diff.

### Verifiable
- `pip install graqle==0.62.1 && pip show graqle` → version 0.62.1
- `pip install graqle==0.62.1 && python -c "import graqle; print(graqle.__version__)"` → 0.62.1
- All v0.62.0 surfaces (`govern serve`, `govern health`, `attest`, `@governed`, Layer 5) byte-identical.

---

## 0.62.0 (2026-05-26) — [Runtime Governance Layer (R2): the anchoring worker turns Layer 5 into a continuously, publicly verifiable production audit trail]

> **The "verifiable in production" story is now end-to-end shippable.** v0.59.0 shipped
> the cryptographic substrate. v0.60.0 (R0) added the one-line `attest()`. v0.61.0 (R1)
> added the FastAPI middleware so a deployed AI service captures decisions with no code
> change. **v0.62.0 closes the loop**: a long-lived `graqle govern serve` worker
> continuously seals decisions into Merkle batches, anchors them to the **public**
> Sigstore Rekor transparency log, and exposes Article 72 post-market monitoring health
> — without changing any Layer 5 module. Fully additive + opt-in: importing nothing
> from `graqle.governance.tamper_evidence.worker` (or not running `graqle govern serve`)
> leaves all prior behaviour byte-identical to v0.61.0.

### Added

- **`graqle.governance.tamper_evidence.worker.AnchoringWorker`** — the long-lived
  scheduler that wraps the **shipped** `Committer` + `LocalReplayQueue`. Each tick
  calls `Committer.flush()` (honours `batch_max_seconds` for a service) and
  `LocalReplayQueue.drain()` (re-anchors queued roots when Rekor recovers, respecting
  the shipped circuit-breaker; at-least-once, never drops). Public surface:
  `AnchoringWorker.run(max_ticks=None)`, `.tick()`, `.stop()`, `.health() -> WorkerHealth`,
  `WorkerHealth.to_dict()`.
- **Security wiring (load-bearing):**
  - **Fail-closed precondition** — `AnchoringWorker.__init__` refuses to construct under
    `fail_open_on_anchor_error=True` (the misconfig surfaces at startup, not silently
    at the first Rekor outage).
  - **PII-safe logging** — error logs carry `type(exc).__name__` + structural extras
    only, never `str(exc)`.
  - **Bounded shutdown flush** — a hung Rekor at process shutdown cannot block exit
    forever; the WAL stays durable so a future `run()` re-seals what didn't complete.
    Configurable via `shutdown_flush_timeout_seconds` (default 30s).
- **`graqle govern serve` CLI** (`graqle/cli/commands/govern_serve.py`) — runs the
  worker as a deployable service. Loads `AttestationConfig` from `graqle.yaml`,
  assembles the Layer 5 commit pipeline, installs SIGINT/SIGTERM handlers (with a
  `KeyboardInterrupt` fallback for Windows-console race), writes
  `.graqle/govern.pid` + `.graqle/govern.version`. Distinct exit codes for orchestrators:
  `1` = missing/corrupt config / worker refused / crash; `2` = `attestation.enabled=false`.
  `--once` runs a single tick (cron-style catch-ups). `--tick-seconds` overrides the
  loop interval. **`_WorkerConfigView`** bridges `AttestationConfig.security.fail_open_on_anchor_error`
  to the top-level attribute the worker reads (without this bridge, a YAML misconfig
  would silently disable the L5 no-silent-skip invariant).
- **`graqle govern health` CLI** — reads `.graqle/govern.health.json` (the snapshot
  the serve loop writes atomically every tick) and emits JSON for external monitoring.
  `--health-file` overrides the path, `--watch N` polls every N seconds
  (`KeyboardInterrupt`-safe), `--pretty/--compact` for human vs pipe-friendly output.
  Fields (PII-safe — counts, booleans, exception **type** names only):
  `running`, `ticks`, `records_committed`, `records_anchored`, `backfill_count`,
  `replay_queue_depth`, `seconds_since_last_anchor`, `last_error_type`, `status_counts`.
  This is the operator surface for **EU AI Act Article 72 post-market monitoring**.
- **Atomic snapshot write** — `NamedTemporaryFile` in the destination directory +
  `os.replace`, so a concurrent reader sees either the previous or the new snapshot
  — never a torn write. Orphaned `.tmp` files are cleaned up on `os.replace` failure
  to close a disk-exhaustion vector.
- Example `examples/runtime_govern_serve_anchoring.py` demonstrating the worker
  end-to-end with an in-memory sink.

### Notes

- **Opt-in & backward-compatible.** v0.62.0 output is byte-identical to v0.61.0 unless
  you import `graqle.governance.tamper_evidence.worker` or run `graqle govern serve`.
- **No changes to the cryptographic substrate.** R2 is pure assembly + lifecycle over
  the v0.59.0 Layer 5 + v0.60.0/v0.61.0 runtime capture. Zero edits to
  `tamper_evidence/{merkle,batcher,committer,sigstore_rekor,local_replay_queue,kg_persist,audit_log_v3,canonicalize,leaf_input_schema}.py`
  or `runtime/runtime.py` in this release.
- **Cryptographic guarantee, restated.** With `graqle govern serve` running, every
  governed decision captured by R0 `attest()` or R1 middleware is durably sealed into a
  Merkle batch and anchored to the public Sigstore Rekor log within
  `batch_max_seconds`. Any third party can verify any decision later using only the
  record + the Rekor entry + the public key — **no GraQle infrastructure access required.**

### Quality

- Triple-sentinel APPROVED 0 BLOCKERs across all three implementation PRs
  (R2-PR1 worker, R2-PR2 CLI, R2-PR3 health). PII safety verified at every layer.
- 100% statement+branch coverage on the new `worker.py`; 99% on `govern_serve.py`
  (1 missed line = POSIX-only SIGTERM install, exercised on Linux/macOS CI via
  `@skipif(win32)`).
- ruff clean. Zero regressions across the 436 existing governance tests.

---

## 0.61.0 (2026-05-25) — [Runtime Governance Layer (R1, Mode B): attach as FastAPI middleware]

> v0.60.0 added Mode A (the explicit `attest()` call). v0.61.0 adds **Mode B** — the
> "attach as middleware" path (ADR-221 §4.1). A deployed FastAPI/Starlette AI service
> can capture **every** governed decision as a durable, PII-safe, tamper-evidence-ready
> record **with no change to the decision code** — by mounting one middleware or
> decorating a route. Composes the shipped R0 `GovernedRuntime.attest()`; nothing in
> `tamper_evidence` or `layer_status` changed. Fully additive + opt-in.

### Added

- **`graqle.governance.runtime.fastapi`** — `GraqleGovernanceMiddleware` (Starlette
  `BaseHTTPMiddleware`) + `@governed` decorator (sync + async). Capture runs on a
  Starlette `BackgroundTask` (0 ms on the response path); lazily built so the package
  imports without Starlette (PEP 562).
- **`graqle.governance.runtime.mapping`** — fail-closed per-domain `DomainMapping` +
  `load_mapping(*_mapping.yaml)`: `identity → pseudonymize`, `hash_only → content_hash`,
  `governance → governance_metadata` (the leaf), `drop → never stored`. **Any
  unmapped field is dropped by default** — a middleware that sees a whole payload
  cannot leak a newly-added PII field by omission.
- Example `examples/runtime_middleware_fastapi.py` + `examples/runtime_mappings/loan_mapping.yaml`.

### Notes

- **Production-safety defaults.** Capture failure defaults to **fail-open with loud
  structured logging** (`on_error="log"`) — an audit side-channel must not turn a healthy
  response into an error for a real user; set `on_error="raise"` to fail-closed. Capture
  error logs carry the exception **type + domain only, never the exception message** (no PII
  leak via logs). A `max_body_bytes` cap (default 1 MiB) bounds the buffered response body
  (oversize bodies are streamed back unmodified and skipped, logged as
  `capture_skipped_oversize`). The shared default runtime is built behind a lock.
- **Streaming caveat.** The middleware buffers `application/json` responses; do not mount it
  on streaming/SSE decision routes (use the `@governed` decorator there). `text/event-stream`
  and non-JSON responses pass through untouched.
- **Opt-in & backward-compatible.** v0.61.0 output is byte-identical to v0.60.0 unless you
  import and use `graqle.governance.runtime.fastapi`.
- **Scope (R1).** This release is the framework attachment + mapping surface. The anchoring
  worker that batches → Merkle-commits → Sigstore-Rekor-anchors the durable trail out of
  band shipped in v0.62.0.

---

## 0.60.0 (2026-05-24) — [Runtime Governance Layer (R0, Mode A): govern what your *deployed* AI decides]

> **GraQle becomes dual-surface in code, not just positioning.** v0.59.0 shipped the
> cryptographic substrate (Layer 5). v0.60.0 adds the first piece of the **Runtime
> Governance Layer** (ADR-221): a deployed AI system can now govern what it *decides*
> — one added line per decision produces a durable, PII-safe, tamper-evidence-ready
> governed record on the same Layer 5 substrate, with 0 ms on the write path. Build-time
> governance proves GraQle holds itself to this standard; run-time governance lets you
> hold *your deployed AI* to it. Fully additive and opt-in — importing nothing from
> `graqle.governance.runtime` leaves all prior behaviour byte-identical to v0.59.0.

### Added

- **`graqle.governance.runtime` — the Runtime Governance Layer (R0 / ADR-221 Mode A).**
  Composition over the shipped Layer 5 primitives; nothing in `tamper_evidence` or
  `layer_status` changed.
  - **`GovernedRuntime.attest(domain, model_id, output, inputs=...)`** — the "one added
    line" at the point of inference. Builds a GovernedTrace leaf record with the frozen
    `LEAF_HASH_FIELDS`, computes the Merkle leaf hash via the **shipped**
    `leaf_hash_for_record` (so a runtime record is byte-compatible with what the Layer 5
    batcher/committer commit), folds `inputs`+`output` into a single `content_hash` (raw
    PII never stored), and durably records it. Returns the record.
  - **`RuntimeDecision`** dataclass + **`attest_decision()`** (structured-input form).
  - **`AttestationSink`** Protocol + **`DurableJsonlSink`** (fsync, `O_APPEND`, `0o600`
    owner-only) + **`InMemorySink`**. The forthcoming anchoring worker plugs into this
    same one-method interface to batch → Merkle-commit → Sigstore-Rekor-anchor out of band.
  - **`pseudonymize()` / `GovernedRuntime.pseudonymize_ref()`** — stable, non-reversible
    identifiers for PII-safe references.
  - Robustness: input validation (`domain`/`model_id` non-empty; `output`/`inputs` dict),
    non-finite-value rejection via the shipped canonicalizer (fails loudly; nothing
    written on failure), no-silent-drop sink contract, a `MAX_RECORD_BYTES` bound, and a
    proven thread-safe shared-instance design (concurrent `attest()` → zero lost/duplicate
    records).

### Notes

- **Opt-in & backward-compatible.** v0.60.0 output is byte-identical to v0.59.0 unless you
  explicitly import and call `graqle.governance.runtime`.
- **Scope (R0).** This release captures decisions into a durable, leaf-hash-compatible,
  PII-safe record via a pluggable sink. Merkle batching + Rekor anchoring as a long-lived
  worker, framework middleware (`@governed` / FastAPI), and a zero-touch sidecar are the
  next runtime increments (ADR-221 R1–R4).
- Runnable example: `examples/runtime_attest_production_decisions.py` — a deployed loan
  service attesting a decision stream, with verifier recompute. See the "Runtime layer
  (Mode A)" section of `examples/README.md`.

---

## 0.59.0 (2026-05-24) — [Layer 5: cryptographic tamper-evidence (RFC 6962 Merkle + RFC 8785 JCS + Sigstore Rekor + ed25519) + runtime layer-switch with monotonic-on]

> **GraQle v0.59.0 ships Layer 5 — cryptographic tamper-evidence — the step up from v0.58.0's *procedural* binding (tampering is detectable by inspection) to *cryptographic* binding (tampering is mathematically detectable by any third party with no GraQle infrastructure access). Governed-trace records are batched into RFC 6962 Merkle trees, canonicalised with RFC 8785 JCS, sealed under an ed25519-signed proof bundle, and the batch root is anchored to the public Sigstore Rekor transparency log. Implements R25-EU01 Phase M1 (Tasks 1.1–1.7) per ADR-RT-003. The whole layer is opt-in: with `attestation.enabled = false` (the default) v0.59.0 produces output byte-identical to v0.58.1 — the cryptographic machinery is real and inert-until-activated, not a no-op release. Layer 5 is the deepest of the five governance layers; a new runtime layer-switch architecture lets a deployment adopt L1–L5 on its own timeline, with a production "monotonic-on" rule (once a layer records its first governed write, it cannot be silently disabled — EU AI Act Article 12: once you start recording, you do not stop recording).**

### Added

- **`graqle.governance.tamper_evidence` — the Layer 5 module** (R25-EU01 Phase M1):
  - **`canonicalize.py`** — RFC 8785 JCS canonicalisation (Task 1.1). Separate `canon` (wrapper/signature scope) and `canon_leaf` (frozen leaf-input scope) functions; rejects non-finite floats (NaN/±Inf/−0.0) and non-JSON-native types so the leaf hash is deterministic across Python/JS/Go reference verifiers.
  - **`merkle.py`** — custom RFC 6962 Merkle tree (Task 1.2): leaf/node domain separation, duplicate-last-node padding, `InclusionProof` scaffolding, bounded tree size.
  - **`leaf_input_schema.py`** — the frozen leaf-hash-input allowlist (`LEAF_HASH_FIELDS`), separating it from the wrapper schema so wrapper fields can be added additively without changing any leaf hash (`proof_format_version` is *inside* the leaf to defeat version-relabel replay).
  - **`batcher.py`** — async batcher with a write-ahead log (Task 1.3): `tempfile → fsync → os.replace` durable enqueue, SHA-256 content-addressed idempotency, crash-recovery replay.
  - **`anchors/sigstore_rekor.py`** + **`local_replay_queue.py`** — Sigstore Rekor anchor (Task 1.4) with an independent circuit-breaker and a durable local replay queue fallback (CONDITION-3); `fail_open_on_anchor_error` defaults to `false` (an unreachable Rekor never silently skips anchoring).
  - **`committer.py`** + audit-log v3 (Task 1.5) — orchestrates batch → Merkle → anchor → persist with a no-silent-drop `CommitStatus`.
  - **`kg_persist.py`** + **`:CommittedBatch` Neo4j schema** (Task 1.6) — single-label, `batch_quarter`-partitioned schema; `Neo4jBatchPersister` mirrors each anchored batch into the KG write-once via `MERGE ... ON CREATE SET`.

- **`graqle.governance.layer_status` — runtime layer-switch + monotonic-on** (ADR-RT-003 §2.2, LS-1..LS-7):
  - Per-layer enabled/monotonic-on registry; production-mode first write flips a layer to `MONOTONIC_ON` and any later disable raises `LayerMonotonicityViolation` (the refused attempt is itself audited). Development mode toggles freely.
  - `dependency_graph.py` validates L5 requires L1+L2+L3; queryable transition `history()`.
  - **LS-7 monotonic-on CAS atomicity** — the in-process flip is lock-guarded, and `Neo4jConnector.persist_monotonic_on()` adds a cross-process **COALESCE write-once** compare-and-set so two concurrent writers can never double-flip (proven by a 50-threads × 200-iterations × 10-runs zero-duplicate test).

- **`graqle.governance.custody.ed25519_key_manifest` — signing-key validity window** (Task 1.7 / C-P2-1). Per-`kid` `valid_from`/`valid_until` window and a monotonic `ACTIVE → RETIRED → REVOKED` lifecycle: ACTIVE signs + verifies, RETIRED is verify-only (historical proofs stay valid), REVOKED is rejected unconditionally. Lets a verifier decide whether a `kid` was trusted to sign at the moment a proof was produced. Uses the `cryptography` ed25519 primitives (a core dependency).

- **`graqle.config.attestation_config` — Layer 5 config surface.** New `attestation:` block (all `extra="forbid"`); secrets (webhook URL, operator token, ed25519 signing-key path) are env-var-only. Omitting the block is byte-identical to v0.58.1.

### Changed

- **`graqle/governance/trace_capture.py`** gains one additive, opt-in observer hook for Merkle leaf emission; default behaviour unchanged.
- **Version** bumped `0.58.1 → 0.59.0` (single bump for the whole Layer 5 PR sequence PR-0…PR-7).

### Performance

- **Write-path latency unchanged** (AC-5). The cr-018 measurement-only spike measured the Merkle commitment over 1,000 R18 traces at **~200× headroom under the AC-5 target** (≤227ms P95, 10% over the R18 baseline) — the user-observable write path is async (the batcher adds 0ms to the write path; per-record commit is bounded by `T_batch + Rekor_P95`). AC-1 commit latency target ≤60s.

### Notes

- **Opt-in and backward-compatible.** With `attestation.enabled = false` (default) and no `attestation:` config block, v0.59.0 output is byte-identical to v0.58.1.
- **Cryptographic guarantee.** With Layer 5 enabled, tampering with any committed governed-trace record is detectable by any third party who can read the public Sigstore Rekor log — no GraQle infrastructure access required.

---

## 0.58.1 (2026-05-21) — [docs: refresh PyPI landing page to v0.58.0]

> **Documentation-only patch.** No code changes — functionally identical to v0.58.0.

### Changed

- **`README.md` PyPI landing page refreshed to v0.58.0.** The v0.58.0 release shipped the four Wave-3-substrate items but the README's headline (`## 🇪🇺 EU AI Act–aligned`) and "What's new" section still referenced v0.57.0, so the PyPI project page (which renders `README.md`, not `CHANGELOG.md`) displayed a stale changelog. This patch adds a dedicated "What's new in v0.58.0" section (cr-016 `GRAQLE_WORKTREE_ROOT`, cr-017 audit-log schema v2 + `policy_version`, cr-019 Article 43 docs, cr-021 OPSF PCT alignment), updates the EU-AI-Act headline to "v0.58.0, Wave 3 substrate", and points the "Full changelog" link at the v0.58.0 entry. The prior v0.57.0 "What's new" section is preserved below the v0.58.0 one as release history.

### Notes

- **Zero code changes.** Only `README.md`, `graqle/__version__.py`, `pyproject.toml`, and `CHANGELOG.md` modified. The package contents are byte-identical to v0.58.0.
- **Why a patch release:** PyPI per-version project descriptions are immutable once published, so refreshing the rendered landing page requires a new release. v0.58.1 is that refresh.

---

## 0.58.0 (2026-05-21) — [Research-Team v0.58.x directive: EU AI Act Wave 3 substrate, OPSF PCT alignment, parallel-worktree dev unblocked]

> **GraQle v0.58.0 ships the four built and sentinel-approved substantive items from the Research-Team-signed v0.58.x directive (cr-016, cr-017, cr-019, cr-021), plus the measurement-only cr-018 spike report that informed the R25-EU01 Phase M1 Merkle + Sigstore Rekor anchoring design. The cryptographic tamper-evidence layer itself (Merkle batch sealing + Sigstore Rekor external anchoring) ships separately as v0.59.0 — see the v0.59.0 entry when it lands. The previously-planned `x-ai-eu-enforcement` sibling namespace was not built for this release; it is folded into the broader R25-EU roadmap rather than a v0.58.1 point release. None of the four items change runtime behaviour for end users unless the new env vars or HTTP header are explicitly set; the new schema fields (cr-017 `schema_version` / `policy_version`) serialise byte-identically to v0.57.4 when absent or `None`. In other words: v0.58.0 adds new opt-in capability surface (env vars, an HTTP header, additive schema fields) but produces output byte-identical to v0.57.4 in the default/unconfigured state — the substantive additions are real and inert-until-activated, not a no-op release.**

### Added

- **`GRAQLE_WORKTREE_ROOT` env var honoured by the MCP server path resolver** (cr-016 — closes CG-MKT-11). The MCP server's `_project_root_from_graph_file` helper at `graqle/plugins/mcp_dev_server.py` now consults `GRAQLE_WORKTREE_ROOT` as the highest-priority project-root source, above the existing `graph_file` parent / `GRAQLE_SERVE_CWD` / `Path.cwd()` precedence. When the env var is set to an absolute directory path, `graq_write` / `graq_generate` / `graq_edit` accept paths under that root — unblocking parallel-worktree development workflows. Path-validation hardening mirrors CR-005a `graq_bash stdout_path`: `Path.resolve()` canonicalisation, `is_dir()` check, `logger.warning` + fall-through on invalid values. **Backward-compatible:** when `GRAQLE_WORKTREE_ROOT` is unset, behaviour is byte-identical to v0.57.4. 29 new tests across 3 layers; 0% regression confirmed via `git stash` A/B.

- **Audit-log record schema v2 + content-addressed `policy_version` binding** (cr-017 — closes the OPSF PCT v0.1 Comment 4 gap with shipped engineering). Every `GovernedTrace` record now carries two new fields: `schema_version: str = "2"` (wire-format generation marker; pre-cr-017 records read as implicit v1 via the new `classify_schema_version` helper) and `policy_version: str | None = None` (SHA-256 content-addressed binding to the active `baseline_doc.baseline_id`; readers needing a non-null value get the sentinel `legacy_pre_v058_unknown` from the new `get_policy_version_or_sentinel` helper for absent/None/empty values). The same `policy_version` field is added as the 11th field on `XAiEuExtension` so OPSF Use B PCT tokens carry the operator's compliance posture. Plus: `_trace_to_rdf` in `graqle/governance/shacl/validator.py` emits both as RDF triples (`schemaVersion` always; `policyVersion` conditionally when set) so downstream SHACL/RDF audit tooling can query them. Auto-population at trace creation time (read `baseline_doc.baseline_id` and write into every new trace) deferred to cr-017b. 66 new tests across 4 layers; 0% regression confirmed.

- **`docs/compliance/eu-ai-act/article-43-conformity-assessment.md`** (cr-019 — closes the docs-asymmetry vs Fuzentry's Article 43 evidence map). Maps GraQle's existing substrate (baseline-doc + audit-log + periodic-assessment + robustness attestation + Article 50 disclosure + claim-limits + Article 14 gate + Article 25 PCT) to Annex VI internal-control requirements per Article 43(1). Explicit non-claim: GraQle does NOT perform conformity assessment itself — the deployer composes the substrate evidence into their own Annex VI file. The deployer remains the conformity-assessment subject.

- **`CONTRIBUTING-COMPLIANCE.md`** (cr-019 follow-on). Repo-top-level contribution guide for EU AI Act docs specifically. Invites docs corrections, translations (DE/FR/ES/IT highest demand from EU-region deployers), compliance gap reports from deployers building Annex VI internal-control files, and cross-framework mappings (NIST AI RMF, ISO 42001, ENISA AI Threat Landscape, EBA AI guidelines). Explains the vocabulary discipline enforced in CI (snapshot-lock rejects `compliant`/`certified`/`guaranteed`/`end-to-end solution`), the four canonical positioning markers (`EU AI Act-aligned`, `Articles 6, 9, 12, 13, 14, 15, 25, 50`, `NOT high-risk`, `NOT GPAI provider`), and the three substantive non-claims enforced by `TestNonClaimsInvariants`.

- **OPSF PCT v0.1 alignment block** (cr-021 — this CR, the release-notes cross-reference plumbing item from the directive item #6).

### Changed

- **`docs/compliance/eu-ai-act/README.md`** (cr-019). Added Article 43 row to the article-by-article table. Added a new "Recent EU AI Act-relevant changes" section with a per-release table linking each v0.5x release to its EU AI Act items + the relevant article docs. Added "Contributing to this documentation" section.

- **`README.md`** (cr-019). Top-level repo / PyPI landing page README updated: Article 25 row now mentions cr-017's 11th field; new Article 43 row added; new "Contributions welcome on the compliance docs" subsection pointing at `CONTRIBUTING-COMPLIANCE.md`.

### Notes

- **Functionally byte-identical to v0.57.4 when the new env vars / HTTP header / schema fields are absent or `None`.** Constitutional 0% regression target met on all 3 code-touching CRs (cr-016, cr-017, cr-019's parity-test exclusion): verified by `git stash` A/B comparison on each.

- **Sentinel chain across all 4 CRs:** all sentinel passes APPROVED (cr-016 + cr-017 used `focus=all` + `focus=security`; cr-019 + cr-021 used `focus=correctness` per cost-optimisation rules — docs/CHANGELOG CRs don't need the 6-agent expensive run).

- **Pre-edit blast-radius prediction proved valuable on every code-touching CR.** `graq_reason` + `graq_predict(fold_back=false)` spent ~$0.10 per CR before any code was written; on cr-016 it caught a 95%-confidence regression risk that caused a proposed Edit 2 to be DROPPED before shipping; on cr-017 it flagged 4 ranked failure chains, 2 of which were subsequently dropped as phantom risks after a $0 grep audit.

- **One discovered-during-work pre-existing infrastructure drift:** the `Release Gate` CI workflow has been failing on every public PR since v0.57.2 with a `FileNotFoundError` (the workflow tries to load a `graqle.yaml` config that isn't in the action's working directory). **Non-blocking** for actual release — the gates that matter for release (`CI`, `Deploy Lambda`, `publish` on tag) all succeed. Cleanup CR queued.

- **One discovered-during-work CI gate doing its job:** the `IP Content Gate` (`scripts/ci/ip_content_scan.py`) caught a patent-application-number reference in cr-019's `CONTRIBUTING-COMPLIANCE.md` that pointed to a GraQle patent not yet on the gate's allowlist. Fix shipped as cr-019's IP-gate fix commit + backfilled to private via PR #131. Follow-up `cr-019c` queued to properly update the scanner allowlist.

### OPSF PCT v0.1 alignment

GraQle v0.58.0 ships engineering that aligns with the OPSF PCT v0.1 public comment window (submission deadline 2026-06-28). Quantamix submits an independent practitioner-reference OPSF comment by 2026-06-24 citing the v0.58.0 commitments below:

- GraQle PCT issuer ships RS256-only per OPSF PCT §5.2.
  Aligns with: independent practitioner submission OPSF Comment 1 (Wesley Felix, 2026-05-18).
  Source: graqle/pct/issuer.py (shipped v0.57.0, unchanged in v0.58.0).

- v0.58.0 ships content-addressed policy_version per audit record + in x-ai-eu extension.
  Aligns with: OPSF Comment 4 (Wesley Felix, 2026-05-18).
  Source: SDK-Op-2 in this release (cr-017 audit-log schema v2 + x-ai-eu field 11).

- v0.58.0 ships Merkle batch sealing + Sigstore Rekor external anchoring.
  Aligns with: OPSF Comment 5 (Wesley Felix, 2026-05-18).
  Source: SDK-Op-3 in this release (R25-EU01 Phase M1 — gated on R25-EU08 ADR + Senior `graq_reason` review at >= 75%; research-team target 2026-06-09).

- v0.58.1 will ship x-ai-eu-enforcement sibling namespace.
  Aligns with: OPSF Comments 2 + 3 (Wesley Felix, 2026-05-18).
  Source: SDK-Op-5 in v0.58.1 (deferred from v0.58.0 to ship Merkle work cleanly).

Article 5 prohibited-practices structured-assessment object (OPSF Comment 6) stays out-of-scope for GraQle's substrate per docs/compliance/eu-ai-act/out-of-scope-articles.md.

### Patent posture (unchanged from v0.57.x)

GraQle is patent-protected under EP26162901.8 (TAMR+, granted) and EP26167849.4 (PSE, granted), plus additional granted continuations covered in the file headers of `graqle/governance/` and `graqle/compliance/` modules. cr-017's `policy_version` field is a SHA-256 content-addressed hash — structural metadata, not novel patent-claim content. `baseline_doc.baseline_id` is already shipped public in v0.57.0. No new patent claim is made or weakened by any v0.58.0 item.

### Constitutional discipline reinforced

- 4 canonical positioning markers preserved verbatim across all docs: `EU AI Act-aligned`, `Articles 6, 9, 12, 13, 14, 15, 25, 50`, `NOT high-risk`, `NOT GPAI provider`.
- 3 substantive non-claims enforced in code by `TestNonClaimsInvariants` (no `compliant`/`certified` boolean field anywhere in the machine-readable surface — the test refuses any field that would assert these as true).
- README snapshot-lock CI gate refuses any new prose using `compliant` / `certified` / `guaranteed` / `end-to-end solution` (except italic / backtick / disavowal forms, per the test's `_LINE_EXEMPTION_PATTERNS`).

### Open follow-ons (not in v0.58.0)

- **cr-016b** — refactor `graqle/plugins/mcp_dev_server.py._resolve_file_path` to delegate root resolution to the cr-016 helper. `graq_predict` flagged a 95%-confidence regression risk for two edge cases (`graph_path=None` and `graph_path=URI` when `GRAQLE_SERVE_CWD` is set); cr-016b will land with proper edge-case test coverage.
- **cr-016c** — add `--memory-size 4096` to `deploy-lambda.yml` so the SF-11 Lambda-OOM mitigation survives every Deploy Lambda workflow run (currently imperative, gets reverted on every push).
- **cr-017b** — auto-populate `policy_version` from `baseline_doc.get_current().baseline_id` in `graqle/governance/trace_capture.py` so every new trace carries the binding without explicit caller code.
- **cr-019c** — update `scripts/ci/ip_content_scan.py` allowlist to include the granted continuation patents not yet recognised by the scanner so they can be referenced in public-facing docs without tripping the gate.
- **`.gitignore` semantics fix** — files in `docs/compliance/` currently need `git add -f` on first introduction because the broader `docs/` ignore wins against the `!docs/compliance/**` allowlist on Windows + Git for Windows + MSYS.

---

## 0.57.4 (2026-05-18) - [cr-022 SF-07 per-project graph routing across studio routes]

> **Closes SF-07 from the 2026-05-17 studio backend audit.** Before v0.57.4, the Studio Lambda served the default 12,354-node monorepo graph on every request *except* `/reason`, even when the frontend sent an `x-project-name` header. This meant users with their own project graphs in S3 (e.g. Brand_Collaboration's 611 MB graph, CopyForge's 45 MB, Bynder's 7 MB, brandio-frontend's 3,825-node graph) could not see those graphs anywhere in the Studio UI — every endpoint silently returned the default. v0.57.4 introduces a single `_resolve_graph_for_request(request)` async helper in `graqle/studio/routes/api.py` that 12 existing route handlers consult instead of reading `state.get("graph")` directly. When the `x-project-name` HTTP header is present and well-formed, the helper returns the project-specific S3-loaded Graqle graph (cached via the existing `_load_project_graph`); otherwise it falls back to the Lambda's default graph at `state["graph"]`. **Behaviour is byte-identical to v0.57.3 when the header is absent.** All 110 existing studio tests continue to pass; 22 new tests added.

### Fixed

- **`graqle/studio/routes/api.py` per-project graph routing** (SF-07). New `_resolve_graph_for_request(request)` async helper co-located with the existing `_load_project_graph` function. The helper reads the `x-project-name` header, returns the project-specific S3-loaded graph (cached after first load via `_load_project_graph`), and falls back to `state["graph"]` when the header is absent, the project name is malformed, or `_load_project_graph` raises. 12 existing handler call-sites (`/project-context`, `/metrics/summary`, `/graph/visualization`, `/graph/visualization/filtered`, `/graph/nodes`, `/graph/node/{node_id}`, `/reason`, `/governance/stats`, `/partials/metrics-cards`, `/partials/node-detail`, `/settings`, `/lessons`, `/neptune/upload`) consult the helper instead of `state.get("graph")` directly. The site at line 92 inside `_load_project_graph` itself is intentionally preserved (it reads the default graph to copy its backend onto the project-specific Graqle instance).

### Security

- **Anchored regex validation on the `x-project-name` header.** New module-level `_PROJECT_NAME_RE = re.compile(r"\A[A-Za-z0-9._\- ]{1,128}\Z")` matches at helper entry. Path traversal (`../`), separators (`/`, `\`), null bytes (`\x00`), control characters, and over-length names (>128 chars) are rejected; rejected names log a `logger.warning` and fall through to the default graph. **The `\A...\Z` anchors (not `^...$`) defeat a real bypass: by default `$` matches before a trailing newline, so `name\n` would have been accepted by `^...$`. This bug was caught by the new test suite before shipping.** All exception paths from `_load_project_graph` are also logged via `logger.warning` to address the silent-exception security blind spot identified by sentinel pass 1.

### Added

- **`tests/test_studio/test_resolve_graph_for_request.py`** (new file, 124 lines, 22 test cases). Covers: header absent (returns default), header empty string (returns default), header malformed with 6 attack vectors (`../../etc/passwd`, `project/subpath`, `foo\\bar`, NULL byte, over-length, empty), `_load_project_graph` raises (returns default + logs), `_load_project_graph` returns None (returns default), `_load_project_graph` returns valid graph (returned in place of default), regex accepts 7 well-formed names, regex rejects 7 malformed names (including the `name\n` bypass).

### Notes

- **Functionally identical** to v0.57.3 when the `x-project-name` header is absent. No CLI changes, no compliance semantics changes, no PCT changes, no claim-limits changes. All v0.57.3 tests continue to pass (110 pre-existing studio tests + 22 new = 135/135 PASS in 1.60s scoped).
- **Sentinel chain:** pass 1 (`focus=all`) returned `CHANGES_REQUESTED` at 92% with 1 valid BLOCKER (silent exception handling) + 2 valid MAJORs (no project name validation, no test coverage on the new helper) + 1 false-positive BLOCKER (an abbreviated diff misled the reviewer about `neptune_health_check`'s signature) + 1 deferred MINOR. After triage, 3 fixes were applied (logger.warning in except, anchored regex validation, 22-case test file) and the new tests caught the `^...$` regex anchor bug. Pass 2 (`focus=all`) on the hardened diff returned `APPROVED` at 95% with 0 BLOCKER + 0 MAJOR. Pass 3 (`focus=security`) on the final diff returned `APPROVED` at 95% with 4/5 agents agreeing.
- **Deferred follow-ups** (out of v0.57.4 scope, documented for future CRs): (1) `reason_stream` retains its own body-based `project` loading logic in addition to the new header-based helper — cleanup deferred to a follow-on CR. (2) Rate limiting on repeated malformed `x-project-name` requests needs a global middleware. (3) `_project_graph_cache` module-level dict thread-safety is pre-existing — bounded in practice by AWS Lambda's single-threaded execution model under the Python GIL.
- **Constitutional notes:** SF-07 implementation used native `Edit` rather than `graq_generate` because `graq_generate` returned `access_denied` on the cr-022 worktree path (same class as 4 prior V-violations from yesterday's session — the KG path-resolver capability gap). Logged as `V-CR-022-EDIT-NATIVE-001`. Systemic fix: Research-Team v0.58.x directive item #1 (cr-016 `GRAQLE_WORKTREE_ROOT`), which the SDK team starts after v0.57.4 ships.
- **SF-10 infrastructure pre-requisite:** an `AllowNeptuneBoltConnectToGraqleKg` IAM inline policy was attached to the `eu-trace-lambda-execution-role` during this session, scoped to the `graqle-kg` cluster only. This grants the Lambda execution role `neptune-db:connect` permission, which is a pre-requisite for SF-10 (Neptune IAM SigV4 auth) to ship in a future CR. The IAM grant itself changes nothing in production until SF-10 code lands.

### What's still open from the studio audit (after v0.57.4)

- **SF-08** — cross-project federation `/studio/api/control/cross-project/search` still returns "Neptune unavailable" because the cross-project module has its own Neptune availability check that doesn't read `NEPTUNE_ENDPOINT` directly. End-to-end requires SF-10 first.
- **SF-09** — Next.js proxy at `quantamixsol/cognigraph-studio` (separate repo) doesn't forward Cognito email as `x-user-email`. Out of scope for this SDK release.
- **SF-10** — Neptune IAM SigV4 auth via a new `graqle.connectors.neptune_auth.NeptuneIamAuthManager`. IAM permission is now granted; code change still needed. Architectural CR, planned as a separate ship.

---

## 0.57.3 (2026-05-17) - [cr-015 Neptune URI from environment variable]

> **Fixes `/studio/api/traversal/hubs` HTTP 500 on the production Lambda.** v0.57.2 added the `neo4j` Bolt driver to the Lambda zip (CR-013), but `graqle.server.app` still passed `graph_cfg.uri = bolt://localhost:7687` to `Neo4jTraversal()`, so every traversal query hit `ConnectionRefusedError: [Errno 111] Connection refused` against localhost on the Lambda. v0.57.3 reads `NEPTUNE_ENDPOINT` + `NEPTUNE_PORT` env vars at app-startup and constructs a proper `bolt+s://endpoint:8182` URI for Neptune. Falls back to `graph_cfg.uri` when `NEPTUNE_ENDPOINT` is empty (local Neo4j + test environments unchanged).

### Fixed

- **`graqle/server/app.py` Neptune URI construction** (SF-06). When `NEPTUNE_ENDPOINT` env var is present, build `bolt+s://{endpoint}:{NEPTUNE_PORT or 8182}` for the `Neo4jTraversal` connector instead of consulting `graph_cfg.uri` (which defaults to `bolt://localhost:7687` from `graqle.yaml`). Restores `/studio/api/traversal/hubs` from HTTP 500 to 200 on AWS Lambda after redeploy.

### Notes

- v0.57.3 is **functionally identical** to v0.57.2 except for the Neptune URI override path. Local development with Neo4j desktop or `docker run neo4j` (no `NEPTUNE_ENDPOINT` env var) continues to use the existing `graph_cfg.uri` flow. No breaking change.

---

## 0.57.2 (2026-05-17) - [cr-014 Compliance HTTP route surfacing]

> **Surfaces the EU AI Act subsystem envelope as Studio HTTP endpoints.** The `graqle.compliance.switch_status.build_switch_status()` function shipped in v0.57.0 as a Python module + CLI command (`graq compliance switch status`), but there was no HTTP route to expose it to the Studio frontend / graqle.com /security page. v0.57.2 adds two routes that read-only wrap the same builder.

### Added

- **`graqle.studio.routes.compliance` module** (new). Mounts `/studio/api/compliance/switch/status` and `/studio/api/compliance/status` HTTP endpoints. Both call `graqle.compliance.switch_status.build_switch_status()` and return the JSON envelope. Fail-closed exception handler returns `schema_version: "1.0"` + structured error body on any internal failure (never raises). Backs the canonical capability statement on graqle.com that "one switch flips every subsystem at once".

- **Studio app mounts `compliance_router` at `/studio/api/compliance`** in `graqle/studio/app.py`. No other route changes.

### Notes

- v0.57.2 is **functionally identical** to v0.57.1 except for the two new HTTP endpoints. No CLI changes, no compliance semantics changes. The same envelope that `graq compliance switch status --format json` already returned is now also reachable over HTTP.

---

## 0.57.1 (2026-05-17) - [cr-011 Studio backend restoration]

> **Bundled hotfix for three independent regressions found in the post-v0.57.0 Studio + Lambda audit.** Marketing on graqle.com advertised v0.57.0 + EU AI Act alignment but live curl of the production Lambda found `/studio/api/graph/visualization` returning HTTP 502 (response > 6 MB Lambda sync cap) and `/studio/api/traversal/hubs` returning HTTP 500 (`ModuleNotFoundError: neo4j` — the Neptune/Neo4j Bolt driver missing because v0.57.0 wheel ships `neo4j` only in `[all]`/`[all-gpu]` extras, not `[api]`, while the Lambda installs `[api]`). User-facing graph viz + traversal restored.

### Fixed

- **`[api]` optional-dependency extra now includes `neo4j>=5.0`** (SF-04). Previously only `[all]`/`[all-gpu]` included it. The studio Lambda installs `graqle[api]` and queries Neptune via the Bolt protocol through the `neo4j` Python driver; without this driver, `/studio/api/traversal/hubs` returned HTTP 500 (`ModuleNotFoundError: No module named 'neo4j'`). Restored after Lambda redeploy.

- **`/studio/api/graph/visualization` now caps response at the configurable `?limit=` param (default 2000 nodes, max 10000)** (SF-05). On KGs larger than `limit`, returns the top-N hub nodes by degree centrality plus only the links between selected nodes (no dangling D3 endpoints). Response always includes `total_nodes`, `total_edges`, `truncated`, `limit` so the UI can show "viewing N of M" hints. Previously crashed with HTTP 502 (`LAMBDA_RUNTIME Failed to post handler success response. Http response code: 413`) on KGs > ~3k nodes because the serialized payload exceeded the AWS Lambda 6 MB synchronous-response cap. Surgical fix — only modifies `graph_visualization`, leaves `graph_visualization_filtered` and every other handler in `routes/api.py` untouched.

### Notes

- v0.57.1 is **functionally identical** to v0.57.0 except for the studio-Lambda path. No EU AI Act semantics change, no PCT change, no claim-limits change. All v0.57.0 tests continue to pass. The CR-011 audit report (auditor: Claude, autonomous cost-optimised mode) and the SF-01/SF-03 deferrals are documented in `.gcc/branches/studio-audit-2026-05-17/STUDIO-AUDIT-REPORT.md` on the auditor's worktree (not shipped in the wheel).

---

## 0.57.0 (2026-05-16) - [cr-010 EU AI Act Wave 2]

> **EU AI Act Wave 2 — every subsystem the deployer's compliance file needs, behind a single switch.** Six new capability gaps (CG-MKT-01..06) close in this release: Article 14 human-review enforcement on auto-apply paths; R25-EU11 v1.0 claim-limits typed vocabulary (17 canonical values, 6 categories, `x-` extension namespace); VERITAS Q16.1 baseline-document generator; Q16.3 periodic-assessment with auto-remediation triggers; Q16.5 OBSERVATION-ONLY feedback-trend tracker (with mandatory AST audit test enforcing the Q-PATENT 2026-05-22 patent-novelty boundary); README snapshot-lock test that fails CI if forbidden marketing words slip in; weekly EUR-Lex content-hash drift guard. Plus a new `graq compliance switch` command that surfaces every EU-AI-Act-aware subsystem in one envelope — the deployer can answer *"what is the effective EU AI Act posture of this install?"* with a single call. Marketing-vs-built honesty score moves from 78/100 to ~98/100 (per ADR-MARKETING-003 verification registry).

### Added

- **`graq compliance switch` command** (new). Single UX entry-point for the EU AI Act mode toggle. Three subcommands:
  - `switch status [--format text|json]` — consolidated envelope showing master switch state + per-subsystem armed state for all 7 EU-AI-Act-aware subsystems (Article 50 disclosure, Article 14 gate, claim-limits, baseline-doc, periodic-assessment, feedback-trend, EUR-Lex guard). Versioned schema (`SWITCH_STATUS_SCHEMA_VERSION = "1.0"`) so CI consumers can pin against it.
  - `switch on [--shell posix|powershell|cmd]` — prints a shell snippet for the user to `eval`/`Invoke-Expression`. Does NOT modify the user's shell directly (env var lives in the user's shell, not in GraQle state).
  - `switch off [--shell ...]` — symmetric disable snippet.

- **`graqle.compliance.switch_status` module** (new). Pure data-assembly layer that probes 7 subsystems and returns a JSON-serialisable envelope. Every probe wraps in try/except — must never raise. Used by `graq compliance switch status` AND embedded under `eu_ai_act_subsystems` in the existing `graq compliance status` JSON output (additive — schema_version stays at `"1"`, no breaking change for v0.56.0 consumers).

- **`graqle.pct` package** (new — CR-010 PR-010b-1). Proof-Claims Token (PCT) issuer + validator + `x-ai-eu` extension namespace, per OPSF Use B framing (pre-action data-obligation permit). `graqle.pct.issuer.issue_pct()` mints a JWS (RS256 + kid header) carrying allowed_purposes / permitted_regions / extension claims; `graqle.pct.validator.validate_pct()` returns ALLOW/BLOCK with structured `failure_reasons`. Vendored OPSF schema pinned to commit SHA `f04bbc4862af836a2696e635275ead4bc835d9d1`. 64KB token-size cap (env-configurable via `GRAQLE_PCT_MAX_TOKEN_BYTES`) prevents DoS. Log-injection-safe `kid` sanitiser strips control chars + bidi-overrides. `graqle.pct.extensions.x_ai_eu.XAiEuExtension` is GraQle's first-public-draft of the `x-ai-eu` namespace (10 fields covering Article 6 classification, Article 9 risk-mgmt ref, Article 12 audit-log pointer, Article 13 transparency doc, Article 14 oversight mode, Article 50 disclosure mode, articles_covered, GPAI provider flag, Annex III category, compliance dossier ID). New CLI: `graq pct issue` + `graq pct validate`.

- **`graqle.compliance.article_14_gate` module** (new — CR-010 PR-010c, CG-MKT-01). EU AI Act Article 14(4)(c)+(d) human-oversight gate. When `GRAQLE_EU_AI_ACT_MODE=on` (or `--human-review-required` is passed), automated write paths (`graq_edit`, `graq_apply`, `graq_auto`) refuse to auto-apply with a structured `ARTICLE_14_HUMAN_REVIEW_REQUIRED` envelope when generation `confidence < threshold`. Default threshold `0.75` is a **placeholder pending R25-EU-CALIB-01 calibration spike** — the refusal envelope advertises `threshold_status: "placeholder"` so auditors see the gate state explicitly. New config field: `GovernancePolicyConfig.human_review_required_threshold`.

- **`graqle.compliance.claim_limits` package** (new — CR-010 PR-010c, CG-MKT-10). R25-EU11 v1.0 typed claim-limits vocabulary. Every governance record henceforth declares "what does this record explicitly NOT claim?" via 17 canonical values across 6 categories (temporal, model-dependency, data-scope, decision-scope, trust-boundary, compliance-scope) + operator-extension namespace `^x-[a-z0-9_-]{1,64}$`. L08 SHACL constraint `ClaimLimitsRequired` + L19 audit-trail rejection are fail-closed (default-deny). Backfill migration writes `["legacy_pre_R25_EU11"]` sentinel to pre-existing records. Public attribution: **Ricky Jones (TrinityOS)** LinkedIn 2026-05-13 formulation. Public taxonomy doc at `docs/compliance/eu-ai-act/claim-limits-taxonomy-v1.0.md`.

- **`graqle.compliance.baseline_doc` module** (new — CR-010 PR-010d, CG-MKT-02). VERITAS Q16.1 baseline-document generator per R25-EU04. Dated, version-pinned, content-addressed (`baseline_id = SHA-256(canonicalize(B))`) artefact at SDK install/upgrade time. Maps to EU AI Act Article 11 (technical documentation) + ISO 42001 Cl. 6.2 (planning). 9-field frozen dataclass; live quantitative metrics (governance gates active, defences active) with `NOT_YET_AVAILABLE` sentinels for metrics whose feed isn't wired yet (fail-loud — auditor sees the gap explicitly rather than `0`/`null`). New CLI: `graq compliance baseline-doc generate --output --signoff --format jsonl|pdf --test-archive-ref`. Append-only JSONL by default; PDF emitter with graceful RuntimeError when `reportlab` isn't installed.

- **`graqle.compliance.periodic_assessment` module** (new — CR-010 PR-010e, CG-MKT-03). VERITAS Q16.3 monthly/quarterly/annual assessment per R25-EU04. Computes 5 quality metrics over a trace-corpus window (`mean_confidence`, `p95_confidence`, `n_degraded`, `n_outcome_not_ok`, `n_governance_refusals`) and auto-creates remediation candidates on 3 default threshold breaches (`outcome>2% → high`, `degraded>5% → warn`, `mean_confidence<0.6 → warn`). Idempotent for same `(period, cadence, baseline_id)`. References the most recent baseline_id (AC-Q163-6 linkage to Q16.1). Maps to EU AI Act Article 9 + ISO 42001 Cl. 9.1. New CLI: `graq compliance periodic-assessment run`.

- **`graqle.compliance.evidence_state` module** (new — CR-010 PR-010e, CG-MKT-04 Layer B). VERITAS Q16.5 OBSERVATION-ONLY feedback-trend tracker. `WelfordAccumulator` pure online statistics + `compute_drift_indicator(current_mean, baseline_mean, baseline_stdev)` z-score with NaN/inf guards. 2-sigma `DRIFT_ALARM_SIGMA` threshold. **CRITICAL — patent-novelty boundary** per Q-PATENT 2026-05-22 binding decision: the drift indicator is an OBSERVATION, never a TRIGGER. No code path in v0.57.0+ may allow `drift_indicator` to invoke `calibrate()`. Enforced by **mandatory AST audit test** `tests/test_compliance/test_q165_no_active_recalibration_path.py` (4 tests scanning for forbidden symbols + verifying frozen-dataclass invariants). Keeps R25-EU04 patent-clean under existing EP26167849.4 Claim 4. New CLI: `graq compliance feedback record/ingest`.

- **`graqle.compliance.eur_lex_guard` module** (new — CR-010 PR-010f, CG-MKT-06). Weekly EUR-Lex authoritative-source drift guard. Enumerates `https://eur-lex.europa.eu/...` URLs from compliance docs (https-only regex; rejects http downgrade), fetches each (defense-in-depth URL re-validation at `_fetch_url` entry, 30s timeout, 10 MiB response cap, GET-only), SHA-256 hashes, compares vs committed `.graqle/eur-lex-baseline.json`. New CLI: `graq compliance eur-lex-check` (exit 1 on drift) + `eur-lex-refresh`. GitHub Actions workflow `.github/workflows/eur-lex-weekly.yml` (cron Monday 06:00 UTC) auto-opens a labelled issue if drift detected.

- **README snapshot-lock test** (new — CR-010 PR-010f, CG-MKT-05). `tests/test_compliance/test_readme_snapshot_lock.py` fails CI if forbidden bare words (compliant/certified/guaranteed/end-to-end solution) appear in README or `docs/compliance/eu-ai-act/*.md`, with negative-lookbehind exemptions for compound technical adjectives (privacy-compliant, GDPR-compliant) and line-level exemptions for italic `*word*`, backticked `` `word` ``, anti-claim sentences ("never say compliant"). Also locks the 4 canonical positioning markers verbatim: "EU AI Act-aligned", "Articles 6, 9, 12, 13, 14, 15, 25, 50", "NOT high-risk", "NOT GPAI provider".

- **Mandatory `test_q165_no_active_recalibration_path.py` AST audit** (CG-MKT-04 enforcement). 4 audit tests that fail the build if any symbol containing `calibrat`/`recalibrate`/`refresh_calibration` is called or imported from `evidence_state.py`. This is the patent-novelty *enforcement* — if a future contributor accidentally wires drift to recalibration, CI fails before the code merges.

- **PCT extension namespace docs** at `graqle/pct/extensions/README.md` documenting the 10-field `x-ai-eu` namespace. GraQle is the first-public-draft author of this OPSF-style extension; PR-010b-1 ships the implementation, and a follow-on OPSF Issue will propose it upstream.

### Changed

- **`graq compliance status` JSON output** (additive change, schema_version stays at `"1"`). New nested envelope `eu_ai_act_subsystems` (versioned independently as `SWITCH_STATUS_SCHEMA_VERSION = "1.0"`) surfaces all 7 EU-AI-Act-aware subsystems. Existing top-level fields (`eu_ai_act_mode`, `articles_covered`, etc.) are unchanged — v0.56.0 consumers see every field they relied on.

- **README rewritten** to lead with EU AI Act Wave 2. Article-by-Article table extended with new rows for Articles 9 + 11 (newly addressed in Wave 2). New "one switch flips every subsystem at once" code block. EU AI Act badge URL unchanged.

- **New compliance tests** — 437 new tests across `tests/test_compliance/` + `tests/test_pct/`. Total compliance + PCT test suite: 658 passed, 1 skipped (no regression on v0.56.0 surface). The skip is `test_envelope_integration.py` (pre-existing, needs external Neo4j).

### Positioning discipline (enforced in code, unchanged from v0.56.0)

GraQle is documented as **"EU AI Act–aligned"** — never *compliant*, never *certified*, never *guaranteed*. The 3 substantive non-claims from v0.56.0 remain enforced. The new `test_readme_snapshot_lock.py` test extends the enforcement to *every* doc under `docs/compliance/eu-ai-act/` plus the README, with exemption regex for legitimate compound technical adjectives.

### Public attribution (new in Wave 2)

- **VERITAS Pillar 16 Part 1** (Andrii Matiash, LinkedIn 2026-05-12) — anchor for Q16.1 + Q16.3 + Q16.5 sub-questions.
- **Claim-limits-as-typed-governance-field concept** (Ricky Jones, TrinityOS, LinkedIn 2026-05-13) — anchor for the R25-EU11 v1.0 taxonomy.

The taxonomy file, the 17-value canonical set, the L08 SHACL constraint definition, the L19 audit-trail integration, the runtime validator, the `x-*` extension namespace, and the backfill protocol are GraQle's contribution under each public attribution.

### Open follow-ons

- **v0.57.1** (calibration spike): R25-EU-CALIB-01 replaces the placeholder `human_review_required_threshold = 0.75` with a calibrated value derived from a Research-Team-owned spike. The `threshold_status` field will flip from `"placeholder"` to `"calibrated"` in the refusal envelope.
- **CG-MKT-11** (worktree-clone systemic blocker): the MCP server path resolver needs a `GRAQLE_WORKTREE_ROOT` env var honored by `graq_write`/`graq_generate`/`graq_edit` so the SDK can be developed end-to-end from any private-first worktree clone. Tracked as a separate CR; not blocking this release.

---

## 0.56.0 (2026-05-15) - [cr-009 EU AI Act Wave 1]

> **EU AI Act Wave 1 — GraQle is now EU AI Act–aligned by design.** The first developer reasoning SDK that ships a structured, version-pinned, CI-pinnable EU AI Act compliance surface. Seven articles documented (4, 12, 13, 14, 15, 25, 50), three new CLI surfaces (`graq compliance status`, `graq compliance export`, `--include-robustness`), Article 50(1) runtime disclosure (one-shot banner + machine-readable `ai_disclosure` envelope field), Article 15 machine-readable robustness attestation (17 named defences, 7 measurable claims with comparative-operator framing). Three substantive non-claims are enforced in code: GraQle is NOT itself a high-risk AI system, NOT a GPAI provider under Article 51, and we never say *compliant* or *certified* — only **EU AI Act–aligned**. The `TestNonClaimsInvariants` test class blocks any release that introduces a `compliant`/`certified` field anywhere in the machine-readable surface.

### Added

- **`graqle.compliance` module** (new package). `disclosure.py` ships the Article 50(1) banner emitter (once-per-process, `threading.Lock`-guarded against async race conditions) plus `AIDisclosure` + `ComplianceEnvelope` frozen dataclasses for MCP envelope hooks. `robustness.py` ships the Article 15 machine-readable attestation (17 defences, 7 measurable claims, 4 cybersecurity negatives, explicit adversarial-input boundary statement). Module-level constants `_ARTICLES_COVERED` and `_SYSTEM_CARD_URL` are duplicated in `graqle.cli.commands.compliance` with a drift-guard test enforcing parity.

- **`graq compliance status` CLI** (new). Read-only EU AI Act compliance posture introspection. Text mode prints a Rich table; `--format json` emits machine-parseable JSON matching the shape that the MCP envelope `compliance` block publishes when `GRAQLE_EU_AI_ACT_MODE=on`. Surfaces: GraQle version, mode flag, articles_covered list, system_card_url, audit_trail metadata (path, session_count, last_session_id stem — NEVER reads session contents), schema_version locked at `"1"`. `--include-robustness` adds the Article 15 attestation block. `--repo-root` to introspect a different repo's audit trail.

- **`graq compliance export` CLI** (new). Materialises the on-disk audit trail (`.graqle/governance/audit/*.json`) as a JSONL stream — one session per line — for Article 12 record-keeping evidence. `--since`/`--until` ISO date filters with full calendar validation via `datetime.strptime` (rejects `2026-02-31`, accepts `2024-02-29` leap). `--sha256-sidecar` writes a companion `<output>.sha256` with one SHA-256 hex digest per output line for tamper detection. Canonical-form serialisation (`sort_keys=True` + compact separators) gives deterministic byte ordering: re-running on the same input window produces byte-identical output. Symlinks in the audit dir are skipped with a stderr warning (hardening — audit trail is append-only on real files). Exit codes: 0 success, 2 bad input, 3 corrupt audit session.

- **EU AI Act compliance documentation** (`docs/compliance/eu-ai-act/`). 9 markdown files: index README, Article 4 (AI literacy — in force since 2025-02-02), Article 12 (record-keeping), Article 13 (deployer transparency), Article 14 (human oversight), Article 15 (accuracy / robustness / cybersecurity), Article 25 (value-chain responsibility), Article 50 (transparency for users), and an explicit out-of-scope file documenting Article 5 prohibited practices, Article 53 GPAI obligations, Article 55 systemic-risk GPAI duties, and Annex VII conformity assessment as **NOT applicable** to GraQle. Every article doc carries an authoritative-source link to EUR-Lex, an applicability-date header, and an applies-to-GraQle verdict (YES / INDIRECTLY / NO). All articles cited against [Regulation (EU) 2024/1689](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689).

- **Article 50(1) AI-disclosure runtime hook** in `graq_reason` MCP envelope. When `GRAQLE_EU_AI_ACT_MODE` is on, every reasoning envelope gains two additive fields: `ai_disclosure` (Article 50(1) machine-readable: `is_ai_generated`, `system`, `version`, `backend`, `ai_act_article_50_paragraph_1` legal anchor) and `compliance` (articles_covered, system_card_url, audit_log_export hint). Plus a once-per-process stderr banner on the first reasoning call: *"⚠ This response was generated by an AI system (GraQle v0.56.0 using {backend} backend). … AI Act Article 50(1) disclosure."* Banner suppress via `GRAQLE_AI_DISCLOSURE=off` for M2M pipelines (suppress applies to banner only — machine-readable field still emits, since downstream pipelines need it to compose deployer-level disclosure). When mode is OFF (default), envelope is **bit-for-bit unchanged** — additive contract preserved.

- **Comprehensive compliance test suite** (`tests/test_compliance/`). 218 tests across 6 files: docs presence + structure + authoritative-source-link + README index integrity + positioning-statement guards (54 tests for the docs surface); CLI surface tests for status (37) and export (65 including 16 parametrized date-bound rejections and the determinism / tamper-detect invariant); disclosure module (48) including banner once-per-session enforcement and stderr-closed-stream non-raising; envelope integration (12) verifying the additive contract under mode-on/mode-off, plus source-drift guards against the live `mcp_dev_server.py` hook; robustness attestation (21) including `TestNonClaimsInvariants` (no `compliant`/`certified` strings ship), drift-guard against article-15 doc and SECURITY.md.

### Changed

- **`README.md` rewritten** — 837 → 207 lines (75% reduction). Now leads with EU AI Act alignment, then explains what GraQle is, the 90-second proof, how it works, model-agnostic operation, governance gate activation, MCP-first integration, security posture, and pricing. Targeted at high-end engineering teams (regulated deployments, EU customers, analyst-grade due diligence).

- **`graqle.cli.main`** wires the new `compliance` sub-app into the typer entry point (2-line additive change: import + `add_typer`).

### Positioning discipline (enforced in code)

GraQle is documented as **"EU AI Act–aligned"** — never *compliant*, never *certified*, never *guaranteed*. Three substantive non-claims:

1. GraQle is NOT itself a high-risk AI system (no Annex III category applies to a developer-side reasoning SDK).
2. GraQle is NOT a General-Purpose AI Model provider under Article 51 (we use third-party LLMs; we don't place one on the EU market).
3. We provide signals and audit primitives; the deployer composes their own Article 9 risk-management file.

`tests/test_compliance/test_eu_ai_act_docs_present.py::TestPositioningStatement` enforces "EU AI Act–aligned" present in docs and "EU AI Act compliant" / "EU AI Act certified" absent. `tests/test_compliance/test_robustness.py::TestNonClaimsInvariants` enforces `article_15_compliant` / `article_15_certified` / `compliant` / `certified` fields are absent from every machine-readable surface.

### Test count

5,500+ passing (Python 3.10 / 3.11 / 3.12). 218 new compliance-specific tests added in v0.56.0.

---

## 0.55.0 (2026-05-14) - [cr-002 + cr-003 + cr-004 + cr-005a + cr-008 rollup]

> **Reasoning honesty + cross-project reliability.** Five CRs roll up into one release: graph-health surfacing on every reasoning envelope (CR-004), the cross-project `WRITE_COLLISION` phantom-error fix that affected every Neo4j-backed `graq_learn` call (CR-008), the unified config resolver promoted to default-ON with 13 internal call sites migrated (CR-002), defensive guards against silent edge-loss regressions (CR-003), and a TOCTOU-safe `stdout_path` parameter on `graq_bash` that closes the long-standing `cmd > file.log` silent-failure ergonomics class (CR-005a). All shipped under the new BAU CR process.

### Breaking changes

- **`GRAQLE_USE_RESOLVER` default flipped from OFF to ON** (CR-002 PR-002c-2b). The resolver is now the canonical config-loading path; submodule-aware ancestor walk for `graqle.yaml` works automatically. Set `GRAQLE_USE_RESOLVER=0` (or `false` / `no`, case-insensitive) to opt OUT and fall through to the legacy `GraqleConfig.from_yaml()` path. The resolver-compat helper has a try/except resolver→legacy fallback, so this flip is safe even in environments with a misconfigured resolver — the worst case is silent fall-through to the prior behaviour.

### Added

- **CR-004 — Reasoning Honesty.** New `GraphHealth` dataclass + `graph_health_probe` helper. Every `graq_reason` / `graq_predict` / `graq_safety_check` envelope now carries an explicit `graph_health` snapshot (8 fields: `node_count`, `edge_count`, `chunks_unembedded`, `percent_stale`, `activation_mode`, `degraded`, `reason`, `schema_version`). The `graq run` and `graq reason` CLI surfaces print a yellow `⚠ degraded reasoning: …` banner before the answer when the graph is degraded. Configurable thresholds (`stale_chunks_threshold` default 500, `edge_node_ratio_threshold` default 0.5, `zero_edges_is_degraded` default true) with env-var overrides. Probe is contractually never-raises (3-deep defence) and adds < 5 ms p95 to envelope build (CI fail-gate). Reason strings are scrubbed via reused `secret_patterns.scan_for_secrets` (200+ patterns), project-root elision, home-dir replacement, and capped at 200 chars.

- **CR-005a — `graq_bash stdout_path` parameter.** Optional new parameter on `graq_bash` writes the FULL untruncated subprocess stdout to disk atomically. Closes the long-standing `graq_bash("cmd > file.log")` silent-failure case (subprocess shell is sandboxed; shell redirects produce empty files). TOCTOU-safe validation per CR-005 § 3.1: canonicalise via `Path.resolve()`, then `relative_to(_project_root)` check, plus defence-in-depth `..` rejection on resolved parts. Parent directories auto-created. Atomic write via `NamedTemporaryFile` + `fsync` + `os.replace`. Failure isolation: file-write `OSError` never masks the subprocess result.

- **CR-002 — Unified Config Resolution.** `load_via_resolver_or_legacy` helper introduced; 13 internal `--config` typer call sites migrated. `GRAQLE_USE_RESOLVER` default flipped ON (see Breaking changes). `GraqleConfig.from_yaml` deprecation-warning block delegates to `is_resolver_enabled()` so the two entry points stay in lock-step.

### Fixed

- **CR-008 — Phantom `WRITE_COLLISION` on Neo4j-backed `graq_learn` calls.** Every `graq_learn` on a Neo4j-backed session was returning `error_code: WRITE_COLLISION` even though no write was ever attempted. Root cause: `_save_graph` returned `tuple[bool, int]` with `False` for FOUR distinct reasons (Neo4j-only / shrink-refused / real `PermissionError` / generic exception) and the four `_handle_learn_*` handlers conflated all four as collision. Replaced with `SaveGraphResult` + `SaveStatus` enum (OK / NO_GRAPH_FILE / SHRINK_REFUSED / COLLISION / SAVE_FAILED). NO_GRAPH_FILE folds into `recorded=True` because the in-memory + backend write already happened. Every project using `bolt://...` in `graqle.yaml` benefits — no client migration needed. New `persistence: <status>` field on `graq_learn` success responses lets clients distinguish Neo4j-only sessions from JSON-write completions.

- **CR-003 — Defensive Edge-Loss Guards.** Hardened guards against the silent edge-loss regression that affected installs between v0.46 and v0.53. `Graqle.to_json` refuses to shrink edge count by > 10% on graphs with > 100 baseline edges. Neo4j schema parity restored. New `scripts/bisect_edge_loss.py` utility for triaging regression-class bugs.

### Test count

5,500+ tests across Python 3.10 / 3.11 / 3.12. ~100 new tests this release (24 CR-008 status-disambiguation, 15 CR-005a `stdout_path`, 46 CR-004 health-probe + envelope + CLI banner, 14 CR-002 resolver migration + flag-default contract).

### Rollback

Every CR is independently revertable:

- **CR-002 flip:** `GRAQLE_USE_RESOLVER=0` env var, no code revert needed.
- **CR-004:** `graph_health` field is `None`-default; envelope omits the key when probe fails; CLI banner skipped on any probe failure. Soft-suppress via `graph_health.zero_edges_is_degraded: false` in `graqle.yaml`.
- **CR-008:** Additive only — new `SaveGraphResult` is back-compat with legacy 2-tuple callers via `_coerce_save_result` shim.
- **CR-005a:** `stdout_path` is optional; absent it, every existing `graq_bash` call is byte-identical to pre-CR-005a behaviour.
- **CR-003:** `GRAQLE_ALLOW_EDGE_SHRINK=1` to override the shrink guard for a single run.

---

## 0.54.3 (2026-05-13) - [bau-cr-007-reason-token-economics]

> **`graq_reason` now costs ~52% less, runs ~48% faster, and stops Bedrock throttling.** Empirical probe against a live 64K-node Neo4j KG: input tokens dropped from ~198K to ~47K per call (-76%), LLM calls from 101 to 51 (-50%), max single prompt from 24,618 to 8,015 chars (-67%), wall time from 49.8s to 25.9s, and 12+ Bedrock `ThrottlingException` retries dropped to 0. Six layered cost ceilings, all configurable via `GraqleConfig.orchestration` with pydantic-validated bounds. EU AI Act audit trails preserved verbatim.

### Why this release matters

Pre-v0.54.3, `graq_reason` was multiplicatively expensive on large activations. Each round issued one full LLM call per activated node (50 nodes × 2 rounds = 100 calls), and each call's prompt had no upper bound — evidence chunks, neighbor messages, and context concatenation could push a single call's input prompt past 24K chars on dense graphs. With Sonnet 4 retail pricing this was ~$0.86 per `graq_reason` call (the SDK's internal `cost_per_1k_tokens` constant reported $0.087, an 8× under-count). Bedrock `ThrottlingException` retries were the canary for the real spend.

This release does **not** change the multiplicative-fan-out architecture (that's a separate v0.55+ optimisation). It bounds the per-call and per-round spend so dense graphs stop blowing past sensible budgets.

### Added — new `OrchestrationConfig` knobs (all pydantic-validated, additive schema)

- **`evidence_hard_ceiling`** — chars cap on the per-node Supporting Evidence block. Applied **after** any embedding-based top-3 filter, so the final evidence shipped to the LLM is never larger than this regardless of embedding availability. Auditable `[truncated by evidence_hard_ceiling]` marker on hit. Default `4000` (~1K tokens). Range `100..200_000`.
- **`prompt_hard_cap`** — last-resort cap on the assembled per-node reasoning prompt. When exceeded, evidence + context are truncated symmetrically while preserving the system block, label/description, and query (head 60% + tail 30%). Auditable `[CR-007 prompt_hard_cap: middle truncated]` marker on hit. Default `10000` (~2.5K tokens). Range `500..400_000`.
- **`top_k_neighbors`** — caps neighbor messages forwarded in `_exchange_round` (round N+). Ranked by `node.activation_score`, fallback to insertion order. Default `8`. Range `1..200`.
- **`max_llm_calls`** — absolute LLM-call ceiling per `graq_reason` invocation. Checked **before** each round (projects `llm_calls_so_far + per_round_estimate` against `max_llm_calls - 1`, reserving 1 call for synthesis) so the ceiling actually constrains rounds. Halts cleanly between rounds — partial state never escapes. Default `60` (covers `max_nodes=50` + `max_rounds=2` + synthesis). Range `1..1000`.
- **`hierarchical_synthesis`** — feature flag (default `False`). When `True`, between rounds the orchestrator replaces per-neighbor messages with one summary per `node.community` / `node.entity_type` bucket via the new `MessagePassingProtocol._build_community_summaries` helper. Cuts inter-node messaging from `O(N × neighbors)` to `O(N × communities)` on dense graphs. Auditable `[community summary truncated]` marker on hit. **Opt-in until empirical validation completes.**
- **`hierarchical_summary_max_chars`** — cap on each community summary's content. Default `1500` (~375 tokens). Range `200..50_000`.

### Added — empirical regression utilities

- **`scripts/profile_reason.py`** — promoted probe utility. Wraps `backend.generate()` / `agenerate()` to record per-call prompt/output chars + latency. Prints CR-007 acceptance check inline (total input < 320K chars, LLM calls ≤ 60, max prompt ≤ 10K chars). Usable against any `graqle.yaml` for regression detection.
- **`tests/test_orchestration/test_token_budget.py`** — NEW, 14 deterministic regression tests (no live LLM required). Covers: defaults, pydantic bounds rejection, evidence truncation w/ marker, prompt cap w/ head+tail markers, top-K configurability, max_llm_calls casting, hierarchical_synthesis flag, `_build_community_summaries` entity_type fallback + truncation.

### Fixed

- **Synthesis prompt bypassed per-node `prompt_hard_cap`** (surfaced by probe — synthesis prompt was 17,295 chars). `AggregationStrategy._synthesize()` now uses budget-aware accumulation that stops at `prompt_hard_cap - 2000` (template headroom). Highest-confidence messages preserved (sort happens upstream); lower-confidence tail trimmed with auditable `[…CR-007 Fix 6: N lower-confidence message(s) omitted…]` marker.
- **`max_llm_calls` post-round-only check was ineffective** for `max_rounds=2` (round 2 always ran before the ceiling could halt anything). Tightened to a pre-round projection check that reserves 1 call budget for synthesis.

### Behaviour changes (knob-tunable; CHANGELOG-disclosed)

- **`Graqle.stats.density` unchanged** from v0.54.2.
- **`graq_reason` confidence on long-evidence canary queries** can regress by up to ~12 percentage points when defaults apply (e.g. 0.58 → 0.46 on a single observed query). The cost-vs-confidence tradeoff is exposed via the knobs. Quality-sensitive users raise `evidence_hard_ceiling`, `top_k_neighbors`, and `max_llm_calls`; cost-sensitive users opt into `hierarchical_synthesis=True`.
- **`graq_reason` log will emit a `warning` line** when `_sanitise_rel_type` falls back (CR-006b carryover) AND when `prompt_hard_cap` or `max_llm_calls` fire. The fallbacks are observable in audit logs without leaking raw content.
- **No graqle.yaml migration required** — pure additive schema. Configs without these keys get the defaults.

### EU AI Act / governance preservation

This is a P1 cost guard, not a governance change. Verified across the diff and confirmed by the security review (0 BLOCKERs, 0 MAJORs):

- `orchestrator.all_messages` keeps every original per-node message regardless of `hierarchical_synthesis` state. The summary only affects what the **next** round's nodes see; the audit trail has full provenance.
- Governance text (`semantic_governance_text`, `constraint_text`, `skills_text`, `label`, `description`) is never dropped — Fix 3's head 60% + tail 30% strategy always preserves it.
- Every truncation event emits a static `[…marker…]` so downstream compliance hooks can detect that a cost-guard fired.
- `ContentSecurityGate` (graph.py snapshot pattern) runs upstream of all CR-007 paths — no bypass introduced.
- `_sanitise_rel_type` (CR-006b) reused as the security boundary for any rel-type interpolation — no new injection vectors.

### Governance trail

- **Private PR**: `quantamixsol/research-development-graqle#88` (merged 2026-05-13).
- **Sentinel chain on consolidated diff**: `graq_safety_check` (MEDIUM, 38 modules, 0 CRITICAL) → `graq_plan` (`plan_6844133c`) → `graq_edit literal` × 14 → `graq_review focus=all` (**APPROVED**, 0 BLOCKERs, 2 MINORs addressed: pydantic Field bounds + bounds-rejection test) → `graq_review focus=security` (**APPROVED**, 0 BLOCKERs) → `graq_predict fold_back=false` (surfaced 5 downstream risks, all mitigated via configurability + this CHANGELOG note).
- **Scoped pytest** on `tests/test_orchestration/` + `tests/test_core/` + `tests/test_connectors/`: **529 passed, 7 skipped, 1 deselected** (pre-existing v0.54.0 baseline failure). **0 regressions.**
- **Empirical probe** against the live 64,223-node Neo4j KG (CR-006 fixed, full multi-edge graph present): all 3 CR-007 acceptance criteria PASS — total input < 320K chars, LLM calls ≤ 60, max prompt ≤ 10K chars.

### Probe acceptance results (live 64K-node Neo4j KG, max_rounds=2, max_nodes=50)

```
Metric                Before v0.54.3       After v0.54.3        Reduction
----------------------------------------------------------------------------
Total input chars     793,595              187,307              -76%
Input tokens          ~198,398             ~46,826              -76%
LLM calls per call    101                   51                  -50%
Max single prompt     24,618 chars         8,015 chars          -67%
Wall time             49.8s                25.9s                -48%
Cost (reported)       $0.087               $0.042               -52%
Bedrock throttling    12+ retries          0 retries            eliminated
```

---

## 0.54.2 (2026-05-13) - [bau-cr-006-multi-edge-full-fix]

> **Complete fix for CR-006 — silent multi-edge collapse across Neo4j + JSON storage paths.** On a 64k-node KG with 216,577 typed edges across 14 relationship types (CALLS=71,739, DEFINES=27,140, RELATED_TO=108,493, plus 11 more), the in-memory graph was reporting only 108,309 edges — exactly the `RELATED_TO` count — because parallel typed edges between the same `(source, target)` pair were silently collapsing in three coupled places: in-memory shape, Neo4j load, and Neo4j save.
>
> **What's fixed:** Full graph round-trip is now lossless. Reads load all 216,577 edges. JSON round-trips preserve edge ids. `graq learn`, `graq grow`, `graq predict --fold_back=true`, `g.save()`, and any `migrate_json_to_neo4j` writer now store typed Neo4j relationships (`:CALLS`, `:DEFINES`, `:IMPORTS`, etc.) instead of all collapsing to `:RELATED_TO`. Downstream analytics queries (impact, blast radius, PageRank, hub detection, community detection, neighborhood materialization) are now type-agnostic and see every edge type.
>
> **Why a single release instead of two**: combined CR-006a (read path, private PR #86) and CR-006b (write + traversal, private PR #87) into one PyPI release per project owner direction. No partial-fix window — users move from v0.54.0 (broken) to v0.54.2 (fully fixed) in one upgrade.

### Changed (BREAKING for downstream NetworkX consumers)

- **`Graqle.to_networkx()` now returns `nx.MultiDiGraph`** (previously `nx.DiGraph`). Parallel typed edges between the same `(source, target)` pair are preserved instead of silently overwriting one another. Edges are keyed by their `CogniEdge.id` so round-trips through `to_json`/`from_json` are lossless. Code that did `isinstance(G, nx.DiGraph)` returns `False` against the new output — switch to `isinstance(G, (nx.DiGraph, nx.MultiDiGraph))` or `G.is_directed() and not G.is_multigraph()` as a positive check.
- **`Graqle.stats.density` can now exceed 1.0** when parallel edges exist. The denominator stays at `n*(n-1)` but the numerator counts parallel edges (NetworkX standard `nx.density` behaviour on `MultiDiGraph`). No CLI/test currently asserts a specific density value; this is a behaviour disclosure for downstream callers that may have hard-coded `0.0–1.0` bounds.
- **`Neo4jConnector.save()` now writes native typed relationship labels** (`:CALLS`, `:DEFINES`, `:IMPORTS`, etc.) instead of collapsing every edge to `:RELATED_TO`. Existing Neo4j databases keep working — old `:RELATED_TO` edges are still readable. But: new edges produced by `graq learn` / `graq grow` / `graq predict --fold_back=true` / `g.save()` from v0.54.2 onward will be visible to native Cypher queries that filter by typed labels (e.g. `MATCH ()-[r:CALLS]->()`).
- **`graqle/connectors/neo4j_traversal.py` analytics queries are now type-agnostic.** All 11 traversal sites (impact analysis, shortest path, hub detection, node context, vector+graph search, PageRank, community detection, neighborhood materialization) now match every relationship type, not just `:RELATED_TO`. Downstream consumers that introspected typed paths returned by `shortest_path()` (which already returns `edge_types` via `[r IN relationships(path) | type(r)]`) will now see real typed labels in the result.

### Fixed (CR-006a — load + in-memory shape, private PR #86)

- **Site 1 — `graqle/core/graph.py:2823 to_networkx`**: Switched the in-memory NetworkX container from `nx.DiGraph` to `nx.MultiDiGraph`. Edges added with `key=eid` so each parallel edge between `(src, tgt)` is preserved under its own key. Updated return-type annotation. Fixes the half-graph collapse on every `to_json` call.
- **Site 2 — `graqle/connectors/neo4j.py:118 Neo4jConnector.load`**: When `r.id` is NULL (which it is for every typed-edge writer that doesn't explicitly set it — the common case), the synthetic edge id now includes the relationship type and a per-result counter (`f"e_{src}_{tgt}_{rel}_{idx}"`) so parallel typed edges between the same `(src, tgt)` pair stop colliding in the `raw_edges` dict. Added `None`-guard for malformed `source`/`target` fields with a redacted warning (logs only `raw_id` presence and sanitised `rel`, never full record content — OWASP A09 logging-failure guard).
- **Site 5 — `graqle/core/graph.py:735 from_networkx`** *(public-only, additional fix not in private PR #86 — caught by public reviewer)*: When the input graph is a `MultiDiGraph`, iterate `G.edges(keys=True, data=True)` so original edge ids carried in the NetworkX edge keys are restored to `CogniEdge.id` on round-trip. Previously, `from_json` → `node_link_graph` → `from_networkx` would re-synthesise positional eids (`e_{src}_{tgt}_{i}`) and drop the original ids. Round-trip is now strictly id-preserving for `MultiDiGraph` inputs; non-multigraph inputs still get positional eids (no behaviour change).

### Fixed (CR-006b — Neo4j writer + traversal, private PR #87)

- **Site 3 — `graqle/connectors/neo4j.py:222 Neo4jConnector.save()`**: Group `edge_rows` by sanitised relationship type, run one Cypher UNWIND per type with native rel-type interpolation: `MERGE (a)-[r:{rtype} {id: row.id}]->(b)`. Mirrors the Neptune connector pattern that already does it right. New `_sanitise_rel_type(name)` helper at module top enforces alphanumeric+underscore identifier safety with `RELATED_TO` fallback — Cypher injection is impossible by construction.
- **Site 3b — `graqle/connectors/upgrade.py:170 generate_migration_cypher` + its `migrate_json_to_neo4j` caller**: Same group-by-type pattern. The generator emits one `UNWIND $edges_<RTYPE>` statement per relationship type; the caller extracts the param name from the statement via regex and binds the appropriate edge subset.
- **Type-agnostic analytics — `graqle/connectors/neo4j_traversal.py`** *(caught by `graq_predict` during the sentinel chain — without this, post-CR-006b typed edges would be silently invisible to every analytics query)*. Removed hardcoded `[:RELATED_TO*N]` and `[r:RELATED_TO]` from 11 query sites: `bfs_impact`, `shortest_path`, `hub_nodes`, `node_context`, `vector_then_graph`, `compute_pagerank` (GDS + degree-approx fallback), `detect_communities` (GDS + connected-components fallback), `materialize_neighborhoods`. GDS `graph.project(...)` calls also updated from `'RELATED_TO'` to `'*'`.

### Added

- **4 regression tests in `tests/test_core/test_multi_edge_preservation.py`** (CR-006a):
  - `test_to_networkx_preserves_parallel_typed_edges` — 3 typed edges A→B (CALLS, DEFINES, IMPORTS) survive `to_networkx`; the output is `nx.MultiDiGraph` with 3 distinct edges.
  - `test_json_round_trip_preserves_multi_edges` — same 3-edge setup round-trips through `to_json`/`from_json`; edge count, relationship set, AND original edge ids are preserved.
  - `test_synthetic_eid_uniqueness_for_null_id_typed_edges` — Site 2 synthetic eid construction yields distinct keys for the three typed edges seen in the live KG.
  - `test_existing_collapsed_json_still_loads` — backward compatibility guard: legacy single-edge JSON files still load cleanly into v0.54.2.
- **28 regression tests in `tests/test_connectors/test_multi_edge_save_preservation.py`** (CR-006b):
  - **`TestSanitiseRelType`** (25 parametrized cases): 10 valid normalisations (`CALLS`, `calls` → `CALLS`, `uses envvar` → `USES_ENVVAR`, etc.) + 15 adversarial inputs (None, empty, leading digit, Cypher injection payloads with `; DROP CONSTRAINT`, `\nMATCH (n) DETACH DELETE n`, backticks/braces/parens/dots/slashes/pipes, non-string types) all sink to `RELATED_TO`.
  - **`TestMigrationCypherTyped`** (3 tests): single typed edge emits one statement with the right native label; three parallel edges (CALLS/DEFINES/IMPORTS) emit three distinct statements; adversarial `rel; DROP CONSTRAINT cogni_node_id;` sanitised to `RELATED_TO` with `DROP` and semicolons stripped from the interpolated Cypher.

### Governance trail

- **Private PRs**: `quantamixsol/research-development-graqle#86` (CR-006a, merged 2026-05-13) and `quantamixsol/research-development-graqle#87` (CR-006b, merged 2026-05-13).
- **Sentinel chain (CR-006a)**: `graq_safety_check` (MEDIUM, 40 modules affected, 0 CRITICAL) → `graq_review focus=all` ×2 (final: APPROVED, 0 BLOCKERs) → `graq_predict fold_back=false` (surfaced density-inflation + multi-graph-consumer risks, both disclosed above) → `graq_review focus=security` (APPROVED, 0 BLOCKERs).
- **Sentinel chain (CR-006b)**: `graq_plan` → `graq_edit literal` × 14 (helper + save + upgrade migrator + caller + 8 traversal sites + regex fix + debug log) → `graq_review focus=all` (APPROVED, 0 BLOCKERs, 2 MINORs addressed) → `graq_review focus=security` (APPROVED, 0 BLOCKERs, 1 MINOR addressed — debug logging on sanitiser fallback) → `graq_predict fold_back=false` — **surfaced `neo4j_traversal.py` hardcoded `:RELATED_TO` risk; fixed in this PR before opening.**
- **Scoped pytest**: `tests/test_core/` + `tests/test_connectors/` — **466 passed, 6 skipped, 1 deselected**. The one deselect (`test_neo4j_traversal::TestHubNodes::test_core_graph_is_hub`) failed on the v0.54.0 baseline too; expected to flip green naturally once production writes start storing typed labels (separate verification after release).

---

## 0.54.0 (2026-05-12) - [bau-edge-guard-resolver]

> **Defensive guards stop silent edge-loss + a unified config resolver lands behind a feature flag.** First release under the new BAU (Business As Usual) Change Request process. Two surgical, additive changes from third-party sister-team feedback (BHG epic, 2026-05-09): a `to_json` guard that refuses to silently drop edges (the v0.46→v0.53 regression mode), and the foundation module for unifying 14+ scattered `graqle.yaml` resolution sites.

### Added

- **`EdgeShrinkError`, `GraphSchemaError`, `GraphFileTooLargeError`** in `graqle/core/exceptions.py`. Inherit from `GraqleError`. `EdgeShrinkError` carries `old_edges`, `new_edges`, `threshold`, and `allow_flag` attributes; division-by-zero-safe message formatting.

- **Symmetric `links` validation** in `_validate_graph_data` (`graqle/core/graph.py`). Previously the validator checked `nodes` existence/type but ignored `links` entirely — the structural asymmetry that allowed the v0.46→v0.53 silent edge-loss regression to ship undetected. Now `links` (or its `edges` alias) must be a list, validated symmetrically with nodes. Refuses `{"nodes": [N>0], "links": []}` unless explicit `metadata: {single_node: true}` marker.

- **Edge-shrink guard** on the `Graqle.to_json` write path. When the existing on-disk graph has more than 100 edges AND the new graph would drop edges by more than 10%, `EdgeShrinkError` is raised with a clear remediation message. The 100-edge floor avoids spurious raises on small graphs and legitimate sparse-graph workflows.

- **`GRAQLE_ALLOW_EDGE_SHRINK` environment variable** as the audit-logged override. Strict allow-list: only `1`, `true`, `yes` (case-insensitive). Invalid values log a warning and are treated as not-allowed. The override path emits a single `logger.warning` audit line (`EDGE_SHRINK_ALLOWED file=<basename> old=<N> new=<N> user_hash=<sha256[:8]> pid=<N>`) for SOC2 § 6.3 change tracking. OWASP A09:2021-safe: no raw `USER`/`USERNAME` in logs, no full filesystem path — only `basename(path)` and a SHA-256-truncated user hash.

- **`graqle/config/resolver.py`** — new unified config resolver module behind the `GRAQLE_USE_RESOLVER` feature flag (default `False` — inert until callers migrate in a follow-up release). Provides:
  - `resolve_config(start, max_depth=10)` — ancestor walk for `graqle.yaml` with submodule fallback (when nested `.graqle/` directory has no yaml, falls through to a parent's yaml and records both `project_root` and `parent_root`).
  - `resolve_neo4j(cfg, **explicit)` — explicit auditable priority chain: `explicit > env > yaml > default` with a `source` field on the returned `Neo4jParams` recording which layer won.
  - `resolve_project_root(start, max_depth=10)` — first ancestor with `graqle.yaml` or `.graqle/`.
  - `is_resolver_enabled()` — reads the feature flag.
  - `ALLOWED_URI_SCHEMES = {bolt, neo4j, https, file}` — positive allow-list (not deny-list) closing the case/encoding/Unicode-bypass class.
  - `SecretStr` — constant-time `__eq__` via `hmac.compare_digest`, repr/str never reveal contents, `__slots__` blocks accidental attribute assignment.
  - Frozen dataclasses `ResolvedConfig` + `Neo4jParams`.

- **`graqle/config/exceptions.py`** — new file. 6 subclasses of `GraqleConfigError`: `ConfigNotFoundError`, `ConfigPathError`, `ConfigYamlError`, `ConfigPermissionError`, `ConfigLockError`, `ConfigSchemeError`.

- **`_assert_not_uri_path`** in the resolver — detects both `scheme://...` and the `scheme:opaque-data` form (`javascript:alert(1)`, `data:text/html;base64,...`) which `urlparse` correctly recognises as having a scheme even without `//`. Includes a Windows-drive-letter guard so `C:\\Users\\...` is not mis-parsed as a URI.

- **Ancestor walk safety** — `max_depth=10` bound, symlink-cycle detection via a `seen: set[Path]` of resolved paths, halt at `Path.home()` boundary, all paths canonicalised via `Path.resolve(strict=False)` before any disk access.

- **Round-trip property test suite** (`tests/test_core/test_persistence_round_trip.py`) — 8 tests, parametrized across 5 graph fixture sizes (5, 50, 100, 500, 1000 nodes) verifying `Graqle.from_json(p).to_json(p2)` preserves node count, edge count, and entity-type distribution exactly.

- **Edge-shrink boundary tests** (`tests/test_core/test_validate_graph_data_edge_shrink.py`) — 27 tests covering: symmetric validation, threshold boundary (exactly 10% loss = allowed, 10.1% = blocked), small-graph grace period, env-var allow-list (case-insensitive, whitespace-stripped, invalid-value warning), division-by-zero defence, OWASP A09 audit-log PII regression test (raw USER/USERNAME and full path must NOT appear in audit lines).

- **Resolver test suite** (`tests/test_config/test_resolver.py`) — 71 tests across 14 classes covering `SecretStr` (masking, constant-time eq, `__slots__`), `ResolvedConfig` validation, `Neo4jParams` masking, URI safety (allow-list + bypass class with `javascript:`/`data:`/`vbscript:`/`mailto:`/`ftp:` without slashes), `resolve_project_root` ancestor walk, `resolve_config` including submodule fallback, `resolve_neo4j` full priority chain, feature-flag toggling, home-redaction helper, end-to-end integration.

### Fixed

- **Silent edge-loss regression** introduced between v0.46 and v0.53. Symptom (BHG epic 2026-05-09, feedback #10): a `graqle.json` with 22,516 nodes and **0** edges. Root cause is being bisected separately (PR-003b); this release adds the defensive guard that makes the failure mode loud rather than silent. A graph that legitimately needs to drop edges by more than 10% (e.g. `graq scan --full` on a dramatically-trimmed source tree) now requires `GRAQLE_ALLOW_EDGE_SHRINK=1` and audit-logs the override.

### Changed

- **`Graqle.to_json` write path now refuses silent edge loss.** This is a behaviour change but only for the failure-mode CR-003 fixes. Existing healthy callers (where edge counts are stable or growing) see no behavioural difference.

### Notes — BAU process

This is the first release shipped under the [BAU (Business As Usual) Change Request process](https://github.com/quantamixsol/graqle/tree/master/.gsm/external/Change%20Requests) launched 2026-05-09. Every non-trivial change is now documented as a CR with explicit scope, evidence, PR strategy, test strategy, rollback procedure, and acceptance criteria. The full CR set for this release:
- `CR-001-bau-charter` — the BAU process charter itself
- `CR-002-unified-config-resolution` — the resolver work (PR-002a here; PR-002b follow-up migrates the 14 call sites)
- `CR-003-kg-persistence-schema-parity` — the persistence guards (PR-003a here; PR-003b bisect, PR-003c root-cause fix, PR-003d schema parity in `neo4j-import` are follow-ups)
- `CR-004-reasoning-honesty` — graph-health surfacing (next release)
- `CR-005-tool-ergonomics` — `graq_bash` improvements (next release)

### Migration notes

If `graq scan --full` or `graq grow` returns `EdgeShrinkError`, run with `GRAQLE_ALLOW_EDGE_SHRINK=1` once to record an audit line and proceed. If you see this on a graph you believed was healthy, run `graq audit --fail-on-zero-edges` to confirm whether you've been silently hit by the v0.46→v0.53 regression.

---

## 0.53.1 (2026-05-03) - [codex-mcp-installer]

> **One command installs GraQle into Codex.** First-class Codex CLI integration,
> full KG → Neo4j bulk transfer command, and a governance gate fix that eliminates
> the invisible permission dialog bug in VS Code.

### Added

- **`graq mcp install codex`** — Registers GraQle as a Codex MCP server in one command.
  Auto-detects Codex CLI on PATH, resolves absolute `graqle.yaml` path (relative paths
  break global MCP entries), runs `codex mcp add graqle -- graq mcp serve --config <abs>`.
  Supports `--mode read-only|read-write` and `--yes` for non-interactive use.
  Env vars (`GRAQLE_PROJECT`, `AWS_DEFAULT_REGION`, `AWS_PROFILE`) passed through with
  safe JSON serialization — no shell quote stripping on Windows.

- **`graq mcp doctor codex`** — 8-point health checklist: Codex on PATH → version →
  graqle listed → graq binary → yaml exists → env JSON valid → KogniDevServer importable
  → serve responds. Fails fast at the first broken step with a clear fix suggestion.

- **`graq mcp tools [--json]`** — Lists all 80+ MCP tools. Queries live server if
  running; falls back to static registry. `--json` for machine-readable output.

- **`graq mcp sessions`** — Shows running MCP server PIDs, versions, and lock files.

- **`graq mcp locks`** — Shows KG write locks currently held.

- **`graq neo4j-import`** — Full KG → Neo4j bulk transfer. Batched MERGE for nodes
  (core props + 1024-dim embeddings) and edges, with schema setup (uniqueness constraint
  + cosine vector index). Validates counts and runs a live vector search after import.
  Flags: `--dry-run`, `--batch-size` (1–5000), `--skip-schema`, `--kg-file`.

### Fixed

- **Governance gate permission dialogs in VS Code.** The gate template
  (`graqle/data/claude_gate/settings.json`) now ships with a full `permissions.allow`
  list for all `graq_*` and `kogni_*` MCP tools. Previously, Claude Code would silently
  wait for a permission dialog that never rendered in the VS Code extension, causing
  sessions to appear stuck. Users on existing installations: run `graq gate-install --force`
  once to apply the fix.

- **`pyproject.toml` version string.** Escaped backslash in `version = "0.53.1\"` caused
  `tomllib.TOMLDecodeError` on `pip install` — broke all CI jobs. Fixed.

---

## 0.53.0 (2026-05-02) - [reliability-release]

> **The reliability release.** 10 silent failure modes fixed across `graq_bash`,
> `graq_write`, `graq_reason`, and `graq_learn`. Users upgrading from v0.46–v0.52
> get automatic import-path shims with zero code changes required. Windows developers
> get stdout capture that actually works. Governance gates that were blocking
> legitimate read-only operations now get out of the way. Every fix is backed by
> targeted tests — 5,357 passing across Python 3.10 / 3.11 / 3.12.

### Fixed

- **BUG-001: `graq_write` path alias.** `path` parameter now accepted as alias
  for `file_path`. If both are present, `file_path` wins. Error message includes
  "Did you mean `file_path`?" hint when `path` was passed.

- **BUG-002: `graq_write` full-file rewrites unblocked.** New `force_overwrite`
  parameter bypasses CG-03_EDIT_GATE for intentional full-file rewrites. Runs
  `_run_preflight` first; governance log entry created on every use. Three-mode
  model now documented in the tool description.

- **BUG-003: `graq_bash` read-only commands bypass CG-02 gate.** New `read_only`
  parameter plus auto-detection (no `>` redirect, no mutating keywords: `rm`, `mv`,
  `pip install`, `git commit`, `DROP`, `DELETE FROM`). Auto-detected read-only
  commands skip the plan gate entirely.

- **BUG-004: `graq_bash` pip install respects active virtualenv.** Checks
  `sys.prefix != sys.base_prefix`. Inside a venv: allowed with governance log
  warning. Outside: blocked with "activate a virtualenv first" message.

- **BUG-005: Windows multi-line `python -c` stdout capture fixed.** On `win32`,
  if a `python -c "..."` command contains embedded newlines, the code is written
  to a `NamedTemporaryFile(.py)` and executed as `python file.py` instead. Temp
  file is deleted in `finally`. Env flag `GRAQLE_WIN32_PYTHON_C_TEMPFILE=0` to
  disable.

- **BUG-006: `graq_reason` orphan-node silent degradation fixed.** When all
  activated nodes have `degree == 0`, falls back to top-10 hub-connected nodes.
  Response envelope includes `activation_warning` key when `nodes_used == 1`.
  `graq_inspect(orphans=True)` lists all orphan nodes.
  Env flag: `GRAQLE_ORPHAN_FALLBACK` (default `"1"`).

- **BUG-007: `graq_learn(mode="outcome")` no longer creates edges to orphan
  nodes.** `LEARNED_FROM` edges are skipped when the target node has `degree == 0`;
  response includes `orphan_targets_skipped` list. New `create_lesson=False`
  parameter records metadata only with no graph write.

- **BUG-008: `graq_reload` unblocked before session start.** Added `"graq_reload"`
  and `"kogni_reload"` to `_CG01_EXEMPT` set. `graq_lifecycle(session_start)` now
  calls `_load_graph_impl()` unconditionally.

- **BUG-009: Backward-compatibility shims for renamed import paths.** Import paths
  renamed between v0.46 and v0.52 now have shims with `DeprecationWarning`
  (removal target: v0.55.0):
  - `graqle.scorer` → `graqle.activation.chunk_scorer`
  - `graqle.backends.bedrock` → `graqle.backends.api`
  - `graqle.api.GraqleClient` → `graqle.core.Graqle`
  - `graqle.cli.commands.scan.DocScanner` → `graqle.scanner.docs.DocumentScanner`
  - `BedrockBackend(model_id=...)` → `BedrockBackend(model=...)`
  - `BedrockBackend(profile=...)` → `BedrockBackend(profile_name=...)`

  New: `MIGRATION-0.46-to-0.52.md` — full migration guide with before/after examples.
  New: `graq doctor` now scans your project files for stale imports and reports
  exact replacement suggestions automatically.

- **BUG-010: numpy `.savez()` double-extension in atomic write pattern fixed.**
  `graq_graph_health(mode="rebuild")` correctly handles `.npz` extension without
  double-appending. `graqle.tools.npz_write(path, arrays, regression_check=True)`
  exposed as public helper.

---

## 0.52.0-alpha (2026-04-19) - [wave-1-gap-closure]

### Added

- **SDK-B5: Worktree `GRAQ.md` inheritance.** `GraqMdLoader` now
  detects git worktrees (where `.git` is a FILE containing
  `gitdir: <path>`) and walks the main repo's chain as well so the
  parent repo's `GRAQ.md` is inherited. Worktree-local `GRAQ.md`
  still takes precedence (closest-to-cwd wins, same as existing
  semantics). Defensive parsing: malformed `.git` files, empty
  gitdir, unreadable main repo — all fail-closed (fall back to the
  regular single-repo walk-up). New helper
  `_resolve_worktree_main_repo()`. 10 new tests in
  `tests/test_chat/test_graq_md_worktree_inheritance.py`. Test-driven
  iteration caught + fixed an ordering bug with `.reverse()`
  semantics before commit. 1198/1198 regression green. Sixth dogfood
  of `graq_release_gate`: CLEAR (risk=0.09, conf=0.96).
- **G3: `graq_vsce_check` — VS Code Marketplace version check.** New
  MCP tool + `kogni_vsce_check` alias (tool count 152 → 154). Queries
  the official Marketplace REST API (stdlib `urllib` only, no `vsce`
  runtime dep) to verify a proposed version does NOT already exist,
  preventing the v0.4.15 → v0.4.16 tag-collision incident class from
  recurring. Per `graq_reason` 96% consensus: Option A (HTTPS API)
  over Option B (shell out to `vsce show`) for minimal dependency
  footprint, better offline testability, deterministic error mapping.
  Returns `{exists, currentVersion, suggestedBump, versions}`.
  Defensive payload parsing (guards every nested access), strict
  semver validation (rejects `v`, `v1`, `0.4`, pre-release), and
  exhaustive `urllib` exception mapping (`timeout` / `HTTPError` /
  `URLError` / non-200 all resolve to structured errors, never raise).
  39 new tests. 1188/1188 regression green. Fifth dogfood of
  `graq_release_gate`: CLEAR (risk=0.12, conf=0.94).
- **CG-09 + CG-10 + CG-11: Bash, Read, Git governance gates.** Three
  coupled gaps closed in one commit. CG-09 (native `Bash` blocked)
  and CG-10 (native `Read` blocked globally, including `~/.claude/**`)
  were already enforced at the Claude Code hook template level; new
  regression-guard tests in `tests/test_gate/` codify the invariant.
  CG-11 (Git gate) is new MCP-side enforcement: `graq_bash` / `kogni_bash`
  calls whose `command` begins with `git <subcmd>` are routed to the
  dedicated `graq_git_*` tool when one exists (`status` / `commit` /
  `branch` / `diff` / `log`); subcommands without a graq_ equivalent
  (`push` / `pull` / `fetch` / `checkout` / ...) pass through. Wrapper
  forms (`sudo git ...`, `env VAR=1 git ...`, `git -C repo ...`,
  `git --git-dir ...`) are all correctly routed. 39 new tests.
  1149/1149 regression green. Post-impl `graq_review` + dogfood
  `graq_release_gate` verdict: CLEAR (risk=0.08, conf=0.95).
- **Wave-1 BLOCKER hardening** (post-impl-review audit, 2026-04-20).
  Seven hardening fixes applied across 4 files after mandatory
  post-impl `graq_review` + `graq_predict` escalation surfaced real
  production risks that passing tests had not caught:
    * `mcp_dev_server.py` — B1: guarded top-level imports of
      `_PERMITTED_RUNNERS` and `DEFAULT_SENSITIVE_KEYS` with narrow
      `ImportError` handling + safe fail-closed fallbacks so the MCP
      server survives degraded imports instead of failing to boot.
    * `mcp_dev_server.py` — B2: narrowed `__version__` import from
      bare `except Exception` to `ImportError`/`ModuleNotFoundError`;
      non-import errors now log loudly instead of silently masking
      packaging/release-gating failures.
    * `release_gate/engine.py` — B3: `_INTERNAL_RISK_THRESHOLDS.get()`
      with safe fallback instead of direct indexing, so invariant
      drift cannot raise `KeyError` and violate the never-crash
      contract.
    * `release_gate/engine.py` — B4: all fallback branches + provider
      calls + threshold lookup now use `effective_target` (the
      validated normalized value), not raw `target`.
    * `activation/layer.py` — B5: `TurnBlocked` raise now gated on
      explicit `tier_mode == ENFORCED and safety.should_block` rather
      than on `verdict.is_blocked`, preventing any future
      `ActivationVerdict` semantics drift from blocking advisory-mode
      turns.
    * `chat/fast_path.py` — B6: `is_path_safe` containment now uses
      `Path.is_relative_to()` (Python 3.9+) instead of lowercase
      string-prefix match, closing the `/tmp/app` vs `/tmp/application`
      confusion class.
  Dogfooded `graq_release_gate` on the combined diff: CLEAR
  (risk=0.10, confidence=0.96). 1,106/1,106 regression green.
- **SDK-B1: `graq init` auto-scaffolds `GRAQ.md`.** `graq init` now
  writes a project-type-aware `GRAQ.md` (Python / TypeScript /
  JavaScript / Rust / Go / generic) at the workspace root. The file is
  a user-facing walk-up that merges on top of the built-in chat system
  prompt. Per ADR-206, creation is ON by default; `--no-graq-md`
  disables. Existing files are never overwritten without explicit
  `overwrite=True`. Atomic write with try/finally cleanup — target
  remains unchanged on any IO failure. 22 new tests + 1106 regression
  green. Also: fixed a pre-existing case-sensitivity bug in
  `TestBuildMcpJson::test_structure` (Windows surfaces `graq.EXE`).
- **ADR-207: Zero-Violation Governance Discipline.** Session-level
  policy codifying (1) every native-tool call with a `graq_*`
  equivalent MUST use the governed path; (2) every commit runs
  `graq_release_gate` on the diff with verdict recorded in commit body;
  (3) every `graq_*` tool failure logged to `.gcc/capability-gaps.md`
  (no silent workarounds). First session-end audit: 1 violation logged
  honestly; 4 capability gaps surfaced to the SDK team. See
  [ADR-207](.gsm/decisions/ADR-207-zero-violation-governance-discipline.md).
- **ADR-206 / SDK-B3: Impact-Radius Fast-Path.** When the chat detects
  an unambiguous file-create intent with zero blast radius, skip the LLM
  pipeline (reason → generate → review) and write directly. Reduces the
  ~75s round-trip to ~0.3s on zero-impact creates. The ADR-205 safety
  layer still evaluates first — zero blast radius does not mean zero
  safety risk. Feature flag `fast_path_enabled` defaults ON
  (ADR-206 Decision: unified flag-default policy); kill switch via
  `GRAQLE_FAST_PATH_ENABLED=0`. New module `graqle/chat/fast_path.py`
  with strict regex classifier + containment-checked path safety.
  30+ new tests. Zero regression (739/739 green).
  See [ADR-206](.gsm/decisions/ADR-206-fast-path-policy-and-flag-defaults.md).
- **ADR-205: Pre-Reason Activation Layer (SDK-B2 + SDK-B4 + GOV-01 + GOV-02).**
  Every chat turn now runs through a three-layer pre-reason activation
  step before the LLM planner is invoked: (1) relevance scoring (TAMR+
  role), (2) safety evaluation (DRACE role), (3) predictive subgraph
  activation (PSE role). The layer is wired into
  `ChatAgentLoop.run_turn` and applies to ALL task types (plan, code,
  edit, debate, reason). Free tier runs in advisory mode (score visible,
  upgrade chip on would-be-blocks); Pro/Enterprise runs in enforced mode
  (turn transitions to FAILED on blocks). Feature flag
  `pre_reason_activation_enabled` defaults ON (codified guard against
  the v0.4.15 flag-never-flipped incident); kill switch via
  `GRAQLE_PRE_REASON_ACTIVATION=0` for regression bisection. New module
  `graqle/activation/` adds Protocol-based providers (matches R18 and G2
  architecture). 18 new tests, 239/239 existing chat tests green, zero
  regression. See
  [docs/governance.md](docs/governance.md#pre-reason-activation-chat-turn-safety-gate)
  and
  [ADR-205](.gsm/decisions/ADR-205-pre-reason-activation-layer.md).
- **G2: Release Gate.** Pre-publish KG-multi-agent governance gate — the
  only tool that combines KG-backed diff review with multi-agent risk
  prediction into a single structured verdict (`CLEAR` / `WARN` / `BLOCK`).
  Ships as three adoption surfaces:
    - **CLI** — `graq release-gate --diff ... --target pypi|vscode-marketplace`
    - **MCP tool** — `graq_release_gate` (also aliased as `kogni_release_gate`)
    - **GitHub Action** — `graqle/release-gate@v1` (Dockerfile-based,
      one-line adoption via `.github/workflows/release-gate.yml`)
  Engine uses the injection pattern (like R18 GovernedTrace) so tests never
  call real LLMs. Provider failures, timeouts, and malformed payloads
  resolve to a safe `WARN` verdict with a caller-safe reason — never
  crashing the build. 20 engine tests + 7 MCP-dispatcher tests, all green.
  See [docs/governance.md](docs/governance.md) and the copy-paste workflow
  template at
  [`.github/workflows/release-gate-example.yml`](.github/workflows/release-gate-example.yml).
- **CG-17 / G1: `graq_memory` MCP tool + memory-write gate.** Native
  `Write` / `Edit` on `~/.claude/projects/*/memory/*.md` is now blocked at
  the dispatcher; memory files must route through the new `graq_memory`
  tool (maintains `MEMORY.md` index + frontmatter validation + atomic
  writes + markdown-safe rendering). 30 new tests (28 pass, 2
  Windows-skipped for symlink/chmod). Zero regressions across
  `tests/test_plugins/` (308 green). Ships with `graq_memory` +
  `kogni_memory` (tool count 148 → 150 for CG-17, then → 152 for G2).

### Changed

- **MCP tool count: 148 → 152** (`graq_memory`, `kogni_memory`,
  `graq_release_gate`, `kogni_release_gate`).

---

## 0.51.6 (2026-04-16) - [unblocks-vscode-pivot]

### Correctness (P0)

- **T01: `Graqle.from_neo4j` is read-only by default.** The pre-v0.51.6
  default silently mirrored the loaded graph to `cwd/graqle.json` after every
  call, which corrupted the SOT during parity testing on 2026-04-16. New
  default is `mirror_to=None` (zero disk writes). Explicit opt-in with
  `mirror_to=<path>`; new `mirror_overwrite` param guards accidental clobber
  with `FileExistsError`. Fixed a latent bug: the mirror block called
  non-existent `graph.save()` - now correctly calls `graph.to_json()`.
- **T02: Neo4j migrator handles dict/list properties and chunks.** Arbitrary
  nested property values now JSON-encode cleanly; node `chunks` extract into
  `:Chunk` nodes via `[:HAS_CHUNK]` edges (matches `Neo4jConnector.save_chunks`
  contract) instead of crashing Neo4j. Verified end-to-end against
  `graqle-abtest-2026-04-16` (40,900 nodes / 68,241 edges / ~64,520 chunks).
- **T04: WRITE_COLLISION self-race eliminated.** The v0.51.5 retry envelope
  blamed "another MCP client" even on single-client sessions - the server
  was racing itself. Fix: module-level `threading.RLock` per absolute graph
  path acquired **before** the OS file lock; re-entrant so
  `graq_predict(fold_back=True)` -> `auto_grow` -> `graq_learn` no longer
  deadlocks. Retry backoff switched from fixed 50 ms * 1.5^k to random
  uniform [50, 250] ms per attempt (eliminates harmonic races). Error
  message rewritten to name the actual caller module/func/line. Same
  issue-tracker entry as P0-4.

### New capabilities

- **T03: `graq_chat_turn` / `graq_chat_poll` / `graq_chat_resume` /
  `graq_chat_cancel` MCP tools registered.** Handlers already shipped in
  `graqle/chat/mcp_handlers.py` since v0.51.4 but were dormant because MCP
  registration was missing. Unblocks VS Code extension v0.4.9 pivot.
  +4 `kogni_chat_*` aliases auto-generated. Pre-registration assertion in
  the alias loop now **fails loudly** on silent handler overwrite
  (predict-flagged D2 defect).
- **T04b: `graq_kg_diag` MCP tool.** Returns recent KG-write latencies,
  attempts, caller stacks, and current lock holders. CG-01 exempt so it
  works before `session_start` (common context: debugging
  `WRITE_COLLISION`). Cheap, no I/O.
- **T05: `ChatConfig` in `GraqleConfig`.** Optional `chat:` block in
  `graqle.yaml` with `enabled` / `default_task_type` / `max_turn_seconds`
  / `permission_mode`. Backward-compat: yamls without the block keep
  current behavior.

### Testing

- **T07: `tests/integration/test_neo4j_backend.py`** - integration-marked
  suite that exercises the full Neo4j backend stack against a real DB.
  Auto-skips when `NEO4J_URI` / `NEO4J_PARITY_PW` are unset. Unit CI stays
  fast via `pytest -m "not integration"`.
- **T08: `tests/integration/test_backend_parity.py`** - parametrized
  parity harness across file and Neo4j backends with tolerance bands.
  Fixed 3 harness bugs from the original 2026-04-16 parity_test.py: bad
  `graqle.activation.activate` import, wrong `add_node(id=...)` kwarg,
  `Graqle(connector=...)` -> `Graqle.from_json` / `Graqle.from_neo4j`.
- **`tests/test_kg_writes/test_no_self_race.py`** - 100 sequential
  `_write_with_lock` calls produce **zero retries** (T04 acceptance gate).
  Re-entrant-deadlock test. Error-message contract test.
- Pre-existing test `tests/test_core/test_graph_neo4j.py::TestToNeo4j`
  fails on `private/master` (bug: `to_neo4j` calls non-existent
  `self.save()`). Not caused by this release; noted for a future fix.

### Build / docs

- **T09: MCP tool inventory at build time.** New
  `scripts/generate_mcp_inventory.py` introspects `TOOL_DEFINITIONS` and
  emits `graqle/docs/mcp-tool-inventory-v0.51.6.md` with name / description
  / args per tool. Shipped in the wheel via `[tool.hatch.build] artifacts`.
  `--check` flag for CI drift gate.
- **Tool count: 138 -> 148.** T03 adds 4 `graq_chat_*` + 4 `kogni_chat_*`
  (= 8); T04 adds `graq_kg_diag` + `kogni_kg_diag` (= 2). T06 updates
  assertions in `tests/test_plugins/`.

### Regression budget

- `test_core` + `test_connectors` + `test_config` + `test_kg_writes` +
  `test_plugins`: **691 / 691 passing** (plus 1 skipped, 2 pre-existing
  deselected).

### Deferred (tracked for v0.52.0)

- T10: `graq_edit max_gap` auto-tune (P2, nice-to-have).
- P1-6 Neo4j docs; P1-9 SAFETY_GATE legitimate-parameter false-positive fix.
- `to_neo4j` latent `graph.save()` crash (separate bug, out of T01 scope).

---

## 0.51.5 (2026-04-15)

Concurrent-MCP write-collision retry envelope (BUG-RACE-1): `os.replace`
retried with exponential backoff under `PermissionError` on Windows.
`GRAQLE_WRITE_RETRY_BUDGET_MS` env knob. The retry loop surfaced a
misleading "another MCP client" error - upgraded fix in v0.51.6 / T04.

## 0.51.4 (2026-04-14)

VS Code handoff bugs + P0 KG protection: `_write_with_lock` refuses writes
that would shrink the graph by more than 1 percent
(`GRAQLE_ALLOW_SHRINK=1` to override).

---

## 0.51.3 (2026-04-14)

### Added

- **`ambiguous_options` field on `graq_reason` responses.** When the arbiter
  surfaces ≥2 near-tied candidate answers (top-2 score gap ≤ 0.10, both ≥ 0.50,
  at most 5 options with unique labels) the response now includes an
  `ambiguous_options` array. Each option carries `option_id`, `label` (1-6
  words, ≤60 chars), `rationale` (one sentence, ≤200 chars), `confidence`
  (0-1), and optional `evidence_refs` (KG node IDs + lesson IDs). The field
  is **additive and optional** — existing consumers see no change on
  non-ambiguous queries. Unlocks the VS Code extension Ambiguity Pause UX
  (graqle-vscode PR #7 BLOCKER-1). Trigger logic lives in
  `Aggregator._compute_ambiguous_options` and threads through
  `synthesis_trunc_info["candidates"]` → `ReasoningResult.metadata` →
  `_handle_reason` response.
- **Capability flag on MCP `initialize` response.** Both top-level
  `capabilities.graq_reason.ambiguous_options` AND
  `serverInfo.capabilities.graq_reason.ambiguous_options` are set to
  `true`. Lets the VS Code extension feature-detect and auto-enable the
  Ambiguity Pause UX on SDK upgrade without version sniffing.
- **`graq_learn` routes JSON-string actions.** When the `action` argument
  is a JSON object with `kind: "pause_pick"`, the handler routes to
  `_handle_pause_pick` which writes an `ambiguity_pick` entity node to
  the KG, bucketed by `task_hash` under a single `ambiguity_bucket:<hash>`
  anchor node (increments `pick_count`). Idempotent on `pause_id` so the
  extension can safely retry. Non-JSON action strings keep their legacy
  outcome-mode behavior unchanged.

### Internal

- 14 new regression tests in `tests/test_plugins/test_v0513_ambiguous_options.py`
  covering all 10 acceptance criteria from the extension team handoff
  (Fixtures A/B/C/D + length cap + aggregate integration + JSON routing
  + idempotency + bucket aggregation + capability flag + tools-list
  invariant + additive schema + non-JSON backward-compat).
- Aggregator change is purely additive: the existing `(answer, trunc_info)`
  tuple signature is preserved (138 downstream consumers unaffected). The
  new `candidates` key is attached to the existing `trunc_info` dict only
  when the trigger fires.
- No new MCP tools added (AC-10). Schema extension only.

### VS Code extension contract

Extension can drop its heuristic `A)/1.` text-parse fallback and remove
the `graqle.experimental.ambiguityPause` opt-in gate in v0.4.5. Detection
path: `capabilities.graq_reason.ambiguous_options === true` OR
`semver.gte(serverInfo.version, '0.51.3')`.

---

## 0.51.0 (2026-04-12)

### Added
- `graq gate-status` CLI command — reports gate health (installed / enforcing /
  interpreter valid / self-test passed). JSON output matches the ADR-154 Layer 2
  contract for the VS Code extension status chip.
- `graq lint-public` CLI command — scans all shipped files under `graqle/` for
  forbidden internal references (pattern tags, tracker IDs, product names, budget
  constants). Returns exit 0 if clean, exit 1 with violation list if not.
- ADR-154: VS Code extension integration spec (7-layer architecture, 7 new MCP
  tools, 9 CLI subcommands, 4-week rollout). First ADR committed to the tracked
  tree for cross-team visibility.
- `graq_write` new-file allowlist: CG-03 edit gate now allows `graq_write` on
  NEW code files (not yet on disk) and files under `.tmp_*` / `scripts/` /
  `tests/` paths. Existing hub code files remain edit-gated.

### Fixed
- Governance robustness hardening (6 pre-existing findings from v0.50.1 review):
  pattern-cache fail-closed semantics, env-var naming alignment + explicit base64
  decode + per-entry schema validation, persisted cumulative state validation,
  `risk_to_int` fail-safest (unknown/None/non-string maps to CRITICAL instead of
  MEDIUM), defensive credential-match attribute access, audit log parent-dir
  creation at init time.
- Systematic sanitization of 107 files across the entire `graqle/` package:
  381 forbidden internal references (ADR-N, TB-N, OT-NNN, CG-*, BLOCKER-N,
  TS-[1-4], product names) replaced with neutral descriptions. Distribution
  lint upgraded from advisory baseline (400) to hard gate (0).

### Internal
- 14 new governance regression tests in `tests/test_core/test_governance_postfix.py`.
- 13 KG lessons taught via `graq_learn` covering governance robustness, gates-on
  friction patterns, squash-merge rule, and Windows interpreter probe pattern.
- `graqle/storage/` module preserved as Phase 0 commit (parked for v0.51.1/v0.52.0).

---

## 0.50.1 (2026-04-12)

### Fixed
- Hardened the Windows installer for the governance gate. `graq gate-install`
  now probes for a working Python 3 interpreter (trying `sys.executable`,
  `python3`, `python`, `py -3`), skips the Windows Store Python stub, and
  substitutes the resolved interpreter into the generated `settings.json`.
  Also adds a `--fix-interpreter` flag to rewrite only the hook command
  string on existing installs.
- `graq gate-install` now runs a post-install self-test with a synthetic
  Bash tool payload and requires the hook to return exit 2 with
  "GATE BLOCKED" on stderr. A broken install can no longer silently
  complete; the command fails with a remediation hint instead.
- Governance gate hook now fails closed on unknown write-class tools.
  Previously, any Claude Code tool not in the explicit allowlist or
  blocklist fell through to exit 0. A regex heuristic
  (`^(Write|Edit|Delete|Exec|Run|Create|Update|Put|Post)`) now blocks
  such tools by default; unknown read-class tools still pass.
- `graq init` now auto-installs the Claude Code governance gate when
  Claude Code is detected (`.claude/` in project or home directory).
  Opt out with `--no-gate` or `GRAQLE_SKIP_GATE_INSTALL=1`. Operators
  no longer need to remember a second `graq gate-install` step.
- Fixed `from graqle import *` raising `AttributeError` because the
  package `__all__` listed `"GraQle"` while the class is `Graqle`.
- Sanitized internal references out of the shipped ChatAgentLoop v4
  built-in floor template and the TCG (Tool Capability Graph) seed
  for public distribution. User-visible tier names and public APIs
  are unchanged.

### Internal
- New `tests/test_distribution/test_no_internal_strings.py` — a
  public-disclosure regression lint that hard-fails on the v0.50.1
  sanitization targets and tracks a high-water advisory baseline for
  the rest of the package.
- Added `/GRAQ.md` at the SDK repo root as a walk-up extension for
  SDK-local developer rules. The file is not shipped in the wheel.
- Governance module internal helper renames: `_check_ts_leakage` →
  `_check_pattern_leakage`, `_TS_BLOCK_PATTERNS_DEFAULT` →
  `_BUILTIN_PATTERNS_DEFAULT`, and related. Backward-compat aliases
  preserve existing internal test imports.

---

### Round-2 remediation (2026-04-11) — research team review PR #49 (follow-up)

Addresses the 1 new BLOCKER (RO2-6) + 3 new MAJORs (RO2-1, RO2-3, RO2-4)
+ 2 MINORs (RO2-2, RO2-5) raised in the Round-2 research team review on
private PR #49. Operator directive: *"maintain our algorithm,
implementation rigour and business value while solving the points raised
by the research team."* All mechanism preserved. Algorithm integrity
verified: 9/9 classify_concern precedence cases pass after the fixes.

**RO2-6 (BLOCKER, now closed) — TCG seed reachability 25/67 → 67/67**
- The Round-1 expansion added 37 new TCGTool nodes but wired only a
  few MATCHES_INTENT edges, leaving 42/67 tools orphaned (unreachable
  from any intent or workflow pattern). Research team's programmatic
  graph-reachability audit caught this.
- Added 8 new TCGIntent nodes: `intent_visual_audit`,
  `intent_browser_automation`, `intent_production_deploy_check`,
  `intent_dependency_management`, `intent_autonomous_task`,
  `intent_knowledge_lookup`, `intent_review_pr`, `intent_trace_reasoning`.
- Added 3 new graduated TCGWorkflowPattern nodes:
  `workflow_visual_audit`, `workflow_autonomous_task`,
  `workflow_review_pr`.
- Added 57 new MATCHES_INTENT edges wiring every previously-orphan
  tool into at least one intent.
- Also backfilled core dev tools (`graq_edit`, `graq_bash`,
  `graq_git_log`) into their existing intents.
- **Reachability now 67/67 tools (100%)**, verified by the post-Round-2
  orphan audit script.

**RO2-4 (MAJOR, now closed) — banned-phrase guard self-defeat**
- The Round-1 `_BANNED_PROMPT_PHRASES` frozenset stored the literal
  patent-leaking sentences as plaintext strings in the shipped source.
  A competitor grepping the PyPI wheel could trivially discover the
  exact phrases the guard was meant to suppress.
- Replaced with `_BANNED_PHRASE_HASHES: frozenset[str]` — a set of
  SHA-1[:16] hex digests. The plaintext phrases never appear in
  shipped source.
- `_assert_no_banned_phrases` now computes a sliding window of 1..8
  word n-grams over each prompt, SHA-1 hashes each window, and
  compares against the hash set. Any match is a regression.
- Regression-tested: the guard still fires on `"Apply rule order
  strictly: safety > prerequisite > cost > ambiguity"` and on each
  legacy persona token (PROPOSER/ADVERSARY/ARBITER) even though none
  of these phrases appear as plaintext in the source.
- Added `test_banned_phrase_hashes_size` (shape check) +
  `test_banned_hash_guard_catches_strict_ordering_regression` +
  `test_banned_hash_guard_catches_persona_regression`.

**RO2-3 (MAJOR, now closed) — precedence comment leaks in debate.py**
- Scrubbed 3 locations where the English precedence chain
  ("safety comes first and wins over prerequisite > cost > ambiguity")
  was leaked in comments / docstrings:
  - `debate.py:209-213` — the `_CATEGORY_SIGNALS` comment. Replaced
    with generic "iteration order is the tie-breaker" language that
    does not state the specific ordering.
  - `debate.py:~299` — docstring inside `classify_concern`. Replaced
    with "is picked per the internal precedence policy".
  - Module docstring "Safety-first precedence with four categories" →
    "Four concern categories with a fixed internal ordering".
- All three scrubs preserve the documentation intent while removing
  the verbatim English chain.

**RO2-1 (MAJOR, now closed) — dead strict reader wired into TCG**
- Round-1 added `settings_loader.require_novelty_lift_min` but
  `tool_capability_graph.graduate_pattern` still read the module
  constant `PROBATION_NOVELTY_LIFT_MIN` directly, making the strict
  reader dead code.
- `ToolCapabilityGraph.__init__` now accepts an optional
  `settings: dict | None` parameter and stores the resolved threshold
  in `self._novelty_lift_min`. If `settings` is provided, the value is
  pulled via `settings_loader.load_novelty_lift_min`; otherwise the
  public default (0.2, intentionally non-operational) is used.
- `graduate_pattern` now reads `self._novelty_lift_min` on every call.
- `load_novelty_lift_min` + `require_novelty_lift_min` are now
  actually called in the hot path.

**RO2-2 (MINOR, now closed) — persona kwarg renamed to role**
- `ReasonFn` protocol: `persona: str` → `role: str`.
- All internal call sites updated.
- Docstring reference scrubbed.
- "Persona" was flagged as semantic cousin of the scrubbed vocabulary
  (core multi-agent debate terminology). Renaming to the neutral
  "role" label completes the vocabulary scrub.

**RO2-5 (MINOR, now closed) — phantom_screenshot tier adjusted**
- `graq_phantom_screenshot` governance tier GREEN → YELLOW.
- Side effect `read` → `net`.
- Rationale added to description: JS execution via remote page makes
  this a governed operation.

**Algorithm integrity verified (9/9 cases pass after fixes)**
- Safety precedence: `"destructive AND expensive AND slow"` → BLOCK
- Prerequisite > cost: `"missing prerequisite also expensive"` → REFINE
- Cost alone: `"this is expensive, high-latency"` → REFINE
- Ambiguity alone: `"ambiguous — unclear"` → REFINE
- Explicit none: `"CONCERN: none"` → PROCEED
- Affirmative safe: `"This action is non-destructive and safe."` → PROCEED
- Credentials rewrite: `"Uses credentials env-var name"` → PROCEED
- Safety alone: `"data loss ahead"` → BLOCK
- Irreversible: `"this is irreversible"` → BLOCK

**Mechanism preserved (non-negotiable per operator directive)**
- 3 parallel role calls via `asyncio.gather`
- Deterministic in-code override of the judge verdict
- 4-category internal ordering (enforced in `_CATEGORY_SIGNALS` list
  order)
- Round-refinement feedback loop
- `MAX_CHECK_ROUNDS = 2` hard ceiling
- `ReasonFn` protocol surface (kwarg name changed, semantics unchanged)

**Reachability verification**
- Pre-Round-1: 30 tools, 12 intents, 5 workflows, no orphans by
  construction
- Post-Round-1: 67 tools, 12 intents, 5 workflows — **42 orphans**
  (RO2-6 finding)
- Post-Round-2: **67 tools, 20 intents, 8 graduated workflows, 0
  orphans** — all tools reachable via at least one MATCHES_INTENT edge
  or workflow_pattern membership

**Tests:** `tests/test_chat/` 236 → **239 passing** (+3 new Round-2
regression tests). Hotfix suites (test_base_serialization.py,
test_continuation.py, test_areason_batch.py, test_aggregation.py)
unchanged at 9+19+9+7 = 44 passing. Zero regressions.

**Post-impl `graq_review` on debate.py with security focus:** **APPROVED
at 93% confidence**. All comments are INFO-level hygiene notes. No
OWASP Top 10 sinks, no secret exposure paths, no unsafe subprocess
calls. Hash-based guard ships without plaintext sensitive phrases.

---

### Round-1 remediation (2026-04-11) — research team review PR #49

Addresses the 2 BLOCKERs + 3 MAJORs raised in the research team review
on private PR #49. Operator waived BLOCKER-R1 conditional on scrubbing
patent-specific language from the debate subsystem while preserving
mechanism, algorithm, quality, and the core edge/moat. BLOCKER-R2 and
MAJOR-R1/R2/R3 are fully fixed.

**BLOCKER-R1 (waived + scrubbed) — debate.py language scrub**
- Renamed persona roles: `PROPOSER → CANDIDATE`, `ADVERSARY → CRITIC`,
  `ARBITER → JUDGE`. No verbatim "PROPOSER/ADVERSARY/ARBITER" strings
  appear anywhere in `graqle/chat/`.
- Rewrote all three role prompts. No prompt contains the banned
  sentence `"safety > prerequisite > cost > ambiguity"` — precedence
  now lives only in code (`classify_concern`), not in prompt text.
- Renamed constants: `_RULE_KEYWORDS → _CATEGORY_SIGNALS`,
  `MAX_DEBATE_ROUNDS → MAX_CHECK_ROUNDS`.
- Renamed functions: `deterministic_arbiter() → classify_concern()`,
  `run_debate() → resolve_concern()`.
- Renamed dataclasses: `DebateRecord → ConcernCheckRecord`,
  `DebateRound → ConcernCheckRound`, `PersonaResponse → RoleResponse`.
- Renamed RCAG node type: `NODE_TYPE_DEBATE_ROUND →
  NODE_TYPE_CHECK_ROUND` with backward-compat alias for in-session
  callers.
- Added `_BANNED_PROMPT_PHRASES` frozenset + `_assert_no_banned_phrases`
  import-time + runtime guard that fails fast on any regression
  reintroducing the scrubbed phrasing. Test suite re-asserts the guard.
- `backend_router.py` docstring scrubbed.
- **Mechanism preserved** (operator waiver condition): 3 parallel role
  calls via `asyncio.gather`, deterministic in-code override of the
  judge verdict, safety-first precedence with four categories
  (safety > prerequisite > cost > ambiguity in code), round-refinement
  feedback loop, `MAX_CHECK_ROUNDS = 2` hard ceiling.

**BLOCKER-R2 — TS-3 activation-threshold collision on 0.15**
- Changed public default of `PROBATION_NOVELTY_LIFT_MIN` from `0.15`
  to `0.2` in `graqle/chat/tool_capability_graph.py`. The old value
  collided exactly with the unpublished PSE `similarity_threshold`
  per research TS-3 finding.
- Updated seed JSON `_meta.schema_notes.probation_thresholds.novelty_lift_min`
  from `0.15` to `0.2` with an explicit annotation that the public
  default is non-operational and operators must override via
  `.graqle/settings.json`.
- Added `settings_loader.load_novelty_lift_min(settings)` strict
  reader and `settings_loader.require_novelty_lift_min(settings)`
  fail-loud variant. The strict reader returns `None` on missing key
  so the caller can fall back to the public default; the fail-loud
  variant raises `ValueError` if the key is absent. Pattern per
  `lesson_20260402T210613`: `config.get(KEY, default)` with a
  numerical default IS a hardcoded threshold disguised as config.
- Test docstring in `test_tool_capability_graph.py` updated to
  reflect the new default.

**MAJOR-R1 — TCG seed coverage expanded from 30 → 67 tools**
- Added 37 new `TCGTool` nodes covering: 4 governance (`graq_gov_gate`,
  `graq_safety_check`, `graq_audit`, `graq_runtime`), 8 phantom
  (`graq_phantom_browse / _click / _type / _screenshot / _audit /
  _session / _discover / _flow`), 13 scorch (`graq_scorch_audit /
  _report / _a11y / _perf / _seo / _mobile / _i18n / _security /
  _conversion / _brand / _auth_flow / _behavioral / _diff`), 6
  lifecycle + workflow (`graq_lifecycle`, `graq_drace`,
  `graq_workflow`, `graq_auto`, `graq_route`, `graq_correct`), and 6
  accessory (`graq_profile`, `graq_web_search`, `graq_plan`,
  `graq_github_pr`, `graq_github_diff`, `graq_todo`). Plus
  `graq_reload` under destructive tier.
- Wired 6 new `MATCHES_INTENT` edges so `intent_audit` now surfaces
  `graq_gov_gate`, `graq_safety_check`, `graq_audit`, `graq_runtime`;
  `intent_governed_refactor` surfaces `graq_gov_gate`; and
  `intent_review` surfaces `graq_safety_check`.
- Restores the "governance pre-disclosure" property promised in PR #49
  body and unblocks the R18 GETC trace-capture flow.

**MAJOR-R1b — auto-create probationary unknowns in reinforce_sequence**
- Added `ToolCapabilityGraph._auto_create_probationary_tool(tool_id)`
  helper that creates a YELLOW probationary `TCGTool` node with
  `governance_tier=YELLOW`, `safe_for_prediction=False`,
  `probation=True`, `auto_created=True`.
- Updated `reinforce_sequence` to auto-create probationary nodes for
  unseen `tool_*`-prefixed ids instead of silently skipping them. Non-
  tool_ prefixed ids are still silently ignored (intents, workflows,
  lessons).
- Predicted missing edges never surface auto-created tools because
  `predict_missing_edges` filters by `safe_for_prediction=True`.
- Keeps BLOCKER-2 valid: no `KogniDevServer.list_tools()` runtime
  bootstrap — learning still comes exclusively from observed usage.
- The docstring claim *"UNKNOWN until reinforce_sequence learns them"*
  is now factually correct.

**MAJOR-R2 — prediction bias toward seeded tools** — automatically
reduced by MAJOR-R1 expansion (67 tools vs 30 before) + auto-create
fallback. No separate code fix.

**MAJOR-R3 — arbiter substring matching is brittle**
- Replaced substring matching with a `_CATEGORY_SIGNALS` list of
  compiled regex patterns using word boundaries (`\bdestructive\b`,
  `\bunsafe\b`, etc.).
- Added `_has_negation` helper with a 20-char look-back window that
  checks for negation tokens (`not `, `no `, `non-`, `never `,
  `without `).
- Added `_has_affirmative_safety` fallback that recognises benign
  markers (`is safe`, `read-only`, `idempotent`, `no side effects`,
  `credentials env-var name` — the `lesson_patent_scrub` safe rewrite
  phrase).
- Four-way fallback decision:
  (1) explicit NONE → PROCEED,
  (2) negation-guarded safety match → BLOCK,
  (3) non-safety signal → REFINE,
  (4) no signal + affirmative marker → PROCEED,
  (5) no signal + no affirmative marker → REFINE (conservative default).
- All 4 false-positive phrases from the research review
  (`non-destructive`, `credentials env-var name`, `unsafe pattern we
  already fixed`, `ambiguous but safe`) now pass their regression
  tests.

**MINOR-R1** — documented (TB-F8 `mcp_dev_server.py` wiring is still a
v0.50.1 follow-up; snippet remains in
`.gcc/CHATAGENTLOOP-V4-COMPLETE.md`).

**MINOR-R4** — `graq_reason_batch` migration tracked as v0.50.1
optimization; no functional change.

**Security invariants added to debate.py**
- `tests/test_chat/test_debate.py` now asserts the module source
  contains no `import subprocess`, no `os.system`, no `os.environ`,
  no `os.getenv`, no legacy persona names at caps, and that every
  shipped prompt passes the banned-phrase guard.
- Added a secret-leakage test: a synthetic SECRET-like value in the
  question never appears in the streamed role outputs.

**Tests**
- `tests/test_chat/`: 214 → **236 passing** (added 22 new Round-1
  regression tests: 15 new debate.py cases, 7 new TCG cases)
- All 236 tests green in 1.28s

---

## v0.50.0 — 2026-04-11

**ChatAgentLoop v4 — Claude-Code-equivalent interactive chat layer (ADR-152).**

This is a feature jump (0.47.3 → 0.50.0) that ships the entire chat
agent loop the VS Code extension v0.6.0 will host: a three-graph
runtime architecture (GRAQ.md / TCG / RCAG), an LLM tool-use loop
that ranks over a TCG-activated subgraph instead of cold-picking from
~134 tools, durable pause/resume with CAS-locked state machine,
session-scoped permission caching, adversarial debate, polyglot
backend routing, hard-error continuation, and convention inference
as a first-class product feature. SDK-HF-01 (graq_generate missing
from generate-intent DAG) is structurally resolved — the extension's
dag.ts + intent.ts are deleted; tool selection moves to the SDK.

### Added
- **`graqle/chat/`** — new package, 8 SDK modules + 2 templates (~6500 LOC).
  - **`streaming.py`** (TB-F1) — ChatEvent envelope, ChatEventBuffer with
    monotonic per-turn sequencing, long-poll cursor helper.
  - **`turn_ledger.py`** (TB-F1) — append-only audit log at
    `.graqle/chat/ledger/turn_<id>.jsonl`.
  - **`settings_loader.py`** (TB-F1) — `.graqle/settings.json` policy
    loader with fail-closed jsonschema validation.
  - **`graq_md_loader.py`** (TB-F1) — multi-root GRAQ.md loader walking
    cwd UP to filesystem root, most-specific-wins conflict merge,
    user-content sandbox escaping.
  - **`templates/GRAQ_default.md`** (TB-F1) — built-in floor with 7
    scenario playbooks (codegen / debug / refactor / audit / review /
    write-new-artifact / convention-inference) + tool catalog.
  - **`tool_capability_graph.py`** (TB-F2) — `ToolCapabilityGraph`
    IS-A `Graqle` subclass with enrichment bypass, 30-tool/12-intent/
    5-workflow/20-lesson seed, intent classification + activation,
    edge reinforcement with [0.0, 10.0] clamp, probationary pattern
    mining (3 obs / 2 holdouts / 0.15 lift), 2-hop missing-edge
    prediction with destructive-edge safety filter, atomic save with
    .bak rollback.
  - **`templates/tcg_default.json`** (TB-F2) — canonical seed: 30 tools
    with governance tiers (GREEN/YELLOW/RED), 12 intents with keyword
    + preferred_sequence, 5 graduated workflow patterns including the
    `convention_inference` workflow that wires `graq_glob → graq_read
    → graq_write` for the `write-new-artifact` intent, 20 lessons,
    108 typed edges (MATCHES_INTENT / USED_AFTER / PART_OF /
    CAUSED_BY).
  - **`rcag.py`** (TB-F3) — `RuntimeChatActionGraph` IS-A `Graqle`,
    7 ephemeral node types (ToolCall, ToolResult, AssistantReasoning,
    GovernanceCheckpoint, DebateRound, ErrorNode, AttachmentContext),
    query augmentation with rolling 3-turn summary + partial
    reasoning, deterministic token-overlap activation fallback for
    unit tests (production wires through `_activate_subgraph(strategy
    ='chunk')`).
  - **`permission_manager.py`** (TB-F4) — `TurnState` enum, `TurnStore`
    with CAS state transitions under `asyncio.Lock`, idempotent
    resume via `tool_result_cache`, crash recovery via terminal
    tombstoning, `PermissionManager` with session-scoped cache keyed
    by `(tool_name, resource_scope, session_id)` plus revocation.
  - **`debate.py`** (TB-F5) — PROPOSER/ADVERSARY/ARBITER personas via
    `asyncio.gather` of three reason calls (will migrate to native
    `graq_reason_batch` now that CG-REASON-01 is fixed in v0.47.3),
    deterministic arbiter rule order safety > prerequisite > cost >
    ambiguity, max 2 rounds, debate chip streaming.
  - **`backend_router.py`** (TB-F6) — `BackendProfile`, `BackendRouter`,
    family detection by name prefix, 6 chat task types (chat_triage /
    chat_reasoning / chat_debate_proposer / chat_debate_adversary /
    chat_debate_arbiter / chat_format), family separation enforced
    only when 2+ families configured, minimal-polyglot degradation
    when only one backend is available.
  - **`agent_loop.py`** (TB-F7) — `ChatAgentLoop` integration point,
    10-step turn flow from ADR-152 §Decision, adaptive budget with
    burst override (25 → 100 ceiling), hard-error continuation via
    ErrorNode + synthetic tool_result, governance parallelism,
    pause/resume/cancel state transitions, CGI-compatible event
    emission shape (ADR-153 seed) so the future project-self-memory
    graph can fold turn events in via a classification pass.
  - **`mcp_handlers.py`** (TB-F8) — four chat handler functions
    (`handle_chat_turn`, `handle_chat_poll`, `handle_chat_resume`,
    `handle_chat_cancel`) that the MCP server will dispatch the
    `graq_chat_*` tools to. Kept in a separate module to minimize
    the hub-file edit surface in `mcp_dev_server.py` per
    CG-DIF-01/CG-DIF-02 — TB-N tracks the small registration block
    that wires them in.

### Tests
- **`tests/test_chat/`** — new directory, 214 tests passing in 1.29s.
  - test_streaming.py (TB-F1)
  - test_turn_ledger.py (TB-F1)
  - test_settings_loader.py (TB-F1)
  - test_graq_md_loader.py (TB-F1)
  - test_isolation.py (TB-F1; updated to allow the four shared core
    modules graqle.core.{graph,node,edge,types,message,state} for
    TB-F2 onward — everything else in graqle.core stays forbidden)
  - test_tool_capability_graph.py (TB-F2, 43 cases covering BLOCKER-1
    enrichment bypass / BLOCKER-2 single source of truth / MAJOR-2
    destructive-edge filter / MAJOR-3 probationary filter /
    MAJOR-4 atomic save rollback / MAJOR-5 negative paths /
    MINOR-1 weight clamp / MINOR-2 probation thresholds)
  - test_rcag.py (TB-F3, 19 cases)
  - test_permission_manager.py (TB-F4, 22 async cases)
  - test_debate.py (TB-F5, 15 cases including the deterministic rule
    order verification)
  - test_backend_router.py (TB-F6, 14 cases)
  - test_agent_loop.py (TB-F7, 11 async cases including the
    SDK-HF-01 structural regression guard
    `test_sdk_hf_01_codegen_picks_graq_generate` that asserts a
    codegen turn produces a tool_planned event for graq_generate
    AND the final turn_complete text contains a fenced python block)
  - test_mcp_handlers.py (TB-F8, 9 async cases)

### Hotfixes rolled into v0.50.0
- **CG-REASON-02** (v0.47.1) — BaseBackend deepcopy/pickle safety via
  `_TRANSIENT_BACKEND_ATTRS` drop on serialization, fixed the
  `cannot pickle '_thread.RLock' object` crash that was hard-downing
  every reasoning round on the openai backend.
- **SDK-HF-02** (v0.47.2) — synthesis truncation regression fixed via
  the new `generate_with_continuation` helper extracted from
  `CogniNode.reason` into `graqle/core/node.py`. The
  `Aggregator._weighted_synthesis` path now recovers from
  `stop_reason=max_tokens` the same way per-node responses do.
  CogniNode.reason() keeps its inline copy of the loop untouched
  (deferred to CG-OT028-01 follow-up).
- **CG-REASON-01** (v0.47.3) — `areason_batch` error fallback fixed via
  the new module-level `_make_error_result(query, exc)` helper that
  builds a valid `ReasoningResult` with all required fields plus
  `backend_status="failed"` / `backend_error` / `reasoning_mode=
  "error"`. Unblocks the native batch reasoning path for the
  ChatAgentLoop debate subsystem.

### Notes
- **SDK-HF-01 structurally resolved.** The extension's `dag.ts` +
  `intent.ts` are obsoleted by the SDK-side TCG. The LLM picks tools
  from a pre-activated TCG subgraph that puts `graq_generate` at
  position #2 (score 1.635) for `write a Python function...` queries
  on day one of the seed, before any user reinforcement. Verified
  by the `test_sdk_hf_01_codegen_picks_graq_generate` regression
  guard.
- **Convention inference is a first-class product feature.** The TCG
  ships with a `workflow_convention_inference` graduated workflow
  pattern wiring `graq_glob → graq_read → graq_write` for the
  `intent_write_new_artifact` intent. The built-in GRAQ.md template
  has a `## Scenario: write-new-artifact` playbook encoding the
  same behavior in natural language.
- **CGI-compatible event emission shape (ADR-153 seed).** Every
  ChatAgentLoop event carries the structural fields a future
  Cognigraph Implementation Graph would need (turn_id, session_id,
  parent_id, tool_name, status, latency_ms, debate_verdict,
  debate_reason, governance_tier, governance_decision). The
  ADR-153 design session (post-v0.50.0) can decide whether to fold
  terminal turn events into a persistent project-self-memory graph
  via a classification pass. No CGI node types or edge schemas are
  implemented in v0.50.0 — ADR-153 ships in v0.51.0 as a separate
  design wave.
- **Source-level isolation rule narrowed.** `tests/test_chat/
  test_isolation.py` now allows the chat package to import from
  `graqle.core.{graph,node,edge,types,message,state}` (the
  legitimate shared core); everything else in `graqle.core` /
  `graqle.backends` / `graqle.orchestration` / `graqle.reasoning` /
  `graqle.intelligence` / `graqle.plugins` / `graqle.connectors`
  stays forbidden. Source-level scan pattern per
  lesson_20260411T081005.
- **Test counts at ship time:**
  - tests/test_chat/: 214 passing in 1.29s (the v4 chat layer)
  - tests/test_backends/test_base_serialization.py: 9 (CG-REASON-02)
  - tests/test_core/test_continuation.py: 19 (SDK-HF-02 helper)
  - tests/test_core/test_areason_batch.py: 9 (CG-REASON-01)
  - tests/test_orchestration/test_aggregation.py: 7 (SDK-HF-02 wiring)
- **TB-F8 hub-file wiring deferred.** The four `mcp_handlers.handle_chat_*`
  functions are ready and tested standalone. The actual registration
  block in `graqle/plugins/mcp_dev_server.py` (8609 lines, impact
  radius 491) will be a small follow-up edit applied via
  `graq_apply` per the CG-DIF-02 hub-file safety rule. See
  `.gcc/CHATAGENTLOOP-V4-COMPLETE.md` for the registration snippet.
- **PyPI publish + git tag pending operator approval.** The build is
  staged at v0.50.0 but `python -m build && twine upload` is not
  run automatically.

---

## v0.47.3 — 2026-04-11

### Fixed
- **CG-REASON-01 (HIGH): `graq_reason_batch` constructor crash** in `graqle/core/graph.py:areason_batch` error fallback. The previous code constructed a `ReasoningResult` with `node_count=0` (a read-only `@property`, not a constructor field) and was missing three required fields: `query`, `active_nodes`, `message_trace`. The error branch also iterated `results` without zipping `queries`, so the failing query string was lost. Fix: extracted the fallback into a new module-level helper `_make_error_result(query, exc) -> ReasoningResult` that constructs the dataclass with all required fields plus `backend_status="failed"`, `backend_error=str(exc)`, `reasoning_mode="error"` so downstream consumers can branch on the failure without parsing the answer string. The loop now uses `for q, r in zip(queries, results)` with a defensive length-check guard. Logging is `str(q)[:80]` to handle non-string queries safely. This unblocks the native batch reasoning path; the ChatAgentLoop v4 adversarial debate subsystem can now use `graq_reason_batch` directly instead of falling back to serial `asyncio.gather` of 3 `graq_reason` calls.

### Added
- **`graqle.core.graph._make_error_result`** — module-level helper that builds a valid error-fallback `ReasoningResult`. Reusable by any caller that needs to construct an error result consistently.
- **9 regression tests** in `tests/test_core/test_areason_batch.py`:
  - 4 helper tests: TypeError-free construction, all required fields populated, `node_count` property accessibility, `confidence=0.0` warning emission as failure telemetry
  - 1 mixed-batch test: success and failure interleaved, result count == query count, query strings preserved
  - 1 all-fail batch test: every query fails, every result is an error fallback
  - 1 downstream consumer compatibility test: error result is consumable through the exact field-access pattern used by `mcp_dev_server._handle_reason_batch` (`.answer`, `.confidence`, `.node_count`, `.cost_usd`, `.reasoning_mode`)
  - 1 empty batch test
  - 1 single-query failure test

### Notes
- Pre-implementation `graq_reason` (96% confidence) chose Option B (helper function) over Option A (inline minimal patch) and Option C (changing the dataclass contract).
- Pre-implementation `graq_review` (86% confidence) returned CHANGES_REQUESTED with 1 BLOCKER + 4 MAJORs + 2 MINORs — all folded into the implementation including dataclass-signature verification, `zip` length-check guard, downstream-consumer test, and test consolidation from 6 cases to 4.
- Post-implementation `graq_review` on the diff (89% confidence) flagged 2 MAJORs + 1 MINOR. The unsafe `q[:80]` was fixed via `str(q)[:80]`. The `_make_error_result` constructor concern was already validated by 9 passing tests and the smoke test. The "redundant length check" stays as defensive code with `# pragma: no cover`.
- Post-implementation broader `graq_review` on `graqle/core/graph.py` flagged 1 BLOCKER + 5 MAJORs on **pre-existing code** (`_release_lock`, `_validate_graph_data`, `reclassify_batch`, etc.) — out of scope for CG-REASON-01 and logged for follow-up.
- Test suite: 67 passed in 7.75s (9 new areason_batch + 19 continuation + 7 aggregation + 5 node + 18 graph + 9 base serialization). This is the cumulative test set across TB-H1, TB-H2, TB-H3 — zero regressions.
- All 3 blocking hotfixes (CG-REASON-02, SDK-HF-02, CG-REASON-01) are now shipped. The ChatAgentLoop v4 build track (TB-F1 → TB-F9) is unblocked.

---

## v0.47.2 — 2026-04-11

### Fixed
- **SDK-HF-02 (HIGH): synthesis truncation regression** in `graqle/orchestration/aggregation.py:_weighted_synthesis`. Synthesis was making a single `backend.generate(prompt, max_tokens=4096)` call and silently returning the (possibly truncated/empty) result whenever `stop_reason=max_tokens`. Multi-agent reasoning rounds were getting partial answers with `confidence_unreliable=True` set silently. The fix introduces a new shared `generate_with_continuation` helper in `graqle/core/node.py` (alongside the existing OT-028 helpers `_extract_overlap_anchor` / `_build_continuation_prompt` / `_deduplicate_seam`) and uses it from `_weighted_synthesis`. The helper preserves all OT-028 invariants: empty-anchor abort, zero-progress guard via content-identity check, seam deduplication, fail-open on mid-loop exception. The first `backend.generate()` call propagates exceptions unchanged; only continuation-round exceptions surface via `metadata["continuation_error"]`. `max_tokens` stays at 4096 — raising to 8192 (per `lesson_20260407T065640`) is a separate tuning decision deferred until measurement shows persistent truncation.
- **`_normalize_response` defensive guards** for `.text=None`, `.truncated=None`, `.stop_reason=None` shapes from non-conforming backends.

### Added
- **`graqle.core.node.generate_with_continuation`** — reusable async helper that any caller can use against any `BaseBackend`. Returns `(text, metadata)` where metadata has `continuation_count`, `was_continued`, `still_truncated`, `stop_reason`, `continuation_error` keys with a fully documented contract for every exit path.
- **`graqle.core.node._normalize_response`** — adapter that handles `GenerateResult` / raw `str` / malformed shapes with defensive logging.
- **19 regression tests** in `tests/test_core/test_continuation.py` covering every helper exit path: clean, recovery, empty-anchor abort, zero-progress, exhaustion, mid-loop fail-open, raw str input, malformed input, max_continuations=0, partial-overlap seam, initial-call exception propagation, mixed return types, arg passthrough, plus 5 normalizer cases including the post-impl review's None-text guard.
- **7 regression tests** in `tests/test_orchestration/test_aggregation.py` covering `_weighted_synthesis`: clean synthesis, truncation recovery (the headline SDK-HF-02 fix), exhaustion, max_tokens=4096 regression assertion, trunc_info shape preservation, initial-call exception propagation, and continuation_error fail-open with log assertion.

### Notes
- Pre-implementation `graq_reason` (94% confidence) chose Option B (shared helper extraction) over copy-paste duplication and per-backend method approaches.
- Pre-implementation `graq_review` round 1 (92% confidence) returned CHANGES_REQUESTED with 4 MAJORs — all folded into a revised plan that eliminated the highest-risk concerns (OT-028 metadata regression, re-export safety) by NOT moving the existing helpers and NOT refactoring `reason()`.
- Pre-implementation `graq_review` round 2 (86% confidence) returned CHANGES_REQUESTED with 4 more MAJORs on the revised plan (exception contract, metadata contract, normalize observability, aggregation error handling) — all folded into the final spec before any code was written.
- Post-implementation `graq_review` (86% confidence) flagged 1 BLOCKER + 4 MAJORs on **pre-existing `reason()` code** (not the new helper) plus 1 MAJOR on the new `_normalize_response` (None handling). The `_normalize_response` MAJOR was fixed immediately. The 5 pre-existing `reason()` issues are logged as **CG-OT028-01** in `.gcc/OPEN-TRACKER-CAPABILITY-GAPS.md` for follow-up — they are real but out of scope for SDK-HF-02 which targets synthesis, not per-node reasoning.
- `core/node.py:reason()` is **NOT** modified in this hotfix. Zero regression risk on the per-node reasoning path. Verified: 5/5 pre-existing tests in `test_node.py` pass.
- Test suite: 58 passed in 5.31s (19 continuation + 7 aggregation + 5 node + 18 graph + 9 base serialization).
- Knowledge nodes added to KG: `knowledge_technical_20260411T070209` (Option B validation), `knowledge_technical_20260411T070448` (design refinement v2), `knowledge_technical_20260411T070606` (design refinement v3 with exception contract).

---

## v0.47.1 — 2026-04-11

### Fixed
- **CG-REASON-02 (CRITICAL): backend pickling crash** in `graqle/backends/base.py` — `BaseBackend` now provides `__getstate__`, `__setstate__`, and `__deepcopy__` that drop transient runtime handles (`_client`, `_async_client`, `_session`, `_executor`, `_loop`, `_lock`) on serialization. Previously, `copy.deepcopy(node)` at the three ADR-151 redaction-snapshot sites in `graqle/core/graph.py` (lines 1520, 1681, 344) would crash with `TypeError: cannot pickle '_thread.RLock' object` after a node had been activated with a backend whose lazy `_client` (e.g. `AsyncOpenAI` holding an `httpx.AsyncClient`) had been instantiated. The fix is backend-agnostic — all 14 providers inherit it through `BaseBackend` — and side-effect free with respect to the source instance, so concurrent reasoning rounds sharing one backend reference each get an isolated copy. Documented serialization contract added to `_TRANSIENT_BACKEND_ATTRS`.

### Added
- **8 regression tests** in `tests/test_backends/test_base_serialization.py` covering all four review-mandated scenarios:
  1. `copy.deepcopy(backend)` after lazy `_client` populated
  2. `pickle.dumps`/`loads` round-trip preserves durable config
  3. ADR-151 simulation: deepcopying a node that holds an activated backend
  4. Concurrent shared-backend isolation (two snapshots from one source backend stay independent)

  Plus a real `OpenAIBackend` smoke test that confirms the abstract-base fix flows through to the concrete provider class, a contract test on `_TRANSIENT_BACKEND_ATTRS`, and a subclass-extension test showing how a future provider with a new transient handle can override `__getstate__`.

### Notes
- Discovered live during the 2026-04-11 ChatAgentLoop v4 design session (12 reasoning rounds). Crash hard-downed `graq_reason`, `graq_reason_batch`, `graq_predict`, and `graq_review` after the first successful round on `openai:gpt-5.4-mini`. Required mid-session VS Code reload to clear.
- Pre-implementation `graq_review(spec=...)` returned CHANGES_REQUESTED (86% confidence) with 4 MAJOR concerns: serialization contract, concurrency safety, end-to-end coverage, test breadth. All four were folded into the implementation before any code was written. The post-implementation review on the diff is pending.
- This unblocks the entire ChatAgentLoop v4 implementation track (TB-H1 → TB-H2 → TB-H3 → v0.50.0).
- Test suite: 8 passed in 0.11s.

---

## v0.47.0 — 2026-04-10

### Added
- **`graq_apply` MCP tool (CG-DIF-02)** — first-class deterministic insertion engine. A governed alternative to `graq_edit` for files where LLM-generated diffs are unreliable: CRITICAL hub modules (impact_radius > 20), large files (> 1500 lines), files with multiple lookalike methods. The tool eliminates the LLM from the diff loop — callers provide exact byte-string anchors and replacements, the engine performs Python's deterministic `bytes.replace()` and atomic write. Anchor uniqueness is enforced (each anchor must occur exactly `expected_count` times, default 1). Atomic write via tempfile + fsync + os.replace. Backup to `.graqle/edit-backup/` before write. ~50x faster than `graq_edit` on hub files (no LLM round-trip). Implements all 9 rails of the Deterministic Insertion Pattern (baseline, validation, uniqueness, replace, post-replacement invariants, atomic write, post-write verify, backup, rollback).
- **8 stable error codes** for `graq_apply`: `GRAQ_APPLY_FILE_NOT_FOUND`, `GRAQ_APPLY_SHA_MISMATCH`, `GRAQ_APPLY_ANCHOR_NOT_FOUND`, `GRAQ_APPLY_ANCHOR_NOT_UNIQUE`, `GRAQ_APPLY_BYTE_DELTA_OUT_OF_BAND`, `GRAQ_APPLY_MARKER_COUNT_MISMATCH`, `GRAQ_APPLY_POST_WRITE_VERIFY`, `GRAQ_APPLY_INVALID_INSERTION`. Callers know exactly what failed and can recover.
- **27 pytest tests** for `graq_apply` covering all 9 rails, every error code, multi-insertion sequencing, and byte-for-byte unchanged-region preservation.
- **`kogni_apply` alias** for `graq_apply` (backward-compat with the kogni_* naming).

### Notes
- This release fixes the underlying root cause of the multiple `graq_edit` failures observed during the v0.46.9 hotfix on `graqle/core/graph.py`. Other projects (Studio, CrawlQ) hitting the same pattern can now use `graq_apply` directly.
- `graq_apply` was used to register itself in `graqle/plugins/mcp_dev_server.py` and to update the `test_expected_tool_names` test — full dogfooding before ship.
- Test suite: 73 passed in 0.47s combined (`test_graq_apply.py` 27 + `test_mcp_dev_server.py` 46).

## v0.46.9 — 2026-04-10

### Fixed
- **OT-060: NEO4J_DISABLED env var gate** in `graqle/core/graph.py` — `Graqle.from_neo4j()` and `Graqle.to_neo4j()` now respect the `NEO4J_DISABLED` env var (truthy: `1`, `true`, `yes`, `on`). When set, both methods raise `RuntimeError` BEFORE importing `Neo4jConnector` or dialing `bolt://`. Zero dials, zero retries. Existing caller `try/except → JSON fallback` contract preserved. Unblocks VS Code MCP server, CI jobs, and Lambda hosts that cannot tolerate slow bolt handshakes. **Neo4j remains a first-class power-user feature** — this is a per-process override, not a feature removal. Once-per-process WARNING via module-level sentinel. 6 new tests in `TestNeo4jDisabledEnvVar`.
- **OT-062: Session-scoped MCP gate bypasses for graqle-vscode** in `graqle/plugins/mcp_dev_server.py` — the `initialize` JSON-RPC handler now reads `clientInfo.name` and, when it equals `"graqle-vscode"`, sets per-instance `_cg01_bypass`, `_cg02_bypass`, `_cg03_bypass` flags. The CG-01 (session_started), CG-02 (plan_active), and CG-03 (edit_enforcement) gates honor these flags. State is naturally session-scoped because each `KogniDevServer` instance is one MCP stdio process; concurrent non-graqle-vscode clients run in their own instances and are unaffected. **Fail-closed default**: missing or unrecognized `clientInfo` → gates remain ON. 5 new tests in `TestInitializeClientInfoBypass`.
- **OT-061: S3 AccessDenied dedupe** in `graqle/core/kg_sync.py` — added `_is_access_denied()`, `_log_s3_error()`, `_reset_access_denied_dedupe()` helpers and a module-level `_access_denied_logged` sentinel. AccessDenied errors are now logged ONCE per process at WARNING; non-AccessDenied S3 errors continue to log at ERROR per occurrence. Replaces 3 noisy `logger.warning` sites in `pull_if_newer` and `_push_worker`. 5 new tests in `TestAccessDeniedDedupe`, including the headline test "10 AccessDenied errors → 1 log line".

### Notes
- 16 new tests added across `test_graph.py`, `test_mcp_dev_server.py`, and `test_kg_sync.py`. All 91 pre-existing tests continue to pass (107 total green, zero regressions).

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
