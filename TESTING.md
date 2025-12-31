# Testing Guide

Comprehensive testing strategy for ReOS covering unit, integration, contract, and E2E testing.

## Overview

ReOS uses a multi-layered testing approach:

- **Unit Tests**: Test individual components/functions in isolation
- **Integration Tests**: Test component interactions
- **Contract Tests**: Ensure frontend ↔ backend RPC compatibility
- **E2E Tests**: Test complete user workflows

## Quick Start

```bash
# Python tests
pytest                    # Run all Python tests with coverage
pytest -v                 # Verbose output
pytest tests/test_api.py  # Run specific test file

# TypeScript tests
cd apps/reos-tauri
npm test                  # Run all tests
npm run test:watch        # Watch mode
npm run test:ui           # Interactive UI
npm run test:coverage     # With coverage report

# E2E tests (when implemented)
npm run test:e2e          # Run E2E tests
npm run test:e2e:ui       # Interactive mode

# Type checking
npm run type-check        # TypeScript
mypy src/reos            # Python

# All tests
pytest && cd apps/reos-tauri && npm test && npm run type-check
```

## Test Structure

```
ReOS/
├── tests/                          # Python tests
│   ├── conftest.py                 # Shared fixtures
│   ├── test_api_smoke.py          # API endpoint tests
│   ├── test_agent_policy.py       # Agent behavior tests
│   ├── test_play_rpc.py           # Play RPC tests
│   └── test_*.py                  # More test files
│
└── apps/reos-tauri/
    ├── src/
    │   ├── components/
    │   │   ├── Chat.test.ts       # Chat component tests
    │   │   ├── Navigation.test.ts # Nav component tests
    │   │   ├── PlayInspector.test.ts
    │   │   └── types.test.ts      # Utility tests
    │   └── test/
    │       ├── setup.ts            # Test configuration
    │       └── rpc-contracts.test.ts  # Contract tests
    │
    ├── vitest.config.ts            # Vitest configuration
    └── playwright.config.ts        # E2E configuration
```

## Python Testing

### Running Tests

```bash
# All tests with coverage
pytest

# Specific test file
pytest tests/test_agent.py

# Specific test function
pytest tests/test_agent.py::test_agent_respects_tool_call_limit

# With coverage report
pytest --cov=src/reos --cov-report=html
open htmlcov/index.html  # View coverage

# Fail if coverage below threshold
pytest --cov-fail-under=70
```

### Writing Tests

```python
import pytest
from reos.db import Database

def test_example(isolated_db_singleton):
    """Test description."""
    db = isolated_db_singleton
    # Test implementation
    assert True

@pytest.fixture
def temp_git_repo(tmp_path):
    """Create temporary git repo for testing."""
    # Fixture implementation
    return repo_path
```

### Coverage Thresholds

- **Minimum**: 70% coverage (enforced in CI)
- **Target**: 80% coverage
- **Critical paths**: 90%+ coverage

Configuration in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = [
  "--cov=src/reos",
  "--cov-report=term-missing",
  "--cov-fail-under=70"
]
```

## TypeScript Testing

### Running Tests

```bash
cd apps/reos-tauri

# Run all tests
npm test

# Watch mode (auto-rerun on changes)
npm run test:watch

# Interactive UI
npm run test:ui

# Coverage report
npm run test:coverage
open coverage/index.html  # View coverage
```

### Writing Component Tests

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Chat } from './Chat';
import { createMockKernelRequest } from '../test/setup';

describe('Chat', () => {
  let mockKernelRequest: ReturnType<typeof createMockKernelRequest>;
  let chat: Chat;

  beforeEach(() => {
    mockKernelRequest = createMockKernelRequest();
    chat = new Chat(mockKernelRequest);
  });

  it('should send non-empty messages', async () => {
    mockKernelRequest.mockResolvedValue({ answer: 'Response' });

    const container = chat.render();
    const input = container.querySelector('.chat-input') as HTMLInputElement;
    const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

    input.value = 'Hello';
    sendBtn.click();

    await new Promise(resolve => setTimeout(resolve, 50));
    expect(mockKernelRequest).toHaveBeenCalledWith('chat/respond', { text: 'Hello' });
  });
});
```

### Coverage Thresholds

Configuration in `vitest.config.ts`:
```typescript
coverage: {
  thresholds: {
    lines: 70,
    functions: 70,
    branches: 70,
    statements: 70
  }
}
```

## RPC Contract Tests

Contract tests ensure frontend and backend agree on RPC method signatures.

Located in `apps/reos-tauri/src/test/rpc-contracts.test.ts`

```typescript
import { z } from 'zod';

const SettingsGetResponseSchema = z.object({
  ollama_url: z.string(),
  ollama_model: z.string(),
  // ... more fields
});

it('settings/get response matches schema', () => {
  const mockResponse = { /* ... */ };
  const result = SettingsGetResponseSchema.safeParse(mockResponse);
  expect(result.success).toBe(true);
});
```

**Benefits:**
- Catches breaking changes between frontend/backend
- Documents expected API responses
- Type-safe validation with Zod

## Continuous Integration

### GitHub Actions Workflow

Located in `.github/workflows/test.yml`

**Triggers:**
- Push to `main`, `develop`, `claude/**` branches
- Pull requests to `main`, `develop`

**Jobs:**

1. **python-tests**
   - Type checking with mypy
   - Linting with ruff
   - Tests with coverage
   - Upload to Codecov

2. **typescript-tests**
   - Type checking with tsc
   - Unit tests with Vitest
   - Coverage reporting
   - Upload to Codecov

3. **integration-check**
   - Build verification
   - Cross-platform compatibility

### Local CI Simulation

```bash
# Run what CI runs
./scripts/ci-local.sh  # (create this script)

# Or manually:
pytest --cov=src/reos --cov-report=xml
cd apps/reos-tauri
npm run type-check
npm run test:coverage
npm run build
```

## Pre-commit Hooks

### Setup

```bash
# Install pre-commit
pip install pre-commit

# Install git hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

### What Runs

Located in `.pre-commit-config.yaml`:

- **Always** (on every commit):
  - Trailing whitespace removal
  - End-of-file fixer
  - YAML/JSON/TOML validation
  - Large file check
  - Private key detection
  - Ruff formatting + linting
  - Mypy type checking
  - TypeScript type checking

- **Manual** (with `--hook-stage manual`):
  - Full Python test suite
  - Full TypeScript test suite

### Bypass Hooks

```bash
# Skip hooks (use sparingly)
git commit --no-verify
```

## Test Coverage Reports

### Viewing Coverage

**Python:**
```bash
pytest --cov=src/reos --cov-report=html
open htmlcov/index.html
```

**TypeScript:**
```bash
cd apps/reos-tauri
npm run test:coverage
open coverage/index.html
```

### Coverage Goals

| Component | Current | Target |
|-----------|---------|--------|
| Python Backend | ~70% | 80% |
| TypeScript Components | ~70% | 80% |
| RPC Contracts | 100% | 100% |
| Critical Paths | TBD | 90%+ |

## Best Practices

### Test Organization

- **One test file per source file**: `Chat.ts` → `Chat.test.ts`
- **Group related tests**: Use `describe()` blocks
- **Clear test names**: `should do X when Y happens`
- **AAA pattern**: Arrange, Act, Assert

### Mocking

**Python:**
```python
from unittest.mock import Mock, patch

@patch('reos.ollama.httpx.Client')
def test_with_mock(mock_client):
    mock_client.return_value.get.return_value.json.return_value = {...}
    # Test
```

**TypeScript:**
```typescript
import { vi } from 'vitest';

const mockFn = vi.fn();
mockFn.mockResolvedValue({ data: 'test' });
```

### Async Testing

**Python:**
```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_operation()
    assert result == expected
```

**TypeScript:**
```typescript
it('should handle async operations', async () => {
  const result = await asyncFunction();
  expect(result).toBe(expected);
});
```

### Error Testing

**Python:**
```python
import pytest
from reos.errors import KernelError

def test_error_handling():
    with pytest.raises(KernelError) as exc:
        raise_error()
    assert exc.value.code == -32602
```

**TypeScript:**
```typescript
it('should handle errors', async () => {
  mockKernelRequest.mockRejectedValue(new Error('Failed'));
  // ... trigger error
  expect(container.textContent).toContain('Error');
});
```

## Troubleshooting

### Tests Failing Locally

```bash
# Clean and reinstall
pip install -e ".[dev]" --force-reinstall
cd apps/reos-tauri && npm ci

# Clear caches
pytest --cache-clear
rm -rf apps/reos-tauri/node_modules/.vite
```

### Git Config Errors

Some tests require git configuration:
```bash
git config --global user.email "test@example.com"
git config --global user.name "Test User"
```

### Coverage Not Generated

```bash
# Python
rm -rf .coverage htmlcov/
pytest --cov=src/reos --cov-report=html

# TypeScript
rm -rf apps/reos-tauri/coverage/
cd apps/reos-tauri && npm run test:coverage
```

## Future Enhancements

- [ ] **Playwright E2E tests** for critical user flows
- [ ] **Visual regression testing** with Playwright screenshots
- [ ] **Accessibility testing** with jest-axe/playwright-axe
- [ ] **Performance testing** with Lighthouse CI
- [ ] **Load testing** for API endpoints
- [ ] **Mutation testing** with Stryker/mutmut
- [ ] **Property-based testing** with Hypothesis
- [ ] **Security testing** (SQL injection, XSS, path traversal)

## Resources

- [Vitest Documentation](https://vitest.dev/)
- [Playwright Documentation](https://playwright.dev/)
- [pytest Documentation](https://docs.pytest.org/)
- [Testing Library](https://testing-library.com/)
- [Codecov](https://codecov.io/)

## Contributing

When adding new features:

1. ✅ Write tests first (TDD)
2. ✅ Ensure coverage doesn't drop
3. ✅ Add contract tests for new RPC methods
4. ✅ Run `pre-commit` before committing
5. ✅ Verify CI passes before merging

Questions? See [docs/testing-strategy.md](docs/testing-strategy.md) or open an issue.
