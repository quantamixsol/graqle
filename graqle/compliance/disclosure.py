"""EU AI Act Article 50(1) AI-disclosure surfaces.

Article 50 paragraph 1 (Regulation (EU) 2024/1689) requires providers of
AI systems that interact with natural persons to ensure those persons
are **informed** they are interacting with an AI system, unless that
fact is obvious from the perspective of a reasonably well-informed
observer.

This module ships two complementary surfaces that activate when the
environment variable ``GRAQLE_EU_AI_ACT_MODE`` is set to a truthy value
(``on/true/1/yes``, case-insensitive):

  1. **Session banner** (``maybe_emit_session_banner``) — printed to
     stderr exactly once per process on the first reasoning call. After
     the first emit the in-process state flag is set, so subsequent
     calls in the same process do not repeat the banner (the "unless
     obvious" carve-out — a developer who has already seen the banner
     once in their session is now informed).
  2. **Machine-readable disclosure** (``build_ai_disclosure`` +
     ``build_compliance_envelope``) — small JSON-serialisable dicts
     attached to MCP envelopes so deployer-side pipelines can route on
     AI-generated content without parsing stderr.

The banner can be **suppressed** by setting ``GRAQLE_AI_DISCLOSURE=off``
for machine-to-machine pipelines where a human never sees stderr (the
suppression is logged downstream so a deployer can verify the suppress
was intentional, per the Art 14 oversight discipline).

No code path in this module writes to disk, calls the network, or
references trade-secret material. Every value is either a public
constant (article numbers, system card URL), an environment variable,
or a GraQle version string from ``graqle.__version__``.
"""

# ── graqle:intelligence ──
# module: graqle.compliance.disclosure
# risk: LOW (impact radius: 1 module — mcp_dev_server only)
# consumers: graqle.plugins.mcp_dev_server (PR-009d wires-in)
# dependencies: __future__, dataclasses, os, sys, typing
# constraints: side-effect-free EXCEPT maybe_emit_session_banner stderr write
# ── /graqle:intelligence ──

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

# Articles GraQle's compliance documentation maps to (shape locked
# alongside graqle.cli.commands.compliance.ARTICLES_COVERED in PR-009b).
# The test-suite drift guard in tests/test_compliance/ enforces parity.
_ARTICLES_COVERED: tuple[str, ...] = ("4", "12", "13", "14", "15", "25", "50")

_SYSTEM_CARD_URL: str = (
    "https://github.com/quantamixsol/graqle/blob/master/"
    "docs/compliance/eu-ai-act/README.md"
)

# In-process state — set to True after the session banner has been emit
# once. Module-level so it survives across MCP tool invocations in the
# same Python process, but resets on process restart (the new session
# starts with a fresh emit). ``reset_session_banner_state`` exists for
# tests; production code should NOT call it.
#
# The mutex (``_BANNER_LOCK``) guards the check-and-set against the
# async-server race where two concurrent ``_handle_reason`` calls could
# both see ``False`` and both emit. ``threading.Lock`` is correct in
# both sync and asyncio contexts because the acquire/release window
# does not yield control (no ``await`` inside).
_SESSION_BANNER_EMITTED: bool = False
_BANNER_LOCK: threading.Lock = threading.Lock()


@dataclass(frozen=True)
class AIDisclosure:
    """Machine-readable Article 50(1) AI-disclosure for an MCP envelope.

    All fields are public and may be quoted in customer compliance
    documentation. Used by every MCP envelope when EU AI Act mode is on.

    Attributes:
        is_ai_generated: Always ``True`` — every GraQle reasoning output
            is, by definition, AI-generated. Boolean for unambiguous
            machine parsing.
        system: The product name. Stable across versions. ``"GraQle"``.
        version: The GraQle SDK version that produced this envelope.
        backend: The third-party LLM identifier (model + provider) when
            available. ``"unknown"`` when not provided. Names the
            specific underlying model so deployers can route to a
            different output-handling pipeline per backend if needed.
        ai_act_article_50_paragraph_1: Always ``True`` — the legal
            anchor for this field. Kept explicit so a deployer's
            compliance auditor can grep for the regulation reference.
    """

    is_ai_generated: bool = True
    system: str = "GraQle"
    version: str = ""
    backend: str = "unknown"
    ai_act_article_50_paragraph_1: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_ai_generated": self.is_ai_generated,
            "system": self.system,
            "version": self.version,
            "backend": self.backend,
            "ai_act_article_50_paragraph_1": self.ai_act_article_50_paragraph_1,
        }


@dataclass(frozen=True)
class ComplianceEnvelope:
    """Machine-readable EU AI Act compliance posture for an MCP envelope.

    Mirrors the shape returned by ``graq compliance status --format json``
    (PR-009b) so customer-side compliance pipelines can parse the same
    structure from the live MCP envelope and the CLI introspection.

    Attributes:
        articles_covered: list of article numbers GraQle documents
            alignment with (e.g. ``["4", "12", "13", "14", "15", "25",
            "50"]``).
        system_card_url: Public docs URL for the compliance index.
        audit_log_export: Hint string describing the CLI command a
            deployer would invoke to materialise the audit trail. Stable
            string suitable for embedding in a deployer's compliance
            runbook.
        version: GraQle SDK version (matches AIDisclosure.version).
    """

    articles_covered: tuple[str, ...] = _ARTICLES_COVERED
    system_card_url: str = _SYSTEM_CARD_URL
    audit_log_export: str = "graq compliance export --since <DATE>"
    version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "articles_covered": list(self.articles_covered),
            "system_card_url": self.system_card_url,
            "audit_log_export": self.audit_log_export,
            "version": self.version,
        }


def is_eu_ai_act_mode_on() -> bool:
    """Return True iff ``GRAQLE_EU_AI_ACT_MODE`` is set to a truthy value.

    Mirrors the identical helper in :mod:`graqle.cli.commands.compliance`
    — kept duplicated here so the disclosure module has zero dependencies
    on the CLI tree (and vice versa). The truthy allowlist is the
    same: ``{on, true, 1, yes}`` case-insensitive.
    """
    raw = os.environ.get("GRAQLE_EU_AI_ACT_MODE", "").strip().lower()
    return raw in {"on", "true", "1", "yes"}


def is_ai_disclosure_suppressed() -> bool:
    """Return True iff ``GRAQLE_AI_DISCLOSURE=off`` is set.

    SCOPE: this env var suppresses ONLY the stderr **banner** — the
    machine-readable ``ai_disclosure`` field on the MCP envelope is
    NOT suppressed by this switch (and intentionally so).

    The rationale: M2M pipelines (CI runs, MCP-over-pipe integrations)
    typically have no human stderr reader, so the banner is just noise
    in their logs. But the machine-readable field is exactly what their
    downstream compliance pipeline NEEDS to compose a deployer-level
    Article 50 disclosure for the eventual human consumer. Suppressing
    that field would defeat the disclosure obligation.

    So:
      * ``GRAQLE_EU_AI_ACT_MODE=off`` (default) → no banner, no field.
      * ``GRAQLE_EU_AI_ACT_MODE=on``,
        ``GRAQLE_AI_DISCLOSURE=on`` (or unset) → banner + field.
      * ``GRAQLE_EU_AI_ACT_MODE=on``,
        ``GRAQLE_AI_DISCLOSURE=off`` → field only (no banner).

    The suppression itself should be logged in the deployer's audit
    trail (this module doesn't do that — it's the caller's
    responsibility, since the audit log is on the caller's process-cwd).
    """
    raw = os.environ.get("GRAQLE_AI_DISCLOSURE", "").strip().lower()
    return raw == "off"


def _get_graqle_version() -> str:
    """Return the current GraQle version string, or ``'unknown'`` on import error."""
    try:
        from graqle.__version__ import __version__
        return __version__
    except ImportError:
        return "unknown"


def build_ai_disclosure(backend: str = "unknown") -> AIDisclosure:
    """Construct an Article 50(1) AI-disclosure dataclass for an MCP envelope.

    Args:
        backend: Third-party LLM identifier (e.g.
            ``"anthropic/claude-sonnet-4-6"``). Pass ``"unknown"`` if
            the caller doesn't know — never block disclosure on a
            missing backend name.

    Returns:
        Frozen dataclass with the disclosure fields. Convert to dict
        via ``.to_dict()`` when adding to a JSON envelope.
    """
    return AIDisclosure(
        is_ai_generated=True,
        system="GraQle",
        version=_get_graqle_version(),
        backend=(backend or "unknown"),
        ai_act_article_50_paragraph_1=True,
    )


def build_compliance_envelope() -> ComplianceEnvelope:
    """Construct the ``compliance`` MCP envelope block.

    Matches the shape of the JSON output from ``graq compliance status``
    so a deployer pipeline can use identical parsing on both surfaces.
    """
    return ComplianceEnvelope(
        articles_covered=_ARTICLES_COVERED,
        system_card_url=_SYSTEM_CARD_URL,
        audit_log_export="graq compliance export --since <DATE>",
        version=_get_graqle_version(),
    )


def _build_banner_text(confidence: float | None, backend: str) -> str:
    """Build the human-readable Article 50(1) banner string.

    Format aligned with the example in
    ``docs/compliance/eu-ai-act/article-50-transparency.md``. Single
    multi-line block written to stderr; no Rich markup so it renders
    correctly in non-terminal contexts (CI logs, log shippers).
    """
    conf_part = (
        f" Confidence: {confidence:.2f}."
        if confidence is not None
        else ""
    )
    return (
        f"⚠ This response was generated by an AI system "
        f"(GraQle v{_get_graqle_version()} using {backend} backend).\n"
        f"   It may be inaccurate.{conf_part} Always verify before relying on it.\n"
        f"   AI Act Article 50(1) disclosure | "
        f"Suppress with GRAQLE_AI_DISCLOSURE=off"
    )


def maybe_emit_session_banner(
    confidence: float | None = None,
    backend: str = "unknown",
    *,
    stream: Any = None,
) -> bool:
    """Emit the Article 50(1) banner to stderr if conditions are met.

    Conditions:
      1. ``GRAQLE_EU_AI_ACT_MODE`` is on.
      2. ``GRAQLE_AI_DISCLOSURE`` is NOT ``off``.
      3. The in-process banner state has not already been emitted.

    Returns:
        ``True`` iff the banner was emitted on this call. The caller
        may use the return value to log the emit event into their
        deployer-side audit trail.

    The banner is written to ``stream`` (default ``sys.stderr``) so
    the JSONL/MCP stdout stream is not polluted. The ``stream``
    parameter is provided for test injection.
    """
    global _SESSION_BANNER_EMITTED

    if not is_eu_ai_act_mode_on():
        return False
    if is_ai_disclosure_suppressed():
        return False

    # Atomic check-and-set under ``_BANNER_LOCK`` so two concurrent
    # MCP tool calls cannot both see ``False`` and both emit. The
    # write itself happens INSIDE the lock to make the emit-then-set
    # appear atomic from the caller's perspective; the write is small
    # (one stderr line) so lock-hold time is microseconds.
    with _BANNER_LOCK:
        if _SESSION_BANNER_EMITTED:
            return False
        text = _build_banner_text(confidence=confidence, backend=backend)
        target = stream if stream is not None else sys.stderr
        try:
            target.write(text + "\n")
            target.flush()
        except (OSError, ValueError):
            # Stream may be closed (e.g. in tests teardown) — degrade
            # silently rather than raise. Disclosure-on-stderr is a
            # best-effort surface; the machine-readable ai_disclosure
            # field on the MCP envelope is the authoritative one. Do
            # NOT set ``_SESSION_BANNER_EMITTED`` here — we want the
            # next caller (which may have a working stream) to retry.
            return False
        _SESSION_BANNER_EMITTED = True
        return True


def reset_session_banner_state() -> None:
    """Reset the in-process banner-emitted flag.

    For test use only. Production code should not call this — the
    once-per-session semantics is the entire point.
    """
    global _SESSION_BANNER_EMITTED
    with _BANNER_LOCK:
        _SESSION_BANNER_EMITTED = False
