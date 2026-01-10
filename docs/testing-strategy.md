## Talking Rock Testing Strategy (Local-First)

### Goals

- Protect the **local-first** privacy contract.
- Keep tests deterministic and fast (prefer in-process + temp resources).
- Cover real seams: SQLite persistence, tool execution, agent policies, safety layers.
- Test each agent's kernel: CAIRN (coherence), ReOS (parse gate), RIVA (intention-verification).

### Principles

- **No cloud calls in tests**. Network boundaries (Ollama/httpx) are mocked.
- **No workspace state coupling**. Tests must not read/write `.reos-data/`.
- **Isolated resources**. Each test uses temp directories and isolated DB.

### Test Pyramid

1) **Unit tests** (fast)
   - Pure logic (parsing, heuristics, schema/serialization).
   - Allowed resources: `tmp_path`, in-memory DB.

2) **Integration tests** (local-only)
   - Real temp SQLite DBs (file-backed in `tmp_path`).
   - Tool execution in sandboxed temp directories.
   - Validate end-to-end seams: command safety, approval workflow, agent routing.

3) **Contract tests**
   - FastAPI endpoints using `TestClient` with isolated DB.
   - MCP JSON-RPC request/response mapping + sandboxing behavior.
   - RPC contract validation for UI kernel.

4) **Agent-specific tests**
   - CAIRN: Coherence kernel, anti-pattern rejection, priority surfacing.
   - ReOS: Parse gate, command safety, circuit breakers.
   - RIVA: Intent discovery, contract building, self-debugging loop.

5) **Safety tests**
   - Command blocking patterns.
   - Rate limiting.
   - Approval workflow (edited commands re-validated).
   - Circuit breaker enforcement.

### Fixtures to Standardize

- `isolated_db`: Creates temp SQLite for test duration.
- `temp_sandbox`: Creates temp directory for file operations.
- `mock_ollama`: Provides predictable LLM responses.

### What to Mock vs Use Real

- **Use real**: SQLite against temp files, file operations in temp dirs.
- **Mock**: `httpx` (Ollama), time when needed, UI externalities.

### Running Tests

```bash
# All tests
pytest

# Specific agent
pytest tests/test_cairn.py
pytest tests/test_linux_tools.py
pytest tests/test_riva.py

# Safety tests
pytest tests/test_security.py

# With coverage
pytest --cov=src/reos
```

### Priority Backlog

1. Safety layer integration tests (command blocking, rate limiting).
2. Agent routing tests (CAIRN → ReOS/RIVA handoff).
3. CAIRN coherence kernel tests.
4. ReOS parse gate tests.
5. RIVA contract/verification loop tests.
6. MCP protocol-level tests.
7. UI RPC contract tests.
