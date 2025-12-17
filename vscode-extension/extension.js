// ReOS VS Code Bridge
// Local-only by default: sends metadata (no document content).

const vscode = require('vscode');
const http = require('http');
const https = require('https');

function nowIso() {
  return new Date().toISOString();
}

class EventBuffer {
  /** @param {number} max */
  constructor(max) {
    this.max = max;
    /** @type {Array<any>} */
    this.items = [];
  }

  /** @param {any} evt */
  push(evt) {
    this.items.push(evt);
    if (this.items.length > this.max) {
      this.items.splice(0, this.items.length - this.max);
    }
  }

  toArray() {
    return this.items.slice();
  }
}

function getConfig() {
  const cfg = vscode.workspace.getConfiguration('reos');
  return {
    serverUrl: cfg.get('serverUrl', 'http://127.0.0.1:8010'),
    enabled: cfg.get('mirroringEnabled', false),
    maxEventsInPanel: cfg.get('maxEventsInPanel', 200),
    sendNoteBody: cfg.get('sendNoteBody', false),
  };
}

function setEnabled(value) {
  return vscode.workspace
    .getConfiguration('reos')
    .update('mirroringEnabled', value, vscode.ConfigurationTarget.Global);
}

function isLocalhostUrl(urlString) {
  try {
    const u = new URL(urlString);
    return u.hostname === '127.0.0.1' || u.hostname === 'localhost';
  } catch {
    return false;
  }
}

function postJson(urlString, path, body, timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    const base = new URL(urlString);
    const target = new URL(path, base);

    const data = Buffer.from(JSON.stringify(body), 'utf8');

    const isHttps = target.protocol === 'https:';
    const client = isHttps ? https : http;

    const req = client.request(
      {
        method: 'POST',
        hostname: target.hostname,
        port: target.port || (isHttps ? 443 : 80),
        path: target.pathname + target.search,
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': data.length,
        },
        timeout: timeoutMs,
      },
      (res) => {
        let raw = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => (raw += chunk));
        res.on('end', () => {
          resolve({ status: res.statusCode || 0, body: raw });
        });
      }
    );

    req.on('timeout', () => {
      req.destroy(new Error('request timeout'));
    });

    req.on('error', (err) => reject(err));
    req.write(data);
    req.end();
  });
}

async function sendEvent(output, kind, payload) {
  const cfg = getConfig();

  // Always record what the extension *observed* (even if mirroring is off), so
  // you can verify the data boundaries in real time.
  const observed = {
    observed_at: nowIso(),
    kind,
    enabled: cfg.enabled,
    payload,
    sent: false,
    status: null,
    error: null,
  };

  if (!cfg.enabled) {
    return observed;
  }

  if (!isLocalhostUrl(cfg.serverUrl)) {
    const msg = 'Refusing to send: serverUrl is not localhost.';
    output.appendLine(`[reos] ${msg}`);
    observed.error = msg;
    return observed;
  }

  const event = {
    source: 'vscode',
    payload_metadata: {
      kind,
      ...payload,
    },
  };

  try {
    const res = await postJson(cfg.serverUrl, '/events', event);
    observed.sent = true;
    observed.status = res.status;
    output.appendLine(`[reos] sent ${kind} -> ${res.status}`);
    return observed;
  } catch (err) {
    observed.sent = false;
    observed.error = String(err);
    output.appendLine(`[reos] send failed (${kind}): ${String(err)}`);
    return observed;
  }
}

function updateStatusBar(statusBar) {
  const cfg = getConfig();
  statusBar.text = cfg.enabled ? 'ReOS: Mirroring On' : 'ReOS: Mirroring Off';
  statusBar.tooltip = 'Toggle ReOS mirroring (metadata-only, localhost only)';
  statusBar.command = 'reos.toggleMirroring';
  statusBar.show();
}

/**
 * Get git branch and commit info for the workspace.
 */
async function getGitInfo() {
  try {
    const folders = vscode.workspace.workspaceFolders || [];
    const gitInfo = {};
    for (const folder of folders) {
      const git = vscode.extensions.getExtension('vscode.git')?.exports.getAPI(1);
      if (git) {
        const repo = git.getRepository(folder.uri);
        if (repo) {
          gitInfo[folder.uri.fsPath] = {
            branch: repo.state.HEAD?.name || 'unknown',
            commit: repo.state.HEAD?.commit || null,
          };
        }
      }
    }
    return gitInfo;
  } catch {
    return {};
  }
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  const output = vscode.window.createOutputChannel('ReOS');

  let panel = null;
  let buffer = new EventBuffer(getConfig().maxEventsInPanel);
  let activeEditor = null;
  let lastEditorChangeTime = Date.now();
  let fileEventHistory = []; // Track file switches for fragmentation detection

  function refreshBufferLimit() {
    const cfg = getConfig();
    if (cfg.maxEventsInPanel !== buffer.max) {
      buffer = new EventBuffer(cfg.maxEventsInPanel);
      // Note: we intentionally drop old events when resizing to keep semantics simple.
    }
  }

  function postToPanel() {
    if (!panel) return;
    try {
      panel.webview.postMessage({ type: 'events', events: buffer.toArray() });
    } catch {
      // ignore
    }
  }

  function ensurePanel() {
    if (panel) {
      panel.reveal();
      postToPanel();
      return;
    }

    panel = vscode.window.createWebviewPanel(
      'reosEvents',
      'ReOS Events',
      vscode.ViewColumn.Beside,
      { enableScripts: true }
    );

    panel.webview.html = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ReOS Events</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; padding: 10px; }
      .hint { opacity: 0.8; margin-bottom: 10px; }
      pre { white-space: pre-wrap; word-break: break-word; }
      .row { display: flex; gap: 8px; align-items: center; margin: 8px 0; }
      button { cursor: pointer; }
    </style>
  </head>
  <body>
    <div class="hint">
      Shows what this extension observes and (if enabled) sends to ReOS. Metadata-only by default.
    </div>
    <div class="row">
      <button id="refresh">Refresh</button>
      <span id="count"></span>
    </div>
    <pre id="out">(waiting for events...)</pre>
    <script>
      const vscode = acquireVsCodeApi();
      const out = document.getElementById('out');
      const count = document.getElementById('count');
      document.getElementById('refresh').addEventListener('click', () => {
        vscode.postMessage({ type: 'refresh' });
      });
      window.addEventListener('message', (event) => {
        const msg = event.data;
        if (!msg || msg.type !== 'events') return;
        const events = msg.events || [];
        count.textContent = `${events.length} events`;
        out.textContent = JSON.stringify(events, null, 2);
      });
    </script>
  </body>
</html>`;

    panel.webview.onDidReceiveMessage((msg) => {
      if (msg && msg.type === 'refresh') {
        postToPanel();
      }
    });

    panel.onDidDispose(() => {
      panel = null;
    });

    postToPanel();
  }

  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  updateStatusBar(statusBar);

  context.subscriptions.push(statusBar);
  context.subscriptions.push(output);

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('reos')) {
        refreshBufferLimit();
        updateStatusBar(statusBar);
        postToPanel();
      }
    })
  );

  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand('reos.toggleMirroring', async () => {
      const cfg = getConfig();
      await setEnabled(!cfg.enabled);
      updateStatusBar(statusBar);
      output.appendLine(`[reos] mirroring ${!cfg.enabled ? 'enabled' : 'disabled'}`);
      postToPanel();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('reos.openEventPanel', async () => {
      ensurePanel();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('reos.pingService', async () => {
      const cfg = getConfig();
      if (!isLocalhostUrl(cfg.serverUrl)) {
        vscode.window.showErrorMessage('ReOS serverUrl must be localhost.');
        return;
      }
      try {
        const res = await new Promise((resolve, reject) => {
          const base = new URL(cfg.serverUrl);
          const target = new URL('/health', base);
          const isHttps = target.protocol === 'https:';
          const client = isHttps ? https : http;
          const req = client.request(
            {
              method: 'GET',
              hostname: target.hostname,
              port: target.port || (isHttps ? 443 : 80),
              path: target.pathname + target.search,
              timeout: 1500,
            },
            (resp) => {
              let raw = '';
              resp.setEncoding('utf8');
              resp.on('data', (chunk) => (raw += chunk));
              resp.on('end', () => resolve({ status: resp.statusCode || 0, body: raw }));
            }
          );
          req.on('timeout', () => req.destroy(new Error('request timeout')));
          req.on('error', reject);
          req.end();
        });
        output.appendLine(`[reos] /health -> ${res.status} ${res.body}`);
        vscode.window.showInformationMessage('ReOS service reachable.');
      } catch (err) {
        output.appendLine(`[reos] ping failed: ${String(err)}`);
        vscode.window.showErrorMessage('ReOS service not reachable.');
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('reos.sendNote', async () => {
      const cfg = getConfig();
      const note = await vscode.window.showInputBox({
        title: 'Send a short note to ReOS (metadata-only recommended)',
        prompt: 'Keep it short. Avoid pasting sensitive content; this is stored locally but still recorded.',
      });
      if (!note) return;

      // Default is *not* to send note body, only length, unless user explicitly enables it.
      const payload = cfg.sendNoteBody
        ? { note_length: note.length, note }
        : { note_length: note.length };

      const observed = await sendEvent(output, 'note', payload);
      buffer.push(observed);
      postToPanel();
    })
  );

  // Metadata-only events
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(async (editor) => {
      if (!editor || !editor.document) return;
      const doc = editor.document;
      const workspaceFolder = vscode.workspace.getWorkspaceFolder(doc.uri);
      const folderPath = workspaceFolder?.uri?.fsPath || null;

      // Track file switch timing for fragmentation detection
      const now = Date.now();
      fileEventHistory.push({
        timestamp: now,
        uri: String(doc.uri),
        folder: folderPath,
      });
      // Keep last 1000 events (roughly 10-20 minutes of switching data)
      if (fileEventHistory.length > 1000) {
        fileEventHistory.shift();
      }
      lastEditorChangeTime = now;

      // Extract project name from folder path
      const projectName = folderPath ? folderPath.split('/').pop() : 'unknown';

      const observed = await sendEvent(output, 'active_editor', {
        uri: String(doc.uri),
        languageId: doc.languageId,
        workspaceFolder: folderPath,
        projectName,
        editorChangeTime: nowIso(),
      });
      buffer.push(observed);
      postToPanel();
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async (doc) => {
      const observed = await sendEvent(output, 'save', {
        uri: String(doc.uri),
        languageId: doc.languageId,
        workspaceFolder: vscode.workspace.getWorkspaceFolder(doc.uri)?.uri?.fsPath || null,
      });
      buffer.push(observed);
      postToPanel();
    })
  );

  // Periodic heartbeat: track time spent in current editor (every 10 seconds)
  // This allows ReOS to calculate time-in-file and detect extended focus/dwelling
  const heartbeatInterval = setInterval(async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor || !editor.document) return;

    const now = Date.now();
    const timeInFile = Math.round((now - lastEditorChangeTime) / 1000); // seconds

    const doc = editor.document;
    const workspaceFolder = vscode.workspace.getWorkspaceFolder(doc.uri);
    const folderPath = workspaceFolder?.uri?.fsPath || null;
    const projectName = folderPath ? folderPath.split('/').pop() : 'unknown';

    const observed = await sendEvent(output, 'heartbeat', {
      uri: String(doc.uri),
      languageId: doc.languageId,
      workspaceFolder: folderPath,
      projectName,
      timeInFileSeconds: timeInFile,
      fileHistoryCount: fileEventHistory.length,
    });
    buffer.push(observed);
    postToPanel();
  }, 10000); // Every 10 seconds

  context.subscriptions.push({
    dispose: () => clearInterval(heartbeatInterval),
  });

  output.appendLine('[reos] extension activated with real-time event streaming');
}

function deactivate() {}

module.exports = { activate, deactivate };
