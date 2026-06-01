"""Tests for the licence nonce replay store (WS-D D1c) — all failure points.

100% statement + branch coverage of graqle/licensing/nonce_store.py, with
fault-injection for the WAL write/recovery defensive paths.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from graqle.licensing import nonce_store as ns_mod
from graqle.licensing.nonce_store import (
    _ENTRY_SUFFIX,
    LicenseNonceStore,
    NonceStoreError,
    _is_valid_stem,
    _safe_dir_fsync,
    _stem_for,
)


# ---- accept-once core ---------------------------------------------------------


def test_accept_once_then_replay(tmp_path):
    s = LicenseNonceStore(tmp_path)
    assert s.accept_once("nonce-A") is True
    assert s.accept_once("nonce-A") is False
    assert s.accept_once("nonce-A") is False
    assert s.has_seen("nonce-A")
    assert s.count == 1


def test_distinct_nonces(tmp_path):
    s = LicenseNonceStore(tmp_path)
    assert s.accept_once("a") and s.accept_once("b")
    assert s.count == 2


def test_has_seen_read_only(tmp_path):
    s = LicenseNonceStore(tmp_path)
    assert s.has_seen("x") is False
    assert s.count == 0


@pytest.mark.parametrize("bad", ["", None, 123])
def test_accept_once_rejects_bad(tmp_path, bad):
    s = LicenseNonceStore(tmp_path)
    with pytest.raises(NonceStoreError):
        s.accept_once(bad)  # type: ignore[arg-type]


def test_accept_once_rejects_overlong(tmp_path):
    s = LicenseNonceStore(tmp_path)
    with pytest.raises(NonceStoreError, match="exceeds"):
        s.accept_once("x" * (ns_mod._MAX_NONCE_LEN + 1))


def test_has_seen_handles_bad_input(tmp_path):
    s = LicenseNonceStore(tmp_path)
    assert s.has_seen("") is False
    assert s.has_seen(None) is False  # type: ignore[arg-type]
    assert s.has_seen("y" * (ns_mod._MAX_NONCE_LEN + 1)) is False


# ---- durability + recovery ----------------------------------------------------


def test_recovery_across_restart(tmp_path):
    LicenseNonceStore(tmp_path).accept_once("keep-me")
    s2 = LicenseNonceStore(tmp_path)
    assert s2.has_seen("keep-me")
    assert s2.accept_once("keep-me") is False


def test_entry_written_with_digest(tmp_path):
    s = LicenseNonceStore(tmp_path)
    s.accept_once("n1")
    stem = _stem_for("n1")
    entry = tmp_path / f"{stem}{_ENTRY_SUFFIX}"
    data = json.loads(entry.read_text())
    assert data["nonce"] == "n1" and data["stem"] == stem


def test_write_idempotent_on_disk(tmp_path):
    s = LicenseNonceStore(tmp_path)
    s.accept_once("n1")
    s._write_entry(_stem_for("n1"), "n1")  # early-return path (exists)
    assert (tmp_path / f"{_stem_for('n1')}{_ENTRY_SUFFIX}").exists()


def test_entry_path_rejects_bad_stem(tmp_path):
    s = LicenseNonceStore(tmp_path)
    with pytest.raises(NonceStoreError):
        s._entry_path("../escape")


# ---- corruption-skip recovery -------------------------------------------------


def _good_entry(tmp_path, nonce):
    stem = _stem_for(nonce)
    (tmp_path / f"{stem}{_ENTRY_SUFFIX}").write_text(
        json.dumps({"stem": stem, "nonce": nonce,
                    "digest": hashlib.sha256((stem + ":" + nonce).encode()).hexdigest()})
    )
    return stem


def test_recovery_skips_corrupt_json(tmp_path):
    (tmp_path / f"{_stem_for('a')}{_ENTRY_SUFFIX}").write_text("{ bad")
    assert LicenseNonceStore(tmp_path).count == 0


def test_recovery_skips_non_dict(tmp_path):
    (tmp_path / f"{_stem_for('a')}{_ENTRY_SUFFIX}").write_text("[1]")
    assert LicenseNonceStore(tmp_path).count == 0


def test_recovery_skips_missing_fields(tmp_path):
    (tmp_path / f"{_stem_for('a')}{_ENTRY_SUFFIX}").write_text(json.dumps({"stem": _stem_for("a")}))
    assert LicenseNonceStore(tmp_path).count == 0


def test_recovery_skips_invalid_stem(tmp_path):
    (tmp_path / f"{_stem_for('a')}{_ENTRY_SUFFIX}").write_text(
        json.dumps({"stem": "short", "nonce": "a", "digest": "x"}))
    assert LicenseNonceStore(tmp_path).count == 0


def test_recovery_skips_filename_mismatch(tmp_path):
    # filename stem for 'a' but body stem for 'b'
    other = _stem_for("b")
    (tmp_path / f"{_stem_for('a')}{_ENTRY_SUFFIX}").write_text(
        json.dumps({"stem": other, "nonce": "b",
                    "digest": hashlib.sha256((other + ":b").encode()).hexdigest()}))
    assert LicenseNonceStore(tmp_path).count == 0


def test_recovery_skips_stem_not_hash_of_nonce(tmp_path):
    stem = _stem_for("a")
    # stem matches filename but nonce doesn't hash to it
    (tmp_path / f"{stem}{_ENTRY_SUFFIX}").write_text(
        json.dumps({"stem": stem, "nonce": "DIFFERENT",
                    "digest": hashlib.sha256((stem + ":DIFFERENT").encode()).hexdigest()}))
    assert LicenseNonceStore(tmp_path).count == 0


def test_recovery_skips_digest_mismatch(tmp_path):
    stem = _stem_for("a")
    (tmp_path / f"{stem}{_ENTRY_SUFFIX}").write_text(
        json.dumps({"stem": stem, "nonce": "a", "digest": "deadbeef"}))
    assert LicenseNonceStore(tmp_path).count == 0


def test_recovery_skips_oversized(tmp_path, monkeypatch):
    _good_entry(tmp_path, "a")
    monkeypatch.setattr(ns_mod, "_MAX_ENTRY_BYTES", 1)
    assert LicenseNonceStore(tmp_path).count == 0


def test_recovery_one_bad_keeps_good(tmp_path):
    _good_entry(tmp_path, "good")
    (tmp_path / f"{_stem_for('bad')}{_ENTRY_SUFFIX}").write_text("corrupt")
    s = LicenseNonceStore(tmp_path)
    assert s.count == 1 and s.has_seen("good")


def test_recovery_unreadable_dir(tmp_path, monkeypatch):
    s = LicenseNonceStore(tmp_path)
    monkeypatch.setattr(Path, "iterdir", lambda self: (_ for _ in ()).throw(OSError("no perms")))
    s._recover()  # must not raise
    assert s.count == 0


def test_recovery_ignores_non_entry_files(tmp_path):
    (tmp_path / "README.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    s = LicenseNonceStore(tmp_path)
    s.accept_once("a")
    assert s.count == 1


# ---- write-path fault injection ----------------------------------------------


def test_write_zero_length_raises(tmp_path, monkeypatch):
    s = LicenseNonceStore(tmp_path)
    stem = _stem_for("z")
    final_str = str(s._entry_path(stem))
    real = Path.stat

    def fake(self, *a, **k):
        st = real(self, *a, **k)
        if str(self) == final_str and st.st_size > 0:
            class _Z:
                st_size = 0
            return _Z()
        return st

    monkeypatch.setattr(Path, "stat", fake)
    with pytest.raises(NonceStoreError, match="zero-length"):
        s._write_entry(stem, "z")


def test_write_stat_oserror_raises(tmp_path, monkeypatch):
    s = LicenseNonceStore(tmp_path)
    stem = _stem_for("z")
    final_str = str(s._entry_path(stem))
    real = Path.stat

    def fake(self, *a, **k):
        st = real(self, *a, **k)
        if str(self) == final_str and st.st_size > 0:
            raise OSError("stat failed")
        return st

    monkeypatch.setattr(Path, "stat", fake)
    with pytest.raises(NonceStoreError, match="could not be stat'd"):
        s._write_entry(stem, "z")


def test_write_cleans_tmp_on_replace_failure(tmp_path, monkeypatch):
    s = LicenseNonceStore(tmp_path)
    monkeypatch.setattr(ns_mod.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("nope")))
    with pytest.raises(OSError):
        s._write_entry(_stem_for("z"), "z")
    assert not list(tmp_path.glob("*.tmp"))


def test_write_unlink_failure_swallowed(tmp_path, monkeypatch):
    s = LicenseNonceStore(tmp_path)
    monkeypatch.setattr(ns_mod.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("nope")))
    monkeypatch.setattr(ns_mod.os, "unlink", lambda p: (_ for _ in ()).throw(OSError("unlink")))
    with pytest.raises(OSError, match="nope"):
        s._write_entry(_stem_for("z"), "z")


# ---- helpers + _safe_dir_fsync branches ---------------------------------------


def test_is_valid_stem():
    assert _is_valid_stem(_stem_for("x"))
    assert not _is_valid_stem("short")
    assert not _is_valid_stem("g" * 64)  # non-hex


def test_safe_dir_fsync_non_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(ns_mod.os, "name", "nt")
    _safe_dir_fsync(tmp_path)


def test_safe_dir_fsync_posix_success(tmp_path, monkeypatch):
    monkeypatch.setattr(ns_mod.os, "name", "posix")
    calls = {"f": 0, "c": 0}
    monkeypatch.setattr(ns_mod.os, "open", lambda p, f: 7)
    monkeypatch.setattr(ns_mod.os, "fsync", lambda fd: calls.__setitem__("f", 1))
    monkeypatch.setattr(ns_mod.os, "close", lambda fd: calls.__setitem__("c", 1))
    _safe_dir_fsync(tmp_path)
    assert calls == {"f": 1, "c": 1}


def test_safe_dir_fsync_posix_open_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ns_mod.os, "name", "posix")
    monkeypatch.setattr(ns_mod.os, "open", lambda p, f: (_ for _ in ()).throw(OSError("no")))
    _safe_dir_fsync(tmp_path)  # swallowed


def test_safe_dir_fsync_posix_close_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ns_mod.os, "name", "posix")
    monkeypatch.setattr(ns_mod.os, "open", lambda p, f: 7)
    monkeypatch.setattr(ns_mod.os, "fsync", lambda fd: None)
    monkeypatch.setattr(ns_mod.os, "close", lambda fd: (_ for _ in ()).throw(OSError("close")))
    _safe_dir_fsync(tmp_path)  # swallowed in finally
