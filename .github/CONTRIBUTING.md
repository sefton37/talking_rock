# Contributing to Talking Rock

## Before You Start

Read the charter: `.github/ReOS_charter.md`

Key principles that guide all contributions:
- **Local-first**: No cloud dependencies for core functionality
- **Transparency**: Every action previewed and explained
- **Capability transfer**: Users should become MORE capable, not dependent
- **Non-coercive**: Never guilt-trip, gamify, or manipulate

## Architecture Overview

Talking Rock has three agents:

| Agent | Code Location | Purpose |
|-------|---------------|---------|
| **CAIRN** | `src/reos/cairn/` | Attention minder |
| **ReOS** | `src/reos/linux_tools.py`, `src/reos/reasoning/` | System control |
| **RIVA** | `src/reos/code_mode/` | Coding assistant |

## Development Setup

```bash
# Clone and install
git clone https://github.com/sefton37/talking_rock.git
cd talking_rock
pip install -e ".[dev]"

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
```

## Code Style

```bash
# Lint
ruff check src/ tests/

# Type check
mypy src/ --ignore-missing-imports

# Test
pytest
```

Requirements:
- 100-char line limit
- Sorted imports
- Type hints on public functions
- Use `collections.abc.Callable`, not `typing.Callable`

## Making Changes

### 1. Understand Which Agent You're Modifying

- **CAIRN changes**: Affect attention/priority logic, The Play, coherence filtering
- **ReOS changes**: Affect system control, command safety, reasoning
- **RIVA changes**: Affect code generation, contracts, execution loop

### 2. Ask the Right Questions

Before writing code:
- Does this serve user sovereignty?
- Is this local-only?
- Does it respect the transparency principle?
- Will users become more capable, or more dependent?

### 3. Write Tests

All changes should have tests. See `docs/testing-strategy.md`.

### 4. Submit a PR

- Clear description of what changed and why
- Reference any related issues
- Ensure CI passes

## What We Will Not Accept

- Cloud dependencies for core features
- Telemetry or data collection without explicit opt-in
- Gamification (streaks, points, badges)
- Dark patterns or engagement hacking
- Features that increase dependency rather than capability

## Questions?

Open an issue or read the docs:
- `docs/tech-roadmap.md` - Where we're going
- `docs/cairn_architecture.md` - CAIRN design
- `docs/code_mode_architecture.md` - RIVA design
- `docs/security.md` - Safety design
