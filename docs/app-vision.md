# Talking Rock Desktop App Vision

## Purpose

The Talking Rock Tauri desktop app is the **home base** for your AI assistant. It provides the UI for three specialized agents:

| Agent | What It Does | UI Surface |
|-------|--------------|------------|
| **CAIRN** | Attention minder, life organizer (default) | Chat, The Play navigator |
| **ReOS** | System control, Linux administration | System panel, command preview |
| **RIVA** | Coding assistant, development help | Diff preview, execution stream |

**It's not just a terminal wrapper—it's where you interact with your local AI companion.**

---

## Core Pillars

### 1. Onboarding & Configuration
**Get Talking Rock to know you and your system**

- **First Run Experience**:
  - Check for Ollama installation
  - Guide user through `ollama pull llama3.2` (or model of choice)
  - Test connectivity and model response
  - Run initial system snapshot (packages, services, containers)
  - Set preferences (auto-approve safe commands, learning mode, etc.)

- **System Discovery**:
  - Automatically detect distro, package manager, installed software
  - Build initial RAG context from system state
  - Offer to set up shell integration (optional)

- **Settings Panel**:
  - Model selection (switch between llama3.2, qwen, mistral, etc.)
  - Safety preferences (circuit breaker limits, sudo prompts)
  - Privacy settings (what to snapshot, log retention)
  - Learning mode toggle (show/hide command breakdowns)

### 2. Conversational Interface
**Talk to CAIRN, who routes to the right agent**

- **Chat Window** (center pane):
  - Natural language input—CAIRN is your default conversational partner
  - CAIRN routes to ReOS for system questions, RIVA for code questions
  - Command preview boxes (approve/reject/explain) when ReOS proposes actions
  - Live output streaming during execution
  - Post-execution summaries (what changed, how to undo)
  - Learning tooltips (command breakdowns, pattern explanations)

- **Conversation Types**:
  - **Life/Attention (CAIRN)**: "What should I focus on today?", "Show me waiting items"
  - **System (ReOS)**: "What's using memory?", "Install docker"
  - **Code (RIVA)**: "Add login to my API", "Fix the test failures"

- **Context Awareness**:
  - System state automatically included (failed services, low disk, etc.)
  - The Play context (current Act, related projects)
  - Conversation history (refer to "it", "that service", "the error from before")

### 3. The Play (CAIRN's Domain)
**Your hierarchical knowledge system**

- **Structure**:
  - Acts → Scenes → Beats (life chapters → projects → tasks)
  - Markdown notebooks at each level
  - Repository assignment to Acts (for RIVA context)

- **CAIRN Features**:
  - Activity tracking (when you last touched things)
  - Kanban states (active, backlog, waiting, done)
  - Priority surfacing without guilt-tripping
  - Coherence kernel filtering (blocks distractions based on identity)

- **Navigation**:
  - Tree view of Acts/Scenes/Beats
  - Quick access to recent items
  - Contact knowledge graph (people ↔ projects)

### 4. System Panel (ReOS's Domain)
**Live view of your Linux system**

- **Nav Panel** (left side):
  - **Metrics**: CPU, RAM, disk usage (with visual indicators)
  - **Services**: List systemd units (green=running, red=failed, gray=inactive)
    - Click → see logs, quick restart/stop
  - **Containers**: Docker/Podman containers and images
    - Quick actions: stop, restart, view logs
  - **Quick Access**: Recent conversations, saved runbooks, failed services

- **Command Workflow**:
  - Preview before execution
  - Approval required for changes
  - Post-execution summary with undo options

### 5. Code Mode (RIVA's Domain)
**AI-assisted development**

- **Diff Preview**:
  - See exactly what RIVA will change before it happens
  - File-by-file, hunk-by-hunk review
  - Accept/reject per file or per hunk

- **Execution Streaming**:
  - Current phase (Intent, Contract, Build, Verify)
  - Progress through steps
  - Live test output
  - Debug attempts

- **Inspector Pane** (right side):
  - Click any response → see full reasoning trail
  - What perspective was active
  - What tools were called
  - Confidence level

### 6. Inspector Pane
**Transparency for all agents**

- Click any response to see:
  - Which agent handled it (CAIRN, ReOS, or RIVA)
  - What context was provided
  - What tools were called
  - What alternatives were considered
  - Why this approach was chosen
  - Confidence level

---

## UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Talking Rock                                Settings | Help     │
├──────────────┬──────────────────────────────┬───────────────────┤
│              │                              │                   │
│  Nav Panel   │      Chat / Main View        │  Inspector Pane   │
│              │                              │                   │
│ The Play     │  User: What should I focus   │  [Click response  │
│ ├─ Act 1     │        on today?             │   to see trail]   │
│ │  ├─ Scene  │                              │                   │
│ │  └─ Scene  │  CAIRN: Based on your Play,  │  Agent: CAIRN     │
│ └─ Act 2     │  I'd suggest focusing on...  │                   │
│              │                              │  Context: The Play │
│ System       │  User: Install docker        │                   │
│ ├─ CPU 23%   │                              │  Tools Called:    │
│ ├─ RAM 4.2GB │  ReOS: I'll install Docker   │  - play_surface   │
│ └─ Disk 67%  │  and add you to the group.   │                   │
│              │                              │                   │
│ Services     │  Plan:                       │  Confidence: 95%  │
│ ├─✓ docker   │  1. apt install docker.io    │                   │
│ ├─✗ nginx    │  2. systemctl enable docker  │                   │
│ └─○ apache2  │                              │                   │
│              │  Proceed? [Yes] [No]         │                   │
│ Containers   │                              │                   │
│ ├─ postgres  │                              │                   │
│ └─ redis     │                              │                   │
└──────────────┴──────────────────────────────┴───────────────────┘
```

---

## User Journeys

### Journey 1: First-Time Setup
1. User launches Talking Rock
2. Welcome screen: "Let's set up Talking Rock"
3. Check: Is Ollama installed? → If not, guide to install
4. Check: Models available? → Guide to `ollama pull llama3.2`
5. Test: Can we connect and get a response?
6. Scan: Initial system snapshot (takes 10s)
7. Done: "Talking Rock is ready. Start by telling CAIRN about yourself."

### Journey 2: Daily Planning (CAIRN)
1. User opens Talking Rock
2. CAIRN surfaces: "Good morning. Based on your Play, here's what needs attention..."
3. Shows prioritized items without guilt-tripping
4. User asks clarifying questions
5. CAIRN updates priorities based on user decisions

### Journey 3: System Issue (ReOS)
1. User notices system slowdown
2. Opens Talking Rock: "Why is my system slow?"
3. CAIRN routes to ReOS
4. ReOS checks system, finds nginx failed
5. Offers to fix, shows command preview
6. User approves, ReOS executes
7. System panel updates: nginx ✓ green

### Journey 4: Coding Task (RIVA)
1. User: "Add user authentication to my API"
2. CAIRN routes to RIVA
3. RIVA discovers intent, builds contract
4. Shows diff preview of proposed changes
5. User reviews, approves
6. RIVA executes, runs tests
7. Self-debugs if tests fail

### Journey 5: Learning
1. User: "How do I list running containers?"
2. CAIRN routes to ReOS
3. ReOS: Shows `docker ps` with breakdown
4. Explains each flag
5. User learns the pattern
6. Next time, types it themselves

---

## What Makes Talking Rock Different

### vs. Terminal Emulators
- Three specialized agents, not just command execution
- Understands **intent**, routes appropriately
- The Play for life organization
- Inspector pane for transparency

### vs. AI Chat Apps
- Knows **YOUR system** (not generic advice)
- Actions are **executable** (not just suggestions)
- Safety is **built-in** (circuit breakers, previews)
- Everything is **local** (no cloud, no privacy leak)

### vs. Productivity Apps
- **Non-coercive**: Surfaces options, never guilt-trips
- **Identity-aware**: Coherence kernel filters distractions
- **Agent architecture**: Specialized helpers, not generic features

---

## Design Principles

### 1. Calm Technology
- No urgent red alerts, no stress inducement
- Gentle notifications, user always in control
- Metrics inform, they don't judge

### 2. Progressive Disclosure
- Simple queries get simple answers
- Click for details (inspector pane)
- Learning mode is optional, not forced

### 3. Capability Transfer
- Show commands, explain patterns
- Celebrate when users "graduate"
- Success = user needs Talking Rock less over time

### 4. Local-First Always
- No cloud calls for core features
- User owns all data
- Works offline (except Ollama model download)

### 5. Transparent AI
- Every response shows reasoning trail
- No hidden decisions
- User can audit everything

---

## Success Metrics

**We'll know Talking Rock is working when:**

1. **First-time users** set up and complete a task in <10 minutes
2. **Learning happens**: Users type raw commands instead of asking
3. **Trust is built**: Users approve commands because they see reasoning
4. **Agent routing works**: Users naturally get routed to the right agent
5. **CAIRN helps**: Users report feeling less overwhelmed, not more

**What we DON'T measure:**
- Daily active usage (less is good if they learned!)
- Commands executed (manual > automated for learning)
- Time in app (efficiency is the goal)

---

## Closing Thoughts

Talking Rock is **not trying to replace your terminal or your brain**.

It's trying to make Linux **accessible**, life **organized**, and coding **assisted**—all through a local, private, transparent AI companion.

The three agents work together:
- **CAIRN** helps you decide what matters
- **ReOS** helps you control your system
- **RIVA** helps you write code

And over time, you **need them less** because you've internalized the patterns.

**That's not a bug. That's the whole point.**

*Talking Rock: AI that works for you, on your terms.*
