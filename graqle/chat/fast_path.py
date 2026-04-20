"""SDK-B3 / flag-default policy — Impact-radius fast-path for ChatAgentLoop.

When a user turn is unambiguously a file-create intent with zero blast
radius, bypass the LLM pipeline (reason → generate → review) and write
the file directly. Reduces a ~75s round-trip to ~0.3s.

Safety invariant (pre-reason-activation design):
    The pre-reason-activation design pre-reason activation layer (DRACE safety gate) runs
    BEFORE this module is consulted. Zero blast radius != zero safety
    risk. If pre-reason-activation design blocks the turn, this module never runs.

Failure semantics:
    All rejection paths are side-effect free: no events emitted, no
    state transitions, no partial writes. The caller falls through to
    the full tool-use loop.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("graqle.chat.fast_path")


# ─── Intent classification ───────────────────────────────────────────────


@dataclass(frozen=True)
class FastPathIntent:
    """Output of classify_intent() — a recognized fast-path trigger."""
    kind: str            # "file_create" (only supported kind today)
    target_path: str     # the raw target as classified; caller still safety-checks
    content_hint: str    # content supplied in the same message (may be empty)


# Strict regex requiring imperative file-create phrasing and a single target.
# Matches "create file X", "make a new file X", "write a file called X",
# with optional "with content: Y" tail.
_INTENT_PATTERN = re.compile(
    r"^\s*"
    r"(?:please\s+)?"
    r"(?:can\s+you\s+)?"
    r"(?P<verb>create|make|new|write|add)"
    r"\s+(?:a\s+)?(?:new\s+)?"
    r"(?:file|note|document)"
    r"\s+(?:called\s+|named\s+)?"
    r"(?P<target>[A-Za-z0-9_.\-/\\]+?)"
    r"\s*"
    r"(?:with\s+(?:content|text|body)[:\s]+(?P<content>.+?))?"
    r"\s*\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)

# Phrases that force None — we refuse to fast-path on any of these cues.
_NEGATION_TOKENS = frozenset({
    "don't", "dont", "do not", "never", "not a", "avoid", "unable to",
})

# Imperative anti-verbs — this is a refactor/edit, NOT a create.
_ANTI_VERBS = frozenset({
    "refactor", "edit", "modify", "change", "update", "fix", "rename",
    "delete", "remove", "move",
})


def classify_intent(user_message) -> Optional[FastPathIntent]:
    """Return a FastPathIntent if the message is unambiguously a file-create.

    Returns None on any of:
      - non-string / empty / whitespace-only input
      - negations ("don't create …")
      - anti-verbs ("refactor …", "edit …")
      - multiple path-looking tokens (ambiguous target)
      - regex non-match
    """
    # Fail-closed null guards (review round 2 MAJOR 2)
    if not isinstance(user_message, str):
        return None
    msg = user_message.strip()
    if not msg:
        return None

    msg_lower = msg.lower()

    # Reject negations
    for neg in _NEGATION_TOKENS:
        if neg in msg_lower:
            return None

    # Reject anti-verbs (edit/refactor requests must not fast-path)
    words = re.findall(r"[A-Za-z]+", msg_lower)
    if words and words[0] in _ANTI_VERBS:
        return None

    # Reject messages with multiple path-looking tokens (ambiguous)
    path_like = re.findall(r"\b[\w\-\.]+\.(?:md|txt|json|yaml|yml|toml|cfg|ini|rst|log)\b",
                           msg_lower)
    if len(path_like) > 1:
        return None

    m = _INTENT_PATTERN.match(msg)
    if m is None:
        return None

    target = (m.group("target") or "").strip()
    if not target:
        return None

    content = (m.group("content") or "").strip()

    return FastPathIntent(
        kind="file_create",
        target_path=target,
        content_hint=content,
    )


# ─── Path safety ─────────────────────────────────────────────────────────


# Secondary blocklist — primary defense is containment check.
_BLOCKED_FRAGMENTS = frozenset({
    ".ssh/", ".git/", ".aws/", ".config/",
    "/etc/", "/root/", "/System/", "/bin/", "/usr/bin/",
})


def is_path_safe(target, cwd) -> bool:
    """Return True iff `target` is safe to write relative to `cwd`.

    Fail-closed on: non-string inputs, empty/blank, resolution errors,
    any escape from cwd after symlink resolution, blocked fragments.
    """
    # Fail-closed null guards (review round 2 MAJOR 3)
    if not isinstance(target, str) or not target.strip():
        return False
    if cwd is None:
        return False

    try:
        cwd_path = Path(cwd) if not isinstance(cwd, Path) else cwd
        cwd_resolved = cwd_path.resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("fast_path is_path_safe: cwd resolve failed: %s", type(exc).__name__)
        return False

    # Resolve target relative to cwd
    try:
        target_path = Path(target)
        if target_path.is_absolute():
            target_resolved = target_path.resolve(strict=False)
        else:
            target_resolved = (cwd_resolved / target_path).resolve(strict=False)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("fast_path is_path_safe: target resolve failed: %s", type(exc).__name__)
        return False

    # Containment check — the primary defense.
    # B6 (wave-1 hardening): replace brittle lowercase string-prefix match
    # with Path.is_relative_to() which compares resolved Path segments and
    # is immune to the /tmp/app vs /tmp/application confusion class that
    # the prefix approach allowed. Python 3.9+.
    try:
        if target_resolved != cwd_resolved and not target_resolved.is_relative_to(cwd_resolved):
            return False
    except (AttributeError, ValueError, OSError):
        # is_relative_to raises ValueError when paths are not comparable
        # (e.g. different drives on Windows). Treat as fail-closed.
        return False

    # Secondary blocklist
    tgt_lower = str(target_resolved).replace("\\", "/").lower()
    for frag in _BLOCKED_FRAGMENTS:
        if frag in tgt_lower:
            return False

    # Reject code files from fast-path (CG-03 handles those via graq_edit)
    _CODE_EXTS = {".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java"}
    if target_resolved.suffix.lower() in _CODE_EXTS:
        return False

    return True


# ─── Public entry point helpers ──────────────────────────────────────────


def is_fast_path_candidate(
    user_message: str,
    cwd,
) -> Optional[FastPathIntent]:
    """Combined classifier + path-safety check.

    Returns the FastPathIntent if the message is a safe fast-path candidate,
    else None. Pure function; no IO.
    """
    intent = classify_intent(user_message)
    if intent is None:
        return None
    if not is_path_safe(intent.target_path, cwd):
        return None
    return intent
