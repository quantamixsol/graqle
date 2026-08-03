# Codex listing assets

## Present

- `graqle-logo-256.png` — the listing icon, referenced by `interface.logo`.

## Still needed — three screenshots

Drop these in **this directory** with **exactly these filenames**, then add them to
`interface.screenshots` in `../.codex-plugin/plugin.json`:

| Filename | Must show |
|---|---|
| `screenshot-1-graph.png` | The knowledge graph rendered — nodes and connections. Hundreds of nodes, not a 5-node toy. Most visually distinctive asset we have. |
| `screenshot-2-reasoning.png` | A real `graq reason` answer **with the confidence score visible in frame**. Do not crop the score out — it is the differentiator. A 70–90% score is more credible than a perfect one. |
| `screenshot-3-studio.png` | A GraQle Studio view showing **graph or reasoning output** — not billing or account settings, which the plugin cannot do and would confuse a reviewer about what they are approving. |

### Specifications

- **PNG**, under 2 MB each
- **1280×800** preferred; 1440×900 or 1920×1200 fine — keep all three the **same aspect ratio**
- Text must stay legible when scaled to ~600px wide

### ⚠️ Check before committing — these ship publicly and permanently

- [ ] No API keys, tokens, licence keys or `.env` contents
- [ ] No client or employer code, module names, repo names or internal URLs
- [ ] No personal data — emails, real names in commit authorship
- [ ] Nothing from the **CrawlQ / TraceGov** side (product-separation rule)
- [ ] No trade-secret internals — weights, thresholds, `AGREEMENT_THRESHOLD`, calibration values
- [ ] No local filesystem paths revealing machine or directory structure

**Use a public open-source repo as the demo subject.** Safe by construction, and it gives
a reviewer something recognisable.

### Why `screenshots` is currently `[]`

`tests/test_packaging/test_codex_plugin_assets.py` asserts that every referenced asset
resolves to a real file. The paths were wired ahead of the images and the guard correctly
failed, so they were removed again — an empty list is allowed, a dangling reference is
not. **Add the files first, then the entries**, and the guard will confirm both.
