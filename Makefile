# ReOS Makefile
# Local-first, Git-first attention kernel companion

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Directories
ROOT_DIR := $(shell pwd)
VENV_DIR := $(ROOT_DIR)/.venv
TAURI_DIR := $(ROOT_DIR)/apps/reos-tauri
SRC_DIR := $(ROOT_DIR)/src
TESTS_DIR := $(ROOT_DIR)/tests

# Python
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip
PYTEST := $(VENV_DIR)/bin/pytest
RUFF := $(VENV_DIR)/bin/ruff
MYPY := $(VENV_DIR)/bin/mypy

# Versioning
VERSION := $(shell grep -m1 'version = ' pyproject.toml | cut -d'"' -f2)

# Colors
CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

.PHONY: help
help: ## Show this help message
	@echo -e "$(CYAN)ReOS$(RESET) - Local-first attention kernel"
	@echo -e "Version: $(VERSION)\n"
	@echo -e "$(GREEN)Available targets:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-20s$(RESET) %s\n", $$1, $$2}'

# =============================================================================
# Development Setup
# =============================================================================

.PHONY: bootstrap
bootstrap: venv npm-install ## Full development environment setup
	@echo -e "$(GREEN)Bootstrap complete!$(RESET)"

.PHONY: venv
venv: ## Create Python virtual environment
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo -e "$(CYAN)Creating virtual environment...$(RESET)"; \
		python3.12 -m venv $(VENV_DIR); \
	fi
	@echo -e "$(CYAN)Installing Python dependencies...$(RESET)"
	@$(PIP) install --upgrade pip
	@$(PIP) install -e ".[dev]"

.PHONY: npm-install
npm-install: ## Install TypeScript/Tauri dependencies
	@echo -e "$(CYAN)Installing npm dependencies...$(RESET)"
	@cd $(TAURI_DIR) && npm install

# =============================================================================
# Code Quality
# =============================================================================

.PHONY: lint
lint: lint-python lint-rust ## Run all linters

.PHONY: lint-python
lint-python: ## Lint Python code with ruff
	@echo -e "$(CYAN)Linting Python...$(RESET)"
	@$(RUFF) check $(SRC_DIR) $(TESTS_DIR)

.PHONY: lint-fix
lint-fix: ## Auto-fix Python linting issues
	@echo -e "$(CYAN)Fixing Python lint issues...$(RESET)"
	@$(RUFF) check --fix $(SRC_DIR) $(TESTS_DIR)

.PHONY: lint-rust
lint-rust: ## Lint Rust code with clippy
	@echo -e "$(CYAN)Linting Rust...$(RESET)"
	@cd $(TAURI_DIR)/src-tauri && cargo clippy --all-targets --all-features -- -D warnings

.PHONY: format
format: format-python format-rust ## Format all code

.PHONY: format-python
format-python: ## Format Python code with ruff
	@echo -e "$(CYAN)Formatting Python...$(RESET)"
	@$(RUFF) format $(SRC_DIR) $(TESTS_DIR)

.PHONY: format-rust
format-rust: ## Format Rust code with rustfmt
	@echo -e "$(CYAN)Formatting Rust...$(RESET)"
	@cd $(TAURI_DIR)/src-tauri && cargo fmt

.PHONY: typecheck
typecheck: ## Run mypy type checker
	@echo -e "$(CYAN)Type checking...$(RESET)"
	@$(MYPY) $(SRC_DIR)

.PHONY: check
check: lint typecheck ## Run all checks (lint + typecheck)
	@echo -e "$(GREEN)All checks passed!$(RESET)"

# =============================================================================
# Testing
# =============================================================================

.PHONY: test
test: ## Run Python tests
	@echo -e "$(CYAN)Running tests...$(RESET)"
	@$(PYTEST) $(TESTS_DIR) -v

.PHONY: test-fast
test-fast: ## Run tests without slow markers
	@echo -e "$(CYAN)Running fast tests...$(RESET)"
	@$(PYTEST) $(TESTS_DIR) -v -m "not slow"

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	@echo -e "$(CYAN)Running tests with coverage...$(RESET)"
	@$(PYTEST) $(TESTS_DIR) --cov=reos --cov-report=term-missing --cov-report=html

.PHONY: test-rust
test-rust: ## Run Rust tests
	@echo -e "$(CYAN)Running Rust tests...$(RESET)"
	@cd $(TAURI_DIR)/src-tauri && cargo test

.PHONY: test-all
test-all: test test-rust ## Run all tests (Python + Rust)
	@echo -e "$(GREEN)All tests passed!$(RESET)"

# =============================================================================
# Build
# =============================================================================

.PHONY: build
build: build-python build-tauri ## Build everything

.PHONY: build-python
build-python: ## Build Python package
	@echo -e "$(CYAN)Building Python package...$(RESET)"
	@$(PYTHON) -m build

.PHONY: build-tauri
build-tauri: ## Build Tauri desktop app
	@echo -e "$(CYAN)Building Tauri app...$(RESET)"
	@cd $(TAURI_DIR) && npm run tauri:build

.PHONY: build-tauri-debug
build-tauri-debug: ## Build Tauri app in debug mode
	@echo -e "$(CYAN)Building Tauri app (debug)...$(RESET)"
	@cd $(TAURI_DIR) && npm run tauri:build -- --debug

# =============================================================================
# Run
# =============================================================================

.PHONY: dev
dev: ## Run Tauri development server
	@echo -e "$(CYAN)Starting Tauri dev server...$(RESET)"
	@cd $(TAURI_DIR) && npm run tauri:dev

.PHONY: kernel
kernel: ## Run Python kernel directly
	@echo -e "$(CYAN)Starting Python kernel...$(RESET)"
	@$(PYTHON) -m reos.ui_rpc_server

.PHONY: api
api: ## Run FastAPI server (legacy)
	@echo -e "$(CYAN)Starting FastAPI server...$(RESET)"
	@$(PYTHON) -m reos.app

# =============================================================================
# Installation
# =============================================================================

PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
DATADIR ?= $(PREFIX)/share
MANDIR ?= $(DATADIR)/man

.PHONY: install
install: build ## Install ReOS system-wide
	@echo -e "$(CYAN)Installing ReOS...$(RESET)"
	@install -Dm755 $(TAURI_DIR)/src-tauri/target/release/reos_tauri $(DESTDIR)$(BINDIR)/reos-desktop
	@install -Dm644 dist/reos.desktop $(DESTDIR)$(DATADIR)/applications/reos.desktop
	@install -Dm644 dist/reos.png $(DESTDIR)$(DATADIR)/icons/hicolor/256x256/apps/reos.png
	@install -Dm644 dist/reos.1 $(DESTDIR)$(MANDIR)/man1/reos.1
	@$(PIP) install --prefix=$(DESTDIR)$(PREFIX) .
	@echo -e "$(GREEN)Installation complete!$(RESET)"

.PHONY: install-user
install-user: ## Install for current user only
	@echo -e "$(CYAN)Installing ReOS for current user...$(RESET)"
	@mkdir -p ~/.local/bin
	@mkdir -p ~/.local/share/applications
	@mkdir -p ~/.config/systemd/user
	@cp $(TAURI_DIR)/src-tauri/target/release/reos_tauri ~/.local/bin/reos-desktop || true
	@cp dist/reos.desktop ~/.local/share/applications/ || true
	@cp dist/reos.service ~/.config/systemd/user/ || true
	@$(PIP) install --user .
	@echo -e "$(GREEN)User installation complete!$(RESET)"
	@echo -e "$(YELLOW)Run: systemctl --user enable --now reos$(RESET)"

.PHONY: uninstall
uninstall: ## Uninstall ReOS
	@echo -e "$(CYAN)Uninstalling ReOS...$(RESET)"
	@rm -f $(DESTDIR)$(BINDIR)/reos-desktop
	@rm -f $(DESTDIR)$(DATADIR)/applications/reos.desktop
	@rm -f $(DESTDIR)$(DATADIR)/icons/hicolor/256x256/apps/reos.png
	@rm -f $(DESTDIR)$(MANDIR)/man1/reos.1
	@$(PIP) uninstall -y reos || true
	@echo -e "$(GREEN)Uninstall complete!$(RESET)"

# =============================================================================
# Packaging
# =============================================================================

.PHONY: dist
dist: dist-python dist-appimage dist-flatpak ## Create all distribution packages

.PHONY: dist-python
dist-python: ## Create Python source distribution
	@echo -e "$(CYAN)Creating Python sdist...$(RESET)"
	@$(PYTHON) -m build --sdist

.PHONY: dist-appimage
dist-appimage: build-tauri ## Create AppImage
	@echo -e "$(CYAN)Creating AppImage...$(RESET)"
	@./scripts/build-appimage.sh

.PHONY: dist-flatpak
dist-flatpak: ## Build Flatpak package
	@echo -e "$(CYAN)Building Flatpak...$(RESET)"
	@flatpak-builder --force-clean build-dir dist/dev.reos.ReOS.yaml

# =============================================================================
# Clean
# =============================================================================

.PHONY: clean
clean: ## Remove build artifacts
	@echo -e "$(CYAN)Cleaning build artifacts...$(RESET)"
	@rm -rf build/ dist/ *.egg-info/
	@rm -rf $(SRC_DIR)/**/__pycache__
	@rm -rf $(TESTS_DIR)/**/__pycache__
	@rm -rf .pytest_cache .mypy_cache .ruff_cache
	@rm -rf htmlcov .coverage
	@cd $(TAURI_DIR) && rm -rf dist/
	@cd $(TAURI_DIR)/src-tauri && cargo clean

.PHONY: clean-all
clean-all: clean ## Remove all generated files including venv
	@echo -e "$(CYAN)Removing virtual environment...$(RESET)"
	@rm -rf $(VENV_DIR)
	@cd $(TAURI_DIR) && rm -rf node_modules/

# =============================================================================
# Documentation
# =============================================================================

.PHONY: docs
docs: ## Build documentation
	@echo -e "$(CYAN)Building documentation...$(RESET)"
	@$(PYTHON) -m sphinx docs/ docs/_build/

.PHONY: docs-serve
docs-serve: docs ## Serve documentation locally
	@echo -e "$(CYAN)Serving docs at http://localhost:8000$(RESET)"
	@$(PYTHON) -m http.server -d docs/_build/html 8000

# =============================================================================
# Release
# =============================================================================

.PHONY: release
release: check test-all build dist ## Full release pipeline
	@echo -e "$(GREEN)Release build complete!$(RESET)"
	@echo -e "$(YELLOW)Don't forget to:$(RESET)"
	@echo -e "  1. Update CHANGELOG.md"
	@echo -e "  2. Tag the release: git tag v$(VERSION)"
	@echo -e "  3. Push: git push origin v$(VERSION)"

.PHONY: version
version: ## Show current version
	@echo $(VERSION)
