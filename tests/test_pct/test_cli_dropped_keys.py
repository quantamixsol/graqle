"""Tests for CLI key-loader malformed-entry handling (MAJOR-C2 sentinel pass 4).

The CLI's `_build_public_key_resolver` previously silently dropped
key-ring entries missing 'kid' or 'public_key_pem'. Pass 4 found this
masks operator-side config errors. The fix surfaces dropped entries
to stderr via the Rich console.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graqle.cli.commands.pct import _build_public_key_resolver


def _write_keys_file(tmp_path: Path, keys: list[dict]) -> Path:
    p = tmp_path / "pct-keys.json"
    p.write_text(
        json.dumps({"schema_version": "1.0", "keys": keys}, indent=2),
        encoding="utf-8",
    )
    return p


class TestKeyLoaderWarnsOnMalformed:
    def test_all_well_formed_no_warning(self, tmp_path, capsys, rsa_keypair):
        from graqle.pct.issuer import export_public_key_pem

        _, pub = rsa_keypair
        pem = export_public_key_pem(pub)
        keys_file = _write_keys_file(
            tmp_path,
            [{"kid": "K1", "public_key_pem": pem}],
        )
        resolver = _build_public_key_resolver(keys_file)
        # No warning expected
        captured = capsys.readouterr()
        assert "warn:" not in (captured.out + captured.err).lower()

        # Resolver returns the key for K1
        result = resolver("K1")
        assert result is not None

    def test_missing_kid_field_warns(self, tmp_path, capsys, rsa_keypair):
        from graqle.pct.issuer import export_public_key_pem

        _, pub = rsa_keypair
        pem = export_public_key_pem(pub)
        keys_file = _write_keys_file(
            tmp_path,
            [
                {"kid": "K1", "public_key_pem": pem},  # well-formed
                {"public_key_pem": pem},  # missing kid
            ],
        )
        _build_public_key_resolver(keys_file)
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "dropped" in combined and "1" in combined

    def test_missing_pem_field_warns(self, tmp_path, capsys):
        keys_file = _write_keys_file(
            tmp_path,
            [
                {"kid": "K2"},  # missing public_key_pem
                {"kid": "K3"},  # missing public_key_pem
            ],
        )
        _build_public_key_resolver(keys_file)
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "dropped" in combined and "2" in combined

    def test_resolver_for_unknown_kid_returns_none(
        self, tmp_path, capsys, rsa_keypair
    ):
        from graqle.pct.issuer import export_public_key_pem

        _, pub = rsa_keypair
        pem = export_public_key_pem(pub)
        keys_file = _write_keys_file(
            tmp_path,
            [{"kid": "K1", "public_key_pem": pem}],
        )
        resolver = _build_public_key_resolver(keys_file)
        # Unknown kid still returns None — the warning is on entries,
        # not on resolution.
        assert resolver("K-unknown") is None
