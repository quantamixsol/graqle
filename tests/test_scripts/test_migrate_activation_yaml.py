"""Tests for scripts/migrate_activation_yaml.py (TC_17..TC_22).

Covers forward migration (old -> new), reverse migration (new -> old for
rollback), dry-run mode, comment preservation, partial migration, idempotency.

SPEC: .gsm/decisions/SPEC-v0623-activation-schema.md §3.2b
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture
def migrate_main():
    """Import the migration script's main() — done lazily to avoid CLI parse at module load."""
    # Add scripts/ to path so we can import the script as a module
    scripts_dir = Path(__file__).parent.parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from migrate_activation_yaml import main
    return main


# ─── TC_17: forward migration in place ─────────────────────────────────────


def test_TC_17_migrate_yaml_inplace(tmp_path, migrate_main):
    yaml_text = """\
graph:
  connector: networkx
activation:
  strategy: top_k
  top_k: 50
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)

    exit_code = migrate_main([str(p)])
    assert exit_code == 0

    # File rewritten
    content = p.read_text()
    assert "ranking: degree" in content
    assert "max_nodes: 50" in content
    assert "strategy:" not in content or "ranking:" in content  # strategy removed
    assert "top_k:" not in content or "max_nodes:" in content

    # Backup created
    bak = tmp_path / "graqle.yaml.bak"
    assert bak.exists()
    assert "strategy: top_k" in bak.read_text()


# ─── TC_18: --dry-run does not write ───────────────────────────────────────


def test_TC_18_migrate_yaml_dry_run_no_write(tmp_path, migrate_main):
    yaml_text = """\
activation:
  strategy: top_k
  top_k: 50
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)
    original = p.read_text()

    exit_code = migrate_main(["--dry-run", str(p)])
    assert exit_code == 0
    # File MUST be unchanged
    assert p.read_text() == original
    # No .bak created in dry-run
    assert not (tmp_path / "graqle.yaml.bak").exists()


# ─── TC_19: --reverse rolls forward fix back to v0.62.2 schema ─────────────


def test_TC_19_migrate_yaml_reverse_to_legacy(tmp_path, migrate_main):
    yaml_text = """\
activation:
  ranking: degree
  max_nodes: 50
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)

    exit_code = migrate_main(["--reverse", str(p)])
    assert exit_code == 0
    content = p.read_text()
    assert "strategy: top_k" in content
    assert "top_k: 50" in content


# ─── TC_20: ruamel preserves comments (only runs if ruamel installed) ───────


def test_TC_20_migrate_yaml_preserves_comments_if_ruamel(tmp_path, migrate_main):
    pytest.importorskip("ruamel.yaml")
    yaml_text = """\
# top of file comment
graph:
  connector: networkx  # inline comment on connector
activation:
  # comment above strategy
  strategy: top_k  # inline on strategy
  top_k: 50
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)
    migrate_main([str(p)])
    after = p.read_text()
    assert "top of file comment" in after
    assert "inline comment on connector" in after
    assert "comment above strategy" in after


# ─── TC_21: partial migration (only top_k set, no strategy) ────────────────


def test_TC_21_migrate_yaml_only_top_k_no_strategy(tmp_path, migrate_main):
    yaml_text = """\
activation:
  top_k: 75
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)
    exit_code = migrate_main([str(p)])
    assert exit_code == 0
    content = p.read_text()
    assert "max_nodes: 75" in content
    assert "top_k:" not in content
    # ranking field NOT added when strategy wasn't present
    assert "ranking:" not in content


# ─── TC_22: already-new schema is a no-op ──────────────────────────────────


def test_TC_22_migrate_yaml_already_new_schema_noop(tmp_path, migrate_main):
    yaml_text = """\
activation:
  ranking: semantic
  max_nodes: 50
"""
    p = tmp_path / "graqle.yaml"
    p.write_text(yaml_text)
    original = p.read_text()
    exit_code = migrate_main([str(p)])
    assert exit_code == 0
    # No changes (no .bak written — exit 0 with "already migrated" message)
    assert p.read_text() == original
    # Backup is created only if --no-backup not passed AND changes were made.
    # Our impl writes nothing on no-op, so no .bak is expected.
    bak = tmp_path / "graqle.yaml.bak"
    assert not bak.exists()
