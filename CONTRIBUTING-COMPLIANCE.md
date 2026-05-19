# Contributing to GraQle's EU AI Act Documentation

Thanks for considering a contribution to GraQle's compliance surface. This document is the specific contribution guide for the **EU AI Act docs and compliance signals** — for general SDK contributions (new MCP tools, backend integrations, plugins), see [CONTRIBUTING.md](./CONTRIBUTING.md) once it exists; this guide is narrower and specifically about the substrate evidence GraQle exposes for deployer compliance work.

## Why a separate guide for compliance contributions

EU AI Act work has constraints that don't apply to most SDK contributions:

1. **Vocabulary is enforced in CI.** The README snapshot-lock test at `tests/test_compliance/test_readme_snapshot_lock.py` mechanically refuses PRs that introduce the words `compliant`, `certified`, `guaranteed`, or `end-to-end solution` into README files or `docs/compliance/eu-ai-act/*.md`. This is not a style preference — it's a marketing-vs-built honesty discipline that protects GraQle's positioning as **"EU AI Act-aligned"** rather than overclaiming.
2. **Four canonical positioning markers are verbatim-locked.** Every EU AI Act doc must preserve these exact strings: *"EU AI Act-aligned"*, *"Articles 6, 9, 12, 13, 14, 15, 25, 50"*, *"NOT high-risk"*, *"NOT GPAI provider"*. The snapshot-lock test enforces this.
3. **Three substantive non-claims are enforced in tests.** `tests/test_compliance/test_robustness.py::TestNonClaimsInvariants` refuses any `compliant: true` or `certified: true` field anywhere in the machine-readable surface.

The above rules exist because the EU AI Act distinguishes between providers of high-risk AI systems (who bear the heaviest obligations), deployers (who bear lighter but still serious ones), and component-vendors (who must produce documentation that supports their customers' compliance work but who do not themselves get "certified"). GraQle is the third category. The docs and code must reflect that consistently, and CI enforces consistency.

## What kinds of contributions are welcome

### Tier 1 — Most valuable today

- **Corrections to the article-by-article docs.** If a sentence in `docs/compliance/eu-ai-act/article-NN-*.md` makes a claim that's wrong, ambiguous, or out of step with current regulator guidance, that's a high-leverage fix.
- **Translations.** German, French, Spanish, and Italian deployers ask for translations most often. The article docs are flat Markdown files with no code dependencies, so each translation is self-contained.
- **Compliance gap reports from real deployers.** If you're building an Annex VI internal-control file (Article 43 conformity-assessment route) and you find an Annex IV requirement the GraQle substrate doesn't yet produce evidence for, file an issue tagged `compliance-gap`. We use these to scope future CRs.

### Tier 2 — Welcome with prior discussion

- **Cross-framework mappings.** If your sector follows additional frameworks (NIST AI RMF, ISO 42001, ENISA AI Threat Landscape, EBA AI guidelines for financial services, the upcoming OPSF Privacy Claims Token spec), a mapping document linking EU AI Act articles to your framework's controls is high-value but needs alignment on structure first.
- **New evidence-mapping for articles not currently covered.** If you have a use case where GraQle could plausibly produce evidence for Article 10 (data governance), or Article 26 (deployer obligations), or another article we currently treat as out-of-scope, open a discussion before the PR. The substrate-vs-out-of-scope boundary is intentional and worth talking through.
- **CI test contributions.** New tests in `tests/test_compliance/` that check parity between the docs and the runtime envelope (like the existing `test_articles_covered_list_matches_compliance_readme` test) are welcome — they're how we keep marketing and code from drifting.

### Tier 3 — Not currently in scope

- **New compliance subsystem implementations.** New code in `graqle/compliance/` that implements substrate evidence for a previously-uncovered article needs a Research-Team review before a PR can be opened. Open a discussion describing the proposed subsystem; the maintainers will route to research-team if appropriate.
- **Patent-adjacent claims.** Certain parts of the substrate are covered by patents (EP26162901.8, EP26166054.2, EP26167849.4 — see file headers in `graqle/governance/` and `graqle/compliance/`). PRs that touch these surfaces require additional IP review.

## What we cannot accept

- **Marketing-style language.** Sentences claiming GraQle is "compliant", "certified", "guaranteed", or an "end-to-end solution" will be rejected by CI before review reaches a maintainer.
- **Contradictions of the four canonical positioning markers.** Any sentence that asserts GraQle IS a high-risk AI system, IS a GPAI provider, IS certified, or covers Articles other than 6/9/12/13/14/15/25/50 substantively will be flagged.
- **Claims not backed by code or tests.** Every claim in `docs/compliance/eu-ai-act/article-NN-*.md` about what GraQle does should be traceable to a Python module in `graqle/compliance/` or a test in `tests/test_compliance/`. Contributions that add a claim without a corresponding code path will be asked to add the code path first (or to soften the claim to "planned" / "queued").

## How to contribute

### For docs corrections + translations

1. **Open an issue first** at https://github.com/quantamixsol/graqle/issues tagged `compliance` or `compliance-doc`. Describe what you want to change and the reading or evidence motivating it.
2. **Fork + branch.** Use a branch name like `docs-compliance/article-NN-fix` or `docs-compliance/article-NN-translation-DE`.
3. **Make the change.** Run `pytest tests/test_compliance/test_readme_snapshot_lock.py` locally before pushing — this catches the most common rejection class (forbidden words) without round-tripping through CI.
4. **Open a PR.** Reference the issue number. The PR template will ask you to confirm: (a) you ran the snapshot-lock test locally, (b) you preserved the four canonical positioning markers, (c) you cited specific GraQle code paths or tests for any new claims you added.

### For compliance gap reports

1. **Open an issue** at https://github.com/quantamixsol/graqle/issues tagged `compliance-gap`.
2. Describe: (a) which Article and which Annex VI sub-requirement, (b) what evidence your auditor / regulator asked for that GraQle doesn't currently produce, (c) what kind of evidence would close the gap (a new envelope field, a new CLI command, a new docs section, etc.).
3. The maintainers will respond with one of: "this is in scope, opening a CR" / "this is out of scope, here's why" / "this needs research-team review, expected response time TBD".

### For substantive interpretation discussions

If your contribution is about *how to read* a section of the EU AI Act differently from how the docs currently read it, **open a Discussion** at https://github.com/quantamixsol/graqle/discussions before a PR. Compliance interpretation is iterative and benefits from group conversation; PRs are better for changes the group has already aligned on.

## What happens after you open a PR

1. **CI runs immediately.** Most rejections happen here — README snapshot-lock, TestNonClaimsInvariants, parity tests. Fix what CI flags before maintainer review.
2. **Maintainer review.** A maintainer with the `compliance-reviewer` label will read the change against the four canonical positioning markers, the three substantive non-claims, and the actual EU AI Act text. Expected response time: 5 business days for tier-1 contributions, longer for tier-2.
3. **Research-team review (only if needed).** Certain changes (new evidence-mapping for currently-out-of-scope articles, patent-adjacent surfaces) get routed to the research team for additional sign-off.
4. **Merge.** Once CI is green and maintainer approval is in, your PR merges.

## Contributor recognition

We list significant compliance-doc contributors in the relevant article doc's footer with a brief attribution. Where appropriate, the recognition includes a link back to the contributor's GitHub profile or organisation. Translation contributors get explicit attribution in the translated file's header.

Public attribution that already exists in the substrate as the precedent:

- **VERITAS Pillar 16** (Andrii Matiash, LinkedIn 2026-05-12) — anchor for Q16.1 + Q16.3 + Q16.5 sub-questions
- **Claim-limits-as-typed-governance-field concept** (Ricky Jones, TrinityOS, LinkedIn 2026-05-13) — anchor for the R25-EU11 v1.0 taxonomy

## Questions?

- General compliance-doc questions: [GitHub Discussions](https://github.com/quantamixsol/graqle/discussions) tagged `compliance`
- Compliance gap reports: [GitHub Issues](https://github.com/quantamixsol/graqle/issues) tagged `compliance-gap`
- Security-sensitive disclosures: see [SECURITY.md](./SECURITY.md) (when present) — do NOT use public issues for security
- General SDK questions: standard [CONTRIBUTING.md](./CONTRIBUTING.md) channels (when present)

Thanks for helping keep GraQle honest about what the EU AI Act asks for and what GraQle actually delivers.
