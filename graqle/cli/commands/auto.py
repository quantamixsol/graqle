"""graq auto — run the autonomous loop: plan, generate, test, fix, retry."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
from pathlib import Path

import typer

from rich.markup import escape

from graqle.cli.console import create_console
from graqle.workflow.autonomous_executor import AutonomousExecutor, ExecutorConfig
from graqle.workflow.mcp_agent import McpActionAgent

console = create_console()

# Allowlist of permitted test runner executables
_PERMITTED_RUNNERS = frozenset({
    "pytest", "python", "python3", "python.exe",
    "tox", "make", "uv", "npm", "npx", "node",
})

_MAX_TASK_LENGTH = 2000


def auto_command(
    task: str = typer.Argument(..., help="Task description for the autonomous loop"),
    config: str = typer.Option("graqle.yaml", "-c", "--config", help="Config file path"),
    max_retries: int = typer.Option(3, "-r", "--max-retries", min=0, max=20, help="Max fix-retry cycles"),
    test_command: str = typer.Option(
        "python -m pytest -x -q", "--test-cmd", help="Test command"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan + generate without writing"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output"),
) -> None:
    """Run the autonomous loop: plan -> generate -> write -> test -> fix -> retry."""
    # Configure logging early so construction messages are captured
    if verbose:
        logging.getLogger("graqle").setLevel(logging.DEBUG)

    # Validate task is non-empty and sanitize
    task = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", task.strip())
    if not task:
        console.print("[red]Task cannot be empty.[/red]")
        raise typer.Exit(code=1)
    if len(task) > _MAX_TASK_LENGTH:
        console.print(f"[red]Task too long ({len(task)} chars, max {_MAX_TASK_LENGTH}).[/red]")
        raise typer.Exit(code=1)

    # Resolve config path (symlink-safe) and validate containment
    resolved_config = Path(config).resolve()
    project_root = Path.cwd().resolve()
    if not resolved_config.is_relative_to(project_root):
        console.print("[red]Config path escapes project root[/red]")
        raise typer.Exit(code=1)
    working_dir = resolved_config.parent

    # Load graph via MCP server
    # Deferred import: KogniDevServer is heavy and not needed for --help
    try:
        from graqle.plugins.mcp_dev_server import KogniDevServer
        server = KogniDevServer(config_path=str(resolved_config))
    except (FileNotFoundError, ValueError, OSError, ImportError) as exc:
        console.print(f"[red]Failed to load config: {escape(str(exc))}[/red]")
        raise typer.Exit(code=1)

    # Parse test command safely with allowlist validation
    try:
        test_cmd_parts = shlex.split(test_command)
    except ValueError as exc:
        console.print(f"[red]Invalid --test-cmd: {escape(str(exc))}[/red]")
        raise typer.Exit(code=1)
    if not test_cmd_parts:
        console.print("[red]--test-cmd cannot be empty[/red]")
        raise typer.Exit(code=1)
    # Reject paths in runner — only bare executable names allowed
    raw_runner = test_cmd_parts[0]
    if "/" in raw_runner or os.sep in raw_runner:
        console.print("[red]--test-cmd runner must be a bare executable name, not a path.[/red]")
        raise typer.Exit(code=1)
    if raw_runner not in _PERMITTED_RUNNERS:
        console.print(
            f"[red]Unsupported test runner: {escape(runner)}. "
            f"Permitted: {', '.join(sorted(_PERMITTED_RUNNERS))}[/red]"
        )
        raise typer.Exit(code=1)

    agent = McpActionAgent(server, working_dir)
    executor_config = ExecutorConfig(
        max_retries=max_retries,
        test_command=test_cmd_parts,
        working_dir=str(working_dir),
        dry_run=dry_run,
    )
    executor = AutonomousExecutor(agent, executor_config)

    console.print(f"[bold cyan]graq auto[/bold cyan] — {escape(task)}")
    console.print(f"  max_retries={max_retries}, dry_run={dry_run}")

    try:
        result = asyncio.run(executor.execute(task))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        raise typer.Exit(code=130)
    except asyncio.CancelledError:
        console.print("\n[yellow]Cancelled.[/yellow]")
        raise typer.Exit(code=130)
    except Exception as exc:
        if verbose:
            console.print_exception()
        console.print(f"[red]Executor error: {escape(str(exc))}[/red]")
        raise typer.Exit(code=1)

    if result.success:
        console.print(f"\n[bold green]SUCCESS[/bold green] after {result.attempts} attempt(s)")
        if result.modified_files:
            console.print("[bold]Modified files:[/bold]")
            for f in result.modified_files:
                console.print(f"  {escape(f)}")
    else:
        console.print(f"\n[bold red]FAILED[/bold red] after {result.attempts} attempt(s)")
        if result.error:
            console.print(f"[red]{escape(result.error)}[/red]")
        raise typer.Exit(code=1)
