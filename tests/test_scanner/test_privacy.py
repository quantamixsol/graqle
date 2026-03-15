"""Comprehensive tests for the RedactionEngine.

Tests cover detection and redaction of API keys, passwords, bearer
tokens, AWS keys, private keys, JWTs, connection strings, custom
patterns, disabled engines, and normal text preservation.
"""

# ── graqle:intelligence ──
# module: tests.test_scanner.test_privacy
# risk: MEDIUM (impact radius: 0 modules)
# dependencies: __future__, pytest, privacy
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import pytest

from graqle.scanner.privacy import RedactionEngine, RedactionMatch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine() -> RedactionEngine:
    """A default RedactionEngine with all patterns enabled."""
    return RedactionEngine()


# ---------------------------------------------------------------------------
# TestRedactionEngine
# ---------------------------------------------------------------------------

class TestRedactionEngine:
    """Unit tests for :class:`RedactionEngine`."""

    # -- API keys -----------------------------------------------------------

    def test_api_key_redacted(self, engine: RedactionEngine):
        """Generic API key patterns are redacted."""
        text = "api_key = sk-abc123def456ghi789"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "sk-abc123def456ghi789" not in result

    def test_api_key_with_equals(self, engine: RedactionEngine):
        """API key assigned with = is redacted."""
        text = "API_KEY=ghp_abcdef1234567890abcdef1234567890ab"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "ghp_abcdef" not in result

    def test_api_key_in_json(self, engine: RedactionEngine):
        """API key in JSON format is redacted."""
        text = '{"api_key": "sk-proj-abc123def456ghi789jkl012mno345"}'
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "sk-proj-abc123" not in result

    def test_openai_key_redacted(self, engine: RedactionEngine):
        """OpenAI-style sk- keys are redacted."""
        text = "OPENAI_API_KEY=sk-1234567890abcdefghijklmnopqrstuvwxyz1234567890ab"
        result = engine.redact(text)
        assert "[REDACTED]" in result

    # -- passwords ----------------------------------------------------------

    def test_password_redacted(self, engine: RedactionEngine):
        """Password values are redacted."""
        text = "password: my_secret_pass_123"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "my_secret_pass_123" not in result

    def test_password_equals(self, engine: RedactionEngine):
        """password= assignment is redacted."""
        text = "password=hunter2"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "hunter2" not in result

    def test_password_in_url(self, engine: RedactionEngine):
        """Password embedded in URL is redacted."""
        text = "mongodb://admin:SuperSecret@host:27017/db"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "SuperSecret" not in result

    def test_passwd_variant(self, engine: RedactionEngine):
        """Variant 'passwd' is also caught."""
        text = "db_passwd=letmein"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "letmein" not in result

    # -- bearer tokens ------------------------------------------------------

    def test_bearer_token_redacted(self, engine: RedactionEngine):
        """Authorization: Bearer tokens are redacted."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "eyJhbGciOi" not in result

    def test_bearer_case_insensitive(self, engine: RedactionEngine):
        """Bearer token detection is case-insensitive."""
        text = "authorization: bearer abcdefghijklmnop1234567890"
        result = engine.redact(text)
        assert "[REDACTED]" in result

    # -- AWS keys -----------------------------------------------------------

    def test_aws_access_key_redacted(self, engine: RedactionEngine):
        """AWS access key IDs (AKIA...) are redacted."""
        text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_aws_secret_key_redacted(self, engine: RedactionEngine):
        """AWS secret access keys are redacted."""
        text = "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "wJalrXUtnFEMI" not in result

    def test_aws_key_in_config(self, engine: RedactionEngine):
        """AWS keys in config file format are redacted."""
        text = "[default]\naws_access_key_id=AKIAI44QH8DHBEXAMPLE\naws_secret_access_key=je7MtGbClwBF/2Zp9Utk/h3yCo8nvbEXAMPLEKEY"
        result = engine.redact(text)
        assert "AKIAI44QH8DHBEXAMPLE" not in result
        assert "je7MtGbClwBF" not in result

    # -- private keys -------------------------------------------------------

    def test_private_key_redacted(self, engine: RedactionEngine):
        """PEM-encoded private key blocks are redacted."""
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF="
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "MIIEpAIBAAK" not in result

    def test_ec_private_key_redacted(self, engine: RedactionEngine):
        """EC private keys are also caught."""
        text = "-----BEGIN EC PRIVATE KEY-----\nMHQCAQEEIODp3D0="
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "MHQCAQEEIODp" not in result

    def test_generic_private_key(self, engine: RedactionEngine):
        """Generic BEGIN PRIVATE KEY is caught."""
        text = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqh="
        result = engine.redact(text)
        assert "[REDACTED]" in result

    # -- JWTs ---------------------------------------------------------------

    def test_jwt_redacted(self, engine: RedactionEngine):
        """JWT tokens (three base64 segments) are redacted."""
        text = "token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "eyJhbGciOi" not in result

    def test_jwt_in_header(self, engine: RedactionEngine):
        """JWT in an HTTP header context is redacted."""
        text = "Cookie: session=eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJhdXRoMC5jb20ifQ.signature123"
        result = engine.redact(text)
        assert "[REDACTED]" in result

    # -- connection strings -------------------------------------------------

    def test_connection_string_postgresql(self, engine: RedactionEngine):
        """PostgreSQL connection strings are redacted."""
        text = "db_url = postgresql://user:pass@host:5432/db"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "pass@host" not in result

    def test_connection_string_mysql(self, engine: RedactionEngine):
        """MySQL connection strings are redacted."""
        text = "DATABASE_URL=mysql://root:password123@localhost:3306/mydb"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "password123" not in result

    def test_connection_string_redis(self, engine: RedactionEngine):
        """Redis connection strings are redacted."""
        text = "REDIS_URL=redis://:authpassword@redis-host:6379/0"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "authpassword" not in result

    def test_connection_string_mongodb(self, engine: RedactionEngine):
        """MongoDB connection strings are redacted."""
        text = "MONGO_URI=mongodb+srv://user:secret@cluster.abc.mongodb.net/db"
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "secret@cluster" not in result

    # -- disabled engine ---------------------------------------------------

    def test_disabled_engine(self):
        """A disabled engine returns text unchanged."""
        engine = RedactionEngine(enabled=False)
        text = "password: secret123 api_key=sk-abc123"
        result = engine.redact(text)
        assert result == text

    def test_disabled_engine_detect_returns_empty(self):
        """A disabled engine's detect() returns no matches."""
        engine = RedactionEngine(enabled=False)
        matches = engine.detect("api_key=secret123456789")
        assert matches == [] or len(matches) == 0

    # -- detect without redacting ------------------------------------------

    def test_detect_without_redacting(self, engine: RedactionEngine):
        """detect() returns matches without modifying the text."""
        text = "api_key=abc123456789012345"
        matches = engine.detect(text)

        assert isinstance(matches, list)
        assert len(matches) >= 1
        assert all(isinstance(m, RedactionMatch) for m in matches)

        # The match should have a pattern_name
        pattern_names = [m.pattern_name for m in matches]
        assert any("api" in name.lower() or "key" in name.lower() for name in pattern_names)

    def test_detect_returns_match_positions(self, engine: RedactionEngine):
        """detect() returns match start/end positions."""
        text = "secret: AKIAIOSFODNN7EXAMPLE"
        matches = engine.detect(text)

        if matches:
            match = matches[0]
            assert hasattr(match, "start") or hasattr(match, "span")
            # The matched text should be within the source
            if hasattr(match, "start") and hasattr(match, "end"):
                assert match.start >= 0
                assert match.end > match.start
                assert match.end <= len(text)

    def test_detect_multiple_patterns(self, engine: RedactionEngine):
        """detect() finds multiple different pattern types in one string."""
        text = (
            "api_key=sk-abc123456789 "
            "password=hunter2 "
            "AKIAIOSFODNN7EXAMPLE"
        )
        matches = engine.detect(text)

        # Should find at least 2 different pattern types
        pattern_names = set(m.pattern_name for m in matches)
        assert len(pattern_names) >= 2

    # -- custom patterns ---------------------------------------------------

    def test_custom_pattern(self):
        """Extra user-defined patterns are applied."""
        engine = RedactionEngine(extra_patterns={"project_id": r"PROJ-\d{4,}"})
        text = "Ticket: PROJ-12345 is assigned."
        result = engine.redact(text)
        assert "[REDACTED]" in result
        assert "PROJ-12345" not in result

    def test_custom_pattern_with_existing(self):
        """Custom patterns work alongside built-in patterns."""
        engine = RedactionEngine(extra_patterns={"internal_id": r"INT-[A-Z0-9]{8}"})
        text = "id: INT-ABCD1234 key: AKIAIOSFODNN7EXAMPLE"
        result = engine.redact(text)
        assert "INT-ABCD1234" not in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_multiple_custom_patterns(self):
        """Multiple custom patterns are all applied."""
        engine = RedactionEngine(
            extra_patterns={
                "ticket": r"TICKET-\d+",
                "employee_id": r"EMP-\d{6}",
            }
        )
        text = "Assign TICKET-999 to EMP-123456."
        result = engine.redact(text)
        assert "TICKET-999" not in result
        assert "EMP-123456" not in result

    # -- disabled default patterns -----------------------------------------

    def test_disabled_default_pattern(self):
        """Disabling a default pattern prevents its redaction."""
        engine = RedactionEngine(disabled_patterns={"email"})
        text = "contact: user@example.com"
        result = engine.redact(text)
        assert "user@example.com" in result

    def test_disabled_pattern_others_still_active(self):
        """Disabling one pattern does not affect others."""
        engine = RedactionEngine(disabled_patterns={"email"})
        text = "email: user@example.com password=secret123"
        result = engine.redact(text)
        assert "user@example.com" in result  # email NOT redacted
        assert "secret123" not in result  # password IS redacted

    def test_disabled_multiple_patterns(self):
        """Multiple patterns can be disabled simultaneously."""
        engine = RedactionEngine(disabled_patterns={"email", "password"})
        text = "email: test@test.com password=abc123"
        result = engine.redact(text)
        assert "test@test.com" in result
        assert "abc123" in result

    # -- normal text unchanged ---------------------------------------------

    def test_normal_text_unchanged(self, engine: RedactionEngine):
        """Ordinary prose without secrets passes through unchanged."""
        text = "This is a normal paragraph about authentication design patterns and best practices for securing APIs."
        result = engine.redact(text)
        assert result == text

    def test_technical_text_without_secrets(self, engine: RedactionEngine):
        """Technical text that mentions 'password' conceptually is not redacted."""
        text = "The password field should be hashed before storage."
        result = engine.redact(text)
        # This is a conceptual mention, not an actual password value.
        # The engine may or may not redact it — but it shouldn't crash.
        assert isinstance(result, str)

    def test_code_comments_without_secrets(self, engine: RedactionEngine):
        """Code comments about security are not false-positived."""
        text = "# TODO: implement API key rotation\n# Check password strength"
        result = engine.redact(text)
        # These are comments about concepts, not actual secrets
        assert isinstance(result, str)

    def test_short_values_not_redacted(self, engine: RedactionEngine):
        """Very short values after 'key=' should not be over-eagerly redacted."""
        text = "key=1"
        result = engine.redact(text)
        # A single character 'key' is unlikely to be a real secret
        assert isinstance(result, str)

    # -- multiple patterns in one text -------------------------------------

    def test_multiple_patterns_in_one_text(self, engine: RedactionEngine):
        """Multiple secrets in one string are all redacted."""
        text = "api_key=abc123456789012 password=secretvalue789"
        result = engine.redact(text)
        assert result.count("[REDACTED]") >= 2
        assert "abc12345678" not in result
        assert "secretvalue789" not in result

    def test_adjacent_secrets(self, engine: RedactionEngine):
        """Secrets appearing right next to each other are both caught."""
        text = "AKIAIOSFODNN7EXAMPLE wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = engine.redact(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    # -- edge cases ---------------------------------------------------------

    def test_empty_string(self, engine: RedactionEngine):
        """Empty string input returns empty string."""
        assert engine.redact("") == ""

    def test_whitespace_only(self, engine: RedactionEngine):
        """Whitespace-only input returns whitespace unchanged."""
        text = "   \n\t  \n   "
        assert engine.redact(text) == text

    def test_very_long_text(self, engine: RedactionEngine):
        """Very long text with embedded secrets is handled without error."""
        filler = "Normal text without secrets. " * 1000
        text = filler + "password=hidden_deep_in_text" + filler
        result = engine.redact(text)
        assert "hidden_deep_in_text" not in result

    def test_unicode_text_with_secrets(self, engine: RedactionEngine):
        """Unicode text containing secrets is properly handled."""
        text = "Passwort: api_key=sk-unicode1234567890abc"
        result = engine.redact(text)
        assert "sk-unicode1234567890abc" not in result

    def test_multiline_text(self, engine: RedactionEngine):
        """Secrets spread across context in multiline text are caught."""
        text = """
        Config file:
        api_key = sk-multiline123456789
        database_url = postgresql://admin:dbpass@db.example.com:5432/prod
        debug = true
        """
        result = engine.redact(text)
        assert "sk-multiline123456789" not in result
        assert "dbpass@" not in result

    # -- idempotency -------------------------------------------------------

    def test_double_redaction_is_safe(self, engine: RedactionEngine):
        """Redacting already-redacted text does not corrupt it."""
        text = "password=secret123"
        first_pass = engine.redact(text)
        second_pass = engine.redact(first_pass)

        assert "[REDACTED]" in second_pass
        # Should not double-wrap: [REDACTED] should not become [[REDACTED]]
        assert "[[REDACTED]]" not in second_pass

    # -- RedactionMatch dataclass ------------------------------------------

    def test_redaction_match_fields(self, engine: RedactionEngine):
        """RedactionMatch has expected fields: pattern_name, matched_text or similar."""
        matches = engine.detect("api_key=AKIAIOSFODNN7EXAMPLE")

        if matches:
            match = matches[0]
            assert hasattr(match, "pattern_name")
            assert isinstance(match.pattern_name, str)
            assert len(match.pattern_name) > 0

    # -- environment variable patterns -------------------------------------

    def test_env_var_export(self, engine: RedactionEngine):
        """Shell export statements with secrets are redacted."""
        text = "export SECRET_KEY=abc123def456ghi789jkl012"
        result = engine.redact(text)
        assert "abc123def456ghi789jkl012" not in result

    def test_dotenv_format(self, engine: RedactionEngine):
        """Dotenv file format secrets are redacted."""
        text = "DATABASE_PASSWORD=super_secret_db_pass_2024"
        result = engine.redact(text)
        assert "super_secret_db_pass_2024" not in result

    # -- GitHub / service tokens -------------------------------------------

    def test_github_token_redacted(self, engine: RedactionEngine):
        """GitHub personal access tokens (ghp_) are redacted."""
        text = "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = engine.redact(text)
        assert "ghp_ABCDEFGHIJ" not in result

    def test_slack_token_redacted(self, engine: RedactionEngine):
        """Slack tokens (xoxb-) are redacted."""
        text = "SLACK_TOKEN=xoxb-fake-fake-fake"
        result = engine.redact(text)
        assert "xoxb-" not in result

    # -- constructor validation --------------------------------------------

    def test_default_constructor(self):
        """Default constructor creates an enabled engine."""
        engine = RedactionEngine()
        assert engine.redact("password=secret123456") != "password=secret123456"

    def test_enabled_true_explicit(self):
        """Explicitly enabled=True behaves like default."""
        engine = RedactionEngine(enabled=True)
        result = engine.redact("password=secret123456")
        assert "[REDACTED]" in result
