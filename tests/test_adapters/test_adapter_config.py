"""Tests for LoRA adapter config and registry."""

# ── graqle:intelligence ──
# module: tests.test_adapters.test_adapter_config
# risk: LOW (impact radius: 0 modules)
# dependencies: json, pytest, pathlib, config, registry
# constraints: none
# ── /graqle:intelligence ──

import json
import pytest
from pathlib import Path

from graqle.adapters.config import AdapterConfig
from graqle.adapters.registry import AdapterRegistry


def test_adapter_config_defaults():
    """AdapterConfig has sensible defaults."""
    cfg = AdapterConfig(name="gdpr", domain="legal")
    assert cfg.rank == 16
    assert cfg.alpha == 32
    assert cfg.dropout == 0.05
    assert "q_proj" in cfg.target_modules


def test_adapter_config_full_id():
    """full_id combines domain and name."""
    cfg = AdapterConfig(name="gdpr", domain="legal", version="v2")
    assert cfg.full_id == "legal/gdpr_v2"


def test_adapter_config_to_peft():
    """to_peft_config() returns PEFT-compatible kwargs."""
    cfg = AdapterConfig(rank=8, alpha=16, dropout=0.1)
    peft = cfg.to_peft_config()
    assert peft["r"] == 8
    assert peft["lora_alpha"] == 16
    assert peft["lora_dropout"] == 0.1
    assert peft["task_type"] == "CAUSAL_LM"


def test_registry_register_and_get():
    """Register and retrieve an adapter."""
    reg = AdapterRegistry(registry_path="/nonexistent")
    cfg = AdapterConfig(adapter_id="legal/gdpr", name="gdpr", domain="legal")
    reg.register(cfg)
    assert reg.get("legal/gdpr") is not None
    assert reg.get("legal/gdpr").name == "gdpr"


def test_registry_list_adapters():
    """List all adapters, optionally filtered by domain."""
    reg = AdapterRegistry(registry_path="/nonexistent")
    reg.register(AdapterConfig(adapter_id="legal/gdpr", name="gdpr", domain="legal"))
    reg.register(AdapterConfig(adapter_id="finance/risk", name="risk", domain="finance"))

    all_adapters = reg.list_adapters()
    assert len(all_adapters) == 2

    legal_only = reg.list_adapters(domain="legal")
    assert len(legal_only) == 1
    assert legal_only[0].domain == "legal"


def test_registry_list_domains():
    """List available domains."""
    reg = AdapterRegistry(registry_path="/nonexistent")
    reg.register(AdapterConfig(adapter_id="legal/gdpr", name="gdpr", domain="legal"))
    reg.register(AdapterConfig(adapter_id="finance/risk", name="risk", domain="finance"))
    domains = reg.list_domains()
    assert set(domains) == {"legal", "finance"}


def test_registry_count():
    """Count registered adapters."""
    reg = AdapterRegistry(registry_path="/nonexistent")
    assert reg.count == 0
    reg.register(AdapterConfig(adapter_id="a", name="a"))
    assert reg.count == 1


def test_registry_scan_local(tmp_path):
    """Scan local directory structure for adapters."""
    # Create adapter directory structure
    domain_dir = tmp_path / "legal" / "gdpr_v1"
    domain_dir.mkdir(parents=True)
    config_data = {"rank": 8, "alpha": 16, "description": "GDPR adapter"}
    (domain_dir / "adapter_config.json").write_text(json.dumps(config_data))

    reg = AdapterRegistry(registry_path=str(tmp_path))
    adapters = reg.list_adapters()
    assert len(adapters) == 1
    assert adapters[0].rank == 8
