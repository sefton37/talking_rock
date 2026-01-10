# Talking Rock Technical Roadmap

## The Vision

**Build the best AI assistant in the world. Then give it away.**

Talking Rock is a local-first AI assistant with three specialized agents:

| Agent | Purpose | Kernel Principle |
|-------|---------|------------------|
| **CAIRN** | Attention minder & default helper | "If you can't verify coherence, decompose the demand" |
| **ReOS** | System agent for Linux control | "Native until foreign. Foreign until confirmed." |
| **RIVA** | Coding agent for development | "If you can't verify it, decompose it" |

Talking Rock exists to prove that the best AI tools don't require:
- Monthly subscriptions to trillion-dollar companies
- Sending your code to someone else's servers
- Trusting black boxes you can't inspect or modify
- Accepting whatever "engagement-optimized" features they decide to ship

Talking Rock is:
- **Open source**: See how it works, fix bugs, add features
- **Local-first**: Everything runs on your hardware
- **Private**: Your data never leaves your machine
- **Yours**: No subscription, no lock-in, no rent

---

## What We're Building

### Three Agents, One Philosophy

**1. CAIRN - Attention Minder**
Your default conversational partner. Manages The Play (your life knowledge base), routes to other agents, filters distractions through your identity.

**2. ReOS - System Agent**
Natural language Linux control. Make the terminal accessible to everyone.

**3. RIVA - Coding Agent**
A full AI coding partner that rivals Cursor, Copilot, and Devin—but running locally, privately, and freely.

All three share the same principles:
- Transparency over magic
- User sovereignty over engagement
- Capability transfer over dependency
- Safety without surveillance

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Talking Rock Architecture                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                     User Interface Layer                            │     │
│  │                                                                     │     │
│  │   Tauri Desktop App              Shell CLI           HTTP API       │     │
│  │   ├── Chat Window                ├── reos "..."      ├── JSON-RPC   │     │
│  │   ├── System Panel               └── Interactive     └── MCP Server │     │
│  │   ├── Diff Preview                                                  │     │
│  │   ├── The Play Navigator                                            │     │
│  │   └── Inspector Pane                                                │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                      │                                       │
│                                      ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                     Routing & Context Layer                         │     │
│  │                                                                     │     │
│  │   ┌─────────────────┐    ┌─────────────────┐    ┌───────────────┐  │     │
│  │   │  Request Router │    │   The Play KB   │    │ System State  │  │     │
│  │   │                 │    │                 │    │   Indexer     │  │     │
│  │   │ Linux vs Code?  │    │ Acts/Scenes/    │    │               │  │     │
│  │   │ Query vs Action?│    │ Beats + Notes   │    │ Snapshots     │  │     │
│  │   └────────┬────────┘    └────────┬────────┘    └───────┬───────┘  │     │
│  │            │                      │                     │          │     │
│  └────────────┼──────────────────────┼─────────────────────┼──────────┘     │
│               │                      │                     │                 │
│               ▼                      ▼                     ▼                 │
│  ┌────────────────────────┐  ┌────────────────────────────────────────┐     │
│  │   ReOS (System Agent)  │  │         RIVA (Code Agent)              │     │
│  │                        │  │                                         │     │
│  │  ┌──────────────────┐  │  │  ┌─────────────────────────────────┐   │     │
│  │  │   Linux Tools    │  │  │  │        Execution Loop           │   │     │
│  │  │                  │  │  │  │                                 │   │     │
│  │  │ • System info    │  │  │  │  Intent ──► Contract ──► Build  │   │     │
│  │  │ • Services       │  │  │  │    │                      │     │   │     │
│  │  │ • Packages       │  │  │  │    │     ┌────────────────┤     │   │     │
│  │  │ • Containers     │  │  │  │    │     │                ▼     │   │     │
│  │  │ • Files          │  │  │  │    │     │    Verify ◄── Debug  │   │     │
│  │  │ • Shell          │  │  │  │    │     │      │               │   │     │
│  │  └──────────────────┘  │  │  │    │     │      ▼               │   │     │
│  │                        │  │  │    │     │  Integrate           │   │     │
│  │  ┌──────────────────┐  │  │  │    │     │      │               │   │     │
│  │  │ Reasoning Engine │  │  │  │    ◄─────┴──────┴── Gap         │   │     │
│  │  │                  │  │  │  │                                 │   │     │
│  │  │ • Plan           │  │  │  └─────────────────────────────────┘   │     │
│  │  │ • Execute        │  │  │                                         │     │
│  │  │ • Recover        │  │  │  ┌─────────────────────────────────┐   │     │
│  │  │ • Learn          │  │  │  │         Code Sandbox            │   │     │
│  │  └──────────────────┘  │  │  │                                 │   │     │
│  │                        │  │  │  • read/write/edit files        │   │     │
│  └────────────────────────┘  │  │  • grep/find                    │   │     │
│                              │  │  • run commands                 │   │     │
│                              │  │  • git operations               │   │     │
│                              │  └─────────────────────────────────┘   │     │
│                              │                                         │     │
│                              │  ┌─────────────────────────────────┐   │     │
│                              │  │       Perspectives              │   │     │
│                              │  │                                 │   │     │
│                              │  │  Analyst → Architect → Engineer │   │     │
│                              │  │     ↑                      ↓    │   │     │
│                              │  │  Gap ← Integrator ← Critic ←    │   │     │
│                              │  │                      ↓          │   │     │
│                              │  │                   Debugger      │   │     │
│                              │  └─────────────────────────────────┘   │     │
│                              └─────────────────────────────────────────┘     │
│                                              │                               │
│                                              ▼                               │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                     Safety & Verification Layer                     │     │
│  │                                                                     │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────┐  │     │
│  │  │   Command    │  │   Circuit    │  │    Diff      │  │ Audit  │  │     │
│  │  │   Blocking   │  │   Breakers   │  │   Preview    │  │  Log   │  │     │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └────────┘  │     │
│  │                                                                     │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                              │                               │
│                                              ▼                               │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                     Model Backend (Pluggable)                       │     │
│  │                                                                     │     │
│  │   Ollama (Local)    Anthropic API    OpenAI API    Local llama.cpp │     │
│  │   └── llama3.2      └── Claude       └── GPT-4     └── Direct GGUF │     │
│  │   └── qwen          └── Opus                                        │     │
│  │   └── mistral                                                       │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                              │                               │
│                                              ▼                               │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                         Storage Layer                               │     │
│  │                                                                     │     │
│  │   SQLite Database              File System                          │     │
│  │   ├── Conversations            ├── The Play (~/.local/share/reos/) │     │
│  │   ├── System Snapshots         ├── File Backups (.reos_backups/)   │     │
│  │   ├── Project Memory           └── Checkpoints                      │     │
│  │   └── Audit Log                                                     │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Current State (What's Built)

### ReOS - System Agent (Complete)
- [x] Natural language system control via Ollama
- [x] Deep system understanding (containers, services, packages, processes)
- [x] System state indexer with daily snapshots
- [x] Multi-step plan generation with approval workflow
- [x] Safety layer (command blocking, risk assessment, rate limiting)
- [x] Circuit breakers (25 ops, 5 min, 3 sudo)
- [x] Conversation persistence across sessions
- [x] Extended reasoning system with adaptive recovery

### RIVA - Coding Agent (Sprint 3 Complete)
- [x] Repository assignment to Acts in The Play
- [x] Automatic code vs sysadmin request routing
- [x] Multi-source intent discovery (prompt + Play + codebase)
- [x] Contract-based development with testable success criteria
- [x] Perspective shifting (7 personas for different phases)
- [x] Self-debugging loop (analyze failures, apply fixes, retry up to 3x)
- [x] Execution-based verification (run tests, trust output)
- [x] Gap analysis and iterative completion

### The Play (Complete)
- [x] Hierarchical knowledge structure (Acts → Scenes → Beats)
- [x] Markdown notebooks at each level
- [x] File attachments
- [x] Context selection (active Acts provide context)
- [x] Repository assignment to Acts

---

## The Roadmap: From Good to Best-in-Class

### Phase 1: Foundation (Current)
**Status: Complete**

What we have:
- Working Linux mode with safety
- Working Code mode with self-debugging
- The Play for context

What makes it work:
- Contract-based development prevents hallucination
- Perspective shifting prevents single-viewpoint blindspots
- Execution-based verification uses test output as ground truth
- Self-debugging loop handles failures automatically

---

### Phase 2: Codebase Understanding
**Goal: Know the codebase like a senior engineer**

The gap: Right now Code Mode greps for patterns. Commercial tools have deep semantic understanding—dependency graphs, symbol tables, semantic search.

#### 2.1 Repository Map

```python
# src/reos/code_mode/repo_map.py

class RepositoryMap:
    """Semantic understanding of the codebase."""

    def __init__(self, sandbox: CodeSandbox):
        self.sandbox = sandbox
        self._dependency_graph: nx.DiGraph = None
        self._symbol_table: dict[str, Symbol] = {}
        self._embeddings: dict[str, np.ndarray] = {}

    def build(self) -> None:
        """Build the repository map."""
        self._build_dependency_graph()
        self._build_symbol_table()
        self._build_embeddings()

    def get_context_for_file(self, path: str) -> str:
        """Get relevant context for working on a file."""
        # What imports this file?
        # What does this file import?
        # What functions are called?
        # What's the test file?

    def semantic_search(self, query: str, k: int = 10) -> list[CodeChunk]:
        """Find code relevant to a natural language query."""
        # Embed the query
        # Find nearest neighbors in code embeddings
        # Return ranked results

    def find_implementations(self, interface: str) -> list[Location]:
        """Find all implementations of an interface/protocol."""

    def find_callers(self, function: str) -> list[Location]:
        """Find all places that call a function."""

    def find_usages(self, symbol: str) -> list[Location]:
        """Find all usages of a symbol."""
```

**Why it matters:**
- Context is everything. With a repo map, the LLM sees relevant code, not random files
- Semantic search finds code by meaning: "where do we handle authentication" finds the auth code even if it's not named "auth"
- Dependency tracking prevents breaking changes

**Implementation:**
1. Parse ASTs for Python, TypeScript, Rust, Go
2. Build call graph and import graph
3. Embed code chunks using local embedding model (nomic-embed, all-MiniLM)
4. Store in SQLite with vector similarity extension

---

#### 2.2 LSP Integration

```python
# src/reos/code_mode/lsp_bridge.py

class LSPBridge:
    """Bridge to Language Server Protocol for real-time feedback."""

    def __init__(self, language: str, root_path: Path):
        self.language = language
        self.root_path = root_path
        self._server: subprocess.Popen = None

    async def start(self) -> None:
        """Start the language server."""
        # pyright for Python
        # typescript-language-server for TS
        # rust-analyzer for Rust

    async def get_diagnostics(self, file: str) -> list[Diagnostic]:
        """Get current errors/warnings for a file."""

    async def get_definition(self, file: str, line: int, col: int) -> Location:
        """Go to definition."""

    async def find_references(self, file: str, line: int, col: int) -> list[Location]:
        """Find all references to symbol at position."""

    async def get_hover(self, file: str, line: int, col: int) -> str:
        """Get hover documentation."""
```

**Why it matters:**
- Real-time type errors without running tests
- "What does this function return?" answered instantly
- Rename refactoring that doesn't break things

---

### Phase 3: User Experience
**Goal: Make it feel magical while staying transparent**

#### 3.1 Diff Preview UI

```typescript
// apps/reos-tauri/src/components/DiffPreview.tsx

interface DiffPreviewProps {
  changes: FileChange[];
  onApprove: (changes: FileChange[]) => void;
  onReject: () => void;
  onApproveFile: (path: string) => void;
  onRejectFile: (path: string) => void;
}

// Show:
// - File-by-file changes
// - Hunk-by-hunk diffs
// - Accept/reject per file
// - Accept/reject per hunk
// - "Explain this change" button
```

**Why it matters:**
- Users MUST see what's changing before it happens
- This is the core of user sovereignty
- No surprises, no "what did it do?"

---

#### 3.2 Streaming Execution UI

```typescript
// apps/reos-tauri/src/components/ExecutionStream.tsx

interface ExecutionStreamProps {
  state: ExecutionState;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
}

// Show:
// - Current phase (Intent, Contract, Build, Verify, etc.)
// - Progress through steps
// - Live test output
// - Debug attempts
// - "Pause and let me look" button
```

**Why it matters:**
- Transparency builds trust
- Users can interrupt when they see something wrong
- Educational: watch how the AI works

---

#### 3.3 Inspector Pane

```typescript
// apps/reos-tauri/src/components/Inspector.tsx

interface InspectorProps {
  message: ChatMessage;
}

// Show:
// - What perspective was active
// - What context was provided
// - What tools were called
// - What alternatives were considered
// - Why this approach was chosen
// - Confidence level
```

**Why it matters:**
- "Why did you do that?" always has an answer
- Debugging AI decisions
- Learning from the AI's reasoning

---

### Phase 4: Intelligence & Memory
**Goal: Get smarter about YOUR projects over time**

#### 4.1 Long-term Project Memory

```python
# src/reos/code_mode/memory.py

@dataclass
class ProjectMemory:
    """Persistent memory for a project."""

    project_id: str

    # What we've learned
    decisions: list[Decision]          # "We use dataclasses, not TypedDict"
    patterns: list[Pattern]            # "Tests go in tests/, named test_*.py"
    corrections: list[Correction]      # "User changed X to Y, remember that"

    # What's happened
    sessions: list[SessionSummary]     # Past conversations
    changes: list[ChangeRecord]        # What was modified when

    def remember_decision(self, decision: str, rationale: str) -> None:
        """Store a decision for future reference."""

    def remember_correction(self, wrong: str, right: str, context: str) -> None:
        """Learn from user corrections."""

    def recall_relevant(self, context: str) -> list[Memory]:
        """Retrieve memories relevant to current context."""
```

**Why it matters:**
- "Last time you did X, you wanted Y"
- Learns your preferences without you having to repeat them
- Gets better the more you use it

---

#### 4.2 Test-First Contracts

```python
# Enhanced contract generation

class ContractBuilder:
    def build_from_intent(self, intent: DiscoveredIntent) -> Contract:
        # Generate actual test code, not just patterns
        criteria = []

        # Generate test code that defines success
        test_code = self._generate_test_code(intent)

        criteria.append(AcceptanceCriterion(
            type=CriterionType.TEST_CODE_PASSES,
            description=f"Generated tests pass",
            test_code=test_code,  # Actual Python/TS/etc test code
        ))

        return Contract(
            acceptance_criteria=criteria,
            test_file=self._write_test_file(test_code),
        )
```

**Why it matters:**
- TDD by default
- Tests ARE the specification
- No ambiguity about what "done" means

---

#### 4.3 Multi-path Exploration

```python
# src/reos/code_mode/explorer.py

class Explorer:
    """Try multiple approaches when unsure."""

    def explore(self, problem: str, n_paths: int = 3) -> list[Approach]:
        """Generate and evaluate multiple approaches."""

        approaches = []
        for i in range(n_paths):
            # Generate approach with different temperature/prompt
            approach = self._generate_approach(problem, i)

            # Evaluate: Does it compile? Do tests pass? How complex?
            score = self._evaluate_approach(approach)

            approaches.append((approach, score))

        return sorted(approaches, key=lambda x: x[1], reverse=True)
```

**Why it matters:**
- Hard problems have multiple solutions
- Try several, pick the best
- Don't get stuck on first idea

---

### Phase 5: Ecosystem
**Goal: Integrate with everything developers use**

#### 5.1 Pluggable Model Backend

```python
# src/reos/models/backend.py

class ModelBackend(Protocol):
    """Protocol for model backends."""

    def complete(self, messages: list[Message], **kwargs) -> str:
        """Generate completion."""

    def embed(self, text: str) -> list[float]:
        """Generate embedding."""

    def stream(self, messages: list[Message], **kwargs) -> Iterator[str]:
        """Stream completion."""

# Implementations
class OllamaBackend(ModelBackend): ...
class AnthropicBackend(ModelBackend): ...
class OpenAIBackend(ModelBackend): ...
class LlamaCppBackend(ModelBackend): ...  # Direct GGUF loading
```

**Why it matters:**
- User chooses their model
- Run fully local or use cloud when needed
- Future-proof: new models just plug in

---

#### 5.2 MCP Tool Integration

```python
# Already have MCP server, extend it

# Register code mode tools dynamically
def get_code_mode_tools(active_act: Act) -> list[Tool]:
    if not active_act.repo_path:
        return []

    return [
        Tool(name="code_read_file", ...),
        Tool(name="code_write_file", ...),
        Tool(name="code_run_tests", ...),
        Tool(name="code_semantic_search", ...),
        Tool(name="code_find_references", ...),
    ]
```

---

#### 5.3 Documentation Lookup

```python
# src/reos/code_mode/docs.py

class DocumentationLookup:
    """Fetch documentation for unknown APIs."""

    def lookup(self, symbol: str, language: str) -> Documentation | None:
        """Look up documentation for a symbol."""

        # Check local cache first
        cached = self._cache.get(symbol, language)
        if cached:
            return cached

        # Fetch from known documentation sources
        doc = self._fetch_from_source(symbol, language)

        if doc:
            self._cache.set(symbol, language, doc)

        return doc
```

**Why it matters:**
- Don't hallucinate APIs—look them up
- Local cache for speed
- Devin does this; we should too

---

## Implementation Priority

### Tier 1: High Impact, Build Next

| Feature | Why | Effort |
|---------|-----|--------|
| **Diff Preview UI** | Users MUST see before approve | Medium |
| **Repository Map** | 10x better context | High |
| **Test-First Contracts** | Verification done right | Medium |

### Tier 2: Competitive Parity

| Feature | Why | Effort |
|---------|-----|--------|
| **Long-term Memory** | Gets better over time | Medium |
| **LSP Integration** | Real-time feedback | High |
| **Streaming UI** | Transparency, trust | Medium |

### Tier 3: Differentiation

| Feature | Why | Effort |
|---------|-----|--------|
| **Multi-path Exploration** | Handles hard problems | High |
| **Documentation Lookup** | Prevent hallucination | Medium |
| **Pluggable Models** | User choice, future-proof | Medium |

---

## What Makes Talking Rock Different

### vs Cursor

| Aspect | Cursor | Talking Rock |
|--------|--------|------|
| Pricing | $20/month | Free |
| Privacy | Code goes to cloud | 100% local |
| Source | Proprietary | Open source |
| Codebase awareness | Excellent | Building (repo map) |
| Self-debugging | Partial | Full loop |
| Linux sysadmin | No | Yes |

### vs GitHub Copilot

| Aspect | Copilot | Talking Rock |
|--------|---------|------|
| Pricing | $10-39/month | Free |
| Privacy | Code processed by GitHub | 100% local |
| Source | Proprietary | Open source |
| Multi-file editing | Limited | Full |
| Test execution | No | Yes |
| Agentic behavior | No | Yes |

### vs Devin

| Aspect | Devin | Talking Rock |
|--------|-------|------|
| Pricing | $500/month | Free |
| Privacy | Cloud-based | 100% local |
| Source | Proprietary | Open source |
| Autonomy | High | Configurable |
| Browser automation | Yes | Planned |
| Long-term memory | Yes | Planned |

### The Talking Rock Advantage

What we can do that they can't:

1. **Fully Local**: Some users can't/won't send code to cloud. Period.
2. **Open Source**: Security audits, bug fixes, feature additions by community
3. **No Rent**: One install, free forever
4. **User Sovereignty**: Optimized for user, not engagement metrics
5. **Linux Integration**: Unique combination of sysadmin + coding
6. **Federated Improvement**: Learn from corrections without centralizing data

---

## Development Principles

### From the Charter

> Talking Rock exists to protect, reflect, and return human attention.

Applied to RIVA (Code Mode):
- **Protect**: Don't break things. Diff preview, backups, circuit breakers.
- **Reflect**: Show reasoning. Inspector pane, execution streaming.
- **Return**: Don't waste time. Get it right the first time with contracts.

### Anti-Patterns We Avoid

1. **Engagement optimization**: We WANT users to finish and leave
2. **Dependency creation**: We WANT users to learn and need us less
3. **Lock-in**: We WANT users to be able to leave (but never want to)
4. **Black boxes**: We WANT users to understand how it works

### Success Metrics

**We'll know we succeeded when:**
- Users trust Talking Rock enough to let it modify code
- Users learn patterns from watching the agents work
- Users choose Talking Rock over paid alternatives
- Users contribute improvements back

**Anti-metrics:**
- Session length (shorter is better if task is done)
- Retention (we want capability transfer, not dependency)
- "Engagement" (if they're done, they're done)

---

## Technical Decisions

### Why Python for the Kernel

- Ollama bindings are mature
- AST parsing for Python/TS is well-supported
- Same language as many target codebases
- Rapid iteration during development

### Why Tauri for the UI

- Native performance
- Rust backend for speed-critical paths
- Web frontend for rapid UI development
- Cross-platform (Linux focus, but Windows/Mac possible)

### Why SQLite for Storage

- Zero configuration
- Single file, easy backup
- Fast enough for our needs
- Vector extensions available (sqlite-vec)

### Why Ollama as Default

- Local-first aligns with our values
- User choice of models
- Active development
- Growing ecosystem

---

## Getting Involved

### For Contributors

1. **Read the Charter**: Understand the philosophy
2. **Pick an issue**: Start small, grow from there
3. **Follow the patterns**: Code style, testing, documentation
4. **Ask questions**: We're happy to help

### Priority Areas

- **Repository Map**: Need AST parsing expertise
- **LSP Integration**: Need language server experience
- **Diff Preview UI**: Need TypeScript/React skills
- **Documentation**: Always welcome

### Testing Strategy

- Unit tests for core logic
- Integration tests for full flows
- Local-only (no cloud calls)
- Temporary resources, isolated DB

---

## Timeline

**Q1 2025: Foundation**
- [x] Code Mode core (intent, contract, execution loop)
- [x] Self-debugging loop
- [x] Execution-based verification
- [ ] Diff preview UI (in progress)

**Q2 2025: Codebase Understanding**
- [ ] Repository map (dependency graph)
- [ ] Semantic search (embeddings)
- [ ] LSP integration (pyright, typescript)

**Q3 2025: Intelligence**
- [ ] Long-term project memory
- [ ] Test-first contracts (generate test code)
- [ ] Multi-path exploration

**Q4 2025: Polish**
- [ ] Streaming execution UI
- [ ] Inspector pane
- [ ] Documentation lookup
- [ ] Pluggable model backends

**2026: Ecosystem**
- [ ] Browser automation
- [ ] More language support
- [ ] Plugin system
- [ ] Community patterns library

---

## Closing

Talking Rock isn't trying to be:
- A startup looking for exit
- A VC-funded growth machine
- A data collection operation disguised as a product

Talking Rock is:
- A tool that respects its users
- A project that believes in open source
- A proof that the best things can be free

The trillion-dollar companies have more engineers, more compute, more data. But they also have shareholders to please, engagement to optimize, rent to collect.

We have none of that. We can optimize purely for making the best tool.

**Let's build it.**
