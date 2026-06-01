"""Tests for the CLI edition guard (WS-C C1) — graqle/cli/_edition_guard.py.

100% statement + branch coverage, including every branch of the
proprietary-vs-real-error discrimination and the distribution mapping.
"""

from __future__ import annotations

import pytest
import typer

from graqle.cli import _edition_guard as g
from graqle.cli._edition_guard import (
    _PACKAGE_TO_DISTRIBUTION,
    _degrade_message,
    _distribution_for,
    _is_proprietary_absence,
    requires_package,
)


def _mnfe(name: str) -> ModuleNotFoundError:
    e = ModuleNotFoundError(f"No module named {name!r}")
    e.name = name
    return e


# ---- _distribution_for --------------------------------------------------------


@pytest.mark.parametrize(
    "module,expected",
    [
        ("graqle.cloud", "graqle-studio"),
        ("graqle.cloud.credentials", "graqle-studio"),
        ("graqle.leads", "graqle-studio"),
        ("graqle.studio.app", "graqle-studio"),
        ("graqle.server", "graqle-studio"),
        ("something.unknown", "graqle-studio"),  # default fallback
    ],
)
def test_distribution_for(module, expected):
    assert _distribution_for(module) == expected


def test_distribution_for_longest_prefix():
    # All proprietary packages currently map to the same dist; assert the
    # longest-prefix logic still resolves a sub-module correctly.
    assert _distribution_for("graqle.studio.routes.api") == "graqle-studio"


# ---- _is_proprietary_absence --------------------------------------------------


@pytest.mark.parametrize(
    "name,is_prop",
    [
        ("graqle.cloud", True),
        ("graqle.cloud.credentials", True),
        ("graqle.leads", True),
        ("graqle.studio", True),
        ("graqle.server.app", True),
        ("numpy", False),
        ("graqle.metering", False),     # a Community module — NOT proprietary
        ("graqle", True),               # parent prefix of a proprietary pkg → treat as absence
        ("", False),
    ],
)
def test_is_proprietary_absence(name, is_prop):
    result = _is_proprietary_absence(_mnfe(name))
    assert (result is not None) == is_prop
    if is_prop:
        assert result == name


def test_is_proprietary_absence_none_name():
    e = ModuleNotFoundError("weird")
    e.name = None  # type: ignore[assignment]
    assert _is_proprietary_absence(e) is None


# ---- _degrade_message ---------------------------------------------------------


def test_degrade_message_has_install_path_no_dead_url():
    msg = _degrade_message("graqle.cloud.credentials", "graq cloud status")
    assert "pip install graqle-studio" in msg
    assert "graq cloud status" in msg
    # AUD-029: must NOT hardcode the not-yet-existent editions URL
    assert "graqle.com/editions" not in msg
    assert "http" not in msg


# ---- requires_package decorator ----------------------------------------------


def test_decorator_passes_through_on_success():
    @requires_package("graq cloud status")
    def ok(a, b=2):
        return a + b

    assert ok(1) == 3
    assert ok(1, b=5) == 6


def test_decorator_degrades_on_proprietary_absence(capsys):
    @requires_package("graq cloud status")
    def cmd():
        raise _mnfe("graqle.cloud.credentials")

    with pytest.raises(typer.Exit) as ei:
        cmd()
    assert ei.value.exit_code == 2


def test_decorator_reraises_non_proprietary_error():
    @requires_package("graq x")
    def cmd():
        raise _mnfe("numpy")  # a real missing dependency — must NOT be masked

    with pytest.raises(ModuleNotFoundError):
        cmd()


def test_decorator_reraises_other_exceptions():
    @requires_package("graq x")
    def cmd():
        raise ValueError("unrelated bug")

    with pytest.raises(ValueError, match="unrelated bug"):
        cmd()


def test_decorator_preserves_metadata():
    @requires_package("graq cloud status")
    def my_command():
        """Docstring stays."""
        return None

    assert my_command.__name__ == "my_command"
    assert my_command.__doc__ == "Docstring stays."


def test_does_not_mask_transitive_community_dep_failure():
    """Adversarial (sentinel graq_predict scenario 2): a proprietary command whose
    backend IS present but fails importing a genuine COMMUNITY transitive dep
    (e.g. boto3) must RE-RAISE — never be mis-shown as 'install graqle-studio'.
    The discriminator keys on exc.name, which would be 'boto3' (not proprietary),
    so it propagates unchanged.
    """
    @requires_package("graq cloud push")
    def cmd():
        # Simulates: `from graqle.cloud.x import y` succeeded, but deeper a real
        # third-party dep is missing.
        raise _mnfe("boto3")

    with pytest.raises(ModuleNotFoundError) as ei:
        cmd()
    assert ei.value.name == "boto3"  # the real error surfaced, not masked


def test_mapping_is_complete():
    # Every proprietary package the wheel excludes must have a distribution hint.
    for pkg in ("graqle.cloud", "graqle.leads", "graqle.studio", "graqle.server"):
        assert pkg in _PACKAGE_TO_DISTRIBUTION
