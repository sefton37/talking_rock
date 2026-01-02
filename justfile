# ReOS Justfile
# Modern command runner - https://github.com/casey/just
# Install: cargo install just
# Usage: just <recipe>

# Default recipe - show help
default:
    @just --list

# =============================================================================
# Development Setup
# =============================================================================

# Full development environment setup
bootstrap: venv npm-install
    @echo "Bootstrap complete!"

# Create Python virtual environment
venv:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment..."
        python3.12 -m venv .venv
    fi
    echo "Installing Python dependencies..."
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e ".[dev]"

# Install TypeScript/Tauri dependencies
npm-install:
    cd apps/reos-tauri && npm install

# Install pre-commit hooks
hooks:
    pip install pre-commit
    pre-commit install
    pre-commit install --hook-type commit-msg

# =============================================================================
# Code Quality
# =============================================================================

# Run all linters
lint: lint-python lint-rust

# Lint Python code
lint-python:
    .venv/bin/ruff check src tests

# Lint Rust code
lint-rust:
    cd apps/reos-tauri/src-tauri && cargo clippy --all-targets --all-features -- -D warnings

# Auto-fix linting issues
fix:
    .venv/bin/ruff check --fix src tests

# Format all code
format: format-python format-rust

# Format Python code
format-python:
    .venv/bin/ruff format src tests

# Format Rust code
format-rust:
    cd apps/reos-tauri/src-tauri && cargo fmt

# Run type checker
typecheck:
    .venv/bin/mypy src

# Run all checks (lint + typecheck)
check: lint typecheck
    @echo "All checks passed!"

# =============================================================================
# Testing
# =============================================================================

# Run Python tests
test *args='':
    .venv/bin/pytest tests -v {{args}}

# Run tests with coverage
test-cov:
    .venv/bin/pytest tests --cov=reos --cov-report=term-missing --cov-report=html

# Run fast tests only
test-fast:
    .venv/bin/pytest tests -v -m "not slow"

# Run Rust tests
test-rust:
    cd apps/reos-tauri/src-tauri && cargo test

# Run all tests
test-all: test test-rust
    @echo "All tests passed!"

# =============================================================================
# Build
# =============================================================================

# Build everything
build: build-python build-tauri

# Build Python package
build-python:
    .venv/bin/python -m build

# Build Tauri desktop app
build-tauri:
    cd apps/reos-tauri && npm run tauri:build

# Build Tauri in debug mode
build-tauri-debug:
    cd apps/reos-tauri && npm run tauri:build -- --debug

# =============================================================================
# Run
# =============================================================================

# Start Tauri development server
dev:
    cd apps/reos-tauri && npm run tauri:dev

# Run Python kernel directly
kernel:
    .venv/bin/python -m reos.ui_rpc_server

# Run FastAPI server (legacy)
api:
    .venv/bin/python -m reos.app

# Run CLI
cli *args='':
    .venv/bin/python -m reos.cli {{args}}

# =============================================================================
# Installation
# =============================================================================

# Install for current user
install-user: build
    mkdir -p ~/.local/bin ~/.local/share/applications ~/.config/systemd/user
    cp apps/reos-tauri/src-tauri/target/release/reos_tauri ~/.local/bin/reos-desktop || true
    cp dist/reos.desktop ~/.local/share/applications/ || true
    cp dist/reos.service ~/.config/systemd/user/ || true
    .venv/bin/pip install --user .
    @echo "Installation complete!"
    @echo "Run: systemctl --user enable --now reos"

# =============================================================================
# Packaging
# =============================================================================

# Create AppImage
appimage: build-tauri
    ./scripts/build-appimage.sh

# Build Flatpak
flatpak:
    flatpak-builder --force-clean build-dir dist/dev.reos.ReOS.yaml

# =============================================================================
# Clean
# =============================================================================

# Remove build artifacts
clean:
    rm -rf build/ dist/ *.egg-info/
    rm -rf src/**/__pycache__ tests/**/__pycache__
    rm -rf .pytest_cache .mypy_cache .ruff_cache
    rm -rf htmlcov .coverage
    cd apps/reos-tauri && rm -rf dist/

# Remove all generated files including venv
clean-all: clean
    rm -rf .venv
    cd apps/reos-tauri && rm -rf node_modules/
    cd apps/reos-tauri/src-tauri && cargo clean

# =============================================================================
# Documentation
# =============================================================================

# Build documentation
docs:
    .venv/bin/python -m sphinx docs/ docs/_build/

# Serve documentation locally
docs-serve: docs
    .venv/bin/python -m http.server -d docs/_build/html 8000

# =============================================================================
# Release
# =============================================================================

# Full release pipeline
release: check test-all build
    @echo "Release build complete!"
    @echo "Don't forget to:"
    @echo "  1. Update CHANGELOG.md"
    @echo "  2. Tag the release"
    @echo "  3. Push the tag"

# Show current version
version:
    @grep -m1 'version = ' pyproject.toml | cut -d'"' -f2

# =============================================================================
# Utilities
# =============================================================================

# Watch files and run tests on change
watch:
    watchexec -e py -r -- just test

# Generate shell completions
completions shell='bash':
    .venv/bin/python -m reos.cli completions {{shell}}

# Open documentation
open-docs:
    xdg-open docs/_build/html/index.html 2>/dev/null || open docs/_build/html/index.html

# Database shell
db-shell:
    sqlite3 ~/.local/share/reos/reos.db

# View logs
logs:
    tail -f ~/.cache/reos/reos.log
