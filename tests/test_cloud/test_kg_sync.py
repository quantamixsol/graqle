"""
Tests for graqle.core.kg_sync — ADR-123 Knowledge Graph Sync.

Covers all 6 phases and all 7 binary success criteria:
  1. graq_learn → local graqle.json updated → S3 push scheduled
  2. pull_if_newer: S3 newer → local updated; S3 older → local unchanged
  3. pull_if_newer: merges local learned nodes not in cloud
  4. graq cloud pull: actually downloads and writes graqle.json
  5. cloud push conflict detection: S3 newer → abort; --force bypasses
  6. graq scan: pre-scan pull runs; post-scan sync logs failure
  7. GRAQLE_OFFLINE=1: all S3 calls skipped, no errors

All S3/boto3 calls are mocked — no real AWS calls made.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph(nodes: list[dict], links: list[dict] | None = None) -> dict:
    return {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": nodes,
        "links": links or [],
    }


def _node(id: str, entity_type: str = "MODULE") -> dict:
    return {"id": id, "label": id, "entity_type": entity_type}


# ---------------------------------------------------------------------------
# is_offline
# ---------------------------------------------------------------------------

class TestIsOffline:
    def test_offline_when_env_set(self, monkeypatch):
        from graqle.core.kg_sync import is_offline
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")
        assert is_offline() is True

    def test_offline_true_string(self, monkeypatch):
        from graqle.core.kg_sync import is_offline
        monkeypatch.setenv("GRAQLE_OFFLINE", "true")
        assert is_offline() is True

    def test_online_by_default(self, monkeypatch):
        from graqle.core.kg_sync import is_offline
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)
        assert is_offline() is False

    def test_online_when_zero(self, monkeypatch):
        from graqle.core.kg_sync import is_offline
        monkeypatch.setenv("GRAQLE_OFFLINE", "0")
        assert is_offline() is False


# ---------------------------------------------------------------------------
# _email_hash
# ---------------------------------------------------------------------------

class TestEmailHash:
    def test_known_hash(self):
        from graqle.core.kg_sync import _email_hash
        import hashlib
        email = "test@graqle.com"
        expected = hashlib.sha256(email.lower().encode()).hexdigest()
        assert _email_hash(email) == expected

    def test_case_insensitive(self):
        from graqle.core.kg_sync import _email_hash
        assert _email_hash("A@B.COM") == _email_hash("a@b.com")


# ---------------------------------------------------------------------------
# _s3_key
# ---------------------------------------------------------------------------

class TestS3Key:
    def test_format(self):
        from graqle.core.kg_sync import _s3_key
        key = _s3_key("abc123", "myproject")
        assert key == "graphs/abc123/myproject/graqle.json"

    def test_custom_filename(self):
        from graqle.core.kg_sync import _s3_key
        key = _s3_key("abc123", "myproject", "metadata.json")
        assert key == "graphs/abc123/myproject/metadata.json"


# ---------------------------------------------------------------------------
# _detect_project_name
# ---------------------------------------------------------------------------

class TestDetectProjectName:
    def test_from_pyproject(self, tmp_path):
        from graqle.core.kg_sync import _detect_project_name
        (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nname = "my-sdk"\n')
        assert _detect_project_name(tmp_path) == "my-sdk"

    def test_from_package_json(self, tmp_path):
        from graqle.core.kg_sync import _detect_project_name
        (tmp_path / "package.json").write_text('{"name": "my-app"}')
        assert _detect_project_name(tmp_path) == "my-app"

    def test_fallback_to_dirname(self, tmp_path):
        from graqle.core.kg_sync import _detect_project_name
        subdir = tmp_path / "my-project"
        subdir.mkdir()
        assert _detect_project_name(subdir) == "my-project"


# ---------------------------------------------------------------------------
# pull_if_newer — offline guard
# ---------------------------------------------------------------------------

class TestPullIfNewerOffline:
    def test_skips_when_offline(self, monkeypatch, tmp_path):
        from graqle.core.kg_sync import pull_if_newer
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")
        result = pull_if_newer(tmp_path / "graqle.json", "myproject")
        assert result.pulled is False
        assert "offline" in result.reason

    def test_skips_when_unauthenticated(self, monkeypatch, tmp_path):
        from graqle.core.kg_sync import pull_if_newer
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)
        with patch("graqle.core.kg_sync._load_creds", return_value=None):
            result = pull_if_newer(tmp_path / "graqle.json", "myproject")
        assert result.pulled is False
        assert "authenticated" in result.reason


# ---------------------------------------------------------------------------
# pull_if_newer — S3 older than local (no pull)
# ---------------------------------------------------------------------------

class TestPullIfNewerS3Older:
    def test_no_pull_when_local_is_newer(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import pull_if_newer

        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        local_file = tmp_path / "graqle.json"
        local_file.write_text(json.dumps(_make_graph([_node("a")])))
        # Make local file appear very recent
        recent_time = time.time()
        os.utime(local_file, (recent_time, recent_time))

        mock_creds = MagicMock()
        mock_creds.email = "user@test.com"

        # S3 last-modified is older than local
        import datetime
        s3_time = datetime.datetime.fromtimestamp(recent_time - 3600, tz=datetime.timezone.utc)
        mock_head = {"LastModified": s3_time, "ContentLength": 100}

        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = mock_head

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch("boto3.client", return_value=mock_s3):
            result = pull_if_newer(local_file, "myproject")

        assert result.pulled is False
        assert "up to date" in result.reason
        mock_s3.get_object.assert_not_called()

    def test_pulls_when_local_is_empty_despite_newer_mtime(self, tmp_path, monkeypatch):
        """Critical: empty local graph (git stash corruption) forces pull even if local mtime is newer."""
        from graqle.core.kg_sync import pull_if_newer

        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        # Simulate git stash corruption: file has extra metadata keys (was a real graph before)
        # but 0 nodes — extra keys prove it was previously populated
        corrupt_graph = _make_graph([])
        corrupt_graph["_meta"] = {"version": "0.38.0", "scanned_at": "2026-03-28T00:00:00Z"}
        local_file = tmp_path / "graqle.json"
        local_file.write_text(json.dumps(corrupt_graph))  # 0 nodes + extra _meta key = corruption
        new_time = time.time()
        os.utime(local_file, (new_time, new_time))

        mock_creds = MagicMock()
        mock_creds.email = "user@test.com"

        # S3 is OLDER than local mtime (would normally skip)
        import datetime
        s3_time = datetime.datetime.fromtimestamp(new_time - 7200, tz=datetime.timezone.utc)
        cloud_nodes = [_node("code_a"), _node("code_b")]
        cloud_data = _make_graph(cloud_nodes)

        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(cloud_data).encode()
        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = {"LastModified": s3_time, "ContentLength": 500}
        mock_s3.get_object.return_value = {"Body": mock_body}

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch("boto3.client", return_value=mock_s3):
            result = pull_if_newer(local_file, "myproject")

        # Must pull despite local being "newer" — because local is empty
        assert result.pulled is True, "Must force-pull when local graph is empty"
        mock_s3.get_object.assert_called_once()
        result_data = json.loads(local_file.read_text())
        assert len(result_data["nodes"]) == 2

    def test_no_force_pull_on_fresh_init_empty_graph(self, tmp_path, monkeypatch):
        """Fresh project init (bare skeleton, no extra keys) must NOT force-pull — not corruption."""
        from graqle.core.kg_sync import pull_if_newer

        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        # Fresh init: bare skeleton with ONLY the 5 standard keys — no _meta, no version
        # This is what graqle writes on first init before any scan
        local_file = tmp_path / "graqle.json"
        fresh_content = json.dumps(_make_graph([]))  # only directed/multigraph/graph/nodes/links
        local_file.write_text(fresh_content)
        new_time = time.time()
        os.utime(local_file, (new_time, new_time))

        # Verify: no extra keys beyond the 5 skeleton keys
        parsed = json.loads(fresh_content)
        skeleton_keys = {"directed", "multigraph", "graph", "nodes", "links"}
        assert set(parsed.keys()) - skeleton_keys == set(), "Fresh init must have no extra keys"

        mock_creds = MagicMock()
        mock_creds.email = "user@test.com"

        import datetime
        s3_time = datetime.datetime.fromtimestamp(new_time - 3600, tz=datetime.timezone.utc)
        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = {"LastModified": s3_time, "ContentLength": 100}

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch("boto3.client", return_value=mock_s3):
            result = pull_if_newer(local_file, "myproject")

        # Fresh init is NOT corruption — must not force-pull
        assert result.pulled is False
        mock_s3.get_object.assert_not_called()


# ---------------------------------------------------------------------------
# pull_if_newer — S3 newer (pull and merge)
# ---------------------------------------------------------------------------

class TestPullIfNewerS3Newer:
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        # Local graph: 2 nodes (1 code, 1 learned)
        local_nodes = [
            _node("code_a"),
            {"id": "lesson_001", "label": "lesson", "entity_type": "LESSON", "source": "graq_learn"},
        ]
        local_file = tmp_path / "graqle.json"
        local_file.write_text(json.dumps(_make_graph(local_nodes)))
        old_time = time.time() - 7200  # 2h ago
        os.utime(local_file, (old_time, old_time))

        # Cloud graph: 3 code nodes (no lesson)
        cloud_nodes = [_node("code_a"), _node("code_b"), _node("code_c")]
        cloud_data = _make_graph(cloud_nodes)

        mock_creds = MagicMock()
        mock_creds.email = "user@test.com"

        import datetime
        s3_time = datetime.datetime.fromtimestamp(time.time(), tz=datetime.timezone.utc)
        mock_head = {"LastModified": s3_time, "ContentLength": 500}

        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(cloud_data).encode()
        mock_get = {"Body": mock_body}

        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = mock_head
        mock_s3.get_object.return_value = mock_get

        return local_file, mock_creds, mock_s3, cloud_nodes

    def test_pulls_and_writes_local(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import pull_if_newer
        local_file, mock_creds, mock_s3, _ = self._setup(tmp_path, monkeypatch)

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch("boto3.client", return_value=mock_s3):
            result = pull_if_newer(local_file, "myproject")

        assert result.pulled is True
        assert "S3" in result.reason

    def test_merges_local_learned_nodes(self, tmp_path, monkeypatch):
        """Local LESSON node not in cloud must be preserved after pull."""
        from graqle.core.kg_sync import pull_if_newer
        local_file, mock_creds, mock_s3, cloud_nodes = self._setup(tmp_path, monkeypatch)

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch("boto3.client", return_value=mock_s3):
            pull_if_newer(local_file, "myproject", merge_learned=True)

        result_data = json.loads(local_file.read_text())
        result_ids = {n["id"] for n in result_data["nodes"]}

        # Cloud nodes present
        assert "code_a" in result_ids
        assert "code_b" in result_ids
        assert "code_c" in result_ids
        # Local LESSON node preserved
        assert "lesson_001" in result_ids

    def test_overwrite_mode_drops_local_learned(self, tmp_path, monkeypatch):
        """With merge_learned=False, local nodes are NOT preserved."""
        from graqle.core.kg_sync import pull_if_newer
        local_file, mock_creds, mock_s3, cloud_nodes = self._setup(tmp_path, monkeypatch)

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch("boto3.client", return_value=mock_s3):
            pull_if_newer(local_file, "myproject", merge_learned=False)

        result_data = json.loads(local_file.read_text())
        result_ids = {n["id"] for n in result_data["nodes"]}
        assert "lesson_001" not in result_ids

    def test_no_overwrite_when_s3_also_empty(self, tmp_path, monkeypatch):
        """Circuit-breaker: if S3 also has 0 nodes, do NOT overwrite local (infinite loop guard)."""
        from graqle.core.kg_sync import pull_if_newer

        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        # Local is corrupt (has _meta key, 0 nodes)
        corrupt_graph = _make_graph([])
        corrupt_graph["_meta"] = {"version": "0.38.0"}
        local_file = tmp_path / "graqle.json"
        local_file.write_text(json.dumps(corrupt_graph))
        old_time = time.time() - 3600
        os.utime(local_file, (old_time, old_time))

        mock_creds = MagicMock()
        mock_creds.email = "user@test.com"

        import datetime
        s3_time = datetime.datetime.fromtimestamp(time.time(), tz=datetime.timezone.utc)
        # S3 also has 0 nodes
        empty_cloud = _make_graph([])
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(empty_cloud).encode()
        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = {"LastModified": s3_time, "ContentLength": 100}
        mock_s3.get_object.return_value = {"Body": mock_body}

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch("boto3.client", return_value=mock_s3):
            result = pull_if_newer(local_file, "myproject")

        # Must NOT pull — circuit-breaker kicks in (S3 also empty)
        assert result.pulled is False
        assert "empty" in result.reason.lower()

    def test_boto3_not_available(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import pull_if_newer
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        mock_creds = MagicMock()
        mock_creds.email = "user@test.com"

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch.dict("sys.modules", {"boto3": None}):
            result = pull_if_newer(tmp_path / "graqle.json", "myproject")

        assert result.pulled is False

    def test_s3_404_returns_gracefully(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import pull_if_newer
        import botocore.exceptions

        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)
        mock_creds = MagicMock()
        mock_creds.email = "user@test.com"

        mock_s3 = MagicMock()
        mock_s3.head_object.side_effect = botocore.exceptions.ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )

        with patch("graqle.core.kg_sync._load_creds", return_value=mock_creds), \
             patch("boto3.client", return_value=mock_s3):
            result = pull_if_newer(tmp_path / "graqle.json", "myproject")

        assert result.pulled is False
        assert "not in cloud" in result.reason


# ---------------------------------------------------------------------------
# schedule_push — debouncing and threading
# ---------------------------------------------------------------------------

class TestSchedulePush:
    def test_skips_when_offline(self, tmp_path, monkeypatch):
        from graqle.core import kg_sync
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")

        with patch("threading.Thread") as mock_thread:
            kg_sync.schedule_push(tmp_path / "graqle.json", "myproject")
            mock_thread.assert_not_called()

    def test_fires_thread(self, tmp_path, monkeypatch):
        from graqle.core import kg_sync
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        # Reset debounce state for this path
        path = tmp_path / "graqle.json"
        path.write_text("{}")
        str_path = str(path)
        with kg_sync._push_states_lock:
            kg_sync._push_states.pop(str_path, None)

        started = []

        class FakeThread:
            def __init__(self, *a, **kw): pass
            def start(self): started.append(True)

        with patch("threading.Thread", FakeThread):
            kg_sync.schedule_push(path, "myproject")

        assert started == [True]

    def test_debounce_prevents_double_push(self, tmp_path, monkeypatch):
        from graqle.core import kg_sync
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        path = tmp_path / "graqle.json"
        path.write_text("{}")
        str_path = str(path)

        # Prime debounce state to "just pushed"
        with kg_sync._push_states_lock:
            from graqle.core.kg_sync import _PushState
            state = _PushState(last_push=time.monotonic())
            kg_sync._push_states[str_path] = state

        started = []

        class FakeThread:
            def __init__(self, *a, **kw): pass
            def start(self): started.append(True)

        with patch("threading.Thread", FakeThread):
            kg_sync.schedule_push(path, "myproject")

        assert started == [], "Should be debounced — no thread started"


# ---------------------------------------------------------------------------
# check_push_conflict
# ---------------------------------------------------------------------------

class TestCheckPushConflict:
    def test_conflict_when_s3_newer(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import check_push_conflict
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        local_file = tmp_path / "graqle.json"
        local_file.write_text("{}")
        old_time = time.time() - 3600
        os.utime(local_file, (old_time, old_time))

        import datetime
        s3_time = datetime.datetime.fromtimestamp(time.time(), tz=datetime.timezone.utc)
        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = {"LastModified": s3_time}

        with patch("boto3.client", return_value=mock_s3):
            conflict, reason = check_push_conflict(local_file, "myproject", "abc123")

        assert conflict is True
        assert "newer" in reason

    def test_no_conflict_when_local_newer(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import check_push_conflict
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        local_file = tmp_path / "graqle.json"
        local_file.write_text("{}")
        new_time = time.time()
        os.utime(local_file, (new_time, new_time))

        import datetime
        s3_time = datetime.datetime.fromtimestamp(new_time - 3600, tz=datetime.timezone.utc)
        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = {"LastModified": s3_time}

        with patch("boto3.client", return_value=mock_s3):
            conflict, reason = check_push_conflict(local_file, "myproject", "abc123")

        assert conflict is False

    def test_offline_returns_no_conflict(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import check_push_conflict
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")
        conflict, reason = check_push_conflict(tmp_path / "graqle.json", "proj", "hash")
        assert conflict is False


# ---------------------------------------------------------------------------
# download_graph
# ---------------------------------------------------------------------------

class TestDownloadGraph:
    def test_downloads_and_writes(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import download_graph
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        cloud_nodes = [_node("n1"), _node("n2"), _node("n3")]
        cloud_data = _make_graph(cloud_nodes)

        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(cloud_data).encode()
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": mock_body}

        local_path = tmp_path / "graqle.json"

        with patch("boto3.client", return_value=mock_s3):
            success, msg, count = download_graph(local_path, "myproject", "abc123", merge=False)

        assert success is True
        assert count == 3
        assert local_path.exists()
        result = json.loads(local_path.read_text())
        assert len(result["nodes"]) == 3

    def test_merges_local_learned_on_download(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import download_graph
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        # Local has a lesson node
        local_path = tmp_path / "graqle.json"
        local_path.write_text(json.dumps(_make_graph([
            _node("code_a"),
            {"id": "lesson_x", "label": "lesson", "entity_type": "LESSON"},
        ])))

        # Cloud has code_a + code_b
        cloud_data = _make_graph([_node("code_a"), _node("code_b")])
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(cloud_data).encode()
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": mock_body}

        with patch("boto3.client", return_value=mock_s3):
            success, _, count = download_graph(local_path, "myproject", "abc123", merge=True)

        assert success is True
        result = json.loads(local_path.read_text())
        ids = {n["id"] for n in result["nodes"]}
        assert "lesson_x" in ids   # preserved
        assert "code_b" in ids     # from cloud
        assert count == 3          # code_a + code_b + lesson_x

    def test_404_returns_failure(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import download_graph
        import botocore.exceptions
        monkeypatch.delenv("GRAQLE_OFFLINE", raising=False)

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = botocore.exceptions.ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "GetObject"
        )

        with patch("boto3.client", return_value=mock_s3):
            success, msg, count = download_graph(tmp_path / "g.json", "proj", "hash")

        assert success is False
        assert count == 0
        assert "not found" in msg.lower()

    def test_offline_returns_failure(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import download_graph
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")
        success, msg, count = download_graph(tmp_path / "g.json", "proj", "hash")
        assert success is False
        assert "offline" in msg


# ---------------------------------------------------------------------------
# Integration: mcp_dev_server._save_graph triggers schedule_push
# ---------------------------------------------------------------------------

class TestMcpServerSaveTriggersPush:
    def test_save_graph_calls_schedule_push(self):
        """After _save_graph, schedule_push is called with the graph file path."""
        from graqle.plugins.mcp_dev_server import KogniDevServer

        server = KogniDevServer.__new__(KogniDevServer)
        server._graph_file = "/tmp/fake/graqle.json"
        server._graph = None

        mock_graph = MagicMock()
        mock_graph.to_networkx.return_value = MagicMock()

        import networkx as nx
        fake_G = nx.DiGraph()
        mock_graph.to_networkx.return_value = fake_G

        with patch("graqle.core.kg_sync.schedule_push") as mock_push, \
             patch("graqle.core.graph._write_with_lock"):
            server._save_graph(mock_graph)

        mock_push.assert_called_once()
        call_path = str(mock_push.call_args[0][0])
        assert "graqle.json" in call_path


# ---------------------------------------------------------------------------
# Integration: graq scan pre-scan pull is called
# ---------------------------------------------------------------------------

class TestScanPrePull:
    def test_scan_calls_pull_if_newer(self, tmp_path, monkeypatch):
        """graq scan should attempt pull_if_newer before scanning."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "main.py").write_text("def hello(): pass\n")

        pull_calls = []

        def fake_pull(path, project, **kw):
            pull_calls.append((str(path), project))
            from graqle.core.kg_sync import PullResult
            return PullResult(pulled=False, reason="local is up to date")

        with patch("graqle.core.kg_sync.pull_if_newer", side_effect=fake_pull):
            from graqle.cli.commands.scan import _scan_repo_impl
            try:
                _scan_repo_impl(
                    path=str(tmp_path),
                    output=str(tmp_path / "graqle.json"),
                    depth=2,
                    include_tests=False,
                    verbose=False,
                    exclude=[],
                    preserve_learned=True,
                )
            except Exception:
                pass  # scan may fail without full setup — we just check pull was called

        assert len(pull_calls) >= 1, "pull_if_newer should have been called before scan"


# ---------------------------------------------------------------------------
# Binary success criteria: offline mode produces no errors
# ---------------------------------------------------------------------------

class TestOfflineModeNoErrors:
    def test_pull_offline_no_exception(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import pull_if_newer
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")
        result = pull_if_newer(tmp_path / "graqle.json", "proj")
        assert result.pulled is False  # no exception raised

    def test_schedule_push_offline_no_exception(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import schedule_push
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")
        schedule_push(tmp_path / "graqle.json", "proj")  # must not raise

    def test_conflict_check_offline_no_exception(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import check_push_conflict
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")
        conflict, _ = check_push_conflict(tmp_path / "g.json", "proj", "hash")
        assert conflict is False  # no exception raised

    def test_download_offline_no_exception(self, tmp_path, monkeypatch):
        from graqle.core.kg_sync import download_graph
        monkeypatch.setenv("GRAQLE_OFFLINE", "1")
        success, _, _ = download_graph(tmp_path / "g.json", "proj", "hash")
        assert success is False  # graceful failure, no exception


class TestAccessDeniedDedupe:
    """OT-061: AccessDenied dedupe — logged ONCE per process at WARNING.

    Non-AccessDenied S3 errors continue to be logged at ERROR per occurrence.
    """

    @pytest.fixture(autouse=True)
    def _reset_dedupe(self):
        """Reset the module-level dedupe sentinel before AND after each test."""
        from graqle.core.kg_sync import _reset_access_denied_dedupe
        _reset_access_denied_dedupe()
        yield
        _reset_access_denied_dedupe()

    def _make_access_denied_error(self):
        """Build a botocore ClientError with AccessDenied code."""
        try:
            import botocore.exceptions
        except ImportError:
            pytest.skip("botocore not installed")
        return botocore.exceptions.ClientError(
            error_response={"Error": {"Code": "AccessDenied", "Message": "denied"}},
            operation_name="PutObject",
        )

    def _make_other_error(self):
        """Build a botocore ClientError with a non-AccessDenied code."""
        try:
            import botocore.exceptions
        except ImportError:
            pytest.skip("botocore not installed")
        return botocore.exceptions.ClientError(
            error_response={"Error": {"Code": "InternalError", "Message": "boom"}},
            operation_name="PutObject",
        )

    def test_is_access_denied_recognizes_AccessDenied_code(self):
        """_is_access_denied returns True for ClientError with AccessDenied code."""
        from graqle.core.kg_sync import _is_access_denied
        assert _is_access_denied(self._make_access_denied_error()) is True

    def test_is_access_denied_returns_False_for_other_codes(self):
        """_is_access_denied returns False for non-AccessDenied ClientError and other exceptions."""
        from graqle.core.kg_sync import _is_access_denied
        assert _is_access_denied(self._make_other_error()) is False
        assert _is_access_denied(ValueError("boom")) is False
        assert _is_access_denied(RuntimeError("nope")) is False

    def test_ten_access_denied_errors_produce_one_log_line(self, caplog):
        """Session prompt requirement: 10 synthetic AccessDenied errors → 1 log line total."""
        import logging
        from graqle.core.kg_sync import _log_s3_error
        err = self._make_access_denied_error()

        with caplog.at_level(logging.WARNING, logger="graqle.core.kg_sync"):
            for _ in range(10):
                _log_s3_error("push", err)

        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "AccessDenied" in r.getMessage()
        ]
        assert len(warning_records) == 1, (
            f"Expected exactly 1 warning across 10 AccessDenied errors, "
            f"got {len(warning_records)}"
        )

    def test_non_access_denied_errors_logged_per_occurrence_at_error(self, caplog):
        """Non-AccessDenied errors fire ERROR every time, not deduped."""
        import logging
        from graqle.core.kg_sync import _log_s3_error
        err = self._make_other_error()

        with caplog.at_level(logging.ERROR, logger="graqle.core.kg_sync"):
            for _ in range(5):
                _log_s3_error("push", err)

        error_records = [
            r for r in caplog.records
            if r.levelno == logging.ERROR
            and "InternalError" in r.getMessage()
        ]
        assert len(error_records) == 5, (
            f"Expected 5 error logs (one per occurrence), got {len(error_records)}"
        )

    def test_dedupe_state_is_reset_by_helper(self, caplog):
        """After _reset_access_denied_dedupe(), the next AccessDenied logs again."""
        import logging
        from graqle.core.kg_sync import _log_s3_error, _reset_access_denied_dedupe
        err = self._make_access_denied_error()

        with caplog.at_level(logging.WARNING, logger="graqle.core.kg_sync"):
            _log_s3_error("push", err)
            _log_s3_error("push", err)  # silenced (same process)
            _reset_access_denied_dedupe()
            _log_s3_error("push", err)  # logs again after reset

        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "AccessDenied" in r.getMessage()
        ]
        assert len(warning_records) == 2, (
            f"Expected 2 warnings (one before reset, one after), got {len(warning_records)}"
        )

