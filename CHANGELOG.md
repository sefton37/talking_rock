# Changelog

All notable changes to ReOS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **CLI**: Full-featured command-line interface with subcommands
  - `reos status` - Show kernel and repository status
  - `reos kernel` - Start the kernel (with daemon mode)
  - `reos stop` - Stop running kernel daemon
  - `reos watch` - Watch a git repository
  - `reos review` - Review commits with LLM
  - `reos chat` - Interactive chat mode
  - `reos config` - Configuration management
  - `reos play` - Acts/Scenes/Beats management
  - `reos persona` - Agent persona management
- **XDG Compliance**: Proper XDG Base Directory support
  - Data in `~/.local/share/reos/`
  - Config in `~/.config/reos/`
  - Cache in `~/.cache/reos/`
  - Migration from legacy `.reos-data/` directory
- **Shell Completions**: Tab completion for bash, zsh, and fish
- **Man Page**: Full manual page (`man reos`)
- **Makefile**: Standard build targets (`make install`, `make test`, etc.)
- **GitHub Actions CI**: Automated testing, linting, and builds
- **systemd Service**: User service for running kernel as daemon
- **Desktop Entry**: `.desktop` file for application menu integration
- **Pre-commit Hooks**: Automated code quality checks
- **Flatpak Manifest**: For universal Linux distribution
- **AppImage Build**: Portable Linux application bundle
- **D-Bus Notifications**: Desktop notification integration
- **Nix Flake**: Reproducible builds for NixOS
- **Justfile**: Modern task runner alternative to Make
- **Devcontainer**: VS Code / GitHub Codespaces support
- **Structured Logging**: JSON log output option
- **Config File**: TOML configuration file support
- **Tauri CSP**: Content Security Policy hardening

### Changed

- Settings now use XDG paths by default on Linux
- Logging now supports structured JSON format
- Stricter mypy configuration for better type safety
- pytest-cov integration with coverage thresholds

### Security

- Added Tauri Content-Security-Policy configuration
- systemd service hardening with security directives
- Path sandboxing improvements in tool execution

### Documentation

- Added `CONTRIBUTING.md` with development guidelines
- Added `SECURITY.md` with vulnerability reporting process
- Added architecture diagrams
- Expanded man page with all commands and options

## [0.0.0-alpha.1] - 2024-XX-XX

### Added

- Initial M1b release: Git-first companion architecture
- Python kernel with SQLite storage
- Tauri desktop application shell
- stdio JSON-RPC 2.0 IPC between UI and kernel
- Git polling and metadata collection
- Ollama integration for local LLM
- Play filesystem (Acts/Scenes/Beats theatrical model)
- Agent personas with customizable system prompts
- MCP tools with repo sandboxing:
  - `reos_git_summary`
  - `reos_repo_grep`
  - `reos_repo_read_file`
  - `reos_repo_list_files`
  - `reos_repo_discover`
- Context budget estimation for LLM overflow prevention
- Review trigger system with cooldown
- Commit watch and auto-review (opt-in)
- Alignment analysis against charter/roadmap

### Architecture

- FastAPI backend (legacy, being phased out)
- stdio JSON-RPC server for Tauri IPC
- SQLite database with migrations
- Event-driven storage with trigger hooks
- Transparent reasoning with audit logging

---

[Unreleased]: https://github.com/your-org/reos/compare/v0.0.0-alpha.1...HEAD
[0.0.0-alpha.1]: https://github.com/your-org/reos/releases/tag/v0.0.0-alpha.1
