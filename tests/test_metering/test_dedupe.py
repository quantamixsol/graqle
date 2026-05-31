"""Tests for the WAL-backed exactly-once dedupe store (WS-B B3).

100% statement + branch coverage of graqle/metering/dedupe.py. Defensive paths
(corruption, zero-length, oversized, path-traversal, fsync failure, Windows vs
POSIX dir-fsync) are reached by real fault injection — never hidden behind
pragma:no-cover.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from graqle.metering import dedupe as dedupe_mod
from graqle.metering.dedupe import (
    _LEDGER_SUFFIX,
    MeterDedupeError,
    MeterDedupeStore,
    _is_valid_key,
    _safe_dir_fsync,
)


def _key(s: str = "p") -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---- key validation -----------------------------------------------------------


def test_is_valid_key():
    assert _is_valid_key(_key())
    assert not _is_valid_key("")
    assert not _is_valid_key("x" * 64)  # not hex
    assert not _is_valid_key(_key()[:-1])  # 63 chars
    assert not _is_valid_key(_key() + "a")  # 65 chars
    assert not _is_valid_key("../" + "a" * 61)  # path-traversal attempt


# ---- exactly-once core --------------------------------------------------------


def test_mark_if_new_first_true_then_false(tmp_path):
    store = MeterDedupeStore(tmp_path)
    k = _key()
    assert store.mark_if_new(k) is True
    assert store.mark_if_new(k) is False  # second time = no-op
    assert store.mark_if_new(k) is False
    assert store.has(k)
    assert store.count == 1


def test_distinct_keys_each_new(tmp_path):
    store = MeterDedupeStore(tmp_path)
    assert store.mark_if_new(_key("a")) is True
    assert store.mark_if_new(_key("b")) is True
    assert store.count == 2


def test_has_is_read_only(tmp_path):
    store = MeterDedupeStore(tmp_path)
    k = _key()
    assert store.has(k) is False
    assert store.count == 0  # has() did not record


def test_mark_if_new_rejects_malformed_key(tmp_path):
    store = MeterDedupeStore(tmp_path)
    with pytest.raises(MeterDedupeError, match="malformed idempotency key"):
        store.mark_if_new("not-a-leaf-hash")


def test_ledger_path_rejects_malformed_key(tmp_path):
    store = MeterDedupeStore(tmp_path)
    with pytest.raises(MeterDedupeError, match="malformed idempotency key"):
        store._ledger_path("../escape")


# ---- durability + crash recovery ---------------------------------------------


def test_recovery_remembers_across_restart(tmp_path):
    s1 = MeterDedupeStore(tmp_path)
    s1.mark_if_new(_key("a"))
    s1.mark_if_new(_key("b"))
    # fresh store over the same dir = simulated process restart
    s2 = MeterDedupeStore(tmp_path)
    assert s2.has(_key("a")) and s2.has(_key("b"))
    assert s2.count == 2
    # a recovered key still dedupes (no re-bill)
    assert s2.mark_if_new(_key("a")) is False


def test_on_disk_entry_written_with_digest(tmp_path):
    store = MeterDedupeStore(tmp_path)
    k = _key()
    store.mark_if_new(k)
    entry = tmp_path / f"{k}{_LEDGER_SUFFIX}"
    assert entry.exists()
    data = json.loads(entry.read_text())
    assert data["idempotency_key"] == k
    assert data["digest"] == hashlib.sha256(k.encode()).hexdigest()


def test_write_entry_idempotent_on_disk(tmp_path):
    store = MeterDedupeStore(tmp_path)
    k = _key()
    store.mark_if_new(k)
    # calling _write_entry again returns early (file exists) — no crash, no dup
    store._write_entry(k)
    assert (tmp_path / f"{k}{_LEDGER_SUFFIX}").exists()


# ---- corruption / tamper rejection on recovery -------------------------------


def test_recovery_skips_corrupt_json(tmp_path):
    (tmp_path / f"{_key('a')}{_LEDGER_SUFFIX}").write_text("{ not json")
    store = MeterDedupeStore(tmp_path)
    assert store.count == 0  # corrupt entry skipped, not trusted


def test_recovery_skips_non_dict_json(tmp_path):
    (tmp_path / f"{_key('a')}{_LEDGER_SUFFIX}").write_text("[1, 2, 3]")
    assert MeterDedupeStore(tmp_path).count == 0


def test_recovery_skips_missing_fields(tmp_path):
    (tmp_path / f"{_key('a')}{_LEDGER_SUFFIX}").write_text(json.dumps({"idempotency_key": _key("a")}))
    assert MeterDedupeStore(tmp_path).count == 0  # no digest


def test_recovery_skips_malformed_key_field(tmp_path):
    p = tmp_path / f"{_key('a')}{_LEDGER_SUFFIX}"
    p.write_text(json.dumps({"idempotency_key": "short", "digest": "x"}))
    assert MeterDedupeStore(tmp_path).count == 0


def test_recovery_skips_filename_content_mismatch(tmp_path):
    # filename says key 'a' but content carries key 'b' => corrupt
    other = _key("b")
    p = tmp_path / f"{_key('a')}{_LEDGER_SUFFIX}"
    p.write_text(json.dumps({"idempotency_key": other, "digest": hashlib.sha256(other.encode()).hexdigest()}))
    assert MeterDedupeStore(tmp_path).count == 0


def test_recovery_skips_digest_mismatch(tmp_path):
    k = _key("a")
    p = tmp_path / f"{k}{_LEDGER_SUFFIX}"
    p.write_text(json.dumps({"idempotency_key": k, "digest": "deadbeef"}))  # wrong digest
    assert MeterDedupeStore(tmp_path).count == 0


def test_recovery_skips_oversized_entry(tmp_path, monkeypatch):
    k = _key("a")
    p = tmp_path / f"{k}{_LEDGER_SUFFIX}"
    p.write_text(json.dumps({"idempotency_key": k, "digest": hashlib.sha256(k.encode()).hexdigest()}))
    monkeypatch.setattr(dedupe_mod, "_MAX_LEDGER_ENTRY_BYTES", 1)  # force oversize
    assert MeterDedupeStore(tmp_path).count == 0


def test_recovery_ignores_non_ledger_files(tmp_path):
    (tmp_path / "README.txt").write_text("not a ledger entry")
    (tmp_path / "sub").mkdir()  # a directory, not a file
    store = MeterDedupeStore(tmp_path)
    store.mark_if_new(_key("a"))
    assert store.count == 1


def test_recovery_one_bad_entry_does_not_drop_good_ones(tmp_path):
    good = _key("good")
    (tmp_path / f"{good}{_LEDGER_SUFFIX}").write_text(
        json.dumps({"idempotency_key": good, "digest": hashlib.sha256(good.encode()).hexdigest()})
    )
    (tmp_path / f"{_key('bad')}{_LEDGER_SUFFIX}").write_text("corrupt")
    store = MeterDedupeStore(tmp_path)
    assert store.has(good) and store.count == 1


def test_read_entry_handles_unreadable_dir(tmp_path, monkeypatch):
    # _recover swallows an OSError from iterdir (no readable ledger dir)
    store = MeterDedupeStore(tmp_path)

    def boom(self):
        raise OSError("no perms")

    monkeypatch.setattr(Path, "iterdir", boom)
    store._recover()  # must not raise
    assert store.count == 0


# ---- write-path fault injection ----------------------------------------------


def test_write_entry_zero_length_after_write_raises(tmp_path, monkeypatch):
    # Inject the fault ONLY at the post-write size check. The function calls
    # final_path.stat() exactly once more after the entry exists; key the fault
    # on the str(path) (no recursion: we call real_stat, never .exists()).
    store = MeterDedupeStore(tmp_path)
    k = _key("z")
    final_str = str(store._ledger_path(k))

    class _Zero:
        st_size = 0

    real_stat = Path.stat

    def fake_stat(self, *a, **kw):
        st = real_stat(self, *a, **kw)
        if str(self) == final_str and st.st_size > 0:
            return _Zero()  # report the written entry as zero-length
        return st

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(MeterDedupeError, match="zero-length"):
        store._write_entry(k)


def test_write_entry_stat_oserror_raises(tmp_path, monkeypatch):
    store = MeterDedupeStore(tmp_path)
    k = _key("z")
    final_str = str(store._ledger_path(k))
    real_stat = Path.stat
    seen = {"n": 0}

    def fake_stat(self, *a, **kw):
        st = real_stat(self, *a, **kw)  # never recurses (no .exists())
        if str(self) == final_str and st.st_size > 0:
            # The first post-existence stat of the final file is the post-write
            # verification; fail it. (exists() precheck ran before the file
            # existed, so st_size>0 isolates the post-write call.)
            seen["n"] += 1
            raise OSError("stat failed")
        return st

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(MeterDedupeError, match="could not be stat'd"):
        store._write_entry(k)
    assert seen["n"] == 1


def test_write_entry_cleans_tmp_on_replace_failure(tmp_path, monkeypatch):
    store = MeterDedupeStore(tmp_path)
    monkeypatch.setattr(dedupe_mod.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError):
        store._write_entry(_key("z"))
    # no leftover .tmp files
    assert not list(tmp_path.glob("*.tmp"))


def test_write_entry_unlink_failure_is_swallowed(tmp_path, monkeypatch):
    store = MeterDedupeStore(tmp_path)
    monkeypatch.setattr(dedupe_mod.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("replace failed")))
    monkeypatch.setattr(dedupe_mod.os, "unlink", lambda p: (_ for _ in ()).throw(OSError("unlink failed")))
    with pytest.raises(OSError, match="replace failed"):  # original error surfaces, unlink error swallowed
        store._write_entry(_key("z"))


# ---- _safe_dir_fsync branches -------------------------------------------------


def test_safe_dir_fsync_noop_on_non_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(dedupe_mod.os, "name", "nt")
    _safe_dir_fsync(tmp_path)  # returns immediately, no fd opened


def test_safe_dir_fsync_posix_success(tmp_path, monkeypatch):
    monkeypatch.setattr(dedupe_mod.os, "name", "posix")
    calls = {"fsync": 0, "close": 0}
    monkeypatch.setattr(dedupe_mod.os, "open", lambda p, f: 7)
    monkeypatch.setattr(dedupe_mod.os, "fsync", lambda fd: calls.__setitem__("fsync", calls["fsync"] + 1))
    monkeypatch.setattr(dedupe_mod.os, "close", lambda fd: calls.__setitem__("close", calls["close"] + 1))
    _safe_dir_fsync(tmp_path)
    assert calls == {"fsync": 1, "close": 1}


def test_safe_dir_fsync_posix_open_error_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(dedupe_mod.os, "name", "posix")
    monkeypatch.setattr(dedupe_mod.os, "open", lambda p, f: (_ for _ in ()).throw(OSError("no dir fd")))
    _safe_dir_fsync(tmp_path)  # error swallowed (fd never opened, finally skips close)


def test_safe_dir_fsync_posix_close_error_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(dedupe_mod.os, "name", "posix")
    monkeypatch.setattr(dedupe_mod.os, "open", lambda p, f: 7)
    monkeypatch.setattr(dedupe_mod.os, "fsync", lambda fd: None)
    monkeypatch.setattr(dedupe_mod.os, "close", lambda fd: (_ for _ in ()).throw(OSError("close failed")))
    _safe_dir_fsync(tmp_path)  # close error swallowed in finally
