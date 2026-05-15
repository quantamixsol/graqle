# Article 15 — Accuracy, Robustness, and Cybersecurity

> **Authoritative source:** [Article 15 — Regulation (EU) 2024/1689 on EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) · [Article 15 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/15/)
>
> **Applicability date:** 2026-08-02.
>
> **Applies to GraQle?** INDIRECTLY — GraQle is not a high-risk AI system, but our defence-in-depth measures support deployers' Article 15 obligations.

## What the Article requires

> "High-risk AI systems shall be designed and developed in such a way that they achieve an appropriate level of accuracy, robustness, and cybersecurity, and that they perform consistently in those respects throughout their lifecycle."

Technical solutions to address AI-specific vulnerabilities must include measures to prevent, detect, respond to, resolve, and control attacks such as:

- Data poisoning
- Model poisoning
- Adversarial examples
- Confidentiality attacks
- Model flaws

## What GraQle provides

### Defence-in-depth inventory

| Defence | Threat addressed | Where |
|---------|------------------|-------|
| **CR-003 edge-loss shrink guard** | Silent data corruption (v0.46→v0.53 regression class). `Graqle.to_json` refuses to shrink edge count by >10% on graphs with >100 baseline edges. Override: `GRAQLE_ALLOW_EDGE_SHRINK=1` — audit-logged. | `graqle/core/graph.py` `_write_with_lock` |
| **CR-008 SaveStatus disambiguation** | Phantom `WRITE_COLLISION` errors masking other failure modes. `SaveGraphResult` + `SaveStatus` enum splits 4 distinct outcomes (Neo4j-only / shrink-refused / real collision / generic save failure). | `graqle/plugins/mcp_dev_server.py` `_save_graph` |
| **`secret_patterns.scan_for_secrets`** | Confidentiality / output-leak class. 200+ patterns scanned on every output candidate; matches replaced with `<redacted: type>`. | `graqle/core/secret_patterns.py` |
| **CR-004 `graph_health` 3-deep never-raises probe** | Probe failure cascading into reasoning failure. Three layers of defensive catch ensure the probe always returns a result, even on internal error. | `graqle/activation/health_probe.py` |
| **CR-005a `stdout_path` TOCTOU-safe** | Path-traversal / write-outside-project-root class. `Path.resolve()` → `relative_to(_project_root)` → defence-in-depth `..` rejection on resolved parts. | `graqle/plugins/mcp_dev_server.py` `_handle_bash` |
| **Patent / IP scan on `git commit`** | Trade-secret leakage. The `graq_git_commit` MCP tool scans the staged diff for trade-secret patterns and blocks the commit if found. | `graqle/plugins/mcp_dev_server.py` `_handle_git_commit` |
| **CG-01..CG-20 governance gates** | Native-tool bypass class. Every write-class operation goes through a gate that validates session state, plan presence, path safety, etc. | `graqle/governance/` + `mcp_dev_server.py` gate decorators |
| **IP-protection-gate CI workflow** | Trade-secret leakage at PR time. CI scans every PR diff for trade-secret patterns and fails the build if detected. | `.github/workflows/ip-content-gate.yml` + `ip_gate.yml` |
| **`pip-audit` CVE scan in CI** | Known-vulnerable dependency class. CI runs `pip-audit` on every PR and fails on un-patched CVEs. | `.github/workflows/ci.yml` |
| **Atomic file writes** | Mid-write corruption / partial state. `NamedTemporaryFile` → `fsync(fileno)` → `os.replace()` everywhere we write files. | `graqle.core.graph._write_with_lock`, `mcp_dev_server._handle_bash` stdout_path |
| **Frozen dataclass result types** | Mutation-after-construction class. `SaveGraphResult`, `GraphHealth` are `@dataclass(frozen=True)`. | `graqle/core/graph_health.py`, `mcp_dev_server.py` |
| **Detail-only-type-name exception messages** | Path / credential leakage via exception messages. We interpolate `type(exc).__name__` into structured response details, never `str(exc)`. | `graqle/plugins/mcp_dev_server.py` `_save_graph`, `_coerce_save_result` |

### Measurable claims (the "appropriate level" benchmark)

| Metric | Claim | Evidence |
|--------|-------|----------|
| `graph_health_probe` p95 latency | < 5 ms | CI fail-gate test `tests/test_activation/test_graph_health_probe.py::test_p95_under_5ms` |
| Test suite size | 5,500+ tests | `pytest tests/` against v0.55.0 |
| Test pass rate (CI) | 100% on master | CI status badge + GitHub Actions history |
| CVE-vulnerable deps | Zero on master | `pip-audit` CI check (every PR) |
| Trade-secret leak rate | Zero new leaks on public master | `ip-protection-gate` CI check (every PR) |
| Phantom `WRITE_COLLISION` rate on Neo4j-backed sessions | Zero | CR-008 closed this entire class |
| Silent edge-loss rate | Zero on graphs ≥100 edges | CR-003 shrink guard |

### Cybersecurity-specific measures

- **No shell injection.** `subprocess.run` calls with `shell=True` are limited to `_handle_bash`, where commands are first scanned against a blocklist (`rm -rf`, `git push --force`, `DROP TABLE`, etc.).
- **No deserialisation of untrusted data.** No `pickle.loads`, no `yaml.unsafe_load`, no `eval`/`exec` of user input.
- **No SSRF surface.** GraQle does not fetch URLs from user-controlled input (the optional `graq_web_search` is gated by explicit user permission per call).
- **License-key secrets** stored only as `SecretStr` with constant-time equality (see `graqle.config.resolver.SecretStr`).
- **Path-traversal defences** as listed above (CR-005a + general resolver pattern).

### Adversarial input handling

The reasoning pipeline (graq_reason / graq_predict) is **NOT** a security boundary for adversarial-input attacks against the underlying LLM. Customers must:

- Treat LLM outputs as untrusted text.
- Apply their own input/output sanitisation before piping into downstream systems.
- Not use GraQle outputs as the sole basis for security-critical decisions.

This boundary is documented explicitly here so it cannot be misread by an integrator.

## How to quote this in your compliance file

When documenting your own Article 15 obligations as a deployer of a high-risk AI system that uses GraQle:

> "Our high-risk AI system uses GraQle ({version}) for code-reasoning support during {scenario}. The robustness, accuracy, and cybersecurity defences GraQle contributes to our system are catalogued at [github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-15-robustness.md](https://github.com/quantamixsol/graqle/blob/master/docs/compliance/eu-ai-act/article-15-robustness.md). Specifically: (a) the CR-003 edge-loss guard prevents silent data corruption; (b) the CR-008 SaveStatus enum ensures save-path failures are accurately classified; (c) the `secret_patterns.scan_for_secrets` redaction protects against confidentiality-attack output leaks; (d) the CR-005a TOCTOU-safe `stdout_path` validation defends against path-traversal in subprocess capture. We additionally implement {our own measures} at the system layer to meet the full Article 15 obligation."

## Dual-compliance cross-reference

GraQle's robustness defences align with:

- **ISO27001 § A.8.25** ("Secure development lifecycle — rules for the secure development of software and systems shall be established and applied").
- **OWASP Top 10:2021** — A01 (Broken Access Control), A05 (Security Misconfiguration), A09 (Security Logging and Monitoring Failures) are all directly addressed by the defences listed above.
- **NIST SP 800-218 (SSDF)** — practices PO.4 (test code), PW.4 (review code), PS.3 (archive provenance) are reflected in the BAU CR sentinel-review process.

## Security disclosure policy

If you discover a security vulnerability in GraQle, please report it privately to **security@quantamixsolutions.com** (or via GitHub's private vulnerability reporting on `quantamixsol/graqle`). The canonical security policy lives in [SECURITY.md](../../../SECURITY.md) at the repository root — it lists supported versions, the supply-chain hardening inventory (Trusted Publishing, Sigstore signatures, CycloneDX SBOM, pip-audit, `.pth`-file guard, reproducible builds), and the disclosure timeline below.

Do not file public issues or PRs that disclose vulnerabilities before they are patched.

Our commitment:

- **Acknowledgement:** within 1 business day.
- **Triage + severity assessment:** within 5 business days.
- **Coordinated disclosure window:** 90 days by default for non-critical, 30 days for critical.
- **Credit:** we name reporters in the release notes unless they prefer to stay anonymous.

## Related GraQle documents

- [Article 12 — Record-Keeping](./article-12-record-keeping.md) — how robustness signals are persisted
- [Article 13 — Transparency to Deployers](./article-13-transparency-to-deployers.md) — how robustness signals reach deployers
- [Article 14 — Human Oversight](./article-14-human-oversight.md) — how robustness signals drive human review

## Sources

- [Regulation (EU) 2024/1689 — EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689)
- [Article 15 — artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/15/)
