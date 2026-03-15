"""Governance Middleware — Thin audit wrapper for MCP tool calls.

Wraps any MCP handler with automatic audit trail logging.
Each tool call is recorded as an AuditEntry in the active session.

Keeps MCP handlers thin (no governance logic inline) and makes
every reasoning call automatically auditable.

See ADR-105 §Governance Integration.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.governance.middleware
# risk: HIGH (impact radius: 34 modules)
# consumers: sdk_self_audit, adaptive, reformulator, relevance, benchmark_runner +29 more
# dependencies: __future__, json, logging, time, pathlib +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from graqle.intelligence.governance.audit import AuditEntry, AuditSession, AuditTrail
from graqle.intelligence.governance.drace import (
    AuditabilityInput,
    DRACEScorer,
)
from graqle.intelligence.governance.evidence import EvidenceStore

logger = logging.getLogger("graqle.intelligence.governance.middleware")


class GovernanceMiddleware:
    """Wraps MCP tool calls with governance audit + DRACE scoring.

    Usage in MCP server:
        self._gov = GovernanceMiddleware(Path("."))

        async def _handle_reason(self, args):
            session = self._gov.start_or_get_session("Reasoning query")
            result = await actual_reason_logic(args)
            self._gov.log_tool_call(session, "graq_reason", args, result)
            return result

    Each call is ~5 lines of integration. No monolith.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._trail = AuditTrail(root)
        self._evidence_store = EvidenceStore(root)
        self._scorer = DRACEScorer()
        self._active_session: AuditSession | None = None

    def start_session(self, task: str, session_id: str | None = None) -> AuditSession:
        """Start a new governance session for a task."""
        self._active_session = self._trail.start_session(task, session_id)
        return self._active_session

    def get_or_start_session(self, task: str) -> AuditSession:
        """Get active session or start a new one."""
        if self._active_session and self._active_session.status == "active":
            return self._active_session
        return self.start_session(task)

    def log_tool_call(
        self,
        session: AuditSession,
        tool: str,
        args: dict[str, Any],
        result: str | dict[str, Any],
        duration_ms: float = 0.0,
        nodes_consulted: int = 0,
    ) -> AuditEntry:
        """Log an MCP tool call as an audit entry.

        Extracts structured data from args and result to build
        a meaningful audit trail entry.
        """
        # Parse result if it's a JSON string
        if isinstance(result, str):
            try:
                result_data = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                result_data = {"raw": result[:200]}
        else:
            result_data = result

        # Build input summary from args
        input_summary = self._summarize_input(tool, args)

        # Build output summary from result
        output_summary = self._summarize_output(tool, result_data)

        # Count evidence items if present
        evidence_count = 0
        if isinstance(result_data, dict):
            evidence_count += len(result_data.get("constraints", []))
            evidence_count += len(result_data.get("incidents", []))
            evidence_count += len(result_data.get("consumers", []))
            if result_data.get("risk_level"):
                evidence_count += 1

        entry = AuditEntry(
            action=self._tool_to_action(tool),
            tool=tool,
            module=args.get("module", args.get("question", "")[:50]),
            input_summary=input_summary,
            output_summary=output_summary,
            evidence_count=evidence_count,
            nodes_consulted=nodes_consulted or result_data.get("nodes_used", 0),
            duration_ms=duration_ms,
            caller=args.get("caller", ""),
        )

        return self._trail.log_entry(session, entry)

    def complete_session(self, session: AuditSession) -> float | None:
        """Complete session with auto-computed DRACE score."""
        if not session.entries:
            self._trail.complete_session(session)
            return None

        # Build typed DRACE inputs from the audit session
        entries_data = [e.model_dump() for e in session.entries]
        score = self._scorer.score_session(entries_data)

        # Enhance with session-level auditability data
        score.auditability = self._compute_session_auditability(session)
        score.session_id = session.session_id

        drace_total = score.total
        self._trail.complete_session(session, drace_score=drace_total)
        self._active_session = None

        logger.info(
            "Session %s completed — DRACE: %.3f (%s)",
            session.session_id, drace_total, score.grade,
        )
        return drace_total

    def _compute_session_auditability(self, session: AuditSession) -> float:
        """Compute A-pillar from actual AuditSession (typed, not heuristic)."""
        from graqle.intelligence.governance.drace import (
            evaluate_auditability,
        )

        complete = 0
        for e in session.entries:
            if e.input_summary and e.output_summary and e.action and e.timestamp:
                complete += 1

        inp = AuditabilityInput(
            session_entries=len(session.entries),
            complete_entries=complete,
            hash_chain_valid=session.verify_chain(),
            session_persisted=True,
        )
        return evaluate_auditability(inp)

    @staticmethod
    def _tool_to_action(tool: str) -> str:
        """Map MCP tool name to audit action."""
        mapping = {
            "graq_reason": "reason",
            "graq_gate": "gate",
            "graq_impact": "impact",
            "graq_preflight": "verify",
            "graq_context": "context",
            "graq_learn": "learn",
            "graq_lessons": "lessons",
            "graq_inspect": "inspect",
        }
        # Strip kogni_ prefix
        clean = tool.replace("kogni_", "graq_")
        return mapping.get(clean, tool)

    @staticmethod
    def _summarize_input(tool: str, args: dict[str, Any]) -> str:
        """Build a human-readable input summary."""
        if "question" in args:
            return f"Question: {args['question'][:100]}"
        if "module" in args:
            action = args.get("action", "context")
            return f"Module: {args['module']}, Action: {action}"
        if "task" in args:
            return f"Task: {args['task'][:100]}"
        if "operation" in args:
            return f"Operation: {args['operation'][:100]}"
        return json.dumps(args)[:100]

    @staticmethod
    def _summarize_output(tool: str, result: dict[str, Any]) -> str:
        """Build a human-readable output summary."""
        if "error" in result:
            return f"Error: {result['error'][:100]}"
        if "answer" in result:
            return f"Answer: {result['answer'][:100]}"
        if "risk_level" in result:
            parts = [f"Risk: {result['risk_level']}"]
            if "consumer_count" in result:
                parts.append(f"Consumers: {result['consumer_count']}")
            if "impact_radius" in result:
                parts.append(f"Impact: {result['impact_radius']}")
            return ", ".join(parts)
        if "confidence" in result:
            return f"Confidence: {result['confidence']}, Nodes: {result.get('nodes_used', 0)}"
        return json.dumps(result)[:150]
