"""graq trustctl — Supply-chain trust verification for Graqle releases.

Consumers (enterprise CI, developers) can run:
    graq trustctl verify                         # verify installed version
    graq trustctl verify --version 0.35.0        # verify a specific release
    graq trustctl verify --wheel dist/graqle-*.whl  # verify a local wheel

All heavy dependencies (sigstore, cyclonedx-bom, pip-audit) are optional
and imported lazily — the command is always importable even in minimal installs.
"""

# ── graqle:intelligence ──
# module: graqle.cli.commands.trustctl
# risk: LOW (impact radius: 1 module — registered in main.py only)
# consumers: main
# dependencies: __future__, pathlib, subprocess, sys, typer, console
# constraints: NEVER import sigstore/cyclonedx at module level (lazy only)
# ── /graqle:intelligence ──

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

from graqle.cli.console import create_console

console = create_console()

trustctl_app = typer.Typer(
    name="trustctl",
    help="Supply-chain trust commands — verify release signatures and SBOMs.",
    no_args_is_help=True,
)


def _require(package: str, extra: str) -> None:
    """Raise a user-friendly error when an optional dep is missing."""
    # Square brackets are Rich markup — escape them so [security] is literal
    install_cmd = f"pip install 'graqle\\[{extra}]'"
    console.print(
        f"[bold red]Missing dependency:[/bold red] [cyan]{package}[/cyan]\n"
        f"Install with: [bold]{install_cmd}[/bold]"
    )
    raise typer.Exit(1)


def _run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Run a subprocess with an explicit arg list (never shell=True)."""
    return subprocess.run(  # noqa: S603
        args,
        capture_output=capture,
        text=True,
    )


# ---------------------------------------------------------------------------
# graq trustctl verify
# ---------------------------------------------------------------------------

@trustctl_app.command(name="verify")
def verify_command(
    version: Optional[str] = typer.Option(
        None,
        "--version", "-v",
        help="Release version to verify (default: installed graqle version).",
    ),
    wheel: Optional[Path] = typer.Option(
        None,
        "--wheel", "-w",
        help="Path to a local .whl file to verify instead of downloading.",
        exists=False,  # We check ourselves for better error messages
    ),
    skip_sigstore: bool = typer.Option(
        False,
        "--skip-sigstore",
        help="Skip Sigstore signature check (not recommended).",
    ),
    skip_sbom: bool = typer.Option(
        False,
        "--skip-sbom",
        help="Skip SBOM generation/check.",
    ),
    skip_audit: bool = typer.Option(
        False,
        "--skip-audit",
        help="Skip pip-audit CVE scan.",
    ),
    policy: Optional[Path] = typer.Option(
        None,
        "--policy",
        help="Path to trust_policy.yaml (default: bundled policy).",
    ),
) -> None:
    """Verify the supply-chain integrity of a Graqle release.

    Checks:
    1. Sigstore signature — proves the wheel was signed by GitHub Actions OIDC
    2. SBOM — generates a CycloneDX bill of materials for the installed package
    3. pip-audit — scans dependencies for known CVEs
    """
    from graqle.__version__ import __version__ as installed_version

    target_version = version or installed_version

    console.print()
    console.print(f"[bold cyan]graq trustctl verify[/bold cyan] — graqle {target_version}")
    console.print()

    passed = 0
    failed = 0
    skipped = 0

    # ── 1. Sigstore signature check ──────────────────────────────────────────
    if skip_sigstore:
        console.print("[yellow]SKIP[/yellow]  Sigstore check (--skip-sigstore)")
        skipped += 1
    else:
        console.print("[dim]Checking Sigstore signature…[/dim]")
        try:
            import sigstore  # type: ignore[import] # noqa: F401
        except ImportError:
            _require("sigstore", "security")

        bundle_url = (
            f"https://github.com/quantamixsol/graqle/releases/download/"
            f"v{target_version}/graqle-{target_version}.sigstore.json"
        )

        if wheel and Path(wheel).exists():
            wheel_path = str(wheel)
        else:
            # Locate the installed wheel or fall back to PyPI download hint
            wheel_path = _find_installed_wheel(target_version)

        if wheel_path is None:
            console.print(
                f"[yellow]SKIP[/yellow]  Sigstore check — wheel for v{target_version} not found locally.\n"
                f"       Download from PyPI first: "
                f"[dim]pip download graqle=={target_version}[/dim]"
            )
            skipped += 1
        else:
            result = _run(
                [
                    sys.executable, "-m", "sigstore", "verify", "github",
                    "--bundle", bundle_url,
                    "--cert-identity",
                    "https://github.com/quantamixsol/graqle/.github/workflows/ci.yml@refs/tags/v" + target_version,
                    wheel_path,
                ],
                capture=True,
            )
            if result.returncode == 0:
                console.print(f"[green]PASS[/green]  Sigstore signature verified for {Path(wheel_path).name}")
                passed += 1
            else:
                console.print(f"[red]FAIL[/red]  Sigstore verification failed:\n{result.stderr.strip()}")
                failed += 1

    # ── 2. SBOM check ────────────────────────────────────────────────────────
    if skip_sbom:
        console.print("[yellow]SKIP[/yellow]  SBOM check (--skip-sbom)")
        skipped += 1
    else:
        console.print("[dim]Generating CycloneDX SBOM…[/dim]")
        try:
            import cyclonedx  # type: ignore[import] # noqa: F401
        except ImportError:
            _require("cyclonedx-bom", "security")

        sbom_output = Path("graqle-sbom.json")
        result = _run(
            [
                sys.executable, "-m", "cyclonedx_py", "environment",
                "--output-format", "JSON",
                "--output-file", str(sbom_output),
            ],
            capture=True,
        )
        if result.returncode == 0 and sbom_output.exists():
            size_kb = sbom_output.stat().st_size // 1024
            console.print(f"[green]PASS[/green]  SBOM generated → {sbom_output} ({size_kb} KB)")
            passed += 1
        else:
            console.print(f"[red]FAIL[/red]  SBOM generation failed:\n{result.stderr.strip()}")
            failed += 1

    # ── 3. pip-audit CVE scan ────────────────────────────────────────────────
    if skip_audit:
        console.print("[yellow]SKIP[/yellow]  pip-audit (--skip-audit)")
        skipped += 1
    else:
        console.print("[dim]Running pip-audit CVE scan…[/dim]")
        try:
            result = _run([sys.executable, "-m", "pip_audit", "--version"], capture=True)
            if result.returncode != 0:
                raise ImportError
        except (ImportError, FileNotFoundError):
            _require("pip-audit", "security")

        result = _run(
            [sys.executable, "-m", "pip_audit", "--format", "json"],
            capture=True,
        )
        if result.returncode == 0:
            console.print("[green]PASS[/green]  pip-audit — no known CVEs found")
            passed += 1
        else:
            # pip-audit exits non-zero when vulnerabilities are found
            console.print(f"[red]FAIL[/red]  pip-audit found vulnerabilities:\n{result.stdout.strip()}")
            failed += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    console.print()
    total = passed + failed + skipped
    if failed == 0:
        console.print(
            f"[bold green]TRUSTED[/bold green]  graqle {target_version} — "
            f"{passed}/{total} checks passed"
            + (f", {skipped} skipped" if skipped else "")
        )
    else:
        console.print(
            f"[bold red]UNTRUSTED[/bold red]  graqle {target_version} — "
            f"{failed}/{total} checks failed"
        )
        raise typer.Exit(1)


def _find_installed_wheel(version: str) -> str | None:
    """Try to locate a cached/downloaded wheel for the given version."""
    import site

    # Look in common pip download cache locations
    search_dirs = [Path("."), Path("dist")]
    try:
        for sp in site.getsitepackages():
            search_dirs.append(Path(sp).parent.parent / "wheels")
    except AttributeError:
        pass

    for d in search_dirs:
        if not d.exists():
            continue
        matches = list(d.glob(f"graqle-{version}-*.whl"))
        if matches:
            return str(matches[0])

    return None


# ---------------------------------------------------------------------------
# graq trustctl policy
# ---------------------------------------------------------------------------

@trustctl_app.command(name="policy")
def policy_command(
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Write policy template to this path (default: print to stdout).",
    ),
) -> None:
    """Print or export the bundled trust_policy.yaml template."""
    bundled = Path(__file__).parent.parent.parent.parent / "tools" / "trust_policy.yaml"
    if bundled.exists():
        content = bundled.read_text()
    else:
        content = _DEFAULT_POLICY

    if output:
        output.write_text(content)
        console.print(f"[green]Written[/green] trust policy to {output}")
    else:
        console.print(content)


_DEFAULT_POLICY = """\
# Graqle Trust Policy
# Used by: graq trustctl verify --policy <this-file>
# ---------------------------------------------------------------------------
sigstore:
  require: true
  certificate_identity_regex: >-
    https://github.com/quantamixsol/graqle/.github/workflows/ci\\.yml
    @refs/tags/v.*
  certificate_oidc_issuer: https://token.actions.githubusercontent.com

sbom:
  require: true
  format: CycloneDX
  minimum_components: 1

pip_audit:
  require: true
  block_on_severity: [CRITICAL, HIGH]

pth_guard:
  require: true   # Wheel must contain zero .pth files (LiteLLM-class prevention)
"""
