"""Mode B runtime governance — the continuous anchoring worker (ADR-221 §4.4 / R2).

v0.62.0 closes the loop: a long-lived `graqle govern serve` worker continuously seals
governed-decision records into Merkle batches, anchors them to the public Sigstore
Rekor log, and writes a PII-safe health snapshot operators can read.

This example assembles the worker the same way `graqle govern serve` does, but with
an in-memory sink + no real Rekor anchor so it runs anywhere — including offline CI.
For a production setup: enable ``attestation.enabled: true`` in ``graqle.yaml`` and run
``graqle govern serve`` as a long-lived process.

Run::

    pip install graqle           # v0.62.0+
    python examples/runtime_govern_serve_anchoring.py
"""

from __future__ import annotations

from pathlib import Path

from graqle.config.attestation_config import AttestationConfig
from graqle.governance.runtime import GovernedRuntime, InMemorySink
from graqle.governance.tamper_evidence.batcher import WalBatcher
from graqle.governance.tamper_evidence.committer import Committer
from graqle.governance.tamper_evidence.worker import AnchoringWorker


def main() -> None:
    import tempfile

    # 1) Configure the substrate. attestation.enabled=true is the opt-in switch;
    #    fail_open_on_anchor_error stays False (the worker REFUSES to start otherwise).
    config = AttestationConfig(enabled=True, batch_max_seconds=1)

    # 2) Assemble the SHIPPED Layer 5 pipeline (committer + WAL batcher). No anchor +
    #    no replay queue in this demo — production wires both via graqle.yaml.
    with tempfile.TemporaryDirectory() as wal_dir:
        batcher = WalBatcher(config=config, wal_root=Path(wal_dir))
        committer = Committer(config=config, batcher=batcher)

        # 3) The R0 surface (`attest`) is what your deployed AI calls per decision.
        sink = InMemorySink()
        runtime = GovernedRuntime(sink=sink, salt="demo-salt")

        # 4) Emit a few decisions through R0 attest() — exactly what a deployed AI
        #    would do per inference — and submit each attested record to the
        #    committer. In production this wiring is handled by trace_capture's
        #    observer hook, but doing it explicitly here makes the data flow obvious.
        for i in range(3):
            record = runtime.attest(
                domain="loan",
                model_id="credit-risk-v4",
                output={"decision": "approve" if i % 2 == 0 else "deny"},
                inputs={"applicant_ref": runtime.pseudonymize_ref(f"user-{i}")},
            )
            committer.submit(record)

        # 5) The R2 worker is the scheduler: each tick flushes the batcher (sealing
        #    + Merkle-rooting + anchoring) and drains the replay queue.
        worker = AnchoringWorker(committer, config, tick_seconds=0.1)

        # In production: worker.run() blocks until SIGINT/SIGTERM. Here: run a few
        # ticks deterministically and emit the health snapshot.
        worker.run(max_ticks=2)

        # 6) The health surface — what `graqle govern health` reads from disk.
        health = worker.health()
        print("Worker health snapshot:")
        for k, v in health.to_dict().items():
            print(f"  {k}: {v}")

        print(
            f"\nOK: {len(sink.records)} record(s) attested. "
            f"In production, the v0.62.0 anchoring worker would commit + anchor these "
            "to the public Sigstore Rekor log via `graqle govern serve`."
        )


if __name__ == "__main__":
    main()
