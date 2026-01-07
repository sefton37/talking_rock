"""Tests for IntentDiscoverer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from reos.code_mode.intent import (
    IntentDiscoverer,
    PromptIntent,
    PlayIntent,
    CodebaseIntent,
    DiscoveredIntent,
)
from reos.code_mode.sandbox import CodeSandbox


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with sample files."""
    # Initialize git repo
    (tmp_path / ".git").mkdir()

    # Create package structure
    src = tmp_path / "src" / "myapp"
    src.mkdir(parents=True)

    (src / "__init__.py").write_text(
        '''"""My application package."""

from .main import run

__all__ = ["run"]
'''
    )

    (src / "main.py").write_text(
        '''"""Main module."""

from .utils import helper
from .models import User

def run():
    """Run the application."""
    user = User(name="test")
    return helper(user)

def other_func():
    """Another function."""
    pass
'''
    )

    (src / "utils.py").write_text(
        '''"""Utility functions."""

def helper(user):
    """Help with something."""
    return f"Hello, {user.name}"

def format_name(name: str) -> str:
    """Format a name."""
    return name.title()

MAX_RETRIES = 3
'''
    )

    (src / "models.py").write_text(
        '''"""Data models."""

from dataclasses import dataclass

@dataclass
class User:
    """A user model."""
    name: str
    email: str = ""

@dataclass
class Product:
    """A product model."""
    id: int
    name: str
'''
    )

    # Create tests directory
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text(
        '''"""Tests for main module."""

import pytest

def test_run():
    """Test run function."""
    pass
'''
    )

    return tmp_path


@pytest.fixture
def sandbox(temp_repo: Path) -> CodeSandbox:
    """Create a CodeSandbox for the temp repo."""
    return CodeSandbox(temp_repo)


@pytest.fixture
def mock_act() -> MagicMock:
    """Create a mock Act for testing."""
    act = MagicMock()
    act.title = "Build User Management"
    act.artifact_type = "feature"
    act.code_config = {"language": "python"}
    act.repo_path = "/tmp/test"
    return act


class TestIntentDiscovererBasic:
    """Tests for basic IntentDiscoverer functionality."""

    def test_create_discoverer(
        self, sandbox: CodeSandbox
    ) -> None:
        """Should create discoverer."""
        discoverer = IntentDiscoverer(sandbox)
        assert discoverer.sandbox is sandbox

    def test_discover_basic_intent(
        self, sandbox: CodeSandbox, mock_act: MagicMock
    ) -> None:
        """Should discover intent from prompt."""
        discoverer = IntentDiscoverer(sandbox)
        intent = discoverer.discover("add a new user function", mock_act)

        assert isinstance(intent, DiscoveredIntent)
        assert intent.prompt_intent.action_verb == "add"
        assert intent.prompt_intent.target in ("function", "user")


class TestCodebaseIntent:
    """Tests for CodebaseIntent."""

    def test_codebase_intent_basic_fields(self) -> None:
        """Should have basic fields."""
        intent = CodebaseIntent(
            language="python",
            architecture_style="standard",
            conventions=["Uses type hints"],
            related_files=["main.py"],
            existing_patterns=["Use dataclass"],
            test_patterns="pytest",
        )

        assert intent.language == "python"
        assert intent.architecture_style == "standard"
        assert intent.test_patterns == "pytest"


class TestPromptAnalysis:
    """Tests for prompt analysis."""

    def test_analyze_prompt_heuristic(
        self, sandbox: CodeSandbox
    ) -> None:
        """Should extract action and target from prompt."""
        discoverer = IntentDiscoverer(sandbox)

        intent = discoverer._analyze_prompt_heuristic("add a new user function")

        assert intent.action_verb == "add"
        assert intent.target == "function"

    def test_analyze_prompt_heuristic_refactor(
        self, sandbox: CodeSandbox
    ) -> None:
        """Should detect refactor action."""
        discoverer = IntentDiscoverer(sandbox)

        intent = discoverer._analyze_prompt_heuristic("refactor the authentication module")

        assert intent.action_verb == "refactor"
        assert intent.target == "module"

    def test_analyze_prompt_heuristic_fix_bug(
        self, sandbox: CodeSandbox
    ) -> None:
        """Should detect fix action for bugs."""
        discoverer = IntentDiscoverer(sandbox)

        intent = discoverer._analyze_prompt_heuristic("fix the login bug")

        assert intent.action_verb == "fix"
        assert intent.target == "bug"


class TestPlayContextAnalysis:
    """Tests for play context analysis."""

    def test_analyze_play_context(
        self, sandbox: CodeSandbox, mock_act: MagicMock
    ) -> None:
        """Should extract context from Act."""
        discoverer = IntentDiscoverer(sandbox)

        intent = discoverer._analyze_play_context(mock_act, "")

        assert intent.act_goal == "Build User Management"
        assert intent.act_artifact == "feature"


class TestCodebaseAnalysis:
    """Tests for codebase analysis."""

    def test_detect_language(
        self, sandbox: CodeSandbox
    ) -> None:
        """Should detect Python as primary language."""
        discoverer = IntentDiscoverer(sandbox)

        language = discoverer._detect_language()

        assert language == "python"

    def test_detect_architecture(
        self, sandbox: CodeSandbox
    ) -> None:
        """Should detect architecture style."""
        discoverer = IntentDiscoverer(sandbox)

        arch = discoverer._detect_architecture()

        # temp_repo has src/ and tests/
        assert arch == "standard"

    def test_detect_conventions(
        self, sandbox: CodeSandbox
    ) -> None:
        """Should detect coding conventions."""
        discoverer = IntentDiscoverer(sandbox)

        conventions = discoverer._detect_conventions()

        assert isinstance(conventions, list)

    def test_detect_test_patterns(
        self, sandbox: CodeSandbox
    ) -> None:
        """Should detect pytest test patterns."""
        discoverer = IntentDiscoverer(sandbox)

        pattern = discoverer._detect_test_patterns()

        assert "pytest" in pattern


class TestDiscoveredIntentSummary:
    """Tests for DiscoveredIntent.summary() method."""

    def test_summary_format(self) -> None:
        """Should generate formatted summary."""
        intent = DiscoveredIntent(
            goal="Add user authentication",
            why="Security requirement",
            what="Create login endpoint",
            how_constraints=["Use JWT tokens"],
            prompt_intent=PromptIntent(
                raw_prompt="add auth",
                action_verb="add",
                target="auth",
                constraints=[],
                examples=[],
                summary="Add authentication",
            ),
            play_intent=PlayIntent(
                act_goal="Security",
                act_artifact="feature",
                scene_context="",
                recent_work=[],
                knowledge_hints=[],
            ),
            codebase_intent=CodebaseIntent(
                language="python",
                architecture_style="standard",
                conventions=[],
                related_files=[],
                existing_patterns=[],
                test_patterns="pytest",
            ),
            confidence=0.8,
            ambiguities=["Which auth method?"],
            assumptions=["Using OAuth"],
        )

        summary = intent.summary()

        assert "Discovered Intent" in summary
        assert "Add user authentication" in summary
        assert "Security requirement" in summary
        assert "JWT tokens" in summary
        assert "80%" in summary
        assert "Which auth method?" in summary
        assert "Using OAuth" in summary
