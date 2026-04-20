"""Alpha-validation harness conftest — session-scoped report + shared fixtures.

Reuses the battle-tested `fresh_server` / `server_with_session` /
`server_with_plan` fixtures from gate-demos/conftest.py (real
KogniDevServer, zero mocks). Adds:

- `alpha_report`: session-scoped dict that each test appends its result
  to. Flushed to `alpha_report.json` at session end.
- `tmp_workspace`: factory for clean per-test temp directories that
  simulate a fresh user project.
- `demo_payload`: helpers for building realistic-but-fake test inputs
  (file diffs, memory writes, PR payloads).
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# Reuse gate-demos fixtures — same server instance as production MCP
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "gate-demos"))
# noinspection PyUnresolvedReferences
from conftest import fresh_server, server_with_session, server_with_plan  # noqa: E402,F401

HARNESS_DIR = Path(__file__).parent
REPORT_PATH = HARNESS_DIR / "alpha_report.json"

# Module-level singleton — survives pytest fixture teardown so
# pytest_sessionfinish can still flush to disk.
_REPORT_SINGLETON: dict[str, Any] | None = None


def _new_report() -> dict[str, Any]:
    try:
        from graqle.__version__ import __version__ as sdk_version
    except Exception:
        sdk_version = "unknown"
    return {
        "sdk_version": sdk_version,
        "python_version": platform.python_version(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": 0.0,
        "items": [],
        "summary": {
            "total": 13,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errored": 0,
            "gate_verdict": "PENDING",
            "blocked_release_targets": [],
        },
        "_start_time": time.monotonic(),
    }


@pytest.fixture(scope="session")
def alpha_report() -> dict[str, Any]:
    """Session-scoped collector. Each test appends to `items`."""
    global _REPORT_SINGLETON
    if _REPORT_SINGLETON is None:
        _REPORT_SINGLETON = _new_report()
    return _REPORT_SINGLETON


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Factory — fresh temp directory simulating a user's project root."""
    ws = tmp_path / "user_project"
    ws.mkdir()
    return ws


class DemoPayload:
    """Builders for realistic-but-fake demo inputs."""

    @staticmethod
    def memory_write(name: str = "demo_fact") -> dict[str, Any]:
        return {
            "path": f"feedback_{name}.md",
            "name": name,
            "description": "synthetic demo fact for alpha validation",
            "type": "feedback",
            "content": "Demo rule: alpha harness verifies governance gates end-to-end.",
        }

    @staticmethod
    def release_diff() -> str:
        return (
            "diff --git a/src/hello.py b/src/hello.py\n"
            "index abc..def 100644\n"
            "--- a/src/hello.py\n"
            "+++ b/src/hello.py\n"
            "@@ -1,3 +1,4 @@\n"
            " def hello():\n"
            "-    return 'hi'\n"
            "+    return 'hello world'\n"
            "+    # demo change for alpha validation\n"
        )

    @staticmethod
    def fast_path_file_create(ws: Path, name: str = "notes.txt") -> dict[str, Any]:
        return {
            "path": str(ws / name),
            "content": "demo content — not a code file, safe for fast path",
        }


@pytest.fixture
def demo() -> type:
    """Alias fixture so tests read naturally: `demo.memory_write()`."""
    return DemoPayload


def record_item(
    report: dict[str, Any],
    item_id: str,
    name: str,
    status: str,
    assertions: int = 0,
    duration_ms: int = 0,
    evidence: dict[str, Any] | None = None,
    failure_reason: str | None = None,
    tracker: str | None = None,
) -> None:
    """Helper for tests to append a structured result."""
    report["items"].append(
        {
            "id": item_id,
            "name": name,
            "status": status,
            "assertions": assertions,
            "duration_ms": duration_ms,
            "evidence": evidence or {},
            "failure_reason": failure_reason,
            "tracker": tracker,
        }
    )


@pytest.fixture
def record(alpha_report: dict[str, Any]):
    """Callable fixture — tests call `record(item_id, name, ...)` directly."""
    def _record(**kwargs):
        record_item(alpha_report, **kwargs)
    return _record


def pytest_sessionfinish(session, exitstatus):
    """Flush report to alpha_report.json at session end."""
    report = _REPORT_SINGLETON
    if report is None:
        return  # no alpha test ran — don't write an empty report

    # Finalize summary
    report["runtime_seconds"] = round(time.monotonic() - report.pop("_start_time"), 2)
    statuses = [it["status"] for it in report["items"]]
    report["summary"]["passed"] = statuses.count("PASS")
    report["summary"]["failed"] = statuses.count("FAIL")
    report["summary"]["skipped"] = statuses.count("SKIP")
    report["summary"]["errored"] = statuses.count("ERROR")

    if report["summary"]["failed"] == 0 and report["summary"]["errored"] == 0:
        report["summary"]["gate_verdict"] = "CLEAR"
    else:
        report["summary"]["gate_verdict"] = "INSUFFICIENT"
        report["summary"]["blocked_release_targets"] = ["pypi", "vscode-marketplace"]

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
