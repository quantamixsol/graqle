"""graq setup-guide — interactive setup guide for new users.

Shows all LLM backend options with clear quality tiers, pricing,
step-by-step API key instructions, and what each tier unlocks.
Designed to eliminate every "how do I set this up?" question.
"""

from __future__ import annotations

import os
import importlib

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

console = Console()


# ---------------------------------------------------------------------------
# Backend tier definitions
# ---------------------------------------------------------------------------

TIERS = [
    {
        "tier": "FREE",
        "name": "Ollama (Local GPU/CPU)",
        "quality": "Good",
        "stars": "***",
        "cost": "$0 — runs on your machine",
        "speed": "Fast (local)",
        "best_for": "Privacy-first, no API keys, offline usage, experimentation",
        "skill_quality": "Hybrid (regex + local embeddings)",
        "reasoning_quality": "Good with 7B+ models, basic with smaller models",
        "models": "qwen2.5:3b (fast), llama3.1:8b (balanced), codellama:34b (best)",
        "setup": [
            "1. Install Ollama: https://ollama.com/download",
            "2. Pull a model:",
            "   ollama pull qwen2.5:3b      # fast, 2GB",
            "   ollama pull llama3.1:8b      # balanced, 5GB",
            "3. Start Ollama (runs in background):",
            "   ollama serve",
            "4. Initialize Graqle:",
            "   graq init --backend ollama --model qwen2.5:3b --no-interactive",
            "",
            "No API key needed. No data leaves your machine.",
        ],
        "env_var": None,
        "package": "httpx",
        "warning": None,
    },
    {
        "tier": "STARTER",
        "name": "Anthropic (Claude)",
        "quality": "Excellent",
        "stars": "*****",
        "cost": "$5 free credits on signup, then ~$0.001-0.01/query",
        "speed": "Fast (API)",
        "best_for": "Best reasoning quality, code analysis, production use",
        "skill_quality": "Hybrid (regex + Titan V2 or local embeddings)",
        "reasoning_quality": "Excellent — Claude models are top-tier for code reasoning",
        "models": "claude-haiku-4-5-20251001 ($0.001/q), claude-sonnet-4-6 ($0.01/q)",
        "setup": [
            "1. Create account: https://console.anthropic.com/",
            "2. Go to API Keys: https://console.anthropic.com/settings/keys",
            "3. Click 'Create Key' -> copy the key (starts with sk-ant-)",
            "4. Set the environment variable:",
            "",
            "   # Linux/Mac:",
            '   echo \'export ANTHROPIC_API_KEY="sk-ant-your-key-here"\' >> ~/.bashrc',
            "   source ~/.bashrc",
            "",
            "   # Windows (PowerShell):",
            '   [System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-your-key-here", "User")',
            "   # Restart your terminal after setting",
            "",
            "   # Windows (CMD):",
            '   setx ANTHROPIC_API_KEY "sk-ant-your-key-here"',
            "",
            "5. Initialize Graqle:",
            "   graq init --backend anthropic --model claude-haiku-4-5-20251001 --no-interactive",
            "",
            "Free tier: $5 credits, enough for ~5,000 queries with Haiku.",
            "Haiku is recommended for Graqle — fast, cheap, great for code.",
        ],
        "env_var": "ANTHROPIC_API_KEY",
        "package": "anthropic",
        "warning": None,
    },
    {
        "tier": "STARTER",
        "name": "OpenAI (GPT)",
        "quality": "Very Good",
        "stars": "****",
        "cost": "$5 free credits on signup, then ~$0.001-0.03/query",
        "speed": "Fast (API)",
        "best_for": "GPT ecosystem familiarity, function calling, broad model selection",
        "skill_quality": "Hybrid (regex + local embeddings)",
        "reasoning_quality": "Very good — GPT-4o-mini is cost-effective, GPT-4o for premium",
        "models": "gpt-4o-mini ($0.001/q), gpt-4o ($0.03/q), o3-mini ($0.01/q)",
        "setup": [
            "1. Create account: https://platform.openai.com/signup",
            "2. Go to API Keys: https://platform.openai.com/api-keys",
            "3. Click 'Create new secret key' -> copy (starts with sk-)",
            "4. Set the environment variable:",
            "",
            "   # Linux/Mac:",
            '   echo \'export OPENAI_API_KEY="sk-your-key-here"\' >> ~/.bashrc',
            "   source ~/.bashrc",
            "",
            "   # Windows (PowerShell):",
            '   [System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-your-key-here", "User")',
            "   # Restart your terminal after setting",
            "",
            "   # Windows (CMD):",
            '   setx OPENAI_API_KEY "sk-your-key-here"',
            "",
            "5. Initialize Graqle:",
            "   graq init --backend openai --model gpt-4o-mini --no-interactive",
            "",
            "Free tier: $5 credits (requires adding payment method first).",
        ],
        "env_var": "OPENAI_API_KEY",
        "package": "openai",
        "warning": "OpenAI requires a payment method even for free credits.",
    },
    {
        "tier": "PRO",
        "name": "AWS Bedrock (Claude/Titan/Llama)",
        "quality": "Excellent",
        "stars": "*****",
        "cost": "AWS Free Tier eligible, then pay-per-use (~$0.001-0.01/query)",
        "speed": "Fast (API, same region as your infra)",
        "best_for": "Enterprise, AWS-native, Titan V2 embeddings, multi-model access",
        "skill_quality": "Best — Titan V2 embeddings (1024-dim) for skill matching",
        "reasoning_quality": "Excellent — same Claude models, plus Llama, Mistral, Titan",
        "models": "anthropic.claude-3-5-haiku-20241022-v1:0, amazon.titan-embed-text-v2:0",
        "setup": [
            "1. Create AWS account: https://aws.amazon.com/free/",
            "2. Enable Bedrock model access:",
            "   - Go to: https://console.aws.amazon.com/bedrock/",
            "   - Select your region (e.g., us-east-1 or eu-central-1)",
            "   - Click 'Model access' -> 'Manage model access'",
            "   - Enable: Anthropic Claude, Amazon Titan Text Embeddings V2",
            "   - Wait ~5 minutes for approval",
            "3. Configure AWS credentials:",
            "",
            "   # Option A: AWS CLI (recommended)",
            "   pip install awscli",
            "   aws configure",
            "   # Enter: Access Key ID, Secret Access Key, Region (eu-central-1)",
            "",
            "   # Option B: Environment variables",
            "   export AWS_ACCESS_KEY_ID=AKIA...",
            "   export AWS_SECRET_ACCESS_KEY=...",
            "   export AWS_DEFAULT_REGION=eu-central-1",
            "",
            "4. Initialize Graqle:",
            "   graq init --backend bedrock --model anthropic.claude-3-5-haiku-20241022-v1:0 --no-interactive",
            "",
            "AWS Free Tier: 12 months free for new accounts.",
            "Bedrock has NO upfront cost — pure pay-per-use.",
            "BONUS: Enables Titan V2 embeddings for best skill matching quality.",
        ],
        "env_var": "AWS_ACCESS_KEY_ID",
        "package": "boto3",
        "warning": "Bedrock model access must be explicitly enabled per region.",
    },
]


# ---------------------------------------------------------------------------
# Quality comparison table
# ---------------------------------------------------------------------------

QUALITY_COMPARISON = """
## What You Get at Each Tier

| Feature | Ollama (Free) | Anthropic/OpenAI | Bedrock (Pro) |
|---------|:---:|:---:|:---:|
| Graph reasoning | Yes | Yes | Yes |
| Code scanning | Yes | Yes | Yes |
| Skill assignment (regex) | Yes | Yes | Yes |
| Skill assignment (semantic) | Yes* | Yes* | **Best** (Titan V2) |
| Reasoning quality | Good | **Excellent** | **Excellent** |
| Ontology generation | No | Yes | Yes |
| Debate protocol | Yes | Yes | Yes |
| MCP/Claude Code integration | Yes | Yes | Yes |
| Data privacy | **Best** (local) | Cloud API | Cloud API |
| Offline usage | **Yes** | No | No |
| Cost | **$0** | ~$0.001/query | ~$0.001/query |

*Uses sentence-transformers (included in base install, 384-dim).
Titan V2 (1024-dim) is available only with AWS Bedrock credentials.

## Recommendation

- **Just trying it out?** -> Ollama (zero cost, zero config)
- **Building real projects?** -> Anthropic Claude Haiku ($5 free credits)
- **Enterprise / AWS shop?** -> Bedrock (Titan V2 embeddings + Claude)
"""


def setup_guide_command(
    backend: str = typer.Argument(
        None,
        help="Show setup for a specific backend: ollama, anthropic, openai, bedrock",
    ),
) -> None:
    """Step-by-step setup guide for Graqle backends.

    Shows all available LLM options with quality ratings, pricing,
    and exact commands to get each API key configured.

    \b
    Examples:
        graq setup-guide              (show all options)
        graq setup-guide anthropic    (show Anthropic setup only)
        graq setup-guide ollama       (show Ollama setup only)
    """
    from graqle.__version__ import __version__

    console.print(Panel.fit(
        f"[bold cyan]Graqle Setup Guide[/bold cyan] v{__version__}\n"
        "Choose your AI backend for graph reasoning",
        border_style="cyan",
    ))

    # If specific backend requested, show just that one
    if backend:
        backend_lower = backend.lower()
        matched = [t for t in TIERS if backend_lower in t["name"].lower()]
        if not matched:
            console.print(f"[red]Unknown backend '{backend}'. Choose: ollama, anthropic, openai, bedrock[/red]")
            raise typer.Exit(1)
        for tier in matched:
            _print_tier_detail(tier)
        return

    # Show overview table first
    console.print()
    _print_overview_table()

    # Show quality comparison
    console.print()
    console.print(Markdown(QUALITY_COMPARISON))

    # Show detailed setup for each tier
    console.print()
    console.print(Panel.fit(
        "[bold]Detailed Setup Instructions[/bold]\n"
        "Follow the steps for your chosen backend below.",
        border_style="green",
    ))

    for tier in TIERS:
        _print_tier_detail(tier)

    # Final note
    console.print()
    console.print(Panel.fit(
        "[bold]After setup, verify with:[/bold]\n\n"
        "  graq doctor          # check everything is working\n"
        "  graq init            # initialize your project\n"
        "  graq run \"query\"   # test a reasoning query\n\n"
        "[dim]Need help? https://github.com/quantamixsol/graqle/issues[/dim]",
        border_style="cyan",
    ))


def _print_overview_table() -> None:
    """Print the backend comparison table with auto-detection."""
    table = Table(
        title="Backend Options",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Tier", style="bold", width=8)
    table.add_column("Backend", min_width=25)
    table.add_column("Quality", width=10)
    table.add_column("Cost", min_width=20)
    table.add_column("Your Status", min_width=20)

    for tier in TIERS:
        # Auto-detect status
        status = _detect_status(tier)
        table.add_row(
            tier["tier"],
            tier["name"],
            tier["stars"],
            tier["cost"].split(",")[0],  # first part only
            status,
        )

    console.print(table)


def _detect_status(tier: dict) -> str:
    """Detect if a backend is ready, installed, or needs setup."""
    pkg = tier.get("package")
    env_var = tier.get("env_var")

    # Check package
    pkg_ok = True
    if pkg:
        try:
            importlib.import_module(pkg)
        except ImportError:
            pkg_ok = False

    # Check env var / credentials
    key_ok = True
    if env_var:
        key_ok = bool(os.environ.get(env_var))

    # Special case: Ollama — check if server is running
    if "ollama" in tier["name"].lower() and pkg_ok:
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=2)
            if r.status_code == 200:
                models = r.json().get("models", [])
                if models:
                    names = [m.get("name", "?") for m in models[:3]]
                    return f"[green]READY[/green] ({', '.join(names)})"
                return "[yellow]running, no models[/yellow] (ollama pull qwen2.5:3b)"
        except Exception:
            if pkg_ok:
                return "[yellow]installed, not running[/yellow] (ollama serve)"
            return "[dim]not installed[/dim]"

    # Special case: Bedrock — check AWS credentials
    if "bedrock" in tier["name"].lower() and pkg_ok:
        try:
            import boto3
            sts = boto3.client("sts")
            identity = sts.get_caller_identity()
            account = identity.get("Account", "?")
            return f"[green]READY[/green] (AWS account: ...{account[-4:]})"
        except Exception:
            return "[yellow]boto3 installed, need credentials[/yellow]"

    if pkg_ok and key_ok:
        return "[green]READY[/green]"
    elif pkg_ok and not key_ok:
        return f"[yellow]need {env_var}[/yellow]"
    elif not pkg_ok:
        return f"[dim]pip install graqle[api][/dim]"
    return "[dim]not configured[/dim]"


def _print_tier_detail(tier: dict) -> None:
    """Print detailed setup instructions for one backend tier."""
    # Detect current status
    status = _detect_status(tier)

    # Build header
    header = (
        f"[bold]{tier['name']}[/bold] [{tier['tier']}]\n"
        f"Quality: {tier['stars']} | Cost: {tier['cost']}\n"
        f"Status: {status}"
    )

    if tier.get("warning"):
        header += f"\n[yellow]Note: {tier['warning']}[/yellow]"

    # Build body
    body_parts = [
        f"[bold]Best for:[/bold] {tier['best_for']}",
        f"[bold]Models:[/bold] {tier['models']}",
        f"[bold]Reasoning:[/bold] {tier['reasoning_quality']}",
        f"[bold]Skills:[/bold] {tier['skill_quality']}",
        "",
        "[bold]Setup steps:[/bold]",
    ]
    body_parts.extend(f"  {line}" for line in tier["setup"])

    body = "\n".join(body_parts)

    # Color based on tier
    border = "green" if tier["tier"] == "FREE" else "cyan" if tier["tier"] == "STARTER" else "magenta"

    console.print()
    console.print(Panel(
        f"{header}\n\n{body}",
        border_style=border,
        title=f"{tier['tier']}: {tier['name']}",
    ))
