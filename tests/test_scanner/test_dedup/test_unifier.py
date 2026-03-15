"""Tests for entity unifier — cross-source name matching."""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_dedup.test_unifier
# risk: LOW (impact radius: 0 modules)
# dependencies: unifier
# constraints: none
# ── /graqle:intelligence ──

from graqle.scanner.dedup.unifier import EntityUnifier, _tokenise


class TestTokenise:
    """Tests for the _tokenise helper."""

    def test_snake_case(self):
        assert _tokenise("verify_token") == ["verify", "token"]

    def test_camel_case(self):
        assert _tokenise("verifyToken") == ["verify", "token"]

    def test_pascal_case(self):
        assert _tokenise("VerifyToken") == ["verify", "token"]

    def test_kebab_case(self):
        assert _tokenise("verify-token") == ["verify", "token"]

    def test_dot_case(self):
        # Dot is treated as file extension separator — strips last segment
        assert _tokenise("verify.token") == ["verify"]
        # But multi-dot works via intermediate splits
        assert _tokenise("my.verify.token") == ["my", "verify"]

    def test_file_extension_stripped(self):
        tokens = _tokenise("auth_service.py")
        assert "auth" in tokens
        assert "service" in tokens
        assert "py" not in tokens

    def test_path_segments(self):
        tokens = _tokenise("src/auth/service")
        assert "src" in tokens
        assert "auth" in tokens
        assert "service" in tokens

    def test_single_short_token_filtered(self):
        # Tokens < 2 chars are filtered
        assert _tokenise("a") == []

    def test_mixed_delimiters(self):
        tokens = _tokenise("my-auth_service.handler")
        assert "auth" in tokens
        assert "service" in tokens


class TestEntityUnifier:
    """Tests for EntityUnifier."""

    def test_register_and_match_cross_source(self):
        """Code node 'verify_token' matches document node 'verifyToken'."""
        unifier = EntityUnifier()
        unifier.register("code::verify_token", "verify_token", "code")
        unifier.register("doc::verifyToken", "verifyToken", "document")

        nodes = {
            "code::verify_token": {"label": "verify_token", "entity_type": "FUNCTION"},
            "doc::verifyToken": {"label": "verifyToken", "entity_type": "SECTION"},
        }
        matches = unifier.find_matches(nodes)
        assert len(matches) >= 1
        # Code should be primary (higher authority)
        primary, secondary, confidence = matches[0]
        assert primary == "code::verify_token"
        assert secondary == "doc::verifyToken"
        assert confidence > 0

    def test_no_match_same_source(self):
        """Two code nodes with same name should NOT match (same source type)."""
        unifier = EntityUnifier()
        unifier.register("code::a", "verify_token", "code")
        unifier.register("code::b", "verify_token", "code")

        nodes = {
            "code::a": {"label": "verify_token", "entity_type": "FUNCTION"},
            "code::b": {"label": "verify_token", "entity_type": "FUNCTION"},
        }
        matches = unifier.find_matches(nodes)
        assert len(matches) == 0

    def test_case_insensitive_matching(self):
        unifier = EntityUnifier(case_insensitive=True)
        unifier.register("code::auth", "AuthService", "code")
        unifier.register("doc::auth", "authservice", "document")

        nodes = {
            "code::auth": {"label": "AuthService", "entity_type": "CLASS"},
            "doc::auth": {"label": "authservice", "entity_type": "SECTION"},
        }
        matches = unifier.find_matches(nodes)
        assert len(matches) >= 1

    def test_no_naming_conventions(self):
        """With naming_conventions=False, only exact (possibly case-insensitive) match."""
        unifier = EntityUnifier(naming_conventions=False, case_insensitive=False)
        unifier.register("code::a", "verify_token", "code")
        unifier.register("doc::b", "verifyToken", "document")

        nodes = {
            "code::a": {"label": "verify_token"},
            "doc::b": {"label": "verifyToken"},
        }
        matches = unifier.find_matches(nodes)
        assert len(matches) == 0

    def test_source_priority_ordering(self):
        """api_spec has higher priority than document."""
        unifier = EntityUnifier()
        unifier.register("api::login", "login", "api_spec")
        unifier.register("doc::login", "login", "document")

        nodes = {
            "api::login": {"label": "login"},
            "doc::login": {"label": "login"},
        }
        matches = unifier.find_matches(nodes)
        assert len(matches) >= 1
        primary, secondary, _ = matches[0]
        assert primary == "api::login"
        assert secondary == "doc::login"

    def test_short_label_no_match(self):
        """Labels shorter than 2 chars produce no variants."""
        unifier = EntityUnifier()
        unifier.register("a", "x", "code")
        unifier.register("b", "x", "document")

        matches = unifier.find_matches({"a": {}, "b": {}})
        assert len(matches) == 0

    def test_multiple_matches_sorted_by_confidence(self):
        """Multiple cross-source matches are sorted by confidence descending."""
        unifier = EntityUnifier()
        unifier.register("code::auth", "auth_service", "code")
        unifier.register("doc::auth", "auth_service", "document")
        unifier.register("cfg::port", "server_port", "json_config")
        unifier.register("doc::port", "server_port", "document")

        nodes = {
            "code::auth": {"label": "auth_service"},
            "doc::auth": {"label": "auth_service"},
            "cfg::port": {"label": "server_port"},
            "doc::port": {"label": "server_port"},
        }
        matches = unifier.find_matches(nodes)
        assert len(matches) >= 2
        # Should be sorted by confidence desc
        confidences = [m[2] for m in matches]
        assert confidences == sorted(confidences, reverse=True)

    def test_kebab_to_snake_match(self):
        """kebab-case code matches snake_case document."""
        unifier = EntityUnifier()
        unifier.register("code::a", "auth-handler", "code")
        unifier.register("doc::a", "auth_handler", "document")

        nodes = {
            "code::a": {"label": "auth-handler"},
            "doc::a": {"label": "auth_handler"},
        }
        matches = unifier.find_matches(nodes)
        assert len(matches) >= 1
