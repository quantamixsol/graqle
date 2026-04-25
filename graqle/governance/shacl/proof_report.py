"""R22 SGCV — Machine-checkable SHACL proof reports.

Serializes ShaclValidationResult to JSON for audit trail and reproducibility.
The shapes_file_hash links each proof to the exact shape set used.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graqle.governance.shacl.validator import ShaclValidationResult


def generate_proof_report(
    result: ShaclValidationResult,
    trace_id: str,
    shapes_file_hash: str,
) -> dict[str, Any]:
    """Return a JSON-serializable proof report for a validation result."""
    return {
        "trace_id": trace_id,
        "shape_set_version": result.shape_set_version,
        "conforms": result.conforms,
        "violations": [
            {
                "shape": v.shape,
                "path": v.path,
                "message": v.message,
                "value": str(v.value) if v.value is not None else None,
            }
            for v in result.violations
        ],
        "validated_at": result.validated_at,
        "shapes_file_hash": shapes_file_hash,
    }


def save_proof_report(report: dict[str, Any], output_path: Path) -> None:
    """Append a proof report to the audit log (append-only JSONL)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report) + "\n")
