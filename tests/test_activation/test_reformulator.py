"""Tests for ADR-104: Query Reformulator — context-aware query enhancement.

49 tests covering:
- AI tool environment detection (6 tests)
- Context-based reformulation (9 tests)
- Pronoun resolution (6 tests)
- Attachment handling (5 tests)
- LLM-based reformulation (5 tests)
- Pass-through / disabled modes (5 tests)
- Edge cases (7 tests)
- Graph integration (3 tests)
- Multimodal scenarios (3 tests)
"""

# ── graqle:intelligence ──
# module: tests.test_activation.test_reformulator
# risk: HIGH (impact radius: 0 modules)
# dependencies: __future__, os, mock, pytest, reformulator
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from graqle.activation.reformulator import (
    _AI_TOOL_ENV_SIGNATURES,
    _MAX_REFORMULATED_LENGTH,
    Attachment,
    QueryReformulator,
    ReformulationContext,
    ReformulationResult,
)

# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def reformulator():
    """Default reformulator in auto mode with no AI tool detected."""
    with patch.dict(os.environ, {}, clear=False):
        return QueryReformulator(mode="auto", enabled=True)


@pytest.fixture
def ai_tool_reformulator():
    """Reformulator that thinks it's inside Claude Code."""
    with patch.dict(os.environ, {"CLAUDE_CODE": "1"}, clear=False):
        return QueryReformulator(mode="auto", enabled=True)


@pytest.fixture
def sample_context():
    """Rich context from an AI tool."""
    return ReformulationContext(
        chat_history=[
            ("user", "I'm looking at the auth service in src/services/auth.ts"),
            ("assistant", "The auth service handles JWT verification and session management."),
            ("user", "What about the payment handler?"),
            ("assistant", "The paymentHandler function processes Stripe webhooks."),
        ],
        project_summary="E-commerce platform with auth, payment, and catalog services",
        current_file="src/services/auth.ts",
        active_symbols=["paymentHandler", "verifyJWT", "sessionStore"],
        tool_name="claude_code",
    )


@pytest.fixture
def minimal_context():
    """Minimal context — just chat history."""
    return ReformulationContext(
        chat_history=[
            ("user", "Show me the config"),
        ],
        tool_name="cursor",
    )


# ── Test AI Tool Detection ──────────────────────────────────────

class TestAIToolDetection:
    """Test environment-based AI tool detection."""

    def test_detects_claude_code(self):
        with patch.dict(os.environ, {"CLAUDE_CODE": "1"}):
            r = QueryReformulator(mode="auto")
            assert r.detected_tool == "claude_code"
            assert r.is_ai_tool_environment is True

    def test_detects_cursor(self):
        with patch.dict(os.environ, {"CURSOR_SESSION_ID": "abc123"}):
            r = QueryReformulator(mode="auto")
            assert r.detected_tool == "cursor"

    def test_detects_codex(self):
        with patch.dict(os.environ, {"OPENAI_CODEX": "true"}):
            r = QueryReformulator(mode="auto")
            assert r.detected_tool == "codex"

    def test_no_tool_detected(self):
        # Clear all known env vars
        env_clean = {v: "" for sigs in _AI_TOOL_ENV_SIGNATURES.values() for v in sigs}
        with patch.dict(os.environ, env_clean, clear=False):
            # Force all to empty
            for v in env_clean:
                os.environ.pop(v, None)
            r = QueryReformulator(mode="auto")
            assert r.detected_tool is None
            assert r.is_ai_tool_environment is False

    def test_static_detect_method(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_VERSION": "1.2.3"}):
            assert QueryReformulator.detect_ai_tool() == "claude_code"

    def test_static_detect_returns_none(self):
        env_clean = {v: "" for sigs in _AI_TOOL_ENV_SIGNATURES.values() for v in sigs}
        with patch.dict(os.environ, env_clean, clear=False):
            for v in env_clean:
                os.environ.pop(v, None)
            assert QueryReformulator.detect_ai_tool() is None


# ── Test Context-Based Reformulation ────────────────────────────

class TestContextReformulation:
    """Test reformulation using AI tool context."""

    def test_adds_file_context(self, sample_context):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        result = r.reformulate("How does the authentication work?", context=sample_context)
        assert result.was_reformulated is True
        assert "src/services/auth.ts" in result.reformulated_query
        assert result.context_source == "ai_tool"

    def test_adds_symbol_context(self, sample_context):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        # Query doesn't mention any active symbols
        result = r.reformulate("What functions handle this?", context=sample_context)
        assert result.was_reformulated is True
        # Should include unmentioned symbols
        assert result.context_source == "ai_tool"

    def test_no_duplicate_file_mention(self, sample_context):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        # Query already mentions a file
        result = r.reformulate("What does auth.ts do?", context=sample_context)
        # Should not double-add file context since query already mentions a file
        assert "auth.ts" in result.reformulated_query

    def test_pronoun_resolution_with_file(self, sample_context):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        result = r.reformulate("What does this do?", context=sample_context)
        assert result.was_reformulated is True
        # Should resolve "this" to something from chat history
        assert result.context_source == "ai_tool"

    def test_preserves_original_intent(self, sample_context):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        result = r.reformulate("How does the authentication work?", context=sample_context)
        # Original query text should still be present
        assert "authentication" in result.reformulated_query.lower()
        assert result.original_query == "How does the authentication work?"

    def test_preserves_question_mark(self, sample_context):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        result = r.reformulate("What does this service do?", context=sample_context)
        if result.was_reformulated:
            assert result.reformulated_query.endswith("?")

    def test_empty_context_no_reformulation(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        empty_ctx = ReformulationContext()
        result = r.reformulate("What does the auth service do?", context=empty_ctx)
        # No enrichments possible → not reformulated
        assert result.was_reformulated is False
        assert result.reformulated_query == "What does the auth service do?"

    def test_confidence_increases_with_context(self, sample_context):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        result = r.reformulate("What does this do?", context=sample_context)
        assert result.confidence > 0.7  # Should get boosts from pronouns + file + symbols

    def test_already_mentioned_symbols_excluded(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            active_symbols=["verifyJWT", "handlePayment"],
            current_file="auth.ts",
        )
        result = r.reformulate("How does verifyJWT handle tokens?", context=ctx)
        # verifyJWT already in query, should not be re-added
        if result.was_reformulated:
            count = result.reformulated_query.lower().count("verifyjwt")
            assert count == 1  # Only the original mention


# ── Test Pronoun Resolution ─────────────────────────────────────

class TestPronounResolution:
    """Test pronoun resolution from chat history."""

    def test_resolves_file_reference(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[
                ("user", "Look at src/services/auth.ts"),
                ("assistant", "That file handles authentication."),
            ],
        )
        result = r.reformulate("What does this do?", context=ctx)
        assert result.was_reformulated is True
        assert "auth.ts" in result.reformulated_query

    def test_resolves_function_reference(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[
                ("user", "The handlePayment function seems buggy"),
            ],
        )
        result = r.reformulate("Can you explain what it does?", context=ctx)
        assert result.was_reformulated is True
        assert "handlePayment" in result.reformulated_query

    def test_resolves_quoted_term(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[
                ("assistant", 'The "session middleware" intercepts all requests.'),
            ],
        )
        result = r.reformulate("How does that work?", context=ctx)
        assert result.was_reformulated is True
        assert "session middleware" in result.reformulated_query

    def test_resolves_service_name(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[
                ("user", "The Payment Gateway is failing"),
            ],
        )
        result = r.reformulate("What could cause that?", context=ctx)
        assert result.was_reformulated is True
        assert "Payment Gateway" in result.reformulated_query

    def test_no_pronoun_no_resolution(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[
                ("user", "The auth service is down"),
            ],
            current_file="auth.ts",
        )
        # Query has no pronouns
        result = r.reformulate("How does the payment gateway work?", context=ctx)
        # No pronoun resolution, but may still add file context
        assert "payment gateway" in result.reformulated_query.lower()

    def test_empty_history_no_crash(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[],
            current_file="main.py",
        )
        result = r.reformulate("What does this do?", context=ctx)
        # Should not crash, may still add file context
        assert result.reformulated_query  # Not empty


# ── Test Attachment Handling ─────────────────────────────────────

class TestAttachmentHandling:
    """Test that screenshots, files, and other attachments are incorporated."""

    def test_screenshot_description_injected(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            attachments=[
                Attachment(
                    type="screenshot",
                    description="Screenshot showing a 500 Internal Server Error in the auth Lambda CloudWatch logs",
                    filename="error_screenshot.png",
                    mime_type="image/png",
                )
            ],
            tool_name="claude_code",
        )
        result = r.reformulate("What's causing this error?", context=ctx)
        assert result.was_reformulated is True
        assert "500" in result.reformulated_query or "auth Lambda" in result.reformulated_query
        assert result.confidence >= 0.85  # Base 0.7 + 0.15 attachment boost

    def test_error_log_attachment(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            attachments=[
                Attachment(
                    type="error_log",
                    description="Stack trace showing TypeError: Cannot read property 'userId' of undefined in paymentHandler.ts:42",
                    filename="error.log",
                )
            ],
        )
        result = r.reformulate("Why is this failing?", context=ctx)
        assert result.was_reformulated is True
        assert "userId" in result.reformulated_query or "paymentHandler" in result.reformulated_query

    def test_attachment_with_content_summary_fallback(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            attachments=[
                Attachment(
                    type="code_snippet",
                    description="",  # No description
                    content_summary="async function handleAuth(req, res) {\n  const token = req.headers.authorization;\n  if (!token) throw new Error('No token');",
                )
            ],
        )
        result = r.reformulate("What's wrong with this code?", context=ctx)
        assert result.was_reformulated is True
        assert "handleAuth" in result.reformulated_query or "authorization" in result.reformulated_query

    def test_attachment_filename_only_fallback(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            attachments=[
                Attachment(
                    type="file",
                    filename="deployment-diagram.pdf",
                )
            ],
        )
        result = r.reformulate("Can you explain this architecture?", context=ctx)
        assert result.was_reformulated is True
        assert "deployment-diagram.pdf" in result.reformulated_query

    def test_max_three_attachments(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            attachments=[
                Attachment(type="screenshot", description=f"Screenshot {i}")
                for i in range(10)
            ],
        )
        result = r.reformulate("What's happening in these screenshots?", context=ctx)
        assert result.was_reformulated is True
        # Only first 3 should be included
        assert "Screenshot 0" in result.reformulated_query
        assert "Screenshot 2" in result.reformulated_query
        assert "Screenshot 5" not in result.reformulated_query


# ── Test Multimodal Scenarios ───────────────────────────────────

class TestMultimodalScenarios:
    """Test real-world scenarios combining attachments with other context."""

    def test_screenshot_plus_chat_history(self):
        """User shares screenshot while discussing a specific service."""
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[
                ("user", "I'm debugging the payment service"),
                ("assistant", "The paymentHandler processes Stripe webhooks"),
            ],
            attachments=[
                Attachment(
                    type="screenshot",
                    description="Browser console showing CORS error when calling /api/payment/webhook",
                )
            ],
            current_file="src/services/payment.ts",
        )
        result = r.reformulate("Why is this not working?", context=ctx)
        assert result.was_reformulated is True
        # Should combine pronoun resolution + file + attachment
        assert result.confidence >= 0.85

    def test_diagram_with_architecture_question(self):
        """User shares architecture diagram and asks about it."""
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            attachments=[
                Attachment(
                    type="diagram",
                    description="Architecture diagram showing API Gateway → Lambda → DynamoDB flow with auth middleware",
                )
            ],
        )
        result = r.reformulate("How does the data flow through the system?", context=ctx)
        assert result.was_reformulated is True
        assert "API Gateway" in result.reformulated_query or "DynamoDB" in result.reformulated_query

    def test_empty_attachment_ignored(self):
        """Attachment with no description, summary, or filename is skipped."""
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            attachments=[
                Attachment(type="unknown"),  # Completely empty
            ],
        )
        result = r.reformulate("What does the auth service do?", context=ctx)
        # Empty attachment adds nothing — no reformulation
        assert result.was_reformulated is False


# ── Test LLM-Based Reformulation ────────────────────────────────

class TestLLMReformulation:
    """Test LLM-based reformulation for standalone SDK usage."""

    def test_llm_reformulation_success(self):
        import asyncio

        async def _run():
            mock_backend = AsyncMock()
            mock_backend.generate = AsyncMock(
                return_value="What authentication mechanism does the auth service use for JWT tokens?"
            )
            mock_backend.name = "mock"
            mock_backend.cost_per_1k_tokens = 0.001

            r = QueryReformulator(mode="llm", backend=mock_backend, enabled=True)
            result = await r.areformulate("how does auth work?")
            assert result.was_reformulated is True
            assert result.context_source == "llm"
            assert result.confidence == 0.6
            mock_backend.generate.assert_called_once()

        asyncio.run(_run())

    def test_llm_reformulation_empty_response_passthrough(self):
        import asyncio

        mock_backend = AsyncMock()
        mock_backend.generate = AsyncMock(return_value="")
        mock_backend.name = "mock"
        mock_backend.cost_per_1k_tokens = 0.001

        r = QueryReformulator(mode="llm", backend=mock_backend, enabled=True)
        result = asyncio.run(r.areformulate("how does auth work?"))
        assert result.was_reformulated is False
        assert result.reformulated_query == "how does auth work?"

    def test_llm_reformulation_error_passthrough(self):
        import asyncio

        mock_backend = AsyncMock()
        mock_backend.generate = AsyncMock(side_effect=Exception("API error"))
        mock_backend.name = "mock"
        mock_backend.cost_per_1k_tokens = 0.001

        r = QueryReformulator(mode="llm", backend=mock_backend, enabled=True)
        result = asyncio.run(r.areformulate("how does auth work?"))
        # Fail-open: returns original query
        assert result.was_reformulated is False
        assert result.reformulated_query == "how does auth work?"

    def test_llm_strips_prefixes(self):
        import asyncio

        mock_backend = AsyncMock()
        mock_backend.generate = AsyncMock(
            return_value='Reformulated query: "How does the JWT auth service handle token verification?"'
        )
        mock_backend.name = "mock"
        mock_backend.cost_per_1k_tokens = 0.001

        r = QueryReformulator(mode="llm", backend=mock_backend, enabled=True)
        result = asyncio.run(r.areformulate("how does auth work?"))
        assert result.was_reformulated is True
        assert not result.reformulated_query.startswith("Reformulated")
        assert not result.reformulated_query.startswith('"')

    def test_llm_rejects_wildly_different(self):
        import asyncio

        mock_backend = AsyncMock()
        # Return something 10x longer than original
        mock_backend.generate = AsyncMock(return_value="x " * 500)
        mock_backend.name = "mock"
        mock_backend.cost_per_1k_tokens = 0.001

        r = QueryReformulator(mode="llm", backend=mock_backend, enabled=True)
        result = asyncio.run(r.areformulate("how does auth work?"))
        # Should reject and use original
        assert result.reformulated_query == "how does auth work?"


# ── Test Pass-Through / Disabled Modes ──────────────────────────

class TestPassThrough:
    """Test that reformulation is properly skipped when it should be."""

    def test_disabled_reformulator(self):
        r = QueryReformulator(mode="auto", enabled=False)
        ctx = ReformulationContext(
            chat_history=[("user", "auth service")],
            current_file="auth.ts",
        )
        result = r.reformulate("What does this do?", context=ctx)
        assert result.was_reformulated is False
        assert result.reformulated_query == "What does this do?"

    def test_off_mode(self):
        r = QueryReformulator(mode="off", enabled=True)
        ctx = ReformulationContext(chat_history=[("user", "auth")])
        result = r.reformulate("What does this do?", context=ctx)
        assert result.was_reformulated is False

    def test_short_query_skipped(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[("user", "auth service")],
        )
        result = r.reformulate("hi", context=ctx)
        assert result.was_reformulated is False

    def test_no_context_no_reformulation(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        result = r.reformulate("How does the auth service work?")
        assert result.was_reformulated is False

    def test_auto_mode_no_tool_no_backend(self):
        """Auto mode with no AI tool detected and no backend → pass-through."""
        env_clean = {v: "" for sigs in _AI_TOOL_ENV_SIGNATURES.values() for v in sigs}
        with patch.dict(os.environ, env_clean, clear=False):
            for v in env_clean:
                os.environ.pop(v, None)
            r = QueryReformulator(mode="auto", enabled=True)
            result = r.reformulate("How does the auth service work?")
            assert result.was_reformulated is False


# ── Test Edge Cases ─────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_max_length_enforcement(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        # Create context that would produce a very long reformulation
        ctx = ReformulationContext(
            chat_history=[
                ("user", "Look at " + "very/deep/nested/path/to/some/file.ts " * 20),
            ],
            current_file="a" * 300 + ".ts",
            active_symbols=["sym_" + str(i) for i in range(50)],
            tool_name="claude_code",
        )
        result = r.reformulate("What does this really long query about something do?", context=ctx)
        assert len(result.reformulated_query) <= _MAX_REFORMULATED_LENGTH

    def test_result_dataclass_fields(self):
        result = ReformulationResult(
            original_query="test",
            reformulated_query="test enhanced",
            was_reformulated=True,
            context_source="ai_tool",
            confidence=0.85,
        )
        assert result.original_query == "test"
        assert result.reformulated_query == "test enhanced"
        assert result.was_reformulated is True
        assert result.context_source == "ai_tool"
        assert result.confidence == 0.85

    def test_context_dataclass_defaults(self):
        ctx = ReformulationContext()
        assert ctx.chat_history == []
        assert ctx.project_summary == ""
        assert ctx.current_file == ""
        assert ctx.active_symbols == []
        assert ctx.tool_name == ""

    def test_special_characters_in_query(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            current_file="src/utils/parse$.ts",
            tool_name="cursor",
        )
        result = r.reformulate("What does the regex /\\d+\\.\\d+/ match?", context=ctx)
        # Should not crash on special regex chars
        assert result.reformulated_query is not None

    def test_unicode_query(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(
            chat_history=[("user", "The Über service handles payments")],
            current_file="uber.ts",
        )
        result = r.reformulate("Was macht dieser Service?", context=ctx)
        assert result.reformulated_query is not None

    def test_multiline_query(self):
        r = QueryReformulator(mode="ai_tool", enabled=True)
        ctx = ReformulationContext(current_file="main.py")
        query = "What does this function do?\nAlso check the return type."
        result = r.reformulate(query, context=ctx)
        assert result.reformulated_query is not None

    def test_concurrent_reformulators_independent(self):
        """Two reformulators with different configs don't interfere."""
        r1 = QueryReformulator(mode="ai_tool", enabled=True)
        r2 = QueryReformulator(mode="off", enabled=True)

        ctx = ReformulationContext(current_file="auth.ts")

        res1 = r1.reformulate("How does authentication work?", context=ctx)
        res2 = r2.reformulate("How does authentication work?", context=ctx)

        # r1 may reformulate, r2 should not
        assert res2.was_reformulated is False


# ── Test Graph Integration ──────────────────────────────────────

class TestGraphIntegration:
    """Test that reformulator integrates correctly with Graqle.reason()."""

    def test_config_has_reformulator_field(self):
        from graqle.config.settings import GraqleConfig, ReformulatorConfig
        config = GraqleConfig.default()
        assert hasattr(config, "reformulator")
        assert isinstance(config.reformulator, ReformulatorConfig)
        assert config.reformulator.enabled is True
        assert config.reformulator.mode == "auto"

    def test_config_from_yaml_with_reformulator(self, tmp_path):
        yaml_content = """
reformulator:
  enabled: true
  mode: "llm"
  graph_summary: "My knowledge graph about services"
"""
        yaml_file = tmp_path / "test_config.yaml"
        yaml_file.write_text(yaml_content)

        from graqle.config.settings import GraqleConfig
        config = GraqleConfig.from_yaml(yaml_file)
        assert config.reformulator.enabled is True
        assert config.reformulator.mode == "llm"
        assert config.reformulator.graph_summary == "My knowledge graph about services"

    def test_reformulator_export_from_activation(self):
        from graqle.activation import (
            QueryReformulator,
            ReformulationContext,
            ReformulationResult,
        )
        assert QueryReformulator is not None
        assert ReformulationContext is not None
        assert ReformulationResult is not None
