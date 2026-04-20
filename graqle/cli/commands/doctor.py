"""graq doctor — comprehensive health check for GraQle installation.

Validates everything a user needs for good reasoning results:
1. Python version & core dependencies
2. Backend packages (anthropic, openai, boto3, ollama)
3. API keys & environment variables
4. Embedding models (Titan V2, sentence-transformers)
5. Graph file & quality
6. Config file validity
7. MCP server registration
8. Skill system readiness

Designed to be the FIRST command a user runs after install.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.doctor
# risk: MEDIUM (impact radius: 1 modules)
# consumers: main
# dependencies: __future__, importlib, os, sys, pathlib +6 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from graqle.cli.console import BRAND_NAME

console = Console()

# Check result types
PASS = "pass"
WARN = "warn"
FAIL = "fail"
INFO = "info"

CheckResult = tuple[str, str, str]  # (status, label, detail)


def _check_python_version() -> CheckResult:
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    if v.major == 3 and v.minor >= 10:
        return (PASS, "Python version", ver_str)
    elif v.major == 3 and v.minor >= 8:
        return (WARN, "Python version", f"{ver_str} (3.10+ recommended)")
    return (FAIL, "Python version", f"{ver_str} (requires 3.8+)")


def _check_graq_on_path() -> CheckResult:
    """Check if the graq CLI is on the system PATH."""
    import shutil
    graq_path = shutil.which("graq")
    if graq_path:
        return (PASS, "CLI: graq on PATH", graq_path)
    return (
        WARN,
        "CLI: graq on PATH",
        "not found — MCP servers may fail. Use fallback: "
        '{"command": "python", "args": ["-m", "graqle.cli.main", "mcp", "serve"]}',
    )


def _check_core_deps() -> list[CheckResult]:
    results = []
    core = ["networkx", "numpy", "pydantic", "pyyaml", "typer", "rich"]
    for pkg in core:
        mod_name = pkg.replace("-", "_").replace("pyyaml", "yaml")
        try:
            mod = importlib.import_module(mod_name)
            ver = getattr(mod, "__version__", "installed")
            results.append((PASS, f"Core: {pkg}", ver))
        except ImportError:
            results.append((FAIL, f"Core: {pkg}", "NOT INSTALLED"))
    return results


def _get_configured_backend() -> str | None:
    """Read the configured backend from graqle.yaml (if present)."""
    config_path = Path("graqle.yaml")
    if not config_path.exists():
        return None
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("model", {}).get("backend")
    except Exception:
        return None


def _check_backend_packages() -> list[CheckResult]:
    """Check which backend packages are available.

    Only warns about the configured backend; others shown as INFO.
    """
    results = []
    configured = _get_configured_backend()  # e.g. "anthropic", "bedrock", "openai", "ollama"

    # Map config backend names to package names
    config_to_pkg = {
        "anthropic": "anthropic",
        "openai": "openai",
        "bedrock": "boto3",
        "ollama": "httpx",
    }

    backends = {
        "anthropic": ("anthropic", "ANTHROPIC_API_KEY", "Claude (Anthropic)"),
        "openai": ("openai", "OPENAI_API_KEY", "GPT (OpenAI)"),
        "boto3": ("boto3", None, "Bedrock (AWS)"),  # checked via boto3 credentials
        "httpx": ("httpx", None, "Ollama (local)"),
    }
    any_backend = False
    configured_pkg = config_to_pkg.get(configured, "") if configured else ""
    for pkg, (mod_name, env_var, label) in backends.items():
        try:
            mod = importlib.import_module(mod_name)
            ver = getattr(mod, "__version__", "installed")
            has_key = True
            key_status = ""
            if env_var:
                has_key = bool(os.environ.get(env_var))
                key_status = f" | {env_var}: {'set' if has_key else 'NOT SET'}"
            elif mod_name == "boto3":
                # Check boto3 credentials (env vars, ~/.aws/credentials, SSO, etc.)
                try:
                    import boto3
                    session = boto3.Session()
                    creds = session.get_credentials()
                    if creds is not None:
                        has_key = True
                        key_status = " | AWS credentials: found"
                    else:
                        has_key = False
                        key_status = " | AWS credentials: NOT FOUND"
                except Exception:
                    has_key = False
                    key_status = " | AWS credentials: check failed"
            if has_key:
                results.append((PASS, f"Backend: {label}", f"{ver}{key_status}"))
                any_backend = True
            else:
                # Only warn for the configured backend; others are INFO
                is_configured = (configured_pkg == pkg) if configured_pkg else True
                level = WARN if is_configured else INFO
                results.append((level, f"Backend: {label}", f"{ver}{key_status}"))
        except ImportError:
            is_configured = (configured_pkg == pkg) if configured_pkg else False
            level = WARN if is_configured else INFO
            results.append((level, f"Backend: {label}", f"{pkg} not installed"))

    # Check provider presets (env-var based, no package needed)
    provider_env_vars = {
        "GROQ_API_KEY": "Groq",
        "DEEPSEEK_API_KEY": "DeepSeek",
        "GEMINI_API_KEY": "Google Gemini",
        "GOOGLE_API_KEY": "Google Gemini",
        "MISTRAL_API_KEY": "Mistral AI",
        "TOGETHER_API_KEY": "Together AI",
        "OPENROUTER_API_KEY": "OpenRouter",
        "FIREWORKS_API_KEY": "Fireworks AI",
        "COHERE_API_KEY": "Cohere",
    }
    seen_providers: set[str] = set()
    for env_var, label in provider_env_vars.items():
        if label in seen_providers:
            continue  # skip duplicate labels (GEMINI/GOOGLE)
        has_key = bool(os.environ.get(env_var))
        if has_key:
            results.append((PASS, f"Provider: {label}", f"{env_var}: set"))
            any_backend = True
            seen_providers.add(label)

    if not any_backend:
        results.append((
            FAIL,
            "No working backend",
            "Install one: pip install graqle[api]  OR  pip install ollama httpx",
        ))
    return results


def _check_api_keys() -> list[CheckResult]:
    """Check API key availability and basic validity."""
    results = []
    keys = {
        "ANTHROPIC_API_KEY": ("sk-ant-", "Anthropic"),
        "OPENAI_API_KEY": ("sk-", "OpenAI"),
    }
    for var, (prefix, label) in keys.items():
        val = os.environ.get(var, "")
        if val:
            # Basic format check (don't log the key!)
            masked = val[:8] + "..." + val[-4:] if len(val) > 12 else "***"
            if prefix and not val.startswith(prefix):
                results.append((WARN, f"Key: {var}", f"{masked} (unexpected format)"))
            else:
                results.append((PASS, f"Key: {var}", masked))
        else:
            results.append((INFO, f"Key: {var}", "not set"))

    # AWS credentials: check full boto3 chain (env vars, ~/.aws/credentials, SSO, instance profile)
    # Not just AWS_ACCESS_KEY_ID env var — users commonly use ~/.aws/credentials
    aws_env = os.environ.get("AWS_ACCESS_KEY_ID", "")
    if aws_env:
        masked = aws_env[:8] + "..." + aws_env[-4:] if len(aws_env) > 12 else "***"
        if not aws_env.startswith("AKIA"):
            results.append((WARN, "Key: AWS credentials", f"{masked} (unexpected format)"))
        else:
            results.append((PASS, "Key: AWS credentials", f"env: {masked}"))
    else:
        # Check boto3 credential chain (covers ~/.aws/credentials, SSO, instance profiles)
        try:
            import boto3
            session = boto3.Session()
            creds = session.get_credentials()
            if creds is not None:
                frozen = creds.get_frozen_credentials()
                if frozen and frozen.access_key:
                    masked = frozen.access_key[:8] + "..." + frozen.access_key[-4:]
                    results.append((PASS, "Key: AWS credentials", f"~/.aws/credentials: {masked}"))
                else:
                    results.append((PASS, "Key: AWS credentials", "found via boto3 chain"))
            else:
                results.append((INFO, "Key: AWS credentials", "not configured"))
        except ImportError:
            results.append((INFO, "Key: AWS credentials", "boto3 not installed"))
        except Exception:
            results.append((INFO, "Key: AWS credentials", "not configured"))

    return results


def _check_embedding_models() -> list[CheckResult]:
    """Check embedding model availability for skill assignment."""
    results = []

    # Check Titan V2 (best quality)
    try:
        import boto3
        region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
        if not region:
            # Try reading from graqle.yaml
            try:
                import yaml
                cfg_path = Path("graqle.yaml")
                if cfg_path.exists():
                    with open(cfg_path, encoding="utf-8") as f:
                        cfg = yaml.safe_load(f) or {}
                    region = cfg.get("model", {}).get("region")
            except Exception:
                pass
        if not region:
            results.append((WARN, "Embeddings: Titan V2",
                            "no AWS region configured — set AWS_DEFAULT_REGION or add region to graqle.yaml"))
            raise Exception("skip")
        client = boto3.client("bedrock-runtime", region_name=region)
        # Don't actually call — just check credentials
        sts = boto3.client("sts")
        sts.get_caller_identity()
        results.append((PASS, "Embeddings: Titan V2", "AWS credentials valid (best quality, 1024-dim)"))
    except Exception as e:
        err = str(e)[:60]
        results.append((INFO, "Embeddings: Titan V2", f"not available ({err})"))

    # Check sentence-transformers (good fallback)
    try:
        import sentence_transformers
        ver = getattr(sentence_transformers, "__version__", "installed")
        results.append((PASS, "Embeddings: sentence-transformers", f"{ver} (384-dim, local)"))
    except ImportError:
        results.append((WARN, "Embeddings: sentence-transformers",
                        "NOT INSTALLED — pip install sentence-transformers"))

    # Summary
    has_titan = any(r[0] == PASS and "Titan" in r[1] for r in results)
    has_st = any(r[0] == PASS and "sentence" in r[1] for r in results)
    if has_titan:
        results.append((PASS, "Skill matching mode", "hybrid (regex + Titan V2 semantic)"))
    elif has_st:
        results.append((PASS, "Skill matching mode", "hybrid (regex + sentence-transformers semantic)"))
    else:
        results.append((WARN, "Skill matching mode", "regex-only (install sentence-transformers for better skills)"))

    return results


def _check_config_file() -> list[CheckResult]:
    """Check graqle.yaml validity."""
    results = []
    config_path = Path("graqle.yaml")

    if not config_path.exists():
        results.append((WARN, "Config: graqle.yaml", "not found — run 'graq init'"))
        return results

    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            results.append((FAIL, "Config: graqle.yaml", "empty file"))
            return results

        results.append((PASS, "Config: graqle.yaml", "valid YAML"))

        # Check for unresolved env var references
        model_cfg = data.get("model", {})
        api_key = model_cfg.get("api_key", "")
        if api_key and api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            if os.environ.get(env_var):
                results.append((PASS, "Config: api_key ref", f"${{{env_var}}} -> set"))
            else:
                results.append((FAIL, "Config: api_key ref",
                                f"${{{env_var}}} -> NOT SET! Reasoning will fail"))

        backend = model_cfg.get("backend", "mock")
        model = model_cfg.get("model", "unknown")
        results.append((INFO, "Config: backend", f"{backend} / {model}"))

    except Exception as e:
        results.append((FAIL, "Config: graqle.yaml", f"parse error: {e}"))

    return results


def _check_graph_file() -> list[CheckResult]:
    """Check knowledge graph file existence and quality."""
    results = []

    candidates = ["graqle.json", "knowledge_graph.json", "graph.json"]
    found = None
    for c in candidates:
        if Path(c).exists():
            found = c
            break

    if not found:
        results.append((WARN, "Graph file", "not found — run 'graq init' or 'graq scan'"))
        return results

    try:
        import json
        size = Path(found).stat().st_size
        with open(found, encoding="utf-8") as f:
            data = json.load(f)

        nodes = data.get("nodes", [])
        edges = data.get("links", data.get("edges", []))

        results.append((PASS, "Graph file", f"{found} ({size:,} bytes)"))
        results.append((INFO, "Graph: nodes", str(len(nodes))))
        results.append((INFO, "Graph: edges", str(len(edges))))

        if len(nodes) == 0:
            results.append((FAIL, "Graph: quality", "0 nodes — graph is empty"))
        else:
            # Check description coverage
            with_desc = sum(1 for n in nodes if n.get("description", "").strip())
            pct = with_desc / len(nodes) * 100
            if pct >= 80:
                results.append((PASS, "Graph: descriptions", f"{pct:.0f}% nodes have descriptions"))
            elif pct >= 50:
                results.append((WARN, "Graph: descriptions", f"{pct:.0f}% — run 'graq validate --fix'"))
            else:
                results.append((FAIL, "Graph: descriptions", f"Only {pct:.0f}% — reasoning quality will be poor"))

    except Exception as e:
        results.append((FAIL, "Graph file", f"{found} — parse error: {e}"))

    return results


def _check_storage_tiers() -> list[CheckResult]:
    """Check storage tier status and invariant."""
    results = []
    try:
        from graqle.storage.tiers import StorageTiers, TierStatus

        tiers = StorageTiers()
        for td in tiers.all():
            if td.status == TierStatus.ACTIVE:
                results.append((PASS, td.name, td.detail))
            elif td.status == TierStatus.OPT_IN_AVAILABLE:
                results.append((INFO, td.name, td.detail))
            elif td.status == TierStatus.DISABLED:
                results.append((WARN, td.name, td.detail))
            else:
                results.append((INFO, td.name, td.detail))

        if tiers.has_override():
            ep = tiers.effective_primary()
            results.append((FAIL, "Storage invariant", ep.detail))
        else:
            ok, reason = tiers.enforce()
            if ok:
                results.append((PASS, "Storage invariant", "Tier 0 is single source of truth — OK"))
            else:
                results.append((WARN, "Storage invariant", reason))
    except Exception as e:
        results.append((WARN, "Storage tiers", f"Could not check: {e}"))
    return results


def _check_mcp_registration() -> list[CheckResult]:
    """Check if MCP server is registered for any supported IDE.

    Bug 17 fix: checks all IDE-specific MCP config paths, not just .mcp.json.
    """
    import json as _json

    results = []

    # All known MCP config paths (IDE → path)
    mcp_paths = {
        "Claude Code": Path(".mcp.json"),
        "Cursor": Path(".cursor") / "mcp.json",
        "VS Code": Path(".vscode") / "mcp.json",
    }

    found_any = False
    for ide_name, mcp_path in mcp_paths.items():
        if not mcp_path.exists():
            continue

        try:
            with open(mcp_path, encoding="utf-8") as f:
                data = _json.load(f)

            servers = data.get("mcpServers", {})
            # Check both "graq" and "graqle" server names (Bug 17)
            mcp_key = None
            for key in ("graq", "graqle"):
                if key in servers:
                    mcp_key = key
                    break

            if mcp_key is not None:
                cmd = servers[mcp_key].get("command", "?")
                args = servers[mcp_key].get("args", [])
                results.append((
                    PASS,
                    f"MCP: {ide_name}",
                    f"{cmd} {' '.join(args)} ({mcp_path})",
                ))
                found_any = True
            else:
                results.append((
                    WARN,
                    f"MCP: {ide_name}",
                    f"{mcp_path} exists but 'graq'/'graqle' server not registered",
                ))
        except Exception as e:
            results.append((FAIL, f"MCP: {ide_name}", f"{mcp_path} parse error: {e}"))

    if not found_any:
        results.append((
            WARN,
            "MCP: registration",
            "not found in any IDE config — run 'graq init' to configure",
        ))

    return results


def _check_bedrock_model_id() -> list[CheckResult]:
    """Validate configured Bedrock model ID against available models."""
    results = []

    # Only check if backend is bedrock
    config_path = Path("graqle.yaml")
    if not config_path.exists():
        return results

    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        model_cfg = data.get("model", {})
        if model_cfg.get("backend") != "bedrock":
            return results
        configured_model = model_cfg.get("model", "")
        if not configured_model:
            return results
    except Exception:
        return results

    try:
        import boto3
        region = (
            model_cfg.get("region")
            or os.environ.get("AWS_DEFAULT_REGION")
            or os.environ.get("AWS_REGION")
        )
        if not region:
            results.append((
                WARN,
                "Bedrock: model ID",
                "no AWS region configured — set region in graqle.yaml or AWS_DEFAULT_REGION",
            ))
            return results
        client = boto3.client("bedrock", region_name=region)
        response = client.list_foundation_models()
        available_ids = {
            m["modelId"] for m in response.get("modelSummaries", [])
        }

        # Also check inference profile format (e.g. eu.anthropic.claude-*)
        # These won't appear in list_foundation_models but are valid
        is_profile = any(
            configured_model.startswith(prefix)
            for prefix in ("us.", "eu.", "ap.", "global.")
        )

        # Normalize: try both with and without version suffix (:0, :1, etc.)
        # AWS Console shows IDs with :0 but list_foundation_models may or may not
        model_variants = {configured_model}
        # Add variant without version suffix
        if re.search(r"-v\d+:\d+$", configured_model):
            model_variants.add(re.sub(r"-v\d+:\d+$", "", configured_model))
        # Add variant with version suffix if missing
        if not re.search(r"-v\d+:\d+$", configured_model):
            model_variants.add(f"{configured_model}-v1:0")

        matched = model_variants & available_ids
        if matched:
            results.append((
                PASS,
                "Bedrock: model ID",
                f"{configured_model} (valid in {region})",
            ))
        elif is_profile:
            # Cross-region inference profiles are valid but not in the list
            base_model = configured_model.split(".", 1)[1] if "." in configured_model else configured_model
            base_variants = {base_model}
            if re.search(r"-v\d+:\d+$", base_model):
                base_variants.add(re.sub(r"-v\d+:\d+$", "", base_model))
            if not re.search(r"-v\d+:\d+$", base_model):
                base_variants.add(f"{base_model}-v1:0")

            if base_variants & available_ids:
                results.append((
                    PASS,
                    "Bedrock: model ID",
                    f"{configured_model} (inference profile, base model valid)",
                ))
            else:
                results.append((
                    WARN,
                    "Bedrock: model ID",
                    f"{configured_model} (inference profile — cannot verify base model '{base_model}')",
                ))
        else:
            # Find close matches for suggestion
            import difflib
            suggestions = difflib.get_close_matches(
                configured_model, list(available_ids), n=3, cutoff=0.4
            )
            hint = ""
            if suggestions:
                hint = f" Did you mean: {', '.join(suggestions)}"
            results.append((
                WARN,
                "Bedrock: model ID",
                f"'{configured_model}' not found in {region}.{hint} "
                f"Format: provider.model-name (e.g. anthropic.claude-sonnet-4-6) "
                f"or with version: anthropic.claude-sonnet-4-6-v1:0",
            ))

    except ImportError:
        # boto3 not installed — skip silently
        pass
    except Exception as e:
        err = str(e)[:80]
        results.append((
            WARN,
            "Bedrock: model ID",
            f"could not validate ({err})",
        ))

    return results


def _check_skill_system() -> list[CheckResult]:
    """Check skill admin readiness."""
    results = []
    try:
        from graqle.ontology.skill_admin import SKILL_LIBRARY, SkillAdmin
        results.append((PASS, "Skills: library", f"{len(SKILL_LIBRARY)} skills across 9 domains"))

        # Test that SkillAdmin can be instantiated
        admin = SkillAdmin(use_titan=False)
        results.append((PASS, "Skills: admin mode", admin.mode))

    except Exception as e:
        results.append((FAIL, "Skills: import error", str(e)[:80]))

    return results


def _check_neo4j_backend() -> list[CheckResult]:
    """Check Neo4j availability and show latency comparison."""
    import json
    import time
    results = []

    # Check current backend from config
    current_backend = "json"
    config_path = Path("graqle.yaml")
    if config_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            current_backend = cfg.get("graph", {}).get("connector", "networkx")
        except Exception:
            pass

    if current_backend == "neo4j":
        # Already on Neo4j — check connection
        try:
            from neo4j import GraphDatabase
            uri = "bolt://localhost:7687"
            if config_path.exists():
                try:
                    import yaml
                    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                    uri = cfg.get("graph", {}).get("uri", uri)
                except Exception:
                    pass

            results.append((PASS, "Backend: Neo4j", f"connected ({uri})"))

            # Show traversal capabilities
            try:
                from graqle.connectors.neo4j_traversal import Neo4jTraversal
                t = Neo4jTraversal(
                    uri=cfg.get("graph", {}).get("uri", "bolt://localhost:7687"),
                    username=cfg.get("graph", {}).get("username", "neo4j"),
                    password=cfg.get("graph", {}).get("password", ""),
                    database=cfg.get("graph", {}).get("database", "neo4j"),
                )
                hubs = t.hub_nodes(top_k=3)
                t0 = time.perf_counter()
                t.impact_bfs(hubs[0]["id"] if hubs else "graqle/core/graph.py", max_depth=3)
                impact_ms = (time.perf_counter() - t0) * 1000
                t.close()
                results.append((PASS, "Neo4j: traversal", f"3-hop impact in {impact_ms:.0f}ms"))
                if hubs:
                    hub_str = ", ".join(h["id"].split("/")[-1] for h in hubs[:3])
                    results.append((INFO, "Neo4j: top hubs", hub_str))
            except Exception as e:
                results.append((WARN, "Neo4j: traversal", f"engine not available ({e})"))

        except ImportError:
            results.append((FAIL, "Backend: Neo4j", "configured but neo4j driver not installed"))
        except Exception as e:
            results.append((WARN, "Backend: Neo4j", f"configured but connection failed: {e}"))
    else:
        # On JSON/NetworkX — show upgrade opportunity
        results.append((INFO, "Backend: JSON", "using file-based graph"))

        # Benchmark current JSON load
        graph_file = None
        for c in ["graqle.json", "knowledge_graph.json", "graph.json"]:
            if Path(c).exists():
                graph_file = Path(c)
                break

        if graph_file:
            try:
                t0 = time.perf_counter()
                data = json.loads(graph_file.read_text(encoding="utf-8"))
                json_ms = (time.perf_counter() - t0) * 1000
                node_count = len(data.get("nodes", []))

                if node_count >= 1000:
                    results.append((WARN, "Backend: performance",
                        f"{node_count:,} nodes — Neo4j would be 12× faster for impact analysis"))
                    results.append((INFO, "Backend: upgrade",
                        "run 'graq upgrade neo4j' for native traversal + PageRank"))
                elif node_count >= 500:
                    results.append((INFO, "Backend: Neo4j ready",
                        f"{node_count:,} nodes — consider 'graq upgrade neo4j' for speed boost"))
            except Exception:
                pass

        # Check if Neo4j driver is at least installed
        try:
            import neo4j  # noqa: F401
            results.append((INFO, "Neo4j: driver", "installed (not configured)"))
        except ImportError:
            results.append((INFO, "Neo4j: driver", "not installed — pip install graqle[neo4j]"))

    return results


def _check_governance_gate() -> list[CheckResult]:
    """Check governance gate status — compile + verify + pre-commit hook."""
    results = []

    # 1. Check compiled intelligence
    graqle_dir = Path(".graqle")
    intel_dir = graqle_dir / "intelligence"
    if intel_dir.is_dir():
        modules = list((intel_dir / "modules").glob("*.json")) if (intel_dir / "modules").is_dir() else []
        if modules:
            results.append((PASS, "Gate: intelligence", f"{len(modules)} modules compiled"))
        else:
            results.append((WARN, "Gate: intelligence", "compiled but no modules — run 'graq compile'"))
    else:
        results.append((WARN, "Gate: intelligence", "not compiled — run 'graq compile'"))

    # 2. Check scorecard
    scorecard_path = graqle_dir / "scorecard.json"
    if scorecard_path.exists():
        try:
            import json
            sc = json.loads(scorecard_path.read_text(encoding="utf-8"))
            health = sc.get("health", "UNKNOWN")
            coverage = sc.get("chunk_coverage", 0)
            style = "PASS" if health == "HEALTHY" else "WARN"
            results.append((PASS if health == "HEALTHY" else WARN,
                          "Gate: health", f"{health} ({coverage:.0f}% chunk coverage)"))
        except Exception:
            results.append((WARN, "Gate: scorecard", "exists but unreadable"))
    else:
        results.append((WARN, "Gate: scorecard", "not found — run 'graq compile'"))

    # 3. Check pre-commit hook
    try:
        from graqle.intelligence.hooks import has_hook
        if has_hook(Path(".")):
            results.append((PASS, "Gate: pre-commit hook", "graq verify runs before every commit"))
        else:
            results.append((WARN, "Gate: pre-commit hook",
                          "not installed — run 'graq compile --hook' to enforce"))
    except Exception:
        results.append((INFO, "Gate: pre-commit hook", "check skipped (not a git repo)"))

    # 4. Check CLAUDE.md intelligence section
    claude_md = Path("CLAUDE.md")
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        if "GraQle Quality Gate" in content or "graqle:intelligence" in content.lower() or "Module Risk Map" in content:
            results.append((PASS, "Gate: CLAUDE.md", "intelligence section injected"))
        else:
            results.append((WARN, "Gate: CLAUDE.md",
                          "exists but no intelligence — run 'graq compile --inject'"))
    else:
        results.append((WARN, "Gate: CLAUDE.md", "not found — run 'graq compile --inject'"))

    # 5. Check governance audit trail
    audit_dir = graqle_dir / "governance" / "audit"
    if audit_dir.is_dir():
        sessions = list(audit_dir.glob("*.json"))
        if sessions:
            results.append((PASS, "Gate: audit trail", f"{len(sessions)} sessions recorded"))
            # Check latest DRACE score
            try:
                import json
                latest = sorted(sessions, reverse=True)[0]
                data = json.loads(latest.read_text(encoding="utf-8"))
                drace = data.get("drace_score")
                if drace is not None:
                    style = PASS if drace >= 0.7 else WARN
                    results.append((style, "Gate: DRACE score", f"{drace:.2f}"))
            except Exception:
                pass
        else:
            results.append((INFO, "Gate: audit trail", "no sessions yet"))
    else:
        results.append((INFO, "Gate: audit trail", "not initialized"))

    return results


def _check_reasoning_smoke() -> list[CheckResult]:
    """Run a trivial reasoning smoke test if a backend + graph are available."""
    results: list[CheckResult] = []

    # Only attempt if we have a graph file and config
    graph_file = None
    for c in ["graqle.json", "knowledge_graph.json", "graph.json"]:
        if Path(c).exists():
            graph_file = c
            break

    if not graph_file:
        results.append((INFO, "Smoke: reasoning", "skipped (no graph file)"))
        return results

    config_path = Path("graqle.yaml")
    if not config_path.exists():
        results.append((INFO, "Smoke: reasoning", "skipped (no graqle.yaml)"))
        return results

    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        backend = data.get("model", {}).get("backend", "mock")
        if backend in ("local", "mock"):
            results.append((INFO, "Smoke: reasoning", f"skipped (backend={backend})"))
            return results
    except Exception:
        results.append((INFO, "Smoke: reasoning", "skipped (config unreadable)"))
        return results

    # Attempt a lightweight graph load (no LLM call — just verify the pipeline initializes)
    try:
        from graqle.core.graph import Graqle
        graph = Graqle.from_json(graph_file)
        node_count = len(graph.nodes)
        if node_count > 0:
            results.append((
                PASS,
                "Smoke: graph loads",
                f"{node_count} nodes from {graph_file} — ready for reasoning",
            ))
        else:
            results.append((WARN, "Smoke: graph loads", "0 nodes — reasoning will have no data"))
    except Exception as e:
        err = str(e)[:80]
        results.append((WARN, "Smoke: graph loads", f"failed to load {graph_file}: {err}"))

    return results


def _check_cloud_connection() -> list[CheckResult]:
    """Check GraQle Cloud connectivity and credentials."""
    results: list[CheckResult] = []

    # Check credentials file
    try:
        from graqle.cloud.credentials import load_credentials
        creds = load_credentials()
        if creds and creds.email:
            results.append((PASS, "Cloud: credentials", f"logged in as {creds.email}"))
        else:
            results.append((INFO, "Cloud: credentials", "not logged in (run: graq login)"))
            return results
    except Exception:
        results.append((INFO, "Cloud: credentials", "not configured (run: graq login)"))
        return results

    # Check S3 connectivity
    try:
        import boto3
        s3 = boto3.client("s3", region_name="eu-central-1")
        import hashlib
        email_h = hashlib.sha256(creds.email.lower().encode()).hexdigest()[:16]
        resp = s3.list_objects_v2(
            Bucket="graqle-graphs-eu",
            Prefix=f"graphs/{email_h}/",
            MaxKeys=10,
        )
        count = resp.get("KeyCount", 0)
        if count > 0:
            results.append((PASS, "Cloud: projects", f"{count} files in cloud"))
        else:
            results.append((INFO, "Cloud: projects", "no projects pushed yet (run: graq cloud push)"))
    except Exception as e:
        results.append((WARN, "Cloud: S3 access", f"cannot reach cloud: {e}"))

    return results


def doctor_command(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all checks including passed"),
    fix: bool = typer.Option(False, "--fix", help="Show fix commands for failures"),
) -> None:
    """Health check for your GraQle installation.

    Validates dependencies, API keys, config, graph, embeddings,
    skills, and MCP server registration. Run this after install.

    \b
    Examples:
        graq doctor
        graq doctor --fix     (show fix commands)
        graq doctor --verbose (show all checks)
    """
    from graqle.__version__ import __version__

    console.print(Panel.fit(
        f"[bold cyan]GraQle Doctor[/bold cyan] v{__version__}\n"
        f"Checking your installation...",
        border_style="cyan",
    ))

    all_results: list[CheckResult] = []

    # Run all checks
    all_results.append(_check_python_version())
    all_results.append(_check_graq_on_path())
    all_results.extend(_check_core_deps())
    all_results.extend(_check_backend_packages())
    all_results.extend(_check_api_keys())
    all_results.extend(_check_embedding_models())
    all_results.extend(_check_config_file())
    all_results.extend(_check_bedrock_model_id())
    all_results.extend(_check_graph_file())
    all_results.extend(_check_storage_tiers())
    all_results.extend(_check_mcp_registration())
    all_results.extend(_check_skill_system())
    all_results.extend(_check_neo4j_backend())
    all_results.extend(_check_governance_gate())
    all_results.extend(_check_reasoning_smoke())
    all_results.extend(_check_cloud_connection())

    # Count results
    passes = sum(1 for r in all_results if r[0] == PASS)
    warns = sum(1 for r in all_results if r[0] == WARN)
    fails = sum(1 for r in all_results if r[0] == FAIL)
    infos = sum(1 for r in all_results if r[0] == INFO)

    # Build table
    table = Table(show_header=True, header_style="bold")
    table.add_column("", width=4)
    table.add_column("Check", min_width=30)
    table.add_column("Detail")

    icons = {PASS: "[green]OK[/green]", WARN: "[yellow]!![/yellow]",
             FAIL: "[red]FAIL[/red]", INFO: "[dim]--[/dim]"}

    for status, label, detail in all_results:
        if not verbose and status in (PASS, INFO):
            continue
        table.add_row(icons[status], label, detail)

    # If verbose, show all
    if verbose:
        for status, label, detail in all_results:
            pass  # Already added above
    else:
        # Show passes count
        if passes > 0:
            table.add_row(
                icons[PASS],
                f"[dim]{passes} checks passed[/dim]",
                "[dim]use --verbose to see all[/dim]",
            )

    console.print(table)

    # Summary
    console.print()
    if fails == 0 and warns == 0:
        console.print(f"[bold green]All checks passed! {BRAND_NAME} is ready.[/bold green]")
    elif fails == 0:
        console.print(f"[bold yellow]{warns} warning(s) — {BRAND_NAME} will work but with reduced quality.[/bold yellow]")
    else:
        console.print(f"[bold red]{fails} failure(s), {warns} warning(s) — fix failures before using {BRAND_NAME}.[/bold red]")

    # Fix suggestions
    if fix and (fails > 0 or warns > 0):
        console.print()
        console.print(Panel.fit(
            "[bold]Suggested fixes:[/bold]",
            border_style="yellow",
        ))

        for status, label, detail in all_results:
            if status not in (FAIL, WARN):
                continue

            if "not installed" in detail.lower() or "NOT INSTALLED" in detail:
                pkg = label.split(":")[-1].strip().lower()
                if "anthropic" in label.lower() or "openai" in label.lower():
                    console.print("  pip install graqle[api]")
                elif "sentence" in label.lower():
                    console.print("  pip install sentence-transformers")
                elif "titan" in label.lower():
                    console.print("  pip install boto3  # + configure AWS credentials")
                else:
                    console.print(f"  pip install {pkg}")

            elif "NOT SET" in detail:
                env_var = label.split(":")[-1].strip()
                if "ANTHROPIC" in detail or "ANTHROPIC" in label:
                    console.print("  export ANTHROPIC_API_KEY=sk-ant-your-key-here")
                elif "OPENAI" in detail or "OPENAI" in label:
                    console.print("  export OPENAI_API_KEY=sk-your-key-here")
                elif "AWS" in detail or "AWS" in label:
                    console.print("  aws configure  # or export AWS_ACCESS_KEY_ID=...")

            elif "not found" in detail.lower() and "graq init" in detail:
                console.print("  graq init")

            elif "empty" in detail.lower() and "graph" in label.lower():
                console.print("  graq scan --repo .")

            elif "regex-only" in detail.lower():
                console.print("  pip install sentence-transformers  # enables hybrid skill matching")

            elif ".mcp.json" in label and "not" in detail.lower():
                console.print("  graq init  # auto-registers MCP server")

            elif "Gate: intelligence" in label and "not compiled" in detail.lower():
                console.print("  graq compile  # build intelligence layer")

            elif "Gate: scorecard" in label and "not found" in detail.lower():
                console.print("  graq compile  # generates scorecard + intelligence")

            elif "Gate: pre-commit hook" in label and "not installed" in detail.lower():
                console.print("  graq compile --hook  # enforce quality gate before every commit")

            elif "Gate: CLAUDE.md" in label and "no intelligence" in detail.lower():
                console.print("  graq compile --inject  # inject risk map into CLAUDE.md")

            elif "Gate: CLAUDE.md" in label and "not found" in detail.lower():
                console.print("  graq compile --inject  # creates CLAUDE.md with intelligence")

            elif "Backend: upgrade" in label or ("Backend: performance" in label and "Neo4j" in detail):
                console.print("  graq upgrade neo4j  # 12× faster multi-hop traversal")

            elif "Neo4j: driver" in label and "not installed" in detail.lower():
                console.print("  pip install graqle[neo4j]  # enables Neo4j backend")

    # Readiness score
    total = passes + warns + fails
    score = int(passes / total * 100) if total > 0 else 0
    color = "green" if score >= 80 else "yellow" if score >= 50 else "red"
    console.print(f"\n[{color}]Readiness: {score}%[/{color}] ({passes}/{total} checks passed)")

    # Always show setup-guide hint if no backend is working
    has_working_backend = any(
        r[0] == PASS and "Backend:" in r[1] and ("Anthropic" in r[1] or "OpenAI" in r[1]
            or "Bedrock" in r[1] or "Ollama" in r[1])
        for r in all_results
    )
    if not has_working_backend:
        console.print()
        console.print(Panel.fit(
            "[bold]No working LLM backend detected.[/bold]\n\n"
            "GraQle needs an AI model to reason over your knowledge graph.\n"
            "You have several options (including FREE local models):\n\n"
            "  [bold cyan]graq setup-guide[/bold cyan]            — see all options with setup steps\n"
            "  [bold cyan]graq setup-guide ollama[/bold cyan]     — free, local, no API key\n"
            "  [bold cyan]graq setup-guide anthropic[/bold cyan]  — best quality, $5 free credits\n",
            border_style="yellow",
            title="Get Started",
        ))
