# Graqle Live Demos

> Proof-of-value walkthroughs. Each demo is self-contained and runnable in < 5 minutes.

| # | Demo | What it shows | Time |
|---|------|---------------|------|
| 01 | [Impact Analysis](./01-impact-analysis/) | Before touching `graph.py`, see what 26 modules break | 3 min |
| 02 | [Secret Scanner](./02-secret-scanner/) | Catch leaked API keys before they hit PyPI | 2 min |
| 03 | [KG Sync Proof](./03-kg-sync-proof/) | Prove local/cloud graph never diverge (ADR-123) | 2 min |

## Prerequisites

```bash
pip install graqle>=0.39.0
# For demos 01: configure your LLM backend
export ANTHROPIC_API_KEY=your_key   # or any of 14 supported backends
```
