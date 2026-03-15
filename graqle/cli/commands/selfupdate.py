"""graq self-update — upgrade Graqle while handling MCP server lock on Windows."""

# ── graqle:intelligence ──
# module: graqle.cli.commands.selfupdate
# risk: LOW (impact radius: 2 modules)
# consumers: main, test_selfupdate
# dependencies: __future__, os, signal, subprocess, sys +3 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

console = Console()


def selfupdate_command(
    version: str = typer.Option(
        None, "--version", "-v",
        help="Specific version to install (default: latest)",
    ),
    restart_mcp: bool = typer.Option(
        True, "--restart-mcp/--no-restart-mcp",
        help="Restart MCP server after upgrade (default: yes)",
    ),
) -> None:
    """Upgrade Graqle, handling MCP server file locks on Windows.

    On Windows, running MCP servers lock the graq.exe entry point,
    preventing pip from overwriting it.  This command:

      1. Detects running MCP/serve processes
      2. Gracefully stops them
      3. Runs pip install --upgrade graqle
      4. Optionally restarts the MCP server

    \b
    Examples:
        graq self-update
        graq self-update --version 0.16.2
        graq self-update --no-restart-mcp
    """
    # Step 1: detect and stop running graq processes (Windows file lock issue)
    stopped_pids: list[int] = []
    mcp_was_running = False

    if sys.platform == "win32":
        console.print("[cyan]Checking for running Graqle processes...[/cyan]")
        stopped_pids, mcp_was_running = _stop_graq_processes()
        if stopped_pids:
            console.print(f"  Stopped {len(stopped_pids)} process(es): {stopped_pids}")
        else:
            console.print("  No running Graqle processes found.")

    # Step 2: pip upgrade
    pkg = f"graqle=={version}" if version else "graqle"
    console.print(f"[cyan]Upgrading: pip install --upgrade {pkg}[/cyan]")

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", pkg],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        console.print(f"[red]Upgrade failed:[/red]")
        console.print(result.stderr or result.stdout)
        raise typer.Exit(1)

    # Show new version
    console.print(result.stdout.strip().split("\n")[-1] if result.stdout.strip() else "")
    try:
        # Re-import to get new version
        import importlib
        import graqle.__version__
        importlib.reload(graqle.__version__)
        console.print(f"[green]Graqle upgraded to v{graqle.__version__.__version__}[/green]")
    except Exception:
        console.print("[green]Upgrade complete.[/green]")

    # Step 3: restart MCP if it was running
    if restart_mcp and mcp_was_running:
        console.print("[cyan]Restarting MCP server...[/cyan]")
        _restart_mcp_server()


def _stop_graq_processes() -> tuple[list[int], bool]:
    """Find and stop running graq/graqle processes. Returns (pids, mcp_was_running)."""
    stopped: list[int] = []
    mcp_running = False

    # Try PID file first (most reliable)
    pid_file = Path(".graqle/mcp.pid")
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            if pid != os.getpid():
                os.kill(pid, signal.SIGTERM)
                stopped.append(pid)
                mcp_running = True
                console.print(f"  Stopped MCP server (PID {pid}) via .graqle/mcp.pid")
                pid_file.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

    try:
        # Use tasklist on Windows to find graq processes
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq graq.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().split("\n"):
            if "graq" in line.lower():
                parts = line.strip('"').split('","')
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1].strip('"'))
                        if pid != os.getpid() and pid not in stopped:
                            os.kill(pid, signal.SIGTERM)
                            stopped.append(pid)
                            mcp_running = True
                    except (ValueError, OSError):
                        pass
    except Exception:
        pass

    # Also check for python processes running graqle MCP
    try:
        result = subprocess.run(
            ["wmic", "process", "where",
             "commandline like '%graqle%mcp%serve%'",
             "get", "processid"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid != os.getpid() and pid not in stopped:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        stopped.append(pid)
                        mcp_running = True
                    except OSError:
                        pass
    except Exception:
        pass

    return stopped, mcp_running


def _restart_mcp_server() -> None:
    """Restart the MCP server in background."""
    try:
        if sys.platform == "win32":
            # Use START to detach the process
            subprocess.Popen(
                ["graq", "mcp", "serve"],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["graq", "mcp", "serve"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        console.print("[green]MCP server restarted.[/green]")
    except Exception as e:
        console.print(f"[yellow]Could not restart MCP server: {e}[/yellow]")
        console.print("[yellow]Run 'graq mcp serve' manually.[/yellow]")
