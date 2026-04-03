"""Sensitivity classification for knowledge-graph nodes — Content sensitivity classification.

Multi-layer detection pipeline that assigns a ``SensitivityLevel`` to every
node *before* it enters the graph.  Typed placeholders preserve embedding
quality while removing secret material.

Layers:
    L0  Property-key substring matching
    L1  Regex pattern scanning (privacy engine)
    L2  Shannon entropy detection
    L3  AST structural detection (credential assignments)
    L4  Semantic / LLM classification (placeholder — not yet implemented)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sensitivity levels
# ---------------------------------------------------------------------------


class SensitivityLevel(IntEnum):
    """Ordered sensitivity tiers — higher value = more restricted."""

    PUBLIC = 0
    INTERNAL = 1
    SECRET = 2
    RESTRICTED = 3


# ---------------------------------------------------------------------------
# Redaction marker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedactionMarker:
    """Byte-offset marker indicating a region that should be redacted.

    Attributes:
        offset:       Start position (0-based) in the source text.
        length:       Number of characters covered by the sensitive span.
        pattern_type: Name of the detection pattern that fired.
        replacement:  Typed placeholder string (preserves embedding quality).
    """

    offset: int
    length: int
    pattern_type: str
    replacement: str


# ---------------------------------------------------------------------------
# Typed placeholders (Content security — preserve embedding quality)
# ---------------------------------------------------------------------------

TYPED_PLACEHOLDERS: dict[str, str] = {
    "aws_key": "<AWS_ACCESS_KEY>",
    "aws_secret_key": "<AWS_SECRET_KEY>",
    "private_key": "<PRIVATE_KEY>",
    "jwt": "<JWT_TOKEN>",
    "connection_string": "<CONNECTION_STRING>",
    "password": "<PASSWORD_VALUE>",
    "api_key": "<API_KEY_VALUE>",
    "graqle_api_key": "<API_KEY_VALUE>",
    "bearer_token": "<BEARER_TOKEN>",
    "generic_secret": "<SECRET_VALUE>",
    "env_export": "<ENV_SECRET>",
    "ssn_like": "<PII_VALUE>",
    "email": "<EMAIL_ADDRESS>",
    "entropy": "<HIGH_ENTROPY_VALUE>",
    "credential_assignment": "<CREDENTIAL_ASSIGNMENT>",
    "generic": "<REDACTED>",
}

# Pattern names that escalate to SECRET (all others -> INTERNAL).
_CRITICAL_PATTERNS: frozenset[str] = frozenset({
    "aws_key",
    "aws_secret_key",
    "private_key",
    "jwt",
    "connection_string",
})

# L3: regex for credential assignment patterns in source code.
_CREDENTIAL_ASSIGNMENT_RE: re.Pattern[str] = re.compile(
    r"""(?ix)
    (?:password|passwd|secret|token|api_key|apikey|access_key|private_key|
       auth_token|credential|connection_string)
    \s*[=:]\s*
    (?:["'][^"']{4,}["'])
    """,
)


# ---------------------------------------------------------------------------
# SensitivityClassifier
# ---------------------------------------------------------------------------


class SensitivityClassifier:
    """Multi-layer sensitivity detection pipeline for content security.

    Instantiate once and reuse — heavy dependencies are lazily imported
    on first use to avoid circular imports and degrade gracefully when
    optional packages are absent.
    """

    def __init__(self) -> None:
        self._sensitive_keys: frozenset[str] | None = None
        self._redaction_engine: Any | None = None
        self._entropy_detector: Any | None = None
        self._l4_warned: bool = False

    # -- lazy loaders (fail-open) ------------------------------------------

    def _get_sensitive_keys(self) -> frozenset[str]:
        if self._sensitive_keys is None:
            try:
                from graqle.core.redaction import DEFAULT_SENSITIVE_KEYS

                self._sensitive_keys = frozenset(
                    k.lower() for k in DEFAULT_SENSITIVE_KEYS
                )
            except ImportError:
                logger.warning(
                    "graqle.core.redaction not available; L0 using built-in keys",
                )
                self._sensitive_keys = frozenset({
                    "password", "secret", "token", "api_key", "apikey",
                    "access_key", "private_key", "credential", "auth",
                    "connection_string", "jwt",
                })
        return self._sensitive_keys

    def _get_redaction_engine(self) -> Any | None:
        if self._redaction_engine is None:
            try:
                from graqle.scanner.privacy import RedactionEngine

                self._redaction_engine = RedactionEngine()
            except ImportError:
                logger.warning("graqle.scanner.privacy not available; L1 disabled")
        return self._redaction_engine

    def _get_entropy_detector(self) -> Any | None:
        if self._entropy_detector is None:
            try:
                from graqle.security.entropy import EntropyDetector

                self._entropy_detector = EntropyDetector()
            except ImportError:
                logger.warning("graqle.security.entropy not available; L2 disabled")
        return self._entropy_detector

    # -- layer implementations ---------------------------------------------

    def _l0_property_keys(self, properties: dict[str, Any]) -> SensitivityLevel:
        """L0: property-key substring matching."""
        keys = self._get_sensitive_keys()
        for prop_key in properties:
            prop_lower = prop_key.lower()
            if any(sk in prop_lower for sk in keys):
                return SensitivityLevel.INTERNAL
        return SensitivityLevel.PUBLIC

    def _l1_regex(self, text: str) -> tuple[SensitivityLevel, list[RedactionMarker]]:
        """L1: regex pattern scanning via RedactionEngine."""
        engine = self._get_redaction_engine()
        if engine is None or not text:
            return SensitivityLevel.PUBLIC, []

        level = SensitivityLevel.PUBLIC
        markers: list[RedactionMarker] = []
        try:
            detections = engine.detect(text)
            for det in detections:
                ptype: str = det.pattern_name
                replacement = TYPED_PLACEHOLDERS.get(
                    ptype, TYPED_PLACEHOLDERS["generic"],
                )
                markers.append(RedactionMarker(
                    offset=det.start,
                    length=det.end - det.start,
                    pattern_type=ptype,
                    replacement=replacement,
                ))
                if ptype in _CRITICAL_PATTERNS:
                    level = max(level, SensitivityLevel.SECRET)
                else:
                    level = max(level, SensitivityLevel.INTERNAL)
        except Exception:
            logger.debug("L1 regex scan failed", exc_info=True)

        return level, markers

    def _l2_entropy(self, text: str) -> SensitivityLevel:
        """L2: Shannon entropy detection."""
        detector = self._get_entropy_detector()
        if detector is None or not text:
            return SensitivityLevel.PUBLIC
        try:
            matches = detector.detect_high_entropy_strings(text)
            if matches:
                return SensitivityLevel.INTERNAL
        except Exception:
            logger.debug("L2 entropy detection failed", exc_info=True)
        return SensitivityLevel.PUBLIC

    @staticmethod
    def _l3_ast_credential(text: str) -> SensitivityLevel:
        """L3: credential assignment patterns in source code."""
        if _CREDENTIAL_ASSIGNMENT_RE.search(text):
            return SensitivityLevel.SECRET
        return SensitivityLevel.PUBLIC

    def _l4_semantic(self) -> SensitivityLevel:
        """L4: placeholder for semantic / LLM classification."""
        if not self._l4_warned:
            logger.debug("L4 semantic/LLM classification not yet implemented")
            self._l4_warned = True
        return SensitivityLevel.PUBLIC

    # -- public API --------------------------------------------------------

    def classify_node(
        self,
        properties: dict[str, Any],
        description: str = "",
        chunks: list[str] | None = None,
    ) -> SensitivityLevel:
        """Return the **highest** sensitivity level found across all layers."""
        chunks = chunks or []
        level = SensitivityLevel.PUBLIC

        # L0 — property-key substring matching
        level = max(level, self._l0_property_keys(properties))

        # Collect all textual content for L1–L3
        texts: list[str] = []
        if description:
            texts.append(description)
        texts.extend(chunks)
        for val in properties.values():
            if isinstance(val, str):
                texts.append(val)

        for text in texts:
            if not text:
                continue
            l1_level, _ = self._l1_regex(text)
            level = max(level, l1_level)
            level = max(level, self._l2_entropy(text))
            level = max(level, self._l3_ast_credential(text))

        return SensitivityLevel(level)

    def classify_text(
        self,
        text: str,
    ) -> tuple[SensitivityLevel, list[RedactionMarker]]:
        """Classify *text* and return sensitivity level with byte-offset markers."""
        level = SensitivityLevel.PUBLIC
        markers: list[RedactionMarker] = []

        if not text:
            return level, markers

        # L1 — regex pattern scanning (produces markers)
        l1_level, l1_markers = self._l1_regex(text)
        level = max(level, l1_level)
        markers.extend(l1_markers)

        # L2 — Shannon entropy
        level = max(level, self._l2_entropy(text))

        # L3 — credential assignment patterns (produces markers)
        for m in _CREDENTIAL_ASSIGNMENT_RE.finditer(text):
            markers.append(RedactionMarker(
                offset=m.start(),
                length=m.end() - m.start(),
                pattern_type="credential_assignment",
                replacement=TYPED_PLACEHOLDERS["credential_assignment"],
            ))
            level = max(level, SensitivityLevel.SECRET)

        return SensitivityLevel(level), markers
