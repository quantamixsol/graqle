"""Unified content security gate — Content security gate.

Enforces sensitivity classification and redaction at all 7 exit points
(G1-G7) before content leaves the GraQle trust boundary:

    G1: areason() / areason_stream()  — LLM reasoning prompts
    G2: _auto_load_chunks()           — chunk synthesis
    G3: _auto_enrich_descriptions()   — description enrichment
    G4: ChunkScorer / embed_fn()      — embedding API calls
    G5: _handle_generate()            — code generation (50K chars)
    G6: _handle_review/_handle_debug  — code review / debug
    G7: QueryReformulator             — graph_summary

All methods are pure — inputs are never mutated. Detection delegates to
``SensitivityClassifier`` and ``RedactionEngine``; replacement uses
``TYPED_PLACEHOLDERS`` for semantic-preserving redaction.


"""

from __future__ import annotations

import copy
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from graqle.security.sensitivity import (
    RedactionMarker,
    SensitivityClassifier,
    SensitivityLevel,
    TYPED_PLACEHOLDERS,
)

__all__ = [
    "ContentAuditRecord",
    "ContentSecurityGate",
    "GateResult",
]

logger = logging.getLogger("graqle.security.content_gate")

# ---------------------------------------------------------------------------
# Default sensitive property keys (lowercase, configurable via constructor)
# ---------------------------------------------------------------------------

_DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "secret", "token", "api_key", "apikey", "api_secret",
    "private_key", "credential", "credentials", "auth_token",
    "access_key", "secret_key", "connection_string", "dsn",
    "ssn", "social_security", "credit_card", "card_number",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    """Result of a pre-send gate check."""

    sensitivity_level: SensitivityLevel
    redactions_needed: int
    can_send: bool
    markers: list[RedactionMarker] = field(default_factory=list)


@dataclass(frozen=True)
class ContentAuditRecord:
    """Immutable audit record created when content passes through a gate."""

    timestamp: str
    destination: str
    gate_id: str
    sensitivity_level: SensitivityLevel
    redactions_applied: int
    original_length: int
    redacted_length: int
    content_hash_pre: str
    content_hash_post: str
    blocked: bool = False
    dry_run: bool = False


# ---------------------------------------------------------------------------
# ContentSecurityGate
# ---------------------------------------------------------------------------


class ContentSecurityGate:
    """Unified content security gate for all exit points (G1-G7).

    Parameters
    ----------
    enabled:
        Master kill-switch.  When ``False`` every method is a pass-through.
    sensitive_keys:
        Extra property key names to treat as sensitive (merged with
        built-in defaults).  Matching is case-insensitive substring.
    block_threshold:
        Minimum SensitivityLevel at which gate_check sets can_send=False.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        sensitive_keys: set[str] | None = None,
        block_threshold: SensitivityLevel = SensitivityLevel.RESTRICTED,
    ) -> None:
        self._enabled = enabled
        self._sensitive_keys: frozenset[str] = (
            _DEFAULT_SENSITIVE_KEYS | frozenset(k.lower() for k in sensitive_keys)
            if sensitive_keys
            else _DEFAULT_SENSITIVE_KEYS
        )
        self._block_threshold = block_threshold
        self._classifier = SensitivityClassifier()

    @property
    def enabled(self) -> bool:
        """Whether the gate is active."""
        return self._enabled

    # -- internal helpers ----------------------------------------------------

    def _is_sensitive_key(self, key: str) -> bool:
        """Return True if key matches any sensitive pattern (substring, case-insensitive)."""
        key_lower = key.lower()
        return any(sk in key_lower for sk in self._sensitive_keys)

    def _placeholder_for_key(self, key: str) -> str:
        """Return a typed placeholder for a property key."""
        key_lower = key.lower()
        for category, placeholder in TYPED_PLACEHOLDERS.items():
            if category in key_lower:
                return placeholder
        return TYPED_PLACEHOLDERS.get("generic", "<REDACTED>")

    @staticmethod
    def _apply_markers(text: str, markers: list[RedactionMarker]) -> str:
        """Replace spans described by markers with typed placeholders.

        Markers are applied in reverse offset order so earlier indices
        remain valid after each replacement.
        """
        if not markers:
            return text
        sorted_markers = sorted(markers, key=lambda m: m.offset, reverse=True)
        result = text
        for marker in sorted_markers:
            end = marker.offset + marker.length
            result = result[:marker.offset] + marker.replacement + result[end:]
        return result

    @staticmethod
    def _sha256(text: str) -> str:
        """Compute SHA-256 hash of text for audit trail."""
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    # -- public API ----------------------------------------------------------

    def redact_properties(
        self,
        properties: dict[str, Any],
        sensitivity: SensitivityLevel | None = None,
    ) -> dict[str, Any]:
        """Return a new dict with sensitive values replaced by typed placeholders.

        Never mutates the input properties dict.
        """
        if not self._enabled:
            return dict(properties)

        out: dict[str, Any] = {}
        for key, value in properties.items():
            if self._is_sensitive_key(key):
                out[key] = self._placeholder_for_key(key)
            else:
                out[key] = copy.deepcopy(value)
        return out

    def redact_text(
        self,
        text: str,
        markers: list[RedactionMarker] | None = None,
    ) -> str:
        """Apply redaction markers to text.

        If markers is None, SensitivityClassifier.classify_text() is
        called to detect them automatically.
        """
        if not self._enabled or not text:
            return text
        if markers is None:
            _, markers = self._classifier.classify_text(text)
        return self._apply_markers(text, markers)

    def redact_for_embedding(self, text: str) -> str:
        """Semantic-preserving redaction for embedding paths.

        Uses SensitivityClassifier to detect sensitive spans and replaces
        them with typed placeholders (not generic [REDACTED]) so that
        embedding vectors retain structural meaning.
        """
        if not self._enabled or not text:
            return text
        _, markers = self._classifier.classify_text(text)
        if not markers:
            return text
        return self._apply_markers(text, markers)

    def prepare_node_for_llm(
        self,
        properties: dict[str, Any],
        description: str,
        chunks: list[str],
    ) -> tuple[dict[str, Any], str, list[str]]:
        """One-call method for G1: classify, redact, return safe copies.

        Returns (safe_properties, safe_description, safe_chunks).
        """
        if not self._enabled:
            return dict(properties), description, list(chunks)

        safe_props = self.redact_properties(properties)
        safe_desc = self.redact_text(description)
        safe_chunks = [self.redact_text(c) for c in chunks]
        return safe_props, safe_desc, safe_chunks

    def prepare_content_for_send(
        self,
        content: str,
        destination: str,
        gate_id: str = "G5",
        dry_run: bool = False,
    ) -> tuple[str, ContentAuditRecord]:
        """For G5/G6: scan content, redact, and create an audit record.

        Returns the redacted content together with an immutable
        ContentAuditRecord.
        """
        hash_pre = self._sha256(content)

        if not self._enabled:
            record = ContentAuditRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                destination=destination,
                gate_id=gate_id,
                sensitivity_level=SensitivityLevel.PUBLIC,
                redactions_applied=0,
                original_length=len(content),
                redacted_length=len(content),
                content_hash_pre=hash_pre,
                content_hash_post=hash_pre,
                blocked=False,
                dry_run=dry_run,
            )
            return content, record

        level, markers = self._classifier.classify_text(content)
        redacted = self._apply_markers(content, markers) if markers else content
        hash_post = self._sha256(redacted)
        blocked = level >= self._block_threshold

        record = ContentAuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            destination=destination,
            gate_id=gate_id,
            sensitivity_level=level,
            redactions_applied=len(markers),
            original_length=len(content),
            redacted_length=len(redacted),
            content_hash_pre=hash_pre,
            content_hash_post=hash_post,
            blocked=blocked,
            dry_run=dry_run,
        )
        logger.info(
            "Gate audit: gate=%s dest=%s level=%s redactions=%d blocked=%s",
            gate_id, destination, level.name, len(markers), blocked,
        )

        # Dry-run still redacts content but flags in audit record.
        # This prevents accidental secret exposure if dry_run is enabled in prod.
        return redacted, record

    def gate_check(self, content: str, destination: str) -> GateResult:
        """Pre-send check returning a GateResult.

        Callers use result.can_send to decide whether to proceed
        and result.markers to apply redaction if needed.
        """
        if not self._enabled:
            return GateResult(
                sensitivity_level=SensitivityLevel.PUBLIC,
                redactions_needed=0,
                can_send=True,
            )

        level, markers = self._classifier.classify_text(content)
        can_send = level < self._block_threshold

        return GateResult(
            sensitivity_level=level,
            redactions_needed=len(markers),
            can_send=can_send,
            markers=list(markers),
        )
