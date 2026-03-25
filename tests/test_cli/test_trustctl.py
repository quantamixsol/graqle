"""Tests for graq trustctl — supply-chain trust verification command."""

# ── graqle:intelligence ──
# module: tests.test_cli.test_trustctl
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, pathlib, subprocess, unittest.mock, typer.testing, graqle.cli.main
# constraints: sigstore/cyclonedx/pip-audit are optional — tests must mock them
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from graqle.cli.main import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes so we can assert on plain text."""
    return re.sub(r"\x1b\[[0-9;]*[mGKH]", "", text)


class TestTrustctlRegistered:
    """trustctl sub-app is wired into the main CLI."""

    def test_trustctl_in_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "trustctl" in result.output

    def test_trustctl_help(self):
        result = runner.invoke(app, ["trustctl", "--help"])
        assert result.exit_code == 0
        assert "verify" in result.output
        assert "policy" in result.output

    def test_verify_help(self):
        result = runner.invoke(app, ["trustctl", "verify", "--help"])
        assert result.exit_code == 0
        # Key flags must be documented
        assert "--version" in result.output
        assert "--wheel" in result.output
        assert "--skip-sigstore" in result.output
        assert "--skip-sbom" in result.output
        assert "--skip-audit" in result.output


class TestTrustctlVerifySkipAll:
    """verify with all checks skipped exits 0 and prints nothing alarming."""

    def test_skip_all_passes(self):
        result = runner.invoke(
            app,
            ["trustctl", "verify", "--skip-sigstore", "--skip-sbom", "--skip-audit"],
        )
        # Should pass (no checks → all skipped) and exit 0
        assert result.exit_code == 0
        assert "SKIP" in result.output
        assert "TRUSTED" in result.output

    def test_skip_all_shows_version(self):
        from graqle.__version__ import __version__
        result = runner.invoke(
            app,
            ["trustctl", "verify", "--skip-sigstore", "--skip-sbom", "--skip-audit"],
        )
        assert result.exit_code == 0
        assert __version__ in _strip_ansi(result.output)


class TestTrustctlVerifySigstore:
    """Sigstore check uses lazy import and calls sigstore via subprocess."""

    def test_missing_sigstore_dep_shows_install_hint(self):
        """When sigstore is not installed, user sees install hint, not traceback."""
        with patch.dict("sys.modules", {"sigstore": None}):
            result = runner.invoke(
                app,
                ["trustctl", "verify", "--skip-sbom", "--skip-audit"],
            )
        assert result.exit_code == 1
        assert "graqle" in _strip_ansi(result.output)
        assert "security" in _strip_ansi(result.output)

    def test_sigstore_pass_on_green_subprocess(self, tmp_path):
        """When sigstore subprocess returns 0, check passes."""
        # Create a fake wheel file so _find_installed_wheel returns something
        fake_wheel = tmp_path / "graqle-0.35.0-py3-none-any.whl"
        fake_wheel.write_bytes(b"fake")

        mock_sigstore = MagicMock()  # makes `import sigstore` succeed

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stderr = ""

        with patch.dict("sys.modules", {"sigstore": mock_sigstore}), \
             patch(
                 "graqle.cli.commands.trustctl._run",
                 return_value=fake_result,
             ), \
             patch(
                 "graqle.cli.commands.trustctl._find_installed_wheel",
                 return_value=str(fake_wheel),
             ):
            result = runner.invoke(
                app,
                ["trustctl", "verify", "--version", "0.35.0",
                 "--skip-sbom", "--skip-audit"],
            )

        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "Sigstore" in result.output

    def test_sigstore_fail_on_bad_subprocess(self, tmp_path):
        """When sigstore subprocess returns non-zero, check fails."""
        fake_wheel = tmp_path / "graqle-0.35.0-py3-none-any.whl"
        fake_wheel.write_bytes(b"fake")

        mock_sigstore = MagicMock()
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stderr = "FAIL: certificate identity mismatch"

        with patch.dict("sys.modules", {"sigstore": mock_sigstore}), \
             patch(
                 "graqle.cli.commands.trustctl._run",
                 return_value=fake_result,
             ), \
             patch(
                 "graqle.cli.commands.trustctl._find_installed_wheel",
                 return_value=str(fake_wheel),
             ):
            result = runner.invoke(
                app,
                ["trustctl", "verify", "--version", "0.35.0",
                 "--skip-sbom", "--skip-audit"],
            )

        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "UNTRUSTED" in result.output


class TestTrustctlVerifySBOM:
    """SBOM check uses lazy import and calls cyclonedx_py via subprocess."""

    def test_missing_cyclonedx_dep_shows_install_hint(self):
        with patch.dict("sys.modules", {"cyclonedx": None}):
            result = runner.invoke(
                app,
                ["trustctl", "verify", "--skip-sigstore", "--skip-audit"],
            )
        assert result.exit_code == 1
        assert "graqle" in _strip_ansi(result.output)
        assert "security" in _strip_ansi(result.output)

    def test_sbom_pass_on_green_subprocess(self, tmp_path):
        mock_cyclonedx = MagicMock()

        # Simulate the SBOM file being created
        fake_sbom = Path("graqle-sbom.json")

        fake_result = MagicMock()
        fake_result.returncode = 0

        def side_effect(args, **kwargs):
            # Create the SBOM file when the subprocess "runs"
            fake_sbom.write_text('{"bomFormat":"CycloneDX"}')
            return fake_result

        with patch.dict("sys.modules", {"cyclonedx": mock_cyclonedx}), \
             patch("graqle.cli.commands.trustctl._run", side_effect=side_effect):
            result = runner.invoke(
                app,
                ["trustctl", "verify", "--skip-sigstore", "--skip-audit"],
            )

        # Cleanup
        if fake_sbom.exists():
            fake_sbom.unlink()

        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "SBOM" in result.output


class TestTrustctlVerifyPipAudit:
    """pip-audit check blocks on vulnerabilities."""

    def test_pip_audit_pass_on_no_vulns(self):
        # version check succeeds (audit is installed), audit run returns 0
        fake_version = MagicMock()
        fake_version.returncode = 0

        fake_audit = MagicMock()
        fake_audit.returncode = 0
        fake_audit.stdout = json.dumps({"dependencies": []})

        call_count = [0]

        def run_side_effect(args, **kwargs):
            call_count[0] += 1
            if "--version" in args:
                return fake_version
            return fake_audit

        with patch("graqle.cli.commands.trustctl._run", side_effect=run_side_effect):
            result = runner.invoke(
                app,
                ["trustctl", "verify", "--skip-sigstore", "--skip-sbom"],
            )

        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "pip-audit" in result.output

    def test_pip_audit_fail_on_vulns(self):
        fake_version = MagicMock()
        fake_version.returncode = 0

        fake_audit = MagicMock()
        fake_audit.returncode = 1  # pip-audit exits 1 when vulns found
        fake_audit.stdout = json.dumps({
            "dependencies": [
                {"name": "requests", "version": "2.27.0",
                 "vulns": [{"id": "CVE-2023-00001", "fix_versions": ["2.28.0"]}]}
            ]
        })

        def run_side_effect(args, **kwargs):
            if "--version" in args:
                return fake_version
            return fake_audit

        with patch("graqle.cli.commands.trustctl._run", side_effect=run_side_effect):
            result = runner.invoke(
                app,
                ["trustctl", "verify", "--skip-sigstore", "--skip-sbom"],
            )

        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "UNTRUSTED" in result.output

    def test_pip_audit_missing_shows_install_hint(self):
        fake_missing = MagicMock()
        fake_missing.returncode = 1  # version check fails = not installed

        with patch("graqle.cli.commands.trustctl._run", return_value=fake_missing):
            result = runner.invoke(
                app,
                ["trustctl", "verify", "--skip-sigstore", "--skip-sbom"],
            )
        assert result.exit_code == 1
        assert "graqle" in _strip_ansi(result.output)
        assert "security" in _strip_ansi(result.output)


class TestTrustctlPolicy:
    """graq trustctl policy prints the bundled policy template."""

    def test_policy_prints_yaml(self):
        result = runner.invoke(app, ["trustctl", "policy"])
        assert result.exit_code == 0
        # Policy content should mention sigstore or pip_audit
        assert "sigstore" in result.output or "pip_audit" in result.output

    def test_policy_writes_to_file(self, tmp_path):
        output_file = tmp_path / "my-policy.yaml"
        result = runner.invoke(
            app,
            ["trustctl", "policy", "--output", str(output_file)],
        )
        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "sigstore" in content
