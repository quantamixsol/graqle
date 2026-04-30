"""GraQle Graph Health Check & Rebuild Script
=============================================
Standalone script and shared engine for the graq_graph_health MCP tool.

Features
--------
- Diagnoses local JSON/NetworkX graph OR Neo4j (CypherActivation mode)
- Reports node/edge counts, zero-vector ratio, cache staleness, activation
  strategy in use, and estimated reasoning latency breakdown
- Incrementally rebuilds .graqle/chunk_embeddings.npz — only embeds new/
  changed chunks, never re-embeds existing vectors (regression-safe)
- Injects ADR→code REFERENCES links and ADR↔ADR RELATED_TO links
- All phases gate-checked; aborts atomically on failure (backups first)
- Backend-agnostic: auto-detects local vs Neo4j from graqle.yaml

Usage (terminal)
----------------
    cd graqle-sdk
    python scripts/graqle_graph_health.py            # health check only
    python scripts/graqle_graph_health.py --rebuild  # health + NPZ rebuild
    python scripts/graqle_graph_health.py --links    # health + ADR link injection
    python scripts/graqle_graph_health.py --full     # health + rebuild + links

MCP surface
-----------
    graq_graph_health(mode="check")   → diagnosis report
    graq_graph_health(mode="rebuild") → NPZ incremental rebuild
    graq_graph_health(mode="full")    → rebuild + links

Shipping path
-------------
    graqle/tools/graph_health.py  ← engine (no CLI code, importable)
    scripts/graqle_graph_health.py ← thin CLI wrapper (this file)
    graqle/plugins/mcp_dev_server.py ← MCP tool wired to engine
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from graqle-sdk root without editable install
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from graqle.tools.graph_health import GraphHealthEngine, HealthReport  # noqa: E402


def _print_report(report: HealthReport) -> None:
    """Pretty-print a HealthReport to stdout."""
    sep = "=" * 60
    print(sep)
    print("GRAQLE GRAPH HEALTH REPORT")
    print(sep)

    # ── Backend ──────────────────────────────────────────────────────
    b = report.backend
    print(f"\nBackend          : {b['type']}")
    if b.get("uri"):
        print(f"URI              : {b['uri']}")
    print(f"Graph file       : {b.get('graph_file', 'n/a')}")
    print(f"Backend status   : {'OK' if b.get('reachable') else 'UNREACHABLE'}")

    # ── Graph stats ──────────────────────────────────────────────────
    g = report.graph_stats
    print(f"\nNodes            : {g['nodes']:,}")
    print(f"Edges            : {g['edges']:,}")
    print(f"Components       : {g['components']}")
    print(f"Avg degree       : {g['avg_degree']:.2f}")
    print(f"Entity types     : {g['entity_type_count']}")

    # ── Activation ───────────────────────────────────────────────────
    a = report.activation
    strategy = a["strategy"]
    print(f"\nActivation mode  : {strategy}")
    if strategy == "chunk_scorer_cached":
        print(f"Cache path       : {a['cache_path']}")
        print(f"Cached chunks    : {a['cached_chunks']:,}")
        print(f"Cache stale      : {a['cache_stale']}")
        print(f"Est. activation  : <1s (batch numpy cosine)")
    elif strategy == "cypher_neo4j":
        print(f"Vector index     : {a.get('vector_index', 'cogni_chunk_embedding_index')}")
        print(f"Est. activation  : <100ms (native vector search)")
    elif strategy == "property_fallback":
        print(f"Est. activation  : 5-10s (regex keyword fallback)")
        print("  WARNING: No embedding cache. Run --rebuild to fix.")

    # ── Latency breakdown ────────────────────────────────────────────
    lt = report.latency_estimate
    print(f"\nEst. reason latency breakdown:")
    print(f"  Activation      : {lt['activation_ms']}ms")
    print(f"  LLM (50 nodes)  : {lt['llm_ms']}ms")
    print(f"  Total           : {lt['total_ms']}ms")

    # ── Embedding cache ───────────────────────────────────────────────
    c = report.cache_status
    print(f"\nNPZ cache        : {c['status']}")
    if c.get("path"):
        print(f"  Path           : {c['path']}")
        print(f"  Chunks         : {c.get('chunks', 0):,}")
        print(f"  Size           : {c.get('size_mb', 0):.1f} MB")
        print(f"  Zero vectors   : {c.get('zero_count', 0)}")
        if c.get("new_chunks_available", 0):
            print(f"  NEW chunks     : {c['new_chunks_available']} (run --rebuild)")

    # ── Gates ────────────────────────────────────────────────────────
    print(f"\nGates:")
    for gate_name, result in report.gates.items():
        status = "PASS" if result["ok"] else "FAIL"
        print(f"  [{status}] {gate_name}: {result['msg']}")

    # ── Rebuild results ───────────────────────────────────────────────
    if report.rebuild_result:
        r = report.rebuild_result
        print(f"\nRebuild:")
        print(f"  Embedded       : {r['new_chunks_embedded']}")
        print(f"  Total chunks   : {r['total_chunks']:,}")
        print(f"  Duration       : {r['duration_s']:.1f}s")
        print(f"  Zero vectors   : {r['zero_count']}")
        print(f"  Regression     : {'CLEAN' if r['regression_clean'] else 'FAILED'}")

    # ── ADR links ────────────────────────────────────────────────────
    if report.link_result:
        lk = report.link_result
        print(f"\nADR Links:")
        print(f"  New code links : {lk['new_code_links']}")
        print(f"  New ADR↔ADR    : {lk['new_adr_links']}")
        print(f"  Total links    : {lk['total_links_after']:,}")

    # ── Recommendation ───────────────────────────────────────────────
    print(f"\nRecommendation   : {report.recommendation}")
    print(sep)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GraQle Graph Health Check & Rebuild",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Incrementally rebuild chunk_embeddings.npz",
    )
    parser.add_argument(
        "--links",
        action="store_true",
        help="Inject ADR→code and ADR↔ADR RELATED_TO links",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run health check + rebuild + link injection",
    )
    parser.add_argument(
        "--graph",
        type=str,
        default=None,
        help="Override path to graqle.json (default: auto-detect from graqle.yaml)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Override path to graqle.yaml (default: search from cwd upward)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Diagnose only, no writes (even with --rebuild / --full)",
    )
    args = parser.parse_args()

    do_rebuild = args.rebuild or args.full
    do_links = args.links or args.full

    engine = GraphHealthEngine(
        graph_path=Path(args.graph) if args.graph else None,
        config_path=Path(args.config) if args.config else None,
    )

    report = engine.run(
        rebuild=do_rebuild and not args.dry_run,
        inject_links=do_links and not args.dry_run,
        dry_run=args.dry_run,
    )

    _print_report(report)

    # Exit non-zero if any gate failed
    if any(not g["ok"] for g in report.gates.values() if g.get("fatal")):
        sys.exit(1)


if __name__ == "__main__":
    main()
