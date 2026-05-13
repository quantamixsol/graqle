"""Profile graq_reason token economics — CR-007 regression utility.

Wraps the configured backend's generate() to record:
  - call count
  - per-call input/output chars
  - per-call latency
Then runs a single graq_reason against the configured KG and prints a
summary that can be eyeballed against CR-007 ceilings:
  - total LLM calls       < orchestration.max_llm_calls
  - max single prompt     < orchestration.prompt_hard_cap
  - total input tokens    < empirical target ~80K

Usage:
  python scripts/profile_reason.py [--question "..."] [--config path]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


def _utf8_stdout() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Profile graq_reason token cost.")
    p.add_argument(
        "--question",
        default="Where is the multi-edge collapse fix implemented in this codebase?",
        help="Question to send through graq_reason.",
    )
    p.add_argument(
        "--config",
        default=None,
        help="Path to graqle.yaml (default: ./graqle.yaml in CWD).",
    )
    p.add_argument(
        "--max-rounds", type=int, default=2,
        help="max_rounds passed to graph.areason (default 2).",
    )
    return p


async def _run(question: str, config_path: Path, max_rounds: int) -> int:
    import graqle
    from graqle.core.graph import Graqle
    from graqle.config.settings import GraqleConfig

    print(f"graqle.__version__ = {graqle.__version__}")
    cfg = GraqleConfig.from_yaml(str(config_path))
    graph = Graqle.from_neo4j(
        uri=cfg.graph.uri,
        username=cfg.graph.username,
        password=cfg.graph.password,
        database=cfg.graph.database,
        config=cfg,
    )
    print(f"Loaded graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # ── Probe wrapper: capture every backend.generate / agenerate call ──
    calls: list[dict] = []
    _patched: set[int] = set()

    def _wrap(b: Any, method_name: str) -> None:
        if id(b) in _patched:
            return
        _patched.add(id(b))
        orig = getattr(b, method_name, None)
        if orig is None:
            return
        if asyncio.iscoroutinefunction(orig):
            async def _async_wrap(prompt, *args, **kwargs):
                t0 = time.monotonic()
                out = await orig(prompt, *args, **kwargs)
                calls.append({
                    "method": method_name,
                    "prompt_chars": len(prompt) if isinstance(prompt, str) else 0,
                    "out_chars": len(str(out)),
                    "latency_ms": (time.monotonic() - t0) * 1000,
                })
                return out
            setattr(b, method_name, _async_wrap)
        else:
            def _sync_wrap(prompt, *args, **kwargs):
                t0 = time.monotonic()
                out = orig(prompt, *args, **kwargs)
                calls.append({
                    "method": method_name,
                    "prompt_chars": len(prompt) if isinstance(prompt, str) else 0,
                    "out_chars": len(str(out)),
                    "latency_ms": (time.monotonic() - t0) * 1000,
                })
                return out
            setattr(b, method_name, _sync_wrap)

    orig_get = graph._get_backend_for_node

    def _probed_get(nid: str, task_type: Any = None) -> Any:
        b = orig_get(nid, task_type=task_type)
        for m in ("agenerate", "generate", "ainvoke", "invoke"):
            if hasattr(b, m):
                _wrap(b, m)
        return b

    graph._get_backend_for_node = _probed_get

    t0 = time.monotonic()
    result = await graph.areason(
        question, max_rounds=max_rounds, task_type="reason",
    )
    total_ms = (time.monotonic() - t0) * 1000

    print()
    print("=== graq_reason result ===")
    print(f"  confidence : {result.confidence:.3f}")
    print(f"  rounds     : {result.rounds_completed}")
    print(f"  nodes_used : {result.node_count}")
    print(f"  cost_usd   : ${result.cost_usd:.4f}")
    print(f"  latency_ms : {total_ms:,.0f}")

    print()
    print(f"=== LLM call telemetry ({len(calls)} backend calls) ===")
    if calls:
        in_total = sum(c["prompt_chars"] for c in calls)
        out_total = sum(c["out_chars"] for c in calls)
        max_in = max(c["prompt_chars"] for c in calls)
        max_out = max(c["out_chars"] for c in calls)
        print(f"  Total input  : {in_total:>10,} chars  (~{in_total // 4:,} tokens)")
        print(f"  Total output : {out_total:>10,} chars  (~{out_total // 4:,} tokens)")
        print(f"  Avg per call : {in_total // len(calls):>10,} in  / {out_total // len(calls):>10,} out")
        print(f"  Largest in   : {max_in:>10,} chars")
        print(f"  Largest out  : {max_out:>10,} chars")

        ceil_target_in = 80_000 * 4   # 80k tokens => ~320k chars
        ceil_target_calls = 60
        ceil_target_max_prompt = 10_000

        print()
        print("=== CR-007 acceptance check ===")
        print(f"  total_input_chars  ({in_total:,}) < target {ceil_target_in:,}      : "
              + ("PASS" if in_total < ceil_target_in else "FAIL"))
        print(f"  llm_calls          ({len(calls)}) <= {ceil_target_calls}                    : "
              + ("PASS" if len(calls) <= ceil_target_calls else "FAIL"))
        print(f"  max_prompt_chars   ({max_in:,}) <= {ceil_target_max_prompt:,}              : "
              + ("PASS" if max_in <= ceil_target_max_prompt else "FAIL"))

    print()
    print("=== Reasoning answer (first 400 chars) ===")
    print(result.answer[:400])
    return 0


def main() -> int:
    _utf8_stdout()
    args = _build_argparser().parse_args()
    cfg_path = Path(args.config) if args.config else Path.cwd() / "graqle.yaml"
    if not cfg_path.exists():
        print(f"ERROR: config not found at {cfg_path}", file=sys.stderr)
        return 2
    return asyncio.run(_run(args.question, cfg_path, args.max_rounds))


if __name__ == "__main__":
    sys.exit(main())
