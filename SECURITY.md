# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.35.x  | ✅ Active          |
| 0.34.x  | ✅ Security fixes  |
| < 0.34  | ❌ No security fixes |

## Reporting a Vulnerability

**Do not file a public GitHub issue for security vulnerabilities.**

Report vulnerabilities via email: **security@quantamixsolutions.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Potential impact

We will acknowledge receipt within **48 hours** and provide a timeline for a fix within **7 days**.

---

## Supply-Chain Security

Graqle takes supply-chain security seriously. Every release from v0.35.0 onwards includes the following hardening measures.

### 1. PyPI Trusted Publishing (OIDC)

Graqle is published to PyPI using [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — a keyless, token-free mechanism that ties every release directly to a specific GitHub Actions workflow run via OIDC.

- **No long-lived API tokens** exist in the publishing pipeline.
- The publishing workflow is `ci.yml` in the `quantamixsol/graqle` repository.
- Any release not signed by this workflow was **not produced by the official pipeline**.

### 2. Sigstore Signatures

Every wheel and source tarball is signed with [Sigstore](https://sigstore.dev) using the GitHub Actions OIDC identity:

```
https://github.com/quantamixsol/graqle/.github/workflows/ci.yml@refs/tags/v<version>
```

Bundles (`.sigstore.json`) are attached to each [GitHub Release](https://github.com/quantamixsol/graqle/releases).

**Verify a release:**
```bash
pip install "graqle[security]"
graq trustctl verify --version 0.35.0
```

Or in CI using the consumer template in `tools/verify-graqle-example.yml`.

### 3. CycloneDX SBOM

A Software Bill of Materials (`graqle-sbom.json`) is generated for every release and attached to the GitHub Release. It lists every Python package in the build environment.

Download: `gh release download v<version> --pattern graqle-sbom.json`

### 4. pip-audit CVE Scanning

Every CI run (including pull requests) runs `pip-audit` against Graqle's dependency tree. Releases are blocked if any **CRITICAL** or **HIGH** CVE is found in core dependencies.

### 5. .pth File Guard (LiteLLM-class Attack Prevention)

The publish pipeline rejects any wheel containing `.pth` files. `.pth` files execute arbitrary Python code at interpreter startup — this is the exact mechanism used in the [2024 LiteLLM supply-chain attack](https://socket.dev/blog/litellm-supply-chain-attack).

Graqle's wheels will never contain `.pth` files. If you ever see one, treat the release as compromised.

### 6. Reproducible Builds

Wheels are built with `SOURCE_DATE_EPOCH` set to a fixed value, producing deterministically reproducible artifacts. You can rebuild from the tagged source and compare checksums.

---

## Accepted CVE Exceptions

This section documents any known CVEs that have been evaluated and accepted (with justification and expiry). All exceptions require sign-off from the maintainers.

| CVE | Package | Severity | Justification | Expiry |
|-----|---------|----------|---------------|--------|
| *(none)* | — | — | — | — |

---

## Dependency Policy

- Core runtime dependencies are pinned to `>=` minimum versions (not upper-bounded) to allow security updates via `pip install --upgrade`.
- Optional extras (`[security]`, `[api]`, `[gpu]`) follow the same policy.
- `pip-audit` runs on every PR and scheduled weekly in CI.

---

## Security Model

### Local-First Architecture

GraQle runs entirely on your machine by default:

- **No telemetry.** GraQle does not phone home, collect usage data, or send analytics.
- **No code upload.** Your source code never leaves your machine unless you explicitly enable cloud sync.
- **Cloud sync is opt-in.** When enabled, only the knowledge graph (node/edge metadata) is uploaded — never source code.
- **API keys stay local.** LLM provider keys are stored in your local `graqle.yaml` config file.

### Knowledge Graph Privacy

The knowledge graph contains:
- File names, function names, class names, and their relationships
- Module-level descriptions and metadata
- Import chains and dependency information

The knowledge graph does **not** contain:
- Full source code
- Credentials, secrets, or environment variable values
- User data or PII

### LLM Provider Communication (ADR-151)

When using cloud LLM backends (Anthropic, OpenAI, etc.), GraQle sends:
- The user's query
- Relevant graph context (node descriptions, relationships)
- System prompts for reasoning
- For code generation (`graq_generate`): source file content (up to 50K chars)

**Content Security Architecture (ADR-151: Tag-Gate-Audit)**

All content sent to external providers passes through a multi-layer security pipeline:

1. **TAG at Ingest** — Every KG node is classified with a sensitivity level (PUBLIC, INTERNAL, SECRET, RESTRICTED) during `graq scan` using 5 detection layers:
   - L0: Property-key pattern matching
   - L1: Regex scanning (200+ patterns for API keys, tokens, connection strings, PEM keys, JWTs)
   - L2: Shannon entropy detection (catches novel secret formats)
   - L3: AST structural detection (credential assignments in source code)
   - L4: Semantic classification (reserved for future use)

2. **GATE at Every Exit** — 7 security gates enforce redaction at every point content leaves the trust boundary:
   - G1: LLM reasoning prompts (node properties, descriptions, chunks)
   - G2-G3: Chunk synthesis and description enrichment
   - G4: Embedding API calls (uses semantic-preserving typed placeholders)
   - G5: Code generation (source file scanning)
   - G6: Code review and debugging
   - G7: Query reformulation

3. **AUDIT Always** — Every external transmission creates a cryptographic audit record:
   - SHA-256 content hashes (pre and post redaction)
   - Append-only JSONL audit log
   - Dry-run mode (`--dry-run`) shows what would be sent without sending
   - Integrates with SOC2/ISO27001 compliance layer

**Sensitive values are replaced with typed placeholders** (e.g., `<API_KEY_VALUE>`, `<AWS_ACCESS_KEY>`) rather than generic `[REDACTED]`, preserving semantic meaning for embedding quality while removing actual secret material.

**Send-time overhead: ~7ms** (negligible against 500ms-5s LLM API latency).

### Dependencies

We monitor dependencies for known vulnerabilities using GitHub Dependabot. All dependencies are pinned to minimum versions in `pyproject.toml`.

## Disclosure Policy

- We follow coordinated disclosure practices
- Security fixes are released as patch versions (e.g., 0.29.1)
- CVEs are published for significant vulnerabilities
- Security advisories are posted on the GitHub repository

## License

GraQle source code is fully auditable. See [LICENSE](LICENSE) for terms. The codebase is available at [github.com/quantamixsol/graqle](https://github.com/quantamixsol/graqle).
