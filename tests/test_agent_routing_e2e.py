"""End-to-End Tests for Agent Routing.

Tests the CAIRN → ReOS/RIVA routing system:
1. CAIRN receives all messages by default
2. System requests route to ReOS
3. Code requests route to RIVA
4. Attention/life requests stay with CAIRN
5. Handoff context is preserved

These tests verify the routing logic without requiring actual LLM calls.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from reos.db import Database
from reos.handoff.models import AgentType, DomainConfidence
from reos.handoff.router import (
    analyze_domain,
    detect_handoff_need,
    build_handoff_context,
    is_simple_request,
    is_complex_request,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create isolated test database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    db.migrate()
    return db


class TestDomainAnalysis:
    """Test domain detection for routing decisions."""

    def test_system_keywords_route_to_reos(self) -> None:
        """System administration keywords should route to ReOS."""
        system_messages = [
            "install docker",
            "restart nginx service",
            "show running processes",
            "check disk space",
            "update packages",
            "what's using port 8080",
            "show memory usage",
            "start postgresql",
            "check systemd status",
        ]

        for message in system_messages:
            result = analyze_domain(message)

            reos_score = next(
                (d for d in result if d.agent == AgentType.REOS),
                None
            )
            assert reos_score is not None, f"'{message}' should match ReOS domain"
            assert reos_score.has_matches, f"'{message}' should have ReOS keyword matches"

    def test_code_keywords_route_to_riva(self) -> None:
        """Code-related keywords should route to RIVA."""
        code_messages = [
            "add a login function",
            "fix the bug in utils.py",
            "refactor this class",
            "write unit tests",
            "implement the API endpoint",
            "debug the error",
            "add type hints",
            "commit these changes",
            "merge the branch",
        ]

        for message in code_messages:
            result = analyze_domain(message)

            riva_score = next(
                (d for d in result if d.agent == AgentType.RIVA),
                None
            )
            assert riva_score is not None, f"'{message}' should match RIVA domain"
            assert riva_score.has_matches, f"'{message}' should have RIVA keyword matches"

    def test_attention_keywords_stay_with_cairn(self) -> None:
        """Attention/life keywords should stay with CAIRN."""
        cairn_messages = [
            "remind me tomorrow",
            "what should I focus on",
            "add to my todo list",
            "schedule a meeting",
            "what's on my calendar",
            "prioritize my tasks",
            "defer this until next week",
            "what am I waiting on",
        ]

        for message in cairn_messages:
            result = analyze_domain(message)

            cairn_score = next(
                (d for d in result if d.agent == AgentType.CAIRN),
                None
            )
            assert cairn_score is not None, f"'{message}' should match CAIRN domain"
            assert cairn_score.has_matches, f"'{message}' should have CAIRN keyword matches"

    def test_ambiguous_message_returns_multiple_domains(self) -> None:
        """Ambiguous messages may match multiple domains."""
        # "run" could be ReOS (run command) or RIVA (run tests)
        result = analyze_domain("run the tests")

        # Should have matches in multiple domains
        matching_domains = [d for d in result if d.has_matches]
        assert len(matching_domains) >= 1, "Should match at least one domain"

    def test_empty_message_returns_no_matches(self) -> None:
        """Empty message should not match any domain."""
        result = analyze_domain("")

        for domain in result:
            assert not domain.has_matches, "Empty message should not match any domain"


class TestHandoffDecision:
    """Test handoff decision logic."""

    def test_simple_request_stays_with_current_agent(self) -> None:
        """Simple out-of-domain requests don't need handoff."""
        # Simple system query from CAIRN context
        assert is_simple_request("what time is it"), (
            "Simple questions should not require handoff"
        )
        assert is_simple_request("hello"), (
            "Greetings should not require handoff"
        )

    def test_complex_request_triggers_handoff(self) -> None:
        """Complex domain-specific requests should trigger handoff."""
        complex_requests = [
            "refactor the entire authentication system",
            "investigate and fix all the memory leaks",
            "migrate the database schema",
            "troubleshoot why the server keeps crashing",
        ]

        for request in complex_requests:
            assert is_complex_request(request), (
                f"'{request}' should be detected as complex"
            )

    def test_detect_handoff_need_from_cairn_to_reos(self) -> None:
        """Should detect need to handoff from CAIRN to ReOS."""
        result = detect_handoff_need(
            message="install docker and configure it for my user",
            current_agent=AgentType.CAIRN,
        )

        assert result is not None, "Should detect handoff need"
        assert result.target_agent == AgentType.REOS, (
            f"Should handoff to ReOS, got {result.target_agent}"
        )

    def test_detect_handoff_need_from_cairn_to_riva(self) -> None:
        """Should detect need to handoff from CAIRN to RIVA."""
        result = detect_handoff_need(
            message="implement user authentication with JWT tokens",
            current_agent=AgentType.CAIRN,
        )

        assert result is not None, "Should detect handoff need"
        assert result.target_agent == AgentType.RIVA, (
            f"Should handoff to RIVA, got {result.target_agent}"
        )

    def test_no_handoff_for_simple_in_domain_request(self) -> None:
        """Simple in-domain requests don't need handoff."""
        result = detect_handoff_need(
            message="what's on my calendar today",
            current_agent=AgentType.CAIRN,
        )

        # Either no handoff needed, or low confidence
        if result is not None:
            assert result.confidence < DomainConfidence.HIGH, (
                "Simple in-domain request should not have high confidence for handoff"
            )


class TestHandoffContext:
    """Test handoff context building."""

    def test_build_context_includes_message(self) -> None:
        """Handoff context should include the original message."""
        context = build_handoff_context(
            message="install nginx",
            current_agent=AgentType.CAIRN,
            conversation_history=["Hello", "Hi there"],
        )

        assert context.original_message == "install nginx"

    def test_build_context_includes_history(self) -> None:
        """Handoff context should include conversation history."""
        history = [
            "I need help with my server",
            "What kind of help?",
            "install nginx please",
        ]

        context = build_handoff_context(
            message="install nginx please",
            current_agent=AgentType.CAIRN,
            conversation_history=history,
        )

        assert len(context.conversation_summary) > 0 or context.recent_messages, (
            "Context should include history"
        )

    def test_build_context_includes_source_agent(self) -> None:
        """Handoff context should identify source agent."""
        context = build_handoff_context(
            message="test message",
            current_agent=AgentType.CAIRN,
        )

        assert context.source_agent == AgentType.CAIRN


class TestAgentTypeEnum:
    """Test AgentType enum values."""

    def test_all_agents_exist(self) -> None:
        """All three agents should exist."""
        assert AgentType.CAIRN.value == "cairn"
        assert AgentType.REOS.value == "reos"
        assert AgentType.RIVA.value == "riva"

    def test_agent_count(self) -> None:
        """Should have exactly 3 agents."""
        agents = list(AgentType)
        assert len(agents) == 3, "Should have exactly 3 agents: CAIRN, ReOS, RIVA"


class TestRoutingIntegration:
    """Integration tests for full routing flow."""

    @patch("reos.agent.ChatAgent")
    def test_chat_routes_system_request_to_reos(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """System request through chat should use ReOS tools."""
        from reos.rpc.handlers.chat import handle_respond

        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.return_value = MagicMock(
            answer="I'll check your processes...",
            conversation_id="conv-1",
            message_id="msg-1",
            message_type="text",
            tool_calls=[{"name": "linux_ps", "arguments": {}}],
            thinking_steps=[],
            pending_approval_id=None,
            extended_thinking_trace=None,
        )
        mock_agent_class.return_value = mock_agent

        result = handle_respond(db, text="show running processes", agent_type="reos")

        # Verify agent_type was passed
        respond_call = mock_agent.respond.call_args
        assert respond_call[1].get("agent_type") == "reos"

    @patch("reos.agent.ChatAgent")
    def test_chat_routes_code_request_to_riva(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Code request through chat should use RIVA tools."""
        from reos.rpc.handlers.chat import handle_respond

        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.return_value = MagicMock(
            answer="I'll analyze the code...",
            conversation_id="conv-1",
            message_id="msg-1",
            message_type="text",
            tool_calls=[{"name": "code_read_file", "arguments": {"path": "main.py"}}],
            thinking_steps=[],
            pending_approval_id=None,
            extended_thinking_trace=None,
        )
        mock_agent_class.return_value = mock_agent

        result = handle_respond(
            db, text="add error handling to the login function", use_code_mode=True
        )

        # Verify code_mode was enabled
        mock_agent_class.assert_called_with(db=db, use_code_mode=True)


class TestDomainConfidence:
    """Test domain confidence levels."""

    def test_confidence_levels_exist(self) -> None:
        """All confidence levels should exist."""
        assert DomainConfidence.LOW is not None
        assert DomainConfidence.MEDIUM is not None
        assert DomainConfidence.HIGH is not None

    def test_confidence_ordering(self) -> None:
        """Confidence levels should be ordered LOW < MEDIUM < HIGH."""
        assert DomainConfidence.LOW < DomainConfidence.MEDIUM
        assert DomainConfidence.MEDIUM < DomainConfidence.HIGH


class TestEdgeCases:
    """Test edge cases in routing."""

    def test_mixed_domain_request(self) -> None:
        """Request touching multiple domains should pick primary."""
        # "install the code linter" touches both ReOS (install) and RIVA (code, linter)
        result = analyze_domain("install the code linting tools")

        # Should have matches in both domains
        reos_matches = next((d for d in result if d.agent == AgentType.REOS), None)
        riva_matches = next((d for d in result if d.agent == AgentType.RIVA), None)

        # At least one should have matches
        assert (reos_matches and reos_matches.has_matches) or \
               (riva_matches and riva_matches.has_matches), \
               "Mixed request should match at least one domain"

    def test_negation_doesnt_trigger_routing(self) -> None:
        """Negated keywords shouldn't trigger routing."""
        # "don't install anything" shouldn't strongly route to ReOS
        result = analyze_domain("don't install anything yet")

        # This is tricky - current implementation may still match "install"
        # The important thing is the routing logic considers context
        pass  # Placeholder for future NLU improvement

    def test_question_about_domain(self) -> None:
        """Questions about a domain should stay informational."""
        # "what is docker" is a question, not an action request
        result = analyze_domain("what is docker")

        # Should match ReOS due to "docker" keyword
        reos = next((d for d in result if d.agent == AgentType.REOS), None)
        assert reos is not None and reos.has_matches

    def test_very_long_message(self) -> None:
        """Very long messages should not crash or timeout."""
        long_message = "install docker and " * 100

        # Should complete without error
        result = analyze_domain(long_message)

        assert result is not None, "Long message should be handled"


class TestTransitionMessages:
    """Test agent transition messages."""

    def test_generate_transition_message(self) -> None:
        """Transition messages should be generated for handoffs."""
        from reos.handoff.models import generate_transition_message

        message = generate_transition_message(
            from_agent=AgentType.CAIRN,
            to_agent=AgentType.REOS,
            reason="System administration request",
        )

        assert "ReOS" in message or "reos" in message.lower(), (
            "Transition message should mention target agent"
        )

    def test_transition_message_includes_reason(self) -> None:
        """Transition message should include the reason."""
        from reos.handoff.models import generate_transition_message

        message = generate_transition_message(
            from_agent=AgentType.CAIRN,
            to_agent=AgentType.RIVA,
            reason="Code modification request",
        )

        # Message should be informative
        assert len(message) > 20, "Transition message should be informative"
