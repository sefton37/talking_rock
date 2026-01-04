#!/usr/bin/env bash
# ReOS Shell Integration
#
# This script provides natural language terminal integration for ReOS.
# When you type something that isn't a valid command, ReOS will offer
# to interpret it as a natural language request.
#
# Installation:
#   Add to your ~/.bashrc or ~/.zshrc:
#     source /path/to/reos/scripts/reos-shell-integration.sh
#
# Usage:
#   After sourcing, just type natural language in your terminal:
#     $ what files are in my home directory
#     ReOS: 'what files are in my home directory' is not a command.
#            Treat as natural language? [Y/n]
#
# Configuration:
#   REOS_SHELL_AUTO=1       - Skip confirmation prompt (auto-process)
#   REOS_SHELL_DISABLED=1   - Disable ReOS shell integration temporarily

# Find the ReOS installation directory
_reos_find_root() {
    local script_path
    script_path="${BASH_SOURCE[0]:-$0}"

    # Handle symlinks
    if command -v readlink >/dev/null 2>&1; then
        script_path="$(readlink -f "$script_path" 2>/dev/null || echo "$script_path")"
    fi

    # Go up from scripts/ to repo root
    local dir
    dir="$(cd "$(dirname "$script_path")/.." 2>/dev/null && pwd)"

    if [[ -f "$dir/reos" ]]; then
        echo "$dir"
        return 0
    fi

    # Fallback: check if reos is in PATH
    if command -v reos >/dev/null 2>&1; then
        echo "$(dirname "$(command -v reos)")"
        return 0
    fi

    return 1
}

# ReOS shell integration handler
# This function is called by bash when a command is not found
command_not_found_handle() {
    local cmd="$1"
    shift
    local full_input="$cmd $*"

    # Disabled check
    if [[ -n "${REOS_SHELL_DISABLED:-}" ]]; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    # Skip if it looks like a typo of a real command (single word, short)
    if [[ -z "$*" && ${#cmd} -le 3 ]]; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    # Skip if it starts with common path prefixes (likely a real command attempt)
    case "$cmd" in
        /*|./*|../*|\~/*|./*)
            printf 'bash: %s: command not found\n' "$cmd" >&2
            return 127
            ;;
    esac

    # Skip if it contains shell operators that suggest a real command attempt
    case "$full_input" in
        *\|*|*\&*|*\>*|*\<*|*\;*)
            printf 'bash: %s: command not found\n' "$cmd" >&2
            return 127
            ;;
    esac

    # Find ReOS root
    local reos_root
    reos_root="$(_reos_find_root)"

    if [[ -z "$reos_root" ]]; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    local python_bin="$reos_root/.venv/bin/python"
    if [[ ! -x "$python_bin" ]]; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    # Auto mode - no confirmation
    if [[ -n "${REOS_SHELL_AUTO:-}" ]]; then
        printf '\033[36mReOS:\033[0m Processing: %s\n' "$full_input" >&2
        "$python_bin" -m reos.shell_cli "$full_input"
        return $?
    fi

    # Interactive mode - ask for confirmation
    printf '\033[36mReOS:\033[0m \047%s\047 is not a command.\n' "$full_input" >&2
    printf '       Treat as natural language? [Y/n] ' >&2

    local response
    read -r response

    case "$response" in
        n|N|no|NO|No)
            printf 'bash: %s: command not found\n' "$cmd" >&2
            return 127
            ;;
        *)
            "$python_bin" -m reos.shell_cli "$full_input"
            return $?
            ;;
    esac
}

# Direct invocation function: reos "natural language query"
reos() {
    local reos_root
    reos_root="$(_reos_find_root)"

    if [[ -z "$reos_root" ]]; then
        echo "ReOS: Could not find ReOS installation" >&2
        return 1
    fi

    local python_bin="$reos_root/.venv/bin/python"
    if [[ ! -x "$python_bin" ]]; then
        echo "ReOS: Python venv not found at $python_bin" >&2
        return 1
    fi

    if [[ $# -eq 0 ]]; then
        # No args - launch full GUI/service
        "$reos_root/reos" "$@"
    elif [[ "$1" == "--"* ]]; then
        # Has flags - pass to main launcher
        "$reos_root/reos" "$@"
    else
        # Natural language prompt
        "$python_bin" -m reos.shell_cli "$@"
    fi
}

# Alias for quick access
alias ask='reos'

# Export for subshells
export -f command_not_found_handle
export -f reos
export -f _reos_find_root

# Success message on load
if [[ -n "${BASH_VERSION:-}" ]]; then
    echo "ReOS shell integration loaded." >&2
    echo "  Usage: Just type natural language, or use 'reos \"query\"'" >&2
    echo "  Note: Queries starting with 'if/for/while' need quotes: reos \"if we have...\"" >&2
fi
