"""
WS-F Trade-Secret Wheel Gate
=============================
Layer 3 IP protection gate: builds the Community graqle wheel and inspects
its RECORD manifest. Fails (exit 1) if any calibration-internal module paths
appear in the wheel, which would mean trade-secret implementation details
shipped to PyPI.

Complements (does NOT duplicate):
  - ip_gate.yml        -> scans PR diff lines for TS-1..4 literal values
  - ip_content_scan.py -> scans docs/text for IP meta-disclosure

This gate's scope: WHEEL MANIFEST only (what actually ships to end users).

Usage
-----
  # CI (build + scan):
  python scripts/ci/trade_secret_wheel_gate.py

  # Local testing with a pre-built wheel:
  python scripts/ci/trade_secret_wheel_gate.py --wheel dist/graqle-*.whl

  # Dry-run (skip build, accept explicit --wheel path):
  python scripts/ci/trade_secret_wheel_gate.py --dry-run --wheel /tmp/my.whl
"""

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Deny list -- module stem prefixes that must NEVER appear in the Community
# wheel. These are module-path strings (safe to name here), NOT TS-1..4
# literal values. Matching is done on the normalised stem so that compiled
# variants (.pyc, .so, .pyd) are caught alongside the source .py file.
# ---------------------------------------------------------------------------
_DENY_LIST: frozenset[str] = frozenset([
    "graqle/governance/calibration.py",
    "graqle/governance/calibration_store.py",
])

# Stems derived automatically from _DENY_LIST — do NOT maintain manually.
# Used for compiled-artifact matching (.cpython-311.pyc, .so, .pyd variants).
_DENY_STEMS: frozenset[str] = frozenset(
    p.rsplit(".", 1)[0] for p in _DENY_LIST
)

# ---------------------------------------------------------------------------
# MONETISATION WHEEL BOUNDARY (owner rule, 2026-07-26)
# ---------------------------------------------------------------------------
# The Community wheel that ships to PyPI must be able to VERIFY entitlements and
# ENFORCE caps, but must NEVER carry the licence signer or the server-side plan/
# issuer logic. This is a MONETISATION-integrity check, distinct from the TS
# calibration check above — it runs in the same release gate so a boundary
# regression fails the PyPI build. (Module-path strings only; no TS values.)

# MUST be present in the Community wheel — the client-side monetisation enforcers
# + offline verifier. If any goes missing, the shipped SDK cannot meter/gate/verify
# entitlements → silent revenue loss.
_MONETISATION_MUST_SHIP: frozenset[str] = frozenset([
    "graqle/licensing/limits.py",           # node-cap ladder (Free 1,000, Pro/Team unlimited)
    "graqle/licensing/meter.py",            # usage meter
    "graqle/licensing/manager.py",          # licence load + verify
    "graqle/licensing/ed25519_license.py",  # ed25519 offline verify
    "graqle/licensing/trusted_keys.json",   # PUBLIC verification key
    "graqle/guardian/tier.py",              # PR-Guardian HARD wall (W2)
])

# MUST NOT ship — server-side commercial code + the licence SIGNER. A leak here
# means the public wheel could forge licences or expose the proprietary plan/issuer.
_MONETISATION_MUST_NOT_SHIP_PREFIXES: tuple[str, ...] = (
    "graqle/cloud/",    # cloud/plans.py etc — server-side plan logic (B0's file)
    "graqle/server/",   # stripe_webhook issuer, register routes
    "graqle/leads/",
    "graqle/studio/",
)
_MONETISATION_MUST_NOT_SHIP_EXACT: frozenset[str] = frozenset([
    "graqle/licensing/keygen.py",   # the SIGNER — verify-only wheel, never issue
])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_wheel(outdir: Path) -> Path:
    """Build the graqle wheel into outdir; return path to the .whl file."""
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[wsf-gate] Building wheel -> {outdir}")
    repo_root = Path(__file__).parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir), "."],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        print("[wsf-gate] BUILD FAILED:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(2)

    wheels = list(outdir.glob("*.whl"))
    if not wheels:
        print("[wsf-gate] ERROR: no .whl file found after build")
        sys.exit(2)
    return wheels[0]


def _scan_wheel(whl_path: Path) -> list[str]:
    """Return list of deny-list violations found in the wheel RECORD."""
    violations: list[str] = []
    with zipfile.ZipFile(whl_path, "r") as zf:
        # Zip Slip guard: reject any zip entry with absolute paths or traversal.
        for entry in zf.namelist():
            norm_entry = entry.replace("\\", "/")
            if norm_entry.startswith("/") or ".." in norm_entry.split("/"):
                print(f"[wsf-gate] ERROR: unsafe zip entry rejected: {entry!r}")
                sys.exit(2)

        # Find the RECORD file (lives at <pkg>-<ver>.dist-info/RECORD)
        record_name = next(
            (n for n in zf.namelist() if n.endswith(".dist-info/RECORD")),
            None,
        )
        if record_name is None:
            print("[wsf-gate] ERROR: RECORD file not found in wheel")
            sys.exit(2)

        record_text = zf.read(record_name).decode("utf-8", errors="replace")

    checked = 0
    for line in record_text.splitlines():
        # RECORD format: path,hash,size  (path is always first)
        path = line.split(",")[0].strip()
        if not path:
            continue
        checked += 1
        norm = path.replace("\\", "/")
        # Exact match (.py source file in wheel)
        if norm in _DENY_LIST:
            violations.append(path)
            continue
        # Stem match: catches compiled variants (.cpython-311.pyc, .so, .pyd).
        # Strip from the FIRST dot in the filename (after last slash) so that
        # "calibration.cpython-311-x86_64.so" -> "graqle/governance/calibration".
        last_slash = norm.rfind("/")
        fname = norm[last_slash + 1:]
        first_dot = fname.find(".")
        norm_stem = norm[: last_slash + 1 + first_dot] if first_dot != -1 else norm
        if norm_stem in _DENY_STEMS:
            violations.append(path)

    print(f"[wsf-gate] Scanned {checked} RECORD entries in {whl_path.name}")
    return violations


def _wheel_record_paths(whl_path: Path) -> set[str]:
    """Return the set of posix-normalised package paths in the wheel RECORD."""
    with zipfile.ZipFile(whl_path, "r") as zf:
        record_name = next(
            (n for n in zf.namelist() if n.endswith(".dist-info/RECORD")), None
        )
        if record_name is None:
            print("[wsf-gate] ERROR: RECORD file not found in wheel")
            sys.exit(2)
        record_text = zf.read(record_name).decode("utf-8", errors="replace")
    paths: set[str] = set()
    for line in record_text.splitlines():
        p = line.split(",")[0].strip()
        if p:
            paths.add(p.replace("\\", "/"))
    return paths


def _scan_monetisation_boundary(whl_path: Path) -> list[str]:
    """Return monetisation-boundary violations in the wheel.

    Two failure classes (owner rule):
      - a client-side ENFORCER is MISSING (silent revenue loss), or
      - a server-side/signer module LEAKED into the public wheel.
    """
    paths = _wheel_record_paths(whl_path)
    violations: list[str] = []

    for must in sorted(_MONETISATION_MUST_SHIP):
        if must not in paths:
            violations.append(f"MISSING ENFORCER: {must}")

    for p in sorted(paths):
        if any(p.startswith(pre) for pre in _MONETISATION_MUST_NOT_SHIP_PREFIXES):
            violations.append(f"LEAKED SERVER-SIDE: {p}")

    for exact in sorted(_MONETISATION_MUST_NOT_SHIP_EXACT):
        stem = exact.rsplit(".", 1)[0]
        for p in sorted(paths):
            if p == exact or p.startswith(stem + "."):
                violations.append(f"LEAKED SIGNER: {p}")

    return violations


def _report_monetisation(violations: list[str], *, dry_run: bool = False) -> None:
    """Print monetisation-boundary results; exit 1 on violations (unless dry-run)."""
    if violations:
        print()
        print("[mon-gate] FAIL -- monetisation wheel boundary violated:")
        for v in violations:
            print(f"  {v}")
            print(f"  {v}", file=sys.stderr)
        print()
        print(
            "[mon-gate] Fix: enforcers must ship; server-side/signer modules must be "
            "excluded in [tool.hatch.build.targets.wheel] exclude in pyproject.toml"
        )
        if dry_run:
            print("[mon-gate] (dry-run: exit 0 despite violations)")
            return
        sys.exit(1)
    print("[mon-gate] PASS -- monetisation boundary intact "
          f"({len(_MONETISATION_MUST_SHIP)} enforcers present; server-side/signer absent)")


def _report(violations: list[str], *, dry_run: bool = False) -> None:
    """Print results and exit.

    dry_run=True: print any violations found but always exit 0 (inspection
    mode — lets engineers audit a wheel without failing the pipeline).
    """
    if violations:
        print()
        print("[wsf-gate] FAIL -- trade-secret modules detected in wheel:")
        for v in violations:
            # Use repr() to prevent ANSI escape injection from crafted RECORD paths.
            print(f"  VIOLATION: {v!r}")
            print(f"  VIOLATION: {v!r}", file=sys.stderr)
        print()
        print(
            "[wsf-gate] Fix: add the violating path(s) to "
            "[tool.hatch.build.targets.wheel] exclude in pyproject.toml"
        )
        if dry_run:
            print("[wsf-gate] (dry-run: exit 0 despite violations)")
            sys.exit(0)
        sys.exit(1)
    else:
        print("[wsf-gate] PASS -- no trade-secret calibration modules in wheel")
        print(f"[wsf-gate] Deny list checked ({len(_DENY_LIST)} entries): {sorted(_DENY_LIST)}")
        sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WS-F: fail build if calibration internals ship in Community wheel"
    )
    parser.add_argument(
        "--wheel",
        metavar="PATH",
        help="Path to a pre-built .whl file (skips build step)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect violations but exit 0 — does not fail the build. Requires --wheel PATH.",
    )
    parser.add_argument(
        "--check-monetisation",
        action="store_true",
        help="Also assert the monetisation wheel boundary (enforcers present + no "
             "server-side/signer leak). Enabled in release CI on a real full build; "
             "off by default so isolated TS-gate tests on synthetic wheels are unaffected.",
    )
    args = parser.parse_args()

    if args.dry_run and not args.wheel:
        parser.error("--dry-run requires --wheel PATH")

    def _run_gates(whl_path: Path) -> None:
        # Monetisation boundary (owner rule): enforcers present + no server-side/signer
        # leak. Opt-in via --check-monetisation (release CI on a REAL full build) so the
        # TS gate's isolated unit tests on synthetic partial wheels are unaffected. Runs
        # in the same release gate so a boundary regression fails the PyPI build. In
        # non-dry-run it exits 1 on failure; otherwise prints and returns.
        if args.check_monetisation:
            mon = _scan_monetisation_boundary(whl_path)
            _report_monetisation(mon, dry_run=args.dry_run)
        # Trade-secret calibration gate (existing behaviour, unchanged).
        violations = _scan_wheel(whl_path)
        _report(violations, dry_run=args.dry_run)

    if args.wheel:
        whl_path = Path(args.wheel).resolve()
        if not whl_path.exists():
            print(f"[wsf-gate] ERROR: wheel not found: {whl_path!r}")
            sys.exit(2)
        print(f"[wsf-gate] Using pre-built wheel: {whl_path}")
        _run_gates(whl_path)
    else:
        with tempfile.TemporaryDirectory(prefix="wsf_wheel_") as tmp:
            whl_path = _build_wheel(Path(tmp))
            _run_gates(whl_path)


if __name__ == "__main__":
    main()
