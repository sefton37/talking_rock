# RIVA Architecture (Code Mode)

## Overview

**RIVA** (Recursive Intention-Verification Architecture) is Talking Rock's coding agent. It autonomously understands, plans, and executes code changes through a contract-based, test-first approach.

RIVA's core kernel principle: **"If you can't verify it, decompose it."**

This document describes RIVA's architecture, components, and execution flow.

## Execution Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RIVA Execution Flow                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   User Prompt                                                           │
│        ↓                                                                │
│   ┌─────────────┐                                                       │
│   │   Router    │ ← Classifies request type                             │
│   └─────────────┘                                                       │
│        ↓                                                                │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    Intent Discovery                              │   │
│   │  • Analyze prompt (LLM or heuristic)                             │   │
│   │  • Extract Play context (Act goals, recent work)                 │   │
│   │  • Scan codebase (language, patterns, related files)             │   │
│   │  • Synthesize unified intent                                     │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│        ↓                                                                │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    Contract Building                             │   │
│   │  • Generate acceptance criteria (testable conditions)            │   │
│   │  • Decompose into atomic steps                                   │   │
│   │  • Optional: Generate test specification (test-first)            │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│        ↓                                                                │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      Execution Loop                              │   │
│   │  for each iteration:                                             │   │
│   │    1. Execute plan steps (via LLM tool calls)                    │   │
│   │    2. Verify contract criteria                                   │   │
│   │    3. If gaps found → create gap contract → retry                │   │
│   │    4. If complete → SUCCESS                                      │   │
│   │    5. If max iterations → FAILED                                 │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│        ↓                                                                │
│   Result (SUCCESS/FAILED/STOPPED)                                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. IntentDiscoverer (`intent.py`)

**Purpose**: Understand what the user wants from multiple sources.

**Sources**:
- **PromptIntent**: Extracted action, target, constraints from user's words
- **PlayIntent**: Act goals, artifact type, recent work from The Play
- **CodebaseIntent**: Language, architecture, conventions, related files

**Key Methods**:
- `discover(prompt, act, knowledge_context)` → `DiscoveredIntent`
- `_analyze_prompt_with_llm()` → LLM-based intent extraction
- `_analyze_codebase()` → grep-based file/pattern discovery
- `_synthesize_intent()` → Combine all sources

**Logging Points**:
- `discovery_start` - Initial context
- `llm_call_start/llm_response` - Full LLM request/response
- `intent_extracted` - Parsed prompt intent
- `intent_synthesized` - Final unified intent
- `discovery_complete` - Summary stats

### 2. ContractBuilder (`contract.py`)

**Purpose**: Define explicit, testable success criteria.

**Contract Structure**:
```python
Contract:
  - id: str
  - intent_summary: str
  - acceptance_criteria: list[AcceptanceCriterion]
  - steps: list[ContractStep]
  - status: ContractStatus
```

**Criterion Types**:
- `FILE_EXISTS` - File must exist
- `FILE_CONTAINS` - File must contain pattern
- `TESTS_PASS` - pytest must pass
- `FUNCTION_EXISTS` - Function must be defined
- `GENERATED_TEST_PASSES` - Generated test must pass (test-first)
- `LAYER_APPROPRIATE` - Logic in correct architectural layer

**Key Methods**:
- `build_from_intent(intent)` → `Contract`
- `build_gap_contract(original, intent)` → Contract for remaining work
- `_generate_criteria_with_llm()` → LLM-based criteria generation
- `_decompose_with_llm()` → LLM-based step decomposition

**Logging Points**:
- `build_start` - Contract building begins
- `llm_call_start/llm_response` - LLM for criteria/steps
- `criteria_generated` - Generated criteria
- `steps_decomposed` - Generated steps
- `build_complete` - Final contract

### 3. CodeExecutor (`executor.py`)

**Purpose**: Execute the plan and verify results.

**Execution Loop**:
```python
while iteration < max_iterations:
    1. Execute step (via LLM tool calls)
    2. Check contract fulfillment
    3. If gaps:
       - Build gap contract
       - Continue iteration
    4. If complete: return SUCCESS
    5. If failed: return FAILED
```

**Phases**:
- `DISCOVERING_INTENT` - Running IntentDiscoverer
- `BUILDING_CONTRACT` - Running ContractBuilder
- `EXECUTING_PLAN` - Running plan steps
- `VERIFYING` - Checking criteria
- `COMPLETED` / `FAILED` / `STOPPED`

### 4. SessionLogger (`session_logger.py`)

**Purpose**: Comprehensive debugging logs for Code Mode sessions.

**Log Location**: `.reos-data/code_mode_sessions/`

**Files per Session**:
- `{session_id}.log` - Human-readable log
- `{session_id}.json` - Structured JSON data

**Log Entry Structure**:
```python
LogEntry:
  - timestamp: str
  - level: str (DEBUG/INFO/WARN/ERROR)
  - module: str (intent/contract/executor/riva)
  - action: str (llm_call_start/decision/step_complete/etc)
  - message: str
  - data: dict (full context)
```

**RPC Endpoints**:
- `code/sessions/list` - List recent sessions
- `code/sessions/get` - Get parsed session data
- `code/sessions/raw` - Get raw log file

## RIVA: Recursive Intention-Verification Architecture

### Core Principle

> **If you can't verify it, decompose it.**

RIVA provides a single recursive rule for code execution. Instead of prescribing levels (project, component, function, line), levels emerge from recursive application of this constraint.

### State Machine

```
                              ┌─────────────────────────────────────────────────────┐
                              │              INTENTION STATE MACHINE                  │
                              └─────────────────────────────────────────────────────┘

                                            ┌──────────┐
                                            │ PENDING  │
                                            └────┬─────┘
                                                 │ work() called
                                                 ▼
                                            ┌──────────┐
                              ┌─────────────│  ACTIVE  │─────────────┐
                              │             └────┬─────┘             │
                              │                  │                   │
                   can_verify_directly?          │           can_verify_directly?
                        = false                  │                = true
                              │                  │                   │
                              │                  │                   ▼
                              │                  │           ┌─────────────────┐
                              │                  │           │   ACTION CYCLE  │
                              │                  │           │  ┌───────────┐  │
                              │                  │           │  │  thought  │  │
                              │                  │           │  │     ↓     │  │
                              │                  │           │  │  action   │  │
                              │                  │           │  │     ↓     │  │
                              │                  │           │  │  result   │  │
                              │                  │           │  │     ↓     │  │
                              │                  │           │  │ judgment  │  │
                              │                  │           │  └─────┬─────┘  │
                              │                  │           └────────┼────────┘
                              │                  │                    │
                              │                  │      ┌─────────────┼─────────────┐
                              │                  │      │             │             │
                              │                  │   SUCCESS       FAILURE      PARTIAL/
                              │                  │      │             │          UNCLEAR
                              │                  │      │             │             │
                              │                  │      ▼             │             │
                              │                  │ ┌──────────┐       │             │
                              │                  │ │ VERIFIED │       │      should_decompose?
                              │                  │ └──────────┘       │             │
                              │                  │                    │    ┌────────┴────────┐
                              │                  │                    │   false            true
                              │                  │                    │    │                 │
                              │                  │                    │    ▼                 │
                              │                  │                    │  retry              │
                              │                  │                    │  cycle ──────────►──┘
                              │                  │                    │                     │
                              ▼                  │                    │                     │
                      ┌───────────────┐          │                    │                     │
                      │  DECOMPOSE    │◄─────────┴────────────────────┴─────────────────────┘
                      │               │
                      │ Split into    │
                      │ 2-5 children  │
                      └───────┬───────┘
                              │
                              ▼
                      ┌───────────────┐
                      │ WORK CHILDREN │ ← Recursive call for each child
                      │  (depth + 1)  │
                      └───────┬───────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
        all children    any child       max depth
          VERIFIED        FAILED          exceeded
              │               │               │
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ VERIFIED │   │  FAILED  │   │  FAILED  │
        └──────────┘   └──────────┘   └──────────┘
```

### Cycle State Machine

Each action cycle within an intention follows this state flow:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CYCLE FLOW                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐       │
│   │ THOUGHT  │ ──►  │  ACTION  │ ──►  │  RESULT  │ ──►  │ JUDGMENT │       │
│   │          │      │          │      │          │      │          │       │
│   │ "What am │      │ COMMAND  │      │ stdout   │      │ SUCCESS  │       │
│   │  I about │      │ EDIT     │      │ stderr   │      │ FAILURE  │       │
│   │  to try" │      │ CREATE   │      │ exit code│      │ PARTIAL  │       │
│   │          │      │ DELETE   │      │ error    │      │ UNCLEAR  │       │
│   │          │      │ QUERY    │      │          │      │          │       │
│   └──────────┘      └──────────┘      └──────────┘      └────┬─────┘       │
│                                                              │             │
│                    if not SUCCESS  ┌────────────────────────┘             │
│                                    ▼                                       │
│                             ┌──────────────┐                               │
│                             │  REFLECTION  │                               │
│                             │              │                               │
│                             │ "Why did it  │                               │
│                             │  fail? What  │                               │
│                             │  to try next"│                               │
│                             └──────────────┘                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Judgment Decision Tree

```
                                ┌─────────────────────┐
                                │    Cycle Result     │
                                └──────────┬──────────┘
                                           │
                      ┌────────────────────┼────────────────────┐
                      │                    │                    │
                      ▼                    ▼                    ▼
               ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
               │   SUCCESS   │      │   FAILURE   │      │   UNCLEAR   │
               │  indicators │      │  indicators │      │             │
               └─────────────┘      └─────────────┘      └─────────────┘

Success indicators:              Failure indicators:           Unclear:
• exit_code == 0                 • exit_code != 0              • No clear success
• "success" in output            • "error" in output             or failure
• "created" in output            • "failed" in output            indicators
• "done" in output               • "exception" in output       • Ambiguous result
• file exists after CREATE       • traceback detected
• pattern found after EDIT       • permission denied
```

### Decomposition Triggers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SHOULD DECOMPOSE?                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────┐                                                       │
│   │ Check Triggers  │                                                       │
│   └────────┬────────┘                                                       │
│            │                                                                │
│   ┌────────┼────────┬────────────────┬────────────────┐                    │
│   │        │        │                │                │                    │
│   ▼        ▼        ▼                ▼                ▼                    │
│ cycles  repeated  repeated      reflection        can't verify            │
│ >= max  failures  unclear        suggests         directly                │
│   │     >= 2      >= 2           decompose            │                    │
│   │        │        │                │                │                    │
│   └────────┴────────┴────────────────┴────────────────┘                    │
│                            │                                                │
│                            ▼                                                │
│                    ┌───────────────┐                                        │
│                    │   DECOMPOSE   │                                        │
│                    │               │                                        │
│                    │ LLM generates │                                        │
│                    │  2-5 children │                                        │
│                    │     with:     │                                        │
│                    │ • what        │                                        │
│                    │ • acceptance  │                                        │
│                    └───────────────┘                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Safety Limits

| Limit | Default | Purpose |
|-------|---------|---------|
| `max_depth` | 10 | Prevent infinite recursion |
| `max_cycles_per_intention` | 5 | Prevent infinite retry loops |
| `max_iterations` | 10 | Overall execution limit |
| `wall_clock_timeout` | 300s | Real-time safety |

These limits are configured in `src/reos/config.py` and can be tuned via environment variables.

### Data Structures (`intention.py`)

```python
Intention:
  - id: str
  - what: str              # Natural language goal
  - acceptance: str        # Verifiable criteria
  - parent_id: str | None
  - children: list[str]    # Child intention IDs
  - status: IntentionStatus (PENDING/ACTIVE/VERIFIED/FAILED)
  - trace: list[Cycle]     # All attempts at this level

Cycle:
  - thought: str           # What we're about to try
  - action: Action         # The concrete action
  - result: str            # What happened
  - judgment: Judgment     # SUCCESS/FAILURE/PARTIAL/UNCLEAR
  - reflection: str | None # Analysis of failure

Action:
  - type: ActionType       # COMMAND/EDIT/CREATE/DELETE/QUERY
  - content: str           # The actual command/code
  - target: str | None     # File path if applicable
```

### The `work()` Algorithm

```python
def work(intention, ctx, depth=0):
    """The recursive navigation algorithm."""

    # Guard against infinite recursion
    if depth > ctx.max_depth:
        intention.status = FAILED
        return

    intention.status = ACTIVE

    # 1. Can we verify this intention directly?
    if can_verify_directly(intention, ctx):
        # 2. Try action cycles
        while intention.status == ACTIVE:
            thought, action = determine_next_action(intention, ctx)
            result = execute_action(action, ctx)
            cycle = Cycle(thought, action, result, ...)

            cycle.judgment = checkpoint.judge_action(intention, cycle)

            if cycle.judgment == SUCCESS:
                intention.status = VERIFIED
            else:
                cycle.reflection = reflect(intention, cycle, ctx)
                if should_decompose(intention, cycle, ctx):
                    break  # Exit to decomposition

            intention.add_cycle(cycle)

    # 3. If not verifiable, decompose
    if intention.status != VERIFIED:
        children = decompose(intention, ctx)

        for child in children:
            intention.add_child(child)

        # 4. Work each child recursively
        for child in intention._child_intentions:
            work(child, ctx, depth + 1)

            if child.status == FAILED:
                intention.status = FAILED
                return

        # 5. Integrate and verify at parent level
        if not integrate(intention, ctx):
            intention.status = FAILED
```

### Decision Functions

**`can_verify_directly(intention, ctx)`**:
- Check for compound structure ("and", "then", "also")
- Check description length (>200 chars → decompose)
- Check acceptance testability (must have verifiable indicators)

**`should_decompose(intention, cycle, ctx)`**:
- Max cycles reached
- Repeated failures (≥2)
- Repeated unclear outcomes (≥2)
- Reflection suggests decomposition

**`decompose(intention, ctx)`**:
- Use LLM to generate 2-5 sub-intentions
- Each child should be more verifiable than parent
- Human/auto checkpoint approves decomposition

### Human Checkpoints (`HumanCheckpoint` Protocol)

```python
class HumanCheckpoint(Protocol):
    def judge_action(self, intention, cycle) -> Judgment
    def approve_decomposition(self, intention, children) -> bool
    def verify_integration(self, intention) -> bool
    def review_reflection(self, intention, cycle) -> bool
```

**`AutoCheckpoint`** provides automatic implementation using:
- Result content heuristics (error/success keywords)
- Exit code detection
- Child verification status

**`UICheckpoint`** provides human-in-the-loop implementation:
```python
def ask_judgment(intention, cycle, auto_judgment):
    # Show UI, get user input
    return user_selected_judgment or auto_judgment

checkpoint = UICheckpoint(
    sandbox=sandbox,
    on_judge_action=ask_judgment,
    on_approve_decomposition=lambda i, c: show_decomposition_ui(i, c),
    on_verify_integration=lambda i: show_integration_ui(i),
    on_review_reflection=lambda i, c: show_reflection_ui(i, c),
)
```

Callbacks receive context and return decisions. When a callback is not provided, UICheckpoint falls back to AutoCheckpoint behavior.

### Session Capture

```python
Session:
  - id: str
  - timestamp: str
  - root: Intention       # Full intention tree
  - metadata: dict        # Duration, cycles, depth, outcome
```

Sessions can be saved/loaded for:
- Training data collection
- Post-mortem debugging
- Session replay

## Logging Strategy

### Log Levels

- **DEBUG**: Cycle start, reflection, action execution details
- **INFO**: Phase changes, LLM calls, major decisions
- **WARN**: Fallbacks (LLM failed, using heuristics)
- **ERROR**: Exceptions, failures, integration errors

### What Gets Logged

1. **Every LLM Call**:
   - System prompt
   - User prompt
   - Raw response
   - Parsed result

2. **Every Decision Point**:
   - can_verify_directly decision
   - should_decompose decision
   - Decomposition approval

3. **Every Action**:
   - Action type and content
   - Execution result
   - Judgment assigned

4. **Every Phase Transition**:
   - Phase changes
   - Iteration boundaries
   - Completion/failure

### Accessing Logs

```python
from reos.code_mode import list_sessions, get_session_log

# List recent sessions
sessions = list_sessions(limit=10)

# Get specific session
log = get_session_log(session_id)
```

Or via RPC:
```json
{"method": "code/sessions/list", "params": {"limit": 20}}
{"method": "code/sessions/get", "params": {"session_id": "..."}}
```

## Testing Strategy

### Unit Tests (`tests/test_riva.py`)

55 tests covering:

**Data Structures**:
- Action serialization/deserialization
- Cycle creation and roundtrip
- Intention tree operations (add_child, get_depth, get_total_cycles)
- Session save/load

**Decision Functions**:
- `can_verify_directly` heuristics
- `should_decompose` conditions
- Heuristic decomposition/action generation

**AutoCheckpoint**:
- Judgment from result content
- Exit code detection
- Decomposition approval
- Integration verification

**Execute Action**:
- Command execution
- File operations
- Query handling
- Error handling

**Work Algorithm**:
- Simple verifiable intentions
- Max depth protection
- Callback invocation

**Logging**:
- Log calls on errors
- Log structure validation

### Integration Tests

- `tests/test_code_executor.py` - Full execution loop
- `tests/test_code_intent.py` - Intent discovery
- `tests/test_code_contract.py` - Contract building

## File Structure

```
src/reos/code_mode/
├── __init__.py          # Exports all public types
├── contract.py          # ContractBuilder, Contract, AcceptanceCriterion
├── diff_utils.py        # Diff generation utilities
├── executor.py          # CodeExecutor (main loop)
├── explorer.py          # Step exploration/alternatives
├── intent.py            # IntentDiscoverer, DiscoveredIntent
├── intention.py         # RIVA: Intention, Cycle, work()
├── perspectives.py      # Phase-specific personas
├── planner.py           # CodePlanner (legacy)
├── project_memory.py    # Project decisions/patterns storage
├── router.py            # Request classification
├── sandbox.py           # File/command sandbox
├── session_logger.py    # Comprehensive session logging
├── streaming.py         # UI state updates
└── test_generator.py    # Test-first code generation
```

## Future Work

1. **RIVA Integration with Executor**: Wire RIVA's `work()` as an alternative execution mode
2. **Human Checkpoint UI**: Surface checkpoint decisions to user via observer/RPC
3. **Training Data Export**: Export sessions in format suitable for fine-tuning
4. **Continuous Improvement**: Use session data to improve LLM prompts
