# Running GraQle on a scheduler

GraQle's rebuild and anchoring commands are designed to run unattended. This page
is the reference contract plus copy-paste recipes for cron, DAG platforms, and CI
runners.

## The contract

Pass any of `--headless`, `--json`, or `--report-json` to opt a command into the
scheduler contract. You then get **meaningful exit codes** and a **machine-readable
run report**.

| Exit code | Meaning | What a scheduler should do |
|---|---|---|
| `0` | Success — work was performed, nothing failed | Continue; downstream steps may run |
| `1` | Failure — the step did not complete, **or any node failed** | Alert / retry |
| `2` | Usage error — bad invocation | Fix the job definition; do not retry |
| `3` | Empty delta — ran fine, nothing to do | Continue, but skip downstream work |

A **partial** failure (some nodes rebuilt, some failed) exits `1`, not `0`. Check
`counters.nodes_updated` and `counters.nodes_failed` in the report to see how much
got through.

`3` is deliberately separate from `0`. A failed step is distinguishable from an
empty delta by exit code alone, and so is "did work actually happen?" — which is
what lets you gate an expensive downstream step on whether the graph changed.

### Flags

| Flag | Effect |
|---|---|
| `--headless` | Never prompt; no colour or progress output. Keeps stdout clean for parsing. |
| `--json` | Write the run report to stdout. |
| `--report-json PATH` | Write the run report to a file (atomically). |
| `--incremental` | `rebuild` only: rebuild nodes whose **source content changed**, not just those missing chunks. |

`--headless` and `--json` are independent on purpose: `--headless` is about
interactivity, `--json` is about output format. Combine them for a scheduler.

### Run report

```json
{
  "schema_version": "1",
  "command": "rebuild",
  "status": "empty_delta",
  "exit_code": 3,
  "started_at": "2026-07-29T13:41:32+00:00",
  "duration_s": 0.42,
  "counters": {
    "nodes_total": 1200,
    "nodes_updated": 0,
    "nodes_with_chunks_after": 1200,
    "nodes_with_chunks_before": 1200
  },
  "errors": []
}
```

`errors` carries exception **type names only** — never messages, paths, or
credentials — so a report is safe to archive as a build artefact.

### Incremental rebuilds

Without `--incremental`, `graq rebuild` only fills in *missing* chunks: a node
whose source file changed but which already has chunks is skipped, so its
evidence goes stale. `--incremental` compares a stored SHA-256 of the source
content and rebuilds what actually changed.

Detection is content-based, not mtime-based, because git checkouts, CI clones,
and Docker layer caching all rewrite mtime — exactly the environments a scheduler
runs in. A graph built before this feature has no stored hash and simply falls
back to the previous behaviour on its first run.

---

## cron

```bash
#!/usr/bin/env bash
# /etc/cron.daily/graqle-rebuild
set -euo pipefail

cd /srv/myproject
REPORT=/var/log/graqle/rebuild-$(date +%F).json

set +e
graq rebuild --headless --json --incremental --report-json "$REPORT"
code=$?
set -e

case $code in
  0) logger -t graqle "rebuild: graph updated" ;;
  3) logger -t graqle "rebuild: no changes" ;;
  2) logger -t graqle -p user.err "rebuild: bad invocation"; exit 2 ;;
  *) logger -t graqle -p user.err "rebuild: FAILED (exit $code)"; exit 1 ;;
esac

# Anchor whatever the rebuild produced.
graq govern serve --once --json --report-json "${REPORT%.json}-anchor.json"
```

`set +e` around the call matters: under `set -e` a non-zero exit (including the
perfectly healthy `3`) would abort the script before you can branch on it.

## Airflow

```python
from airflow.decorators import task
from airflow.exceptions import AirflowSkipException
import subprocess, json

@task
def rebuild_graph() -> dict:
    proc = subprocess.run(
        ["graq", "rebuild", "--headless", "--json", "--incremental"],
        capture_output=True, text=True, cwd="/srv/myproject",
    )
    if proc.returncode == 2:
        raise ValueError(f"bad invocation: {proc.stderr}")
    if proc.returncode not in (0, 3):
        raise RuntimeError(f"rebuild failed (exit {proc.returncode})")

    report = json.loads(proc.stdout)
    if proc.returncode == 3:
        # Nothing changed — skip the downstream anchor/publish tasks.
        raise AirflowSkipException("graph unchanged")
    return report
```

Mapping exit `3` onto `AirflowSkipException` is the idiomatic way to express
"healthy, but there was nothing to do" — it keeps the DAG green while correctly
short-circuiting downstream work.

## GitHub Actions

```yaml
- name: Rebuild knowledge graph
  id: rebuild
  run: |
    set +e
    graq rebuild --headless --json --incremental --report-json rebuild.json
    echo "exit_code=$?" >> "$GITHUB_OUTPUT"
    set -e

- name: Fail on rebuild error
  if: steps.rebuild.outputs.exit_code == '1' || steps.rebuild.outputs.exit_code == '2'
  run: exit 1

- name: Publish (only when the graph actually changed)
  if: steps.rebuild.outputs.exit_code == '0'
  run: graq govern serve --once --json

- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: graqle-run-report
    path: rebuild.json
```

## Idempotency

Re-running any of these is safe. A second `graq rebuild --incremental` over an
unchanged tree does no work and exits `3`, so an overlapping or retried job
cannot corrupt the graph or double-anchor.
