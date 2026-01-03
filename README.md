# ReOS - Natural Language Linux

**Make using Linux as easy as having a conversation.**

ReOS is a local-first AI companion that lets you control your entire Linux system through natural language. No more memorizing commands, reading man pages, or searching Stack Overflow. Just describe what you want to do, and ReOS helps you do it safely.

## What Makes ReOS Different

- **Truly Local**: Runs entirely on your machine using Ollama. No cloud, no latency, no privacy concerns.
- **Deep System Understanding**: ReOS knows YOUR system - your distro, your packages, your services, your processes.
- **Transparent Actions**: Every command is previewed before execution. You always see what's happening.
- **Recoverable Mistakes**: Destructive operations show undo commands. It's conversational - you can say "wait, undo that."
- **Safety First**: Dangerous commands are blocked. Risky operations require confirmation.
- **No Paperclips**: Hard-coded circuit breakers prevent runaway AI execution. [Learn more](#circuit-breakers)

## Examples

```
You: Show me what's using the most memory
ReOS: [Lists top processes by memory usage]

You: My disk is almost full, help me clean up
ReOS: [Analyzes disk usage, suggests safe cleanup options]

You: Install docker and set it up for my user
ReOS: [Previews commands, installs Docker, adds you to group]

You: What services are failing?
ReOS: [Lists failed systemd services with details]

You: The nginx config has a typo, help me fix it
ReOS: [Reads config, identifies issue, shows diff before applying]
```

## Quick Start

```bash
# 1. Install Ollama (if not already installed)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# 2. Clone and install ReOS
git clone https://github.com/sefton37/ReOS
cd ReOS
pip install -e .

# 3. Run the desktop app
cd apps/reos-tauri
npm install
npm run tauri:dev
```

## Linux Tools

ReOS provides natural language access to:

| Category | Capabilities |
|----------|-------------|
| **System Info** | CPU, memory, disk, network, load averages, uptime |
| **Process Management** | List, sort by CPU/memory, identify resource hogs |
| **Service Management** | Start/stop/restart systemd services, view status |
| **Package Management** | Search, install, remove packages (apt/dnf/pacman/zypper) |
| **File Operations** | List directories, find files, read logs |
| **Docker** | List containers and images, manage containers |
| **Shell Commands** | Execute any safe command with previews for destructive ops |

## Safety Features

ReOS is designed to prevent accidents:

- **Blocked**: Commands like `rm -rf /`, fork bombs, disk formatting
- **Preview Mode**: Destructive commands show what they'll do first
- **Undo Support**: Many operations provide an undo command
- **Warnings**: Risky patterns are flagged before execution

```
You: Delete all the temp files
ReOS: [Preview] This will delete 47 files in /tmp:
      - /tmp/session_12345
      - /tmp/cache_xyz
      - ... (45 more)
      This action cannot be undone. Proceed? [y/N]
```

## Circuit Breakers

**The "paperclip problem" won't happen here.**

You've heard the thought experiment: tell an AI to make paperclips efficiently, and it converts the entire planet into paperclips because you didn't say when to stop. ReOS has hard-coded limits that **the AI cannot override**:

| Protection | What It Prevents |
|------------|------------------|
| **Operation Limit** | Max 25 commands per plan—no infinite loops |
| **Time Limit** | 5 minute hard cap—no runaway execution |
| **Privilege Cap** | Max 3 sudo escalations—can't keep adding permissions |
| **Scope Lock** | Blocks actions unrelated to your request |
| **Human Checkpoints** | Forces pause after 2 automatic recoveries |

If the AI tries to "fix" your nginx install by deleting system logs? **Blocked.** Tries to run 100 commands to "optimize" your system? **Stopped at 25.** Keeps escalating to root? **Capped at 3.**

```
You: fix everything on my system

ReOS: [After 25 operations]
      ⚠️ Execution paused: Maximum operations reached (25/25)

      Completed: 24 steps
      Pending: 8 steps remaining

      Continue? (This resets the operation counter)
```

These limits are enforced in code, not by the AI's "judgment." The AI literally cannot change them during execution. Only you can modify them in config.

[Full technical details →](docs/reasoning.md#circuit-breakers-paperclip-problem-prevention)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Tauri Desktop App                     │
│  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │ Chat Window  │  │System Panel │  │  Inspector    │  │
│  └──────────────┘  └─────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────┘
                           │ JSON-RPC (stdio)
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    Python Kernel                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ Ollama LLM  │  │ Linux Tools │  │  SQLite State   │ │
│  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   Your Linux System                      │
│    systemd │ apt/dnf/pacman │ docker │ files │ ...     │
└─────────────────────────────────────────────────────────┘
```

## Principles

From the [ReOS Charter](.github/ReOS_charter.md):

> ReOS exists to protect, reflect, and return human attention.

Applied to system administration:
- **Transparent**: You see every command before it runs
- **Explainable**: ReOS explains why it suggests what it does
- **Recoverable**: Mistakes can be undone through conversation
- **Sovereign**: Your system, your data, your choice

## Requirements

- Linux (any major distro)
- Python 3.12+
- Node.js 18+
- Rust toolchain (for Tauri)
- Ollama with a local model

## Development

```bash
# Run tests
uv run pytest tests/

# Run with debug logging
REOS_LOG_LEVEL=DEBUG npm run tauri:dev
```

## Roadmap

- [ ] Command history and undo stack
- [ ] System monitoring dashboard
- [ ] Cron job management
- [ ] Network configuration
- [ ] User/group management
- [ ] Firewall configuration
- [ ] Backup automation

## License

MIT

---

*ReOS: Because your computer should understand you, not the other way around.*
