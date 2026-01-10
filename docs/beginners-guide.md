# Beginner's Guide to Talking Rock

## What is Talking Rock?

Talking Rock is a local-first AI assistant with three specialized agents:

| Agent | What It Does | When to Use |
|-------|--------------|-------------|
| **CAIRN** | Attention minder, life organizer | "What should I focus on?", "Show me waiting items" |
| **ReOS** | System control for Linux | "Install docker", "Why is nginx failing?" |
| **RIVA** | Coding assistant | "Add login to my API", "Fix the failing tests" |

Everything runs locally. Your data never leaves your machine.

## Quick Start

### 1. Install Dependencies

```bash
# Ollama (local LLM)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# Python 3.12+
# (use your distro's package manager)
```

### 2. Install Talking Rock

```bash
git clone https://github.com/sefton37/talking_rock.git
cd talking_rock
pip install -e .
```

### 3. Run

```bash
# CLI mode
reos "what services are running?"

# Or start the desktop app
cd apps/reos-tauri && npm install && npm run tauri:dev
```

## Your First Conversations

### With ReOS (System Agent)

```
You: What's using the most memory?
ReOS: [Shows top processes by memory usage with explanation]

You: Install htop
ReOS: I'll install htop. Command: sudo apt install htop
      Proceed? [y/N]
```

ReOS always previews commands before running them.

### With CAIRN (Attention Minder)

```
You: Create an act called "Side Projects"
CAIRN: Created Act "Side Projects". Want to add a Scene?

You: What needs my attention?
CAIRN: Based on your Play:
       - Scene "Learn Rust" hasn't been touched in 2 weeks
       - Beat "Review PR #42" is waiting on Alex since Monday
```

CAIRN helps you organize without guilt-tripping.

### With RIVA (Coding Agent)

```
You: Add input validation to the login endpoint
RIVA: I'll analyze the codebase and create a contract...
      [Shows diff preview]
      Apply these changes? [y/N]
```

RIVA shows you exactly what it will change before doing it.

## Key Principles

1. **Local-first** - All data stays on your machine
2. **Transparency** - Every action is previewed and explained
3. **Capability transfer** - Learn patterns, become more capable over time
4. **Non-coercive** - Surfaces options, never guilt-trips or gamifies

## Next Steps

- Set up The Play: `docs/the-play.md`
- Understand ReOS safety: `docs/security.md`
- Explore CAIRN: `docs/cairn_architecture.md`
- Explore RIVA: `docs/code_mode_architecture.md`

## Getting Help

- Issues: https://github.com/sefton37/talking_rock/issues
- Charter: `.github/ReOS_charter.md`
