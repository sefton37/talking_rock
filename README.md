# Talking Rock - Your AI, Your Hardware, Your Life

**The open source, local-first AI that gives you everything the trillion-dollar tech companies charge perpetual rent for—running on your own hardware, with your data staying private when you choose local models.**

Talking Rock is a three-agent system designed around how you actually live:

| Agent | Role | Domain |
|-------|------|--------|
| **CAIRN** | Attention Minder | Life organization, knowledge base, calendars, priorities |
| **ReOS** | System Agent | Linux administration, terminal, services, packages |
| **RIVA** | Code Agent | Software development, debugging, testing, git |

All three share the same philosophy: **AI should be a tool you own, not a service you rent.**

---

## The Three Agents

```
┌─────────────────────────────────────────────────────────────────┐
│                        TALKING ROCK                              │
│                                                                  │
│    ┌──────────────────────────────────────────────────────┐     │
│    │                      CAIRN                            │     │
│    │              (Default Entry Point)                    │     │
│    │         Attention · Life · Knowledge Base             │     │
│    │                                                       │     │
│    │   "Is this a system thing? → ReOS"                   │     │
│    │   "Is this a code thing? → RIVA"                     │     │
│    │   "Is this a life/attention thing? → I handle it"    │     │
│    └───────────────────┬──────────────────────────────────┘     │
│                        │                                         │
│            ┌───────────┴───────────┐                            │
│            ▼                       ▼                            │
│    ┌──────────────┐       ┌──────────────┐                      │
│    │    ReOS      │       │    RIVA      │                      │
│    │   (System)   │       │    (Code)    │                      │
│    │              │       │              │                      │
│    │  Terminal UI │       │ Code Mode UI │                      │
│    └──────────────┘       └──────────────┘                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### CAIRN - The Attention Minder

CAIRN embodies "No One" - calm, non-coercive, makes room rather than demands. It's your scrum master and air traffic controller for everything in your life.

**Core Principles:**
- Surfaces the **next thing**, not everything
- Priority driven by **your decision**—CAIRN surfaces when decisions are needed
- Time and calendar aware (integrates with Thunderbird)
- **Never gamifies, never guilt-trips** ("waiting when you're ready" vs "you haven't touched this")

**Capabilities:**
- Knowledge base CRUD (todos, notes, projects, references)
- Kanban states: Active → Backlog → Waiting → Someday → Done
- Calendar integration (Thunderbird)
- Contact knowledge graph (link people to projects)
- Activity tracking (when you last touched things)
- Smart surfacing (what needs attention today)

### ReOS - The System Agent

ReOS controls your Linux system through conversation. Deep system understanding, transparent actions, safety-first.

```bash
$ reos "what's using all my memory"
Top memory users:
1. chrome (2.3 GB)
2. docker (1.8 GB)
3. code (890 MB)

$ reos "stop all nextcloud containers"
Plan:
  1. Stop nextcloud-app
  2. Stop nextcloud-redis
  3. Stop nextcloud-db

Proceed? [y/n]: y
✓ All containers stopped.
```

**Capabilities:**
- Process and memory monitoring
- Service management (systemd)
- Package management (apt/dnf/pacman)
- Container management (Docker)
- File operations
- Shell command execution (with safety guardrails)

### RIVA - The Code Agent

RIVA (Recursive Intent Verification Architecture) is methodical: it verifies intent before acting, writes tests first, and trusts execution output over LLM claims.

```
You: Add user authentication to the API

RIVA: [INTENT] Analyzing request...
      - Action: Add new feature
      - Target: API authentication

      [CONTRACT] Success criteria:
      ✓ test_login_valid_credentials passes
      ✓ test_login_invalid_password passes
      ✓ test_logout_clears_session passes

      [PLAN] 4 steps:
      1. Create src/auth.py
      2. Add routes to src/api/routes.py
      3. Create tests/test_auth.py
      4. Run tests to verify

      [Showing diff preview...]

      Approve changes? [y/n]
```

**Capabilities:**
- Intent discovery (prompt + project context + codebase patterns)
- Contract-based development (testable success criteria)
- Test-first approach (generates actual test code)
- Self-debugging loop (analyze failures, apply fixes, retry)
- Git operations
- Multi-language support (Python, TypeScript, Rust, Go)

---

## Handoff System

Agents seamlessly hand off to each other when a request falls outside their domain. **Switching is always user-gated**—you confirm or reject every handoff.

```
User (in CAIRN): "My disk is almost full, can you help?"

CAIRN: ## Handoff Proposed: CAIRN → ReOS

       **Why I'm suggesting this handoff:**
       This is a system administration task (disk management) that
       ReOS specializes in.

       **About ReOS:**
       ReOS is the System Agent, specializing in Linux system
       administration, services, packages, processes, and terminal operations.

       **Your choice:**
       You can confirm this handoff, or stay with CAIRN if you prefer.

       [Confirm] [Reject]
```

**Design Principles:**
- **15 tools per agent max** (LLM cognitive research shows degradation beyond ~20)
- **Explicit transitions** with verbose explanations
- **User always in control** - reject any handoff
- **Structured context passing** - receiving agent knows exactly what you need
- **Flexible agents** - handle simple out-of-domain tasks without handoff

---

## The Play - Your Personal Knowledge System

The Play provides context across everything you do:

| Level | Time Horizon | Example |
|-------|--------------|---------|
| **The Play** | Your life | Your identity, values, long-term vision |
| **Acts** | > 1 year | "Building my startup", "Career at Company X" |
| **Scenes** | > 1 month | "Launch MVP", "Q1 Platform Migration" |
| **Beats** | > 1 week | "Set up CI/CD", "Implement auth" |

CAIRN tracks activity across The Play—when you last touched projects, what's active, what's stale. When you assign a repository to an Act, RIVA activates for coding requests in that context.

---

## Safety & Sovereignty

### You're Always in Control

- **Diff preview**: See exactly what will change before any file is modified
- **Approval required**: All file changes, commands, and handoffs require your explicit OK
- **Automatic backups**: Every file modification is backed up
- **Rollback**: Undo any change

### Circuit Breakers

Built-in limits to prevent runaway operations:

| Protection | Limit | Enforcement |
|------------|-------|-------------|
| Max operations per task | 25 | ✓ Enforced |
| Max execution time | 5 minutes | ✓ Enforced |
| Max sudo escalations | 3 per session | ✓ Enforced |
| Debug retry attempts | 3 | ✓ Enforced |
| Human checkpoint | After 2 automated recoveries | ✓ Enforced |
| Tools per agent | 15 max | ✓ Enforced |

### Privacy

- **Local-first**: With Ollama, everything stays on your machine
- **No telemetry**: We don't know you exist
- **Open source**: Audit everything
- **Your choice**: Use Ollama locally, or cloud APIs if you prefer

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TALKING ROCK                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                    Natural Language Layer                    │   │
│   │              Shell CLI  │  Tauri Desktop App                │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                               │                                      │
│   ┌───────────────────────────┴───────────────────────────┐         │
│   │                   Agent Layer (15 tools each)          │         │
│   │                                                        │         │
│   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │         │
│   │   │   CAIRN     │  │    ReOS     │  │    RIVA     │   │         │
│   │   │  Attention  │  │   System    │  │    Code     │   │         │
│   │   │             │  │             │  │             │   │         │
│   │   │ • KB CRUD   │  │ • Shell     │  │ • Read/Edit │   │         │
│   │   │ • Calendar  │  │ • Services  │  │ • Search    │   │         │
│   │   │ • Contacts  │  │ • Packages  │  │ • Tests     │   │         │
│   │   │ • Surfacing │  │ • Docker    │  │ • Git       │   │         │
│   │   └─────────────┘  └─────────────┘  └─────────────┘   │         │
│   │           │                │                │          │         │
│   │           └────────────────┼────────────────┘          │         │
│   │                    Handoff System                      │         │
│   │              (User-gated transitions)                  │         │
│   └────────────────────────────────────────────────────────┘         │
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                  Shared Infrastructure                       │   │
│   │                                                              │   │
│   │  The Play (KB)  │  CAIRN Store  │  Safety Layer  │  Handoff │   │
│   │                                                              │   │
│   │  Ollama │ Anthropic │ OpenAI │ Local llama.cpp              │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# 2. Clone and install
git clone https://github.com/sefton37/ReOS
cd ReOS
pip install -e .

# 3. Run the desktop app
cd apps/reos-tauri
npm install
npm run tauri:dev

# 4. Start with CAIRN (default), switch agents as needed
```

---

## What's Built

### CAIRN (New - Attention Minder)
- [x] Knowledge base integration with The Play
- [x] Kanban state tracking (active, backlog, waiting, someday, done)
- [x] Activity tracking (last touched, touch count)
- [x] Priority management (user-driven, 1-5 scale)
- [x] Time awareness (due dates, defer until, calendar)
- [x] Thunderbird integration (contacts, calendar, events)
- [x] Contact knowledge graph (link people to projects)
- [x] Smart surfacing algorithms
- [x] 22 MCP tools

### ReOS (System Agent)
- [x] Natural language system control
- [x] Deep system understanding (containers, services, packages, processes)
- [x] Multi-step plan generation with approval workflow
- [x] Safety layer (command blocking, risk assessment, rate limiting)
- [x] Circuit breakers (25 ops, 5 min, 3 sudo)

### RIVA (Code Agent)
- [x] Repository assignment to Acts
- [x] Intent discovery (prompt + Play + codebase patterns)
- [x] Contract-based development (testable success criteria)
- [x] Test-first approach (generates actual test code)
- [x] Self-debugging loop (analyze failures, apply fixes, retry)
- [x] Quality tier tracking (transparency when LLM falls back)
- [x] Multi-language tools (Python, TypeScript, Rust, Go)

### Handoff System (New)
- [x] Structured context passing (distilled, not full history)
- [x] User confirmation gates (switching is always user-gated)
- [x] Explicit, verbose transition messaging
- [x] RIVA-style intent verification for multi-domain requests
- [x] 15-tool cap per agent (validated)
- [x] Flexible agents (handle simple out-of-domain tasks)

---

## Comparison: Talking Rock vs Commercial Tools

| Capability | Cursor | Copilot | Devin | Talking Rock |
|------------|--------|---------|-------|--------------|
| Code completion | ✓ | ✓ | ✓ | ✓ |
| Multi-file editing | ✓ | Partial | ✓ | ✓ |
| Test execution | ✓ | ✗ | ✓ | ✓ |
| Self-debugging | Partial | ✗ | ✓ | ✓ |
| **Life organization** | ✗ | ✗ | ✗ | **✓ (CAIRN)** |
| **Linux sysadmin** | ✗ | ✗ | ✗ | **✓ (ReOS)** |
| **Local-First** | ✗ | ✗ | ✗ | **✓** |
| **Open Source** | ✗ | ✗ | ✗ | **✓** |
| **No Subscription** | ✗ | ✗ | ✗ | **✓** |
| **Data Privacy** | ✗ | ✗ | ✗ | **✓** |

---

## The Meaning

Software is eating the world. AI is eating software. And a handful of companies want to be the landlords of AI—charging rent forever for tools that could run on your own hardware.

Talking Rock is the alternative:
- **User sovereignty**: You control the AI, not the other way around
- **Transparency**: See every decision, every step, every line of reasoning
- **Privacy**: With local models, your code and data stay on your machine
- **Freedom**: No lock-in, no subscription, no "we changed our pricing"
- **Holistic**: One system for life, work, and code—not three separate tools

The trillion-dollar companies have resources we don't. But they also have incentives we don't—engagement metrics, retention, lock-in. Talking Rock is optimized purely for what's best for the user.

**The goal: Make the best AI assistant in the world. Then give it away.**

---

## Contributing

Talking Rock is open source (MIT). Contributions welcome:
- Bug reports and feature requests via GitHub Issues
- Code contributions via Pull Requests
- Documentation improvements
- Testing on different distros and configurations

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for guidelines.

---

## Requirements

- Linux (any major distro)
- Python 3.12+
- Node.js 18+ (for Tauri UI)
- Rust toolchain (for Tauri)
- Ollama with a local model (or API key for cloud models)
- Thunderbird (optional, for calendar/contacts integration)

---

## Links

- [Technical Roadmap](docs/tech-roadmap.md) - Full implementation plan
- [Security Design](docs/security-design.md) - How Talking Rock protects your system
- [CAIRN Architecture](docs/cairn_architecture.md) - Attention minder design
- [The Play Documentation](docs/the-play.md) - Knowledge system details

---

## License

MIT

---

*Talking Rock: AI that works for you, not rents from you.*
