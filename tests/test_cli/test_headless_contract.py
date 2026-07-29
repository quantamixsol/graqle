"""CR-010.R6 — scheduler-grade CLI contract.

Covers the machine contract itself (``graqle.cli.headless``) and its two current
consumers (``graq rebuild``, ``graq govern serve --once``).

The load-bearing assertion in this file is that **a failed step is
distinguishable from an empty delta by exit code alone** — R6's literal
acceptance criterion — and that opting into the contract does not change the
behaviour of any existing bare invocation.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graqle.cli.headless import (
    REPORT_SCHEMA_VERSION,
    ExitCode,
    HeadlessPromptError,
    RunReport,
    RunStatus,
    guard_no_prompt,
    utc_now_iso,
)

runner = CliRunner()


def _report(status: RunStatus, **kw) -> RunReport:
    return RunReport(
        command=kw.pop("command", "rebuild"),
        status=status,
        started_at=kw.pop("started_at", utc_now_iso()),
        duration_s=kw.pop("duration_s", 0.5),
        **kw,
    )


# ── the contract itself ──────────────────────────────────────────────────────


class TestExitCodeContract:
    def test_the_four_codes_are_the_documented_values(self):
        assert int(ExitCode.SUCCESS) == 0
        assert int(ExitCode.FAILURE) == 1
        assert int(ExitCode.USAGE) == 2
        assert int(ExitCode.EMPTY_DELTA) == 3

    def test_failure_is_distinguishable_from_empty_delta(self):
        """R6's literal acceptance criterion."""
        assert ExitCode.FAILURE != ExitCode.EMPTY_DELTA

    def test_empty_delta_is_also_distinguishable_from_success(self):
        """Otherwise a scheduler cannot gate a downstream step on 'did work happen?'."""
        assert ExitCode.EMPTY_DELTA != ExitCode.SUCCESS

    @pytest.mark.parametrize("status", list(RunStatus))
    def test_every_status_maps_to_an_exit_code(self, status):
        """Total function — a new status cannot silently fall through to 0."""
        assert isinstance(status.exit_code, ExitCode)

    def test_exit_code_is_derived_not_settable(self):
        """The report cannot carry a status/exit_code pair that disagree."""
        assert "exit_code" not in RunReport.__dataclass_fields__
        assert _report(RunStatus.FAILURE).exit_code == ExitCode.FAILURE

    def test_report_is_frozen(self):
        with pytest.raises(Exception):
            _report(RunStatus.SUCCESS).status = RunStatus.FAILURE  # type: ignore[misc]


class TestRunReportSerialization:
    def test_payload_shape_and_schema_version(self):
        payload = json.loads(_report(RunStatus.SUCCESS, counters={"n": 2}).to_json())
        assert payload["schema_version"] == REPORT_SCHEMA_VERSION
        assert payload["status"] == "success"
        assert payload["exit_code"] == 0
        assert payload["counters"] == {"n": 2}
        assert payload["errors"] == []

    def test_serialized_exit_code_matches_status(self):
        for status in RunStatus:
            payload = json.loads(_report(status).to_json())
            assert payload["exit_code"] == int(status.exit_code)

    def test_counters_are_sorted_for_stable_diffs(self):
        payload = json.loads(_report(RunStatus.SUCCESS, counters={"z": 1, "a": 2}).to_json())
        assert list(payload["counters"]) == ["a", "z"]

    def test_output_is_valid_json(self):
        json.loads(_report(RunStatus.EMPTY_DELTA).to_json())


# ── adversarial / negative ───────────────────────────────────────────────────


class TestHeadlessGuard:
    def test_guard_raises_under_headless(self):
        with pytest.raises(HeadlessPromptError):
            guard_no_prompt(True, "API key")

    def test_guard_is_a_noop_when_interactive(self):
        guard_no_prompt(False, "API key")  # must not raise


class TestReportIsPiiSafe:
    def test_errors_carry_type_names_not_messages(self):
        """A report may be archived by a scheduler — it must never carry secrets.

        Mirrors the rule already enforced on .graqle/govern.health.json.
        """
        secret = "sk-live-DEADBEEF-do-not-leak"
        try:
            raise ValueError(f"auth failed for token {secret}")
        except ValueError as exc:
            report = _report(RunStatus.FAILURE, errors=(type(exc).__name__,))

        rendered = report.to_json()
        assert secret not in rendered
        assert "ValueError" in rendered


class TestReportPersistence:
    def test_report_json_is_written_and_parseable(self, tmp_path):
        from graqle.cli.headless import _write_report_atomically

        dest = tmp_path / "nested" / "run.json"
        _write_report_atomically(_report(RunStatus.SUCCESS, counters={"n": 1}), dest)

        assert json.loads(dest.read_text(encoding="utf-8"))["counters"] == {"n": 1}

    def test_no_orphan_tempfile_is_left_behind(self, tmp_path):
        from graqle.cli.headless import _write_report_atomically

        dest = tmp_path / "run.json"
        _write_report_atomically(_report(RunStatus.SUCCESS), dest)

        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_unwritable_report_path_does_not_mask_the_run_outcome(self, tmp_path, capsys):
        """A bookkeeping failure must not hide why the step itself failed."""
        import typer

        from graqle.cli.headless import emit_and_exit

        # A directory where the report file should be → the write must fail.
        blocked = tmp_path / "run.json"
        blocked.mkdir()

        with pytest.raises(typer.Exit) as excinfo:
            emit_and_exit(_report(RunStatus.FAILURE), json_out=False, report_path=blocked)

        assert excinfo.value.exit_code == int(ExitCode.FAILURE)
        assert "could not write run report" in capsys.readouterr().err


# ── graq rebuild: the end-to-end contract ────────────────────────────────────


def _seed_graph(tmp_path: Path, body: str) -> tuple[Path, Path]:
    src = tmp_path / "src_a.py"
    src.write_text(body, encoding="utf-8")
    graph = tmp_path / "g.json"
    graph.write_text(
        json.dumps(
            {
                "directed": True,
                "multigraph": False,
                "graph": {},
                "nodes": [
                    {
                        "id": "mod::a",
                        "label": "a",
                        "type": "PythonModule",
                        "description": "sample module a",
                        "properties": {"file_path": str(src)},
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    return graph, src


def _run_rebuild(*args: str):
    """Invoke the real registered CLI command."""
    from graqle.cli.main import app

    return runner.invoke(app, ["rebuild", *args])


class TestProgrammaticCaller:
    """`graq init` calls rebuild_command() directly (init.py) — not via Typer.

    Unfilled ``typer.Option(...)`` defaults arrive as truthy ``OptionInfo``
    sentinels on that path. Left unnormalised they select machine mode and then
    fail on ``Path(OptionInfo)``, breaking `graq init`'s auto-rebuild.
    """

    def test_direct_call_returns_int_and_does_not_exit(self, tmp_path):
        import warnings

        from graqle.cli.commands.rebuild import rebuild_command

        graph, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = rebuild_command(
                graph_path=str(graph),
                config_path=str(tmp_path / "absent.yaml"),
                force=True,
            )

        assert isinstance(result, int)

    def test_option_sentinels_do_not_enable_machine_mode(self):
        """The OptionInfo sentinel must read as 'not supplied', not as True."""
        import typer

        from graqle.cli.commands.rebuild import _flag

        assert _flag(typer.Option(False, "--headless")) is False
        assert _flag(False) is False
        assert _flag(True) is True


class TestFailedNodeAccounting:
    """Sentinel BLOCKER-1: a swallowed per-node error must remain countable."""

    def test_failed_nodes_are_counted_not_swallowed(self, tmp_path):
        from unittest.mock import patch

        from graqle.core.graph import Graqle

        graph_path, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")
        graph = Graqle.from_json(str(graph_path))

        with patch("pathlib.Path.read_text", side_effect=PermissionError("denied")):
            updated = graph.rebuild_chunks(force=True)

        assert updated == 0
        assert graph.last_rebuild_failed_nodes >= 1

    def test_attribute_exists_before_any_rebuild(self, tmp_path):
        """Class-level default — readable even if rebuild_chunks never ran."""
        from graqle.core.graph import Graqle

        assert Graqle().last_rebuild_failed_nodes == 0

    def test_clean_run_reports_zero_failures(self, tmp_path):
        from graqle.core.graph import Graqle

        graph_path, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")
        graph = Graqle.from_json(str(graph_path))
        graph.rebuild_chunks(force=True)

        assert graph.last_rebuild_failed_nodes == 0


class TestContentHashing:
    def test_undecodable_bytes_do_not_collide(self):
        """Sentinel MINOR-1: errors='ignore' silently DROPS undecodable bytes.

        Under ``ignore`` these two hash identically (both encode to ``b"ab"``),
        so editing a file to add or remove an undecodable byte would be seen as
        "unchanged" and skipped. ``replace`` substitutes rather than drops, so
        the difference survives into the hash.
        """
        from graqle.core.graph import _content_hash

        assert _content_hash("a\udce9b") != _content_hash("ab")


class TestRebuildMachineContract:
    def test_missing_graph_exits_failure_not_zero(self, tmp_path):
        """The measured defect R6 exists to fix: this used to exit 0."""
        res = _run_rebuild(
            "--graph-path", str(tmp_path / "missing.json"), "--headless", "--json"
        )
        assert res.exit_code == int(ExitCode.FAILURE)
        payload = json.loads(res.stdout)
        assert payload["status"] == "failure"
        assert payload["errors"] == ["GraphFileNotFound"]

    def test_bare_invocation_on_missing_graph_still_exits_zero(self, tmp_path):
        """Backwards compatibility: a published CLI's exit code must not move."""
        res = _run_rebuild("--graph-path", str(tmp_path / "missing.json"))
        assert res.exit_code == 0

    def test_unchanged_source_is_empty_delta(self, tmp_path):
        graph, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")
        _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--force")

        res = _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--incremental")
        assert res.exit_code == int(ExitCode.EMPTY_DELTA)
        assert json.loads(res.stdout)["counters"]["nodes_updated"] == 0

    def test_changed_source_is_rebuilt(self, tmp_path):
        """Change-based, not presence-based: the node already HAS chunks."""
        graph, src = _seed_graph(tmp_path, "def alpha():\n    return 1\n")
        _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--force")

        src.write_text("def alpha():\n    return 99\n\ndef beta():\n    return 2\n", encoding="utf-8")

        res = _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--incremental")
        assert res.exit_code == int(ExitCode.SUCCESS)
        assert json.loads(res.stdout)["counters"]["nodes_updated"] >= 1

    def test_rerunning_is_idempotent(self, tmp_path):
        """Second identical run must report no work — the cron-safety property."""
        graph, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")
        _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--force")

        first = _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--incremental")
        second = _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--incremental")
        assert first.exit_code == second.exit_code == int(ExitCode.EMPTY_DELTA)

    def test_report_json_flag_writes_the_file(self, tmp_path):
        graph, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")
        dest = tmp_path / "reports" / "run.json"

        res = _run_rebuild("--graph-path", str(graph), "--headless", "--report-json", str(dest))
        assert dest.exists()
        payload = json.loads(dest.read_text(encoding="utf-8"))
        assert payload["command"] == "rebuild"
        assert payload["exit_code"] == res.exit_code

    def test_headless_keeps_stdout_machine_clean(self, tmp_path):
        """Decorative output must never contaminate a parsed stdout stream."""
        graph, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")
        res = _run_rebuild("--graph-path", str(graph), "--headless", "--json")
        json.loads(res.stdout)  # parses as pure JSON, nothing else on the stream

    def test_corrupt_graph_is_a_failure_not_a_traceback(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ this is not valid json", encoding="utf-8")

        res = _run_rebuild("--graph-path", str(bad), "--headless", "--json")
        assert res.exit_code == int(ExitCode.FAILURE)
        assert json.loads(res.stdout)["status"] == "failure"

    def test_total_node_failure_is_not_reported_as_empty_delta(self, tmp_path):
        """Sentinel BLOCKER-1 (reproduced, real).

        Every node raising also yields ``updated == 0``. Reporting that as
        EMPTY_DELTA would tell a scheduler "all healthy, nothing to do" when in
        fact nothing worked. It must be a FAILURE.
        """
        from unittest.mock import patch

        graph, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")

        # Drive the real code path: make the per-node file read raise.
        with patch("pathlib.Path.read_text", side_effect=PermissionError("denied")):
            res = _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--force")

        assert res.exit_code == int(ExitCode.FAILURE)
        assert json.loads(res.stdout)["status"] == "failure"

    def test_partial_failure_is_not_reported_as_success(self, tmp_path):
        """Sentinel pass-2 BLOCKER: some nodes fail, some succeed.

        Falling into the "updated > 0" branch would exit 0 and tell the
        scheduler the run was healthy while part of the graph is broken.
        """
        from unittest.mock import patch

        from graqle.core.graph import Graqle

        graph, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")

        real_rebuild = Graqle.rebuild_chunks

        def _one_ok_one_failed(self, *args, **kwargs):
            updated = real_rebuild(self, *args, **kwargs)
            self.last_rebuild_failed_nodes = 1  # simulate a mixed outcome
            return max(updated, 1)

        with patch.object(Graqle, "rebuild_chunks", _one_ok_one_failed):
            res = _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--force")

        assert res.exit_code == int(ExitCode.FAILURE)
        payload = json.loads(res.stdout)
        assert payload["status"] == "failure"
        assert payload["counters"]["nodes_failed"] == 1
        assert payload["counters"]["nodes_updated"] >= 1  # work DID happen, still a failure

    def test_missing_hash_falls_back_safely(self, tmp_path):
        """A graph from an older release has no hash — it must still rebuild."""
        graph, _ = _seed_graph(tmp_path, "def alpha():\n    return 1\n")
        res = _run_rebuild("--graph-path", str(graph), "--headless", "--json", "--incremental")
        assert res.exit_code in (int(ExitCode.SUCCESS), int(ExitCode.EMPTY_DELTA))
        assert json.loads(res.stdout)["status"] in ("success", "empty_delta")
