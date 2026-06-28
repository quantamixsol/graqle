## OPSF PCT Spec — Public Submission (3 Issues filed 2026-06-27)

Three issues filed to `opsf-org/pct-spec` before the 30 June 2026 public-comment deadline, from account `quantamixsol` under Harish Kumar, Founder, Quantamix Solutions B.V. / GraQle.

### Filed Issues

| # | Title | URL |
|---|---|---|
| 1 | Extension namespace proposal — x-ai-eu (EU AI Act compliance fields) | https://github.com/opsf-org/pct-spec/issues/65 |
| 2 | Reference implementation — PCT issuer + validator + x-ai-eu extension (Apache 2.0, GraQle SDK) | https://github.com/opsf-org/pct-spec/issues/66 |
| 3 | RS256 key custody and rotation patterns over multi-year (10y+) audit horizon | https://github.com/opsf-org/pct-spec/issues/67 |

---

## Sentinel Review — Pre-Filing Sign-Off

> Internal 3-pass review completed before filing. Sentinel methodology matches GCC PR review protocol (ADR-209).

### Pass 1 — Issue 1 (`x-ai-eu` extension namespace) vs `graqle/pct/extensions/x_ai_eu.py` v0.76.0

| Claim in Issue Body | Evidence in Code | Result |
|---|---|---|
| 11-field extension dataclass | `XAiEuExtension` has fields 1-10 (ADR-205 §2.2) + field 11 `policy_version` (CR-017) | ✅ PASS |
| Field 1: `article_6_classification` with 5 enum values (`non_high_risk`, `annex_iii_high_risk`, `annex_i_high_risk`, `gpai_model`, `gpai_systemic_risk`) | Confirmed in `Article6Classification` enum in `x_ai_eu.py` | ✅ PASS |
| Field 5: `article_14_human_oversight_mode` enum: `disabled \| monitor \| gated` | Confirmed `Article14OversightMode` enum | ✅ PASS |
| Field 6: `article_50_disclosure_mode` enum: `auto_banner \| machine_only \| suppress_with_logged_reason` | Confirmed `Article50DisclosureMode` enum | ✅ PASS |
| Field 9: `annex_iii_category` with 8 Annex III categories | Confirmed `AnnexIiiCategory` enum with all 8 values | ✅ PASS |
| Field 11: `policy_version` (SHA-256 content-addressed hash) | Confirmed `policy_version: str \| None = None` as field 11, added by CR-017 | ✅ PASS |
| `article_9` conditional: required when annex_iii or annex_i high-risk | Confirmed in `__post_init__` conditional guard | ✅ PASS |
| `annex_iii_category` conditional: required when `annex_iii_high_risk` | Confirmed in `__post_init__` conditional guard | ✅ PASS |
| `articles_covered` default includes Article 11 | `baseline_doc.py` `DEFAULT_ARTICLES_COVERED = ("4", "11", "12", "13", "14", "15", "25", "50")` — confirmed | ✅ PASS |
| Status: "NOT YET proposed to OPSF" | Docstring in `x_ai_eu.py` says: `"Public-comms status: NOT YET proposed to OPSF (per ADR-RT-001 Option 2A)"` — this filing changes that status | ✅ Accurate at time of filing |
| Reference implementation Apache 2.0, v0.76.0 | `__version__.py` confirms `0.76.0`; repo LICENSE is Apache 2.0 | ✅ PASS |

**Pass 1 verdict: ALL PASS — Issue 1 body cleared for filing.**

---

### Pass 2 — Issue 2 (reference implementation) vs `graqle/pct/issuer.py` + `graqle/pct/validator.py` v0.76.0

| Claim in Issue Body | Evidence in Code | Result |
|---|---|---|
| `issue_pct(request, signing_key, kid, issuer_url) -> compact-JWS` | `def issue_pct(request, *, signing_key, kid, issuer_url, now=None, pct_id=None) -> str` — confirmed | ✅ PASS |
| `validate_pct(token, public_key_resolver, ...) -> PctValidationResult(decision: ALLOW\|BLOCK)` | `def validate_pct(token, *, public_key_resolver, expected_action=None, expected_jurisdiction=None, expected_purpose=None, now=None) -> PctValidationResult` — confirmed | ✅ PASS |
| Hash algorithm guard: refuses MD5, SHA-1 | `_PROHIBITED_HASH_ALGORITHMS: frozenset = frozenset({"md5", "sha-1", "sha1"})` at line 62 of `issuer.py` | ✅ PASS |
| 64 KiB DoS cap (`GRAQLE_PCT_MAX_TOKEN_BYTES`) | `_MAX_TOKEN_BYTES = int(os.environ.get("GRAQLE_PCT_MAX_TOKEN_BYTES", 65536))` at line 557 of `validator.py` | ✅ PASS |
| `kid` sanitisation in failure logs | `_sanitise_kid_for_log(kid)` at line 572 of `validator.py` — control char replacement | ✅ PASS |
| Cross-tests against all 4 OPSF scenarios | `tests/test_pct/test_opsf_example_compat.py` — 4 scenario fixtures, round-trip validate, assert `_expected_decision` | ✅ PASS |
| OPSF schema vendored from `opsf-org/pct-spec@develop` | `graqle/pct/schema/pct_v0_1.json` confirmed | ✅ PASS |

**Pass 2 verdict: ALL PASS — Issue 2 body cleared for filing.**

---

### Pass 3 — Issue 3 (key custody + rotation) vs `issuer.py` + `validator.py` key design v0.76.0

| Claim in Issue Body | Evidence in Code | Result |
|---|---|---|
| `kid` mandatory in JWS header | Issuer docstring point 3 + `_validate_kid(kid)` enforces non-empty, ≤256 chars, safe charset | ✅ PASS |
| `public_key_resolver(kid)` callback in validator | `validate_pct(..., public_key_resolver, ...)` — resolver called with `kid` from JWS header | ✅ PASS |
| `.well-known/pct-keys.json` key-ring referenced | Issuer docstring + line 319 of `issuer.py` reference the well-known endpoint pattern | ✅ PASS |
| Rotation = ADD never REMOVE (old keys retained) | Design in issuer.py; `valid_until` pattern documented | ✅ PASS |
| Revocation = `revoked: true` + `revoked_at_iso`; tokens before revocation timestamp still ACCEPT | Described in `validator.py` key-ring resolution pattern | ✅ PASS |

**Pass 3 verdict: ALL PASS — Issue 3 body cleared for filing.**

---

## Corrections Applied Before Filing

1. **Article 11 added** to `articles_covered` in Issue 1 body: changed `["4", "12", "13", "14", "15", "25", "50"]` → `["4", "11", "12", "13", "14", "15", "25", "50"]` (Article 11 = technical documentation, per `baseline_doc.py` `DEFAULT_ARTICLES_COVERED`)
2. **Harish Kumar attribution** added to top of all three issue bodies

## ADR References

- ADR-205: `graqle.pct.{issuer,validator}` + `graqle.pct.extensions.x_ai_eu` module layout — ACCEPTED
- ADR-RT-001: Research team binding decision accepting PCT Use B + Option 2A (propose to OPSF post-Borner call)
- ADR-MARKETING-001: All language uses "aligned with" EU AI Act — no "compliant/certified/guaranteed"
- RULE-BOUNDARY-001: Substrate proves the replayable path — does NOT decide permission/gate/stop/block actions

## Filing Authority

- Peter Borner (OPSF Chairman) engaged substantively on 2026-05-28, co-signing "aligned with, not setting"
- ADR-RT-001 Option 2A: propose 24-48h post-Borner call — condition met; filing authorised
- Public commitment to file before 30 June 2026 made in `lead-engine/posts/2026-05-28_reply_to_peter_borner_FINAL.md`
