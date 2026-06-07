## Known workarounds (learned behaviours)

These are distilled from the knowledge graph's lesson nodes — real failures, so
you don't repeat them.

| Situation | Workaround |
|-----------|-----------|
| `graq_bash` blocked until a plan exists (CG-02) | run `graq_plan(dry_run=true)` first |
| `graq_write` rejects an existing file (CG-03) | use `graq_edit(strategy="literal")` for existing files |
| `graq_edit` / `graq_write` resolve relative paths to site-packages, not the worktree (S-010) | use absolute paths, or fall back to a native write of NEW files with a logged capability-gap (V-marker) |
| `graq_edit` local backend fails | `graq_reason` to generate the full corrected file → `graq_write` it → log the gap |
| `graq_generate` without `file_path` lands code in the wrong file | always pass an explicit `file_path` |
| PR `--body` inline truncates | write the body to `/tmp/pr_body.md`, use `--body-file` |
| `graq_review` truncates files > 500 lines | `graq_grep` the flagged symbols first |
| Multi-line `python -c` swallows stdout on Windows | write a `.py` file and run it as a file |
| patent / trade-secret gate blocks an edit (even on the `-` side of a diff) | this is a real safety gate — do not force; escalate the false-positive |
| Editor format-on-save silently reverts `.py`/`.toml` after a write | re-read after write; disable format-on-save for governed edits |

## Protected paths (require approver identity)

Edits to `pyproject.toml`, `graqle.yaml`, `.mcp.json`, `.claude/settings.json`
require `approved_by` (the project owner). The owner is the SOLE approver of any
PR — the AI NEVER self-approves.

## Resource & spend governance

Any cloud resource expected to cost > $10/month requires EXPLICIT owner approval
BEFORE activation. State the estimated monthly cost first; wait for an explicit
"yes". Refuse to create billable resources above the threshold without it.
