## Copilot Instructions for Talking Rock

### Vision: AI That Works For You, On Your Terms

**Talking Rock** is a local-first AI assistant with three specialized agents:

| Agent | Purpose | Kernel Principle |
|-------|---------|------------------|
| **CAIRN** | Attention minder & life organizer (default) | "If you can't verify coherence, decompose the demand" |
| **ReOS** | System agent for Linux control | "Native until foreign. Foreign until confirmed." |
| **RIVA** | Coding agent for development | "If you can't verify it, decompose it" |

Talking Rock is **not** a productivity tracker or surveillance tool. It is a local-first companion that respects user sovereignty.

### Current Architecture

**Tech Stack**: Python 3.12 (kernel), Tauri+Vite+TypeScript (desktop UI), FastAPI (local service), Ollama (local LLM), SQLite (persistence).

**Key Components**:

1. **CAIRN (Attention Minder)**
   - Default agent users interact with
   - Manages The Play knowledge base (Acts/Scenes/Beats)
   - Routes to ReOS (system) or RIVA (code) based on request
   - Coherence Kernel filters attention through user identity
   - Files: `src/reos/cairn/`

2. **ReOS (System Agent)**
   - Natural language Linux control
   - Parse Gate: context-aware command proposals
   - Safety layer with circuit breakers
   - Files: `src/reos/linux_tools.py`, `src/reos/reasoning/`

3. **RIVA (Coding Agent)**
   - Intent discovery + contract-based development
   - Test-first, self-debugging loop
   - Recursive intention-verification architecture
   - Files: `src/reos/code_mode/`

4. **Tauri Desktop App**
   - TypeScript/Tauri shell spawning Python kernel
   - 3-pane layout: nav, chat, inspection
   - Files: `apps/reos-tauri/`

5. **SQLite Core**
   - Conversations, system state, The Play, audit logs
   - File: `src/reos/db.py`

### Design Principles

- **Local-First**: All data stays on user's machine. No cloud calls for core functionality.
- **Transparency Over Magic**: Every action previewed, explained, reversible.
- **Capability Transfer**: Users should become MORE capable over time, not dependent.
- **Non-Coercion**: Surfaces options, never guilt-trips or gamifies.
- **Safety Without Surveillance**: Circuit breakers the AI cannot override.

### When Working on Talking Rock Code

**Before Writing Code**:
1. Check which agent this affects (CAIRN, ReOS, or RIVA)
2. Ask: "Does this serve user sovereignty and local-first principles?"
3. If adding data collection: "Is this local-only? Does user consent?"
4. If adding UI/language: "Is this compassionate, non-prescriptive?"

**Code Style & Validation**:
- `ruff check` (100-char lines, sorted imports, PEP8)
- `mypy src/ --ignore-missing-imports`
- `pytest` before commit
- Use `collections.abc.Callable`, not `typing.Callable`
- Add docstrings and type hints to public functions

**Language & Tone**:
- Avoid: "productivity", "focus mode", "streaks", "good/bad day"
- Use: "coherent/fragmented", "what needs attention", "what's your intention?"

**Local Data**:
- All data in `.reos-data/` (git-ignored)
- SQLite for persistence
- Never commit DB files, only schemas in code

### Key Files to Know

| File | Purpose |
|------|---------|
| `src/reos/cairn/` | CAIRN attention minder |
| `src/reos/code_mode/` | RIVA coding agent |
| `src/reos/linux_tools.py` | ReOS system tools |
| `src/reos/reasoning/` | ReOS reasoning engine |
| `src/reos/agent.py` | Chat agent orchestration |
| `src/reos/db.py` | SQLite schema |
| `src/reos/mcp_tools.py` | MCP tool registry |
| `apps/reos-tauri/` | Desktop UI |
| `docs/tech-roadmap.md` | Architecture & milestones |
| `.github/ReOS_charter.md` | ReOS principles |
| `docs/cairn_architecture.md` | CAIRN design |
| `docs/code_mode_architecture.md` | RIVA design |
| `docs/parse-gate.md` | ReOS Parse Gate |

### Running & Testing

```bash
# Desktop App (Tauri)
cd apps/reos-tauri && npm install && npm run tauri:dev

# Tests
pytest

# Lint + Type Check
ruff check src/ tests/
mypy src/ --ignore-missing-imports
```

### The Three Kernels

Each agent has its own reasoning kernel:

**CAIRN's Coherence Kernel**:
- Filters attention demands through user identity
- "If you can't verify coherence, decompose the demand"
- Anti-patterns for instant rejection

**ReOS's Parse Gate**:
- "Native until foreign. Foreign until confirmed."
- "If you can't verify it, decompose it."
- Three-layer safety extraction

**RIVA's Intention-Verification**:
- "If you can't verify it, decompose it."
- Recursive decomposition until verifiable
- Test-first contracts

### Non-Goals (flag if requested)

- Task managers or todo lists (CAIRN surfaces, doesn't manage)
- Gamified streaks, quotas, productivity scores
- Cloud storage without explicit consent
- Keystroke logging or surveillance
- Corporate productivity tracking

### Guiding Question

> "Does this help the user choose how to spend their attention, or does it try to control their attention?"

If the latter, you're off-vision. Attention is labor and sacred. We protect it, reflect it; we don't optimize it.

When in doubt, read the README and ask for clarification.
