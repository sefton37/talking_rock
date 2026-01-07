# ReOS Extended Reasoning and Planning System

The reasoning system provides intelligent planning for complex Linux operations while keeping simple requests fast and natural.

## Overview

ReOS uses an **LLM-first approach** to understand your requests. Instead of rigid pattern matching, it uses the LLM to:

1. **Parse your intent**: Is this a question (query) or a request to change something (action)?
2. **Match against your system**: What containers, services, or packages are you referring to?
3. **Generate actionable plans**: Create step-by-step execution plans with rollback capability

This means natural language like "stop the nextcloud containers" works without needing to know exact container names.

## How It Works

### 1. LLM Intent Parsing

Every request goes through the LLM to understand what you want:

| Intent Type | Examples | Behavior |
|-------------|----------|----------|
| **Query** | "what containers are running?", "show memory" | Answer directly, no approval |
| **Action** | "stop the nginx service", "install htop" | Create plan, require approval |
| **Combined** | "is nextcloud running? if so stop it" | Prioritize action, create plan |

The LLM has access to your **system context** - it knows your actual container names, running services, and installed packages. So "stop the redis container" matches against `nextcloud-redis` on your system.

### 2. Task Planning

For complex requests, ReOS creates a step-by-step plan:

```
You: speed up my boot time

ReOS: Let me check what's slowing it down first...

Found three bottlenecks:
1. NetworkManager waits 90s for network (you're on wifi, don't need this)
2. snapd taking 12s (you're not using snaps)
3. Old bluetooth service running (you don't have bluetooth)

I can disable these safely. Should take about 30 seconds and won't
affect anything you use. Want me to go ahead?
```

### 3. Safe Execution

During execution:
- Each step is verified before moving to the next
- Config files are backed up before modification
- Rollback commands are recorded for each change
- If something fails, previous changes can be undone

### 4. Natural Conversation

The system speaks naturally, not robotically:

**Bad (robotic):**
```
ANALYZING REQUEST...
COMPLEXITY LEVEL: HIGH
GENERATING EXECUTION PLAN...
STEP 1 OF 7: INITIATING...
```

**Good (natural):**
```
Okay, speeding up your boot. Let me check what's slowing it down first...
```

## Configuration

Create `~/.config/reos/settings.toml`:

```toml
[reasoning]
enabled = true           # Enable planning system
auto_assess = true       # Automatically classify requests
always_confirm = false   # Ask before ANY system changes
explain_steps = true     # Show what each step does

[safety]
require_approval_for_permanent = true  # Confirm destructive ops
auto_backup_configs = true             # Backup before modifying
verify_each_step = true                # Check each step succeeded
rollback_on_failure = true             # Auto-undo on failure

[conversation]
verbosity = "normal"     # "minimal", "normal", or "detailed"
show_commands = true     # Show actual commands being run
```

## Usage

### Triggering Planning Manually

Even for simple requests, you can force planning:

```
You: plan: install docker
ReOS: Here's what I'll do to install Docker:
      1. Update package cache
      2. Install prerequisites
      3. Add Docker repository
      ...
```

### Checking Rollback History

```
You: what can you undo?
ReOS: Recent actions I can undo:
      1. Started nginx service (2 minutes ago)
      2. Installed vim package (5 minutes ago)
      Say 'undo' to revert the most recent action.
```

### Undoing Changes

```
You: undo
ReOS: Done! Undid: Started nginx service
      (ran: sudo systemctl stop nginx)
```

### Changing Verbosity

```
You: be more detailed
ReOS: Got it, I'll explain more about what I'm doing.

You: be brief
ReOS: Okay, keeping it short.
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      ReasoningEngine                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    LLMPlanner (Primary)                     │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐   │ │
│  │  │ Intent      │──│ Target      │──│ Plan             │   │ │
│  │  │ Parser      │  │ Matcher     │  │ Generator        │   │ │
│  │  └─────────────┘  └─────────────┘  └──────────────────┘   │ │
│  │        │                │                   │               │ │
│  │        │    System Context (containers, services, pkgs)    │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│            ┌─────────────────┴─────────────────┐                │
│            ▼                                   ▼                │
│     ┌─────────────┐                    ┌─────────────────┐     │
│     │   Queries   │                    │ TaskPlanner     │     │
│     │ (no plan)   │                    │ + AdaptiveExec  │     │
│     └─────────────┘                    └────────┬────────┘     │
│                                                 │               │
│                                      ┌──────────┴─────────┐    │
│                                      │  ErrorClassifier   │    │
│                                      │  AdaptiveReplanner │    │
│                                      │  ExecutionLearner  │    │
│                                      └────────────────────┘    │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                     SafetyManager                           │ │
│  │      (backups, rollback stack, risk assessment)             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| **LLMPlanner** | Primary intent parsing and plan generation using LLM |
| **Intent Parser** | Distinguishes queries from actions using LLM |
| **Target Matcher** | Resolves natural language to actual system resources |
| **TaskPlanner** | Breaks requests into steps with dependencies |
| **AdaptiveExecutor** | Runs steps with automatic error recovery |
| **ErrorClassifier** | Diagnoses failures (missing deps, permissions, etc.) |
| **AdaptiveReplanner** | Dynamically revises plans on failure |
| **ExecutionLearner** | Learns what works on this specific system |
| **SafetyManager** | Risk analysis, backups, rollback capability |

## Examples

### Query Request (No Plan Needed)

```
User: "what containers are running"
ReOS: [Intent: query, resource: containers]
      [Executes: docker ps]
      "You have 4 containers running:
       - nextcloud-app (Up 2 hours)
       - nextcloud-redis (Up 2 hours)
       - portainer (Up 2 hours)
       - n8n (Up 2 hours)"
```

### Action Request (Plan Generated)

```
User: "stop the nextcloud containers"
ReOS: [Intent: action=stop, resource: containers]
      [Matched targets: nextcloud-app, nextcloud-redis]

      "This will stop 2 containers:
       1. Stop nextcloud-app
       2. Stop nextcloud-redis

       Proceed? [y/n]"

User: "y"
ReOS: [Executing plan...]
      ✓ Stopped nextcloud-app
      ✓ Stopped nextcloud-redis
      "Done! Both containers stopped."
```

### Combined Request (Action Takes Priority)

```
User: "is nextcloud running? if so remove it"
ReOS: [Intent: action=remove, resource: containers, condition: if_running]
      [System lookup: nextcloud-app (running), nextcloud-redis (running)]

      "Nextcloud is running (2 containers). Here's the removal plan:
       1. Stop nextcloud-app
       2. Remove nextcloud-app
       3. Stop nextcloud-redis
       4. Remove nextcloud-redis

       This cannot be undone. Proceed? [y/n]"
```

### Risky Request (Approval Required)

```
User: "upgrade to the latest kernel"
ReOS: [Complexity: risky]
      "Kernel upgrade to 6.8.0. Here's what'll happen:

       1. Download ~200MB
       2. Install new kernel alongside current one (5.15.0)
       3. Update GRUB bootloader
       4. Reboot required

       Your current kernel stays installed as backup.
       If anything goes wrong, you can boot back to 5.15.0.

       Takes about 10 minutes. Ready?"

User: "yes"
ReOS: [Executes with progress updates]
      "All done! ✓
       New kernel installed. Reboot when you're ready.
       (I've backed up your boot config just in case)"
```

## Safety Guarantees

1. **Never execute risky operations without approval** - Destructive commands are always shown first
2. **Backups before modifications** - Config files are backed up automatically
3. **Rollback capability** - Most operations can be undone with a single command
4. **Transparent execution** - You always see what's being run
5. **Graceful failure** - If something breaks, changes are rolled back

## Adaptive Execution

When things go wrong during execution, ReOS doesn't just fail - it tries to fix the problem automatically.

### Error Classification

When a step fails, ReOS classifies the error into one of these categories:

| Category | Examples | Automatic Recovery |
|----------|----------|-------------------|
| **Missing Dependency** | "command not found", "package not installed" | Install the missing package |
| **Permission Denied** | "Permission denied", "must be root" | Retry with sudo |
| **Transient** | "Connection timed out", "Network unreachable" | Wait and retry |
| **Resource Busy** | "Device busy", "lock file exists" | Wait and retry |
| **Already Exists** | "File exists", "already installed" | Often fine, continue |
| **Not Found** | "No such file or directory" | Ask for help |
| **Conflict** | "Dependency conflict", "version mismatch" | Ask for help |

### Automatic Recovery Example

```
You: install and configure nginx

ReOS: [Starts executing plan...]

      Step 1: Installing nginx...
      ✗ Error: Unable to locate package nginx

      → Diagnosed: Missing dependency (apt cache outdated)
      → Trying fix: Updating package cache first...
      ✓ apt update completed

      → Retrying: Installing nginx...
      ✓ nginx installed

      Step 2: Enabling nginx service...
      ✓ Done

      Completed with 1 recovery action.
```

### Learning From Experience

ReOS remembers what works on your specific system:

- **Successful patterns** - Steps that worked are more likely to be used again
- **Failed patterns** - Steps that consistently fail get flagged
- **System quirks** - Platform-specific behaviors are recorded

This data is stored locally at `~/.config/reos/knowledge.db`.

```
You: why did you update apt first?

ReOS: I learned that on this system, apt install often fails
      without a recent cache update. I've seen this 3 times before,
      so now I do it proactively.
```

### Recovery Limits

For safety, automatic recovery is limited:
- Maximum 3 recovery attempts per execution
- Maximum 2 fix attempts per error type
- User intervention required for critical or unclassifiable errors

## Quality Commitment Framework

ReOS implements a Quality Commitment Framework to ensure every decision and action meets engineering excellence standards.

### Engineering Quality Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                  QUALITY COMMITMENT LAYERS                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Layer 1: REASONING TRANSPARENCY                                 │
│  ├─ Every decision has a chain-of-thought audit trail          │
│  ├─ Alternatives considered are logged                          │
│  └─ Justification for chosen approach is recorded               │
│                                                                   │
│  Layer 2: ENGINEERING STANDARDS                                  │
│  ├─ Idempotent operations preferred                             │
│  ├─ Explicit over implicit (no hidden state changes)           │
│  ├─ Fail-fast patterns (don't silently ignore errors)          │
│  └─ Commands checked for anti-patterns                          │
│                                                                   │
│  Layer 3: QUALITY GATES                                          │
│  ├─ Pre-flight: Is this the right approach?                    │
│  ├─ Mid-flight: Is execution proceeding correctly?             │
│  └─ Post-flight: Did we achieve the goal?                       │
│                                                                   │
│  Layer 4: MAINTAINABILITY SCORING                                │
│  ├─ Documentation/comments assessed                             │
│  ├─ Reversibility considered                                    │
│  ├─ Hardcoded values flagged                                    │
│  └─ Clarity of intent evaluated                                 │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### What Gets Checked

| Category | Good Patterns | Anti-Patterns |
|----------|--------------|---------------|
| **Idempotency** | `--force`, `--exist-ok`, `IF NOT EXISTS` | - |
| **Explicit** | `--yes`, `-y`, `--no-interaction` | Implicit state changes |
| **Error Handling** | Fail-fast, explicit errors | `\|\| true`, `2>/dev/null` |
| **Efficiency** | Direct file access | `cat file \| grep` (useless cat) |
| **Maintainability** | Comments, documentation | Hardcoded IPs, home paths |

### Quality Gates in Action

**Pre-flight checks** (before execution):
- Is the goal clearly stated?
- Does a plan exist?
- Is the scope reasonable (≤25 steps)?
- Is system context available?
- Are there conflicting operations?

**Mid-flight checks** (during execution):
- Did each step succeed?
- Are there warnings to note?
- Should we pause for review?

**Post-flight checks** (after execution):
- Did all steps complete?
- Were there critical errors?
- Was the goal achieved?

### Reasoning Audit Trail

Every significant decision creates an audit trail:

```
=== REASONING CHAIN: plan_creation ===
Goal: Stop all nextcloud containers
Context: User has 4 running containers

Step 1: Parse intent
  Rationale: Need to understand action and targets
  Alternatives: Ask for clarification, execute directly
  Why chosen: Request is unambiguous

Step 2: Match resources
  Rationale: Find containers matching "nextcloud"
  Confidence: 100%

Conclusion: Plan created with 2 stop operations
Quality Score: 85%
```

### Quality Assessment Example

```
You: stop the nextcloud containers

ReOS: [Quality Assessment]
      Plan Score: 0.9 (Excellent)
      ✓ Concise plan with focused steps
      ✓ Uses idempotent patterns
      ✓ Includes verification steps

      Plan:
        1. Stop nextcloud-app
        2. Stop nextcloud-redis

      Proceed? [y/n]
```

### Configuration

The quality framework uses the same config file (`~/.config/reos/settings.toml`):

```toml
[reasoning]
explain_steps = true     # Show reasoning in responses

[safety]
verify_each_step = true  # Run mid-flight quality gates
```

## Layer Placement Verification

ReOS automatically detects and enforces architectural layer boundaries to prevent logic from being placed in the wrong part of the codebase.

### The Problem

When adding new functionality, it's easy to place code in a convenient location rather than the architecturally correct one. For example:
- Adding business logic to an RPC handler (should be in agent/service)
- Adding request parsing to a storage layer (should be in RPC layer)
- Adding orchestration logic to an executor (should be in agent layer)

### How Layer Detection Works

ReOS extracts layer responsibilities from two sources:

**1. Module Docstrings** (source: "docstring")
```python
"""UI RPC server for the ReOS desktop app.

This is intentionally *not* MCP; it's a UI-facing RPC layer.

Design goals:
- Local-only (stdio; no network listener).
- Metadata-first by default.
"""
```

ReOS parses these docstrings to understand:
- What layer type this file belongs to (rpc, agent, executor, storage, service)
- What it's responsible for
- What it should NOT do (explicit "not" statements)

**2. Path Pattern Inference** (source: "inferred")
If no docstring exists, ReOS infers layer type from file paths:
- `*rpc*`, `*server*`, `*handler*` → rpc layer
- `*agent*` → agent layer
- `*executor*`, `*runner*` → executor layer
- `*db*`, `*storage*` → storage layer
- `*service*` → service layer

### Layer Responsibilities

| Layer | Does | Does NOT |
|-------|------|----------|
| **RPC** | Parse requests, route to handlers, format responses | Business logic, decision making |
| **Agent** | Orchestrate requests, make routing decisions, manage state | Low-level execution, request parsing |
| **Executor** | Execute planned operations, report progress | Planning, user interaction |
| **Storage** | Persist/retrieve data, manage connections | Business logic, request handling |
| **Service** | Implement business logic, coordinate domain operations | Request parsing, response formatting |

### Contract Verification

When Code Mode generates acceptance criteria, it can include `LAYER_APPROPRIATE` criteria:

```json
{
  "type": "layer_appropriate",
  "target_file": "src/reos/ui_rpc_server.py",
  "pattern": "def _check_repo_prerequisite",
  "layer_constraint": {
    "logic_type": "business_logic",
    "appropriate_layers": ["agent", "service"],
    "inappropriate_layers": ["rpc", "storage"],
    "reason": "Business logic should not be in RPC layer"
  }
}
```

If the code is placed in an inappropriate layer, the criterion fails with:
```
VIOLATION: business_logic placed in rpc layer (src/reos/ui_rpc_server.py).
Business logic should not be in RPC layer.
```

### Writing Good Docstrings

To help ReOS understand your architecture, add docstrings to key files:

```python
"""User authentication service.

This service handles:
- User login/logout
- Session management
- Token validation

This is intentionally NOT responsible for:
- HTTP request parsing (that's the RPC layer)
- Database queries (that's the auth repository)
"""
```

ReOS will extract both responsibilities and "not responsible for" statements to guide placement decisions.

## Circuit Breakers (Paperclip Problem Prevention)

To prevent runaway AI behavior, ReOS enforces hard limits that **cannot be overridden by the AI**:

### Hard Limits

| Limit | Default | Purpose |
|-------|---------|---------|
| **Max Operations** | 25 | Stop after 25 commands per plan |
| **Max Time** | 5 minutes | Hard timeout for any plan execution |
| **Max Privilege Escalations** | 3 | Limit sudo additions |
| **Max Injected Steps** | 5 | Limit plan growth during recovery |
| **Human Checkpoint** | After 2 recoveries | Force human review |
| **Max Learned Patterns** | 1000 | Cap learning database size |

### Scope Drift Detection

ReOS blocks "fixes" that drift too far from the original request:

```
You: install nginx

ReOS: [During recovery, attempts to run rm -rf /var/log]
      ⛔ BLOCKED: Scope drift detected - Recursive deletion outside /tmp
      [Execution paused for human review]
```

Blocked patterns include:
- `rm -rf /` (outside /tmp)
- `chmod -R 777`
- `curl | bash` (unless requested)
- `fdisk`, `parted` (partition tools)
- Firewall disabling
- Credential modification

### What Happens When Limits Are Hit

When any limit is reached, execution **immediately stops** and returns control to you:

```
You: fix everything on my system

ReOS: [After 25 operations]
      ⚠️ Execution paused: Maximum operations reached (25/25)

      Completed: 24 steps
      Pending: 8 steps remaining
      Time elapsed: 2m 34s

      Continue? (This resets the operation counter)
```

### Why These Limits Exist

These limits prevent the AI from:
1. **Executing indefinitely** - No infinite loops
2. **Escalating privileges unbounded** - Can't keep adding sudo
3. **Growing plans without limit** - Can't inject infinite "fix" steps
4. **Consuming unlimited resources** - Memory and time are capped
5. **Drifting from the request** - Must stay related to what you asked

The limits are enforced in code and **cannot be modified by the AI during execution**. Only you can change them in config.

## Fallback Behavior

The LLM planner is the primary intent parser, but ReOS gracefully falls back when needed:

### Fallback Chain

```
User Request
     │
     ▼
┌────────────────────┐
│   LLM Planner      │──── Success? ────► Use LLM plan
└────────────────────┘
     │ Fail/Empty
     ▼
┌────────────────────┐
│ Template Matching  │──── Match? ────► Use template plan
└────────────────────┘
     │ No match
     ▼
┌────────────────────┐
│  Regex Intent      │──── Parsed? ────► Generate steps
│  Parsing           │
└────────────────────┘
     │ No match
     ▼
┌────────────────────┐
│ Return empty plan  │──── Normal agent handles request
└────────────────────┘
```

### When Fallback Occurs

| Scenario | Behavior |
|----------|----------|
| LLM returns empty/no steps | Falls back to templates, then regex |
| LLM unavailable (no callback) | Uses templates and regex directly |
| LLM times out or errors | Treated as empty response, falls back |
| Query intent detected | Returns empty plan, normal agent answers |

### Transparency

Fallback is logged but doesn't surface to users unless debug logging is enabled:
- `DEBUG: LLM planner returned no steps, falling back`
- `DEBUG: Using template-based plan`
- `DEBUG: Using regex fallback plan`

This ensures a seamless experience - users get an answer either way, whether from the LLM planner or fallback mechanisms.

## Limitations

- Planning uses heuristics and may misclassify edge cases
- Rollback is not always possible (e.g., deleted files without backup)
- Complex multi-system operations may need manual verification
- Learning system stores local data only (no cloud sync)

## Development

### Running Tests

```bash
PYTHONPATH=src uv run pytest tests/test_reasoning.py -v
```

### Adding New Task Templates

Templates for common operations are in `planner.py`:

```python
TASK_TEMPLATES = {
    "my_operation": {
        "pattern": r"do something with (\w+)",
        "steps": [
            {
                "id": "step1",
                "title": "First step",
                "step_type": StepType.COMMAND,
                "action": {"command": "echo {captured_group}"},
            },
        ],
    },
}
```

### Customizing Conversation Style

Subclass `ConversationManager` to change formatting:

```python
class MyConversationManager(ConversationManager):
    def format_plan_presentation(self, plan):
        # Custom formatting
        return my_custom_format(plan)
```
