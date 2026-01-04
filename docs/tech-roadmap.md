# ReOS Technical Roadmap - Natural Language Linux

## Scope and Intent

ReOS is a **local-first conversational interface for Linux systems**.

**Guiding Star:** Make using Linux as easy as having a conversation.

### What This Means

- **Natural Language First**: Users speak intent ("install docker"), ReOS translates to safe commands
- **Transparent Execution**: Every command is previewed, explained, and user-approved
- **Deep System Understanding**: ReOS knows YOUR system (distro, packages, services, containers)
- **Safety-First**: Circuit breakers, undo suggestions, preview mode for destructive operations
- **Capability Transfer**: Users learn Linux through repeated pattern exposure, not dependency

**Not a magic wand.** Not a black box. A **Rosetta Stone** for the terminal.

---

## Core Philosophy

From the [ReOS Charter](../.github/ReOS_charter.md):

> ReOS exists to protect, reflect, and return human attention by making Linux transparent.

Applied to terminal usage:
- **Attention is labor**: Time spent Googling flags is attention stolen from real work
- **Transparency over magic**: Show the command, explain the reasoning, let users learn
- **Safety without surveillance**: Deep system knowledge without privacy invasion
- **No paperclips**: Hard-coded limits prevent runaway AI execution

---

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────────────────────┐
│                   Tauri Desktop App                      │
│  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │ System Panel │  │ Chat Window │  │  Inspector    │  │
│  │ (Live State) │  │(Conversation)│  │(Reasoning)    │  │
│  └──────────────┘  └─────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────┘
                         │ JSON-RPC (stdio)
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  Python Reasoning Kernel                 │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Ollama LLM  │  │ Linux Tools  │  │ Extended       │ │
│  │ (Local)     │  │ (System API) │  │ Reasoning      │ │
│  └─────────────┘  └──────────────┘  └────────────────┘ │
│  ┌──────────────────────────────────────────────────┐   │
│  │ SQLite: System snapshots + Conversation history  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  Your Linux System                       │
│    systemd │ apt/dnf │ docker │ processes │ files │ ... │
└─────────────────────────────────────────────────────────┘
```

### Key Components

**1. Linux Tools Layer ([linux_tools.py](../src/reos/linux_tools.py))**
- System monitoring (CPU, RAM, disk, network, load)
- Process management (list, filter, kill)
- Service control (systemd start/stop/restart/status)
- Package management (detect distro, search, install, remove)
- Container operations (docker/podman list, manage)
- File operations (find, search, read logs)
- Shell execution with safety guardrails

**2. System State Indexer ([system_index.py](../src/reos/system_index.py))**
- Daily snapshots of system state
- Hardware: CPU cores, RAM, disk, network interfaces
- OS: distro, kernel, boot parameters
- Packages: ALL installed packages (not just "key" ones)
- Services: ALL systemd units (running, failed, disabled)
- Containers: images, running containers, volumes
- Network: interfaces, routes, listening ports
- Provides RAG context: "Answer based on THIS system, not generic advice"

**3. Extended Reasoning System ([reasoning/](../src/reos/reasoning/))**
- **Complexity Assessment**: Classify requests (Simple/Complex/Diagnostic/Risky)
- **Planning**: Break multi-step requests into executable steps
- **Execution**: Run steps with monitoring, rollback on failure
- **Adaptive Recovery**: Retry/fix errors, learn from patterns
- **Circuit Breakers**: Hard limits (25 ops, 5 min, 3 sudo, scope lock)
- **Conversation Flow**: Natural back-and-forth troubleshooting

**4. UI Layer (Tauri + TypeScript)**
- **System Panel**: Live view of system state (CPU, RAM, services, containers)
- **Chat Window**: Natural language conversation interface
- **Inspector Pane**: Click any response → see reasoning trail (prompt, tools, alternatives)
- **Command Preview**: Show exact commands before execution, with approve/reject

**5. Storage (SQLite)**
- System snapshots (daily, for RAG context)
- Conversation history (for context continuity)
- Events/audit log (all actions, reversible)
- User preferences (learning mode, auto-approve patterns)

---

## Assumptions

- **OS**: Linux (any major distro: Ubuntu, Fedora, Arch, Debian, openSUSE)
- **Language**: Python 3.12+ (kernel), TypeScript/Rust (Tauri UI)
- **LLM**: Ollama (local, user-choice of model: llama3.2, qwen, mistral, etc.)
- **Deployment**: Desktop app (Tauri), optional CLI mode
- **Privacy**: Local-first, no cloud calls, SQLite storage only

---

## Use Case Flows

### Example 1: System Monitoring
```
User: "What's using the most memory?"

ReOS: [Runs: ps aux --sort=-%mem | head -10]

      Top memory users:
      1. chrome (2.3 GB)
      2. docker (1.8 GB)
      3. code (890 MB)

      💡 Command: ps aux --sort=-%mem | head -10
         ps aux       = list all processes
         --sort=-%mem = sort by memory descending
         head -10     = show top 10
```

### Example 2: Multi-Step Installation
```
User: "Install Docker and set it up for my user"

ReOS: I'll install Docker and add you to the docker group.
      This requires sudo.

      Plan:
      1. sudo apt update
      2. sudo apt install docker.io
      3. sudo systemctl enable --now docker
      4. sudo usermod -aG docker kellogg

      After step 4, you'll need to log out and back in.

      Proceed? [y/N]

User: y

ReOS: [Executes steps 1-4 with live progress]
      ✓ Updated package lists
      ✓ Installed docker.io (version 24.0.5)
      ✓ Enabled and started docker service
      ✓ Added kellogg to docker group

      Done! Log out and back in to use docker without sudo.
```

### Example 3: Troubleshooting
```
User: "Nginx isn't working"

ReOS: Checking nginx status...
      [Runs: systemctl status nginx]

      Service failed. Error: "bind() to 0.0.0.0:80 failed (98: Address already in use)"

      Something else is using port 80. Checking...
      [Runs: sudo lsof -i :80]

      Found: Apache2 is running on port 80.

      Options:
      1. Stop Apache: sudo systemctl stop apache2
      2. Run nginx on different port (edit /etc/nginx/sites-enabled/default)

      Which approach?

User: 1

ReOS: [Runs: sudo systemctl stop apache2]
      ✓ Stopped apache2

      [Runs: sudo systemctl start nginx]
      ✓ Started nginx

      Nginx is now running on port 80.
```

### Example 4: Disk Cleanup
```
User: "My disk is full, help me clean up"

ReOS: Analyzing disk usage...
      [Runs: df -h && du -sh /var/log /home/kellogg/Downloads /var/lib/docker/overlay2]

      Disk usage:
      / : 92% full (47GB used of 50GB)

      Large directories:
      - /var/log: 8.2 GB (old logs)
      - /home/kellogg/Downloads: 12.3 GB
      - /var/lib/docker: 6.7 GB (old container layers)

      Safe cleanup options:
      1. Rotate old logs: journalctl --vacuum-size=2G
      2. Clean Docker: docker system prune -a
      3. Review Downloads folder (I'll list largest files)

      Which would you like to do?
```

---

## Development Milestones

### M0: Foundation (✓ Completed)
- [x] Python kernel with SQLite storage
- [x] Ollama integration with tool use
- [x] Linux tools library (system, services, packages, containers)
- [x] Basic MCP server (JSON-RPC stdio)
- [x] Safety infrastructure (command blocking, risk assessment)

### M1: Desktop App Shell (✓ Complete)
- [x] Tauri app with 3-pane layout
- [x] Chat interface via RPC (ui_rpc_server.py)
- [x] System status display (basic)
- [x] Extended reasoning system (planning, execution, recovery)
- [x] Circuit breakers (SafetyLimits enforcement)
- [ ] Inspector pane (reasoning trail visualization) **← Future**
- [ ] Command preview UI (approve/reject) **← Future (CLI works)**

### M2: Conversational Flows (✓ Complete - Backend)
**Goal: Complete end-to-end user journeys for common tasks**

#### M2.1: Command Preview & Approval (✓ Backend Complete)
- [x] Backend: Plan generation with step preview
- [x] Backend: Approval workflow (approve/reject via chat)
- [x] Backend: Live output streaming during execution
- [x] CLI: Shell integration for natural language input
- [ ] UI: Command preview component **← Future**

#### M2.2: System State Dashboard (Partial)
- [x] Backend: System state collection (SteadyStateCollector)
- [x] Backend: RAG context for LLM (steady state in every prompt)
- [ ] UI: Live system metrics in nav panel **← Future**
- [ ] UI: Service/container indicators **← Future**

#### M2.3: Multi-Step Workflows (✓ Complete)
- [x] LLM-first intent parsing (hybrid approach)
- [x] Deterministic step generation from intent
- [x] Plan execution with step-by-step progress
- [x] Rollback on failure (automatic)
- [ ] UI: Progress visualization **← Future**

#### M2.4: Conversational Troubleshooting (✓ Backend Complete)
- [x] Conversation persistence across sessions
- [x] Intent detection (approval, rejection, choices)
- [x] Reference resolution (pattern matching for "it", "that")
- [x] Error explanation in natural language
- [ ] Deep semantic reference resolution **← Future enhancement**

### M3: Intelligence & Learning (Later)
**Goal: Make ReOS smarter about YOUR system and patterns**

#### M3.1: Personal Runbooks
- [ ] Remember past solutions ("Last time this happened, you ran X")
- [ ] Detect recurring issues ("This nginx error has happened 3 times")
- [ ] Suggest automation ("You keep doing this—want a script?")

#### M3.2: Proactive Monitoring
- [ ] Background watcher for service failures
- [ ] Alert user: "nginx just failed—want to investigate?"
- [ ] Disk space warnings before critical
- [ ] Unusual resource usage detection

#### M3.3: Pattern Learning
- [ ] Auto-approve safe repeated commands (user configurable)
- [ ] Suggest shortcuts ("You often do X then Y—combine?")
- [ ] Learn from corrections ("You always change X to Y—remember that?")

### M4: Advanced Capabilities (Future)
**Goal: Handle complex scenarios and edge cases**

#### M4.1: Configuration Management
- [ ] Edit config files conversationally ("Change nginx port to 8080")
- [ ] Diff preview before writing
- [ ] Backup original, rollback support
- [ ] Syntax validation

#### M4.2: Network Troubleshooting
- [ ] "Why can't I reach X?" → route tracing, DNS checks, firewall rules
- [ ] Port scanning and service detection
- [ ] SSL certificate checking
- [ ] Connection debugging

#### M4.3: User/Group Management
- [ ] Create users, set permissions conversationally
- [ ] Group membership management
- [ ] SSH key setup and distribution

#### M4.4: Cron/Timer Management
- [ ] "Run this script every day at 3am"
- [ ] List scheduled tasks in natural language
- [ ] Edit/delete timers conversationally

### M5: Ecosystem Integration (Speculative)
**Goal: Expand beyond terminal to broader system usage**

#### M5.1: Git Integration (Optional)
- [ ] "Show me what changed in my repo"
- [ ] Alignment checks (changes vs roadmap/charter)
- [ ] Smart commit grouping suggestions

#### M5.2: Development Workflows (Optional)
- [ ] "Set up a Python dev environment for this project"
- [ ] Dependency installation across languages
- [ ] Test runner integration

#### M5.3: Attention Tracking (Optional)
- [ ] Detect "stuck" patterns (same error for 30 minutes)
- [ ] Offer help: "You've been fighting this—want me to take a look?"
- [ ] Revolution/Evolution classification (learning new tool vs deepening mastery)

---

## Technical Priorities (Next 4 Weeks)

### Week 1: Command Preview & Execution Flow
**Goal: Complete the chat → preview → execute → result loop**

1. **Backend: Execution streaming**
   - Modify [executor.py](../src/reos/reasoning/executor.py) to stream step results
   - Add `stream_step_output` to ui_rpc_server
   - Real-time command output to UI

2. **Frontend: Command preview component**
   - Display: command, explanation, risk level, undo
   - Buttons: [Approve] [Reject] [Edit Command] [Explain More]
   - Live output display during execution

3. **Backend: Post-execution summary**
   - Detect what changed (files modified, services started, packages installed)
   - Generate undo commands where possible
   - Store in conversation history for "how do I undo X?"

### Week 2: System State Dashboard
**Goal: Make system status visible and actionable**

1. **Backend: Live state API**
   - Add RPC method: `get_system_state()` → CPU, RAM, disk, services, containers
   - Implement polling (every 5s in background)
   - Detect changes (service status flips, new containers, disk threshold)

2. **Frontend: Nav panel overhaul**
   - System metrics widgets (CPU/RAM/Disk with visual indicators)
   - Service list with status icons, click to see logs/restart
   - Container list with quick actions
   - Click any item → opens contextual chat ("Tell me about this service")

3. **Integration: State-aware chat**
   - System state automatically included in LLM context
   - "Nginx failed 2 minutes ago" → ReOS can reference this unprompted

### Week 3: Multi-Step Workflows
**Goal: Handle "install docker" style requests end-to-end**

1. **Backend: Plan preview**
   - Reasoning system generates plan
   - Returns to UI BEFORE execution
   - User approval required → then execute

2. **Frontend: Progress UI**
   - Show plan steps (✓ complete, ⏳ in progress, ⋯ pending)
   - Live updates as steps execute
   - Rollback button if something fails

3. **Backend: Robust error recovery**
   - Improve [adaptive.py](../src/reos/reasoning/adaptive.py) error classification
   - Smart retries (transient network errors)
   - User choice on failure: [Retry] [Skip Step] [Abort] [Ask ReOS to Fix]

### Week 4: Inspector Pane & Transparency
**Goal: Users can see EXACTLY how ReOS reasoned**

1. **Backend: Reasoning trail capture**
   - Every response includes: prompt sent, model used, tools called, alternatives considered
   - Store in conversation history DB

2. **Frontend: Inspector pane**
   - Click any ReOS message → right pane shows full reasoning
   - Expandable sections: Prompt | Tools Called | Confidence | Alternatives
   - "Why did you choose apt over snap?" → visible in trail

3. **Educational tooltips**
   - Hover over command → quick explanation
   - Click "Learn More" → full man page excerpt or tutorial link

---

## Guardrails from Charter

**Privacy & Safety:**
- No cloud calls (except optional Ollama remote models if user configures)
- No keystroke capture or content reading (only metadata)
- All data in local SQLite (~/.local/share/reos/reos.db)
- User approval required for:
  - Any sudo command
  - Destructive operations (rm, format, etc.)
  - Package changes (install/remove)
  - Service changes (start/stop)

**Circuit Breakers (Paperclip Prevention):**
- Max 25 commands per task (then require human approval)
- Max 5 minutes execution time (hard stop)
- Max 3 sudo escalations per task
- Scope lock: AI cannot drift from original request
- Human checkpoint after 2 automated recoveries

**Language & Tone:**
- Reflective, not prescriptive ("Here's what I found" vs "You should")
- Educational, not condescending (show commands, explain patterns)
- No moral language ("good/bad job", productivity scores)
- Compassionate errors ("This failed because..." not "You did wrong")

---

## Development Workflow

**Setup:**
```bash
# Install dependencies
pip install -e .
ollama pull llama3.2

# Run desktop app (dev mode)
./reos

# Run tests
pytest tests/ -v

# Type checking
mypy src/reos

# Linting
ruff check src/
```

**Testing Strategy:**
- Unit tests: Core logic (linux_tools, reasoning, safety)
- Integration tests: Full flows (chat → plan → execute → result)
- Local-only: No cloud calls, temp resources, isolated DB
- See [testing-strategy.md](testing-strategy.md) for details

**Branch Strategy:**
- `main`: Stable, ready to demo
- `dev`: Integration branch
- Feature branches: `feature/command-preview`, `feature/state-dashboard`, etc.

---

## Success Metrics (Internal)

**We'll know ReOS is working when:**

1. **Usability:** Non-technical users can install software without Googling
2. **Transparency:** Users trust ReOS because they can see its reasoning
3. **Learning:** Users start typing raw commands instead of asking ReOS (capability transfer)
4. **Safety:** Zero incidents of destructive commands running without approval
5. **Performance:** <2s response time for simple queries, <10s for complex plans

**Anti-metrics (things we explicitly DON'T measure):**
- User dependency (we WANT them to graduate away)
- Engagement time (less is better if they accomplished their goal)
- Automation rate (some things should require user thought)

---

## Open Questions

1. **Auto-approval for read-only commands?**
   - Should `ps aux`, `systemctl status`, `df -h` auto-run without preview?
   - Or always show what's happening (transparency over convenience)?

2. **Command history integration?**
   - Should ReOS learn from bash history (detect patterns)?
   - Privacy concern: requires reading past commands

3. **Error telemetry (opt-in)?**
   - Anonymous error pattern sharing to improve reasoning?
   - Requires opt-in, privacy policy, anonymization

4. **Multi-user systems?**
   - How does ReOS handle shared servers?
   - Should it know about other users' processes/services?

5. **Remote systems?**
   - SSH integration: "Install docker on my server at X"?
   - Security concerns, credential management

---

## Long-Term Vision Alignment

**Phase 1 (Now): Natural Language Linux**
- Conversational terminal control
- Transparent command execution
- System state awareness
- Safety-first multi-step workflows

**Phase 2 (Later): Attention Integration**
- Detect "stuck" patterns (same error loop for 30 min)
- Offer proactive help ("Want me to investigate?")
- Track revolution/evolution in tool learning

**Phase 3 (Future): Knowledge Accumulation**
- Personal runbooks ("How you solved this before")
- Cross-user pattern learning (opt-in, anonymized)
- Predictive troubleshooting ("This usually means X")

**Phase 4 (Speculative): Life Integration**
- Broader attention tracking (email, browser, calendar)
- Context-aware suggestions ("You're context-switching a lot today")
- Life graph: projects, people, time, attention flows

**But the terminal remains the foundation.**
Everything expands from "make Linux conversational."

---

## Closing

ReOS is not trying to be:
- A DevOps automation platform (Ansible, Terraform)
- A monitoring dashboard (Grafana, Prometheus)
- A package manager GUI (GNOME Software, Discover)
- A terminal emulator (it can be, but that's not the core)

ReOS is:
- **A translation layer** between human intent and Linux commands
- **A learning tool** that shows you the pattern until you internalize it
- **A safety net** that prevents "oops I deleted /usr"
- **A companion** that makes the terminal feel less hostile

If we succeed:
- Fewer people bounce off Linux due to "too hard"
- More people gain genuine Linux capability (not just GUI dependence)
- Attention shifts from fighting syntax to building things

**Make using Linux as easy as having a conversation.**
That's the mission.
Everything else is in service of that.
