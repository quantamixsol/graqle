"""CG-14 Config Drift Auditor tests (Wave 2 Phase 3).

Covers:
  - Detection helper: hash file, symlinks, permission errors (6)
  - Baseline lifecycle: first-run, clean, corrupted, schema (8)
  - Accept workflow: success, unknown file, missing file, timestamp (5)
  - Concurrency: thread-safe audit, accept vs audit, atomic save (4)
  - Path resolution: custom root, baseline override (2)
  - Edge cases: empty + duplicate protected_files, extra fields (3)
  - MCP handler: schema, audit, accept validation, error envelopes (7)
  - Public API + sanitization (3)

Spec: Wave 2 Plan v1.1 §2.1 CG-14.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.governance import (
    BaselineCorruptedError,
    ConfigDriftAuditor,
    DriftRecord,
    FileReadError,
)
from graqle.governance import config_drift as cd_mod
from graqle.governance.config_drift import (
    BASELINE_SCHEMA_VERSION,
    DEFAULT_PROTECTED_FILES,
    _hash_file,
    _sanitize,
    _validate_baseline,
    build_accept_response,
    build_audit_response,
    build_error_envelope,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Temp directory with all 4 default protected files populated."""
    (tmp_path / "graqle.yaml").write_text("model:\n  backend: local\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n', encoding="utf-8")
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def auditor(tmp_repo: Path) -> ConfigDriftAuditor:
    return ConfigDriftAuditor(root=tmp_repo)


# ─────────────────────────────────────────────────────────────────────────
# 1-6. Detection helper: _hash_file, symlinks, errors
# ─────────────────────────────────────────────────────────────────────────


def test_hash_file_returns_sha256(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert _hash_file(f) == expected


def test_hash_file_empty_file(tmp_path: Path):
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    assert _hash_file(f) == hashlib.sha256(b"").hexdigest()


def test_hash_file_missing_raises_filenotfounderror(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        _hash_file(tmp_path / "nope.txt")


def test_hash_file_directory_raises_filereaderror(tmp_path: Path):
    """Opening a directory for read raises IsADirectoryError -> FileReadError."""
    d = tmp_path / "dir"
    d.mkdir()
    with pytest.raises(FileReadError):
        _hash_file(d)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_hash_file_broken_symlink_raises_filenotfounderror(tmp_path: Path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "does-not-exist")
    with pytest.raises(FileNotFoundError):
        _hash_file(link)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_hash_file_valid_symlink_hashes_through_target(tmp_path: Path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"hello")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert _hash_file(link) == hashlib.sha256(b"hello").hexdigest()


# ─────────────────────────────────────────────────────────────────────────
# 7-14. Baseline lifecycle: first-run, clean, corrupted, schema
# ─────────────────────────────────────────────────────────────────────────


def test_first_audit_creates_baseline_and_emits_baseline_missing(auditor, tmp_repo):
    records = auditor.audit()
    assert (tmp_repo / ".graqle" / "config_baseline.json").exists()
    assert len(records) == 4
    assert all(r.drift_type == "baseline_missing" for r in records)
    assert all(r.severity == "medium" for r in records)
    assert all(r.requires_review for r in records)


def test_second_audit_after_first_run_is_clean(auditor):
    auditor.audit()  # create baseline
    records = auditor.audit()
    assert records == []


def test_modified_file_is_detected(auditor, tmp_repo):
    auditor.audit()
    (tmp_repo / "graqle.yaml").write_text("model:\n  backend: openai\n", encoding="utf-8")
    records = auditor.audit()
    assert len(records) == 1
    r = records[0]
    assert r.file_path == "graqle.yaml"
    assert r.drift_type == "modified"
    assert "hash changed" in r.diff_summary


def test_missing_file_is_detected(auditor, tmp_repo):
    auditor.audit()
    (tmp_repo / "graqle.yaml").unlink()
    records = auditor.audit()
    missing = [r for r in records if r.drift_type == "missing"]
    assert len(missing) == 1
    assert missing[0].file_path == "graqle.yaml"
    assert missing[0].severity == "high"


def test_first_run_mixed_missing_readable(tmp_repo: Path):
    # Delete one protected file BEFORE first audit
    (tmp_repo / ".mcp.json").unlink()
    auditor = ConfigDriftAuditor(root=tmp_repo)
    records = auditor.audit()
    # 3 readable -> baseline_missing, 1 absent -> missing
    types = sorted(r.drift_type for r in records)
    assert types == ["baseline_missing", "baseline_missing", "baseline_missing", "missing"]
    # Baseline should contain entries ONLY for the 3 readable files
    baseline = json.loads((tmp_repo / ".graqle" / "config_baseline.json").read_text(encoding="utf-8"))
    assert set(baseline["entries"].keys()) == {"graqle.yaml", "pyproject.toml", ".claude/settings.json"}


def test_baseline_corrupted_emits_drift_for_all(auditor, tmp_repo):
    auditor.audit()
    # Corrupt the baseline
    baseline_path = tmp_repo / ".graqle" / "config_baseline.json"
    baseline_path.write_text("not valid json {{{", encoding="utf-8")
    records = auditor.audit()
    assert len(records) == 4
    assert all(r.drift_type == "baseline_corrupted" for r in records)
    assert all(r.severity == "high" for r in records)


def test_baseline_wrong_schema_version_is_corrupted(auditor, tmp_repo):
    auditor.audit()
    baseline_path = tmp_repo / ".graqle" / "config_baseline.json"
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    data["schema_version"] = 99
    baseline_path.write_text(json.dumps(data), encoding="utf-8")
    records = auditor.audit()
    assert all(r.drift_type == "baseline_corrupted" for r in records)


def test_baseline_non_dict_entries_is_corrupted(auditor, tmp_repo):
    auditor.audit()
    baseline_path = tmp_repo / ".graqle" / "config_baseline.json"
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    data["entries"] = "not a dict"
    baseline_path.write_text(json.dumps(data), encoding="utf-8")
    records = auditor.audit()
    assert all(r.drift_type == "baseline_corrupted" for r in records)


def test_baseline_bad_sha256_length_is_corrupted(auditor, tmp_repo):
    auditor.audit()
    baseline_path = tmp_repo / ".graqle" / "config_baseline.json"
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    first_key = next(iter(data["entries"]))
    data["entries"][first_key]["sha256"] = "tooshort"
    baseline_path.write_text(json.dumps(data), encoding="utf-8")
    records = auditor.audit()
    assert all(r.drift_type == "baseline_corrupted" for r in records)


def test_baseline_malformed_iso8601_is_corrupted(auditor, tmp_repo):
    auditor.audit()
    baseline_path = tmp_repo / ".graqle" / "config_baseline.json"
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    first_key = next(iter(data["entries"]))
    data["entries"][first_key]["approved_at"] = "not-a-timestamp"
    baseline_path.write_text(json.dumps(data), encoding="utf-8")
    records = auditor.audit()
    assert all(r.drift_type == "baseline_corrupted" for r in records)


def test_new_protected_file_after_baseline_is_detected(tmp_repo):
    # First audit with reduced protected list
    auditor1 = ConfigDriftAuditor(root=tmp_repo, protected_files=["graqle.yaml"])
    auditor1.audit()
    auditor1.accept("graqle.yaml", "test-approver")  # clean baseline
    # Second audit with expanded list
    auditor2 = ConfigDriftAuditor(
        root=tmp_repo, protected_files=["graqle.yaml", "pyproject.toml"],
    )
    records = auditor2.audit()
    new_rec = [r for r in records if r.drift_type == "new_protected"]
    assert len(new_rec) == 1
    assert new_rec[0].file_path == "pyproject.toml"


# ─────────────────────────────────────────────────────────────────────────
# 15-19. Accept workflow
# ─────────────────────────────────────────────────────────────────────────


def test_accept_updates_baseline_makes_file_clean(auditor, tmp_repo):
    auditor.audit()
    (tmp_repo / "graqle.yaml").write_text("# new content\n", encoding="utf-8")
    assert len(auditor.audit()) == 1  # modified
    auditor.accept("graqle.yaml", "reviewer-alice")
    assert auditor.audit() == []  # now clean


def test_accept_records_approver_and_iso8601_timestamp(auditor, tmp_repo):
    auditor.audit()
    auditor.accept("graqle.yaml", "reviewer-alice")
    baseline = json.loads((tmp_repo / ".graqle" / "config_baseline.json").read_text(encoding="utf-8"))
    entry = baseline["entries"]["graqle.yaml"]
    assert entry["approver"] == "reviewer-alice"
    # ISO-8601 with Z suffix
    ts = entry["approved_at"]
    assert ts.endswith("Z")
    datetime.fromisoformat(ts.replace("Z", "+00:00"))  # no exception = valid


def test_accept_unknown_file_raises_valueerror(auditor):
    with pytest.raises(ValueError, match="not in protected_files"):
        auditor.accept("random.txt", "reviewer")


def test_accept_missing_file_raises_filenotfounderror(auditor, tmp_repo):
    (tmp_repo / "graqle.yaml").unlink()
    with pytest.raises(FileNotFoundError):
        auditor.accept("graqle.yaml", "reviewer")


def test_accept_empty_approver_raises_valueerror(auditor):
    with pytest.raises(ValueError, match="non-empty"):
        auditor.accept("graqle.yaml", "")


# ─────────────────────────────────────────────────────────────────────────
# 20-23. Concurrency: thread safety + atomic write
# ─────────────────────────────────────────────────────────────────────────


def test_concurrent_audits_no_corruption(auditor):
    auditor.audit()  # prime baseline
    results: list[list] = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        r = auditor.audit()
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    # Baseline exists + is clean -> all audits return []
    assert all(r == [] for r in results)


def test_concurrent_accept_vs_audit_no_corruption(auditor, tmp_repo):
    auditor.audit()
    errors: list[Exception] = []
    barrier = threading.Barrier(4)

    def audit_worker():
        try:
            barrier.wait()
            for _ in range(5):
                auditor.audit()
        except Exception as e:
            errors.append(e)

    def accept_worker():
        try:
            barrier.wait()
            for _ in range(5):
                auditor.accept("graqle.yaml", "reviewer")
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=audit_worker),
        threading.Thread(target=audit_worker),
        threading.Thread(target=accept_worker),
        threading.Thread(target=accept_worker),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Final state: baseline valid JSON, parseable
    baseline = json.loads((tmp_repo / ".graqle" / "config_baseline.json").read_text(encoding="utf-8"))
    assert baseline["schema_version"] == BASELINE_SCHEMA_VERSION


def test_atomic_save_replace_failure_preserves_baseline(auditor, tmp_repo):
    """If os.replace raises, original baseline is unchanged + tmp is cleaned."""
    auditor.audit()  # create baseline
    baseline_path = tmp_repo / ".graqle" / "config_baseline.json"
    original = baseline_path.read_bytes()

    # Modify the file to trigger a baseline update, then monkeypatch os.replace
    (tmp_repo / "graqle.yaml").write_text("# modified\n", encoding="utf-8")
    with patch.object(os, "replace", side_effect=OSError("simulated rename failure")):
        with pytest.raises(OSError, match="simulated rename failure"):
            auditor.accept("graqle.yaml", "reviewer")

    # Baseline unchanged
    assert baseline_path.read_bytes() == original
    # No orphaned .tmp files
    tmp_files = list(baseline_path.parent.glob(".config_baseline.*.tmp"))
    assert tmp_files == []


def test_save_baseline_creates_parent_dir(tmp_path: Path):
    """Baseline parent directory is created if missing."""
    baseline = tmp_path / "nested" / "dir" / "baseline.json"
    assert not baseline.parent.exists()
    (tmp_path / "graqle.yaml").write_text("x\n", encoding="utf-8")
    auditor = ConfigDriftAuditor(
        root=tmp_path,
        baseline_path=baseline,
        protected_files=["graqle.yaml"],
    )
    auditor.audit()
    assert baseline.exists()


# ─────────────────────────────────────────────────────────────────────────
# 24-25. Path resolution
# ─────────────────────────────────────────────────────────────────────────


def test_custom_baseline_path_overrides_default(tmp_path: Path):
    (tmp_path / "graqle.yaml").write_text("x", encoding="utf-8")
    custom = tmp_path / "custom_baseline.json"
    auditor = ConfigDriftAuditor(
        root=tmp_path,
        baseline_path=custom,
        protected_files=["graqle.yaml"],
    )
    auditor.audit()
    assert custom.exists()
    # Default location NOT created
    assert not (tmp_path / ".graqle" / "config_baseline.json").exists()


def test_baseline_path_is_absolute_after_init(tmp_path: Path):
    auditor = ConfigDriftAuditor(root=tmp_path)
    assert auditor.baseline_path.is_absolute()
    assert auditor.root.is_absolute()


# ─────────────────────────────────────────────────────────────────────────
# 26-28. Edge cases
# ─────────────────────────────────────────────────────────────────────────


def test_empty_protected_files_returns_empty_drift(tmp_path: Path):
    auditor = ConfigDriftAuditor(root=tmp_path, protected_files=[])
    assert auditor.audit() == []


def test_duplicate_protected_files_deduplicated(tmp_path: Path):
    (tmp_path / "graqle.yaml").write_text("x", encoding="utf-8")
    auditor = ConfigDriftAuditor(
        root=tmp_path, protected_files=["graqle.yaml", "graqle.yaml", "  ", "graqle.yaml"],
    )
    assert auditor.protected_files == ("graqle.yaml",)


def test_default_protected_files_unchanged():
    # Back-compat: the default tuple hasn't changed shape
    assert DEFAULT_PROTECTED_FILES == (
        "graqle.yaml",
        "pyproject.toml",
        ".mcp.json",
        ".claude/settings.json",
    )


# ─────────────────────────────────────────────────────────────────────────
# 29-35. MCP handler: schema + validation + error envelopes
# ─────────────────────────────────────────────────────────────────────────


def test_mcp_tool_definition_shape():
    import graqle.plugins.mcp_dev_server as mcp

    tool = next((t for t in mcp.TOOL_DEFINITIONS if t["name"] == "graq_config_audit"), None)
    assert tool is not None
    schema = tool["inputSchema"]
    assert schema["type"] == "object"
    props = schema["properties"]
    assert props["action"]["enum"] == ["audit", "accept"]
    assert props["action"]["default"] == "audit"
    assert "file" in props
    assert "approver" in props
    assert schema["required"] == []


def test_mcp_tool_count_increased_by_one():
    """Adding graq_config_audit without removing anything."""
    import graqle.plugins.mcp_dev_server as mcp

    names = [t["name"] for t in mcp.TOOL_DEFINITIONS]
    assert "graq_config_audit" in names
    assert "graq_audit" in names  # pre-existing, unchanged
    # No duplicate entries
    assert len(names) == len(set(names))


@pytest.mark.asyncio
async def test_handler_invalid_action_returns_error_envelope():
    import graqle.plugins.mcp_dev_server as mcp

    # Minimal fake server — we only need the _handle_config_audit method bound
    class _FakeServer:
        _graph_file = None
    server = _FakeServer()
    result_json = await mcp.KogniDevServer._handle_config_audit(
        server, {"action": "delete"},
    )
    result = json.loads(result_json)
    assert result["error"] == "CG-14_INVALID_ACTION"


@pytest.mark.asyncio
async def test_handler_accept_missing_file_returns_validation_error():
    import graqle.plugins.mcp_dev_server as mcp

    class _FakeServer:
        _graph_file = None
    server = _FakeServer()
    result = json.loads(await mcp.KogniDevServer._handle_config_audit(
        server, {"action": "accept", "approver": "alice"},
    ))
    assert result["error"] == "CG-14_VALIDATION"
    assert result["field"] == "file"


@pytest.mark.asyncio
async def test_handler_accept_missing_approver_returns_validation_error():
    import graqle.plugins.mcp_dev_server as mcp

    class _FakeServer:
        _graph_file = None
    server = _FakeServer()
    result = json.loads(await mcp.KogniDevServer._handle_config_audit(
        server, {"action": "accept", "file": "graqle.yaml"},
    ))
    assert result["error"] == "CG-14_VALIDATION"
    assert result["field"] == "approver"


@pytest.mark.asyncio
async def test_handler_audit_returns_drift_response(tmp_repo, monkeypatch):
    import graqle.plugins.mcp_dev_server as mcp

    # Point the handler at tmp_repo by mocking ConfigDriftAuditor's default root
    monkeypatch.chdir(tmp_repo)

    class _FakeServer:
        _graph_file = None
    server = _FakeServer()
    result = json.loads(await mcp.KogniDevServer._handle_config_audit(
        server, {"action": "audit"},
    ))
    assert result["action"] == "audit"
    assert "drift_records" in result
    assert "total_drift" in result
    # First-run: 4 files, all baseline_missing
    assert result["total_drift"] == 4


@pytest.mark.asyncio
async def test_handler_accept_rejects_path_traversal():
    """MAJOR-2 hardening: '..' traversal + absolute paths blocked at handler."""
    import graqle.plugins.mcp_dev_server as mcp

    class _FakeServer:
        _graph_file = None
    server = _FakeServer()

    for bad in ("../../../etc/passwd", "foo/../../bar", "/etc/passwd", "C:\\Windows\\hosts"):
        result = json.loads(await mcp.KogniDevServer._handle_config_audit(
            server, {"action": "accept", "file": bad, "approver": "alice"},
        ))
        assert result["error"] == "CG-14_INVALID_FILE_PATH", f"failed to block: {bad}"


@pytest.mark.asyncio
async def test_handler_accept_unknown_file_returns_unknown_file_envelope(tmp_repo, monkeypatch):
    import graqle.plugins.mcp_dev_server as mcp

    monkeypatch.chdir(tmp_repo)

    class _FakeServer:
        _graph_file = None
    server = _FakeServer()
    result = json.loads(await mcp.KogniDevServer._handle_config_audit(
        server, {"action": "accept", "file": "random.txt", "approver": "alice"},
    ))
    assert result["error"] == "CG-14_UNKNOWN_FILE"
    assert result["file"] == "random.txt"


# ─────────────────────────────────────────────────────────────────────────
# 36-38. Public API + sanitization + back-compat
# ─────────────────────────────────────────────────────────────────────────


def test_public_api_reexports_importable():
    """All four public symbols importable from graqle.governance."""
    from graqle.governance import (
        BaselineCorruptedError as _BCE,
        ConfigDriftAuditor as _CDA,
        DriftRecord as _DR,
        FileReadError as _FRE,
    )
    assert _BCE is BaselineCorruptedError
    assert _CDA is ConfigDriftAuditor
    assert _DR is DriftRecord
    assert _FRE is FileReadError


def test_sanitize_strips_windows_path():
    out = _sanitize("PermissionError: [Errno 13] Permission denied: 'C:\\Users\\alice\\secret.yaml'")
    assert "C:\\Users" not in out
    assert "<path>" in out


def test_sanitize_strips_posix_path():
    out = _sanitize("error reading /home/alice/.secrets/api_key.txt")
    assert "/home/alice" not in out
    assert "<path>" in out


def test_sanitize_truncates_long_messages():
    long = "x" * 500
    out = _sanitize(long)
    assert len(out) == 200


def test_sanitize_handles_non_string():
    out = _sanitize(123)
    assert isinstance(out, str)


def test_build_error_envelope_sanitizes_message():
    env = build_error_envelope("X", "failed at C:\\Users\\alice\\foo.json")
    assert "C:\\Users" not in env["message"]
    assert env["error"] == "X"


def test_build_audit_response_shape():
    records = [DriftRecord("f.yaml", "modified", True, None, "x", "medium")]
    out = build_audit_response(records)
    assert out["action"] == "audit"
    assert out["total_drift"] == 1
    assert len(out["drift_records"]) == 1
    assert out["drift_records"][0]["file_path"] == "f.yaml"


def test_build_accept_response_shape():
    out = build_accept_response("f.yaml", "alice")
    assert out == {
        "action": "accept",
        "file": "f.yaml",
        "approver": "alice",
        "status": "accepted",
    }


def test_extra_request_fields_ignored_backcompat():
    """Extra fields on request envelope are ignored (back-compat)."""
    # _validate_baseline: extra keys on entries are ignored
    baseline = {
        "schema_version": 1,
        "entries": {
            "x.yaml": {
                "sha256": "a" * 64,
                "approver": None,
                "approved_at": None,
                "unknown_future_key": "ok",
            },
        },
    }
    validated = _validate_baseline(baseline)
    assert validated["entries"]["x.yaml"]["unknown_future_key"] == "ok"
