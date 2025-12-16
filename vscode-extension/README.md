## ReOS VS Code Bridge (local-only)

This extension mirrors **metadata-only** VS Code activity events to the local ReOS service.

### What it sends
- Active editor changes: file URI, language id, workspace folder path
- Saves: file URI, language id, workspace folder path
- Optional notes you type manually (stored locally by ReOS)

It does **not** read document contents automatically.

### Setup
1) Start the ReOS service (in this repo):
   - `python -m reos`
2) Open this folder in VS Code:
   - `File -> Open Folder... -> /home/kellogg/dev/ReOS/vscode-extension`
3) Press `F5` to launch an Extension Development Host.

### Use
- Status bar: **ReOS: Mirroring Off/On** (click to toggle)
- Command palette:
  - `ReOS: Ping Local Service`
  - `ReOS: Toggle Mirroring`
  - `ReOS: Send Note (Metadata Only)`

### Settings
- `reos.serverUrl` (default `http://127.0.0.1:8010`)
- `reos.mirroringEnabled` (default `false`)

### Charter alignment
- Localhost-only guard: the extension refuses to send events to non-localhost URLs.
- Metadata-only by default; no hidden network calls.
