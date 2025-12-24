import { invoke } from '@tauri-apps/api/core';
import { z } from 'zod';

import './style.css';

const JsonRpcResponseSchema = z.object({
  jsonrpc: z.literal('2.0'),
  id: z.union([z.string(), z.number(), z.null()]).optional(),
  result: z.unknown().optional(),
  error: z
    .object({
      code: z.number(),
      message: z.string(),
      data: z.unknown().optional()
    })
    .optional()
});

type ChatRespondResult = {
  answer: string;
};

type ProjectsListResult = {
  projects: string[];
  active_project_id: string | null;
};

type KbTreeResult = {
  project_id: string | null;
  files: string[];
};

type KbReadResult = {
  path: string;
  text: string;
};

type KbWritePreviewResult = {
  project_id: string;
  path: string;
  exists: boolean;
  sha256_current: string;
  sha256_new: string;
  diff: string;
};

type KbWriteApplyResult = {
  ok: boolean;
  project_id: string;
  path: string;
  sha256_current: string;
};


async function kernelRequest(method: string, params: unknown): Promise<unknown> {
  const raw = await invoke('kernel_request', { method, params });
  const parsed = JsonRpcResponseSchema.parse(raw);
  if (parsed.error) {
    throw new Error(`${parsed.error.message} (code ${parsed.error.code})`);
  }
  return parsed.result;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function buildUi() {
  const root = document.getElementById('app');
  if (!root) return;

  root.innerHTML = '';

  const shell = el('div');
  shell.className = 'shell';
  shell.style.display = 'flex';
  shell.style.height = '100vh';
  shell.style.fontFamily = 'system-ui, sans-serif';

  const nav = el('div');
  nav.className = 'nav';
  nav.style.width = '240px';
  nav.style.borderRight = '1px solid #ddd';
  nav.style.padding = '12px';
  nav.style.overflow = 'auto';

  const navTitle = el('div');
  navTitle.textContent = 'ReOS';
  navTitle.style.fontWeight = '600';
  navTitle.style.marginBottom = '10px';

  const projectsHeader = el('div');
  projectsHeader.textContent = 'Projects';
  projectsHeader.style.marginTop = '12px';
  projectsHeader.style.fontWeight = '600';

  const projectsList = el('div');
  projectsList.style.display = 'flex';
  projectsList.style.flexDirection = 'column';
  projectsList.style.gap = '6px';

  const kbHeader = el('div');
  kbHeader.textContent = 'KB';
  kbHeader.style.marginTop = '12px';
  kbHeader.style.fontWeight = '600';

  const kbList = el('div');
  kbList.style.display = 'flex';
  kbList.style.flexDirection = 'column';
  kbList.style.gap = '6px';


  nav.appendChild(navTitle);
  nav.appendChild(projectsHeader);
  nav.appendChild(projectsList);
  nav.appendChild(kbHeader);
  nav.appendChild(kbList);

  const center = el('div');
  center.className = 'center';
  center.style.flex = '1';
  center.style.display = 'flex';
  center.style.flexDirection = 'column';

  const chatLog = el('div');
  chatLog.className = 'chat-log';
  chatLog.style.flex = '1';
  chatLog.style.padding = '12px';
  chatLog.style.overflow = 'auto';

  const inputRow = el('div');
  inputRow.className = 'input-row';
  inputRow.style.display = 'flex';
  inputRow.style.gap = '8px';
  inputRow.style.padding = '12px';
  inputRow.style.borderTop = '1px solid #ddd';

  const input = el('input');
  input.className = 'chat-input';
  input.type = 'text';
  input.placeholder = 'Type a message…';
  input.style.flex = '1';

  const send = el('button');
  send.className = 'send-btn';
  send.textContent = 'Send';

  inputRow.appendChild(input);
  inputRow.appendChild(send);

  const inspection = el('div');
  inspection.className = 'inspection';
  inspection.style.width = '420px';
  inspection.style.borderLeft = '1px solid #ddd';
  inspection.style.margin = '0';
  inspection.style.padding = '12px';
  inspection.style.overflow = 'auto';

  const inspectionTitle = el('div');
  inspectionTitle.style.fontWeight = '600';
  inspectionTitle.style.marginBottom = '8px';
  inspectionTitle.textContent = 'Inspection';

  const inspectionBody = el('div');

  inspection.appendChild(inspectionTitle);
  inspection.appendChild(inspectionBody);

  center.appendChild(chatLog);
  center.appendChild(inputRow);

  shell.appendChild(nav);
  shell.appendChild(center);
  shell.appendChild(inspection);

  root.appendChild(shell);

  function append(role: 'user' | 'reos', text: string) {
    const row = el('div');
    row.className = `chat-row ${role}`;

    const bubble = el('div');
    bubble.className = `chat-bubble ${role}`;
    bubble.textContent = text;

    row.appendChild(bubble);
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function appendThinking(): { row: HTMLDivElement; bubble: HTMLDivElement } {
    const row = el('div') as HTMLDivElement;
    row.className = 'chat-row reos';

    const bubble = el('div') as HTMLDivElement;
    bubble.className = 'chat-bubble reos thinking';

    const dots = el('span') as HTMLSpanElement;
    dots.className = 'typing-dots';
    dots.innerHTML = '<span></span><span></span><span></span>';
    bubble.appendChild(dots);

    row.appendChild(bubble);
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
    return { row, bubble };
  }

  let activeProjectId: string | null = null;

  function showJsonInInspector(title: string, obj: unknown) {
    inspectionTitle.textContent = title;
    inspectionBody.innerHTML = '';
    const pre = el('pre');
    pre.style.margin = '0';
    pre.textContent = JSON.stringify(obj ?? null, null, 2);
    inspectionBody.appendChild(pre);
  }

  function showKbEditor(opts: { projectId: string; treePath: string; file: KbReadResult }) {
    inspectionTitle.textContent = `KB: ${opts.file.path.replace(/^projects\//, '')}`;
    inspectionBody.innerHTML = '';

    const status = el('div');
    status.style.marginBottom = '8px';
    status.style.opacity = '0.8';
    status.textContent = '';

    const textarea = el('textarea');
    textarea.value = opts.file.text ?? '';
    textarea.style.width = '100%';
    textarea.style.height = '40vh';
    textarea.style.fontFamily = 'monospace';
    textarea.style.fontSize = '12px';
    textarea.style.boxSizing = 'border-box';

    const btnRow = el('div');
    btnRow.style.display = 'flex';
    btnRow.style.gap = '8px';
    btnRow.style.marginTop = '8px';
    btnRow.style.marginBottom = '8px';

    const previewBtn = el('button');
    previewBtn.textContent = 'Preview diff';

    const applyBtn = el('button');
    applyBtn.textContent = 'Apply';
    applyBtn.disabled = true;

    const reloadBtn = el('button');
    reloadBtn.textContent = 'Reload';

    btnRow.appendChild(previewBtn);
    btnRow.appendChild(applyBtn);
    btnRow.appendChild(reloadBtn);

    const diffPre = el('pre');
    diffPre.style.margin = '0';
    diffPre.style.whiteSpace = 'pre-wrap';
    diffPre.textContent = '';

    let expectedShaCurrent: string | null = null;

    async function reload() {
      status.textContent = 'Reloading…';
      try {
        const reloaded = (await kernelRequest('kb/read', {
          project_id: opts.projectId,
          path: opts.treePath
        })) as KbReadResult;
        textarea.value = reloaded.text ?? '';
        diffPre.textContent = '';
        expectedShaCurrent = null;
        applyBtn.disabled = true;
        status.textContent = '';
      } catch (e) {
        status.textContent = `Reload error: ${String(e)}`;
      }
    }

    previewBtn.addEventListener('click', () => {
      void (async () => {
        status.textContent = 'Previewing…';
        try {
          const res = (await kernelRequest('kb/write_preview', {
            project_id: opts.projectId,
            path: opts.treePath,
            text: textarea.value
          })) as KbWritePreviewResult;
          expectedShaCurrent = res.sha256_current;
          diffPre.textContent = res.diff || '(no changes)';
          applyBtn.disabled = false;
          status.textContent = '';
        } catch (e) {
          expectedShaCurrent = null;
          applyBtn.disabled = true;
          status.textContent = `Preview error: ${String(e)}`;
        }
      })();
    });

    applyBtn.addEventListener('click', () => {
      void (async () => {
        if (!expectedShaCurrent) {
          status.textContent = 'Preview diff before applying.';
          return;
        }
        status.textContent = 'Applying…';
        try {
          const res = (await kernelRequest('kb/write_apply', {
            project_id: opts.projectId,
            path: opts.treePath,
            text: textarea.value,
            expected_sha256_current: expectedShaCurrent
          })) as KbWriteApplyResult;
          expectedShaCurrent = res.sha256_current;
          diffPre.textContent = '';
          applyBtn.disabled = true;
          status.textContent = 'Applied.';
        } catch (e) {
          status.textContent = `Apply error: ${String(e)}`;
        }
      })();
    });

    reloadBtn.addEventListener('click', () => void reload());

    inspectionBody.appendChild(status);
    inspectionBody.appendChild(textarea);
    inspectionBody.appendChild(btnRow);
    inspectionBody.appendChild(diffPre);
  }

  async function refreshProjects() {
    const res = (await kernelRequest('projects/list', {})) as ProjectsListResult;
    activeProjectId = res.active_project_id ?? null;

    projectsList.innerHTML = '';
    for (const id of res.projects ?? []) {
      const btn = el('button');
      btn.textContent = id === activeProjectId ? `• ${id}` : id;
      btn.addEventListener('click', async () => {
        await kernelRequest('projects/set_active', { project_id: id });
        activeProjectId = id;
        await refreshProjects();
        await refreshKb();
      });
      projectsList.appendChild(btn);
    }

    if ((res.projects ?? []).length === 0) {
      const empty = el('div');
      empty.textContent = '(no projects/)';
      empty.style.opacity = '0.7';
      projectsList.appendChild(empty);
    }
  }

  async function refreshKb() {
    kbList.innerHTML = '';
    const res = (await kernelRequest('kb/tree', { project_id: activeProjectId })) as KbTreeResult;
    if (!res.project_id) {
      const empty = el('div');
      empty.textContent = '(select a project)';
      empty.style.opacity = '0.7';
      kbList.appendChild(empty);
      return;
    }

    for (const p of res.files ?? []) {
      const btn = el('button');
      btn.textContent = p.replace(/^projects\//, '');
      btn.addEventListener('click', async () => {
        const file = (await kernelRequest('kb/read', { project_id: res.project_id, path: p })) as KbReadResult;
        showKbEditor({ projectId: res.project_id as string, treePath: p, file });
      });
      kbList.appendChild(btn);
    }

    if ((res.files ?? []).length === 0) {
      const empty = el('div');
      empty.textContent = '(no kb files)';
      empty.style.opacity = '0.7';
      kbList.appendChild(empty);
    }
  }


  async function onSend() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    append('user', text);

    // Immediately show an empty ReOS bubble with a thinking animation.
    const pending = appendThinking();

    try {
      const res = (await kernelRequest('chat/respond', { text })) as ChatRespondResult;
      pending.bubble.classList.remove('thinking');
      pending.bubble.textContent = res.answer ?? '(no answer)';
    } catch (e) {
      pending.bubble.classList.remove('thinking');
      pending.bubble.textContent = `Error: ${String(e)}`;
    }
  }

  send.addEventListener('click', () => void onSend());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') void onSend();
  });

  // Initial load
  void (async () => {
    try {
      await refreshProjects();
      await refreshKb();
    } catch (e) {
      showJsonInInspector('Startup error', { error: String(e) });
    }
  })();
}

buildUi();
