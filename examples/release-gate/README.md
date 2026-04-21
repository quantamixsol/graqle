# GraQle Release Gate — Example Workflow

This directory contains a **copy-paste template** for integrating the GraQle Release Gate into your own GitHub Actions pipeline.

## Usage

Copy `release-gate.yml` into your own repo as `.github/workflows/release-gate.yml`:

```bash
cp examples/release-gate/release-gate.yml .github/workflows/release-gate.yml
```

The workflow uses the published `graqle/release-gate@v1` GitHub Action and runs on both:

- `release` — when a release is published (gates PyPI publish post-hoc)
- `pull_request` — when the PR modifies `pyproject.toml`, `package.json`, `CHANGELOG.md`, `src/**`, or `graqle/**`

## Required inputs

| Input | Required | Notes |
|-------|----------|-------|
| `target` | yes | `pypi` or `vscode-marketplace` |
| `strict` | no | `'true'` fails on WARN; default only fails on BLOCK |
| `graqle-license` | no | Free tier runs in degraded mode without a license key |

## Why this is NOT in `.github/workflows/`

If this file lived in `.github/workflows/` it would run against THIS repo on every release — which is a chicken-and-egg problem since the action needs to be pip-installed from a release that hasn't been published to PyPI yet. It belongs in `examples/` as documentation.
