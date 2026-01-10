# Talking Rock Desktop (Tauri)

This is the Talking Rock desktop application—a Tauri shell that spawns the Python kernel and communicates via stdio JSON-RPC.

The app provides the UI for three specialized agents:
- **CAIRN** - Attention minder (default)
- **ReOS** - System agent for Linux control
- **RIVA** - Coding agent

## Dev Prerequisites

- Node + npm
- Rust toolchain
- Python 3.12+ with `reos` importable (e.g. `pip install -e .` from repo root)

## Run (dev)

From repo root:
```bash
pip install -e .
```

From this folder:
```bash
npm install
npm run tauri:dev
```

## Kernel

The UI spawns the Python kernel:
```bash
python -m reos.ui_rpc_server
```

You can override which Python is used:
```bash
export REOS_PYTHON=/path/to/.venv/bin/python
```

If `REOS_PYTHON` is not set, the app will try to auto-detect `.venv/bin/python` by walking upward from the Tauri executable.

## RPC Methods

Currently implemented:
- `chat/respond` with `{ "text": "..." }` - Main chat interface, routes to CAIRN/ReOS/RIVA

Coming soon:
- System state queries (for ReOS panel)
- The Play navigation (for CAIRN)
- Code execution streaming (for RIVA)
