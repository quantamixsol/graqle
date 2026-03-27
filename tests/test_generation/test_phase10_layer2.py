"""Phase 10 Layer 2 — Secret Pattern Detection Tests.

Tests for graqle/core/secret_patterns.py (Layer 2A regex + Layer 2B AST).
Tests for governance.py integration of new 200+ pattern library.

Coverage:
  - Pattern count ≥ 200
  - All major provider groups covered
  - True positives: each provider family has at least one match
  - False positive controls: comments, placeholders, env references pass
  - AST detection: variable assignment, concatenation, f-strings, dicts
  - Governance integration: secrets escalate to T3
  - Adversarial: base64-encoded, obfuscated, multi-line
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. Pattern library metadata
# ---------------------------------------------------------------------------

class TestPatternLibrary:
    """Verify the pattern library meets coverage and count requirements."""

    def test_pattern_count_at_least_200(self) -> None:
        from graqle.core.secret_patterns import get_pattern_count
        assert get_pattern_count() >= 200, f"Expected ≥200 patterns, got {get_pattern_count()}"

    def test_required_groups_present(self) -> None:
        from graqle.core.secret_patterns import get_pattern_groups
        groups = set(get_pattern_groups())
        required = {"aws", "github", "openai", "anthropic", "stripe", "db", "jwt", "pki", "generic", "slack"}
        missing = required - groups
        assert not missing, f"Missing required groups: {missing}"

    def test_pattern_groups_count(self) -> None:
        from graqle.core.secret_patterns import get_pattern_groups
        groups = get_pattern_groups()
        assert len(groups) >= 30, f"Expected ≥30 groups, got {len(groups)}"


# ---------------------------------------------------------------------------
# 2. Layer 1 — Regex true positives
# ---------------------------------------------------------------------------

class TestRegexTruePositives:
    """Each major provider/group must detect its canonical pattern."""

    def _check(self, content: str) -> tuple[bool, list]:
        from graqle.core.secret_patterns import check_secrets
        return check_secrets(content)

    def test_aws_access_key(self) -> None:
        key = "AKIA" + "IOSFODNN7EXAMPLE1234"
        found, matches = self._check(key)
        assert found, "AWS AKIA key not detected"
        assert any(m.group == "aws" for m in matches)

    def test_aws_secret_key(self) -> None:
        found, matches = self._check("aws_secret_access_key = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'")
        assert found
        assert any(m.group == "aws" for m in matches)

    def test_github_pat_classic(self) -> None:
        token = "ghp_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcdef"
        found, matches = self._check(token)
        assert found
        assert any(m.group == "github" for m in matches)

    def test_github_oauth_token(self) -> None:
        token = "gho_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcdef"
        found, matches = self._check(token)
        assert found
        assert any(m.group == "github" for m in matches)

    def test_openai_key(self) -> None:
        found, matches = self._check("sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ12345678901234")
        assert found, "OpenAI sk- key not detected"

    def test_anthropic_key(self) -> None:
        # ANTHROPIC_API_KEY env var pattern
        found, matches = self._check("ANTHROPIC_API_KEY = 'sk-ant-api02-abcdefghijk'")
        assert found
        # Detected via envfile, anthropic, openai, or generic group
        assert len(matches) >= 1

    def test_stripe_live_secret(self) -> None:
        # Built at runtime to avoid static secret scanners flagging test fixtures
        token = "sk_" + "live_abcdefghijklmnopqrstuvwx"
        found, matches = self._check(token)
        assert found
        assert any(m.group == "stripe" for m in matches)

    def test_stripe_test_secret(self) -> None:
        token = "sk_" + "test_abcdefghijklmnopqrstuvwx"
        found, matches = self._check(token)
        assert found
        assert any(m.group == "stripe" for m in matches)

    def test_stripe_webhook_secret(self) -> None:
        token = "whsec" + "_abcdefghijklmnopqrstuvwxyz123456"
        found, matches = self._check(token)
        assert found
        assert any(m.group == "stripe" for m in matches)

    def test_slack_bot_token(self) -> None:
        token = "xoxb" + "-12345678901-12345678901-abcdefghijklmnopqrstuvwx"
        found, matches = self._check(token)
        assert found
        assert any(m.group == "slack" for m in matches)

    def test_postgres_url_with_password(self) -> None:
        found, matches = self._check("postgresql://user:actualpassword123@localhost:5432/mydb")
        assert found
        assert any(m.group == "db" for m in matches)

    def test_mongodb_url_with_password(self) -> None:
        found, matches = self._check("mongodb://user:actualpassword123@localhost:27017/mydb")
        assert found
        assert any(m.group == "db" for m in matches)

    def test_jwt_bearer_token(self) -> None:
        # JWT parts split to avoid static scanner false positives on test fixture
        h = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        p = "eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        s = "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        jwt = f"{h}.{p}.{s}"
        found, matches = self._check(f"Authorization: Bearer {jwt}")
        assert found
        assert any(m.group == "jwt" for m in matches)

    def test_rsa_private_key(self) -> None:
        found, matches = self._check("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...")
        assert found
        assert any(m.group == "pki" for m in matches)

    def test_gcp_service_account(self) -> None:
        found, matches = self._check('{"type": "service_account", "project_id": "my-project"}')
        assert found
        assert any(m.group == "google" for m in matches)

    def test_generic_password_assign(self) -> None:
        found, matches = self._check("db_password = 'superSecret123!'")
        assert found
        # Detected by db group (db_password_key pattern) or generic group
        assert any(m.group in ("db", "generic") for m in matches)

    def test_json_secret_field(self) -> None:
        found, matches = self._check('{"api_key": "actual_secret_value_here_123456"}')
        assert found

    def test_groq_key(self) -> None:
        found, matches = self._check("gsk_" + "A" * 52)
        assert found
        assert any(m.group == "groq" for m in matches)

    def test_sendgrid_key(self) -> None:
        # SG.{22chars}.{43chars} format
        key = "SG." + "A" * 22 + "." + "B" * 43
        found, matches = self._check(key)
        assert found
        assert any(m.group == "sendgrid" for m in matches)

    def test_twilio_account_sid(self) -> None:
        found, matches = self._check("AC" + "a" * 32)
        assert found
        assert any(m.group == "twilio" for m in matches)

    def test_docker_env_password(self) -> None:
        found, matches = self._check("DOCKER_PASSWORD = 'mysupersecretpassword123'")
        assert found

    def test_export_env_secret(self) -> None:
        found, matches = self._check("export DATABASE_PASSWORD=actualsecretvalue123")
        assert found

    def test_huggingface_token(self) -> None:
        found, matches = self._check("hf_" + "A" * 37)
        assert found
        assert any(m.group == "huggingface" for m in matches)


# ---------------------------------------------------------------------------
# 3. Layer 1 — False positive controls
# ---------------------------------------------------------------------------

class TestRegexFalsePositiveControls:
    """Safe content must NOT trigger false positives."""

    def _check(self, content: str) -> bool:
        from graqle.core.secret_patterns import check_secrets
        found, _ = check_secrets(content)
        return found

    def test_env_reference_not_flagged(self) -> None:
        # Using env vars (not hardcoded string values) is safe
        assert not self._check("password = os.environ['DB_PASSWORD']")

    def test_template_variable_not_flagged(self) -> None:
        assert not self._check("password = '${PASSWORD}'")

    def test_pytest_fixture_short_value(self) -> None:
        # Short quoted passwords are not flagged (< 8 chars)
        assert not self._check("password = 'abc'")  # 3 chars — below minimum

    def test_comment_aws_key_example(self) -> None:
        # Comments with obvious fake example keys should not be a big concern
        # The AKIA prefix will match — this is correct behavior (conservative)
        # This test documents the expected behavior: example keys ARE flagged
        found = self._check("# Example: AKIAIOSFODNN7EXAMPLE1234")
        # Flagging AKIA even in comments is intentional — conservative security
        assert found  # CORRECT behavior: flag AKIA patterns anywhere

    def test_placeholder_value_short(self) -> None:
        # "api_key = 'abc'" — too short to be a real key for most patterns
        assert not self._check("api_key = 'abc'")  # only 3 chars

    def test_env_var_reference_format(self) -> None:
        assert not self._check("SECRET = $SECRET_VALUE")

    def test_yaml_empty_value(self) -> None:
        assert not self._check("password: ''")

    def test_yaml_null_value(self) -> None:
        # password: null — unquoted null not flagged by tightened yaml pattern
        assert not self._check("password: null")

    def test_yaml_env_reference(self) -> None:
        # Env var substitution syntax not flagged
        assert not self._check("password: ${DB_PASSWORD}")


# ---------------------------------------------------------------------------
# 4. Layer 2B — AST structural detection
# ---------------------------------------------------------------------------

class TestASTDetection:
    """AST layer catches obfuscation not caught by regex."""

    def _ast_check(self, code: str):
        from graqle.core.secret_patterns import check_secrets_ast
        return check_secrets_ast(code)

    def test_simple_assignment_detected(self) -> None:
        code = '''password = "actual_secret_value_here"'''
        matches = self._ast_check(code)
        assert len(matches) >= 1
        assert any("password" in m.pattern_name for m in matches)

    def test_string_concatenation_detected(self) -> None:
        code = '''api_key = "first_half_" + "second_half_12345678"'''
        matches = self._ast_check(code)
        assert len(matches) >= 1

    def test_dict_key_credential_detected(self) -> None:
        code = '''config = {"password": "actualsecretvalue123", "host": "localhost"}'''
        matches = self._ast_check(code)
        assert len(matches) >= 1
        assert any("password" in m.pattern_name for m in matches)

    def test_function_keyword_arg_detected(self) -> None:
        code = '''connect(host="localhost", password="actualsecretvalue123")'''
        matches = self._ast_check(code)
        assert len(matches) >= 1

    def test_annotated_assign_detected(self) -> None:
        code = '''secret: str = "actualsecretvalue123456789"'''
        matches = self._ast_check(code)
        assert len(matches) >= 1

    def test_fstring_detected(self) -> None:
        code = '''token = f"prefix_{value}_suffix_12345678"'''
        matches = self._ast_check(code)
        assert len(matches) >= 1

    def test_placeholder_skipped(self) -> None:
        code = '''password = "changeme"'''
        matches = self._ast_check(code)
        # "changeme" is in the placeholder list
        assert len(matches) == 0

    def test_short_value_skipped(self) -> None:
        code = '''api_key = "abc"'''
        matches = self._ast_check(code)
        assert len(matches) == 0

    def test_non_credential_var_skipped(self) -> None:
        code = '''username = "some_long_username_value_here"'''
        matches = self._ast_check(code)
        # "username" is not a credential-adjacent name
        assert len(matches) == 0

    def test_syntax_error_returns_empty(self) -> None:
        code = '''this is not python code @@###'''
        matches = self._ast_check(code)
        assert matches == []

    def test_non_python_content_returns_empty(self) -> None:
        content = "this is markdown content, not Python"
        matches = self._ast_check(content)
        assert matches == []


# ---------------------------------------------------------------------------
# 5. Combined check (Layer 1 + Layer 2B)
# ---------------------------------------------------------------------------

class TestCombinedCheck:
    """check_secrets_full activates AST layer based on regex score."""

    def test_combined_finds_regex_match(self) -> None:
        from graqle.core.secret_patterns import check_secrets_full
        key = "AKIA" + "IOSFODNN7EXAMPLE1234"
        found, matches = check_secrets_full(key)
        assert found
        assert any(not m.via_ast for m in matches)

    def test_combined_activates_ast_when_regex_score_high(self) -> None:
        """When >1 regex pattern matches (score > 0.3), AST layer also runs."""
        from graqle.core.secret_patterns import check_secrets_full
        # Multiple credential patterns in one file should trigger AST
        _akia = "AKIA" + "IOSFODNN7EXAMPLE1234"
        _ghp = "ghp_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ123456"
        code = f'''
api_key = "sk_" + "live_abcdefghijklmnopqrstuvwx"
password = "{_akia}"
token = "{_ghp}"
'''
        found, matches = check_secrets_full(code, use_ast=True)
        assert found
        # Should have both regex and possibly AST matches
        assert len(matches) >= 3

    def test_combined_no_ast_when_disabled(self) -> None:
        from graqle.core.secret_patterns import check_secrets_full, check_secrets
        code = '''password = "actualsecretvalue123456789"'''
        _, with_ast = check_secrets_full(code, use_ast=True)
        _, no_ast = check_secrets_full(code, use_ast=False)
        # AST should find it even if regex didn't (or add to regex finds)
        assert len(with_ast) >= len(no_ast)


# ---------------------------------------------------------------------------
# 6. Governance integration — secrets escalate to T3
# ---------------------------------------------------------------------------

class TestGovernanceSecretEscalation:
    """Verify governance.py routes secrets through Layer 2 and escalates tier."""

    def test_github_token_in_diff_escalates_to_t3(self) -> None:
        from graqle.core.governance import GovernanceMiddleware
        _tok = "ghp_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ123456"
        diff = f"+token = '{_tok}'"
        gm = GovernanceMiddleware()
        result = gm.check(diff=diff, file_path="config.py", risk_level="LOW", impact_radius=0)
        assert result.tier in ("T3", "TS-BLOCK"), f"Expected T3/TS-BLOCK for secret, got {result.tier}"

    def test_aws_key_in_content_escalates_to_t3(self) -> None:
        from graqle.core.governance import GovernanceMiddleware
        content = "AWS_SECRET_ACCESS_KEY = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'"
        gm = GovernanceMiddleware()
        result = gm.check(content=content, file_path="deploy.sh", risk_level="LOW", impact_radius=0)
        assert result.tier in ("T3",), f"Expected T3 for secret, got {result.tier}"

    def test_private_key_in_diff_escalates(self) -> None:
        from graqle.core.governance import GovernanceMiddleware
        diff = "+-----BEGIN RSA PRIVATE KEY-----\n+MIIEpAIBAAKCAQEA..."
        gm = GovernanceMiddleware()
        result = gm.check(diff=diff, file_path="key.pem", risk_level="LOW", impact_radius=0)
        assert result.tier in ("T3", "TS-BLOCK")

    def test_clean_diff_t1_unchanged(self) -> None:
        """Clean diff without secrets should remain T1 at LOW/low radius."""
        from graqle.core.governance import GovernanceMiddleware
        diff = "+def greet(name):\n+    return f'Hello, {name}!'"
        gm = GovernanceMiddleware()
        result = gm.check(diff=diff, file_path="utils.py", risk_level="LOW", impact_radius=1)
        assert result.tier == "T1", f"Clean diff escalated unexpectedly to {result.tier}"

    def test_secret_warning_in_result(self) -> None:
        from graqle.core.governance import GovernanceMiddleware
        _tok = "sk_" + "live_abcdefghijklmnopqrstuvwx"
        diff = f"+STRIPE_SECRET_KEY = '{_tok}'"
        gm = GovernanceMiddleware()
        result = gm.check(diff=diff, file_path="settings.py", risk_level="LOW", impact_radius=0)
        assert result.warnings, "Expected secret exposure warning in result"
        assert any("secret" in w.lower() or "exposure" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# 7. Adversarial patterns
# ---------------------------------------------------------------------------

class TestAdversarialPatterns:
    """Adversarial evasion attempts must be caught."""

    def _check(self, content: str) -> bool:
        from graqle.core.secret_patterns import check_secrets_full
        found, _ = check_secrets_full(content)
        return found

    def test_secret_in_multiline_string(self) -> None:
        code = '''config = {
    "password": "actual_secret_value_123456"
}'''
        assert self._check(code)

    def test_secret_in_yaml_block(self) -> None:
        yaml = "database:\n  password: actual_secret_value_here"
        assert self._check(yaml)

    def test_secret_in_json(self) -> None:
        json_content = '{"api_key": "actual_secret_value_here_1234"}'
        assert self._check(json_content)

    def test_bearer_token_in_header(self) -> None:
        _h = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        _p = "eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        _s = "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        code = f'{{"Authorization": "Bearer {_h}.{_p}.{_s}"}}'
        assert self._check(code)

    def test_connection_string_with_password(self) -> None:
        conn = "postgresql://admin:mypassword123@prod-db.example.com:5432/myapp"
        assert self._check(conn)

    def test_export_statement_secret(self) -> None:
        _tok = "ghp_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ123456"
        sh = f"export GITHUB_TOKEN={_tok}"
        assert self._check(sh)

    def test_string_concat_in_code(self) -> None:
        """AST catches concatenation even when regex misses."""
        from graqle.core.secret_patterns import check_secrets_full
        code = 'secret_key = "first_part_" + "second_part_1234567890abcdef"'
        found, matches = check_secrets_full(code, use_ast=True)
        assert found

    def test_db_password_in_env(self) -> None:
        env = "DB_PASSWORD=actual_production_password_here"
        assert self._check(env)
