"""Real-crash worker for the WAL batcher crash matrix (R25-EU01 PR-3 tests).

Run as a SUBPROCESS (never via ``python -c`` — cmd.exe swallows multi-line
``-c`` stdout on Windows). The parent test process spawns this worker, waits for
it to advance to a ``--phase`` boundary, then KILLS it with a real OS signal
(``Popen.terminate()`` / ``.kill()`` -> ``TerminateProcess`` on Windows,
``SIGTERM``/``SIGKILL`` on POSIX). This exercises *genuine* crash semantics — an
abrupt process death with no chance to run cleanup handlers — which in-process
fault injection cannot reproduce.

Protocol (so the parent kill is deterministic, not a race):

* The worker enqueues records into a WAL under ``--wal-root``.
* When it reaches the requested ``--phase`` boundary it writes a single line
  ``READY:<phase>`` to stdout, flushes, then busy-waits forever.
* The parent reads that line, knows the on-disk state is exactly at the boundary,
  and kills the worker. No timing guesswork.

Phases (each names the on-disk state at which the worker parks for the kill):

* ``after-enqueue``        N records fully enqueued (durable in the WAL), parked.
* ``mid-batch``            Some records enqueued, fewer than the size ceiling, parked
                           (the batch_max_seconds path: nothing flushed yet).
* ``before-flush``         At the size ceiling but parked just before flush() runs.

The invariant the parent asserts after the kill: a fresh ``WalBatcher`` over the
same ``--wal-root`` drains the WAL and the recovered records commit EXACTLY once
(content-addressed dedup), with no partial or duplicated leaves.
"""

from __future__ import annotations

import argparse
import sys
import time


def _emit_ready(phase: str) -> None:
    """Signal the parent that the on-disk state is at ``phase``, then park."""
    sys.stdout.write(f"READY:{phase}\n")
    sys.stdout.flush()
    # Park forever; the parent kills us here. A bounded ceiling prevents an
    # orphaned worker from living indefinitely if the parent itself dies.
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        time.sleep(0.05)


def _record(i: int) -> dict:
    """A minimally valid leaf-input record (mirrors test_merkle._record)."""
    import hashlib

    return {
        "proof_format_version": "1.0.0",
        "record_id": f"tr_{i:06d}",
        "content_hash": hashlib.sha256(f"payload-{i}".encode()).hexdigest(),
        "timestamp_unix": 1_700_000_000 + i,
        "governance_metadata": {"decision": "ALLOW", "seq": i},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="WAL batcher crash worker")
    parser.add_argument("--wal-root", required=True, help="WAL root directory")
    parser.add_argument(
        "--phase",
        required=True,
        choices=["after-enqueue", "mid-batch", "before-flush"],
        help="on-disk state at which to park for the parent kill",
    )
    parser.add_argument(
        "--count", type=int, default=3, help="number of records to enqueue"
    )
    args = parser.parse_args()

    # Imported here so an import error surfaces as a worker exit, not a collection
    # failure in the parent test module.
    from graqle.config.attestation_config import AttestationConfig
    from graqle.governance.tamper_evidence.batcher import WalBatcher

    # A high size ceiling so enqueue() never auto-flushes during the worker's
    # run; the parent controls exactly when (if ever) a flush happens.
    config = AttestationConfig(batch_max_records=10_000, batch_max_seconds=300)
    # NO committer: the worker only ever populates the WAL, then dies. Recovery
    # and commit are the parent's job after the kill.
    batcher = WalBatcher(config=config, wal_root=args.wal_root)

    if args.phase == "after-enqueue":
        for i in range(args.count):
            batcher.enqueue(_record(i))
        _emit_ready("after-enqueue")
    elif args.phase == "mid-batch":
        # Enqueue strictly fewer than `count` so the batch is partial.
        for i in range(max(1, args.count - 1)):
            batcher.enqueue(_record(i))
        _emit_ready("mid-batch")
    elif args.phase == "before-flush":
        for i in range(args.count):
            batcher.enqueue(_record(i))
        # Parked deliberately BEFORE any flush() call: every record is durable in
        # the WAL but none has been committed.
        _emit_ready("before-flush")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
