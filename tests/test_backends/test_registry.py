"""Tests for BackendRegistry."""

import pytest

from graqle.backends.mock import MockBackend
from graqle.backends.registry import BackendRegistry


def test_registry_register_and_get():
    """Register and retrieve a backend."""
    reg = BackendRegistry()
    backend = MockBackend()
    reg.register("test", backend)

    result = reg.get("test")
    assert result is backend


def test_registry_builtin_mock():
    """Get builtin mock backend by name."""
    reg = BackendRegistry()
    backend = reg.get("mock")
    assert backend is not None


def test_registry_missing_raises():
    """KeyError for unknown backend name."""
    reg = BackendRegistry()
    with pytest.raises(KeyError):
        reg.get("nonexistent-backend")


def test_registry_available():
    """available lists registered + builtin backends."""
    reg = BackendRegistry()
    reg.register("custom", MockBackend())
    available = reg.available
    assert "custom" in available
    assert "mock" in available


def test_registry_contains():
    """__contains__ works for registered and builtin."""
    reg = BackendRegistry()
    assert "mock" in reg
    assert "nonexistent" not in reg
    reg.register("mine", MockBackend())
    assert "mine" in reg
