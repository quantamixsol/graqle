"""graq rebuild — Rebuild chunks and evidence for all KG nodes.

Ensures every node has fresh chunks from its source files so that
reasoning agents have evidence to cite. Run this after:
  - Installing/upgrading GraQle
  - Changing source files in your project
  - Loading a KG that was built without chunks (e.g., hand-built KGs)

Usage:
    graq rebuild                          # rebuild missing chunks only
    graq rebuild --force                  # re-read ALL source files
    graq rebuild --graph my.json          # specify a different graph
    graq rebuild --re-embed               # dry-run: show what re-embed would do (safe)
    graq rebuild --re-embed --force       # actually re-embed all nodes (writes to disk)

Scheduler use (CR-010.R6):
    graq rebuild --headless --json                 # machine contract: JSON report + exit code
    graq rebuild --headless --json --incremental   # rebuild only nodes whose source CHANGED
    graq rebuild --json --report-json run.json     # also archive the report

Exit codes apply when any of --headless/--json/--report-json is passed:
    0 success (work done) · 1 failure · 2 usage error · 3 empty delta (nothing to do)
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.rebuild
# risk: LOW (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, json, logging, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import typer

logger = logging.getLogger("graqle.cli.rebuild")


def _flag(value: object) -> bool:
    """Coerce a possibly-unfilled Typer option to a plain bool.

    Typer fills these in when the command is invoked from the CLI, but a direct
    Python call (``graq init`` auto-rebuilds this way) leaves the ``OptionInfo``
    sentinel in place. ``OptionInfo`` is truthy, so a naive ``bool()`` would read
    an unsupplied flag as enabled.
    """
    return value is True


def rebuild_command(
    graph_path: str = "graqle.json",
    config_path: str = "graqle.yaml",
    force: bool = False,
    re_embed: bool = False,
    incremental: bool = typer.Option(
        False,
        "--incremental",
        help="Rebuild only nodes whose source content CHANGED (hash-based), "
             "not merely those missing chunks.",
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="Non-interactive: never prompt, no colour/progress output. "
             "Enables the scheduler exit-code contract.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a machine-readable JSON run report on stdout. "
             "Enables the scheduler exit-code contract.",
    ),
    report_json: str | None = typer.Option(
        None,
        "--report-json",
        help="Write the JSON run report to this path (atomic). "
             "Enables the scheduler exit-code contract.",
    ),
) -> int:
    """Rebuild chunks for all nodes in the KG.

    If re_embed=True without force=True, runs a safe dry-run that shows what
    would happen without writing anything to disk. Pass force=True to commit.

    Returns the number of nodes updated.

    Machine contract (CR-010.R6)
    ----------------------------
    Passing any of *headless*, *json_out* or *report_json* opts this invocation
    into the scheduler contract: a :class:`RunReport` is produced and the process
    exits 0/1/2/3 (see :mod:`graqle.cli.headless`).

    Why opt-in: Typer discards a command's return value, so today **every**
    ``graq rebuild`` exits 0 — including the "graph file not found" path. Fixing
    that unconditionally would change the exit code of a published CLI under
    anyone's existing cron entry. Callers who pass a machine flag are new by
    definition and have no legacy expectation, so they get the corrected codes
    immediately; bare invocations keep exiting 0 and get a DeprecationWarning
    naming the release that changes it.
    """
    from graqle.cli.headless import (
        RunReport,
        RunStatus,
        emit_and_exit,
        utc_now_iso,
    )

    # `rebuild_command` is also called PROGRAMMATICALLY (graq init's auto-rebuild,
    # init.py). Such a caller does not go through Typer, so the unfilled
    # ``typer.Option(...)`` defaults arrive as OptionInfo objects — which are
    # truthy, and would wrongly select machine mode and then blow up on
    # Path(OptionInfo). Normalise first: an OptionInfo means "not supplied".
    headless = _flag(headless)
    json_out = _flag(json_out)
    incremental = _flag(incremental)
    report_json = report_json if isinstance(report_json, (str, Path)) else None

    # Any machine flag selects the scheduler contract.
    machine_mode = bool(headless or json_out or report_json)
    started_at = utc_now_iso()
    t_start = time.monotonic()

    def _finish(
        status: RunStatus,
        counters: dict[str, int],
        errors: tuple[str, ...] = (),
    ) -> None:
        """Emit the run report and exit. Only called in machine mode."""
        emit_and_exit(
            RunReport(
                command="rebuild",
                status=status,
                started_at=started_at,
                duration_s=time.monotonic() - t_start,
                counters=counters,
                errors=errors,
            ),
            json_out=json_out,
            report_path=report_json,
        )

    try:
        from rich.console import Console
        console = Console()
    except ImportError:
        console = None

    # Under --headless: no colour, no progress rendering, and stdout stays clean
    # so a scheduler parsing --json output is never fed decorative text.
    def _print(msg: str) -> None:
        if headless:
            return
        if console:
            console.print(msg)
        else:
            print(msg)

    if not machine_mode:
        # Advance notice: this path is scheduled to start exiting non-zero.
        # stderr, so it can never contaminate stdout that a script is parsing.
        import warnings

        warnings.warn(
            "graq rebuild currently exits 0 even when it fails (e.g. a missing "
            "graph file). A future release will return a meaningful exit code "
            "for bare invocations. Pass --headless/--json today to opt into the "
            "scheduler contract (0 success, 1 failure, 2 usage, 3 empty delta).",
            DeprecationWarning,
            stacklevel=2,
        )

    gp = Path(graph_path)
    if not gp.exists():
        _print(f"[red]Graph file not found: {graph_path}[/red]")
        _print("Run [cyan]graq init[/cyan] first to create a graph.")
        if machine_mode:
            _finish(
                RunStatus.FAILURE,
                {"nodes_total": 0, "nodes_updated": 0},
                errors=("GraphFileNotFound",),
            )
        return 0

    from graqle.config.settings import GraqleConfig
    from graqle.core.graph import Graqle

    # Load config + graph. A corrupt or unreadable graph is a hard failure: in
    # machine mode it must surface as exit 1, never as an unhandled traceback a
    # scheduler would record as a crash with no report.
    try:
        cp = Path(config_path)
        config = GraqleConfig.from_yaml(str(cp)) if cp.exists() else GraqleConfig.default()
        graph = Graqle.from_json(str(gp), config=config)
    except Exception as exc:
        _print(f"[red]Could not load graph: {type(exc).__name__}[/red]")
        if machine_mode:
            _finish(
                RunStatus.FAILURE,
                {"nodes_total": 0, "nodes_updated": 0},
                errors=(type(exc).__name__,),
            )
        raise

    _print(f"[bold cyan]Rebuilding chunks[/bold cyan] for {len(graph.nodes)} nodes...")
    if force:
        _print("[yellow]Force mode: re-reading ALL source files[/yellow]")

    t0 = time.monotonic()

    # Count nodes with chunks before
    before_count = sum(
        1 for n in graph.nodes.values()
        if n.properties.get("chunks")
    )

    # Rebuild
    updated = graph.rebuild_chunks(force=force, incremental=incremental)

    # Count after
    after_count = sum(
        1 for n in graph.nodes.values()
        if n.properties.get("chunks")
    )

    chunk_time = time.monotonic() - t0

    # Save back to JSON
    _save_graph(graph, str(gp))

    _print("\n[green]Done![/green]")
    _print(f"  Nodes with chunks: {before_count} -> {after_count}")
    _print(f"  Nodes updated: {updated}")
    _print(f"  Chunk rebuild time: {chunk_time:.1f}s")

    if after_count == 0:
        _print(
            "\n[yellow]Warning:[/yellow] No nodes have chunks. "
            "Make sure your nodes have 'source_file' or 'file_path' "
            "properties pointing to readable files."
        )

    # Rebuild embedding cache for fast query-time activation (v0.12.3)
    # Use config-driven embedding engine (BUG-2 fix: respects graqle.yaml embeddings section)
    t1 = time.monotonic()
    try:
        from graqle.activation.chunk_scorer import ChunkScorer
        from graqle.activation.embeddings import create_embedding_engine, get_engine_info

        engine = create_embedding_engine(config)
        engine_info = get_engine_info(engine)
        scorer = ChunkScorer(embedding_engine=engine)
        scorer.build_cache(graph)

        embed_time = time.monotonic() - t1
        cache_path = Path(".graqle/chunk_embeddings.npz")
        cache_size = cache_path.stat().st_size / 1024 if cache_path.exists() else 0

        _print(f"  [green]Embedding cache rebuilt[/green]")
        _print(f"  Embedding backend: [cyan]{engine_info['backend']}[/cyan]")
        _print(f"  Embedding model: [cyan]{engine_info['model']}[/cyan] ({engine_info['dimension']}-dim)")
        _print(f"  Embedding time: {embed_time:.1f}s")
        _print(f"  Cache size: {cache_size:.0f}KB")
    except Exception as exc:
        _print(f"  [dim]Embedding cache skipped: {exc}[/dim]")

    # --re-embed: re-compute all node embeddings with the active engine.
    # graq_predict flagged this as CRITICAL risk without proper guards (2026-03-25).
    # Safety protocol enforced here:
    #   1. Dry-run by default (re_embed=True, force=False) — shows impact, writes nothing
    #   2. Dimension pre-check before skip_validation is honored
    #   3. Snapshot (graqle.json.bak) written before any disk write
    #   4. Restore snapshot on any exception during re-embed
    if re_embed:
        _re_embed_nodes(graph, str(gp), config, force, _print)

    total_time = time.monotonic() - t0
    _print(f"\n  [bold]Total rebuild time: {total_time:.1f}s[/bold]")

    if machine_mode:
        # EMPTY_DELTA is the whole point of the contract: "ran fine, nothing to
        # do" must be distinguishable from "failed" by exit code alone, and also
        # from "did work" — so a scheduler can gate a downstream step on whether
        # the graph actually changed.
        #
        # Critically, a run in which every node raised also produces updated == 0.
        # Reporting that as EMPTY_DELTA would tell the scheduler "all healthy,
        # nothing to do" while nothing worked at all, so nodes_failed decides:
        # any failure with no successful update is a FAILURE, not an empty delta.
        # Any failure at all is a FAILURE, whether or not other nodes succeeded.
        # A partial failure reported as exit 0 would be the same silent-success
        # bug in a smaller costume: a scheduler routes on the exit code, so
        # "most of the graph rebuilt, some of it is broken" must not read as
        # healthy. nodes_failed/nodes_updated in the report tell the operator
        # how much got through.
        failed = int(getattr(graph, "last_rebuild_failed_nodes", 0))
        if failed:
            status = RunStatus.FAILURE
        elif updated:
            status = RunStatus.SUCCESS
        else:
            status = RunStatus.EMPTY_DELTA

        _finish(
            status,
            {
                "nodes_total": len(graph.nodes),
                "nodes_updated": updated,
                "nodes_failed": failed,
                "nodes_with_chunks_before": before_count,
                "nodes_with_chunks_after": after_count,
            },
            errors=("ChunkRebuildFailed",) if failed else (),
        )

    return updated


def _re_embed_nodes(graph: Graqle, graph_path: str, config, force: bool, _print) -> None:
    """Re-embed all nodes with the currently active embedding engine.

    Dry-run by default. Pass force=True to actually write to disk.
    Safety guards per graq_predict analysis (2026-03-25, 79% confidence):
    - Dimension pre-check before any write
    - Snapshot before write, restore on failure
    """
    import shutil

    try:
        from graqle.activation.embeddings import create_embedding_engine, get_engine_info
    except ImportError as exc:
        _print(f"[red]--re-embed requires embedding deps: {exc}[/red]")
        _print("Install with: pip install 'graqle[embeddings]'")
        return

    engine = create_embedding_engine(config)
    engine_info = get_engine_info(engine)
    active_model = engine_info.get("model", "unknown")
    active_dim = int(engine_info.get("dimension", 0))

    # Dimension pre-check: compare against _meta stored in graph
    # This check runs BEFORE skip_validation — graq_predict flagged that
    # skip_validation removes the only reconciliation point if this is skipped.
    import json as _json
    gp = Path(graph_path)
    with open(gp, encoding="utf-8") as _f:
        _raw = _json.load(_f)
    stored_meta = (_raw.get("graph") or {}).get("_meta", {})
    stored_dim = int(stored_meta.get("embedding_dim", 0))
    stored_model = stored_meta.get("embedding_model", "unknown")

    node_count = len(graph.nodes)

    _print(f"\n[bold cyan]--re-embed analysis[/bold cyan]")
    _print(f"  Nodes to re-embed: [cyan]{node_count}[/cyan]")
    _print(f"  Stored model:  [dim]{stored_model}[/dim] ({stored_dim}-dim)")
    _print(f"  Active model:  [cyan]{active_model}[/cyan] ({active_dim}-dim)")

    if stored_dim > 0 and active_dim > 0 and stored_dim != active_dim:
        _print(
            f"\n[yellow]Dimension change detected:[/yellow] "
            f"{stored_dim}-dim → {active_dim}-dim. "
            "All stored embeddings will be replaced."
        )
    elif stored_model != active_model and stored_model != "unknown":
        _print(
            f"\n[yellow]Model change detected:[/yellow] "
            f"{stored_model} → {active_model}."
        )

    if not force:
        _print(
            "\n[yellow]DRY RUN — nothing written.[/yellow] "
            "Pass [cyan]--force[/cyan] to actually re-embed and save."
        )
        return

    # Live run: snapshot first, restore on any failure
    backup_path = str(gp) + ".bak"
    _print(f"\n  Snapshotting graph → [dim]{backup_path}[/dim]")
    shutil.copy2(str(gp), backup_path)

    _print(f"  Re-embedding [cyan]{node_count}[/cyan] nodes with [cyan]{active_model}[/cyan]...")
    try:
        re_embedded = 0
        for node in graph.nodes.values():
            desc = node.description or node.label
            if not desc:
                continue
            embedding = engine.embed(desc)
            node.properties["_embedding_cache"] = embedding.tolist()
            re_embedded += 1

        # Save via to_json (writes _meta with new model/dim, uses _write_with_lock)
        graph.to_json(str(gp))

        _print(f"  [green]Re-embedded {re_embedded} nodes.[/green]")
        _print(f"  Snapshot retained at [dim]{backup_path}[/dim] — delete when satisfied.")
    except Exception as exc:
        _print(f"\n[red]Re-embed failed: {exc}[/red]")
        _print(f"[yellow]Restoring snapshot from {backup_path}...[/yellow]")
        shutil.copy2(backup_path, str(gp))
        _print("[green]Snapshot restored. Graph is unchanged.[/green]")
        raise


def _save_graph(graph: Graqle, path: str) -> None:
    """Save graph back to JSON, preserving node_link format (atomic write)."""
    import networkx as nx
    from graqle.core.graph import _write_with_lock

    G = graph.to_networkx()
    data = nx.node_link_data(G, edges="links")
    content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    _write_with_lock(path, content)
