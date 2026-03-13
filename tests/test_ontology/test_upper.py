"""Tests for UpperOntology — domain-agnostic class hierarchy."""

import pytest

from graqle.ontology.upper import UpperOntology, UPPER_HIERARCHY


class TestUpperOntology:
    def setup_method(self):
        self.onto = UpperOntology()

    def test_default_hierarchy_has_thing(self):
        assert "Thing" in self.onto.hierarchy
        assert self.onto.hierarchy["Thing"] == ""

    def test_default_branches(self):
        branches = ["Agent", "Spatial", "Temporal", "Governance",
                     "Artifact", "Measurement", "Cognitive", "Lineage"]
        for b in branches:
            assert b in self.onto.hierarchy
            assert self.onto.hierarchy[b] == "Thing"

    def test_get_ancestors_branch(self):
        ancestors = self.onto.get_ancestors("Governance")
        assert ancestors == ["Thing"]

    def test_get_ancestors_unknown(self):
        ancestors = self.onto.get_ancestors("NONEXISTENT")
        assert ancestors == []

    def test_is_subtype_same(self):
        assert self.onto.is_subtype_of("Governance", "Governance") is True

    def test_is_subtype_branch_to_thing(self):
        assert self.onto.is_subtype_of("Governance", "Thing") is True

    def test_is_subtype_not_subtype(self):
        assert self.onto.is_subtype_of("Agent", "Governance") is False

    def test_extend(self):
        self.onto.extend({"REGULATION": "Governance", "POLICY": "Governance"})
        assert "REGULATION" in self.onto.hierarchy
        assert self.onto.is_subtype_of("REGULATION", "Governance") is True
        assert self.onto.is_subtype_of("REGULATION", "Thing") is True

    def test_get_valid_children(self):
        self.onto.extend({"REGULATION": "Governance", "POLICY": "Governance"})
        children = self.onto.get_valid_children("Governance")
        assert "REGULATION" in children
        assert "POLICY" in children

    def test_get_all_descendants(self):
        self.onto.extend({
            "REGULATION": "Governance",
            "GOV_ENFORCEMENT": "Governance",
        })
        descendants = self.onto.get_all_descendants("Thing")
        assert "Governance" in descendants
        assert "REGULATION" in descendants
        assert "GOV_ENFORCEMENT" in descendants

    def test_get_branch(self):
        self.onto.extend({"REGULATION": "Governance"})
        assert self.onto.get_branch("REGULATION") == "Governance"
        assert self.onto.get_branch("Governance") == "Governance"

    def test_is_valid_type(self):
        assert self.onto.is_valid_type("Thing") is True
        assert self.onto.is_valid_type("Governance") is True
        assert self.onto.is_valid_type("FAKE") is False

    def test_get_leaf_types(self):
        # In default upper ontology, branches have no children → they are leaves
        leaves = self.onto.get_leaf_types()
        assert "Agent" in leaves  # no children in default

    def test_normalize_type(self):
        self.onto.extend({"REGULATION": "Governance"})
        assert self.onto.normalize_type("regulation") == "REGULATION"
        assert self.onto.normalize_type("") == "UNKNOWN"

    def test_ancestors_no_infinite_loop(self):
        # Should not loop even with odd data
        onto = UpperOntology({"A": "B", "B": "A"})
        # Should terminate
        ancestors = onto.get_ancestors("A")
        assert len(ancestors) < 10  # must terminate
