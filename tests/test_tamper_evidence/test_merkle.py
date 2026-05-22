"""Tests for the RFC 6962 Merkle tree (v0.59.0 PR-2, R25-EU01 Task 1.2).

Covers: build/root determinism, inclusion-proof verification for every leaf,
single-bit tamper detection (AC-3), zero false positives on untampered data
(AC-4), RFC 6962 §2.1 padding edge cases (power-of-2 vs odd sizes), domain
separation (leaf vs node prefixes), and the §358 Proof Bundle serialization.
"""

from __future__ import annotations

import hashlib

import pytest

from graqle.governance.tamper_evidence.merkle import (
    InclusionProof,
    LEAF_PREFIX,
    MAX_TREE_SIZE,
    MerkleError,
    MerkleTree,
    NODE_PREFIX,
    SIBLING_LEFT,
    SIBLING_RIGHT,
    leaf_hash_for_record,
)

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - hypothesis is an optional dev dep
    _HAS_HYPOTHESIS = False

    # No-op shims so the @given/@settings decorators below remain valid Python
    # at class-definition time. The whole TestProperties class is skipped via
    # skipif, but skipif only skips EXECUTION — the class body (and therefore
    # the decorator expressions) is still evaluated at collection time.
    def given(*_args, **_kwargs):  # type: ignore[no-redef]
        def _decorator(func):
            return func

        return _decorator

    def settings(*_args, **_kwargs):  # type: ignore[no-redef]
        def _decorator(func):
            return func

        return _decorator

    class _StStub:  # type: ignore[no-redef]
        def __getattr__(self, _name):
            return lambda *a, **k: None

    st = _StStub()  # type: ignore[assignment]

    class HealthCheck:  # type: ignore[no-redef]
        too_slow = None


# ---- helpers ------------------------------------------------------------------


def _record(i: int) -> dict:
    """A minimally valid leaf-input record (canon_leaf requires proof_format_version)."""
    return {
        "proof_format_version": "1.0.0",
        "record_id": f"tr_{i:06d}",
        "content_hash": hashlib.sha256(f"payload-{i}".encode()).hexdigest(),
        "timestamp_unix": 1_700_000_000 + i,
        "governance_metadata": {"decision": "ALLOW", "seq": i},
    }


def _leaves(n: int) -> list[bytes]:
    """``n`` distinct RFC 6962 leaf hashes."""
    return [leaf_hash_for_record(_record(i)) for i in range(n)]


# ---- RFC 6962 domain separation -----------------------------------------------


def test_leaf_prefix_is_0x00_node_prefix_is_0x01():
    """Domain-separation prefixes are the RFC 6962 constants. FROZEN contract."""
    assert LEAF_PREFIX == b"\x00"
    assert NODE_PREFIX == b"\x01"


def test_leaf_hash_uses_leaf_prefix():
    """leaf_hash_for_record == SHA256(0x00 || canon_leaf(record))."""
    from graqle.governance.tamper_evidence.canonicalize import canon_leaf

    rec = _record(7)
    expected = hashlib.sha256(b"\x00" + canon_leaf(rec)).digest()
    assert leaf_hash_for_record(rec) == expected


def test_leaf_and_node_hash_spaces_are_disjoint():
    """A two-leaf node hash must not collide with any single-leaf leaf hash.

    The whole point of the 0x00/0x01 prefixes: a node can never be mistaken for
    a leaf (second-preimage resistance over the tree shape).
    """
    leaves = _leaves(2)
    tree = MerkleTree(leaves)
    assert tree.root not in set(leaves)


# ---- build + root determinism -------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 9, 16, 17, 31, 100])
def test_root_is_deterministic_rebuild(n):
    """Build -> root -> rebuild from identical leaves -> identical root."""
    leaves = _leaves(n)
    root_a = MerkleTree(leaves).root
    root_b = MerkleTree(list(leaves)).root
    assert root_a == root_b
    assert len(root_a) == 32  # SHA-256 digest size


def test_root_changes_when_any_leaf_changes():
    """Swapping one leaf changes the root (no accidental collisions)."""
    leaves = _leaves(8)
    base = MerkleTree(leaves).root
    mutated = list(leaves)
    mutated[3] = leaf_hash_for_record(_record(999))
    assert MerkleTree(mutated).root != base


def test_leaf_order_matters():
    """The tree is order-sensitive: reordering leaves changes the root."""
    leaves = _leaves(4)
    base = MerkleTree(leaves).root
    reordered = [leaves[1], leaves[0], leaves[2], leaves[3]]
    assert MerkleTree(reordered).root != base


def test_single_leaf_root_is_the_leaf_hash():
    """A one-leaf tree's root is that leaf hash (no node hashing applied)."""
    leaves = _leaves(1)
    assert MerkleTree(leaves).root == leaves[0]


def test_from_records_matches_from_leaf_hashes():
    """from_records and from_leaf_hashes produce identical roots."""
    records = [_record(i) for i in range(6)]
    leaves = [leaf_hash_for_record(r) for r in records]
    assert MerkleTree.from_records(records).root == MerkleTree.from_leaf_hashes(leaves).root


def test_empty_tree_rejected():
    """Layer 5 never commits an empty batch; building from zero leaves raises."""
    with pytest.raises(MerkleError):
        MerkleTree([])


def test_oversize_tree_rejected_without_allocating():
    """A leaf count above MAX_TREE_SIZE is refused (DoS / caller-bug guard).

    The check reads len() and raises BEFORE the defensive copy or level build,
    so an oversized list never triggers the O(N) tree construction. We assert on
    a sentinel list whose __len__ lies, proving no per-element work happens.
    """

    class _HugeList(list):
        def __len__(self):  # report oversize without holding the elements
            return MAX_TREE_SIZE + 1

    with pytest.raises(MerkleError, match="MAX_TREE_SIZE"):
        MerkleTree(_HugeList([b"\x00" * 32]))


def test_root_hex_and_size():
    leaves = _leaves(5)
    tree = MerkleTree(leaves)
    assert tree.root_hex == tree.root.hex()
    assert len(tree.root_hex) == 64
    assert tree.size == 5


def test_leaf_hash_at_returns_correct_leaf():
    """leaf_hash_at(i) returns exactly the i-th leaf hash used to build the tree."""
    leaves = _leaves(6)
    tree = MerkleTree(leaves)
    for i in range(6):
        assert tree.leaf_hash_at(i) == leaves[i]


def test_leaf_hash_at_out_of_range():
    """leaf_hash_at rejects out-of-range indices with a descriptive IndexError."""
    tree = MerkleTree(_leaves(4))
    with pytest.raises(IndexError):
        tree.leaf_hash_at(4)
    with pytest.raises(IndexError):
        tree.leaf_hash_at(-1)


# ---- RFC 6962 §2.1 padding (duplicate last node) ------------------------------


def test_odd_level_duplicates_last_node():
    """A 3-leaf tree pairs leaf[2] with itself per §2.1 (matches manual build)."""
    leaves = _leaves(3)
    tree = MerkleTree(leaves)

    def node(left, right):
        return hashlib.sha256(b"\x01" + left + right).digest()

    h01 = node(leaves[0], leaves[1])
    h22 = node(leaves[2], leaves[2])  # duplicated last node
    expected_root = node(h01, h22)
    assert tree.root == expected_root


def test_power_of_two_does_not_duplicate():
    """A 4-leaf tree is a clean binary tree (no self-pairing)."""
    leaves = _leaves(4)
    tree = MerkleTree(leaves)

    def node(left, right):
        return hashlib.sha256(b"\x01" + left + right).digest()

    expected_root = node(node(leaves[0], leaves[1]), node(leaves[2], leaves[3]))
    assert tree.root == expected_root


# ---- inclusion proofs ---------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 9, 16, 17, 31, 64, 100])
def test_inclusion_proof_verifies_every_leaf(n):
    """Every leaf's inclusion proof recomputes the published root (AC-7 core)."""
    leaves = _leaves(n)
    tree = MerkleTree(leaves)
    root = tree.root
    for i in range(n):
        proof = tree.inclusion_proof(i)
        assert proof.compute_root() == root
        assert proof.verify(root) is True


def test_inclusion_proof_out_of_range():
    tree = MerkleTree(_leaves(4))
    with pytest.raises(IndexError):
        tree.inclusion_proof(4)
    with pytest.raises(IndexError):
        tree.inclusion_proof(-1)


def test_inclusion_proof_wrong_root_fails():
    """A proof must not verify against a different root (AC-4: no false positives)."""
    tree = MerkleTree(_leaves(8))
    other_root = MerkleTree(_leaves(8)[::-1]).root
    proof = tree.inclusion_proof(2)
    assert proof.verify(other_root) is False


def test_proof_path_length_is_tree_depth():
    """An 8-leaf tree has depth 3, so each proof has exactly 3 siblings."""
    tree = MerkleTree(_leaves(8))
    for i in range(8):
        assert len(tree.inclusion_proof(i).merkle_path) == 3


# ---- AC-3: single-bit tamper detection ----------------------------------------


def test_single_bit_flip_detected_for_all_leaves():
    """AC-3: flipping one bit in any leaf hash makes its proof fail (1000/1000)."""
    n = 64
    leaves = _leaves(n)
    tree = MerkleTree(leaves)
    root = tree.root
    detected = 0
    for i in range(n):
        proof = tree.inclusion_proof(i)
        # Flip the lowest bit of the leaf hash and re-verify the same path.
        flipped = bytearray(proof.leaf_hash)
        flipped[-1] ^= 0x01
        tampered = InclusionProof(
            leaf_index=proof.leaf_index,
            tree_size=proof.tree_size,
            leaf_hash=bytes(flipped),
            merkle_path=proof.merkle_path,
            merkle_path_directions=proof.merkle_path_directions,
        )
        if tampered.verify(root) is False:
            detected += 1
    assert detected == n  # 100% detection


def test_sibling_tamper_detected():
    """Corrupting a sibling hash in the path breaks verification."""
    tree = MerkleTree(_leaves(8))
    root = tree.root
    proof = tree.inclusion_proof(5)
    bad_path = list(proof.merkle_path)
    corrupt = bytearray(bad_path[0])
    corrupt[0] ^= 0xFF
    bad_path[0] = bytes(corrupt)
    tampered = InclusionProof(
        leaf_index=proof.leaf_index,
        tree_size=proof.tree_size,
        leaf_hash=proof.leaf_hash,
        merkle_path=bad_path,
        merkle_path_directions=proof.merkle_path_directions,
    )
    assert tampered.verify(root) is False


# ---- AC-4: zero false positives -----------------------------------------------


def test_zero_false_positives_untampered():
    """AC-4: untampered proofs verify 100% of the time across many sizes."""
    false_positives = 0
    total = 0
    for n in [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]:
        tree = MerkleTree(_leaves(n))
        root = tree.root
        for i in range(n):
            total += 1
            if tree.inclusion_proof(i).verify(root) is not True:
                false_positives += 1
    assert false_positives == 0
    assert total > 0


# ---- InclusionProof construction guards + serialization -----------------------


def test_inclusion_proof_length_mismatch_rejected():
    with pytest.raises(MerkleError):
        InclusionProof(
            leaf_index=0,
            tree_size=2,
            leaf_hash=b"\x00" * 32,
            merkle_path=[b"\x11" * 32],
            merkle_path_directions=[SIBLING_LEFT, SIBLING_RIGHT],  # too many
        )


def test_inclusion_proof_invalid_direction_rejected():
    with pytest.raises(MerkleError):
        InclusionProof(
            leaf_index=0,
            tree_size=2,
            leaf_hash=b"\x00" * 32,
            merkle_path=[b"\x11" * 32],
            merkle_path_directions=[2],  # not 0 or 1
        )


def test_to_bundle_shape_matches_spec():
    """Bundle uses hex strings for hashes and INTEGER directions (R25-EU01 §358)."""
    tree = MerkleTree(_leaves(8))
    bundle = tree.inclusion_proof(3).to_bundle()
    assert bundle["leaf_index"] == 3
    assert bundle["tree_size"] == 8
    assert all(isinstance(h, str) and len(h) == 64 for h in bundle["merkle_path"])
    assert all(d in (0, 1) for d in bundle["merkle_path_directions"])
    # Directions are ints, NOT bools (JCS interop). bool is an int subclass, so
    # assert the exact type to lock this down.
    assert all(type(d) is int for d in bundle["merkle_path_directions"])


def test_directions_are_left_or_right_constants():
    assert SIBLING_LEFT == 0
    assert SIBLING_RIGHT == 1


# ---- property tests (skipped if hypothesis unavailable) -----------------------


@pytest.mark.skipif(not _HAS_HYPOTHESIS, reason="hypothesis not installed")
class TestProperties:
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @given(n=st.integers(min_value=1, max_value=130))
    def test_all_proofs_verify_for_any_size(self, n):
        leaves = _leaves(n)
        tree = MerkleTree(leaves)
        root = tree.root
        for i in range(n):
            assert tree.inclusion_proof(i).verify(root) is True

    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(n=st.integers(min_value=2, max_value=64), seed=st.integers(0, 255))
    def test_any_single_byte_flip_detected(self, n, seed):
        leaves = _leaves(n)
        tree = MerkleTree(leaves)
        root = tree.root
        i = seed % n
        proof = tree.inclusion_proof(i)
        flipped = bytearray(proof.leaf_hash)
        flipped[seed % 32] ^= 0x01
        if bytes(flipped) == proof.leaf_hash:  # pragma: no cover - xor always flips
            return
        tampered = InclusionProof(
            leaf_index=proof.leaf_index,
            tree_size=proof.tree_size,
            leaf_hash=bytes(flipped),
            merkle_path=proof.merkle_path,
            merkle_path_directions=proof.merkle_path_directions,
        )
        assert tampered.verify(root) is False

    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(n=st.integers(min_value=1, max_value=128))
    def test_root_stable_under_rebuild(self, n):
        leaves = _leaves(n)
        assert MerkleTree(leaves).root == MerkleTree(list(leaves)).root
