#!/usr/bin/env bash
# ReOS Shell Integration - Parse Gate Architecture
#
# KERNEL PRINCIPLE: "Native until foreign. Foreign until confirmed."
#
# - Everything is passthrough by default—bash gets first claim on every keystroke
# - Only when input is unparseable as command does NL interpretation activate
# - NL interpretation never executes directly—it proposes, then awaits confirmation
#   that returns you to native execution
#
# SACRED CONTRACTS:
# - Commands execute literally (bash parses, bash executes)
# - Interactive prompts work (we don't exist during execution)
# - Pipes, redirects, chains all work (bash handles all syntax)
# - Tab completion, Ctrl+C, signals, history - all untouched
# - stdin/stdout/stderr - NL layer NEVER touches streams
#
# Installation:
#   Add to your ~/.bashrc or ~/.zshrc:
#     source /path/to/reos/scripts/reos-shell-integration.sh

# Find the ReOS installation directory
_reos_find_root() {
    local script_path
    script_path="${BASH_SOURCE[0]:-$0}"

    if command -v readlink >/dev/null 2>&1; then
        script_path="$(readlink -f "$script_path" 2>/dev/null || echo "$script_path")"
    fi

    local dir
    dir="$(cd "$(dirname "$script_path")/.." 2>/dev/null && pwd)"

    if [[ -f "$dir/reos" ]]; then
        echo "$dir"
        return 0
    fi

    if command -v reos >/dev/null 2>&1; then
        echo "$(dirname "$(command -v reos)")"
        return 0
    fi

    return 1
}

# Cache paths
_REOS_ROOT="$(_reos_find_root)"
_REOS_PYTHON="${_REOS_ROOT}/.venv/bin/python"

# Colors for output
_reos_color() {
    local color="$1"
    shift
    case "$color" in
        cyan)    printf '\033[36m%s\033[0m' "$*" ;;
        green)   printf '\033[32m%s\033[0m' "$*" ;;
        yellow)  printf '\033[33m%s\033[0m' "$*" ;;
        red)     printf '\033[31m%s\033[0m' "$*" ;;
        dim)     printf '\033[2m%s\033[0m' "$*" ;;
        bold)    printf '\033[1m%s\033[0m' "$*" ;;
        *)       printf '%s' "$*" ;;
    esac
}

# Check if input looks like a typo of a real command
_reos_is_typo() {
    local input="$1"
    local first_word="${input%% *}"

    # Single short word - probably a typo
    [[ ${#first_word} -le 2 && "$input" == "$first_word" ]] && return 0

    # Starts with path characters - probably meant to run something
    [[ "$first_word" == /* || "$first_word" == ./* || "$first_word" == ../* ]] && return 0

    return 1
}

# Check if input looks like natural language vs command typo
# PRINCIPLE: Be permissive. If bash rejected it, the NL interpreter should try.
# Only reject things that are obviously NOT natural language.
_reos_is_natural_language() {
    local input="$1"
    local lower="${input,,}"
    local word_count
    word_count=$(echo "$input" | wc -w)

    # Multi-word input is almost always natural language intent
    # (If it were valid shell syntax, bash would have run it)
    [[ $word_count -ge 2 ]] && return 0

    # Single word that looks like an action verb (even misspelled)
    # Common action words and their likely typos
    [[ "$lower" =~ ^(install|intall|instal|remove|delete|create|make|start|stop|restart|check|update|upgrade|search|open|close|kill|run|show|list|find|help|what|how|why|where|who|can|please) ]] && return 0

    # Single word ending in common verb suffixes
    [[ "$lower" =~ (ing|ate|ify|ize)$ ]] && return 0

    # If it's a single word and not in any of the above, it's probably a typo
    # Let bash's "command not found" handle it
    return 1
}

# THE PARSE GATE - This is our only entry point
# Called by bash when a command is not found
command_not_found_handle() {
    local cmd="$1"
    shift
    local full_input="$cmd${*:+ $*}"

    # Disabled check
    if [[ -n "${REOS_SHELL_DISABLED:-}" ]]; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    # Quick rejection: likely typos or path errors
    if _reos_is_typo "$full_input"; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    # Check if this looks like natural language
    if ! _reos_is_natural_language "$full_input"; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    # ═══════════════════════════════════════════════════════════════
    # NL INTERPRETATION - Propose only, never execute
    # ═══════════════════════════════════════════════════════════════

    _reos_color cyan "🐧 ReOS: "
    _reos_color dim "Interpreting: "
    echo "$full_input"
    echo ""

    # Call Python to propose a command (NOT execute)
    local proposed_command
    local explanation
    local result

    if [[ ! -x "$_REOS_PYTHON" ]]; then
        _reos_color red "Error: ReOS Python not found at $_REOS_PYTHON"
        echo ""
        return 1
    fi

    # Get proposed command from Python (propose-only mode)
    result=$("$_REOS_PYTHON" -m reos.shell_propose "$full_input" 2>&1)
    local exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        _reos_color red "Error: "
        echo "$result"
        return 1
    fi

    # Parse result (format: COMMAND\nEXPLANATION)
    proposed_command=$(echo "$result" | head -1)
    explanation=$(echo "$result" | tail -n +2)

    if [[ -z "$proposed_command" ]]; then
        _reos_color yellow "I couldn't determine a command for that request."
        echo ""
        return 1
    fi

    # ═══════════════════════════════════════════════════════════════
    # CONFIRMATION GATE - User decides, then native execution
    # ═══════════════════════════════════════════════════════════════

    _reos_color bold "Proposed command:"
    echo ""
    echo "  $proposed_command"
    echo ""

    if [[ -n "$explanation" ]]; then
        _reos_color dim "$explanation"
        echo ""
        echo ""
    fi

    # Prompt for confirmation
    local response
    read -p $'[\033[32my\033[0m]es / [\033[31mn\033[0m]o / [\033[33me\033[0m]dit: ' -n1 response
    echo ""

    case "$response" in
        y|Y)
            echo ""
            # ═══════════════════════════════════════════════════════
            # NATIVE EXECUTION - Bash runs the command directly
            # The NL layer is now completely out of the picture
            # ═══════════════════════════════════════════════════════
            history -s "$proposed_command"
            eval "$proposed_command"
            return $?
            ;;
        e|E)
            echo ""
            # Let user edit the command
            local edited_command
            read -e -p "Edit command: " -i "$proposed_command" edited_command
            if [[ -n "$edited_command" ]]; then
                echo ""
                history -s "$edited_command"
                eval "$edited_command"
                return $?
            else
                _reos_color dim "Cancelled (empty command)."
                echo ""
                return 1
            fi
            ;;
        *)
            echo ""
            _reos_color dim "Cancelled."
            echo ""
            return 1
            ;;
    esac
}

# Direct invocation: reos "natural language query"
reos() {
    if [[ -z "$_REOS_ROOT" ]]; then
        echo "ReOS: Could not find ReOS installation" >&2
        return 1
    fi

    if [[ ! -x "$_REOS_PYTHON" ]]; then
        echo "ReOS: Python venv not found at $_REOS_PYTHON" >&2
        return 1
    fi

    if [[ $# -eq 0 ]]; then
        # No args - launch GUI
        "$_REOS_ROOT/reos" "$@"
    elif [[ "$1" == "--"* ]]; then
        # Has flags - pass to main launcher
        "$_REOS_ROOT/reos" "$@"
    else
        # Explicit NL request - goes through same flow as command_not_found
        local full_input="$*"

        _reos_color cyan "🐧 ReOS: "
        _reos_color dim "Interpreting: "
        echo "$full_input"
        echo ""

        local result
        result=$("$_REOS_PYTHON" -m reos.shell_propose "$full_input" 2>&1)
        local exit_code=$?

        if [[ $exit_code -ne 0 ]]; then
            _reos_color red "Error: "
            echo "$result"
            return 1
        fi

        local proposed_command
        local explanation
        proposed_command=$(echo "$result" | head -1)
        explanation=$(echo "$result" | tail -n +2)

        if [[ -z "$proposed_command" ]]; then
            _reos_color yellow "I couldn't determine a command for that request."
            echo ""
            return 1
        fi

        _reos_color bold "Proposed command:"
        echo ""
        echo "  $proposed_command"
        echo ""

        if [[ -n "$explanation" ]]; then
            _reos_color dim "$explanation"
            echo ""
            echo ""
        fi

        local response
        read -p $'[\033[32my\033[0m]es / [\033[31mn\033[0m]o / [\033[33me\033[0m]dit: ' -n1 response
        echo ""

        case "$response" in
            y|Y)
                echo ""
                history -s "$proposed_command"
                eval "$proposed_command"
                return $?
                ;;
            e|E)
                echo ""
                local edited_command
                read -e -p "Edit command: " -i "$proposed_command" edited_command
                if [[ -n "$edited_command" ]]; then
                    echo ""
                    history -s "$edited_command"
                    eval "$edited_command"
                    return $?
                else
                    _reos_color dim "Cancelled."
                    echo ""
                    return 1
                fi
                ;;
            *)
                echo ""
                _reos_color dim "Cancelled."
                echo ""
                return 1
                ;;
        esac
    fi
}

# Alias for convenience
alias ask='reos'

# Export for subshells
export -f command_not_found_handle
export -f reos
export -f _reos_find_root
export -f _reos_is_typo
export -f _reos_is_natural_language
export -f _reos_color
export _REOS_ROOT
export _REOS_PYTHON

# Announce (minimal - we're not intercepting anything)
if [[ -n "${BASH_VERSION:-}" && -t 0 ]]; then
    echo "🐧 ReOS: Natural language available. Just type what you want." >&2
    echo "   Valid commands run normally. Unknown input gets interpreted." >&2
fi
