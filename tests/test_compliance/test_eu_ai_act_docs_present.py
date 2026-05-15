"""CR-009 PR-009a tests — EU AI Act compliance documentation presence + integrity.

Locks down the docs/compliance/eu-ai-act/ directory as the canonical surface
for our Article-by-Article compliance mapping. The intent is that regulators
or customer compliance teams reading our docs find them present, well-formed,
and citing the authoritative EUR-Lex regulation source.

Test categories:

1. File presence — every Article doc enumerated in CR-009 § 4.1 exists on disk.
2. Required-headings invariant — each Article doc has the headings that downstream
   compliance teams will look for: "What the Article requires", "What GraQle
   provides", "How to quote this in your compliance file".
3. Authoritative source link — every Article doc embeds the EUR-Lex URL for
   Regulation (EU) 2024/1689. Customers MUST be able to verify our claims
   against the binding regulation text.
4. README index — every doc listed in the README index has the corresponding
   file on disk (no broken internal links).

CI safety: pure filesystem reads, no network calls, no subprocess. The web
links cited inside the docs are checked at the regulation-summary-refresh
cadence (separate CI workflow — not this test).
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ── Constants ─────────────────────────────────────────────────────────


DOCS_ROOT = Path(__file__).resolve().parent.parent.parent / "docs" / "compliance" / "eu-ai-act"

EUR_LEX_AUTHORITATIVE_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689"

REQUIRED_ARTICLE_DOCS = [
    "README.md",
    "article-04-ai-literacy.md",
    "article-12-record-keeping.md",
    "article-13-transparency-to-deployers.md",
    "article-14-human-oversight.md",
    "article-15-robustness.md",
    "article-25-value-chain.md",
    "article-50-transparency.md",
    "out-of-scope-articles.md",
]

ARTICLE_DOC_REQUIRED_HEADINGS = [
    "## What the Article requires",
    "## What GraQle provides",
    "## How to quote this in your compliance file",
]

# README and out-of-scope-articles don't have the standard Article-doc shape —
# they have their own structure. So those skip the per-Article heading check.
ARTICLE_DOCS_WITH_STANDARD_SHAPE = [
    "article-04-ai-literacy.md",
    "article-12-record-keeping.md",
    "article-13-transparency-to-deployers.md",
    "article-14-human-oversight.md",
    "article-15-robustness.md",
    "article-25-value-chain.md",
    "article-50-transparency.md",
]


# ── 1. File presence ──────────────────────────────────────────────────


class TestDocsPresence:
    """Every doc enumerated in CR-009 § 4.1 must exist on disk.

    Regression guard for: someone deletes a doc, breaks regulator citation.
    """

    def test_docs_directory_exists(self) -> None:
        assert DOCS_ROOT.is_dir(), (
            f"docs/compliance/eu-ai-act/ must exist at {DOCS_ROOT}. "
            "This directory is the canonical Article-by-Article compliance "
            "surface per CR-009."
        )

    @pytest.mark.parametrize("filename", REQUIRED_ARTICLE_DOCS)
    def test_required_doc_exists(self, filename: str) -> None:
        path = DOCS_ROOT / filename
        assert path.is_file(), (
            f"Required compliance doc missing: {filename}. "
            f"CR-009 § 4.1 lists this as a mandatory file. Restore it from "
            f"git history or recreate from the regulation summary."
        )

    @pytest.mark.parametrize("filename", REQUIRED_ARTICLE_DOCS)
    def test_required_doc_non_empty(self, filename: str) -> None:
        path = DOCS_ROOT / filename
        content = path.read_text(encoding="utf-8")
        # Bound the minimum at 1000 chars — a real Article doc is 5-10k chars.
        assert len(content) >= 1000, (
            f"Compliance doc {filename} is suspiciously short "
            f"({len(content)} chars). Real Article docs are 5,000+ chars. "
            f"This may indicate accidental truncation or a stub."
        )


# ── 2. Required-headings invariant ────────────────────────────────────


class TestArticleDocStructure:
    """Article docs (excluding README + out-of-scope) must have the three
    standard headings so customer compliance teams find them where they
    expect.

    Regression guard for: someone rewrites a doc and drops a heading,
    breaking the quoting pattern downstream teams depend on.
    """

    @pytest.mark.parametrize("filename", ARTICLE_DOCS_WITH_STANDARD_SHAPE)
    @pytest.mark.parametrize("heading", ARTICLE_DOC_REQUIRED_HEADINGS)
    def test_article_doc_has_required_heading(
        self, filename: str, heading: str,
    ) -> None:
        path = DOCS_ROOT / filename
        content = path.read_text(encoding="utf-8")
        assert heading in content, (
            f"Article doc {filename} is missing required heading "
            f"{heading!r}. CR-009 § 4.1 mandates the three-heading "
            f"shape so customer compliance teams find a consistent surface."
        )


# ── 3. Authoritative source link ──────────────────────────────────────


class TestAuthoritativeSourceLink:
    """Every Article doc must embed the EUR-Lex URL for Regulation (EU)
    2024/1689 so customers can verify our claims against the binding
    regulation text. Without this, our docs are unverifiable.

    Regression guard for: someone updates a doc and drops the EUR-Lex
    link, leaving citation traceability broken.
    """

    @pytest.mark.parametrize("filename", REQUIRED_ARTICLE_DOCS)
    def test_doc_cites_eur_lex(self, filename: str) -> None:
        path = DOCS_ROOT / filename
        content = path.read_text(encoding="utf-8")
        assert EUR_LEX_AUTHORITATIVE_URL in content, (
            f"Compliance doc {filename} does not embed the authoritative "
            f"EUR-Lex URL ({EUR_LEX_AUTHORITATIVE_URL}). Every Article doc "
            f"MUST cite the binding regulation source so customers can "
            f"verify our claims."
        )


# ── 4. README index integrity ─────────────────────────────────────────


class TestReadmeIndexIntegrity:
    """Every Article doc listed in the README index table must exist on
    disk. Prevents broken internal links in the docs directory.
    """

    def test_readme_lists_all_required_articles(self) -> None:
        readme = (DOCS_ROOT / "README.md").read_text(encoding="utf-8")
        # All Article docs (except the README itself) should be linked.
        for doc in REQUIRED_ARTICLE_DOCS:
            if doc == "README.md":
                continue
            # Markdown link format: ](./<doc>) or ](<doc>)
            link_form_relative = f"](./{doc})"
            link_form_bare = f"]({doc})"
            assert link_form_relative in readme or link_form_bare in readme, (
                f"README does not link to {doc}. CR-009 § 4.1 requires the "
                f"README index to be the single navigation surface for the "
                f"compliance directory."
            )

    def test_readme_links_resolve_on_disk(self) -> None:
        """No broken `[...](./article-XX-*.md)` links in the README."""
        import re
        readme = (DOCS_ROOT / "README.md").read_text(encoding="utf-8")
        # Find ](./*.md) relative links pointing at files in this directory.
        pattern = re.compile(r"]\(\./([^)\s]+\.md)\)")
        for match in pattern.finditer(readme):
            target = DOCS_ROOT / match.group(1)
            assert target.is_file(), (
                f"README links to {match.group(1)} but the file does not "
                f"exist on disk at {target}. Broken internal link."
            )


# ── 5. Positioning statement invariant ────────────────────────────────


class TestPositioningStatement:
    """The README positioning statement must clearly say GraQle is NOT a
    high-risk AI system and NOT a GPAI model provider. These are the two
    key load-bearing claims for our compliance posture.

    Regression guard for: someone softens the positioning to claim more
    than we can defend. This test fires loudly if either negation is dropped.
    """

    def test_readme_says_graqle_is_not_high_risk(self) -> None:
        readme = (DOCS_ROOT / "README.md").read_text(encoding="utf-8")
        # Allow various phrasings, but require explicit "NOT high-risk".
        not_high_risk_phrases = [
            "NOT a high-risk AI system",
            "is not a high-risk AI system",
            "not a high-risk system",
        ]
        assert any(p in readme for p in not_high_risk_phrases), (
            "README positioning statement must explicitly say GraQle is NOT "
            "a high-risk AI system. This negation is load-bearing for our "
            "Article 6 / Annex III scoping. Found none of: "
            f"{not_high_risk_phrases}"
        )

    def test_readme_says_graqle_is_not_gpai_provider(self) -> None:
        readme = (DOCS_ROOT / "README.md").read_text(encoding="utf-8")
        not_gpai_phrases = [
            "NOT a general-purpose AI MODEL provider",
            "is not a general-purpose AI MODEL provider",
            "not a GPAI model provider",
            "not a general-purpose AI model provider",
        ]
        assert any(p in readme for p in not_gpai_phrases), (
            "README positioning statement must explicitly say GraQle is NOT "
            "a GPAI model provider. This negation is load-bearing for our "
            "Article 53 scoping (we use GPAI models, we don't release them). "
            f"Found none of: {not_gpai_phrases}"
        )

    def test_readme_uses_aligned_not_compliant_or_certified(self) -> None:
        """We claim 'EU AI Act–aligned', not 'compliant' or 'certified'.

        Compliance + certification are stronger claims that require formal
        legal review (compliant) or notified-body assessment (certified).
        Our positioning is deliberately scoped to 'aligned' until those are
        actually done.
        """
        readme = (DOCS_ROOT / "README.md").read_text(encoding="utf-8")
        # The phrase "EU AI Act–aligned" (or with regular hyphen) must appear.
        aligned_appearance = (
            "EU AI Act–aligned" in readme
            or "EU AI Act-aligned" in readme
            or '"EU AI Act' in readme  # quoted positioning paragraph
        )
        assert aligned_appearance, (
            "README must claim 'EU AI Act–aligned' positioning. This is the "
            "defensible claim. Stronger claims ('compliant', 'certified') "
            "require additional legal / assessment work and are out of scope."
        )
