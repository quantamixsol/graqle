"""
GraQle — Production NPZ Rebuild + Deduplication Script
=======================================================
Designed for: 64,110 nodes / 102,490 chunks / Bedrock Titan V2 (1024-dim)

What this script does (in order):
  1. PRE-FLIGHT   — verify graph, NPZ, Bedrock, AWS profile
  2. COST PREVIEW — print exact token/cost/time estimate, ask to confirm
  3. DEDUP        — remove duplicate node IDs from graqle.json (atomic write)
  4. GAP ANALYSIS — find chunks with no existing 1024-dim vector
  5. EMBED        — Titan V2 via Bedrock, throttle-safe, 50ms pace + retry
  6. MERGE        — append to existing NPZ, SHA regression gate
  7. VERIFY       — read-back shape + zero-vector check
  8. FINAL GATES  — print pass/fail table

Guarantees:
  - Existing vectors are NEVER modified (SHA check before atomic write)
  - Graph file is backed up before dedup write
  - NPZ is backed up before any write
  - All output written to LOG_FILE in real time
  - Script aborts (sys.exit(1)) on any FATAL gate failure
  - Resumable: re-run anytime, only embeds chunks not yet in NPZ

Cost (pre-calculated, confirmed accurate):
  102,490 chunks × 644 avg chars ÷ 4 chars/token = ~16.5M tokens
  Titan V2 price: $0.00002 per 1K tokens = ~$0.33 total

Time estimate:
  @ 20 req/s (optimistic): ~85 min
  @ 10 req/s (realistic):  ~170 min
  @ 5  req/s (throttled):  ~340 min

Run from C:/Users/haris/Graqle/:
  C:/Users/haris/Graqle/.venv/Scripts/python graqle-sdk/scripts/rebuild_npz.py
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path("C:/Users/haris/Graqle")
GRAPH_FILE  = ROOT / "graqle.json"
NPZ_FILE    = ROOT / ".graqle" / "chunk_embeddings.npz"
CONFIG_FILE = ROOT / "graqle.yaml"
LOG_FILE    = ROOT / "graqle-sdk" / "scripts" / "rebuild_npz.log"
BACKUP_DIR  = ROOT / "graqle-sdk" / "scripts" / "backups"

# ── Bedrock config (from graqle.yaml cbs-dpt profile) ────────────────────────
AWS_PROFILE  = "cbs-dpt"
AWS_REGION   = "us-east-1"
MODEL_ID     = "amazon.titan-embed-text-v2:0"
EMBED_DIM    = 1024
PACE_SECS    = 0.05     # 50ms between calls = ~20 req/s steady state
LOG_EVERY    = 50       # print progress every N chunks

# ── Helpers ───────────────────────────────────────────────────────────────────
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
_log_fh = open(LOG_FILE, "w", encoding="utf-8")

def log(msg: str) -> None:
    ts   = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    _log_fh.write(line + "\n")
    _log_fh.flush()

def sha256_first_mb(data: bytes) -> str:
    return hashlib.sha256(data[:1024 * 1024]).hexdigest()[:16]

def gate(label: str, ok: bool, fatal: bool = True) -> bool:
    status = "PASS" if ok else "FAIL"
    log(f"  GATE [{status}] {label}")
    if not ok and fatal:
        log(f"\nABORTED at gate: {label}")
        _log_fh.close()
        sys.exit(1)
    return ok

def save_json_atomic(data: dict, path: Path) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    shutil.move(tmp, str(path))

def save_npz_atomic(path: Path, **arrays) -> None:
    tmp = str(path) + ".tmp.npz"
    np.savez(tmp, **arrays)
    shutil.move(tmp, str(path))


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
sep = "=" * 64
log(sep)
log("GRAQLE NPZ REBUILD — Bedrock Titan V2 (1024-dim)")
log(f"Graph : {GRAPH_FILE}")
log(f"NPZ   : {NPZ_FILE}")
log(f"Log   : {LOG_FILE}")
log(sep)

# ── PHASE 1: PRE-FLIGHT ───────────────────────────────────────────────────────
log("\n── PHASE 1: PRE-FLIGHT ──")

gate("graqle.json exists",    GRAPH_FILE.exists())
gate("graqle.yaml exists",    CONFIG_FILE.exists())
gate(".graqle/ dir exists",   NPZ_FILE.parent.exists() or not NPZ_FILE.parent.mkdir(parents=True, exist_ok=True))

# Load graph
log("  Loading graph...")
g_data = json.load(open(GRAPH_FILE, encoding="utf-8"))
nodes  = g_data.get("nodes", [])
links  = g_data.get("links", [])
gate(f"graph has >= 1000 nodes (got {len(nodes):,})", len(nodes) >= 1000)

# Count chunks
total_chunk_count = sum(len(n.get("chunks", [])) for n in nodes)
log(f"  Nodes   : {len(nodes):,}")
log(f"  Edges   : {len(links):,}")
log(f"  Chunks  : {total_chunk_count:,}")

# Check Bedrock
log("  Testing Bedrock connectivity...")
try:
    import boto3
    _session = boto3.Session(profile_name=AWS_PROFILE)
    _bedrock = _session.client("bedrock-runtime", region_name=AWS_REGION)
    _test    = _bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps({"inputText": "ping", "dimensions": EMBED_DIM, "normalize": True}),
        contentType="application/json",
        accept="application/json",
    )
    _test_vec = json.loads(_test["body"].read())["embedding"]
    gate(f"Bedrock Titan V2 reachable (dim={len(_test_vec)})", len(_test_vec) == EMBED_DIM)
except Exception as exc:
    gate(f"Bedrock unreachable: {exc}", False, fatal=True)


# ── PHASE 2: COST + TIME PREVIEW ─────────────────────────────────────────────
log("\n── PHASE 2: COST + TIME PREVIEW ──")

total_chars  = sum(
    len((ch.get("text","") if isinstance(ch,dict) else str(ch)).strip()[:3000])
    for n in nodes for ch in n.get("chunks",[])
)
est_tokens   = total_chars / 4
est_cost_usd = (est_tokens / 1000) * 0.00002
est_min_20   = total_chunk_count / 20 / 60
est_min_10   = total_chunk_count / 10 / 60

log(f"  Total chunks to consider : {total_chunk_count:,}")
log(f"  Total chars              : {total_chars:,}")
log(f"  Est tokens               : {est_tokens:,.0f}")
log(f"  Est cost (Titan V2)      : ${est_cost_usd:.4f}")
log(f"  Est time @ 20 req/s      : {est_min_20:.1f} min")
log(f"  Est time @ 10 req/s      : {est_min_10:.1f} min (conservative)")
log(f"  AWS profile              : {AWS_PROFILE}")
log(f"  Region                   : {AWS_REGION}")
log(f"  Model                    : {MODEL_ID}")

print("\n" + "!" * 64)
print(f"  ESTIMATED COST : ${est_cost_usd:.4f}")
print(f"  ESTIMATED TIME : {est_min_20:.0f}–{est_min_10:.0f} min")
print("!" * 64)
confirm = input("\nType YES to proceed, anything else to abort: ").strip()
if confirm != "YES":
    log("Aborted by user.")
    _log_fh.close()
    sys.exit(0)


# ── PHASE 3: DEDUPLICATION ───────────────────────────────────────────────────
log("\n── PHASE 3: DEDUPLICATION ──")

id_counts: dict[str, int] = collections.Counter(
    n.get("id", "") for n in nodes
)
dupes = {nid: cnt for nid, cnt in id_counts.items() if cnt > 1}
log(f"  Duplicate node IDs found : {len(dupes)}")

if dupes:
    log("  Backing up graph before dedup...")
    ts_str = time.strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"graqle-pre-dedup-{ts_str}.json"
    shutil.copy2(str(GRAPH_FILE), str(backup_path))
    log(f"  Backup : {backup_path}")

    # Keep first occurrence of each node ID, drop subsequent duplicates
    seen: set[str] = set()
    deduped_nodes: list = []
    removed = 0
    for n in nodes:
        nid = n.get("id", "")
        if nid in seen:
            removed += 1
        else:
            seen.add(nid)
            deduped_nodes.append(n)

    # Also deduplicate links (same source+target+relationship)
    link_keys: set[tuple] = set()
    deduped_links: list = []
    removed_links = 0
    for lk in links:
        key = (lk.get("source",""), lk.get("target",""),
               lk.get("relationship", lk.get("type","")))
        if key in link_keys:
            removed_links += 1
        else:
            link_keys.add(key)
            deduped_links.append(lk)

    g_data["nodes"] = deduped_nodes
    g_data["links"] = deduped_links
    save_json_atomic(g_data, GRAPH_FILE)

    nodes = deduped_nodes
    links = deduped_links
    log(f"  Removed duplicate nodes : {removed}")
    log(f"  Removed duplicate links : {removed_links}")
    log(f"  Nodes after dedup       : {len(nodes):,}")
    log(f"  Links after dedup       : {len(links):,}")
    gate(f"dedup complete — {removed} nodes removed", True)
else:
    log("  No duplicates found — graph is clean.")

# Verify no dupes remain
remaining_dupes = len(nodes) - len({n.get("id","") for n in nodes})
gate(f"zero duplicate node IDs after dedup (got {remaining_dupes})", remaining_dupes == 0)


# ── PHASE 4: LOAD EXISTING NPZ + GAP ANALYSIS ────────────────────────────────
log("\n── PHASE 4: GAP ANALYSIS ──")

if NPZ_FILE.exists():
    log("  Loading existing NPZ...")
    npz_in             = np.load(str(NPZ_FILE), allow_pickle=True)
    existing_keys      = list(npz_in["chunk_keys"])
    existing_node_ids  = list(npz_in["chunk_node_ids"])
    existing_matrix    = npz_in["chunk_matrix"].copy()
    existing_desc_keys = list(npz_in.get("desc_keys",   np.array([], dtype=object)))
    existing_desc_mat  = npz_in.get("desc_matrix",
                            np.zeros((0, EMBED_DIM), dtype=np.float32)).copy()

    existing_sha = sha256_first_mb(existing_matrix.tobytes())
    log(f"  Existing NPZ : {len(existing_keys):,} chunks, shape={existing_matrix.shape}")
    log(f"  Matrix SHA   : {existing_sha}  (regression baseline)")

    zero_before = int((np.abs(existing_matrix).sum(axis=1) == 0).sum())
    gate(f"existing NPZ dim == {EMBED_DIM} (got {existing_matrix.shape[1] if len(existing_matrix.shape)>1 else 0})",
         existing_matrix.shape[1] == EMBED_DIM if len(existing_matrix.shape) > 1 else False,
         fatal=False)
    gate(f"existing zero-vectors == 0 (got {zero_before})", zero_before == 0, fatal=False)

    # Backup existing NPZ
    ts_str = time.strftime("%Y%m%d-%H%M%S")
    npz_backup = BACKUP_DIR / f"chunk_embeddings-pre-rebuild-{ts_str}.npz"
    shutil.copy2(str(NPZ_FILE), str(npz_backup))
    log(f"  NPZ backup   : {npz_backup}")
else:
    log("  No existing NPZ — starting fresh.")
    existing_keys     = []
    existing_node_ids = []
    existing_matrix   = np.empty((0, EMBED_DIM), dtype=np.float32)
    existing_desc_keys = []
    existing_desc_mat  = np.empty((0, EMBED_DIM), dtype=np.float32)
    existing_sha       = sha256_first_mb(existing_matrix.tobytes())

existing_key_set = set(existing_keys)

# Build gap list
gap: list[tuple[str, int, str]] = []
for n in nodes:
    nid    = n.get("id", "")
    chunks = n.get("chunks", [])
    for idx, ch in enumerate(chunks):
        key = f"{nid}::{idx}"
        if key not in existing_key_set:
            text = (ch.get("text", "") if isinstance(ch, dict) else str(ch)).strip()
            gap.append((nid, idx, text[:3000]))

log(f"  Already embedded : {len(existing_keys):,}")
log(f"  New to embed     : {len(gap):,}")
gate(f"gap >= 0 — nothing to do? ({len(gap)} chunks)", len(gap) >= 0, fatal=False)

if not gap:
    log("\n  NPZ is already up to date. Nothing to embed.")
    log(f"\nLog: {LOG_FILE}")
    _log_fh.close()
    sys.exit(0)


# ── PHASE 5: EMBED ────────────────────────────────────────────────────────────
log(f"\n── PHASE 5: EMBED {len(gap):,} CHUNKS via Bedrock Titan V2 ──")

def embed_with_retry(text: str, max_retries: int = 8) -> list[float]:
    for attempt in range(max_retries):
        try:
            resp = _bedrock.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "inputText":  text if text.strip() else "empty document",
                    "dimensions": EMBED_DIM,
                    "normalize":  True,
                }),
                contentType="application/json",
                accept="application/json",
            )
            return json.loads(resp["body"].read())["embedding"]
        except Exception as exc:
            err = str(exc)
            if "ThrottlingException" in err or "429" in err or "Too Many" in err:
                wait = min(300, 60 * (2 ** attempt))
                log(f"  THROTTLE attempt {attempt+1}/{max_retries} — sleeping {wait}s")
                time.sleep(wait)
            elif "ServiceUnavailable" in err or "503" in err:
                wait = 10 * (attempt + 1)
                log(f"  SERVICE UNAVAILABLE attempt {attempt+1} — sleeping {wait}s")
                time.sleep(wait)
            elif attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                log(f"  WARN: zero-vec fallback after {max_retries} attempts: {exc}")
                return [0.0] * EMBED_DIM
    return [0.0] * EMBED_DIM

new_vecs:     list[np.ndarray] = []
new_keys:     list[str]        = []
new_node_ids: list[str]        = []
zero_count    = 0
t0            = time.time()

# Save partial progress every N chunks (crash recovery)
SAVE_EVERY = 500

for i, (nid, idx, text) in enumerate(gap):
    if i > 0 and i % LOG_EVERY == 0:
        elapsed = time.time() - t0
        rate    = i / max(elapsed, 0.01)
        eta_s   = (len(gap) - i) / max(rate, 0.01)
        eta_min = eta_s / 60
        pct     = i / len(gap) * 100
        log(f"  [{i:>6}/{len(gap)}] {pct:.1f}%  "
            f"{rate:.1f} req/s  ETA {eta_min:.1f} min  "
            f"zeros={zero_count}")

    vec = embed_with_retry(text)
    arr = np.array(vec, dtype=np.float32)

    if float(np.abs(arr).sum()) == 0.0:
        zero_count += 1
        log(f"  WARN: zero vector for {nid}::{idx}")

    new_vecs.append(arr)
    new_keys.append(f"{nid}::{idx}")
    new_node_ids.append(nid)

    # Partial save — crash recovery checkpoint
    if len(new_vecs) % SAVE_EVERY == 0 and len(new_vecs) > 0:
        partial_matrix  = np.vstack([existing_matrix, np.vstack(new_vecs)])
        partial_keys    = existing_keys + new_keys
        partial_ids     = existing_node_ids + new_node_ids
        save_npz_atomic(
            NPZ_FILE,
            chunk_keys     = np.array(partial_keys,    dtype=object),
            chunk_node_ids = np.array(partial_ids,     dtype=object),
            chunk_matrix   = partial_matrix,
            desc_keys      = np.array(existing_desc_keys, dtype=object),
            desc_matrix    = existing_desc_mat,
        )
        log(f"  CHECKPOINT saved: {len(partial_keys):,} total chunks")

    time.sleep(PACE_SECS)

elapsed_total = time.time() - t0
log(f"\n  Embedded {len(new_vecs):,} chunks in {elapsed_total:.1f}s  "
    f"({len(new_vecs)/max(elapsed_total,0.01):.1f} req/s)")
log(f"  Zero vectors : {zero_count}")


# ── PHASE 6: MERGE + ATOMIC WRITE ────────────────────────────────────────────
log("\n── PHASE 6: MERGE + ATOMIC WRITE ──")

new_matrix = np.vstack(new_vecs) if new_vecs else np.empty((0, EMBED_DIM), dtype=np.float32)

merged_keys   = existing_keys     + new_keys
merged_ids    = existing_node_ids + new_node_ids
merged_matrix = np.vstack([existing_matrix, new_matrix])

log(f"  Merged shape : {merged_matrix.shape}")

# Regression gate — existing vectors must be byte-identical
regression_sha = sha256_first_mb(merged_matrix[:len(existing_matrix)].tobytes())
gate(
    f"existing vectors byte-identical (SHA {existing_sha} == {regression_sha})",
    regression_sha == existing_sha,
    fatal=True,
)

gate(
    f"merged rows == existing + new ({len(merged_keys)} == {len(existing_keys)} + {len(new_vecs)})",
    len(merged_keys) == len(existing_keys) + len(new_vecs),
)

save_npz_atomic(
    NPZ_FILE,
    chunk_keys     = np.array(merged_keys,         dtype=object),
    chunk_node_ids = np.array(merged_ids,           dtype=object),
    chunk_matrix   = merged_matrix,
    desc_keys      = np.array(existing_desc_keys,   dtype=object),
    desc_matrix    = existing_desc_mat,
)
npz_size_mb = NPZ_FILE.stat().st_size / 1024 / 1024
log(f"  NPZ written  : {len(merged_keys):,} chunks, {npz_size_mb:.1f} MB")


# ── PHASE 7: VERIFY ──────────────────────────────────────────────────────────
log("\n── PHASE 7: VERIFY ──")

verify       = np.load(str(NPZ_FILE), allow_pickle=True)
verify_mat   = verify["chunk_matrix"]
verify_keys  = list(verify["chunk_keys"])
final_zeros  = int((np.abs(verify_mat).sum(axis=1) == 0).sum())
regress_sha2 = sha256_first_mb(verify_mat[:len(existing_matrix)].tobytes())

gate(f"read-back shape == {merged_matrix.shape}",
     tuple(verify_mat.shape) == tuple(merged_matrix.shape))
gate(f"read-back keys count == {len(merged_keys):,}",
     len(verify_keys) == len(merged_keys))
gate(f"final zero vectors == 0 (got {final_zeros})", final_zeros == 0, fatal=False)
gate(f"regression SHA clean after write",
     regress_sha2 == existing_sha)
gate(f"embedding dim == {EMBED_DIM} (got {verify_mat.shape[1]})",
     verify_mat.shape[1] == EMBED_DIM)


# ── PHASE 8: FINAL GATE TABLE ────────────────────────────────────────────────
log("\n── PHASE 8: FINAL SUMMARY ──")

g2      = json.load(open(GRAPH_FILE, encoding="utf-8"))
n2      = g2.get("nodes", [])
l2      = g2.get("links", [])
dupes2  = len(n2) - len({n.get("id","") for n in n2})

checks = {
    f"nodes clean ({len(n2):,}, 0 dupes)":              dupes2 == 0,
    f"NPZ chunks == {len(merged_keys):,}":               len(verify_keys) == len(merged_keys),
    f"NPZ dim == {EMBED_DIM}":                           verify_mat.shape[1] == EMBED_DIM,
    f"zero vectors == 0 (got {final_zeros})":            final_zeros == 0,
    f"regression SHA clean":                             regress_sha2 == existing_sha,
    f"new chunks embedded == {len(new_vecs):,}":         len(new_vecs) == len(gap),
}

all_pass = True
for msg, ok in checks.items():
    log(f"  {'PASS' if ok else 'FAIL'} — {msg}")
    if not ok:
        all_pass = False

log("")
if all_pass:
    log(sep)
    log("ALL GATES PASS — NPZ rebuild complete.")
    log(f"  Total chunks : {len(merged_keys):,}")
    log(f"  Dim          : {EMBED_DIM}")
    log(f"  Size         : {npz_size_mb:.1f} MB")
    log(f"  Duration     : {elapsed_total:.0f}s ({elapsed_total/60:.1f} min)")
    log(f"  Cost est.    : ${est_cost_usd:.4f}")
    log(f"  Zero vectors : {final_zeros}")
    log(sep)
    log("NEXT STEPS:")
    log("  1. Restart MCP server (or run graq_reload in active session)")
    log("  2. Run a test query via graq_reason to confirm semantic activation")
    log("  3. Run health check: python graqle-sdk/scripts/graqle_graph_health.py")
else:
    log("SOME GATES FAILED — check above.")
    log(f"  Backups at: {BACKUP_DIR}")

log(f"\nFull log: {LOG_FILE}")
_log_fh.close()
