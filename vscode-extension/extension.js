// ReOS VS Code Bridge
// Local-only by default: sends metadata (no document content).

const vscode = require('vscode');
const http = require('http');
const https = require('https');

function getConfig() {
  const cfg = vscode.workspace.getConfiguration('reos');
  return {
    serverUrl: cfg.get('serverUrl', 'http://127.0.0.1:8010'),
    enabled: cfg.get('mirroringEnabled', false),
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

  if (!cfg.enabled) {
    return;
  }

  if (!isLocalhostUrl(cfg.serverUrl)) {
    output.appendLine('[reos] Refusing to send: serverUrl is not localhost.');
    return;
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
    output.appendLine(`[reos] sent ${kind} -> ${res.status}`);
  } catch (err) {
    output.appendLine(`[reos] send failed (${kind}): ${String(err)}`);
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
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  const output = vscode.window.createOutputChannel('ReOS');

  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  updateStatusBar(statusBar);

  context.subscriptions.push(statusBar);
  context.subscriptions.push(output);

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('reos')) {
        updateStatusBar(statusBar);
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
      const note = await vscode.window.showInputBox({
        title: 'Send a short note to ReOS (metadata-only recommended)',
        prompt: 'Keep it short. Avoid pasting sensitive content; this is stored locally but still recorded.',
      });
      if (!note) return;
      await sendEvent(output, 'note', { note_length: note.length, note });
    })
  );

  // Metadata-only events
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(async (editor) => {
      if (!editor || !editor.document) return;
      const doc = editor.document;
      await sendEvent(output, 'active_editor', {
        uri: String(doc.uri),
        languageId: doc.languageId,
        workspaceFolder: vscode.workspace.getWorkspaceFolder(doc.uri)?.uri?.fsPath || null,
      });
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async (doc) => {
      await sendEvent(output, 'save', {
        uri: String(doc.uri),
        languageId: doc.languageId,
        workspaceFolder: vscode.workspace.getWorkspaceFolder(doc.uri)?.uri?.fsPath || null,
      });
    })
  );

  output.appendLine('[reos] extension activated');
}

function deactivate() {}

module.exports = { activate, deactivate };
