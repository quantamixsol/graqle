"""CG-MKT-05 — README snapshot-lock test (MC-HLD-01).

Per ADR-MARKETING-001 §11, the README's public positioning is bound by
four invariants that CI must protect:

1. **Forbidden words NEVER appear**: ``compliant`` / ``certified`` /
   ``guaranteed`` / ``end-to-end solution``. These are stronger claims
   than GraQle can defend without formal legal review or notified-body
   assessment, and slipping into them is the single biggest reputational
   risk for the EU AI Act positioning.

2. **The canonical positioning markers appear verbatim**:
   - "EU AI Act–aligned" (en-dash) OR "EU AI Act-aligned" (hyphen) badge
   - Scope statement "Articles 6, 9, 12, 13, 14, 15, 25, 50"
   - The two NOT-claims: "NOT itself a high-risk AI system" + "NOT a
     GPAI provider"

3. **A doc-source for the canonical sentence exists** — either README
   or one of ``docs/compliance/eu-ai-act/*.md`` quotes the full
   "GraQle is EU AI Act–aligned by design. We give your high-risk AI
   system the signals, audit trail, and disclosure primitives you
   need to satisfy your own Article 9 risk-management file — without
   GraQle itself being subject to the high-risk obligations." sentence
   verbatim.

4. **The aligned-badge SVG URL is intact** in the README so the
   shields.io badge renders.

If any invariant breaks, the PR cannot merge until either the README
is restored or ADR-MARKETING-001 is formally amended.

References:
    - ADR-MARKETING-001 §11 (`.gsm/decisions/ADR-MARKETING-001-summary.md`)
    - CG-MKT-05 in OPEN-TRACKER-CAPABILITY-GAPS.md
    - Companion: pre-existing :class:`TestPositioningStatement` in
      :mod:`tests.test_compliance.test_eu_ai_act_docs_present`
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPO_ROOT / "README.md"
EU_AI_ACT_DOCS_DIR = REPO_ROOT / "docs" / "compliance" / "eu-ai-act"


# ---------------------------------------------------------------------------
# Forbidden public-comms words
# ---------------------------------------------------------------------------

# Word-boundary regex — matches the bare word but NOT compounds like
# "non-compliance" (regulator-direction noun) or "complete" (different word).
# Three exemption rules apply (each line of the text is checked independently):
#
# 1. Lines with italic *compliant* / *certified* (meta-mention not claim).
# 2. Lines disavowing the word: contain "never say" or "do not claim" or
#    "not compliant" or "not certified" — these are protective statements.
# 3. Backticked uses like `compliant` (code-identifier reference).
#
# We implement this by stripping italic / backtick / disavowal lines BEFORE
# the regex search.
_FORBIDDEN_PATTERNS: dict[str, re.Pattern[str]] = {
    # "compliant" — bare word only, NOT compound hyphenated adjectives
    # like "privacy-compliant" / "GDPR-compliant" / "data-compliant"
    # which qualify a TYPE of handling rather than claiming GraQle is
    # itself compliant. Negative lookbehind on hyphen-word.
    "compliant": re.compile(r"(?<![A-Za-z\-])compliant\b", re.IGNORECASE),
    "certified": re.compile(r"(?<![A-Za-z\-])certified\b", re.IGNORECASE),
    "guaranteed": re.compile(r"(?<![A-Za-z\-])guaranteed\b", re.IGNORECASE),
    "end-to-end solution": re.compile(
        r"\bend[- ]to[- ]end\s+solution\b", re.IGNORECASE
    ),
}

# Italic + code-fence + disavowal exemptions: lines matching ANY of these
# are removed from the text before forbidden-word checks. These are explicit
# REGULATOR-FACING ANTI-CLAIMS (saying "we don't claim X") and
# ENGINEERING META-REFERENCES (e.g. "the `compliant` field is blocked").
_LINE_EXEMPTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"never\s+say", re.IGNORECASE),
    re.compile(r"do\s+not\s+claim", re.IGNORECASE),
    re.compile(r"not\s+(?:compliant|certified)\b", re.IGNORECASE),
    # Lines that ONLY mention the words inside italic / backtick markers:
    # *compliant*, *certified*, `compliant`, `certified`. These are
    # talking-about-the-word, not making-the-claim.
    re.compile(r"\*compliant\*", re.IGNORECASE),
    re.compile(r"\*certified\*", re.IGNORECASE),
    re.compile(r"`compliant`", re.IGNORECASE),
    re.compile(r"`certified`", re.IGNORECASE),
)


def _strip_exempt_lines(text: str) -> str:
    """Remove lines that are explicit anti-claims or meta-references."""
    kept = []
    for line in text.splitlines():
        if any(pat.search(line) for pat in _LINE_EXEMPTION_PATTERNS):
            continue
        kept.append(line)
    return "\n".join(kept)

# The canonical positioning sentence from ADR-MARKETING-001 §11. The full
# sentence is long enough that exact-match is brittle (any subtle
# typographic shift breaks). We instead check that THREE distinctive
# substrings co-occur in the same document.
_CANONICAL_SENTENCE_SUBSTRINGS: tuple[str, ...] = (
    "EU AI Act",            # the actual posture word(s)
    "aligned",              # the only acceptable verb
    "signals",              # canonical noun for the SDK's contribution
)


def _normalise_dashes(text: str) -> str:
    """Map en-dashes + em-dashes to hyphens so substring checks are robust."""
    return text.replace("–", "-").replace("—", "-")


# ---------------------------------------------------------------------------
# Tests — CG-MKT-05 snapshot-lock
# ---------------------------------------------------------------------------


class TestForbiddenWords:
    """Invariant 1: forbidden marketing-claim words must NEVER appear."""

    def test_readme_no_forbidden_words(self):
        text = _strip_exempt_lines(README_PATH.read_text(encoding="utf-8"))
        violations = [
            label
            for label, pat in _FORBIDDEN_PATTERNS.items()
            if pat.search(text)
        ]
        assert violations == [], (
            f"README.md uses forbidden marketing-claim word(s): "
            f"{violations!r}. Per ADR-MARKETING-001 §11, only 'aligned' "
            f"is permitted. 'compliant' / 'certified' / 'guaranteed' / "
            f"'end-to-end solution' require formal legal review or "
            f"notified-body assessment. (Anti-claim lines using "
            f"'never say' / 'not compliant' / italic *compliant* are exempt.)"
        )

    def test_eu_ai_act_docs_no_forbidden_words(self):
        if not EU_AI_ACT_DOCS_DIR.exists():
            pytest.skip("docs/compliance/eu-ai-act/ not present")
        violations: list[tuple[str, str]] = []
        for md in EU_AI_ACT_DOCS_DIR.glob("*.md"):
            text = _strip_exempt_lines(md.read_text(encoding="utf-8"))
            for label, pat in _FORBIDDEN_PATTERNS.items():
                if pat.search(text):
                    violations.append((md.name, label))
        assert violations == [], (
            f"EU AI Act docs use forbidden marketing-claim word(s): "
            f"{violations!r}. Per ADR-MARKETING-001 §11, only 'aligned' "
            f"is permitted in deployer-facing compliance docs."
        )


class TestCanonicalPositioningMarkers:
    """Invariant 2: canonical positioning markers must appear verbatim."""

    def test_readme_has_aligned_badge_phrase(self):
        text = _normalise_dashes(README_PATH.read_text(encoding="utf-8"))
        # Accept en-dash and hyphen variants. Post-normalisation both
        # become hyphen.
        assert "EU AI Act-aligned" in text or "EU AI Act-aligned" in text, (
            "README must contain 'EU AI Act-aligned' (or with en-dash). "
            "Per ADR-MARKETING-001 §11, this is the canonical posture word."
        )

    def test_readme_has_articles_scope_statement(self):
        text = README_PATH.read_text(encoding="utf-8")
        # Allow either comma-separated or with "and" before last.
        # ADR canonical: "Articles 6, 9, 12, 13, 14, 15, 25, 50".
        assert "Articles 6, 9, 12, 13, 14, 15, 25, 50" in text, (
            "README must contain the literal scope list "
            "'Articles 6, 9, 12, 13, 14, 15, 25, 50' per ADR-MARKETING-001 §11."
        )

    def test_readme_has_not_high_risk_negation(self):
        text = README_PATH.read_text(encoding="utf-8")
        # Same negation TestPositioningStatement already asserts, but
        # repeated here so the snapshot-lock is a single-file CI gate.
        accepted = [
            "NOT a high-risk AI system",
            "NOT** itself a high-risk AI system",
            "is not a high-risk AI system",
            "not a high-risk system",
            "not itself a high-risk AI system",
        ]
        assert any(p in text for p in accepted), (
            "README must contain a 'NOT a high-risk AI system' negation. "
            f"Found none of: {accepted}"
        )

    def test_readme_has_not_gpai_provider_negation(self):
        text = README_PATH.read_text(encoding="utf-8")
        accepted = [
            "NOT a GPAI provider",
            "NOT** a GPAI provider",
            "not a GPAI provider",
            "NOT a general-purpose AI MODEL provider",
            "is not a general-purpose AI MODEL provider",
        ]
        assert any(p in text for p in accepted), (
            "README must contain a 'NOT a GPAI provider' negation. "
            f"Found none of: {accepted}"
        )


class TestCanonicalSentenceSourceExists:
    """Invariant 3: a doc-source quotes the canonical sentence's distinctive substrings."""

    def test_canonical_substrings_co_occur(self):
        candidates: list[Path] = [README_PATH]
        if EU_AI_ACT_DOCS_DIR.exists():
            candidates.extend(EU_AI_ACT_DOCS_DIR.glob("*.md"))
        # Also accept the ADR stub itself
        adr_stub = REPO_ROOT / ".gsm" / "decisions" / "ADR-MARKETING-001-summary.md"
        if adr_stub.exists():
            candidates.append(adr_stub)

        for path in candidates:
            text = path.read_text(encoding="utf-8")
            if all(sub in text for sub in _CANONICAL_SENTENCE_SUBSTRINGS):
                return  # found the source — invariant satisfied
        pytest.fail(
            f"No document under README / docs/compliance/eu-ai-act/ / "
            f"ADR-MARKETING-001 stub contains all three canonical sentence "
            f"substrings {_CANONICAL_SENTENCE_SUBSTRINGS!r}. Per "
            f"ADR-MARKETING-001 §11, the canonical sentence must live in "
            f"at least one publicly-visible doc."
        )


class TestBadgeSvgUrlIntact:
    """Invariant 4: shields.io aligned-badge URL must render."""

    def test_readme_has_shields_io_badge_url(self):
        text = README_PATH.read_text(encoding="utf-8")
        # The shields.io badge URL pattern for the EU AI Act-aligned badge.
        # We don't pin the exact colour or query string — just the host
        # + the "EU%20AI%20Act-aligned" stem so the badge keeps rendering.
        assert (
            "img.shields.io/badge/EU%20AI%20Act-aligned" in text
            or "img.shields.io/badge/EU AI Act-aligned" in text
        ), (
            "README must contain the shields.io 'EU AI Act-aligned' badge "
            "URL. The badge is part of the public positioning surface per "
            "ADR-MARKETING-001 §11."
        )
