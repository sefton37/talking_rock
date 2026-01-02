# Contributing to ReOS

Thank you for your interest in contributing to ReOS! This document provides guidelines and information for contributors.

## Code of Conduct

By participating in this project, you agree to abide by our Code of Conduct:

- Be respectful and inclusive
- Focus on constructive feedback
- Assume good intentions
- Prioritize user privacy and data sovereignty

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+
- Rust (latest stable)
- Git
- Ollama (for local LLM)

### Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/reos.git
cd reos

# Run the bootstrap script
./scripts/bootstrap.sh

# Or use make
make bootstrap

# Verify the setup
make check
make test
```

### Running Locally

```bash
# Start the Tauri development server
make dev

# Or run just the Python kernel
make kernel

# Run the FastAPI server (legacy)
make api
```

## Development Workflow

### Branch Naming

Use descriptive branch names:

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation changes
- `refactor/description` - Code refactoring
- `test/description` - Test additions/changes

### Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `style`: Formatting (no code change)
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance

Examples:
```
feat(cli): add watch command for repo monitoring
fix(agent): handle empty LLM responses gracefully
docs(readme): update installation instructions
```

### Pre-commit Hooks

Install pre-commit hooks to ensure code quality:

```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg
```

## Code Quality

### Python

- **Style**: We use [ruff](https://github.com/astral-sh/ruff) for linting and formatting
- **Types**: Type hints are required; checked with [mypy](https://mypy-lang.org/)
- **Tests**: Write tests for new functionality using pytest

```bash
# Run linter
make lint-python

# Run formatter
make format-python

# Run type checker
make typecheck

# Run tests
make test
```

### Rust

- **Style**: Use `cargo fmt` for formatting
- **Linting**: Use `cargo clippy` with `-D warnings`

```bash
# Run Rust linter
make lint-rust

# Run Rust formatter
make format-rust

# Run Rust tests
make test-rust
```

### TypeScript

- **Style**: Use the project's TypeScript configuration
- **Types**: Strict type checking enabled

## Testing

### Test Structure

```
tests/
├── conftest.py          # Shared fixtures
├── test_*.py            # Test modules
└── fixtures/            # Test data
```

### Running Tests

```bash
# All Python tests
make test

# With coverage
make test-cov

# Fast tests only
make test-fast

# Rust tests
make test-rust

# All tests
make test-all
```

### Writing Tests

- Use pytest fixtures for setup/teardown
- Use `tmp_path` for temporary files
- Use `isolated_db_singleton` for database tests
- Mock external services (Ollama, git)

Example:

```python
def test_feature(tmp_path, isolated_db_singleton):
    """Test description."""
    # Arrange
    ...

    # Act
    result = function_under_test()

    # Assert
    assert result == expected
```

## Architecture Guidelines

### Core Principles

1. **Local-first**: No cloud dependencies by default
2. **Privacy**: Metadata-only; explicit opt-in for content
3. **Transparency**: All AI reasoning must be auditable
4. **Simplicity**: Minimal dependencies, clear interfaces

### File Organization

```
src/reos/
├── cli.py           # CLI entry point
├── paths.py         # XDG path handling
├── settings.py      # Configuration
├── db.py            # SQLite operations
├── agent.py         # LLM agent
├── mcp_tools.py     # Tool implementations
└── ...
```

### Adding New Features

1. Start with a design document or issue discussion
2. Implement with tests
3. Update documentation
4. Submit a pull request

### Adding New Tools

Tools in `mcp_tools.py` must:

1. Be repo-scoped with path sandboxing
2. Use `safe_repo_path()` for path validation
3. Return structured data (dict, not raw strings)
4. Handle errors gracefully with `ToolError`

## Pull Request Process

1. **Create a feature branch** from `main`
2. **Make your changes** with appropriate tests
3. **Run checks locally**: `make check && make test`
4. **Push your branch** and create a PR
5. **Fill out the PR template** with description and test plan
6. **Address review feedback**
7. **Squash and merge** once approved

### PR Checklist

- [ ] Tests pass locally
- [ ] Linting passes
- [ ] Type checking passes
- [ ] Documentation updated (if applicable)
- [ ] CHANGELOG.md updated (for user-facing changes)
- [ ] Commit messages follow conventions

## Documentation

- Update `README.md` for user-facing changes
- Update docstrings for API changes
- Add architecture docs in `docs/` for significant features

## Releasing

Releases are managed by maintainers:

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create a git tag: `git tag v0.x.y`
4. Push the tag: `git push origin v0.x.y`
5. CI will build and publish releases

## Getting Help

- **Issues**: For bugs and feature requests
- **Discussions**: For questions and ideas
- **Pull Requests**: For code contributions

## License

By contributing, you agree that your contributions will be licensed under the project's license.

---

Thank you for contributing to ReOS!
