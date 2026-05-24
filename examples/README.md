# GraQle Examples

Runnable examples for GraQle. Each is self-contained and uses only the public API.

| File | What it shows | Run time |
|------|---------------|----------|
| `quickstart.py` | Build a KG and ask a governed question | ~30s |
| `governance_example.py` | Governance primitives | ~10s |
| **`v059_cryptographic_governance_usecase.py`** | **Layer 5 cryptographic tamper-evidence, a real use case, step by step** | ~3s |
| **`v059_e2e_dogfood.py`** | Smoke-test every Layer 5 feature against the installed package | ~2s |

---

## 1. Setup (zero to running, ~60 seconds)

```bash
# 1. a clean virtual environment
python -m venv graqle-demo
source graqle-demo/bin/activate          # Windows: graqle-demo\Scripts\activate

# 2. install GraQle from PyPI (Layer 5 ships in 0.59.0+)
pip install graqle                       # or: pip install graqle==0.59.0

# 3. confirm
python -c "import graqle, graqle.__version__ as v; print('graqle', v.__version__)"
```

`cryptography` (for ed25519) ships as a core dependency — nothing else to install.

---

## 2. Run the cryptographic-governance use case (the headline demo)

```bash
# from a checkout of the repo:
python examples/v059_cryptographic_governance_usecase.py

# or fetch just the one file and run it anywhere:
#   curl -O https://raw.githubusercontent.com/quantamixsol/graqle/master/examples/v059_cryptographic_governance_usecase.py
#   python v059_cryptographic_governance_usecase.py
```

**The story it runs** — a bank's AI declines a loan, and you watch the decision become
tamper-evident, end to end:

1. **Governed decision** — the AI returns `DECLINE` on a loan application.
2. **Layer 5 locks (monotonic-on)** — first governed write locks the layer; trying to
   disable it is **refused and itself audited** (EU AI Act Article 12).
3. **Canonicalize (RFC 8785)** — and *prove* the leaf/wrapper split (operational fields
   don't change the cryptographic hash).
4. **Merkle commit (RFC 6962)** — the day's decisions reduce to one root.
5. **ed25519 sign** under a key with a validity window.
6. **Anchor** — `{root, kid, signature}` published to a public transparency log
   (Sigstore Rekor in production).
7. **Auditor verifies, six months later, with zero access** → **AUTHENTIC**.
8. **Tamperer flips DECLINE→APPROVE** → **TAMPER DETECTED**.
9. **Key compromised → revoked** → even its original valid signature stops verifying.

Expected final banner: `USE CASE COMPLETE` (exit code 0).

### Verify the published package end-to-end

```bash
python examples/v059_e2e_dogfood.py
# -> 10/10 passed
# -> ALL NEW v0.59.0 FEATURES VERIFIED WORKING
```

---

## 3. Use it in your own code (the minimal real-life recipe)

```python
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from graqle.governance.tamper_evidence.merkle import MerkleTree
from graqle.governance.custody import Ed25519KeyManifest

UTC = timezone.utc

# your governed decisions for this batch (dicts with the leaf fields)
records = [
    {"proof_format_version": "1.0.0", "record_id": "decision-1",
     "content_hash": "sha256:...", "timestamp_unix": 1780000000,
     "governance_metadata": {"decision": "DECLINE", "reason_code": "..."}},
]

# 1. commit to a Merkle root
root_hex = MerkleTree.from_records(records).root_hex

# 2. sign the root with a windowed ed25519 key
priv = Ed25519PrivateKey.generate()
keys = Ed25519KeyManifest()
keys.register("my-signing-key-2026-Q2", priv.public_key(),
              valid_from=datetime(2026, 1, 1, tzinfo=UTC),
              valid_until=datetime(2026, 12, 31, tzinfo=UTC),
              private_key=priv)
signature = keys.sign("my-signing-key-2026-Q2", bytes.fromhex(root_hex))

# 3. publish {root_hex, kid, signature} to your transparency log (Sigstore Rekor).
# 4. anyone with the records + that public anchor + the public key can now verify:
verifier = Ed25519KeyManifest()
verifier.register("my-signing-key-2026-Q2", priv.public_key(),  # public key only
                  valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                  valid_until=datetime(2026, 12, 31, tzinfo=UTC))
ok = (MerkleTree.from_records(records).root_hex == root_hex
      and verifier.verify("my-signing-key-2026-Q2", bytes.fromhex(root_hex), signature))
print("AUTHENTIC" if ok else "TAMPERED")
```

To enable Layer 5 in a real deployment, set `attestation.enabled: true` in `graqle.yaml`
(it is off by default — with it off, output is byte-identical to a pre-Layer-5 release).

---

## 4. Run it through the MCP server (Claude Code / Cursor / VS Code)

GraQle ships an MCP server exposing its tools as `graq_*` commands inside your AI IDE,
so you can drive a real-life governed workflow conversationally — no scripts.

### Start the server

```bash
pip install "graqle[api]"
graq mcp serve            # exposes the graq_* / kogni_* tools over MCP
```

Register it with your client (Claude Code example, `.mcp.json`):

```json
{
  "mcpServers": {
    "graqle": { "command": "graq", "args": ["mcp", "serve"] }
  }
}
```

### A real-life workflow, end to end, in MCP commands

Build a graph of your codebase, then reason and govern over it:

```text
graq_inspect                      # graph stats + hub nodes (start here)
graq_context(query="loan decision audit path", deep=true)
                                  # focused context: which modules/decisions matter
graq_reason(question="Does our loan-decision path produce a tamper-evident audit record?")
                                  # multi-agent answer with confidence + traced activation
graq_impact(component="governance/tamper_evidence")
                                  # blast radius before any change
graq_preflight(action="enable Layer 5 cryptographic tamper-evidence in production")
                                  # safety check + relevant lessons
graq_reason(question="Walk the full journey: decision -> Merkle commit -> Rekor anchor -> auditor verify")
graq_learn(action="enabled Layer 5", outcome="success",
           lesson="monotonic-on locks the layer on first governed write")
                                  # teach the graph the outcome
```

Or use the smart router slash command in Claude Code:

```text
/graq Does enabling Layer 5 change our write-path latency, and what gets anchored to Rekor?
```

The same five layers the script demonstrates (substrate → reasoning → governed trace →
permit enforcement → cryptographic tamper-evidence) are what the MCP tools reason over —
the script shows the *cryptographic mechanics*, the MCP commands show *governed reasoning
about your own system* on top of them.

---

## Troubleshooting

- **`ModuleNotFoundError: graqle.governance.custody`** — you're on a pre-0.59.0 install.
  `pip install --upgrade graqle==0.59.0` (Layer 5 landed in 0.59.0).
- **The dogfood prints a version other than 0.59.0** — your `python` is resolving an
  older install; use the venv's interpreter explicitly (`graqle-demo/bin/python ...`).
- **`graq: command not found`** — install the CLI extras: `pip install "graqle[api]"`.
