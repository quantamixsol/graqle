"""EU AI Act mode switch — consolidated status report.

This module assembles a single, JSON-serialisable view of every
EU-AI-Act-mode-aware subsystem so an operator (or their CI) can answer
*one* question with *one* call: **what is the effective EU AI Act
posture of this GraQle install, right now?**

The eight subsystems surfaced:

1. ``eu_ai_act_mode`` — the master env-var toggle (``GRAQLE_EU_AI_ACT_MODE``).
2. ``ai_disclosure`` — Article 50 user-disclosure banner state.
3. ``article_14_human_review_gate`` — Article 14(4)(c)+(d) confidence gate.
4. ``claim_limits`` — R25-EU11 v1.0 taxonomy state.
5. ``baseline_document`` — VERITAS Q16.1 baseline-doc surface state.
6. ``periodic_assessment`` — VERITAS Q16.3 quality-metric thresholds.
7. ``feedback_trend`` — VERITAS Q16.5 OBSERVATION-ONLY drift watcher.
8. ``eur_lex_drift_guard`` — Weekly EUR-Lex content-hash baseline.

The data is **read-only** — this module never writes config or env
state. Callers that need to *flip* the switch must do that in the
user's shell (``export GRAQLE_EU_AI_ACT_MODE=on``) — that's the
trust boundary, not a CLI side effect.

Design notes:

- No subsystem import is allowed to fail the assembly. Every probe
  wraps in try/except and degrades to ``"unavailable"`` rather than
  raising. The whole point of this surface is "tell me what's
  actually present" — if a subsystem isn't importable, that itself
  is the answer.

- The output schema is **versioned** (``schema_version`` field).
  Bumping it requires a CHANGELOG entry; consumers can pin against
  the version to fail their CI loudly when the shape changes.

- No trade-secret references (TS-1..TS-4). Every threshold here is
  a public spec value documented under ``docs/compliance/``.

References:
    - CG-MKT-01..06 (closed by CR-010)
    - ADR-MARKETING-001 §11 (positioning constitution)
    - docs/compliance/eu-ai-act/README.md
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

#: Schema version. Bump on any output-shape change.
SWITCH_STATUS_SCHEMA_VERSION: str = "1.0"


def _probe_master_switch() -> dict[str, Any]:
    """Return the master env-var state."""
    raw = os.environ.get("GRAQLE_EU_AI_ACT_MODE", "")
    truthy_set = {"on", "true", "1", "yes"}
    is_on = raw.strip().lower() in truthy_set
    return {
        "env_var": "GRAQLE_EU_AI_ACT_MODE",
        "raw_value": raw,
        "is_on": is_on,
        "truthy_values_accepted": sorted(truthy_set),
    }


def _probe_ai_disclosure() -> dict[str, Any]:
    """Return Article 50 disclosure state."""
    try:
        from graqle.compliance.disclosure import (
            is_ai_disclosure_suppressed,
            is_eu_ai_act_mode_on,
        )
        return {
            "subsystem": "article_50_user_disclosure",
            "armed": is_eu_ai_act_mode_on(),
            "banner_suppressed": is_ai_disclosure_suppressed(),
            "machine_envelope_field": "ai_disclosure",
            "env_var_for_banner_suppression": "GRAQLE_AI_DISCLOSURE",
            "anchor": "EU AI Act Article 50(1)",
        }
    except ImportError as exc:
        return {
            "subsystem": "article_50_user_disclosure",
            "status": "unavailable",
            "error": str(exc),
        }


def _probe_article_14_gate() -> dict[str, Any]:
    """Return Article 14 human-review gate state."""
    try:
        from graqle.compliance.article_14_gate import (
            ARTICLE_14_CLAUSES,
            DEFAULT_HUMAN_REVIEW_THRESHOLD,
            THRESHOLD_STATUS_PLACEHOLDER,
            _is_eu_ai_act_mode_on,
        )
        return {
            "subsystem": "article_14_human_review_gate",
            "armed": _is_eu_ai_act_mode_on(),
            "default_threshold": DEFAULT_HUMAN_REVIEW_THRESHOLD,
            "threshold_status": THRESHOLD_STATUS_PLACEHOLDER,
            "clauses": list(ARTICLE_14_CLAUSES),
            "refusal_error_code": "ARTICLE_14_HUMAN_REVIEW_REQUIRED",
            "affected_tools": ["graq_edit", "graq_apply", "graq_auto"],
            "calibration_followup": "R25-EU-CALIB-01 spike (replaces 0.75 placeholder)",
        }
    except ImportError as exc:
        return {
            "subsystem": "article_14_human_review_gate",
            "status": "unavailable",
            "error": str(exc),
        }


def _probe_claim_limits() -> dict[str, Any]:
    """Return R25-EU11 claim-limits taxonomy state."""
    try:
        from graqle.compliance.claim_limits.taxonomy import (
            CANONICAL_CLAIM_LIMITS,
            CLAIM_LIMITS_TAXONOMY_VERSION,
            LEGACY_BACKFILL_VALUE,
            X_PREFIX,
        )
        return {
            "subsystem": "claim_limits_default_deny",
            "armed": True,  # always-on once shipped — not env-gated
            "taxonomy_version": CLAIM_LIMITS_TAXONOMY_VERSION,
            "canonical_value_count": len(CANONICAL_CLAIM_LIMITS),
            "extension_namespace": X_PREFIX,
            "backfill_sentinel": LEGACY_BACKFILL_VALUE,
            "enforcement": ["L08_SHACL_ClaimLimitsRequired", "L19_audit_trail"],
            "anchor": "R25-EU11 v1.0 (Ricky Jones / TrinityOS LinkedIn 2026-05-13)",
        }
    except ImportError as exc:
        return {
            "subsystem": "claim_limits_default_deny",
            "status": "unavailable",
            "error": str(exc),
        }


def _probe_baseline_document() -> dict[str, Any]:
    """Return Q16.1 baseline-document surface state."""
    try:
        from graqle.compliance.baseline_doc import (
            DEFAULT_ARTICLES_COVERED,
            DEFAULT_ISO_42001_CLAUSES,
            PROOF_FORMAT_VERSION,
        )
        # Look for an existing baseline log under .graqle/baseline-docs/
        baseline_dir = Path(".graqle") / "baseline-docs"
        recent_logs: list[str] = []
        try:
            if baseline_dir.exists():
                recent_logs = sorted(
                    p.name for p in baseline_dir.glob("*.jsonl")
                )[-5:]
        except (PermissionError, OSError):
            pass
        return {
            "subsystem": "veritas_q161_baseline_document",
            "armed": True,
            "proof_format_version": PROOF_FORMAT_VERSION,
            "default_articles_covered": list(DEFAULT_ARTICLES_COVERED),
            "default_iso_42001_clauses": list(DEFAULT_ISO_42001_CLAUSES),
            "cli_command": "graq compliance baseline-doc generate",
            "default_output_dir": str(baseline_dir),
            "recent_baseline_logs": recent_logs,
            "anchor": "EU AI Act Article 11 + ISO 42001 Cl. 6.2 + VERITAS Q16.1",
        }
    except ImportError as exc:
        return {
            "subsystem": "veritas_q161_baseline_document",
            "status": "unavailable",
            "error": str(exc),
        }


def _probe_periodic_assessment() -> dict[str, Any]:
    """Return Q16.3 periodic-assessment threshold state."""
    try:
        from graqle.compliance.periodic_assessment import (
            THRESHOLD_DEGRADED_RATE,
            THRESHOLD_LOW_MEAN_CONFIDENCE,
            THRESHOLD_OUTCOME_NOT_OK_RATE,
        )
        # Look for existing assessment logs
        assessment_dir = Path(".graqle") / "periodic-assessments"
        recent_logs: list[str] = []
        try:
            if assessment_dir.exists():
                recent_logs = sorted(
                    p.name for p in assessment_dir.glob("*.jsonl")
                )[-5:]
        except (PermissionError, OSError):
            pass
        return {
            "subsystem": "veritas_q163_periodic_assessment",
            "armed": True,
            "thresholds": {
                "outcome_not_ok_rate_high_severity": THRESHOLD_OUTCOME_NOT_OK_RATE,
                "degraded_rate_warn_severity": THRESHOLD_DEGRADED_RATE,
                "mean_confidence_warn_severity_below": THRESHOLD_LOW_MEAN_CONFIDENCE,
            },
            "cadence_options": ["monthly", "quarterly", "annual"],
            "cli_command": "graq compliance periodic-assessment run",
            "default_output_dir": str(assessment_dir),
            "recent_assessment_logs": recent_logs,
            "anchor": "EU AI Act Article 9 + ISO 42001 Cl. 9.1 + VERITAS Q16.3",
        }
    except ImportError as exc:
        return {
            "subsystem": "veritas_q163_periodic_assessment",
            "status": "unavailable",
            "error": str(exc),
        }


def _probe_feedback_trend() -> dict[str, Any]:
    """Return Q16.5 OBSERVATION-ONLY feedback-trend state."""
    try:
        from graqle.compliance.evidence_state import (
            DRIFT_ALARM_SIGMA,
        )
        feedback_log = Path(".graqle") / "feedback" / "feedback.jsonl"
        record_count = 0
        try:
            if feedback_log.exists():
                # Cheap line count — open + iterate, no parsing
                with feedback_log.open("r", encoding="utf-8") as f:
                    record_count = sum(1 for _ in f)
        except (PermissionError, OSError):
            pass
        return {
            "subsystem": "veritas_q165_feedback_trend",
            "armed": True,
            "mode": "OBSERVATION_ONLY",
            "patent_novelty_boundary": "Q-PATENT 2026-05-22 — drift is observation, never a trigger",
            "audit_test": "tests/test_compliance/test_q165_no_active_recalibration_path.py",
            "drift_alarm_sigma": DRIFT_ALARM_SIGMA,
            "cli_record_command": "graq compliance feedback record",
            "cli_ingest_command": "graq compliance feedback ingest",
            "default_log_path": str(feedback_log),
            "record_count": record_count,
            "anchor": "VERITAS Q16.5 + EP26167849.4 Claim 4 (cross-call, not per-call)",
        }
    except ImportError as exc:
        return {
            "subsystem": "veritas_q165_feedback_trend",
            "status": "unavailable",
            "error": str(exc),
        }


def _probe_eur_lex_drift_guard() -> dict[str, Any]:
    """Return EUR-Lex drift-guard baseline state."""
    try:
        from graqle.compliance.eur_lex_guard import (
            DEFAULT_BASELINE_PATH,
            FETCH_TIMEOUT_SECONDS,
            MAX_RESPONSE_BYTES,
            USER_AGENT,
            load_baseline,
        )
        baseline_path = Path(DEFAULT_BASELINE_PATH)
        baseline_present = baseline_path.exists()
        baseline_entry_count = 0
        if baseline_present:
            try:
                baseline_entry_count = len(load_baseline(baseline_path))
            except (ValueError, OSError):
                baseline_entry_count = -1  # corrupt
        return {
            "subsystem": "eur_lex_drift_guard",
            "armed": True,
            "baseline_path": DEFAULT_BASELINE_PATH,
            "baseline_present": baseline_present,
            "baseline_entry_count": baseline_entry_count,
            "fetch_timeout_seconds": FETCH_TIMEOUT_SECONDS,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "user_agent": USER_AGENT,
            "cli_check_command": "graq compliance eur-lex-check",
            "cli_refresh_command": "graq compliance eur-lex-refresh",
            "workflow_cron": "0 6 * * 1 (Mondays 06:00 UTC)",
            "workflow_path": ".github/workflows/eur-lex-weekly.yml",
        }
    except ImportError as exc:
        return {
            "subsystem": "eur_lex_drift_guard",
            "status": "unavailable",
            "error": str(exc),
        }


def build_switch_status() -> dict[str, Any]:
    """Build the full consolidated switch-status envelope.

    Returns a JSON-serialisable dict with seven subsystem probes plus
    a top-level summary. Safe to call from any context — never raises.

    Semantics of the ``armed`` field per subsystem (sentinel pass 3 INFO):

      - ``ai_disclosure.armed`` — **env-gated**: True iff
        ``GRAQLE_EU_AI_ACT_MODE`` is truthy. Reflects whether the
        Article 50 banner + machine envelope field will be emitted on
        the next reasoning call.
      - ``article_14_human_review_gate.armed`` — **env-gated**: same
        as ``ai_disclosure``. Reflects whether the gate will refuse
        low-confidence auto-apply.
      - ``claim_limits.armed`` — **always-on once shipped**. The L08
        SHACL constraint + L19 audit-trail check fire regardless of
        EU AI Act mode.
      - ``baseline_document.armed`` — **always-on**. The CLI surface
        is available regardless of mode.
      - ``periodic_assessment.armed`` — **always-on**. Same.
      - ``feedback_trend.armed`` — **always-on, OBSERVATION-ONLY**.
        The patent-novelty boundary means this is true regardless of
        mode.
      - ``eur_lex_drift_guard.armed`` — **always-on**. The weekly
        workflow runs unconditionally.

    Read ``armed`` as "would this subsystem engage if invoked", not as
    "is the master EU AI Act mode flag flipped on" — that's
    ``master_switch.is_on``.

    Schema:

        {
          "schema_version": "1.0",
          "master_switch": {...},
          "subsystems": {
            "ai_disclosure": {...},
            "article_14_human_review_gate": {...},
            "claim_limits": {...},
            "baseline_document": {...},
            "periodic_assessment": {...},
            "feedback_trend": {...},
            "eur_lex_drift_guard": {...},
          },
          "summary": {
            "master_switch_on": bool,
            "subsystems_total": int,
            "subsystems_available": int,
            "subsystems_armed_when_mode_on": int,
          }
        }
    """
    master = _probe_master_switch()
    subsystems = {
        "ai_disclosure": _probe_ai_disclosure(),
        "article_14_human_review_gate": _probe_article_14_gate(),
        "claim_limits": _probe_claim_limits(),
        "baseline_document": _probe_baseline_document(),
        "periodic_assessment": _probe_periodic_assessment(),
        "feedback_trend": _probe_feedback_trend(),
        "eur_lex_drift_guard": _probe_eur_lex_drift_guard(),
    }
    # Sentinel pass 1 MINOR — defensive summary against unexpected probe shape.
    # `s` should always be a dict (every _probe_* returns one), but if a
    # future probe drifts off-spec we want the summary to degrade gracefully
    # rather than crash the regulator-readable surface.
    available = sum(
        1 for s in subsystems.values()
        if isinstance(s, dict) and "status" not in s
    )
    armed_count = sum(
        1 for s in subsystems.values()
        if isinstance(s, dict) and s.get("armed") is True
    )
    return {
        "schema_version": SWITCH_STATUS_SCHEMA_VERSION,
        "master_switch": master,
        "subsystems": subsystems,
        "summary": {
            # Sentinel pass 3 MINOR — defensive .get() even though
            # _probe_master_switch always populates "is_on". Trivial
            # cost; eliminates any KeyError surface.
            "master_switch_on": master.get("is_on", False),
            "subsystems_total": len(subsystems),
            "subsystems_available": available,
            "subsystems_armed_when_mode_on": armed_count,
        },
    }
