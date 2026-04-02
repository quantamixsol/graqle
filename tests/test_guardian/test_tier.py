"""Tests for graqle.guardian.tier — Free/Pro tier enforcement."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from graqle.guardian.tier import (
    FREE_SCANS_PER_MONTH,
    TierStatus,
    check_tier,
    record_scan,
)


class TestCheckTier:
    def test_free_tier_default(self):
        status = check_tier()
        assert status.tier == "free"
        assert status.scans_limit == FREE_SCANS_PER_MONTH

    def test_pro_tier_with_api_key(self):
        status = check_tier(api_key="grq_test_key_123")
        assert status.tier == "pro"
        assert status.can_scan is True
        assert status.custom_shacl_allowed is True
        assert status.scans_limit == -1

    def test_free_tier_allows_scan_under_limit(self):
        with patch("graqle.guardian.tier._load_usage", return_value={}):
            status = check_tier()
            assert status.can_scan is True
            assert status.scans_used == 0

    def test_free_tier_blocks_at_limit(self):
        from datetime import datetime, timezone

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with patch(
            "graqle.guardian.tier._load_usage",
            return_value={month: FREE_SCANS_PER_MONTH},
        ):
            status = check_tier()
            assert status.can_scan is False
            assert status.scans_used == FREE_SCANS_PER_MONTH

    def test_free_tier_custom_shacl_not_allowed(self):
        status = check_tier()
        assert status.custom_shacl_allowed is False


class TestRecordScan:
    def test_pro_tier_does_not_write(self, tmp_path):
        with patch("graqle.guardian.tier._USAGE_FILE", tmp_path / "usage.json"):
            record_scan(api_key="grq_test")
            assert not (tmp_path / "usage.json").exists()

    def test_free_tier_increments_count(self, tmp_path):
        usage_file = tmp_path / "usage.json"
        with patch("graqle.guardian.tier._USAGE_FILE", usage_file):
            record_scan()
            assert usage_file.exists()
            data = json.loads(usage_file.read_text())
            # Should have exactly 1 scan for current month
            assert sum(data.values()) == 1


class TestTierStatus:
    def test_dataclass_fields(self):
        ts = TierStatus(
            tier="free",
            scans_used=5,
            scans_limit=10,
            month="2026-04",
            can_scan=True,
            custom_shacl_allowed=False,
        )
        assert ts.tier == "free"
        assert ts.scans_used == 5
        assert ts.month == "2026-04"
