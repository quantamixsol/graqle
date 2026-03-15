"""Tests for server middleware — auth, rate limiting, validation."""

# ── graqle:intelligence ──
# module: tests.test_server.test_middleware
# risk: HIGH (impact radius: 32 modules)
# consumers: sdk_self_audit, adaptive, reformulator, relevance, benchmark_runner +27 more
# dependencies: __future__, os, time, mock, pytest +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
import time
from unittest.mock import patch

from graqle.server.middleware import (
    MAX_BATCH_SIZE,
    MAX_QUERY_LENGTH,
    MAX_ROUNDS,
    RateLimiter,
    TokenBucket,
    get_configured_api_keys,
)

# ===========================================================================
# Token Bucket
# ===========================================================================

def test_token_bucket_allows_within_capacity():
    bucket = TokenBucket(rate=10.0, capacity=5.0)
    for _ in range(5):
        assert bucket.consume() is True
    # 6th should fail
    assert bucket.consume() is False


def test_token_bucket_refills_over_time():
    bucket = TokenBucket(rate=100.0, capacity=5.0)
    # Drain
    for _ in range(5):
        bucket.consume()
    assert bucket.consume() is False
    # Wait for refill
    time.sleep(0.06)
    assert bucket.consume() is True


def test_token_bucket_respects_capacity():
    bucket = TokenBucket(rate=1000.0, capacity=3.0)
    time.sleep(0.01)  # Refill a lot
    # But capacity caps at 3
    assert bucket.consume(3.0) is True
    assert bucket.consume(1.0) is False


# ===========================================================================
# Rate Limiter
# ===========================================================================

def test_rate_limiter_per_client():
    limiter = RateLimiter(rate=10.0, capacity=2.0)
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is False
    # Different client is independent
    assert limiter.allow("client-b") is True


# ===========================================================================
# API Key Configuration
# ===========================================================================

def test_get_api_keys_from_single_env():
    with patch.dict(os.environ, {"COGNIGRAPH_API_KEY": "my-secret"}, clear=False):
        keys = get_configured_api_keys()
        assert "my-secret" in keys


def test_get_api_keys_from_multi_env():
    with patch.dict(
        os.environ,
        {"COGNIGRAPH_API_KEYS": "key1,key2,key3", "COGNIGRAPH_API_KEY": ""},
        clear=False,
    ):
        keys = get_configured_api_keys()
        assert keys == {"key1", "key2", "key3"}


def test_get_api_keys_empty_when_not_configured():
    with patch.dict(
        os.environ,
        {"COGNIGRAPH_API_KEY": "", "COGNIGRAPH_API_KEYS": ""},
        clear=False,
    ):
        keys = get_configured_api_keys()
        assert len(keys) == 0


# ===========================================================================
# Validation Constants
# ===========================================================================

def test_validation_constants():
    assert MAX_QUERY_LENGTH == 10_000
    assert MAX_ROUNDS == 20
    assert MAX_BATCH_SIZE == 50
