"""ChatAgentLoop v4 settings loader .

Fail-closed jsonschema-validated loader for ``.graqle/settings.json``.

Error taxonomy (all subclasses of ChatSettingsError):

  MissingFileWarning   — file not present; returns defaults and logs info.
                         NOT raised, just logged as a soft signal.
  InvalidJsonError     — file present but not valid JSON. Raised.
  SchemaViolationError — JSON valid but fails jsonschema. Raised.
  UnknownKeyError      — JSON contains unexpected keys (additionalProperties:
                         false enforced via the schema). Raised.

The schema enforces:
  - ``governance_tier_overrides``: dict[str, "GREEN"|"YELLOW"|"RED"]
  - ``max_burst_calls``: int in [1, 500]
  - ``per_tool_timeouts``: dict[str, positive number]
  - ``session_permission_cache_enabled``: bool
  - ``max_continuations_chat``: int in [0, 10]

Eager jsonschema import — fail-closed validation cannot be optional.
"""

# ── graqle:intelligence ──
# module: graqle.chat.settings_loader
# risk: LOW (impact radius: 0 modules at # consumers: graqle.chat.agent_loop # dependencies: dataclasses, json, jsonschema, pathlib
# constraints: zero intra-graqle deps; fail-closed on schema violation
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

__all__ = [
    "ChatSettings",
    "SettingsLoader",
    "ChatSettingsError",
    "InvalidJsonError",
    "SchemaViolationError",
    "UnknownKeyError",
    "CHAT_SETTINGS_SCHEMA",
]

logger = logging.getLogger("graqle.chat.settings_loader")

_DEFAULT_PATH = Path.home() / ".graqle" / "settings.json"


# ── error taxonomy ────────────────────────────────────────────────────


class ChatSettingsError(Exception):
    """Base error for chat settings load failures."""


class InvalidJsonError(ChatSettingsError):
    """Settings file exists but is not valid JSON."""


class SchemaViolationError(ChatSettingsError):
    """Settings file parses as JSON but fails schema validation."""


class UnknownKeyError(ChatSettingsError):
    """Settings file contains an unexpected top-level key (additionalProperties:false)."""


# ── schema ────────────────────────────────────────────────────────────


CHAT_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "governance_tier_overrides": {
            "type": "object",
            "additionalProperties": {
                "type": "string",
                "enum": ["GREEN", "YELLOW", "RED"],
            },
        },
        "max_burst_calls": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
        },
        "per_tool_timeouts": {
            "type": "object",
            "additionalProperties": {
                "type": "number",
                "exclusiveMinimum": 0,
            },
        },
        "session_permission_cache_enabled": {
            "type": "boolean",
        },
        "max_continuations_chat": {
            "type": "integer",
            "minimum": 0,
            "maximum": 10,
        },
    },
}


# ── ChatSettings dataclass ────────────────────────────────────────────


@dataclass(frozen=True)
class ChatSettings:
    """Runtime-typed representation of .graqle/settings.json.

    All fields have safe defaults so ``ChatSettings()`` is always valid.
    """

    governance_tier_overrides: dict[str, str] = field(default_factory=dict)
    max_burst_calls: int = 100
    per_tool_timeouts: dict[str, float] = field(default_factory=dict)
    session_permission_cache_enabled: bool = True
    max_continuations_chat: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "governance_tier_overrides": dict(self.governance_tier_overrides),
            "max_burst_calls": self.max_burst_calls,
            "per_tool_timeouts": dict(self.per_tool_timeouts),
            "session_permission_cache_enabled": self.session_permission_cache_enabled,
            "max_continuations_chat": self.max_continuations_chat,
        }

    @classmethod
    def from_validated_dict(cls, raw: dict[str, Any]) -> "ChatSettings":
        """Construct from a dict that has already passed schema validation."""
        return cls(
            governance_tier_overrides=dict(
                raw.get("governance_tier_overrides", {})
            ),
            max_burst_calls=int(raw.get("max_burst_calls", 100)),
            per_tool_timeouts={
                k: float(v) for k, v in raw.get("per_tool_timeouts", {}).items()
            },
            session_permission_cache_enabled=bool(
                raw.get("session_permission_cache_enabled", True)
            ),
            max_continuations_chat=int(raw.get("max_continuations_chat", 3)),
        )


# ── SettingsLoader ────────────────────────────────────────────────────


class SettingsLoader:
    """Fail-closed loader for ``.graqle/settings.json``.

    Usage:
        settings = SettingsLoader().load()  # ~/.graqle/settings.json
        settings = SettingsLoader(Path("./custom/settings.json")).load()
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_PATH

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> ChatSettings:
        """Load and validate settings.

        Returns ChatSettings() defaults if the file is missing (logs info).
        Raises InvalidJsonError / SchemaViolationError / UnknownKeyError on
        parse/validation failures.
        """
        if not self._path.exists():
            logger.info(
                "ChatSettings file not found at %s — using defaults",
                self._path,
            )
            return ChatSettings()

        try:
            raw_text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ChatSettingsError(
                f"ChatSettings file at {self._path} could not be read: {exc}"
            ) from exc

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise InvalidJsonError(
                f"ChatSettings file at {self._path} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise SchemaViolationError(
                f"ChatSettings file at {self._path} must be a JSON object, "
                f"got {type(parsed).__name__}"
            )

        # Fail-closed schema validation via Draft 2020-12
        validator = Draft202012Validator(CHAT_SETTINGS_SCHEMA)
        errors = sorted(validator.iter_errors(parsed), key=lambda e: e.path)
        if errors:
            # additionalProperties:false violations map to UnknownKeyError;
            # everything else is a generic SchemaViolationError.
            unknown_keys: list[str] = []
            other_errors: list[str] = []
            for err in errors:
                msg = err.message
                if err.validator == "additionalProperties":
                    # err.path is empty at the top level; parse the unknown
                    # keys out of the validator error message.
                    unknown_keys.append(msg)
                else:
                    loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
                    other_errors.append(f"{loc}: {msg}")
            if unknown_keys and not other_errors:
                raise UnknownKeyError(
                    f"ChatSettings at {self._path} has unknown key(s): "
                    + "; ".join(unknown_keys)
                )
            raise SchemaViolationError(
                f"ChatSettings at {self._path} failed validation: "
                + "; ".join(other_errors + unknown_keys)
            )

        return ChatSettings.from_validated_dict(parsed)


# BLOCKER-R2 Round-1 — required-key helper for the TCG novelty lift
# threshold. See lesson_20260402T210613: config.get(KEY, default) with a
# numerical default IS a hardcoded threshold disguised as config.
# Correct pattern: config[KEY] with fail-loud ValueError on missing key.

_NOVELTY_LIFT_SETTINGS_PATH = ("chat", "probation", "novelty_lift_min")


def load_novelty_lift_min(settings: dict | None) -> float | None:
    """Extract ``chat.probation.novelty_lift_min`` from a settings dict.

    Returns ``None`` if the settings dict is None or the key is absent
    so the caller can fall back to the module default
    (``tool_capability_graph.PROBATION_NOVELTY_LIFT_MIN``). Callers that
    require the operator value MUST raise themselves on None — this
    helper is a strict reader, not a default-provider, to comply with
    the lesson_20260402T210613 pattern.
    """
    if not settings:
        return None
    node = settings
    for key in _NOVELTY_LIFT_SETTINGS_PATH:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    try:
        value = float(node)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"settings[{'.'.join(_NOVELTY_LIFT_SETTINGS_PATH)}] "
            f"must be a float, got {type(node).__name__}: {exc}"
        ) from None
    if not 0.0 <= value <= 1.0:
        raise ValueError(
            f"settings[{'.'.join(_NOVELTY_LIFT_SETTINGS_PATH)}] "
            f"must be in [0.0, 1.0], got {value}"
        )
    return value


def require_novelty_lift_min(settings: dict) -> float:
    """Strict reader: raises ValueError if the key is missing. Use in
    production contexts that must NOT fall back to the public default.
    """
    value = load_novelty_lift_min(settings)
    if value is None:
        raise ValueError(
            "chat.probation.novelty_lift_min is required in settings — "
            "the public default is intentionally non-operational. Set "
            "the value in .graqle/settings.json before running."
        )
    return value

