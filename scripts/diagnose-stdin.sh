#!/usr/bin/env bash
# Diagnostic script for stdin issues in ReOS shell integration

echo "=== ReOS Stdin Diagnostic ==="
echo ""

# Test 1: Basic terminal check
echo "1. Terminal check:"
echo "   TTY: $(tty)"
echo "   TERM: $TERM"
echo "   stdin isatty: $([ -t 0 ] && echo "yes" || echo "no")"
echo ""

# Test 2: Current stty settings
echo "2. Current stty settings:"
stty -a 2>&1 | head -5
echo ""

# Test 3: Test direct bash read
echo "3. Testing bash read (type something and press Enter):"
read -p "   Enter text: " test_input
echo "   You entered: '$test_input'"
echo ""

# Test 4: Test Python stdin
echo "4. Testing Python stdin:"
"${_REOS_PYTHON:-python3}" -c "
import sys
print(f'   stdin.isatty(): {sys.stdin.isatty()}')
print(f'   stdin fileno: {sys.stdin.fileno()}')
x = input('   Enter text: ')
print(f'   You entered: {repr(x)}')
"
echo ""

# Test 5: Test Python subprocess with os.system
echo "5. Testing Python os.system (type Y and press Enter):"
"${_REOS_PYTHON:-python3}" -c "
import os
os.environ['REOS_TERMINAL_MODE'] = '1'
ret = os.system('read -p \"   Enter Y/n: \" x && echo \"   Got: \$x\"')
print(f'   Return code: {ret}')
"
echo ""

# Test 6: Test through the actual code path
echo "6. Testing actual ReOS execute_command:"
"${_REOS_PYTHON:-python3}" -c "
import os
import sys
sys.path.insert(0, '${_REOS_ROOT:-/home/kellogg/dev/ReOS}/src')
os.environ['REOS_TERMINAL_MODE'] = '1'

from reos.linux_tools import execute_command
print('   Calling execute_command with interactive prompt...')
result = execute_command('read -p \"   Enter Y/n: \" x && echo \"   Got: \$x\"', timeout=30)
print(f'   Result: success={result.success}, returncode={result.returncode}')
"
echo ""

echo "=== Diagnostic Complete ==="
