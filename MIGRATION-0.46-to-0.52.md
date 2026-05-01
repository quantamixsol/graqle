# Migration Guide: graqle v0.46 → v0.52

This guide covers breaking import path changes introduced between v0.46 and v0.52.
Backward-compatibility shims are provided for all renamed paths — they emit
`DeprecationWarning` and will be **removed in v0.55.0**.

---

## Summary of Changes

| Old path (v0.46) | New path (v0.52+) | Shim available? |
|---|---|---|
| `graqle.scorer.ChunkScorer` | `graqle.activation.chunk_scorer.ChunkScorer` | ✅ Yes |
| `graqle.cli.commands.scan.DocScanner` | `graqle.scanner.docs.DocumentScanner` | ✅ Yes |
| `graqle.backends.bedrock.BedrockBackend` | `graqle.backends.api.BedrockBackend` | ✅ Yes |
| `graqle.api.GraqleClient` | `graqle.core.Graqle` | ✅ Yes |
| `BedrockBackend(model_id=...)` | `BedrockBackend(model=...)` | ✅ Yes |
| `BedrockBackend(profile=...)` | `BedrockBackend(profile_name=...)` | ✅ Yes |

**Shim removal date:** v0.55.0

---

## 1. ChunkScorer

**Before (v0.46):**
```python
from graqle.scorer import ChunkScorer
```

**After (v0.52+):**
```python
from graqle.activation.chunk_scorer import ChunkScorer
```

---

## 2. DocumentScanner (was DocScanner)

**Before (v0.46):**
```python
from graqle.cli.commands.scan import DocScanner
scanner = DocScanner(nodes, edges, options=opts)
```

**After (v0.52+):**
```python
from graqle.scanner.docs import DocumentScanner
scanner = DocumentScanner(nodes, edges, options=opts)
```

---

## 3. BedrockBackend

**Before (v0.46):**
```python
from graqle.backends.bedrock import BedrockBackend
backend = BedrockBackend(model_id="anthropic.claude-sonnet-4-6-v1:0", profile="my-profile")
```

**After (v0.52+):**
```python
from graqle.backends.api import BedrockBackend
backend = BedrockBackend(model="anthropic.claude-sonnet-4-6-v1:0", profile_name="my-profile")
```

---

## 4. Graqle (was GraqleClient)

**Before (v0.46):**
```python
from graqle.api import GraqleClient
client = GraqleClient(graph_path="graqle.json")
```

**After (v0.52+):**
```python
from graqle.core.graph import Graqle
client = Graqle(graph_path="graqle.json")
```

---

## Detecting Stale Imports

Run `graq doctor` to automatically scan your project for deprecated import paths:

```
graq doctor
```

Sample output when stale imports are found:

```
!! Migration: stale imports   2 stale import(s) found — run: graq doctor --fix
-- stale import              src/my_module.py: 'graqle.scorer' → 'graqle.activation.chunk_scorer'
-- stale import              scripts/embed.py: 'graqle.api.GraqleClient' → 'graqle.core.Graqle'
```

---

## Timeline

| Version | Action |
|---|---|
| v0.46 | Original paths (now deprecated) |
| v0.52 | Shims added — DeprecationWarning on import |
| v0.55.0 | Shims removed — imports will fail |
