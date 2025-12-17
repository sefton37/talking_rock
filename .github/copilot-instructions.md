## Copilot Instructions for ReOS

### Vision: Git Companion (Build Anywhere, Reflect in ReOS)

ReOS is a **companion attention system** for developers.

- Your editor is the primary workspace (any editor).
- **Git is the primary signal source** for what changed.
- ReOS sits alongside and reflects back patterns: drift vs plan, too many parallel threads, and gentle checkpoints.

ReOS is **not** a task manager and **not** a surveillance tool. It is a memory + reflection surface for how attention is being spent through changes.

### Current Architecture (Git-First)

**Tech Stack**: Python 3.12, PySide6 (ReOS GUI), FastAPI (optional local event service), Ollama (local LLM), SQLite (local persistence), Git CLI.

**Key Components**:
1. **Git Observer** (Primary Observer)
   - Polls repo metadata locally (`git status`, `git diff --stat`, `git diff --numstat`).
   - Optionally (explicit opt-in), includes limited diff text for deeper review.
   - File: `src/reos/git_poll.py`

2. **ReOS Desktop App** (Companion + Reflection)
   - 3-pane layout: repos | reflection | inspection (reasoning trail).
   - Surfaces gentle checkpoints when changes suggest drift or too many threads.
   - Files: `src/reos/gui/main_window.py`, `src/reos/gui/__init__.py`

3. **SQLite Core** (Single Source of Truth)
   - Stores git snapshots + checkpoint events + user notes.
   - File: `src/reos/db.py`

4. **Command Registry** (Reasoning About Alignment)
   - Commands are repo-centric and compare changes against `docs/tech-roadmap.md` + `ReOS_charter.md`.
   - File: `src/reos/commands.py`

5. **Ollama Layer** (Local LLM)
   - All reasoning local; no cloud calls.
   - File: `src/reos/ollama.py`

### Design Principles

- **Bifocal Workflow**: Your editor is primary (your flow stays unbroken); ReOS is always-on companion.
- **Observation Over Prescription**: ReOS notices what you're doing, doesn't tell you what to do.
- **Attention as Sacred**: Reflections honor labor—never shame, guilt, or moral judgment.
- **Checks & Balances**: Proactive nudges ("You've been deep for 2 hrs—water break?"), not punishments.
- **Local-First**: All data SQLite; no sync to cloud without explicit consent.
- **Transparent Reasoning**: Every ReOS insight shows its full reasoning trail; user can inspect.

### When Working on ReOS Code

**Before Writing Code**:
1. Check the charter ([ReOS_charter.md](../ReOS_charter.md)) — does this serve "protect, reflect, return attention"?
2. Ask: "Does this strengthen the Git-first + ReOS bifocal system, or create distraction?"
3. If adding data collection: "Is this metadata-only? Does user consent?"
4. If adding UI/language: "Is this compassionate, non-prescriptive, non-judgmental?"

**Architecture Principles**:
- Git polling is the **observer** (collect local repo signals).
- ReOS app is the **companion** (reflect, offer wisdom).
- Bifocal means: the editor should not be disrupted; ReOS prompts should be wise, not noisy.
- Drift/threads are assessed against charter + roadmap; avoid conjuring intent from metadata.

**Code Style & Validation**:
- `ruff check` (100-char lines, sorted imports, PEP8)
- `mypy src/ --ignore-missing-imports` (PySide6 stubs are sparse)
- `pytest` before commit (5 tests must pass)
- Use `collections.abc.Callable`, not `typing.Callable`
- Add docstrings and type hints to all public functions

**Language & Tone**:
- Avoid: "productivity", "focus mode", "streaks", "good/bad day", "distracted"
- Use: "fragmented/coherent", "revolution/evolution", "your attention was", "what's your intention?"
- Examples:
  - ✗ "You were distracted."
  - ✓ "7 file switches in 5 minutes. Was this creative exploration or fragmentation?"
  - ✗ "Great productivity streak!"
  - ✓ "You've been in this codebase for 3 hours. Deep work or dwelling?"

**Local Data & Git Safety**:
- All data → `.reos-data/` (git-ignored)
- `.gitignore` includes: `*.sqlite*`, `*.db`, `.venv/`, `__pycache__/`, `.reos-data/`
- Never commit DB files, only schemas in code
- Update `.gitignore` when adding new local data types

**Database Work**:
- Schema in `src/reos/db.py` (events, sessions, classifications, audit_log)
- All tables have `created_at`, `ingested_at` for audit trail
- Use `Database.get_db()` singleton for safe access
- Events table: populated by git observer snapshots and checkpoint triggers
- Fresh DB per test (avoid threading issues)

**ReOS Desktop App (PySide6)**:
- Left nav pane: observed repos/sessions (clickable, load context)
- Center: real-time attention dashboard + reflection chat
- Right inspection pane: click on insight → show reasoning (system prompt + LLM output + tools called)
- Proactive prompts: "8 switches in 5 min—settle on one file?" (compassionate, not demanding)
- No gamified UI; no streaks, scores, or "levels"

**Attention Classification** (Coming):
- Track context switching signals (optionally from editor events; Git remains primary)
- Detect "frayed mind" (rapid switches + shallow engagement + no-break periods)
- Classify periods as: coherent (deep focus) vs fragmented (scattered attention)
- Classify as: revolution (disruptive change) vs evolution (gradual integration)
- Use parameterized heuristics (explainable), not opaque ML
- Reflect without judgment: "This period shows high switching" not "You were distracted"

**Checks & Balances System** (Coming):
- Real-time detection: "8 context switches in 5 minutes"
- Proactive prompts: "Settle into one file? Or is this creative exploration?"
- Intention checks: "You've been on this file for 30 min—understanding emerging?"
- Rest prompts: "Deep focus for 2 hours—good. Water break?"
- All prompts are compassionate, never shaming

**Non-Goals** (flag if requested):
- ❌ Task managers or todo lists
- ❌ Gamified streaks, quotas, productivity scores
- ❌ Engagement loops or dopamine-driven UX
- ❌ Cloud storage without explicit consent
- ❌ Keystroke logging or message-body parsing
- ❌ "Good/bad day" moral framing
- ❌ Corporate surveillance

### Typical Workflow (Vision)

```
1. User codes in their editor of choice
2. ReOS observes the repo (local Git polling):
   - working tree state
   - diffstat/numstat (change breadth)
   - optional diff text (explicit opt-in)
   → stored in SQLite
3. ReOS shows:
   - repo status + change scope signals
   - checkpoints: drift vs charter/roadmap, or too many threads
4. User can open an insight to see the inspection trail and add a note.

Result: Your editor stays primary; ReOS stays a quiet companion that helps you return to intention.
```

### Running & Testing

```bash
# ReOS Desktop App
python -m reos.gui          # Launch app
reos-gui                     # (same, via script entry)

# FastAPI Service (feeds events into SQLite)
python -m reos.app          # Runs on http://127.0.0.1:8010

# Tests
pytest                       # Run test suite

# Lint + Type Check
ruff check src/ tests/       # Linting
mypy src/ --ignore-missing-imports  # Type checking
```

### Key Files to Know

| File | Purpose | Team |
|------|---------|------|
| `src/reos/git_poll.py` | Git observer polling and snapshot events | Core |
| `src/reos/gui/main_window.py` | ReOS 3-pane layout | GUI |
| `src/reos/commands.py` | Attention introspection commands | Core |
| `src/reos/db.py` | SQLite schema (events, sessions, classifications) | Core |
| `src/reos/ollama.py` | Local LLM client | Core |
| `src/reos/app.py` | FastAPI service (event ingestion) | Core |
| `tests/test_db.py` | SQLite tests | Tests |
| `docs/tech-roadmap.md` | Architecture & milestones | Planning |
| `ReOS_charter.md` | Core values & principles | Vision |

### Before You Ask for Help

- Is your question about a principle → check the charter first
- Is it about bifocal architecture → ask: "Does this keep the editor unbroken while ReOS is wise?"
- Is it about language → ask: "Is this compassionate and non-prescriptive?"
- Is it about data → ask: "Is this metadata-only? Does user consent?"
- Is it about code style → run ruff, mypy, pytest

**Guiding Question**: "Does this help the user choose how to spend their attention, or does it try to control their attention?"

If the latter, you're off-vision. Attention is labor and sacred. We protect it, reflect it; we don't optimize it.

When in doubt, re-read [ReOS_charter.md](../ReOS_charter.md) and ask for clarification before proceeding.
