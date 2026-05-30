#!/usr/bin/env python3
"""scripts/migrate_activation_yaml.py — one-shot migration v0.62.3.

Rewrites graqle.yaml from old `activation:` schema to new:
    activation:                  activation:
      strategy: top_k     ==>      ranking: degree
      top_k: 50                    max_nodes: 50

Usage:
    python -m scripts.migrate_activation_yaml graqle.yaml             # in-place + .bak
    python -m scripts.migrate_activation_yaml --dry-run graqle.yaml   # preview only
    python -m scripts.migrate_activation_yaml --reverse graqle.yaml   # new -> old (rollback)

Comments and ordering are preserved via ruamel.yaml round-trip. If ruamel is
not installed, falls back to PyYAML (loses comments — warns the user).

V-MARKER: V-CR-WRITE-NATIVE-001 (same as registry.py).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import warnings
from pathlib import Path
from typing import Any

# Same migration table the runtime validator uses (graqle/config/settings.py)
STRATEGY_TO_RANKING: dict[str, str] = {
    "chunk": "semantic",
    "top_k": "degree",
    "full": "none",
    "pcst": "semantic",
    "manual": "none",
}
RANKING_TO_LEGACY_STRATEGY: dict[str, str] = {
    "semantic": "chunk",
    "degree": "top_k",
    "none": "full",
}


def _load_yaml(path: Path) -> tuple[Any, Any]:
    """Load yaml with ruamel if available (preserves comments), else PyYAML."""
    try:
        from ruamel.yaml import YAML
        yaml_rt = YAML()
        yaml_rt.preserve_quotes = True
        with path.open("r", encoding="utf-8") as f:
            data = yaml_rt.load(f)
        return data, yaml_rt
    except ImportError:
        warnings.warn(
            "ruamel.yaml not installed — using PyYAML (comments will be lost). "
            "pip install ruamel.yaml to preserve formatting.",
            UserWarning,
            stacklevel=2,
        )
        import yaml
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data, yaml


def _dump_yaml(data: Any, dumper: Any, path: Path) -> None:
    """Dump yaml back to path using whichever dumper _load_yaml returned."""
    if hasattr(dumper, "dump"):
        # ruamel.yaml YAML instance OR PyYAML module
        with path.open("w", encoding="utf-8") as f:
            if hasattr(dumper, "preserve_quotes"):
                dumper.dump(data, f)
            else:
                dumper.dump(data, f, default_flow_style=False, sort_keys=False)


def migrate_forward(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Old schema -> new schema. Returns (changed, list of human-readable changes)."""
    changes: list[str] = []
    act = data.get("activation")
    if not isinstance(act, dict):
        return False, ["no activation: section found, nothing to migrate"]

    old_strategy = act.pop("strategy", None) if "strategy" in act else None
    old_top_k = act.pop("top_k", None) if "top_k" in act else None

    if old_strategy is None and old_top_k is None:
        return False, ["activation: section is already on new schema (no strategy/top_k fields)"]

    if old_strategy is not None:
        new_ranking = STRATEGY_TO_RANKING.get(old_strategy, "semantic")
        if old_strategy not in STRATEGY_TO_RANKING:
            changes.append(
                f"WARNING: strategy={old_strategy!r} is not a known legacy value; "
                f"defaulted ranking to 'semantic'. Review manually."
            )
        # Don't overwrite if user already has new ranking field
        if "ranking" not in act:
            act["ranking"] = new_ranking
            changes.append(f"strategy: {old_strategy!r} -> ranking: {new_ranking!r}")
        else:
            changes.append(
                f"strategy: {old_strategy!r} dropped (ranking: {act['ranking']!r} already set)"
            )

    if old_top_k is not None:
        if "max_nodes" not in act:
            act["max_nodes"] = int(old_top_k)
            changes.append(f"top_k: {old_top_k} -> max_nodes: {old_top_k}")
        else:
            changes.append(
                f"top_k: {old_top_k} dropped (max_nodes: {act['max_nodes']} already set)"
            )

    return True, changes


def migrate_reverse(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """New schema -> old schema. For rollback to v0.62.2."""
    changes: list[str] = []
    act = data.get("activation")
    if not isinstance(act, dict):
        return False, ["no activation: section found, nothing to migrate"]

    new_ranking = act.pop("ranking", None) if "ranking" in act else None
    new_max_nodes = act.pop("max_nodes", None) if "max_nodes" in act else None

    if new_ranking is None and new_max_nodes is None:
        return False, ["activation: section has no new-schema fields to reverse"]

    if new_ranking is not None:
        legacy = RANKING_TO_LEGACY_STRATEGY.get(new_ranking, "chunk")
        if "strategy" not in act:
            act["strategy"] = legacy
            changes.append(f"ranking: {new_ranking!r} -> strategy: {legacy!r}")

    if new_max_nodes is not None:
        if "top_k" not in act:
            act["top_k"] = int(new_max_nodes)
            changes.append(f"max_nodes: {new_max_nodes} -> top_k: {new_max_nodes}")

    return True, changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate graqle.yaml between v0.62.2 (old) and v0.62.3+ (new) activation schema"
    )
    parser.add_argument("yaml_path", type=Path, help="Path to graqle.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print changes without writing the file")
    parser.add_argument("--reverse", action="store_true",
                        help="Migrate NEW schema -> OLD (rollback to v0.62.2)")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip writing the .bak file (default: write graqle.yaml.bak)")
    args = parser.parse_args(argv)

    if not args.yaml_path.exists():
        print(f"ERROR: {args.yaml_path} does not exist", file=sys.stderr)
        return 2

    data, dumper = _load_yaml(args.yaml_path)
    if not isinstance(data, dict):
        print(f"ERROR: {args.yaml_path} does not contain a YAML mapping at the top level",
              file=sys.stderr)
        return 2

    migrator = migrate_reverse if args.reverse else migrate_forward
    changed, changes = migrator(data)

    direction = "REVERSE (new -> old)" if args.reverse else "FORWARD (old -> new)"
    print(f"=== Migration direction: {direction} ===")
    print(f"=== File: {args.yaml_path} ===")
    if not changed:
        for line in changes:
            print(f"  {line}")
        print("=== No changes needed. Exit 0. ===")
        return 0

    print("Changes:")
    for line in changes:
        print(f"  - {line}")

    if args.dry_run:
        print("=== DRY-RUN: no file written ===")
        return 0

    # Backup before write
    if not args.no_backup:
        bak_path = args.yaml_path.with_suffix(args.yaml_path.suffix + ".bak")
        shutil.copy2(args.yaml_path, bak_path)
        print(f"=== Backup saved: {bak_path} ===")

    _dump_yaml(data, dumper, args.yaml_path)
    print(f"=== Wrote: {args.yaml_path} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
