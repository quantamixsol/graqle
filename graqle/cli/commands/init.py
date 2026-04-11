"""graq init — set up intelligent development for any project and IDE.

Creates graqle.yaml, graqle.json (knowledge graph from scan),
MCP server registration (IDE-specific), AI instructions file,
and .graq/ workspace structure. Works with any IDE or terminal.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.init
# risk: HIGH (impact radius: 2 modules)
# consumers: main, test_init
# dependencies: __future__, json, logging, os, re +13 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.table import Table

from graqle.cli.console import BRAND_NAME

console = Console()
logger = logging.getLogger("graqle.cli.init")

# ──────────────────────────────────────────────────────────────────────
# Backend / model registry
# ──────────────────────────────────────────────────────────────────────

BACKENDS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "models": [
            ("claude-sonnet-4-6", "Claude Sonnet — Balanced, recommended ($0.003/query)", True),
            ("claude-haiku-4-5-20251001", "Claude Haiku — Fast + cheap ($0.001/query)", False),
            ("claude-opus-4-6", "Claude Opus — Most capable ($0.05/query)", False),
        ],
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "name": "OpenAI",
        "models": [
            ("gpt-5.4-mini", "GPT-5.4 Mini — Fast + high quality ($0.002/query)", True),
            ("gpt-4o-mini", "GPT-4o-mini — Fast + cheap ($0.002/query)", False),
            ("gpt-4o", "GPT-4o — Balanced ($0.01/query)", False),
            ("gpt-5.4", "GPT-5.4 — Most capable ($0.01/query)", False),
        ],
        "api_key_env": "OPENAI_API_KEY",
    },
    "groq": {
        "name": "Groq (Fast Inference)",
        "models": [
            ("llama-3.3-70b-versatile", "Llama 3.3 70B — Fast + capable ($0.0006/query)", True),
            ("llama-3.1-8b-instant", "Llama 3.1 8B — Ultra-fast ($0.00005/query)", False),
            ("gemma2-9b-it", "Gemma 2 9B — Lightweight ($0.0002/query)", False),
            ("mixtral-8x7b-32768", "Mixtral 8x7B — 32K context ($0.0002/query)", False),
        ],
        "api_key_env": "GROQ_API_KEY",
    },
    "gemini": {
        "name": "Google Gemini",
        "models": [
            ("gemini-2.0-flash", "Gemini 2.0 Flash — Fast + cheap ($0.0001/query)", True),
            ("gemini-2.5-pro", "Gemini 2.5 Pro — Most capable ($0.001/query)", False),
            ("gemini-2.5-flash", "Gemini 2.5 Flash — Balanced ($0.00015/query)", False),
            ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite — Ultra-cheap ($0.00004/query)", False),
        ],
        "api_key_env": "GEMINI_API_KEY",
    },
    "ollama": {
        "name": "Ollama (Local / Free)",
        "models": [
            ("qwen2.5:7b", "Qwen 2.5 7B — Good general purpose (free, local)", True),
            ("llama3.2:3b", "Llama 3.2 3B — Fast + lightweight (free, local)", False),
            ("codestral:22b", "Codestral 22B — Code-focused (free, local)", False),
            ("deepseek-r1:8b", "DeepSeek R1 8B — Reasoning (free, local)", False),
        ],
        "api_key_env": None,
    },
    "bedrock": {
        "name": "AWS Bedrock",
        "models": [
            (
                "anthropic.claude-sonnet-4-6-v1:0",
                "Claude Sonnet on Bedrock — Recommended",
                True,
            ),
            (
                "anthropic.claude-haiku-4-5-20251001-v1:0",
                "Claude Haiku on Bedrock — Fast + cheap",
                False,
            ),
        ],
        "api_key_env": "AWS_ACCESS_KEY_ID",
    },
    "deepseek": {
        "name": "DeepSeek",
        "models": [
            ("deepseek-chat", "DeepSeek Chat — Ultra-cheap ($0.00014/query)", True),
            ("deepseek-reasoner", "DeepSeek Reasoner — Chain-of-thought ($0.0006/query)", False),
        ],
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "together": {
        "name": "Together AI",
        "models": [
            ("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama 3.3 70B Turbo ($0.0009/query)", True),
            ("meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "Llama 3.1 8B Turbo ($0.0002/query)", False),
            ("Qwen/Qwen2.5-72B-Instruct-Turbo", "Qwen 2.5 72B ($0.0012/query)", False),
        ],
        "api_key_env": "TOGETHER_API_KEY",
    },
    "mistral": {
        "name": "Mistral AI",
        "models": [
            ("mistral-small-latest", "Mistral Small — Fast + cheap ($0.0002/query)", True),
            ("mistral-large-latest", "Mistral Large — Most capable ($0.002/query)", False),
            ("codestral-latest", "Codestral — Code-focused ($0.0003/query)", False),
        ],
        "api_key_env": "MISTRAL_API_KEY",
    },
    "openrouter": {
        "name": "OpenRouter (Multi-provider)",
        "models": [
            ("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B ($0.0004/query)", True),
            ("google/gemini-2.0-flash-001", "Gemini 2.0 Flash ($0.0001/query)", False),
            ("deepseek/deepseek-chat-v3-0324", "DeepSeek Chat ($0.00014/query)", False),
        ],
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "fireworks": {
        "name": "Fireworks AI",
        "models": [
            ("accounts/fireworks/models/llama-v3p3-70b-instruct", "Llama 3.3 70B ($0.0009/query)", True),
            ("accounts/fireworks/models/llama-v3p1-8b-instruct", "Llama 3.1 8B ($0.0002/query)", False),
        ],
        "api_key_env": "FIREWORKS_API_KEY",
    },
    "cohere": {
        "name": "Cohere",
        "models": [
            ("command-r-plus", "Command R+ — Most capable ($0.0025/query)", True),
            ("command-r", "Command R — Fast ($0.00015/query)", False),
        ],
        "api_key_env": "COHERE_API_KEY",
    },
    "custom": {
        "name": "Custom OpenAI-compatible endpoint",
        "models": [],
        "api_key_env": "CUSTOM_API_KEY",
    },
}

# ──────────────────────────────────────────────────────────────────────
# AI instructions content — universal across IDEs
# ──────────────────────────────────────────────────────────────────────

AI_INSTRUCTIONS_SECTION = r"""
# GraQle — Dev Intelligence Layer

> Auto-generated by `graq init`. Provides your AI coding assistant with
> structured access to your project's knowledge graph, reasoning engine,
> and session memory — regardless of which IDE or AI tool you use.

---

## MANDATORY: When to Use GraQle (Trigger Rules)

**If the user says any of these, you MUST use GraQle MCP tools — do NOT fall back to your own file reading/grep/agent tools:**

- "use graqle", "ask graqle", "graqle reason", "graq reason"
- "use the knowledge graph", "check the KG", "what does the graph say"
- "kogni reason", "kogni impact", "kogni preflight", "kogni context"
- "/graq", "/kogni" (slash commands)

**When triggered, follow this protocol:**
1. Classify the question (see Smart Query Routing below)
2. Call the appropriate GraQle MCP tool (`graq_reason`, `graq_impact`, `graq_preflight`, `graq_context`, `graq_lessons`, `graq_learn`, `graq_inspect`)
3. Present the GraQle answer to the user
4. Only supplement with your own tools if GraQle's answer is incomplete

**Auto-trigger (use GraQle without being asked) when:**
- The question spans 3+ services, modules, or files ("what depends on X?")
- The question is about impact analysis ("what breaks if I change X?")
- The question is about past mistakes or lessons learned
- The question requires multi-hop reasoning across the architecture
- You would otherwise need to read 5+ files to answer

**Do NOT use GraQle for:**
- Single-file edits where you already know the file
- Git operations, deployment commands
- Questions about code you're currently looking at in the editor
- Simple lookups that a grep can answer

---

## What GraQle Does

GraQle turns your codebase into a **knowledge graph** where every module,
service, config, and dependency is a node. It then provides:

1. **Focused context** — 500-token summaries instead of 20-60K brute-force file reads
2. **Graph reasoning** — multi-agent reasoning across your entire architecture
3. **Impact analysis** — "what breaks if I change X?" answered in seconds
4. **Lessons learned** — past mistakes surfaced before you repeat them
5. **Auto-growing graph** — git hooks keep the KG in sync with your code

---

## Available Tools

### MCP Tools (Claude Code, Cursor, VS Code, and MCP-compatible IDEs)

These are the PRIMARY tools. Use them when GraQle is triggered.

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `graq_context` | Focused context for a service/module | "Tell me about X", "What does X do?" |
| `graq_reason` | Multi-agent graph reasoning | "Why does X?", "How does X work end-to-end?" |
| `graq_reason_batch` | Parallel reasoning over multiple queries | Batch code review, multi-file analysis |
| `graq_inspect` | Graph structure inspection | "How many nodes?", "Graph stats" |
| `graq_preflight` | Pre-change safety check | "What should I check before changing X?" |
| `graq_impact` | Impact analysis for changes | "What breaks if I change X?" |
| `graq_lessons` | Past mistake patterns | "What went wrong with X?", "Common failures?" |
| `graq_learn` | Teach the graph new knowledge | "Remember that X depends on Y" |
| `graq_safety_check` | Combined impact + preflight + reasoning | Pre-deployment safety gate |
| `graq_reload` | Force-reload graph from disk | After manual graph edits or graq learn |
| `graq_audit` | Deep KG health audit (chunk coverage) | Validate evidence quality for reasoning |
| `graq_gate` | Pre-compiled intelligence gate | Instant module context, impact, scorecard |
| `graq_drace` | DRACE governance scoring | Audit trails, explainability |
| `graq_runtime` | Live runtime observability | CloudWatch/Azure/GCP log queries |
| `graq_route` | Task routing to optimal backend | Route queries by complexity/cost |
| `graq_lifecycle` | Module lifecycle analysis | Track module maturity and stability |

All tools are also available with `kogni_` prefix (backward compatibility).

### CLI (works in any terminal)
| Command | What it does |
|---------|-------------|
| `graq run "<query>"` | Reason over the knowledge graph |
| `graq context <name>` | Get 500-token focused context for any entity |
| `graq inspect --stats` | Graph statistics (nodes, edges, density) |
| `graq scan repo .` | Re-scan codebase and rebuild the KG |
| `graq doctor` | Health check your installation |
| `graq setup-guide` | Step-by-step backend setup |

### Python SDK (works everywhere)
```python
from graqle import Graqle
from graqle.backends.api import AnthropicBackend

graph = Graqle.from_json("graqle.json")
graph.set_default_backend(AnthropicBackend(model="claude-sonnet-4-6"))
result = graph.reason("What depends on the auth service?")
print(result.answer)
```

---

## Smart Query Routing

Always pick the **cheapest correct approach** before calling expensive tools:

| Query Type | Route | Cost | When |
|-----------|-------|------|------|
| **LOOKUP** | `grep` or read KG files | ~200 tokens | Single fact, named entity |
| **CROSS-CUT** | Read specific KG section | ~300-800 tokens | Spans 2-3 known entities |
| **IMPACT** | `graq_impact` | ~800-1500 tokens | "What breaks if..." |
| **REASONING** | `graq_reason` | ~1500-3000 tokens | Multi-hop "why/how" questions |
| **PREFLIGHT** | `graq_preflight` | ~500-1000 tokens | Pre-change safety check |
| **LESSONS** | `graq_lessons` | ~400-800 tokens | Past mistake patterns |

**Rules:**
1. **Cheapest first.** Always try grep/read before MCP tools.
2. **Never use graq_reason for lookups.** A grep is 10x cheaper.
3. **Escalate, don't guess.** If grep finds nothing, escalate to next tier.
4. **When the user explicitly asks for GraQle, skip to the right MCP tool.** Don't second-guess — they want graph reasoning.

---

## Session Continuity (optional — .graq/ workspace)

GraQle can maintain structured memory across sessions:

```
.graq/
├── main.md           — project roadmap and goals
├── registry.md       — active branches/tasks
├── branches/
│   └── main/
│       ├── commit.md     — milestone summaries
│       ├── log.md        — session trace
│       └── metadata.yaml — branch state
└── checkpoints/      — archived session snapshots
```

### Session Start
1. Read `.graq/main.md` (~300 tokens)
2. Read `.graq/branches/{active}/commit.md` (~400 tokens)
3. Resume from last checkpoint

### During Work
- Checkpoint after every completed milestone
- Auto-checkpoint every 30 minutes

### Session End
- Save progress (even if incomplete)
- Create checkpoint for next session

---

## Configuration

- `graqle.yaml` — Model backend, cost budgets, activation strategy
- `graqle.json` — The knowledge graph (auto-generated by `graq scan repo .`)
- `.mcp.json` — MCP server registration (IDE-specific)

To re-scan: `graq scan repo .`
To query: `graq run "your question"`
To get context: `graq context <service-name>`
""".strip()

# Keep backward compat for existing code referencing old name
CLAUDE_MD_SECTION = AI_INSTRUCTIONS_SECTION

# ──────────────────────────────────────────────────────────────────────
# Repo scanning (enhanced from scan.py)
# ──────────────────────────────────────────────────────────────────────

_SKIP_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".next",
    ".nuxt",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "egg-info",
    ".eggs",
    "out",
}

_PYTHON_EXTS = {".py"}
_JS_TS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_CONFIG_NAMES = {
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env",
    ".env.example",
    "requirements.txt",
    "Pipfile",
}


def _should_skip(path: Path) -> bool:
    """Return True if *path* (or any ancestor) is in the skip set."""
    return any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts)


def _detect_project_type(root: Path) -> str:
    """Detect whether the project is Python, Node, or monorepo."""
    has_python = (root / "pyproject.toml").exists() or (root / "setup.py").exists()
    has_node = (root / "package.json").exists()
    if has_python and has_node:
        return "monorepo"
    if has_node:
        return "node"
    return "python"


def _extract_python_imports(content: str) -> list[str]:
    """Return local-looking import targets from Python source."""
    imports: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("from ") or stripped.startswith("import "):
            match = re.match(r"(?:from|import)\s+([\w.]+)", stripped)
            if match:
                module = match.group(1)
                # Keep relative and dotted (likely local) imports
                if "." in module:
                    imports.append(module)
    return imports


def _extract_js_imports(content: str) -> list[str]:
    """Return local import paths from JS/TS source."""
    imports: list[str] = []
    for match in re.finditer(
        r"""(?:import|require)\s*\(?\s*['"]([./][^'"]+)['"]\s*\)?""", content
    ):
        imports.append(match.group(1))
    for match in re.finditer(r"""from\s+['"]([./][^'"]+)['"]""", content):
        imports.append(match.group(1))
    return imports


def _chunk_source_code(content: str, max_chunk_chars: int = 1500) -> list[dict[str, str]]:
    """Split source code into semantic chunks at function/class boundaries.

    Each chunk is a dict with "text" and "type" keys, matching the format
    expected by CogniNode._build_evidence_text().

    Strategy: split on top-level def/class/function/export boundaries.
    If a block exceeds max_chunk_chars, split it further by blank lines.
    """
    chunks: list[dict[str, str]] = []
    lines = content.splitlines(keepends=True)

    if not lines:
        return []

    # Patterns that start a new semantic block
    boundary_patterns = (
        "def ", "class ", "async def ",           # Python
        "function ", "export ", "const ", "let ",  # JS/TS
        "import ", "from ",                        # import blocks
        "describe(", "it(", "test(",              # tests
    )

    current_block: list[str] = []
    block_type = "source_code"

    def _flush_block() -> None:
        text = "".join(current_block).strip()
        if not text or len(text) < 20:
            return
        # If block is too large, split by blank lines
        if len(text) > max_chunk_chars:
            sub_parts = re.split(r"\n\s*\n", text)
            accum = ""
            for part in sub_parts:
                if len(accum) + len(part) > max_chunk_chars and accum:
                    chunks.append({"text": accum.strip(), "type": block_type})
                    accum = part
                else:
                    accum = accum + "\n\n" + part if accum else part
            if accum.strip():
                chunks.append({"text": accum.strip(), "type": block_type})
        else:
            chunks.append({"text": text, "type": block_type})

    for line in lines:
        stripped = line.lstrip()
        # Check if this line starts a new top-level block
        is_boundary = (
            any(stripped.startswith(p) for p in boundary_patterns)
            and not line[0:1].isspace()  # top-level only (no indentation)
        )

        if is_boundary and current_block:
            _flush_block()
            current_block = [line]
            # Detect block type
            if stripped.startswith(("def ", "async def ")):
                block_type = "function"
            elif stripped.startswith("class "):
                block_type = "class"
            elif stripped.startswith(("import ", "from ")):
                block_type = "imports"
            elif stripped.startswith(("export ",)):
                block_type = "export"
            elif stripped.startswith(("describe(", "it(", "test(")):
                block_type = "test"
            else:
                block_type = "source_code"
        else:
            current_block.append(line)

    # Flush remaining
    if current_block:
        _flush_block()

    return chunks


def _summarize_file(content: str, file_path: str, max_len: int = 300) -> str:
    """Generate a rich description from file content (no LLM needed).

    Extracts exports, function signatures, class names, and docstrings
    to create a meaningful description for the node agent.
    """
    lines = content.splitlines()
    parts: list[str] = []

    # Extract docstring (first triple-quote block or JSDoc)
    for i, line in enumerate(lines[:20]):
        stripped = line.strip()
        if stripped.startswith(('"""', "'''", "/*", "/**")):
            doc_lines = []
            for j in range(i, min(i + 8, len(lines))):
                doc_lines.append(lines[j].strip().strip('"\'*/'))
            doc = " ".join(dl for dl in doc_lines if dl)[:200]
            if doc:
                parts.append(doc)
            break

    # Extract function/class signatures
    signatures: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("def ", "async def ", "class ")):
            sig = stripped.split(":", 1)[0].split("{", 1)[0].strip()
            signatures.append(sig)
        elif stripped.startswith(("export function", "export const", "export default")):
            sig = stripped[:100].split("{", 1)[0].strip()
            signatures.append(sig)

    if signatures:
        parts.append("Defines: " + ", ".join(signatures[:10]))

    if not parts:
        # Fallback: first non-empty, non-comment lines
        for line in lines[:10]:
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "//", "/*", "*")):
                parts.append(stripped[:100])
                break

    summary = f"{file_path}. " + ". ".join(parts)
    return summary[:max_len]


def scan_repository(root: Path) -> dict[str, Any]:
    """Scan a repository and return a NetworkX-compatible node-link dict.

    Returns the dict directly (no NetworkX dependency required at scan time
    for the init command — we build the structure manually).

    Each source file node includes:
    - description: rich summary (signatures, docstrings)
    - chunks: semantic code chunks for evidence-based reasoning
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    import_edges: list[tuple[str, str]] = []

    project_type = _detect_project_type(root)

    # ── Collect source files ────────────────────────────────────────
    source_exts = _PYTHON_EXTS | _JS_TS_EXTS

    for fpath in root.rglob("*"):
        if not fpath.is_file():
            continue
        if _should_skip(fpath):
            continue

        rel = fpath.relative_to(root)
        file_id = str(rel).replace("\\", "/")

        # Source files
        if fpath.suffix in source_exts:
            entity_type = "PythonModule" if fpath.suffix in _PYTHON_EXTS else "JSModule"

            # Read file content for chunking + description
            content = ""
            chunks: list[dict[str, str]] = []
            description = f"{entity_type}: {rel}"
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                # Generate rich description from content
                description = _summarize_file(content, str(rel))
                # Chunk file content for evidence-based reasoning
                chunks = _chunk_source_code(content)
            except Exception:
                pass

            node_data: dict[str, Any] = {
                "id": file_id,
                "label": fpath.stem,
                "type": entity_type,
                "description": description,
                "file_path": str(rel),  # T3: lazy load full file when needed
            }
            if chunks:
                node_data["chunks"] = chunks
                node_data["chunk_count"] = len(chunks)

            nodes.append(node_data)
            node_ids.add(file_id)

            # Directory node
            if len(rel.parts) > 1:
                dir_id = "/".join(rel.parts[:-1])
                if dir_id not in node_ids:
                    nodes.append(
                        {
                            "id": dir_id,
                            "label": rel.parts[-2],
                            "type": "Directory",
                            "description": f"Directory: {dir_id}",
                        }
                    )
                    node_ids.add(dir_id)
                edges.append(
                    {"source": dir_id, "target": file_id, "relationship": "CONTAINS"}
                )

            # Parse imports from already-read content
            try:
                if content and fpath.suffix in _PYTHON_EXTS:
                    for imp in _extract_python_imports(content):
                        target = imp.replace(".", "/") + ".py"
                        import_edges.append((file_id, target))
                elif content and fpath.suffix in _JS_TS_EXTS:
                    for imp in _extract_js_imports(content):
                        import_edges.append((file_id, imp))
            except Exception:
                pass

        # Config files
        elif fpath.name in _CONFIG_NAMES:
            if file_id not in node_ids:
                # Read config content for chunks too
                config_chunks: list[dict[str, str]] = []
                config_desc = f"Configuration: {fpath.name}"
                try:
                    config_content = fpath.read_text(encoding="utf-8", errors="ignore")
                    if config_content.strip():
                        # Store config as a single chunk (configs are usually small)
                        config_chunks = [{"text": config_content[:3000], "type": "config"}]
                        config_desc = f"Configuration: {fpath.name}. " + config_content[:200].replace("\n", " ")
                except Exception:
                    pass

                node_data = {
                    "id": file_id,
                    "label": fpath.stem,
                    "type": "Config",
                    "description": config_desc,
                }
                if config_chunks:
                    node_data["chunks"] = config_chunks
                nodes.append(node_data)
                node_ids.add(file_id)

        # Test files
        elif fpath.name.startswith("test_") or fpath.name.endswith("_test.py"):
            if file_id not in node_ids:
                # Read test content for chunks
                test_chunks: list[dict[str, str]] = []
                test_desc = f"Test: {rel}"
                try:
                    test_content = fpath.read_text(encoding="utf-8", errors="ignore")
                    test_desc = _summarize_file(test_content, str(rel))
                    test_chunks = _chunk_source_code(test_content)
                except Exception:
                    pass

                node_data = {
                    "id": file_id,
                    "label": fpath.stem,
                    "type": "TestModule",
                    "description": test_desc,
                }
                if test_chunks:
                    node_data["chunks"] = test_chunks
                nodes.append(node_data)
                node_ids.add(file_id)

    # ── Resolve import edges ────────────────────────────────────────
    for source, target in import_edges:
        # Try exact match and common variants
        candidates = [target]
        if not target.endswith((".py", ".js", ".ts", ".tsx", ".jsx")):
            candidates.extend([target + ext for ext in [".py", ".ts", ".js", "/index.ts", "/index.js"]])
        for candidate in candidates:
            if candidate in node_ids:
                edges.append(
                    {"source": source, "target": candidate, "relationship": "IMPORTS"}
                )
                break

    return {
        "directed": True,
        "multigraph": False,
        "graph": {"project_type": project_type},
        "nodes": nodes,
        "links": edges,
    }


# ──────────────────────────────────────────────────────────────────────
# File generators
# ──────────────────────────────────────────────────────────────────────


def _build_graqle_yaml(
    backend: str,
    model: str,
    api_key_ref: str,
    embedding_model: str | None = None,
    gov_config: dict[str, Any] | None = None,
) -> str:
    """Return the contents of graqle.yaml."""
    model_cfg: dict[str, Any] = {
        "backend": backend if backend != "custom" else "api",
        "model": model,
    }
    region = None
    # Bug 7 fix: Bedrock uses region, not api_key.
    # AWS authentication uses IAM credentials (via aws configure or
    # env vars AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY), not an API key.
    if backend == "bedrock":
        region = (
            os.environ.get("AWS_DEFAULT_REGION")
            or os.environ.get("AWS_REGION")
            or "us-east-1"  # Last resort — user can change in graqle.yaml
        )
        model_cfg["region"] = region
    elif backend == "ollama":
        # Ollama is local — no API key needed
        pass
    else:
        model_cfg["api_key"] = api_key_ref

    activation_cfg: dict[str, Any] = {
        "strategy": "chunk",
        "max_nodes": 20,
    }
    if embedding_model:
        activation_cfg["embedding_model"] = embedding_model

    # Build embeddings config section (v0.29.3+)
    # This is the single source of truth for embedding backend selection
    embeddings_cfg: dict[str, Any] = {}
    if embedding_model:
        if "titan" in (embedding_model or "").lower():
            embeddings_cfg["backend"] = "bedrock"
            embeddings_cfg["model"] = embedding_model
            if region:
                embeddings_cfg["region"] = region
        elif "sentence-transformers" in (embedding_model or ""):
            embeddings_cfg["backend"] = "local"
            embeddings_cfg["model"] = embedding_model
        else:
            embeddings_cfg["backend"] = "local"
            embeddings_cfg["model"] = embedding_model

    gov_yaml: dict[str, Any] = {"enabled": True}
    if gov_config:
        gov_yaml["enabled"] = gov_config.get("governance_enabled", True)
        if gov_config.get("shacl_validation") is False:
            gov_yaml["shacl_validation"] = False
        if gov_config.get("semantic_shacl"):
            gov_yaml["semantic_shacl"] = True

    cfg: dict[str, Any] = {
        "model": model_cfg,
        "graph": {
            "connector": "networkx",
        },
        "activation": activation_cfg,
        "orchestration": {
            "max_rounds": 3,
            "convergence_threshold": 0.92,
        },
        "cost": {
            "budget_per_query": 0.10,
            "dynamic_ceiling": True,
            "hard_ceiling_multiplier": 3.0,
        },
        "observer": {
            "enabled": True,
        },
        "governance": gov_yaml,
    }
    if embeddings_cfg:
        cfg["embeddings"] = embeddings_cfg
    return yaml.dump(cfg, default_flow_style=False, sort_keys=False)


# ──────────────────────────────────────────────────────────────────────
# IDE detection and config
# ──────────────────────────────────────────────────────────────────────

SUPPORTED_IDES = {
    "auto": "Auto-detect from project files",
    "claude": "Claude Code (.mcp.json + CLAUDE.md)",
    "cursor": "Cursor (.cursor/mcp.json + .cursorrules)",
    "vscode": "VS Code (.vscode/mcp.json + .github/copilot-instructions.md)",
    "windsurf": "Windsurf (.mcp.json + .windsurfrules)",
    "generic": "Any IDE / terminal (graq CLI only, no MCP)",
}


def _detect_ide(root: Path) -> str:
    """Auto-detect which IDE the project uses."""
    if (root / ".cursor").is_dir() or (root / ".cursorrules").exists():
        return "cursor"
    if (root / ".vscode").is_dir():
        return "vscode"
    if (root / ".windsurfrules").exists():
        return "windsurf"
    if (root / "CLAUDE.md").exists() or (root / ".mcp.json").exists():
        return "claude"
    # Default to claude for backward compat, but show as generic-compatible
    return "claude"


def _resolve_graq_command() -> str:
    """Find the full path to the ``graq`` executable.

    Uses :func:`shutil.which` so that on Windows the result is e.g.
    ``C:\\Users\\...\\Scripts\\graq.exe``.  Falls back to bare ``"graq"``
    with a console warning when the executable is not on PATH.
    """
    # Try standard PATH lookup
    full_path = shutil.which("graq")
    if full_path:
        return full_path

    # On Windows, try explicit .exe lookup
    full_path = shutil.which("graq.exe")
    if full_path:
        return full_path

    # Try common pip install paths
    bin_path = Path(sys.prefix) / "bin" / "graq"
    if bin_path.exists():
        return str(bin_path)
    scripts_path = Path(sys.prefix) / "Scripts" / "graq.exe"
    if scripts_path.exists():
        return str(scripts_path)

    # Ultimate fallback: derive from sys.executable (the Python running us)
    # pip always installs console_scripts next to the Python executable
    py_dir = Path(sys.executable).parent
    for candidate in [
        py_dir / "Scripts" / "graq.exe",  # Windows pip
        py_dir / "Scripts" / "graq",      # Windows
        py_dir / "graq",                  # Unix venv
        py_dir / "bin" / "graq",          # Unix system
    ]:
        if candidate.exists():
            return str(candidate)

    # On Windows, check common pip Scripts dirs and suggest PATH fix
    if sys.platform == "win32":
        scripts_dirs = [
            Path(sys.prefix) / "Scripts",
            Path(sys.executable).parent / "Scripts",
            Path.home() / "AppData" / "Roaming" / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts",
            Path.home() / "AppData" / "Local" / "Programs" / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts",
        ]
        for sd in scripts_dirs:
            graq_exe = sd / "graq.exe"
            if graq_exe.exists():
                console.print(
                    f"  [yellow]WARNING:[/yellow] Found 'graq.exe' at [bold]{graq_exe}[/bold] "
                    f"but it's not on PATH.\n"
                    f"  [dim]Fix: Add this directory to your PATH:[/dim]\n"
                    f"    [bold cyan]setx PATH \"%PATH%;{sd}\"[/bold cyan]\n"
                    f"  [dim]Or in PowerShell:[/dim]\n"
                    f"    [bold cyan]$env:PATH += \";{sd}\"[/bold cyan]\n"
                    f"  [dim]Then restart your terminal.[/dim]"
                )
                return str(graq_exe)

    console.print(
        "  [yellow]WARNING:[/yellow] Could not find 'graq' executable. "
        "MCP server may fail to start.\n"
        "  [dim]Fix: ensure 'graq' is on your PATH, or reinstall: pip install graqle[/dim]"
    )
    return "graq"


def _build_mcp_json(ide: str = "claude") -> dict[str, Any]:
    """Return the MCP server config structure for the target IDE."""
    mcp_entry = {
        "type": "stdio",
        "command": _resolve_graq_command(),
        "args": ["mcp", "serve", "--config", "graqle.yaml"],
    }
    return {
        "mcpServers": {
            "graqle": mcp_entry,
        }
    }


def _get_mcp_path(root: Path, ide: str) -> Path:
    """Return the MCP config file path for the target IDE."""
    if ide == "cursor":
        return root / ".cursor" / "mcp.json"
    elif ide == "vscode":
        return root / ".vscode" / "mcp.json"
    else:
        # claude, windsurf, generic all use root .mcp.json
        return root / ".mcp.json"


def _get_instructions_path(root: Path, ide: str) -> Path:
    """Return the AI instructions file path for the target IDE."""
    if ide == "cursor":
        return root / ".cursorrules"
    elif ide == "vscode":
        return root / ".github" / "copilot-instructions.md"
    elif ide == "windsurf":
        return root / ".windsurfrules"
    else:
        # claude or generic
        return root / "CLAUDE.md"


def _get_instructions_marker(ide: str) -> str:
    """Marker to detect if instructions already exist."""
    return "# GraQle — Dev Intelligence Layer"


def _build_gcc_main_md(root: Path) -> str:
    """Auto-generate .gcc/main.md from project README if it exists."""
    readme_path = root / "README.md"
    header = "# Project Roadmap\n\n"
    if readme_path.exists():
        try:
            content = readme_path.read_text(errors="ignore")
            # Extract first 30 lines as summary
            lines = content.splitlines()[:30]
            summary = "\n".join(lines)
            return header + f"## From README\n\n{summary}\n\n## Goals\n\n- [ ] Define project goals here\n"
        except Exception:
            pass
    return header + "## Goals\n\n- [ ] Define project goals here\n"


def _build_gcc_registry_md() -> str:
    """Return initial .gcc/registry.md content."""
    return (
        "# Branch Registry\n\n"
        "| Branch | Status | Owner | Last Active |\n"
        "|--------|--------|-------|-------------|\n"
        "| main | ACTIVE | — | — |\n"
    )


def _build_gcc_config_yaml() -> str:
    """Return .gcc/config.yaml content."""
    cfg = {
        "project": "auto-detected",
        "token_budget": {
            "session_start": 800,
            "max_gcc_overhead_pct": 5,
        },
        "auto_commit_interval_min": 30,
    }
    return yaml.dump(cfg, default_flow_style=False, sort_keys=False)


def _build_gcc_metadata_yaml() -> str:
    """Return initial branch metadata.yaml."""
    cfg = {
        "branch": "main",
        "parent": None,
        "status": "ACTIVE",
        "file_tree": [],
        "open_questions": [],
    }
    return yaml.dump(cfg, default_flow_style=False, sort_keys=False)


# ──────────────────────────────────────────────────────────────────────
# /graq skill — smart query router for Claude Code
# ──────────────────────────────────────────────────────────────────────

KOGNI_SKILL_CONTENT = r"""Smart query router for project knowledge. Classifies the user's question and picks the cheapest approach that gives a correct answer.

IMPORTANT: When the user explicitly says "use graqle", "ask graqle", "graqle reason", or "use the knowledge graph" — skip classification and go directly to the appropriate GraQle MCP tool. Do NOT fall back to grep/read when the user explicitly wants GraQle.

## Decision Tree — Execute in order, stop at first match

### Step 0: Check for explicit GraQle request

If the user said "use graqle" or similar, go directly to Step 2 and pick the MCP tool that matches:
- Impact/dependency questions -> `graq_impact`
- "What breaks / what depends" -> `graq_impact`
- "Why / how / explain" -> `graq_reason`
- Safety / preflight checks -> `graq_preflight`
- Past mistakes / lessons -> `graq_lessons`
- "Tell me about X" / context -> `graq_context`
- "Remember / teach" -> `graq_learn`
- Graph stats -> `graq_inspect`
- Everything else -> `graq_reason`

### Step 1: Classify the query

Read the user's question (passed as $ARGUMENTS) and classify it into ONE of these categories:

| Category | Pattern | Examples |
|----------|---------|----------|
| **LOOKUP** | Single fact, named entity, "which X does Y" | "Which Lambda creates manifest?", "What's the Neo4j URI?", "What env vars does L03 need?" |
| **CROSS-CUT** | Spans 3+ components, services, or files | "What services depend on Neo4j?", "Which Lambdas use shared/tamr_retrieval.py?", "What modules does L06 import?" |
| **IMPACT** | "What happens if", "what breaks", change analysis | "What breaks if I remove trace_scoring.py?", "Impact of changing Neo4j schema?" |
| **REASONING** | Why/how questions, architectural, multi-hop | "Why does TRACE score drop for single-doc queries?", "How does the document pipeline work end-to-end?" |
| **PREFLIGHT** | About to change code, need safety check | "What should I check before modifying L03?", "Any gotchas for CORS changes?" |
| **LESSONS** | Past mistakes, failure patterns | "What went wrong with document naming?", "Common deployment failures?" |

### Step 2: Route to the right approach

#### LOOKUP -> Direct grep/read (cost: 100-500 tokens)
```
1. Grep for the key term in .gcc/project-kg.md (or graqle.json)
2. If found -> return the relevant rows/section. DONE.
3. If not found -> grep tasks/lessons-distilled.md
4. If still not found -> escalate to CROSS-CUT
```
**Tools:** Grep, Read (targeted lines only)

#### CROSS-CUT -> Targeted read or graq_context (cost: 300-800 tokens)
```
1. Read only the relevant section(s) of .gcc/project-kg.md
2. If project-kg.md doesn't have the relationships -> call graq_context
3. Synthesize answer. DONE.
```

#### IMPACT -> graq_impact MCP tool (cost: ~800-1500 tokens)
```
1. Call graq_impact with the component name
2. Present the impact trace to the user
```
**This is where GraQle earns its keep** — traversing dependency chains automatically.

#### REASONING -> graq_reason MCP tool (cost: ~1500-3000 tokens)
```
1. Call graq_reason with the question
2. If confidence < 0.5, supplement with targeted file reads
3. Present synthesized answer
```
**This is GraQle's sweet spot** — multi-hop reasoning across nodes.

#### PREFLIGHT -> graq_preflight MCP tool (cost: ~500-1000 tokens)
```
1. Call graq_preflight with the action and files
2. Present warnings, lessons, and safety boundaries
```

#### LESSONS -> graq_lessons MCP tool (cost: ~400-800 tokens)
```
1. Call graq_lessons with the operation
2. Present matched lessons with severity
```

### Step 3: Report the routing decision

Always start your response with a one-line routing tag so the user sees the cost/benefit:

```
[GRAQLE: {CATEGORY} -> {approach} | ~{estimated_tokens} tokens]
```

Examples:
- `[GRAQLE: LOOKUP -> grep project-kg.md | ~200 tokens]`
- `[GRAQLE: IMPACT -> graq_impact | ~1200 tokens]`
- `[GRAQLE: REASONING -> graq_reason (3 rounds) | ~2500 tokens]`

### Step 4: Answer the question

After routing, answer the user's question using the chosen approach. Be concise. Cite the source (file:line or GraQle node IDs).

## Token Budget Summary

| Approach | Typical cost | When to use |
|----------|-------------|-------------|
| Grep project-kg.md | 100-300 tokens | Single fact, named entity |
| Read section of KG | 300-800 tokens | Cross-referencing 2-3 tables |
| graq_lessons | 400-800 tokens | Past mistake patterns |
| graq_preflight | 500-1000 tokens | Pre-change safety check |
| graq_impact | 800-1500 tokens | Change impact analysis |
| graq_reason | 1500-3000 tokens | Multi-hop reasoning, "why" questions |

## Rules

1. **User says "use graqle" = use GraQle.** No second-guessing. Call the MCP tool.
2. **Cheapest first (when auto-routing).** Try grep before MCP tools.
3. **Always show the routing tag.** Transparency builds trust.
4. **Escalate, don't guess.** If grep returns nothing, escalate to the next tier — don't fabricate.
5. **Cache awareness.** If project-kg.md was already read this session, reuse from memory — don't re-read.
""".strip()


# ──────────────────────────────────────────────────────────────────────
# Backend verification — test that the API key works BEFORE proceeding
# ──────────────────────────────────────────────────────────────────────


def _resolve_api_key(api_key_ref: str) -> str | None:
    """Resolve a key reference like ${ANTHROPIC_API_KEY} to the actual value."""
    if api_key_ref.startswith("${") and api_key_ref.endswith("}"):
        env_var = api_key_ref[2:-1]
        return os.environ.get(env_var)
    return api_key_ref  # raw key


def _verify_backend(
    backend: str,
    model: str,
    api_key_ref: str,
    no_interactive: bool,
) -> None:
    """Verify the backend actually works by making a minimal API call.

    This is the FIRST thing a new user sees after choosing their backend.
    If it fails, they get clear, actionable instructions to fix it.
    """
    resolved_key = _resolve_api_key(api_key_ref)

    # ── Step 1: Check if the key is even available ──────────────────
    if resolved_key is None:
        env_var = api_key_ref[2:-1] if api_key_ref.startswith("${") else "API_KEY"
        console.print(
            f"  [yellow]WARNING:[/yellow] Environment variable "
            f"[bold]{env_var}[/bold] is not set.\n"
            f"  The graph and MCP tools will be created, but reasoning\n"
            f"  queries (graq run, graq_reason) will fail until you set it.\n"
        )
        console.print(
            f"  [dim]Fix: export {env_var}=your-key-here[/dim]\n"
            f"  [dim]Then restart Claude Code to pick up the change.[/dim]\n"
        )
        return

    # ── Step 2: Try a minimal API call ──────────────────────────────
    try:
        if backend == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=resolved_key)
            resp = client.messages.create(
                model=model,
                max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )
            console.print(
                f"  [green]Connected to Anthropic ({model})[/green]\n"
            )

        elif backend == "openai":
            import openai
            client = openai.OpenAI(api_key=resolved_key)
            client.chat.completions.create(
                model=model,
                max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )
            console.print(
                f"  [green]Connected to OpenAI ({model})[/green]\n"
            )

        elif backend == "bedrock":
            import boto3
            region = (
                os.environ.get("AWS_DEFAULT_REGION")
                or os.environ.get("AWS_REGION")
                or "us-east-1"
            )
            client = boto3.client("bedrock-runtime", region_name=region)
            import json as _json
            client.invoke_model(
                modelId=model,
                body=_json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "hi"}],
                }),
                contentType="application/json",
            )
            console.print(
                f"  [green]Connected to AWS Bedrock ({model} in {region})[/green]\n"
            )

        elif backend == "custom":
            console.print(
                "  [dim]Custom backend — skipping verification.[/dim]\n"
                "  [dim]Test manually: graq run \"hello\"[/dim]\n"
            )

    except ImportError as e:
        pkg = str(e).split("'")[-2] if "'" in str(e) else "required package"
        console.print(
            f"  [yellow]WARNING:[/yellow] Missing package: {pkg}\n"
            f"  [dim]Fix: pip install {pkg}[/dim]\n"
            f"  The graph will be created, but reasoning needs this package.\n"
        )

    except Exception as e:
        err_msg = str(e)[:200]
        console.print(
            f"  [yellow]WARNING:[/yellow] Backend connection failed.\n"
            f"  [dim]{err_msg}[/dim]\n"
        )

        # Provide backend-specific fix instructions
        if backend == "anthropic":
            console.print(
                "  [bold]To fix:[/bold]\n"
                "  1. Check your API key at https://console.anthropic.com/\n"
                "  2. export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  3. Re-run: graq init\n"
            )
        elif backend == "openai":
            console.print(
                "  [bold]To fix:[/bold]\n"
                "  1. Check your API key at https://platform.openai.com/api-keys\n"
                "  2. export OPENAI_API_KEY=sk-...\n"
                "  3. Re-run: graq init\n"
            )
        elif backend == "bedrock":
            # Bug 7: Check if this is a cross-region inference profile issue
            err_lower = err_msg.lower()
            if "validationexception" in err_lower or "on-demand" in err_lower:
                console.print(
                    "  [bold]To fix (cross-region inference profile):[/bold]\n"
                    f"  The model '{model}' may not support on-demand throughput.\n"
                    "  Try using a cross-region inference profile ID instead:\n"
                    f"  [cyan]eu.{model}[/cyan] (EU region) or [cyan]us.{model}[/cyan] (US region)\n\n"
                    "  Update graqle.yaml:\n"
                    f"    model: eu.{model}\n\n"
                    "  Or re-run: graq init\n"
                )
            else:
                console.print(
                    "  [bold]To fix:[/bold]\n"
                    "  1. Ensure AWS credentials are configured (aws configure)\n"
                    "  2. Ensure the model is enabled in your AWS Bedrock console\n"
                    "  3. Set the region: export AWS_DEFAULT_REGION=eu-central-1\n"
                    "  4. For cross-region models, use inference profile IDs:\n"
                    f"     eu.{model} or us.{model}\n"
                    "  5. Re-run: graq init\n"
                )

        console.print(
            "  [dim]Continuing setup — graph and MCP tools will still be created.\n"
            "  Reasoning queries will fail until the backend is fixed.[/dim]\n"
        )


# ──────────────────────────────────────────────────────────────────────
# Interactive prompts
# ──────────────────────────────────────────────────────────────────────


def _prompt_backend() -> str:
    """Ask the user to pick a backend, with auto-detection of what's available."""
    import importlib

    # Auto-detect which backends are ready (package installed + API key set)
    detection = {
        "anthropic": {"pkg": "anthropic", "env": "ANTHROPIC_API_KEY"},
        "openai": {"pkg": "openai", "env": "OPENAI_API_KEY"},
        "groq": {"pkg": "httpx", "env": "GROQ_API_KEY"},
        "gemini": {"pkg": "httpx", "env": "GEMINI_API_KEY"},
        "ollama": {"pkg": "httpx", "env": None},
        "bedrock": {"pkg": "boto3", "env": "AWS_ACCESS_KEY_ID"},
        "deepseek": {"pkg": "httpx", "env": "DEEPSEEK_API_KEY"},
        "together": {"pkg": "httpx", "env": "TOGETHER_API_KEY"},
        "mistral": {"pkg": "httpx", "env": "MISTRAL_API_KEY"},
        "openrouter": {"pkg": "httpx", "env": "OPENROUTER_API_KEY"},
        "fireworks": {"pkg": "httpx", "env": "FIREWORKS_API_KEY"},
        "cohere": {"pkg": "httpx", "env": "COHERE_API_KEY"},
        "custom": {"pkg": None, "env": None},
    }

    table = Table(title="Available Backends", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Backend", style="bold")
    table.add_column("Description")
    table.add_column("Status", style="dim")

    backend_keys = list(BACKENDS.keys())
    recommended_idx = 1  # default

    for i, key in enumerate(backend_keys, 1):
        det = detection.get(key, {})
        pkg = det.get("pkg")
        env = det.get("env")

        # Check package
        pkg_ok = True
        if pkg:
            try:
                importlib.import_module(pkg)
            except ImportError:
                pkg_ok = False

        # Check env var (for Bedrock, also check ~/.aws/credentials)
        env_ok = True
        if env:
            env_ok = bool(os.environ.get(env))
            if not env_ok and key == "bedrock":
                try:
                    import boto3
                    session = boto3.Session()
                    creds = session.get_credentials()
                    env_ok = creds is not None
                except Exception:
                    pass

        # Build status string
        if pkg_ok and env_ok and env:
            status = "[green]ready[/green]"
            if recommended_idx == 1:
                recommended_idx = i  # first ready backend
        elif pkg_ok and not env:
            status = "[green]installed[/green]"
        elif pkg_ok and not env_ok:
            status = f"[yellow]need {env}[/yellow]"
        elif not pkg_ok:
            status = f"[dim]pip install {pkg}[/dim]"
        else:
            status = ""

        table.add_row(str(i), key, BACKENDS[key]["name"], status)

    console.print(table)
    console.print("[dim]Backends marked 'ready' have package + API key detected.[/dim]\n")
    choice = IntPrompt.ask(
        "Choose a backend",
        default=recommended_idx,
        choices=[str(i) for i in range(1, len(backend_keys) + 1)],
    )
    selected_key = backend_keys[choice - 1]

    # Check if required package is missing and offer to install
    det = detection.get(selected_key, {})
    pkg = det.get("pkg")
    if pkg:
        try:
            importlib.import_module(pkg)
        except ImportError:
            console.print(
                f"\n  [yellow]The '{selected_key}' backend requires '{pkg}' package.[/yellow]"
            )
            install = Prompt.ask(
                f"  Install {pkg} now?",
                choices=["y", "n"],
                default="y",
            )
            if install == "y":
                import subprocess
                pip_pkg = pkg
                # Map import names to pip package names
                pip_map = {"anthropic": "anthropic", "openai": "openai", "boto3": "boto3"}
                pip_pkg = pip_map.get(pkg, pkg)
                console.print(f"  [dim]Installing {pip_pkg}...[/dim]")
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", pip_pkg],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    console.print(f"  [green]{pip_pkg} installed successfully![/green]\n")
                else:
                    console.print(
                        f"  [red]Installation failed.[/red] Install manually: pip install {pip_pkg}\n"
                    )
            else:
                console.print(f"  [dim]Skipped. Install later: pip install {pkg}[/dim]\n")

    return selected_key


def _prompt_model(backend: str) -> str:
    """Ask the user to pick a model for the chosen backend."""
    models = BACKENDS[backend]["models"]
    if not models:
        return Prompt.ask("Enter model name or endpoint URL", default="gpt-4o-mini")

    table = Table(title=f"Models for {BACKENDS[backend]['name']}", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="bold")
    table.add_column("Description")
    table.add_column("Default", style="dim")

    for i, (model_id, desc, is_default) in enumerate(models, 1):
        table.add_row(str(i), model_id, desc, "yes" if is_default else "")

    console.print(table)

    default_idx = next(
        (i for i, (_, _, d) in enumerate(models, 1) if d), 1
    )
    choice = IntPrompt.ask(
        "Choose a model",
        default=default_idx,
        choices=[str(i) for i in range(1, len(models) + 1)],
    )
    return models[choice - 1][0]


def _prompt_api_key(backend: str) -> str:
    """Ask the user how to provide their API key. Returns a ${VAR} reference or raw key."""
    env_var = BACKENDS[backend].get("api_key_env")

    # Ollama and other local backends don't need an API key
    if not env_var:
        console.print("[green]No API key needed — this backend runs locally.[/green]")
        return ""

    existing = os.environ.get(env_var)

    if existing:
        console.print(f"[green]Found ${env_var} in environment.[/green]")
        use_existing = Prompt.ask(
            f"Use ${{{env_var}}} from environment?",
            choices=["y", "n"],
            default="y",
        )
        if use_existing == "y":
            return f"${{{env_var}}}"

    console.print(f"\nHow should {BRAND_NAME} access your API key?")
    console.print(f"  [bold]1.[/bold] Environment variable ${{{env_var}}} (recommended)")
    console.print("  [bold]2.[/bold] Enter the key now (stored in graqle.yaml)")

    choice = IntPrompt.ask("Choice", default=1, choices=["1", "2"])

    if choice == 1:
        console.print(
            f"\n[dim]Set the variable before running graq:[/dim]"
            f"\n  export {env_var}=your-key-here\n"
        )
        return f"${{{env_var}}}"
    else:
        key = Prompt.ask("Enter your API key", password=True)
        return key


# ──────────────────────────────────────────────────────────────────────
# Smart project pre-scan + model recommendations
# ──────────────────────────────────────────────────────────────────────


def _quick_project_scan(root: Path) -> dict[str, Any]:
    """Fast pre-scan of the project to determine size and complexity.

    Returns a profile dict used to recommend the best model/embedding combo.
    """
    import fnmatch

    profile: dict[str, Any] = {
        "file_count": 0,
        "py_files": 0,
        "ts_files": 0,
        "js_files": 0,
        "go_files": 0,
        "java_files": 0,
        "rust_files": 0,
        "doc_files": 0,
        "has_tests": False,
        "has_docker": False,
        "has_ci": False,
        "estimated_nodes": 0,
        "size_category": "small",  # small/medium/large/enterprise
        "primary_language": "unknown",
        "frameworks": [],
    }

    exclude = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".venv", "venv", "env"}
    code_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".rb", ".php", ".cs", ".cpp", ".c", ".swift", ".kt"}
    doc_extensions = {".md", ".rst", ".txt", ".pdf", ".docx"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude and not d.startswith(".")]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in code_extensions:
                profile["file_count"] += 1
                if ext == ".py":
                    profile["py_files"] += 1
                elif ext in (".ts", ".tsx"):
                    profile["ts_files"] += 1
                elif ext in (".js", ".jsx"):
                    profile["js_files"] += 1
                elif ext == ".go":
                    profile["go_files"] += 1
                elif ext == ".java":
                    profile["java_files"] += 1
                elif ext == ".rs":
                    profile["rust_files"] += 1
            elif ext in doc_extensions:
                profile["doc_files"] += 1
            if f in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml"):
                profile["has_docker"] = True
            if f in (".github", "Jenkinsfile", ".gitlab-ci.yml", ".circleci"):
                profile["has_ci"] = True
            if "test" in f.lower() or "spec" in f.lower():
                profile["has_tests"] = True

    # Detect CI from directories
    if (root / ".github" / "workflows").exists():
        profile["has_ci"] = True

    # Detect frameworks
    if (root / "package.json").exists():
        profile["frameworks"].append("Node.js")
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8", errors="ignore"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps:
                profile["frameworks"].append("Next.js")
            if "react" in deps:
                profile["frameworks"].append("React")
            if "vue" in deps:
                profile["frameworks"].append("Vue")
            if "express" in deps:
                profile["frameworks"].append("Express")
        except Exception:
            pass
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        profile["frameworks"].append("Python")
    if (root / "go.mod").exists():
        profile["frameworks"].append("Go")
    if (root / "Cargo.toml").exists():
        profile["frameworks"].append("Rust")

    # Determine primary language
    lang_counts = {
        "Python": profile["py_files"],
        "TypeScript": profile["ts_files"],
        "JavaScript": profile["js_files"],
        "Go": profile["go_files"],
        "Java": profile["java_files"],
        "Rust": profile["rust_files"],
    }
    if any(lang_counts.values()):
        profile["primary_language"] = max(lang_counts, key=lang_counts.get)

    # Estimate nodes (roughly 3-8 nodes per code file)
    profile["estimated_nodes"] = profile["file_count"] * 5

    # Size category
    fc = profile["file_count"]
    if fc < 50:
        profile["size_category"] = "small"
    elif fc < 200:
        profile["size_category"] = "medium"
    elif fc < 1000:
        profile["size_category"] = "large"
    else:
        profile["size_category"] = "enterprise"

    return profile


def _show_project_profile(profile: dict[str, Any]) -> None:
    """Display the quick project profile to the user."""
    table = Table(title="Project Profile (Quick Scan)", show_header=False, border_style="cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Code files", str(profile["file_count"]))
    table.add_row("Primary language", profile["primary_language"])
    if profile["frameworks"]:
        table.add_row("Frameworks", ", ".join(profile["frameworks"]))
    table.add_row("Estimated KG nodes", f"~{profile['estimated_nodes']:,}")
    table.add_row("Size category", profile["size_category"].upper())
    table.add_row("Documentation files", str(profile["doc_files"]))
    table.add_row("Has tests", "[green]yes[/green]" if profile["has_tests"] else "[yellow]no[/yellow]")
    table.add_row("Has Docker", "[green]yes[/green]" if profile["has_docker"] else "[dim]no[/dim]")
    table.add_row("Has CI/CD", "[green]yes[/green]" if profile["has_ci"] else "[dim]no[/dim]")

    console.print(table)


def _recommend_model(backend: str, profile: dict[str, Any]) -> str | None:
    """Recommend the best model for this backend based on project profile.

    Returns the recommended model ID, or None if no strong recommendation.
    """
    size = profile["size_category"]
    models = BACKENDS[backend]["models"]
    if not models:
        return None

    # For large/enterprise projects, recommend more capable models
    if size in ("large", "enterprise"):
        # Find the most capable (usually non-default, more expensive)
        for model_id, desc, _ in models:
            if any(kw in desc.lower() for kw in ("capable", "opus", "large", "pro", "4o ", "command-r+")):
                return model_id

    # For small/medium, default is usually right
    for model_id, _, is_default in models:
        if is_default:
            return model_id

    return models[0][0]


def _prompt_model_with_recommendation(backend: str, profile: dict[str, Any]) -> str:
    """Enhanced model prompt with project-aware recommendations and pros/cons."""
    models = BACKENDS[backend]["models"]
    if not models:
        return Prompt.ask("Enter model name or endpoint URL", default="gpt-4o-mini")

    recommended = _recommend_model(backend, profile)
    size = profile["size_category"]

    table = Table(
        title=f"Models for {BACKENDS[backend]['name']}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="bold")
    table.add_column("Description")
    table.add_column("Fit", style="dim")

    for i, (model_id, desc, is_default) in enumerate(models, 1):
        # Determine fit for this project
        if model_id == recommended:
            fit = "[green]RECOMMENDED[/green]"
        elif "cheap" in desc.lower() or "fast" in desc.lower() or "mini" in desc.lower() or "lite" in desc.lower():
            fit = "[green]good[/green]" if size in ("small", "medium") else "[yellow]may be limited[/yellow]"
        elif "capable" in desc.lower() or "opus" in desc.lower() or "large" in desc.lower() or "pro" in desc.lower():
            fit = "[green]good[/green]" if size in ("large", "enterprise") else "[dim]overkill[/dim]"
        else:
            fit = "[green]good[/green]"

        table.add_row(str(i), model_id, desc, fit)

    console.print(table)

    # Show recommendation reasoning
    if recommended:
        rec_desc = next((d for m, d, _ in models if m == recommended), "")
        if size in ("large", "enterprise"):
            console.print(
                f"\n  [bold cyan]Recommendation:[/bold cyan] Your project has {profile['file_count']} code files "
                f"(~{profile['estimated_nodes']:,} estimated nodes).\n"
                f"  A more capable model produces [bold]better ontologies[/bold] and "
                f"[bold]higher-quality reasoning[/bold] for complex codebases.\n"
            )
        elif size == "small":
            console.print(
                f"\n  [bold cyan]Recommendation:[/bold cyan] Your project is small ({profile['file_count']} files). "
                f"A fast model keeps costs low while still producing accurate results.\n"
            )
        else:
            console.print(
                f"\n  [bold cyan]Recommendation:[/bold cyan] Good balance of quality and cost for "
                f"a {profile['file_count']}-file codebase.\n"
            )

    rec_idx = next((i for i, (m, _, _) in enumerate(models, 1) if m == recommended), 1)
    choice = IntPrompt.ask(
        "Choose a model",
        default=rec_idx,
        choices=[str(i) for i in range(1, len(models) + 1)],
    )
    return models[choice - 1][0]


# ── Embedding model selection ─────────────────────────────────────────

EMBEDDING_OPTIONS = [
    {
        "id": "sentence-transformers/all-MiniLM-L6-v2",
        "name": "MiniLM L6 (Local)",
        "dims": 384,
        "pros": "Free, runs locally, no API key needed, fast",
        "cons": "Lower quality for complex semantic matching",
        "best_for": "Small-medium projects, offline use, cost-sensitive",
        "requires": "pip install sentence-transformers",
    },
    {
        "id": "sentence-transformers/all-mpnet-base-v2",
        "name": "MPNet Base (Local)",
        "dims": 768,
        "pros": "Best local model quality, good semantic understanding",
        "cons": "Slower than MiniLM, larger model download (~420MB)",
        "best_for": "Medium-large projects wanting best local quality",
        "requires": "pip install sentence-transformers",
    },
    {
        "id": "amazon.titan-embed-text-v2:0",
        "name": "Amazon Titan V2 (AWS Bedrock)",
        "dims": 1024,
        "pros": "Highest quality, production-grade, 1024 dimensions",
        "cons": "Requires AWS account + Bedrock access, ~$0.0001/query",
        "best_for": "Large/enterprise projects, production deployments",
        "requires": "AWS credentials + Bedrock model access enabled",
    },
]


def _prompt_embedding_model(profile: dict[str, Any]) -> str:
    """Ask the user to choose an embedding model with pros/cons."""
    size = profile["size_category"]

    console.print(Panel.fit(
        "[bold cyan]Embedding Model[/bold cyan]\n\n"
        "Embeddings are the foundation of your knowledge graph's intelligence.\n"
        "They determine how well GraQle finds relevant code when you ask questions.\n\n"
        "[bold]Why this matters for AI coding tools:[/bold]\n"
        "  Your AI assistant (Claude, Cursor, Copilot) reads thousands of tokens.\n"
        "  GraQle reduces that to ~500 tokens of [bold]precisely relevant[/bold] context.\n"
        "  Better embeddings = better relevance = better AI answers = less cost.\n\n"
        "[bold]Higher-quality embeddings pay for themselves:[/bold]\n"
        "  - Activate the [bold]right[/bold] 20 nodes instead of [dim]random[/dim] 20 nodes\n"
        "  - Reduce reasoning token waste by 30-50% (fewer irrelevant nodes)\n"
        "  - Catch impact paths that low-dim embeddings miss entirely\n\n"
        "[dim]This affects: query relevance, skill routing, chunk scoring, impact analysis[/dim]",
        border_style="cyan",
        title="Context Intelligence",
    ))

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="bold", min_width=20)
    table.add_column("Dims", style="dim", width=5)
    table.add_column("Pros", style="green")
    table.add_column("Cons", style="yellow")
    table.add_column("Fit", style="dim")

    # Check availability
    has_st = False
    try:
        import importlib
        importlib.import_module("sentence_transformers")
        has_st = True
    except ImportError:
        pass

    has_bedrock = False
    try:
        import boto3
        session = boto3.Session()
        has_bedrock = session.get_credentials() is not None
    except Exception:
        pass

    # Determine recommended
    if size in ("large", "enterprise") and has_bedrock:
        recommended_idx = 3  # Titan V2
    elif size in ("medium", "large") and has_st:
        recommended_idx = 2  # MPNet
    else:
        recommended_idx = 1  # MiniLM

    for i, opt in enumerate(EMBEDDING_OPTIONS, 1):
        available = True
        if "MiniLM" in opt["name"] or "MPNet" in opt["name"]:
            available = has_st
        elif "Titan" in opt["name"]:
            available = has_bedrock

        fit = ""
        if i == recommended_idx:
            fit = "[green]RECOMMENDED[/green]"
        elif not available:
            fit = f"[red]needs: {opt['requires']}[/red]"
        elif size in ("large", "enterprise") and opt["dims"] >= 768:
            fit = "[green]good[/green]"
        elif size in ("small", "medium") and "Local" in opt["name"]:
            fit = "[green]good[/green]"
        else:
            fit = "[dim]ok[/dim]"

        table.add_row(
            str(i),
            opt["name"],
            str(opt["dims"]),
            opt["pros"],
            opt["cons"],
            fit,
        )

    console.print(table)

    rec = EMBEDDING_OPTIONS[recommended_idx - 1]
    console.print(
        f"\n  [bold cyan]Recommendation:[/bold cyan] [bold]{rec['name']}[/bold] — {rec['best_for']}\n"
    )

    choice = IntPrompt.ask(
        "Choose an embedding model",
        default=recommended_idx,
        choices=["1", "2", "3"],
    )

    selected = EMBEDDING_OPTIONS[choice - 1]

    # Check if required dependencies are installed, offer to install
    if "MiniLM" in selected["name"] or "MPNet" in selected["name"]:
        if not has_st:
            console.print(
                f"\n  [yellow]'{selected['name']}' requires sentence-transformers.[/yellow]\n"
                f"  Without it, GraQle falls back to a basic hash-based embedding\n"
                f"  (much lower quality for semantic search and skill matching).\n"
            )
            install = Prompt.ask(
                "  Install sentence-transformers now?",
                choices=["y", "n"],
                default="y",
            )
            if install == "y":
                console.print("  [dim]Installing sentence-transformers (this may take a minute)...[/dim]")
                import subprocess
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "sentence-transformers"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    console.print("  [green]sentence-transformers installed successfully![/green]\n")
                else:
                    console.print(
                        f"  [red]Installation failed.[/red] You can install manually:\n"
                        f"  [dim]pip install sentence-transformers[/dim]\n"
                    )
            else:
                console.print(
                    "  [dim]Skipped. Install later: pip install sentence-transformers[/dim]\n"
                    "  [dim]Without it, embedding quality will be reduced.[/dim]\n"
                )
    elif "Titan" in selected["name"]:
        if not has_bedrock:
            console.print(
                f"\n  [yellow]'{selected['name']}' requires AWS Bedrock access.[/yellow]\n"
                f"  You need:\n"
                f"  1. [bold]boto3[/bold] installed: pip install boto3\n"
                f"  2. [bold]AWS credentials[/bold] configured: aws configure\n"
                f"  3. [bold]Bedrock model access[/bold] enabled in AWS console\n"
            )
            try:
                import importlib
                importlib.import_module("boto3")
            except ImportError:
                install_boto = Prompt.ask(
                    "  Install boto3 now?",
                    choices=["y", "n"],
                    default="y",
                )
                if install_boto == "y":
                    console.print("  [dim]Installing boto3...[/dim]")
                    import subprocess
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "boto3"],
                        capture_output=True, text=True,
                    )
                    if result.returncode == 0:
                        console.print("  [green]boto3 installed successfully![/green]\n")
                    else:
                        console.print(f"  [red]Installation failed.[/red] Install manually: pip install boto3\n")

    return selected["id"]


# ── Governance / ontology configuration ───────────────────────────────

def _prompt_governance(profile: dict[str, Any]) -> dict[str, Any]:
    """Ask about governance, ontology, and SHACL constraint preferences."""
    console.print(Panel.fit(
        "[bold cyan]Governance & Ontology[/bold cyan]\n\n"
        "GraQle builds a domain-specific ontology for your codebase and\n"
        "validates it with SHACL-like constraints. This ensures your\n"
        "knowledge graph stays consistent and trustworthy.\n\n"
        "[dim]Features: DRACE scoring, audit trails, evidence chains,\n"
        "SHACL constraint validation, scope gates[/dim]",
        border_style="cyan",
        title="Quality Assurance",
    ))

    gov_config: dict[str, Any] = {
        "governance_enabled": True,
        "shacl_validation": True,
        "ontology_mode": "auto",
        "scan_docs": True,
    }

    # Ontology mode
    console.print("\n[bold]Ontology Generation[/bold]")
    console.print("  [bold]1.[/bold] Auto (recommended) — LLM generates domain-specific ontology")
    console.print("  [bold]2.[/bold] Heuristic — Pattern-based, no LLM needed (faster but generic)")
    console.print("  [bold]3.[/bold] Custom — Provide your own ontology YAML file")

    ont_choice = IntPrompt.ask(
        "Ontology mode",
        default=1,
        choices=["1", "2", "3"],
    )
    gov_config["ontology_mode"] = ["auto", "heuristic", "custom"][ont_choice - 1]

    # SHACL constraints
    console.print("\n[bold]SHACL Constraint Validation[/bold]")
    console.print(
        "  SHACL gates validate that nodes and edges conform to your ontology.\n"
        "  This catches malformed data during scan and prevents graph corruption.\n"
    )
    console.print("  [bold]1.[/bold] Enabled (recommended) — Validate all nodes/edges against ontology")
    console.print("  [bold]2.[/bold] Semantic SHACL — Enhanced validation using embeddings (slower, more accurate)")
    console.print("  [bold]3.[/bold] Disabled — Skip validation (faster scan, no guarantees)")

    shacl_choice = IntPrompt.ask(
        "SHACL validation level",
        default=1,
        choices=["1", "2", "3"],
    )
    if shacl_choice == 3:
        gov_config["shacl_validation"] = False
    elif shacl_choice == 2:
        gov_config["shacl_validation"] = True
        gov_config["semantic_shacl"] = True

    # Document scanning
    if profile["doc_files"] > 0:
        console.print(f"\n[bold]Document Scanning[/bold] ({profile['doc_files']} docs found)")
        console.print(
            "  GraQle can ingest Markdown, PDF, DOCX, PPTX, and XLSX files\n"
            "  into the knowledge graph with cross-referencing to code.\n"
        )
        console.print("  [bold]1.[/bold] Scan all documents (recommended)")
        console.print("  [bold]2.[/bold] Code only — skip document scanning")

        doc_choice = IntPrompt.ask(
            "Document scanning",
            default=1,
            choices=["1", "2"],
        )
        gov_config["scan_docs"] = doc_choice == 1
    else:
        console.print("\n  [dim]No documentation files detected — skipping doc scan config[/dim]")

    return gov_config


# ──────────────────────────────────────────────────────────────────────
# /graq skill installer
# ──────────────────────────────────────────────────────────────────────


def _install_graq_skill(root: Path) -> bool:
    """Install the /graq smart-routing skill for Claude Code.

    Installs to TWO locations for maximum coverage:
    1. Project-local: {root}/.claude/commands/graq.md  (for this project)
    2. User-global:   ~/.claude/commands/graq.md       (for all projects)

    Returns True if at least one location was written.
    """
    installed = False

    # Project-local installation
    local_dir = root / ".claude" / "commands"
    local_path = local_dir / "graq.md"
    if local_path.exists():
        existing = local_path.read_text(encoding="utf-8", errors="ignore")
        if "Smart query router" in existing:
            console.print("  [dim].claude/commands/graq.md already installed — skipping[/dim]")
        else:
            local_dir.mkdir(parents=True, exist_ok=True)
            local_path.write_text(KOGNI_SKILL_CONTENT, encoding="utf-8")
            console.print("  [green]+[/green] .claude/commands/graq.md (project skill)")
            installed = True
    else:
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path.write_text(KOGNI_SKILL_CONTENT, encoding="utf-8")
        console.print("  [green]+[/green] .claude/commands/graq.md (project skill)")
        installed = True

    # User-global installation (only if not already there)
    home = Path.home()
    global_dir = home / ".claude" / "commands"
    global_path = global_dir / "graq.md"
    if global_path.exists():
        existing = global_path.read_text(encoding="utf-8", errors="ignore")
        if "Smart query router" in existing:
            console.print("  [dim]~/.claude/commands/graq.md already installed — skipping[/dim]")
        else:
            global_dir.mkdir(parents=True, exist_ok=True)
            global_path.write_text(KOGNI_SKILL_CONTENT, encoding="utf-8")
            console.print("  [green]+[/green] ~/.claude/commands/graq.md (global skill)")
            installed = True
    else:
        global_dir.mkdir(parents=True, exist_ok=True)
        global_path.write_text(KOGNI_SKILL_CONTENT, encoding="utf-8")
        console.print("  [green]+[/green] ~/.claude/commands/graq.md (global skill)")
        installed = True

    return installed


# ──────────────────────────────────────────────────────────────────────
# File writers (with merge/append logic)
# ──────────────────────────────────────────────────────────────────────


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts. Override values win over base values."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _write_graqle_yaml(
    root: Path, content: str, *, force: bool = False
) -> bool:
    """Write graqle.yaml, merging with existing config if present.

    v0.12.1: Merges new defaults into existing config instead of overwriting.
    User's custom values (API keys, Neo4j credentials, model overrides) are
    preserved. Only missing keys are added from the new template.
    """
    import yaml as _yaml

    target = root / "graqle.yaml"
    if target.exists():
        try:
            existing_raw = target.read_text(encoding="utf-8")
            existing = _yaml.safe_load(existing_raw) or {}
            new_config = _yaml.safe_load(content) or {}

            # Deep merge: existing user values win, new defaults fill gaps
            merged = _deep_merge(new_config, existing)
            merged_content = _yaml.dump(
                merged, default_flow_style=False, sort_keys=False,
            )

            if not force:
                try:
                    from rich.prompt import Confirm
                    update = Confirm.ask(
                        "  [yellow]graqle.yaml exists.[/yellow] "
                        "Merge new defaults (your settings preserved)?",
                        default=True,
                    )
                    if not update:
                        console.print("  [dim]Keeping existing graqle.yaml unchanged[/dim]")
                        return False
                except Exception:
                    pass  # Non-interactive: merge silently

            target.write_text(merged_content, encoding="utf-8")
            console.print("  [green]Merged new defaults into existing graqle.yaml[/green]")
            return True
        except Exception:
            pass  # If merge fails, fall through to fresh write

    target.write_text(content, encoding="utf-8")
    return True


def _write_graqle_json(root: Path, graph_data: dict[str, Any]) -> bool:
    """Write graqle.json (knowledge graph)."""
    target = root / "graqle.json"
    if target.exists():
        console.print("  [yellow]graqle.json already exists — overwriting with fresh scan[/yellow]")
    target.write_text(json.dumps(graph_data, indent=2), encoding="utf-8")
    return True


def _write_mcp_json(root: Path, ide: str = "claude") -> bool:
    """Write or merge MCP config for the target IDE."""
    if ide == "generic":
        return False  # No MCP for generic/terminal mode

    target = _get_mcp_path(root, ide)
    mcp_entry = _build_mcp_json(ide)

    # Ensure parent directory exists
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            if "mcpServers" not in existing:
                existing["mcpServers"] = {}
            if "graqle" in existing.get("mcpServers", {}):
                console.print(f"  [dim]{target.name} already has graqle entry — skipping[/dim]")
                return False
            existing["mcpServers"]["graqle"] = mcp_entry["mcpServers"]["graqle"]
            target.write_text(json.dumps(existing, indent=2), encoding="utf-8")
            console.print(f"  [green]Merged graqle into existing {target.name}[/green]")
            return True
        except (json.JSONDecodeError, KeyError):
            console.print(f"  [yellow]{target.name} exists but is invalid — overwriting[/yellow]")

    target.write_text(json.dumps(mcp_entry, indent=2), encoding="utf-8")
    return True


def _write_claude_md(root: Path, ide: str = "claude") -> bool:
    """Write or append AI instructions for the target IDE."""
    target = _get_instructions_path(root, ide)
    marker = _get_instructions_marker(ide)
    # Also check old marker for backward compat
    old_marker = "# GraQle — Governed Development Protocol"

    # Ensure parent directory exists
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if marker in existing or old_marker in existing:
            console.print(f"  [dim]{target.name} already has graQle section — skipping[/dim]")
            return False
        # Append
        with open(target, "a", encoding="utf-8") as f:
            f.write("\n\n" + AI_INSTRUCTIONS_SECTION + "\n")
        console.print(f"  [green]Appended graQle section to existing {target.name}[/green]")
        return True

    target.write_text(AI_INSTRUCTIONS_SECTION + "\n", encoding="utf-8")
    return True


def _write_gcc_structure(root: Path) -> bool:
    """Create .graq/ workspace structure. Skips if it already exists.

    Also supports legacy .gcc/ — if that exists, we skip to avoid confusion.
    """
    # Support legacy .gcc/ and new .graq/
    legacy = root / ".gcc"
    graq_dir = root / ".graq"

    if legacy.exists() or graq_dir.exists():
        name = ".gcc" if legacy.exists() else ".graq"
        console.print(f"  [dim]{name}/ already exists — skipping[/dim]")
        return False

    # Create directories using new .graq/ name
    (graq_dir / "branches" / "main").mkdir(parents=True, exist_ok=True)
    (graq_dir / "checkpoints").mkdir(parents=True, exist_ok=True)

    # Write files
    (graq_dir / "main.md").write_text(_build_gcc_main_md(root), encoding="utf-8")
    (graq_dir / "registry.md").write_text(_build_gcc_registry_md(), encoding="utf-8")
    (graq_dir / "config.yaml").write_text(_build_gcc_config_yaml(), encoding="utf-8")
    (graq_dir / "branches" / "main" / "commit.md").write_text(
        "# Commit Log — main\n\n", encoding="utf-8"
    )
    (graq_dir / "branches" / "main" / "log.md").write_text(
        "# Session Log — main\n\n", encoding="utf-8"
    )
    (graq_dir / "branches" / "main" / "metadata.yaml").write_text(
        _build_gcc_metadata_yaml(), encoding="utf-8"
    )
    # .gitkeep for checkpoints
    (graq_dir / "checkpoints" / ".gitkeep").write_text("", encoding="utf-8")

    return True


# ──────────────────────────────────────────────────────────────────────
# Main init command
# ──────────────────────────────────────────────────────────────────────


def _install_auto_grow_hook(root: Path) -> None:
    """Install a git post-commit hook that auto-updates graqle.json.

    This is the core promise: the graph adapts and grows with every commit.
    The hook runs `graq grow` which does an incremental scan + ingest.
    """
    git_dir = root / ".git"
    if not git_dir.is_dir():
        console.print("  [dim]Not a git repo — skipping auto-grow hook[/dim]")
        return

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / "post-commit"

    # The hook script
    hook_content = """#!/bin/sh
# GraQle auto-grow hook — updates the knowledge graph on every commit.
# Installed by `graq init`. Remove this file to disable.

# Run in background so commits aren't slowed down
(graq grow --quiet 2>/dev/null &)
"""

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="ignore")
        if "graq grow" in existing:
            console.print("  [dim]post-commit hook already has graq grow[/dim]")
            return
        # Append to existing hook
        with open(hook_path, "a", encoding="utf-8") as f:
            f.write("\n" + hook_content)
        console.print("  [green]+[/green] Appended graq grow to existing post-commit hook")
    else:
        hook_path.write_text(hook_content, encoding="utf-8")
        # Make executable on Unix
        try:
            hook_path.chmod(0o755)
        except Exception:
            pass
        console.print("  [green]+[/green] Installed git post-commit hook (auto-grow)")


def init_command(
    path: str = typer.Argument(".", help="Project root directory"),
    backend: str | None = typer.Option(
        None, "--backend", "-b", help="Backend: anthropic, openai, bedrock, custom"
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model identifier"
    ),
    api_key_env: str | None = typer.Option(
        None, "--api-key-env", help="Environment variable name for API key"
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="API key value (prefer --api-key-env instead)"
    ),
    no_interactive: bool = typer.Option(
        False, "--no-interactive", help="Skip interactive prompts"
    ),
    no_scan: bool = typer.Option(
        False, "--no-scan", help="Skip repository scan"
    ),
    no_gcc: bool = typer.Option(
        False, "--no-gcc", help="Skip .gcc/ directory creation"
    ),
    no_claude_md: bool = typer.Option(
        False, "--no-claude-md", help="Skip CLAUDE.md creation"
    ),
    no_mcp: bool = typer.Option(
        False, "--no-mcp", help="Skip .mcp.json creation"
    ),
    no_skill: bool = typer.Option(
        False, "--no-skill", help="Skip /graq skill installation"
    ),
    no_gate: bool = typer.Option(
        False,
        "--no-gate",
        help=(
            "Skip auto-installing the Claude Code governance gate when "
            "Claude Code is detected. Can also be set via "
            "GRAQLE_SKIP_GATE_INSTALL=1."
        ),
    ),
    ide: str = typer.Option(
        "auto", "--ide", "-i",
        help="Target IDE: auto, claude, cursor, vscode, windsurf, generic",
    ),
) -> None:
    """Initialize GraQle for your project and IDE.

    Sets up a knowledge graph, model configuration, MCP server registration
    (for your IDE), and AI instructions — everything needed for intelligent
    development. Works with any IDE, AI tool, or plain terminal.

    \b
    Interactive (default):
        graq init

    \b
    Specific IDE:
        graq init --ide cursor
        graq init --ide vscode
        graq init --ide generic    (CLI only, no MCP)

    \b
    Non-interactive:
        graq init --backend anthropic --model claude-sonnet-4-6 \\
                   --api-key-env ANTHROPIC_API_KEY --no-interactive
    """
    root = Path(path).resolve()
    if not root.exists():
        console.print(f"[red]Path not found: {root}[/red]")
        raise typer.Exit(1)

    # ── IDE detection ──────────────────────────────────────────────
    if ide == "auto":
        ide = _detect_ide(root)

    if ide not in SUPPORTED_IDES:
        console.print(f"[red]Unknown IDE '{ide}'. Choose: {', '.join(SUPPORTED_IDES.keys())}[/red]")
        raise typer.Exit(1)

    # ── Banner ──────────────────────────────────────────────────────
    console.print(
        Panel(
            "[bold cyan]GraQle[/bold cyan] — Dev Intelligence Layer\n"
            "[dim]Setting up intelligent development for your project[/dim]",
            border_style="cyan",
        )
    )
    ide_label = SUPPORTED_IDES.get(ide, ide)
    console.print(f"Project root: [bold]{root}[/bold]")
    console.print(f"Target IDE:   [bold cyan]{ide_label}[/bold cyan]\n")

    # ── Auto-detect non-TTY environment ──────────────────────────────
    if not no_interactive and not sys.stdin.isatty():
        console.print(
            "[yellow]Non-interactive mode detected. Using defaults. "
            "Pass --no-interactive explicitly to suppress this message.[/yellow]\n"
        )
        no_interactive = True

    # ── Step 1: Gather configuration ────────────────────────────────
    if no_interactive:
        # Non-interactive: use provided flags or defaults
        chosen_backend = backend or "anthropic"
        if chosen_backend not in BACKENDS:
            console.print(
                f"[red]Unknown backend '{chosen_backend}'. "
                f"Choose from: {', '.join(BACKENDS.keys())}[/red]"
            )
            raise typer.Exit(1)

        chosen_model = model
        if not chosen_model:
            models = BACKENDS[chosen_backend]["models"]
            chosen_model = next(
                (m for m, _, d in models if d),
                models[0][0] if models else "gpt-4o-mini",
            )

        if api_key:
            api_key_ref = api_key
        elif api_key_env:
            api_key_ref = f"${{{api_key_env}}}"
        else:
            env_name = BACKENDS[chosen_backend].get("api_key_env")
            api_key_ref = f"${{{env_name}}}" if env_name else ""
        chosen_embedding = None  # Use default in non-interactive mode
        gov_config = None
    else:
        # Interactive — smart guided wizard

        # ── Step 0: Quick project pre-scan ──────────────────────────
        console.print("[bold]Analyzing your project...[/bold]\n")
        project_profile = _quick_project_scan(root)
        _show_project_profile(project_profile)
        console.print()

        console.print(Panel.fit(
            "[bold cyan]Why GraQle needs an LLM backend[/bold cyan]\n\n"
            "GraQle builds a knowledge graph of your codebase so your AI\n"
            "assistant reads [bold]500-token focused summaries[/bold] instead of\n"
            "[bold]20,000+ token brute-force file scans[/bold].\n\n"
            "[green]One-time setup cost, long-term savings:[/green]\n"
            "  * 33x faster context retrieval\n"
            "  * 541x more token-efficient per query\n"
            "  * Cross-source reasoning (code + docs + configs)\n\n"
            "[dim]Choose any backend below — all work equally well.[/dim]",
            border_style="cyan",
            title="Context Intelligence",
        ))
        console.print()

        # ── Step 1/5: Backend selection ──────────────────────────────
        console.print("[bold]Step 1/5:[/bold] Choose your AI backend\n")
        chosen_backend = _prompt_backend()

        # ── Step 2/5: Model selection with recommendations ───────────
        console.print("\n[bold]Step 2/5:[/bold] Choose a reasoning model\n")
        chosen_model = _prompt_model_with_recommendation(chosen_backend, project_profile)

        # ── Step 3/5: API key configuration ──────────────────────────
        console.print("\n[bold]Step 3/5:[/bold] API key configuration\n")
        api_key_ref = _prompt_api_key(chosen_backend)

        # ── Step 4/5: Embedding model selection ──────────────────────
        console.print("\n[bold]Step 4/5:[/bold] Choose an embedding model\n")
        chosen_embedding = _prompt_embedding_model(project_profile)

        # ── Step 5/5: Governance & ontology ───────────────────────────
        console.print("\n[bold]Step 5/5:[/bold] Governance & ontology configuration\n")
        gov_config = _prompt_governance(project_profile)

    console.print(
        f"\n[bold green]Configuration:[/bold green] "
        f"{BACKENDS[chosen_backend]['name']} / {chosen_model}\n"
    )

    # ── Verify backend connection (with retry) ──────────────────────
    max_retries = 3
    for attempt in range(max_retries):
        console.print("[bold]Verifying backend connection...[/bold]")
        try:
            _verify_backend(chosen_backend, chosen_model, api_key_ref, no_interactive)
            break  # Success
        except SystemExit:
            raise  # Let typer.Exit propagate
        except Exception:
            if attempt < max_retries - 1 and not no_interactive:
                console.print(
                    "\n[yellow]Backend verification failed.[/yellow] "
                    "Would you like to try different settings?\n"
                )
                retry = Prompt.ask("Retry with different backend/model?", choices=["y", "n"], default="y")
                if retry == "y":
                    console.print("\n[bold]Step 1/5:[/bold] Choose your AI backend\n")
                    chosen_backend = _prompt_backend()
                    console.print("\n[bold]Step 2/5:[/bold] Choose a reasoning model\n")
                    chosen_model = _prompt_model_with_recommendation(chosen_backend, project_profile)
                    console.print("\n[bold]Step 3/5:[/bold] API key configuration\n")
                    api_key_ref = _prompt_api_key(chosen_backend)
                else:
                    console.print("[dim]Continuing without verified backend...[/dim]\n")
                    break
            else:
                console.print("[dim]Continuing without verified backend...[/dim]\n")
                break

    # ── Step 2: Scan + domain detection + ingest ────────────────────
    graph_data: dict[str, Any] | None = None
    if not no_scan:
        # 2a: Code scan
        console.print("[bold]Scanning repository...[/bold]")
        graph_data = scan_repository(root)
        node_count = len(graph_data["nodes"])
        edge_count = len(graph_data["links"])
        project_type = graph_data["graph"].get("project_type", "unknown")
        console.print(
            f"  Code scan: [cyan]{node_count}[/cyan] nodes, "
            f"[cyan]{edge_count}[/cyan] edges "
            f"([dim]{project_type} project[/dim])"
        )

        # 2b: Domain detection + dynamic ontology generation
        console.print("\n[bold]Detecting project domain...[/bold]")
        try:
            from graqle.ontology.domain_detector import auto_ontology, detect_domain
            profile = detect_domain(root)
            console.print(
                f"  Domain: [cyan]{profile.primary_domain}[/cyan] "
                f"({', '.join(profile.secondary_domains[:3])})"
            )
            console.print(
                f"  Language: [cyan]{profile.language}[/cyan] | "
                f"Frameworks: [cyan]{', '.join(profile.frameworks[:3]) or 'none'}[/cyan]"
            )

            # Use best LLM for ontology (Sonnet, not Haiku) — one-time cost
            ont_api_key = None
            if api_key and not api_key.startswith("${"):
                ont_api_key = api_key
            elif api_key_ref and not api_key_ref.startswith("${"):
                ont_api_key = api_key_ref
            else:
                ont_api_key = os.environ.get("ANTHROPIC_API_KEY")

            node_shapes, edge_shapes = auto_ontology(
                root, api_key=ont_api_key, register=True,
            )
            console.print(
                f"  Ontology: [green]{len(node_shapes)}[/green] node types, "
                f"[green]{len(edge_shapes)}[/green] edge types"
            )
        except Exception as e:
            console.print(f"  [yellow]Domain detection skipped: {e}[/yellow]")

        # 2c: Knowledge ingestion (markdown KGs, .gcc/, lessons, etc.)
        console.print("\n[bold]Ingesting knowledge sources...[/bold]")
        try:
            from graqle.cli.commands.ingest import (
                _discover_sources_auto,
                _discover_sources_from_config,
                _merge_graphs,
            )
            from graqle.ontology.markdown_parser import parse_and_infer

            config_path_obj = root / "graqle.yaml"
            kg_sources = _discover_sources_from_config(config_path_obj)
            if not kg_sources:
                kg_sources = _discover_sources_auto(root)

            if kg_sources:
                entities, edges_list = parse_and_infer(kg_sources)
                new_nodes = [e.to_node_dict() for e in entities]
                new_links = [
                    {
                        "source": edge.source_id,
                        "target": edge.target_id,
                        "relationship": edge.relationship,
                        "confidence": edge.confidence,
                        "source_file": edge.source_file,
                    }
                    for edge in edges_list
                ]
                graph_data = _merge_graphs(graph_data, new_nodes, new_links)
                graph_data.pop("_merge_stats", None)
                total_n = len(graph_data.get("nodes", []))
                total_e = len(graph_data.get("links", []))
                console.print(
                    f"  Ingested [cyan]{len(kg_sources)}[/cyan] source(s): "
                    f"[green]{total_n}[/green] total nodes, "
                    f"[green]{total_e}[/green] total edges"
                )
            else:
                console.print("  [dim]No markdown KG sources found (code scan only)[/dim]")
        except Exception as e:
            console.print(f"  [yellow]Ingestion skipped: {e}[/yellow]")

        # 2d: Initialize metrics
        console.print("\n[bold]Initializing metrics...[/bold]")
        try:
            from graqle.metrics.engine import MetricsEngine
            metrics = MetricsEngine(root / ".graqle")
            if graph_data:
                from collections import Counter
                type_counts = Counter(n.get("type", "") for n in graph_data.get("nodes", []))
                metrics.graph_stats_initial = {
                    "nodes": len(graph_data.get("nodes", [])),
                    "edges": len(graph_data.get("links", [])),
                    "node_types": dict(type_counts.most_common()),
                }
                metrics.graph_stats_current = dict(metrics.graph_stats_initial)
            metrics.save()
            console.print("  [green]+[/green] .graqle/metrics.json")
        except Exception as e:
            console.print(f"  [yellow]Metrics init skipped: {e}[/yellow]")

        console.print()

    # ── Step 3: Write files ─────────────────────────────────────────
    console.print("[bold]Creating files...[/bold]")

    # graqle.yaml
    yaml_content = _build_graqle_yaml(
        chosen_backend, chosen_model, api_key_ref, chosen_embedding, gov_config
    )
    _write_graqle_yaml(root, yaml_content)
    console.print("  [green]+[/green] graqle.yaml")

    # Auto-add graqle.yaml to .gitignore (prevents accidental API key leaks)
    gitignore_path = root / ".gitignore"
    _gitignore_entries = ["graqle.yaml", ".graqle/"]
    try:
        existing_gi = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
        missing = [e for e in _gitignore_entries if e not in existing_gi]
        if missing:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                if existing_gi and not existing_gi.endswith("\n"):
                    f.write("\n")
                f.write("# GraQle — config may contain API keys\n")
                for entry in missing:
                    f.write(f"{entry}\n")
            console.print(f"  [green]+[/green] .gitignore (added {', '.join(missing)})")
    except Exception:
        console.print("  [yellow]![/yellow] Could not update .gitignore — add graqle.yaml manually")

    # graqle.json
    if graph_data is not None:
        _write_graqle_json(root, graph_data)
        console.print("  [green]+[/green] graqle.json")

        # Auto-rebuild chunks from source files to ensure evidence is available
        try:
            from graqle.cli.commands.rebuild import rebuild_command
            updated = rebuild_command(
                graph_path=str(root / "graqle.json"),
                config_path=str(root / "graqle.yaml"),
                force=True,
            )
            if updated > 0:
                console.print(f"  [green]+[/green] Rebuilt chunks for {updated} nodes")
        except Exception as exc:
            console.print(f"  [yellow]![/yellow] Chunk rebuild skipped: {exc}")

        # Note: embedding cache is already built by rebuild_command above (v0.29.4+).
        # No separate ChunkScorer pass needed — rebuild_command uses
        # create_embedding_engine(config) which correctly routes to
        # TitanV2Engine / EmbeddingEngine / SimpleEmbeddingEngine.


    # MCP config (IDE-specific location)
    if not no_mcp:
        mcp_path = _get_mcp_path(root, ide)
        if _write_mcp_json(root, ide):
            console.print(f"  [green]+[/green] {mcp_path.relative_to(root)}")

    # AI instructions (IDE-specific file)
    if not no_claude_md:
        instr_path = _get_instructions_path(root, ide)
        if _write_claude_md(root, ide):
            console.print(f"  [green]+[/green] {instr_path.relative_to(root)}")

    # /graq skill (smart query router)
    if not no_skill:
        _install_graq_skill(root)

    # .graq/ workspace
    if not no_gcc:
        created = _write_gcc_structure(root)
        if created:
            console.print("  [green]+[/green] .graq/ (session workspace)")

    # ── Step 4: Install auto-grow git hook ───────────────────────────
    _install_auto_grow_hook(root)

    # ── Auto-detect readiness ──────────────────────────────────────
    # Quick health check inline (not full doctor, just key checks)
    _readiness_warnings: list[str] = []

    # Check embedding model for skill quality
    _has_embeddings = False
    try:
        import sentence_transformers  # noqa: F401
        _has_embeddings = True
    except ImportError:
        pass
    if not _has_embeddings:
        try:
            import boto3
            sts = boto3.client("sts")
            sts.get_caller_identity()
            _has_embeddings = True
        except Exception:
            pass
    if not _has_embeddings:
        _readiness_warnings.append(
            "[yellow]![/yellow] Skill matching: regex-only mode "
            "(pip install sentence-transformers for better skill assignment)"
        )

    # Check API key resolution
    _resolved_key = None
    if api_key_ref and api_key_ref.startswith("${") and api_key_ref.endswith("}"):
        _env = api_key_ref[2:-1]
        _resolved_key = os.environ.get(_env)
        if not _resolved_key:
            # For Bedrock, check boto3 credential chain (covers ~/.aws/credentials, SSO, etc.)
            if chosen_backend == "bedrock" and _env == "AWS_ACCESS_KEY_ID":
                try:
                    import boto3
                    _session = boto3.Session()
                    _creds = _session.get_credentials()
                    if _creds is not None:
                        _resolved_key = "aws-credentials-chain"
                except Exception:
                    pass
            if not _resolved_key:
                _readiness_warnings.append(
                    f"[red]![/red] API key: {_env} is NOT SET — reasoning will fail. "
                    f"Set it: export {_env}=your-key-here"
                )
    elif api_key_ref:
        _resolved_key = api_key_ref

    # ── Step 5: Track project init (lead capture) ──────────────────
    try:
        from graqle.leads.collector import track_project_init
        _node_ct = len(graph_data.get("nodes", [])) if graph_data else 0
        _edge_ct = len(graph_data.get("links", [])) if graph_data else 0
        track_project_init(
            project_path=str(root),
            node_count=_node_ct,
            edge_count=_edge_ct,
            backend=chosen_backend,
            ide=ide,
        )
    except Exception:
        pass  # Never fail on telemetry

    # ── Done ────────────────────────────────────────────────────────
    console.print()
    node_total = len(graph_data.get("nodes", [])) if graph_data else 0
    edge_total = len(graph_data.get("links", [])) if graph_data else 0

    readiness_section = ""
    if _readiness_warnings:
        readiness_section = (
            "\n[bold yellow]Readiness warnings:[/bold yellow]\n"
            + "\n".join(f"  {w}" for w in _readiness_warnings)
            + "\n"
        )

    # Build component status table
    # Show a human-friendly label for the chosen embedding model
    if not chosen_embedding or chosen_embedding == "sentence-transformers/all-MiniLM-L6-v2":
        _embedding_label = "MiniLM L6 (384-dim, local)"
    elif "titan" in (chosen_embedding or "").lower():
        _embedding_label = "Titan V2 (1024-dim, Bedrock)"
    elif "mpnet" in (chosen_embedding or "").lower():
        _embedding_label = "MPNet Base (768-dim, local)"
    else:
        _embedding_label = chosen_embedding
    _gov_label = "enabled" if (not gov_config or gov_config.get("governance_enabled", True)) else "disabled"
    _shacl_label = "semantic" if (gov_config and gov_config.get("semantic_shacl")) else (
        "enabled" if (not gov_config or gov_config.get("shacl_validation", True)) else "disabled"
    )

    # Check component availability
    _st_ok = False
    try:
        import importlib as _il
        _il.import_module("sentence_transformers")
        _st_ok = True
    except ImportError:
        pass

    _boto_ok = False
    try:
        import importlib as _il
        _il.import_module("boto3")
        _boto_ok = True
    except ImportError:
        pass

    status_lines = [
        f"  [bold]Graph:[/bold]       [cyan]{node_total}[/cyan] nodes, [cyan]{edge_total}[/cyan] edges",
        f"  [bold]Backend:[/bold]     {BACKENDS[chosen_backend]['name']} / {chosen_model}",
        f"  [bold]Embeddings:[/bold]  {_embedding_label}  {'[green]ready[/green]' if _st_ok or (_boto_ok and 'titan' in (chosen_embedding or '').lower()) else '[yellow]fallback mode[/yellow]'}",
        f"  [bold]Governance:[/bold]  {_gov_label}",
        f"  [bold]SHACL:[/bold]       {_shacl_label}",
        f"  [bold]IDE:[/bold]         {ide_label}",
    ]

    # Plugin status
    plugin_lines = []
    if _st_ok:
        plugin_lines.append("  [green]OK[/green] sentence-transformers (semantic embeddings)")
    else:
        plugin_lines.append("  [yellow]--[/yellow] sentence-transformers [dim](pip install sentence-transformers)[/dim]")
    if _boto_ok:
        plugin_lines.append("  [green]OK[/green] boto3 (AWS Bedrock / cloud push)")
    else:
        plugin_lines.append("  [yellow]--[/yellow] boto3 [dim](pip install boto3)[/dim]")
    if _resolved_key:
        plugin_lines.append(f"  [green]OK[/green] API key ({chosen_backend})")
    else:
        plugin_lines.append(f"  [red]--[/red] API key [dim](set {BACKENDS[chosen_backend].get('api_key_env', 'API_KEY')})[/dim]")

    # ── Auto-install Claude Code governance gate (CG-GATE-02, v0.50.1) ──
    # If Claude Code is detected in this project OR user-globally, and the
    # user has not opted out, install the governance gate so that native
    # Claude Code tools (Read/Write/Edit/Bash/...) are routed through the
    # governed graq_* equivalents.
    skip_gate = no_gate or os.environ.get("GRAQLE_SKIP_GATE_INSTALL") == "1"
    if not skip_gate:
        claude_in_project = (root / ".claude").exists()
        claude_in_home = (Path.home() / ".claude").exists()
        if claude_in_project or claude_in_home:
            try:
                from graqle.cli.main import gate_install_command
                console.print(
                    "\n[cyan]Claude Code detected — installing governance gate...[/cyan]"
                )
                gate_install_command(
                    path=str(root),
                    force=False,
                    dry_run=False,
                    json_output=False,
                    fix_interpreter=False,
                )
            except typer.Exit as exc:
                if exc.exit_code not in (0, None):
                    console.print(
                        "[yellow]Gate install skipped "
                        "(already installed or --force needed). "
                        "Run 'graq gate-install --force' manually if needed.[/yellow]"
                    )
            except Exception as exc:  # noqa: BLE001
                console.print(
                    f"[yellow]Gate auto-install failed: {exc}. "
                    "Run 'graq gate-install' manually.[/yellow]"
                )

    # Choose header and border based on graph health
    if node_total == 0:
        _header = "[bold yellow]Project initialized — but graph is empty![/bold yellow]"
        _border = "yellow"
        _title = "Warning"
        _graph_warning = (
            "\n[yellow]The knowledge graph has 0 nodes. This means scanning found no code files.\n"
            "Possible causes:\n"
            "  - You ran init with --no-scan\n"
            "  - The directory contains no .py / .js / .ts files\n"
            "  - All files matched exclude patterns\n"
            "Run [bold]graq scan repo .[/bold] to rebuild the graph.[/yellow]\n"
        )
    else:
        _header = "[bold green]Project initialized![/bold green]"
        _border = "green"
        _title = "Done"
        _graph_warning = ""

    console.print(
        Panel(
            f"{_header}\n\n"
            + "\n".join(status_lines) + "\n"
            f"{_graph_warning}"
            f"{readiness_section}\n"
            "[bold]Component Status:[/bold]\n"
            + "\n".join(plugin_lines) + "\n\n"
            "[bold]Next steps:[/bold]\n"
            "  1. [bold]graq doctor[/bold]          — verify your setup is complete\n"
            "  2. [bold]/graq <question>[/bold]     — smart-routed query (cheapest approach)\n"
            "  3. [bold]graq run \"query\"[/bold]    — full graph reasoning\n\n"
            "[bold]All commands:[/bold]\n"
            "  [bold]graq doctor[/bold]             — health check\n"
            "  [bold]graq context <name>[/bold]    — 500-token focused context\n"
            "  [bold]graq impact <module>[/bold]   — dependency impact analysis\n"
            "  [bold]graq cloud push[/bold]        — push graph to cloud dashboard\n"
            "  [bold]graq inspect --stats[/bold]   — graph statistics\n\n"
            f"[dim]Auto-grow: git post-commit hook keeps the knowledge graph in sync.[/dim]",
            border_style=_border,
            title=_title,
        )
    )

    # Registration nudge (soft, non-blocking)
    try:
        from graqle.leads.collector import get_registration_nudge
        nudge = get_registration_nudge()
        if nudge:
            console.print(f"\n{nudge}")
    except Exception:
        pass
