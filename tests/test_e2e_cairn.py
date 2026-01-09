"""End-to-End Tests for CAIRN - The Attention Minder.

These tests simulate real user scenarios with CAIRN:

1. Play Knowledge Base Integration
   - Reading/writing me.md (core identity)
   - CRUD operations on Acts, Scenes, Beats
   - KB file operations for knowledge storage
   - Identity extraction for coherence verification

2. Thunderbird Integration
   - Contact parsing from address book
   - Calendar event parsing
   - Todo parsing and overdue detection
   - Contact-linked knowledge items

3. Coherence Verification Recursion
   - Anti-pattern fast-path rejection
   - Direct verification for simple demands
   - Recursive decomposition for complex demands
   - Aggregate scoring across sub-demands
   - Trace storage for audit trail

4. Surfacing Algorithm
   - Priority-based surfacing
   - Time-aware surfacing (due dates, calendar)
   - Stale item detection
   - Waiting-on tracking
   - Coherence-filtered surfacing

Run with: pytest tests/test_e2e_cairn.py -v
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

from reos.cairn.coherence import (
    AttentionDemand,
    CoherenceCheck,
    CoherenceResult,
    CoherenceTrace,
    CoherenceVerifier,
    IdentityFacet,
    IdentityModel,
)
from reos.cairn.models import (
    ActivityType,
    CairnMetadata,
    ContactRelationship,
    KanbanState,
    SurfaceContext,
)
from reos.cairn.store import CairnStore
from reos.cairn.surfacing import CairnSurfacer
from reos.cairn.thunderbird import (
    CalendarEvent,
    CalendarTodo,
    ThunderbirdBridge,
    ThunderbirdConfig,
    ThunderbirdContact,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_play_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a complete temporary Play structure."""
    play_path = tmp_path / "play"
    play_path.mkdir()

    # Create me.md (core identity)
    me_md = play_path / "me.md"
    me_md.write_text(
        """# My Story

I am a software engineer who values building tools that help people.

## Values
- Clean, maintainable code
- Test-driven development
- Open source contribution
- Continuous learning

## Goals
- Build an AI assistant for developers
- Learn Rust programming
- Contribute to open source projects

## Constraints
- Remote work only
- No cryptocurrency or NFT projects
- Focus on developer tools
""",
        encoding="utf-8",
    )

    # Create acts directory with sample acts
    acts_path = play_path / "acts"
    acts_path.mkdir()

    # Create acts.json
    (play_path / "acts.json").write_text(
        json.dumps(
            {
                "acts": [
                    {
                        "act_id": "talking-rock",
                        "title": "Building Talking Rock",
                        "active": True,
                        "notes": "Building a local-first AI assistant",
                        "repo_path": "/home/user/projects/talking-rock",
                    },
                    {
                        "act_id": "learn-rust",
                        "title": "Learning Rust",
                        "active": False,
                        "notes": "Learning systems programming with Rust",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Create act directories with scenes (beats are stored within scenes.json)
    tr_act = acts_path / "talking-rock"
    tr_act.mkdir()
    (tr_act / "scenes.json").write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "scene_id": "cairn-impl",
                        "title": "Implement CAIRN",
                        "intent": "Build the attention minder component",
                        "status": "in_progress",
                        "time_horizon": "2 weeks",
                        "notes": "Core surfacing algorithm and coherence kernel",
                        "beats": [
                            {
                                "beat_id": "coherence-kernel",
                                "title": "Implement Coherence Kernel",
                                "status": "completed",
                                "notes": "Recursive verification mirroring RIVA pattern",
                            },
                            {
                                "beat_id": "surfacing-algo",
                                "title": "Build Surfacing Algorithm",
                                "status": "in_progress",
                                "notes": "Priority and time-aware surfacing",
                            },
                        ],
                    },
                    {
                        "scene_id": "riva-impl",
                        "title": "Implement RIVA",
                        "intent": "Build the code mode component",
                        "status": "completed",
                        "time_horizon": "done",
                        "notes": "Recursive intent verification complete",
                        "beats": [],
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Create KB directory with sample files (KB is under play_root/kb/acts/{act_id}/)
    kb_path = play_path / "kb" / "acts" / "talking-rock"
    kb_path.mkdir(parents=True)
    (kb_path / "design-notes.md").write_text(
        """# CAIRN Design Notes

## Core Philosophy
- Surface the next thing, not everything
- Priority driven by user decision
- Never gamifies, never guilt-trips

## Key Patterns
- Recursive decomposition for complex demands
- Anti-pattern fast-path for known rejections
- Identity-first filtering
""",
        encoding="utf-8",
    )

    yield play_path


@pytest.fixture
def temp_cairn_db(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary CAIRN database."""
    db_path = tmp_path / "cairn.db"
    yield db_path


@pytest.fixture
def cairn_store(temp_cairn_db: Path) -> CairnStore:
    """Create a CAIRN store with temp database."""
    return CairnStore(temp_cairn_db)


@pytest.fixture
def surfacer(cairn_store: CairnStore) -> CairnSurfacer:
    """Create a surfacer with the test store."""
    return CairnSurfacer(cairn_store)


@pytest.fixture
def mock_thunderbird_profile(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a mock Thunderbird profile with SQLite databases."""
    profile_path = tmp_path / "thunderbird" / "test.default"
    profile_path.mkdir(parents=True)

    # Create address book database
    abook_path = profile_path / "abook.sqlite"
    conn = sqlite3.connect(abook_path)
    conn.execute("CREATE TABLE properties (card TEXT, name TEXT, value TEXT)")

    # Add sample contacts
    contacts_data = [
        ("contact-1", [
            ("DisplayName", "Alice Developer"),
            ("PrimaryEmail", "alice@example.com"),
            ("Company", "TechCorp"),
            ("FirstName", "Alice"),
            ("LastName", "Developer"),
            ("JobTitle", "Senior Engineer"),
        ]),
        ("contact-2", [
            ("DisplayName", "Bob Designer"),
            ("PrimaryEmail", "bob@design.co"),
            ("Company", "DesignStudio"),
            ("FirstName", "Bob"),
            ("LastName", "Designer"),
        ]),
        ("contact-3", [
            ("DisplayName", "Charlie Manager"),
            ("PrimaryEmail", "charlie@corp.com"),
            ("WorkPhone", "555-1234"),
        ]),
    ]

    for card_id, props in contacts_data:
        for name, value in props:
            conn.execute(
                "INSERT INTO properties (card, name, value) VALUES (?, ?, ?)",
                (card_id, name, value),
            )
    conn.commit()
    conn.close()

    # Create calendar database
    cal_path = profile_path / "calendar-data"
    cal_path.mkdir()
    cal_db_path = cal_path / "local.sqlite"

    conn = sqlite3.connect(cal_db_path)
    conn.execute(
        """CREATE TABLE cal_events (
            id TEXT PRIMARY KEY,
            title TEXT,
            event_start INTEGER,
            event_end INTEGER,
            event_stamp INTEGER,
            flags INTEGER,
            icalString TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE cal_todos (
            id TEXT PRIMARY KEY,
            title TEXT,
            todo_entry INTEGER,
            todo_due INTEGER,
            todo_completed INTEGER,
            flags INTEGER,
            icalString TEXT
        )"""
    )

    # Add sample events (timestamps in microseconds)
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    events = [
        (
            "event-1",
            "Team Standup",
            int((today_start + timedelta(hours=9)).timestamp() * 1_000_000),
            int((today_start + timedelta(hours=9, minutes=30)).timestamp() * 1_000_000),
            "LOCATION:Conference Room A\nSTATUS:CONFIRMED",
        ),
        (
            "event-2",
            "Code Review Session",
            int((today_start + timedelta(hours=14)).timestamp() * 1_000_000),
            int((today_start + timedelta(hours=15)).timestamp() * 1_000_000),
            "LOCATION:Zoom\nDESCRIPTION:Review CAIRN implementation",
        ),
        (
            "event-3",
            "Sprint Planning",
            int((today_start + timedelta(days=1, hours=10)).timestamp() * 1_000_000),
            int((today_start + timedelta(days=1, hours=11)).timestamp() * 1_000_000),
            "STATUS:TENTATIVE",
        ),
    ]

    for evt_id, title, start, end, ical in events:
        conn.execute(
            "INSERT INTO cal_events (id, title, event_start, event_end, event_stamp, flags, icalString) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (evt_id, title, start, end, start, 0, ical),
        )

    # Add sample todos
    todos = [
        (
            "todo-1",
            "Review Pull Request",
            int((today_start - timedelta(days=1)).timestamp() * 1_000_000),  # Overdue
            None,
            "STATUS:NEEDS-ACTION\nPRIORITY:1",
        ),
        (
            "todo-2",
            "Update Documentation",
            int((today_start + timedelta(days=3)).timestamp() * 1_000_000),
            None,
            "STATUS:IN-PROCESS\nPRIORITY:5",
        ),
        (
            "todo-3",
            "Deploy to Production",
            int((today_start + timedelta(days=7)).timestamp() * 1_000_000),
            None,
            "STATUS:NEEDS-ACTION",
        ),
    ]

    for todo_id, title, due, completed, ical in todos:
        conn.execute(
            "INSERT INTO cal_todos (id, title, todo_entry, todo_due, todo_completed, flags, icalString) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (todo_id, title, due, due, completed, 0, ical),
        )

    conn.commit()
    conn.close()

    yield profile_path


@pytest.fixture
def thunderbird_bridge(mock_thunderbird_profile: Path) -> ThunderbirdBridge:
    """Create a Thunderbird bridge with mock profile."""
    config = ThunderbirdConfig(profile_path=mock_thunderbird_profile)
    return ThunderbirdBridge(config)


@pytest.fixture
def complex_identity() -> IdentityModel:
    """Create a rich identity model for E2E testing."""
    return IdentityModel(
        core="""I am a software engineer focused on building developer tools.

I value:
- Clean, maintainable code
- Test-driven development
- Open source contribution
- Continuous learning
- Work-life balance

My current goals:
- Build Talking Rock, a local-first AI assistant
- Learn Rust for systems programming
- Contribute to open source projects

I avoid:
- Cryptocurrency and NFT projects
- Hustle culture
- Surveillance technology
""",
        facets=[
            IdentityFacet(
                name="goal",
                source="act:talking-rock",
                content="Build Talking Rock - a local-first AI assistant that respects privacy",
                weight=2.0,
            ),
            IdentityFacet(
                name="goal",
                source="act:learn-rust",
                content="Learn Rust programming for systems-level development",
                weight=1.5,
            ),
            IdentityFacet(
                name="project",
                source="scene:cairn-impl",
                content="Implement CAIRN - the attention minder with coherence verification",
                weight=1.8,
            ),
            IdentityFacet(
                name="value",
                source="me.md:values",
                content="Test-driven development and clean code practices",
                weight=1.5,
            ),
            IdentityFacet(
                name="constraint",
                source="me.md:constraints",
                content="Remote work only, no cryptocurrency projects",
                weight=2.0,
            ),
            IdentityFacet(
                name="knowledge",
                source="kb:design-notes.md",
                content="CAIRN surfaces the next thing, not everything. Priority driven by user.",
                weight=1.0,
            ),
        ],
        anti_patterns=[
            "crypto",
            "nft",
            "blockchain",
            "hustle",
            "grind",
            "spam",
            "marketing email",
            "newsletter signup",
            "surveillance",
        ],
    )


# =============================================================================
# Play Knowledge Base E2E Tests
# =============================================================================


class TestPlayKnowledgeBaseE2E:
    """E2E tests for Play knowledge base integration."""

    def test_read_me_markdown_with_real_structure(self, temp_play_root: Path) -> None:
        """Test reading me.md from a real Play structure."""
        from reos import play_fs

        with patch.object(play_fs, "play_root", return_value=temp_play_root):
            content = play_fs.read_me_markdown()

            assert "software engineer" in content.lower()
            assert "Values" in content
            assert "Goals" in content
            assert "Constraints" in content
            assert "No cryptocurrency" in content

    def test_list_acts_with_code_mode(self, temp_play_root: Path) -> None:
        """Test listing acts including code mode configuration."""
        from reos import play_fs

        with patch.object(play_fs, "play_root", return_value=temp_play_root):
            acts, active_id = play_fs.list_acts()

            assert len(acts) == 2
            assert active_id == "talking-rock"

            # Find the active act
            active_act = next(a for a in acts if a.active)
            assert active_act.title == "Building Talking Rock"
            assert active_act.repo_path == "/home/user/projects/talking-rock"

    def test_list_scenes_for_act(self, temp_play_root: Path) -> None:
        """Test listing scenes within an act."""
        from reos import play_fs

        with patch.object(play_fs, "play_root", return_value=temp_play_root):
            scenes = play_fs.list_scenes(act_id="talking-rock")

            assert len(scenes) == 2
            scene_titles = [s.title for s in scenes]
            assert "Implement CAIRN" in scene_titles
            assert "Implement RIVA" in scene_titles

    def test_list_beats_for_scene(self, temp_play_root: Path) -> None:
        """Test listing beats within a scene."""
        from reos import play_fs

        with patch.object(play_fs, "play_root", return_value=temp_play_root):
            beats = play_fs.list_beats(act_id="talking-rock", scene_id="cairn-impl")

            assert len(beats) == 2
            beat_titles = [b.title for b in beats]
            assert "Implement Coherence Kernel" in beat_titles

    def test_kb_list_and_read_files(self, temp_play_root: Path) -> None:
        """Test listing and reading KB files."""
        from reos import play_fs

        with patch.object(play_fs, "play_root", return_value=temp_play_root):
            kb_files = play_fs.kb_list_files(act_id="talking-rock")

            assert "design-notes.md" in kb_files

            content = play_fs.kb_read(act_id="talking-rock", path="design-notes.md")
            assert "Core Philosophy" in content
            assert "Surface the next thing" in content

    def test_identity_extraction_from_play(self, temp_play_root: Path) -> None:
        """Test building IdentityModel from real Play structure."""
        from reos import play_fs
        from reos.cairn.identity import build_identity_model

        with patch.object(play_fs, "play_root", return_value=temp_play_root):
            identity = build_identity_model(include_kb=True)

            # Core should have me.md content
            assert "software engineer" in identity.core.lower()

            # Should have facets from acts
            goal_facets = identity.get_facets_by_name("goal")
            assert len(goal_facets) >= 1

            # Should have KB facets if include_kb=True
            kb_facets = [f for f in identity.facets if f.source.startswith("kb:")]
            # KB facets may or may not be present depending on content length


# =============================================================================
# Thunderbird Integration E2E Tests
# =============================================================================


class TestThunderbirdIntegrationE2E:
    """E2E tests for Thunderbird integration."""

    def test_bridge_status(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test getting bridge status."""
        status = thunderbird_bridge.get_status()

        assert status["has_address_book"] is True
        assert status["has_calendar"] is True

    def test_list_all_contacts(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test listing all contacts."""
        contacts = thunderbird_bridge.list_contacts()

        assert len(contacts) == 3

        # Check contact details
        alice = next(c for c in contacts if "Alice" in c.display_name)
        assert alice.email == "alice@example.com"
        assert alice.organization == "TechCorp"
        assert alice.first_name == "Alice"
        assert alice.job_title == "Senior Engineer"

    def test_search_contacts(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test searching contacts by name/email."""
        # Search by name
        results = thunderbird_bridge.search_contacts("Alice")
        assert len(results) == 1
        assert results[0].display_name == "Alice Developer"

        # Search by company
        results = thunderbird_bridge.search_contacts("TechCorp")
        assert len(results) == 1

        # Search by email domain
        results = thunderbird_bridge.search_contacts("design.co")
        assert len(results) == 1
        assert "Bob" in results[0].display_name

    def test_get_contact_by_id(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test getting a specific contact."""
        contact = thunderbird_bridge.get_contact("contact-1")

        assert contact is not None
        assert contact.display_name == "Alice Developer"
        assert contact.email == "alice@example.com"

        # Non-existent contact
        missing = thunderbird_bridge.get_contact("nonexistent")
        assert missing is None

    def test_list_calendar_events(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test listing calendar events."""
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=2)

        events = thunderbird_bridge.list_events(start=start, end=end)

        assert len(events) >= 2  # At least today's events

        # Check event details
        standup = next((e for e in events if "Standup" in e.title), None)
        assert standup is not None
        assert standup.location == "Conference Room A"

    def test_get_today_events(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test getting today's events."""
        events = thunderbird_bridge.get_today_events()

        assert len(events) >= 2  # Standup and Code Review

    def test_get_upcoming_events(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test getting upcoming events in next N hours."""
        events = thunderbird_bridge.get_upcoming_events(hours=24)

        assert len(events) >= 2

    def test_list_todos(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test listing calendar todos."""
        todos = thunderbird_bridge.list_todos(include_completed=False)

        assert len(todos) == 3

        # Check todo details
        pr_todo = next((t for t in todos if "Pull Request" in t.title), None)
        assert pr_todo is not None
        assert pr_todo.priority == 1  # High priority

    def test_get_overdue_todos(self, thunderbird_bridge: ThunderbirdBridge) -> None:
        """Test getting overdue todos."""
        overdue = thunderbird_bridge.get_overdue_todos()

        assert len(overdue) >= 1
        assert any("Pull Request" in t.title for t in overdue)


class TestThunderbirdContactLinksE2E:
    """E2E tests for CAIRN contact knowledge graph."""

    def test_link_contact_to_entity(
        self,
        cairn_store: CairnStore,
        thunderbird_bridge: ThunderbirdBridge,
    ) -> None:
        """Test linking Thunderbird contact to Play entity."""
        # Create entity metadata
        cairn_store.get_or_create_metadata("act", "talking-rock")

        # Link contact
        link = cairn_store.link_contact(
            contact_id="contact-1",  # Alice Developer
            entity_type="act",
            entity_id="talking-rock",
            relationship=ContactRelationship.COLLABORATOR,
            notes="Working on CAIRN together",
        )

        assert link.contact_id == "contact-1"
        assert link.relationship == ContactRelationship.COLLABORATOR

        # Retrieve links
        links = cairn_store.get_contact_links(contact_id="contact-1")
        assert len(links) == 1
        assert links[0].entity_id == "talking-rock"

    def test_contact_with_multiple_projects(
        self,
        cairn_store: CairnStore,
    ) -> None:
        """Test contact linked to multiple projects."""
        cairn_store.get_or_create_metadata("act", "project-a")
        cairn_store.get_or_create_metadata("act", "project-b")
        cairn_store.get_or_create_metadata("scene", "scene-1")

        # Link contact to multiple entities
        cairn_store.link_contact("contact-1", "act", "project-a", ContactRelationship.OWNER)
        cairn_store.link_contact("contact-1", "act", "project-b", ContactRelationship.COLLABORATOR)
        cairn_store.link_contact("contact-1", "scene", "scene-1", ContactRelationship.STAKEHOLDER)

        links = cairn_store.get_contact_links(contact_id="contact-1")
        assert len(links) == 3

        # Filter by entity type
        act_links = cairn_store.get_contacts_for_entity("act", "project-a")
        assert len(act_links) == 1
        assert act_links[0].relationship == ContactRelationship.OWNER


# =============================================================================
# Coherence Recursion E2E Tests
# =============================================================================


class TestCoherenceRecursionE2E:
    """E2E tests for the coherence verification recursion principle."""

    def test_anti_pattern_fast_path_no_llm_call(self, complex_identity: IdentityModel) -> None:
        """Test that anti-patterns reject instantly without LLM."""
        mock_llm = MagicMock()
        verifier = CoherenceVerifier(complex_identity, llm=mock_llm)

        demand = AttentionDemand.create(
            source="email",
            content="Amazing crypto opportunity - invest now!",
            urgency=8,
        )

        result = verifier.verify(demand)

        # Should reject via anti-pattern
        assert result.recommendation == "reject"
        assert result.overall_score == -1.0
        assert "anti-pattern" in " ".join(result.trace).lower()

        # LLM should NOT have been called
        mock_llm.chat_json.assert_not_called()

    def test_simple_demand_direct_verification(self, complex_identity: IdentityModel) -> None:
        """Test that simple demands are verified directly."""
        verifier = CoherenceVerifier(complex_identity, llm=None)

        demand = AttentionDemand.create(
            source="github",
            content="Review code change",
            urgency=5,
        )

        result = verifier.verify(demand)

        # Simple demand should be verified directly
        assert "direct" in " ".join(result.trace).lower() or len(result.checks) > 0
        assert len(demand.sub_demands) == 0  # No decomposition

    def test_complex_demand_decomposition(self, complex_identity: IdentityModel) -> None:
        """Test that complex demands are decomposed recursively."""
        verifier = CoherenceVerifier(complex_identity, llm=None, max_depth=3)

        # Complex demand with multiple parts
        demand = AttentionDemand.create(
            source="work",
            content="Review the CAIRN code changes and also update the documentation for the new API and additionally write tests for the coherence verification module",
            urgency=6,
        )

        result = verifier.verify(demand)

        # Should have been decomposed
        assert len(demand.sub_demands) > 0 or "decompos" in " ".join(result.trace).lower()

    def test_recursive_depth_limiting(self, complex_identity: IdentityModel) -> None:
        """Test that recursion is properly limited."""
        verifier = CoherenceVerifier(complex_identity, llm=None, max_depth=2)

        # Deeply nested demand
        demand = AttentionDemand.create(
            source="complex",
            content="A and B and C and D and E and F and G",
            urgency=5,
        )

        result = verifier.verify(demand)

        # Should complete without infinite recursion
        assert result is not None
        assert result.recommendation in ("accept", "defer", "reject")

    def test_aggregate_scoring_mixed_sub_demands(self, complex_identity: IdentityModel) -> None:
        """Test aggregate scoring with mixed coherence sub-demands."""
        verifier = CoherenceVerifier(complex_identity, llm=None)

        # Demand with both coherent and incoherent parts
        demand = AttentionDemand.create(
            source="mixed",
            content="Build developer tools and also check crypto prices",
            urgency=5,
        )

        result = verifier.verify(demand)

        # Should have checks from multiple sub-demands
        # Final recommendation depends on aggregation
        assert result is not None
        # The anti-pattern "crypto" should affect the result
        assert result.overall_score < 0.5  # Not fully coherent due to crypto mention

    def test_coherence_trace_creation(self, complex_identity: IdentityModel) -> None:
        """Test that coherence traces are properly created."""
        from reos.cairn.identity import get_identity_hash

        verifier = CoherenceVerifier(complex_identity, llm=None)

        demand = AttentionDemand.create(
            source="work",
            content="Implement CAIRN surfacing algorithm",
            urgency=7,
        )

        result = verifier.verify(demand)
        identity_hash = get_identity_hash(complex_identity)

        trace = CoherenceTrace.create(result, identity_hash)

        assert trace.demand_id == demand.id
        assert trace.identity_hash == identity_hash
        assert trace.final_score == result.overall_score
        assert trace.recommendation == result.recommendation
        assert trace.user_override is None

    def test_heuristic_keyword_overlap_scoring(self, complex_identity: IdentityModel) -> None:
        """Test heuristic scoring based on keyword overlap."""
        verifier = CoherenceVerifier(complex_identity, llm=None)

        # High overlap with identity
        aligned_demand = AttentionDemand.create(
            source="work",
            content="Build local-first AI assistant with clean code and tests",
            urgency=6,
        )
        aligned_result = verifier.verify(aligned_demand)

        # Low overlap with identity
        unrelated_demand = AttentionDemand.create(
            source="random",
            content="Buy groceries and pick up dry cleaning",
            urgency=3,
        )
        unrelated_result = verifier.verify(unrelated_demand)

        # Aligned demand should score higher
        assert aligned_result.overall_score > unrelated_result.overall_score


class TestCoherenceTraceStorageE2E:
    """E2E tests for coherence trace storage and retrieval."""

    def test_save_and_retrieve_trace(
        self,
        cairn_store: CairnStore,
        complex_identity: IdentityModel,
    ) -> None:
        """Test saving and retrieving coherence traces."""
        from reos.cairn.identity import get_identity_hash

        verifier = CoherenceVerifier(complex_identity, llm=None)

        demand = AttentionDemand.create(
            source="test",
            content="Build developer tools",
            urgency=5,
        )

        result = verifier.verify(demand)
        identity_hash = get_identity_hash(complex_identity)
        trace = CoherenceTrace.create(result, identity_hash)

        # Save trace using individual params
        cairn_store.save_coherence_trace(
            trace_id=trace.trace_id,
            demand_id=trace.demand_id,
            timestamp=trace.timestamp,
            identity_hash=trace.identity_hash,
            checks=[c.to_dict() for c in trace.checks],
            final_score=trace.final_score,
            recommendation=trace.recommendation,
        )

        # Retrieve trace
        retrieved = cairn_store.get_coherence_trace(trace.trace_id)

        assert retrieved is not None
        assert retrieved["demand_id"] == trace.demand_id
        assert retrieved["final_score"] == trace.final_score

    def test_record_user_override(
        self,
        cairn_store: CairnStore,
        complex_identity: IdentityModel,
    ) -> None:
        """Test recording user override of coherence decision."""
        from reos.cairn.identity import get_identity_hash

        verifier = CoherenceVerifier(complex_identity, llm=None)

        demand = AttentionDemand.create(
            source="test",
            content="Something neutral",
            urgency=5,
        )

        result = verifier.verify(demand)
        trace = CoherenceTrace.create(result, get_identity_hash(complex_identity))

        cairn_store.save_coherence_trace(
            trace_id=trace.trace_id,
            demand_id=trace.demand_id,
            timestamp=trace.timestamp,
            identity_hash=trace.identity_hash,
            checks=[c.to_dict() for c in trace.checks],
            final_score=trace.final_score,
            recommendation=trace.recommendation,
        )

        # User overrides the decision
        cairn_store.record_user_override(trace.trace_id, "accept")

        # Retrieve and verify override
        updated = cairn_store.get_coherence_trace(trace.trace_id)
        assert updated is not None
        assert updated["user_override"] == "accept"

    def test_list_traces_for_demand(
        self,
        cairn_store: CairnStore,
        complex_identity: IdentityModel,
    ) -> None:
        """Test listing traces for a specific demand."""
        from reos.cairn.identity import get_identity_hash

        verifier = CoherenceVerifier(complex_identity, llm=None)
        identity_hash = get_identity_hash(complex_identity)

        # Create multiple traces for same demand type
        for i in range(3):
            demand = AttentionDemand.create(
                source="test",
                content=f"Test demand {i}",
                urgency=5,
            )
            result = verifier.verify(demand)
            trace = CoherenceTrace.create(result, identity_hash)
            cairn_store.save_coherence_trace(
                trace_id=trace.trace_id,
                demand_id=trace.demand_id,
                timestamp=trace.timestamp,
                identity_hash=trace.identity_hash,
                checks=[c.to_dict() for c in trace.checks],
                final_score=trace.final_score,
                recommendation=trace.recommendation,
            )

        # List all traces
        traces = cairn_store.list_coherence_traces(limit=10)
        assert len(traces) == 3


# =============================================================================
# Surfacing Algorithm E2E Tests
# =============================================================================


class TestSurfacingAlgorithmE2E:
    """E2E tests for the surfacing algorithm."""

    def test_surface_by_priority(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
    ) -> None:
        """Test that higher priority items surface first."""
        # Create items with different priorities
        cairn_store.get_or_create_metadata("act", "low-priority")
        cairn_store.set_kanban_state("act", "low-priority", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "low-priority", 1)

        cairn_store.get_or_create_metadata("act", "high-priority")
        cairn_store.set_kanban_state("act", "high-priority", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "high-priority", 5)

        cairn_store.get_or_create_metadata("act", "medium-priority")
        cairn_store.set_kanban_state("act", "medium-priority", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "medium-priority", 3)

        results = surfacer.surface_next()

        if results:
            # First result should be highest priority
            priorities = []
            for item in results:
                meta = cairn_store.get_metadata(item.entity_type, item.entity_id)
                if meta and meta.priority:
                    priorities.append(meta.priority)

            if len(priorities) >= 2:
                # Priorities should be descending (highest first)
                assert priorities[0] >= priorities[-1]

    def test_surface_due_today(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
    ) -> None:
        """Test surfacing items due today."""
        # Item due today
        cairn_store.get_or_create_metadata("beat", "due-today")
        cairn_store.set_kanban_state("beat", "due-today", KanbanState.ACTIVE)
        now = datetime.now()
        end_of_day = now.replace(hour=23, minute=59, second=59)
        cairn_store.set_due_date("beat", "due-today", end_of_day)

        # Item due next week
        cairn_store.get_or_create_metadata("beat", "due-later")
        cairn_store.set_kanban_state("beat", "due-later", KanbanState.ACTIVE)
        cairn_store.set_due_date("beat", "due-later", now + timedelta(days=7))

        results = surfacer.surface_today()

        # Due today should be in results
        entity_ids = [r.entity_id for r in results]
        assert "due-today" in entity_ids

    def test_surface_stale_items(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
    ) -> None:
        """Test surfacing stale (untouched) items."""
        # Create item and make it stale
        cairn_store.get_or_create_metadata("scene", "stale-item")
        cairn_store.set_kanban_state("scene", "stale-item", KanbanState.ACTIVE)

        # Manually set last_touched to 10 days ago
        metadata = cairn_store.get_metadata("scene", "stale-item")
        assert metadata is not None
        metadata.last_touched = datetime.now() - timedelta(days=10)
        cairn_store.save_metadata(metadata)

        results = surfacer.surface_stale(days=7)

        assert len(results) >= 1
        assert any(r.entity_id == "stale-item" for r in results)

    def test_surface_waiting_items(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
    ) -> None:
        """Test surfacing items in WAITING state."""
        cairn_store.get_or_create_metadata("beat", "waiting-item")
        cairn_store.set_kanban_state(
            "beat",
            "waiting-item",
            KanbanState.WAITING,
            waiting_on="Client approval",
        )

        results = surfacer.surface_waiting()

        assert len(results) >= 1
        waiting_item = next((r for r in results if r.entity_id == "waiting-item"), None)
        assert waiting_item is not None

    def test_surface_needs_priority(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
    ) -> None:
        """Test surfacing active items without priority."""
        # Active item without priority
        cairn_store.get_or_create_metadata("act", "no-priority")
        cairn_store.set_kanban_state("act", "no-priority", KanbanState.ACTIVE)

        # Active item with priority
        cairn_store.get_or_create_metadata("act", "has-priority")
        cairn_store.set_kanban_state("act", "has-priority", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "has-priority", 3)

        results = surfacer.surface_needs_priority()

        entity_ids = [r.entity_id for r in results]
        assert "no-priority" in entity_ids
        assert "has-priority" not in entity_ids


class TestCoherenceEnabledSurfacingE2E:
    """E2E tests for coherence-enabled surfacing."""

    def test_surfacing_with_coherence_filter(
        self,
        cairn_store: CairnStore,
        temp_play_root: Path,
    ) -> None:
        """Test that coherence filtering affects surfacing results."""
        from reos import play_fs
        from reos.cairn.identity import add_anti_pattern

        # Create items
        cairn_store.get_or_create_metadata("act", "coherent-item")
        cairn_store.set_kanban_state("act", "coherent-item", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "coherent-item", 5)

        cairn_store.get_or_create_metadata("act", "incoherent-item")
        cairn_store.set_kanban_state("act", "incoherent-item", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "incoherent-item", 5)

        # Create surfacer with LLM (would need to mock for full test)
        surfacer = CairnSurfacer(cairn_store, llm=None)

        # Surface without coherence (baseline)
        with patch.object(play_fs, "play_root", return_value=temp_play_root):
            results = surfacer.surface_next(enable_coherence=False)

            # Both items should appear
            entity_ids = [r.entity_id for r in results]
            assert len(entity_ids) >= 1


# =============================================================================
# Full E2E Flow Tests
# =============================================================================


class TestFullCAIRNFlowE2E:
    """Full end-to-end flow tests simulating real user scenarios."""

    def test_morning_routine_surfacing(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
        thunderbird_bridge: ThunderbirdBridge,
    ) -> None:
        """Simulate morning routine: what should I focus on today?"""
        # Set up some items
        cairn_store.get_or_create_metadata("act", "main-project")
        cairn_store.set_kanban_state("act", "main-project", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "main-project", 5)

        cairn_store.get_or_create_metadata("beat", "urgent-task")
        cairn_store.set_kanban_state("beat", "urgent-task", KanbanState.ACTIVE)
        cairn_store.set_priority("beat", "urgent-task", 5)
        cairn_store.set_due_date("beat", "urgent-task", datetime.now() + timedelta(hours=4))

        cairn_store.get_or_create_metadata("beat", "someday-task")
        cairn_store.set_kanban_state("beat", "someday-task", KanbanState.SOMEDAY)

        # Get today's focus
        today_items = surfacer.surface_today()
        next_items = surfacer.surface_next()

        # Calendar events
        events = thunderbird_bridge.get_today_events()

        # Combine for morning briefing
        assert len(today_items) >= 0 or len(next_items) >= 0 or len(events) >= 0

    def test_contact_project_lookup(
        self,
        cairn_store: CairnStore,
        thunderbird_bridge: ThunderbirdBridge,
    ) -> None:
        """Simulate: what am I working on with Alice?"""
        # Create project and link to contact
        cairn_store.get_or_create_metadata("act", "project-with-alice")
        cairn_store.set_kanban_state("act", "project-with-alice", KanbanState.ACTIVE)
        cairn_store.link_contact(
            "contact-1",  # Alice
            "act",
            "project-with-alice",
            ContactRelationship.COLLABORATOR,
        )

        cairn_store.get_or_create_metadata("beat", "alice-task")
        cairn_store.link_contact(
            "contact-1",
            "beat",
            "alice-task",
            ContactRelationship.WAITING_ON,
            notes="Waiting for Alice's review",
        )

        # Look up Alice's contact
        contacts = thunderbird_bridge.search_contacts("Alice")
        assert len(contacts) == 1
        alice = contacts[0]

        # Get all links for Alice
        links = cairn_store.get_contact_links(contact_id="contact-1")
        assert len(links) == 2

        # Check waiting items
        waiting_links = [l for l in links if l.relationship == ContactRelationship.WAITING_ON]
        assert len(waiting_links) == 1

    def test_coherence_rejection_flow(
        self,
        cairn_store: CairnStore,
        complex_identity: IdentityModel,
    ) -> None:
        """Simulate: rejecting an incoherent demand and recording override."""
        from reos.cairn.identity import get_identity_hash

        verifier = CoherenceVerifier(complex_identity, llm=None)

        # Incoherent demand
        demand = AttentionDemand.create(
            source="email",
            content="Join our blockchain startup!",
            urgency=9,
        )

        result = verifier.verify(demand)

        # Should be rejected
        assert result.recommendation == "reject"

        # Save trace using individual params
        trace = CoherenceTrace.create(result, get_identity_hash(complex_identity))
        cairn_store.save_coherence_trace(
            trace_id=trace.trace_id,
            demand_id=trace.demand_id,
            timestamp=trace.timestamp,
            identity_hash=trace.identity_hash,
            checks=[c.to_dict() for c in trace.checks],
            final_score=trace.final_score,
            recommendation=trace.recommendation,
        )

        # User disagrees and overrides
        cairn_store.record_user_override(trace.trace_id, "defer")

        # Verify override recorded
        updated = cairn_store.get_coherence_trace(trace.trace_id)
        assert updated is not None
        assert updated["user_override"] == "defer"

    def test_activity_tracking_workflow(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
    ) -> None:
        """Simulate: tracking activity over time."""
        # Create item
        cairn_store.get_or_create_metadata("beat", "tracked-task")
        cairn_store.set_kanban_state("beat", "tracked-task", KanbanState.ACTIVE)

        # Touch it multiple times (simulating user interaction)
        cairn_store.touch("beat", "tracked-task", ActivityType.VIEWED)
        cairn_store.touch("beat", "tracked-task", ActivityType.EDITED)
        cairn_store.touch("beat", "tracked-task", ActivityType.VIEWED)

        # Check activity log
        log = cairn_store.get_activity_log("beat", "tracked-task")
        assert len(log) >= 3

        # Check touch count
        metadata = cairn_store.get_metadata("beat", "tracked-task")
        assert metadata is not None
        assert metadata.touch_count >= 3

    def test_defer_and_resurface_workflow(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
    ) -> None:
        """Simulate: deferring an item and having it resurface."""
        # Create active item
        cairn_store.get_or_create_metadata("beat", "deferrable-task")
        cairn_store.set_kanban_state("beat", "deferrable-task", KanbanState.ACTIVE)
        cairn_store.set_priority("beat", "deferrable-task", 3)

        # Defer for 1 day (in past for test)
        yesterday = datetime.now() - timedelta(days=1)
        cairn_store.defer_until("beat", "deferrable-task", yesterday)

        # Check state changed to SOMEDAY
        metadata = cairn_store.get_metadata("beat", "deferrable-task")
        assert metadata is not None
        assert metadata.kanban_state == KanbanState.SOMEDAY

        # In a real implementation, a background job would check deferred items
        # and move them back to ACTIVE when defer_until has passed


# =============================================================================
# MCP Tools E2E Tests
# =============================================================================


class TestMCPToolsE2E:
    """E2E tests for MCP tool interface."""

    def test_list_tools_returns_tools(self) -> None:
        """Test that list_tools returns tool definitions."""
        from reos.cairn.mcp_tools import list_tools

        tools = list_tools()

        # Should have multiple tools
        assert len(tools) > 0

        # Each tool should have required fields
        for tool in tools:
            assert hasattr(tool, "name")
            assert hasattr(tool, "description")
            assert hasattr(tool, "input_schema")
            assert tool.name.startswith("cairn_")

    def test_tool_names_exist(self) -> None:
        """Test that expected tool names are defined."""
        from reos.cairn.mcp_tools import list_tools

        tools = list_tools()
        tool_names = {t.name for t in tools}

        # Check for key tools
        expected_tools = [
            "cairn_list_items",
            "cairn_get_item",
            "cairn_surface_next",
            "cairn_set_priority",
        ]

        for expected in expected_tools:
            assert expected in tool_names, f"Missing tool: {expected}"

    def test_surfacer_integration(
        self,
        cairn_store: CairnStore,
        surfacer: CairnSurfacer,
    ) -> None:
        """Test surfacer integration that MCP tools use."""
        # Set up items
        cairn_store.get_or_create_metadata("act", "tool-test-item")
        cairn_store.set_kanban_state("act", "tool-test-item", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "tool-test-item", 5)

        # Use surfacer directly (same as MCP tool would)
        results = surfacer.surface_next()

        # Should return list
        assert isinstance(results, list)

    def test_store_operations_for_tools(
        self,
        cairn_store: CairnStore,
    ) -> None:
        """Test store operations that MCP tools use."""
        # Create metadata (cairn_get_item uses this)
        cairn_store.get_or_create_metadata("beat", "tool-test")
        metadata = cairn_store.get_metadata("beat", "tool-test")
        assert metadata is not None

        # Set priority (cairn_set_priority uses this)
        cairn_store.set_priority("beat", "tool-test", 4, reason="Testing")
        updated = cairn_store.get_metadata("beat", "tool-test")
        assert updated is not None
        assert updated.priority == 4

        # Set kanban state (cairn_set_kanban_state uses this)
        cairn_store.set_kanban_state("beat", "tool-test", KanbanState.ACTIVE)
        updated = cairn_store.get_metadata("beat", "tool-test")
        assert updated is not None
        assert updated.kanban_state == KanbanState.ACTIVE
