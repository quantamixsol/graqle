# GraQle SDK — project-local chat overrides

> This file is the walk-up `GRAQ.md` for the graqle-sdk repository. It is
> NOT shipped in the `graqle` wheel. When Claude Code runs inside this
> repo, the ChatAgentLoop v4 loader picks up this file and merges it on
> top of the immutable built-in floor (`graqle/chat/templates/GRAQ_default.md`).
>
> Content here is treated as advisory context for SDK developers — the
> floor rules are NEVER overridden.

## SDK-specific hard limits (extensions to the floor)

- **Cross-project edits.** This session is scoped to `graqle-sdk/`. Never
  touch `graqle-studio/`, `graqle-vscode/`, `crawlq/`, `tracegov/`.
- **Patent-protected stubs.** The files listed in `tests/conftest.py`
  `collect_ignore` are IP-protected stubs — never attempt to implement
  them from the test skeleton alone. Implementation lives in the
  private research branch.
- **pytest runner.** On Windows, running `pytest tests/` without a path
  can crash pytest-xdist workers. Prefer a scoped path
  (e.g. `pytest tests/test_core/`) or pass `-p no:xdist`.
- **Cost envelope (SDK dogfooding).** Target $0.079/turn, hard ceiling
  $0.10/turn when running this project's own chat loop on itself.
- **Turn budget.** Base 25 tool calls / 120s per tool; burst override
  up to 100 calls with a soft chip.
- **Cloud spend gate.** $10/month is the hard threshold above which any
  cloud-billable resource creation requires prior explicit approval,
  as defined in `CLAUDE.md`.

## SDK-specific scenario hints

### Release pipeline
1. Bump `pyproject.toml` + `graqle/__version__.py` in one commit
2. Update `CHANGELOG.md` in the same commit
3. Tag `vX.Y.Z` only after operator approval on the merged PR
4. Trusted Publishing via GitHub Actions picks up the tag and publishes

### Hotfix pipeline
1. Branch `hotfix/<shortname>` off `private/master`
2. One commit per fix with a clear `fix(...):` prefix
3. Full governance chain per fix (reason → review → commit)
4. PR to private/master, operator reviews, merge, tag, publish

## Operating conventions

This repository uses the Graphical Context Controller (`.gcc/`) for
session memory and the Global Strategy Management (`.gsm/`) for
architectural decision records. Read those directories at session
start for context continuity across instances.

## Attribution

Project-local walk-up extensions. Last updated 2026-04-12 during the
v0.50.1 hotfix implementation session.
