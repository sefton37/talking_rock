import { invoke } from '@tauri-apps/api/core';
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';
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

type PlayMeReadResult = {
  markdown: string;
};

type PlayActsListResult = {
  active_act_id: string | null;
  acts: Array<{ act_id: string; title: string; active: boolean; notes: string }>;
};

type PlayScenesListResult = {
  scenes: Array<{
    scene_id: string;
    title: string;
    intent: string;
    status: string;
    time_horizon: string;
    notes: string;
  }>;
};

type PlayBeatsListResult = {
  beats: Array<{ beat_id: string; title: string; status: string; notes: string; link: string | null }>;
};

type PlayActsCreateResult = {
  created_act_id: string;
  acts: Array<{ act_id: string; title: string; active: boolean; notes: string }>;
};

type PlayScenesMutationResult = {
  scenes: PlayScenesListResult['scenes'];
};

type PlayBeatsMutationResult = {
  beats: PlayBeatsListResult['beats'];
};

type PlayKbListResult = {
  files: string[];
};

type PlayKbReadResult = {
  path: string;
  text: string;
};

type PlayKbWritePreviewResult = {
  path: string;
  exists: boolean;
  sha256_current: string;
  expected_sha256_current: string;
  sha256_new: string;
  diff: string;
};

type PlayKbWriteApplyResult = {
  ok: boolean;
  sha256_current: string;
};

class KernelError extends Error {
  code: number;

  constructor(message: string, code: number) {
    super(message);
    this.name = 'KernelError';
    this.code = code;
  }
}


async function kernelRequest(method: string, params: unknown): Promise<unknown> {
  const raw = await invoke('kernel_request', { method, params });
  const parsed = JsonRpcResponseSchema.parse(raw);
  if (parsed.error) {
    throw new KernelError(parsed.error.message, parsed.error.code);
  }
  return parsed.result;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

const REOS_ASCII = `
██████╗ ███████╗ ██████╗ ███████╗
██╔══██╗██╔════╝██╔═══██╗██╔════╝
██████╔╝█████╗  ██║   ██║███████╗
██╔══██╗██╔══╝  ██║   ██║╚════██║
██║  ██║███████╗╚██████╔╝███████║
╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝
`.trim();

function buildLoginScreen(onLogin: () => void) {
  const root = document.getElementById('app');
  if (!root) return;

  root.innerHTML = '';

  const screen = el('div');
  screen.className = 'login-screen';

  // ASCII Art Title
  const ascii = el('pre');
  ascii.className = 'login-ascii';
  ascii.textContent = REOS_ASCII;

  // Tagline
  const tagline = el('div');
  tagline.className = 'login-tagline';
  tagline.textContent = 'attention is labor';

  // Byline
  const byline = el('div');
  byline.className = 'login-byline';
  byline.textContent = 'Talking Rock';

  // Login Card
  const card = el('div');
  card.className = 'login-card';

  // Username field
  const usernameField = el('div');
  usernameField.className = 'login-field';
  const usernameLabel = el('label');
  usernameLabel.className = 'login-label';
  usernameLabel.textContent = 'Username';
  const usernameInput = el('input') as HTMLInputElement;
  usernameInput.className = 'login-input';
  usernameInput.type = 'text';
  usernameInput.placeholder = 'Enter your username';
  usernameField.appendChild(usernameLabel);
  usernameField.appendChild(usernameInput);

  // Password field
  const passwordField = el('div');
  passwordField.className = 'login-field';
  const passwordLabel = el('label');
  passwordLabel.className = 'login-label';
  passwordLabel.textContent = 'Password';
  const passwordInput = el('input') as HTMLInputElement;
  passwordInput.className = 'login-input';
  passwordInput.type = 'password';
  passwordInput.placeholder = 'Enter your password';
  passwordField.appendChild(passwordLabel);
  passwordField.appendChild(passwordInput);

  // Login button
  const loginBtn = el('button');
  loginBtn.className = 'login-btn';
  loginBtn.textContent = 'Sign In';

  // Recovery link
  const recovery = el('a');
  recovery.className = 'login-recovery';
  recovery.textContent = 'Forgot your credentials?';

  // Error message area
  const errorMsg = el('div');
  errorMsg.className = 'login-error';

  card.appendChild(usernameField);
  card.appendChild(passwordField);
  card.appendChild(loginBtn);
  card.appendChild(recovery);
  card.appendChild(errorMsg);

  screen.appendChild(ascii);
  screen.appendChild(tagline);
  screen.appendChild(byline);
  screen.appendChild(card);

  root.appendChild(screen);

  // Handle login
  const handleLogin = () => {
    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    if (!username) {
      errorMsg.textContent = 'Please enter your username';
      return;
    }
    if (!password) {
      errorMsg.textContent = 'Please enter your password';
      return;
    }

    // For now, accept any non-empty credentials
    // In a real app, this would validate against a backend
    errorMsg.textContent = '';
    onLogin();
  };

  loginBtn.addEventListener('click', handleLogin);
  passwordInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleLogin();
  });
  usernameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') passwordInput.focus();
  });

  // Handle recovery
  recovery.addEventListener('click', () => {
    errorMsg.textContent = 'Recovery feature coming soon...';
  });

  // Focus username input
  usernameInput.focus();
}

function buildUi() {
  const query = new URLSearchParams(window.location.search);
  if (query.get('view') === 'me') {
    void buildMeWindow();
    return;
  }

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

  const meHeader = el('div');
  meHeader.textContent = 'Me (The Play)';
  meHeader.style.marginTop = '12px';
  meHeader.style.fontWeight = '600';

  const meBtn = el('button');
  meBtn.textContent = 'Me';

  const actsHeader = el('div');
  actsHeader.textContent = 'Acts';
  actsHeader.style.marginTop = '12px';
  actsHeader.style.fontWeight = '600';

  const actsList = el('div');
  actsList.style.display = 'flex';
  actsList.style.flexDirection = 'column';
  actsList.style.gap = '6px';

  nav.appendChild(navTitle);
  nav.appendChild(meHeader);
  nav.appendChild(meBtn);
  nav.appendChild(actsHeader);
  nav.appendChild(actsList);

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

  let activeActId: string | null = null;
  let actsCache: PlayActsListResult['acts'] = [];
  let selectedSceneId: string | null = null;
  let selectedBeatId: string | null = null;

  let scenesCache: PlayScenesListResult['scenes'] = [];
  let beatsCache: PlayBeatsListResult['beats'] = [];

  let kbSelectedPath = 'kb.md';
  let kbTextDraft = '';
  let kbPreview: PlayKbWritePreviewResult | null = null;

  function showJsonInInspector(title: string, obj: unknown) {
    inspectionTitle.textContent = title;
    inspectionBody.innerHTML = '';
    const pre = el('pre');
    pre.style.margin = '0';
    pre.textContent = JSON.stringify(obj ?? null, null, 2);
    inspectionBody.appendChild(pre);
  }

  async function openMeWindow() {
    try {
      const existing = await WebviewWindow.getByLabel('me');
      if (existing) {
        await existing.setFocus();
        return;
      }
    } catch {
      // Best effort: if getByLabel fails, fall through and create a new window.
    }

    const w = new WebviewWindow('me', {
      title: 'Me — ReOS',
      url: '/?view=me',
      width: 900,
      height: 700
    });
    void w;
  }

  meBtn.addEventListener('click', () => void openMeWindow());

  function rowHeader(title: string) {
    const h = el('div');
    h.textContent = title;
    h.style.fontWeight = '600';
    h.style.margin = '10px 0 6px';
    return h;
  }

  function label(text: string) {
    const l = el('div');
    l.textContent = text;
    l.style.fontSize = '12px';
    l.style.opacity = '0.8';
    l.style.marginBottom = '4px';
    return l;
  }

  function textInput(value: string) {
    const i = el('input') as HTMLInputElement;
    i.type = 'text';
    i.value = value;
    i.style.width = '100%';
    i.style.boxSizing = 'border-box';
    i.style.padding = '8px 10px';
    i.style.border = '1px solid rgba(209, 213, 219, 0.7)';
    i.style.borderRadius = '10px';
    i.style.background = 'rgba(255, 255, 255, 0.55)';
    return i;
  }

  function textArea(value: string, heightPx = 90) {
    const t = el('textarea') as HTMLTextAreaElement;
    t.value = value;
    t.style.width = '100%';
    t.style.boxSizing = 'border-box';
    t.style.padding = '8px 10px';
    t.style.border = '1px solid rgba(209, 213, 219, 0.7)';
    t.style.borderRadius = '10px';
    t.style.background = 'rgba(255, 255, 255, 0.55)';
    t.style.minHeight = `${heightPx}px`;
    t.style.resize = 'vertical';
    return t;
  }

  function smallButton(text: string) {
    const b = el('button') as HTMLButtonElement;
    b.textContent = text;
    b.style.padding = '8px 10px';
    b.style.border = '1px solid rgba(209, 213, 219, 0.65)';
    b.style.borderRadius = '10px';
    b.style.background = 'rgba(255, 255, 255, 0.35)';
    return b;
  }

  async function refreshBeats(actId: string, sceneId: string) {
    const res = (await kernelRequest('play/beats/list', { act_id: actId, scene_id: sceneId })) as PlayBeatsListResult;
    beatsCache = res.beats ?? [];
  }

  async function refreshKbForSelection() {
    if (!activeActId) return;
    const sceneId = selectedSceneId ?? undefined;
    const beatId = selectedBeatId ?? undefined;

    const filesRes = (await kernelRequest('play/kb/list', {
      act_id: activeActId,
      scene_id: sceneId,
      beat_id: beatId
    })) as PlayKbListResult;

    const files = filesRes.files ?? [];
    if (files.length > 0 && !files.includes(kbSelectedPath)) {
      kbSelectedPath = files[0];
    }

    try {
      const readRes = (await kernelRequest('play/kb/read', {
        act_id: activeActId,
        scene_id: sceneId,
        beat_id: beatId,
        path: kbSelectedPath
      })) as PlayKbReadResult;
      kbTextDraft = readRes.text ?? '';
    } catch {
      // If missing, keep draft as-is (acts as a create).
    }
    kbPreview = null;
  }

  function renderPlayInspector() {
    inspectionTitle.textContent = 'The Play';
    inspectionBody.innerHTML = '';

    if (!activeActId) {
      const empty = el('div');
      empty.textContent = 'Create an Act to begin.';
      empty.style.opacity = '0.8';
      inspectionBody.appendChild(empty);

      inspectionBody.appendChild(rowHeader('Act'));
      const actCreateRow = el('div');
      actCreateRow.style.display = 'flex';
      actCreateRow.style.gap = '8px';
      const actNewTitle = textInput('');
      actNewTitle.placeholder = 'New act title';
      const actCreate = smallButton('Create');
      actCreateRow.appendChild(actNewTitle);
      actCreateRow.appendChild(actCreate);
      inspectionBody.appendChild(actCreateRow);

      actCreate.addEventListener('click', () => {
        void (async () => {
          const title = actNewTitle.value.trim();
          if (!title) return;
          const res = (await kernelRequest('play/acts/create', { title })) as PlayActsCreateResult;
          activeActId = res.created_act_id;
          selectedSceneId = null;
          selectedBeatId = null;
          await refreshActs();
          if (activeActId) await refreshScenes(activeActId);
        })();
      });
      return;
    }

    const activeAct = actsCache.find((a) => a.act_id === activeActId) ?? null;

    const status = el('div');
    status.style.fontSize = '12px';
    status.style.opacity = '0.85';
    status.style.marginBottom = '8px';
    status.textContent = selectedBeatId
      ? `Act → Scene → Beat`
      : selectedSceneId
        ? `Act → Scene`
        : `Act`;
    inspectionBody.appendChild(status);

    // Act editor + create
    inspectionBody.appendChild(rowHeader('Act'));

    const actTitle = textInput('');
    const actNotes = textArea('', 70);
    const actSave = smallButton('Save Act');
    const actCreateRow = el('div');
    actCreateRow.style.display = 'flex';
    actCreateRow.style.gap = '8px';
    const actNewTitle = textInput('');
    actNewTitle.placeholder = 'New act title';
    const actCreate = smallButton('Create');
    actCreateRow.appendChild(actNewTitle);
    actCreateRow.appendChild(actCreate);

    inspectionBody.appendChild(label('Title'));
    inspectionBody.appendChild(actTitle);
    inspectionBody.appendChild(label('Notes'));
    inspectionBody.appendChild(actNotes);
    inspectionBody.appendChild(actSave);
    inspectionBody.appendChild(label('Create new act'));
    inspectionBody.appendChild(actCreateRow);

    void (async () => {
      if (!activeAct) return;
      actTitle.value = activeAct.title ?? '';
      actNotes.value = activeAct.notes ?? '';
    })();

    actSave.addEventListener('click', () => {
      void (async () => {
        if (!activeActId) return;
        await kernelRequest('play/acts/update', {
          act_id: activeActId,
          title: actTitle.value,
          notes: actNotes.value
        });
        await refreshActs();
      })();
    });

    actCreate.addEventListener('click', () => {
      void (async () => {
        const title = actNewTitle.value.trim();
        if (!title) return;
        const res = (await kernelRequest('play/acts/create', { title })) as PlayActsCreateResult;
        activeActId = res.created_act_id;
        selectedSceneId = null;
        selectedBeatId = null;
        await refreshActs();
        if (activeActId) await refreshScenes(activeActId);
      })();
    });

    // Scenes section
    inspectionBody.appendChild(rowHeader('Scenes'));

    const sceneCreateTitle = textInput('');
    sceneCreateTitle.placeholder = 'New scene title';
    const sceneCreateBtn = smallButton('Create');
    const sceneCreateRow = el('div');
    sceneCreateRow.style.display = 'flex';
    sceneCreateRow.style.gap = '8px';
    sceneCreateRow.appendChild(sceneCreateTitle);
    sceneCreateRow.appendChild(sceneCreateBtn);
    inspectionBody.appendChild(sceneCreateRow);

    const scenesList = el('div');
    scenesList.style.display = 'flex';
    scenesList.style.flexDirection = 'column';
    scenesList.style.gap = '6px';
    scenesList.style.marginTop = '8px';
    inspectionBody.appendChild(scenesList);

    const sceneDetails = el('div');
    inspectionBody.appendChild(sceneDetails);

    const beatsDetails = el('div');
    inspectionBody.appendChild(beatsDetails);

    const kbSection = el('div');
    inspectionBody.appendChild(kbSection);

    const renderScenesList = () => {
      scenesList.innerHTML = '';
      if (scenesCache.length === 0) {
        const empty = el('div');
        empty.textContent = '(no scenes yet)';
        empty.style.opacity = '0.7';
        scenesList.appendChild(empty);
        return;
      }
      for (const s of scenesCache) {
        const btn = smallButton(selectedSceneId === s.scene_id ? `• ${s.title}` : s.title);
        btn.style.textAlign = 'left';
        btn.addEventListener('click', () => {
          selectedSceneId = s.scene_id;
          selectedBeatId = null;
          void (async () => {
            if (activeActId) {
              await refreshBeats(activeActId, s.scene_id);
              await refreshKbForSelection();
            }
            renderPlayInspector();
          })();
        });
        scenesList.appendChild(btn);
      }
    };

    const renderSceneDetails = () => {
      sceneDetails.innerHTML = '';
      if (!selectedSceneId) return;
      const s = scenesCache.find((x) => x.scene_id === selectedSceneId);
      if (!s) return;

      sceneDetails.appendChild(rowHeader('Scene Details'));
      const tTitle = textInput(s.title ?? '');
      const tIntent = textInput(s.intent ?? '');
      const tStatus = textInput(s.status ?? '');
      const tH = textInput(s.time_horizon ?? '');
      const tNotes = textArea(s.notes ?? '', 80);
      const save = smallButton('Save Scene');

      sceneDetails.appendChild(label('Title'));
      sceneDetails.appendChild(tTitle);
      sceneDetails.appendChild(label('Intent'));
      sceneDetails.appendChild(tIntent);
      sceneDetails.appendChild(label('Status'));
      sceneDetails.appendChild(tStatus);
      sceneDetails.appendChild(label('Time horizon'));
      sceneDetails.appendChild(tH);
      sceneDetails.appendChild(label('Notes'));
      sceneDetails.appendChild(tNotes);
      sceneDetails.appendChild(save);

      save.addEventListener('click', () => {
        void (async () => {
          if (!activeActId || !selectedSceneId) return;
          await kernelRequest('play/scenes/update', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            title: tTitle.value,
            intent: tIntent.value,
            status: tStatus.value,
            time_horizon: tH.value,
            notes: tNotes.value
          });
          await refreshScenes(activeActId);
          renderPlayInspector();
        })();
      });
    };

    const renderBeats = () => {
      beatsDetails.innerHTML = '';
      if (!activeActId || !selectedSceneId) return;

      beatsDetails.appendChild(rowHeader('Beats'));

      const createRow = el('div');
      createRow.style.display = 'flex';
      createRow.style.gap = '8px';
      const newTitle = textInput('');
      newTitle.placeholder = 'New beat title';
      const newStatus = textInput('');
      newStatus.placeholder = 'status';
      const createBtn = smallButton('Create');
      createRow.appendChild(newTitle);
      createRow.appendChild(newStatus);
      createRow.appendChild(createBtn);
      beatsDetails.appendChild(createRow);

      const list = el('div');
      list.style.display = 'flex';
      list.style.flexDirection = 'column';
      list.style.gap = '6px';
      list.style.marginTop = '8px';
      beatsDetails.appendChild(list);

      const detail = el('div');
      beatsDetails.appendChild(detail);

      const renderList = () => {
        list.innerHTML = '';
        if (beatsCache.length === 0) {
          const empty = el('div');
          empty.textContent = '(no beats yet)';
          empty.style.opacity = '0.7';
          list.appendChild(empty);
          return;
        }
        for (const b of beatsCache) {
          const btn = smallButton(selectedBeatId === b.beat_id ? `• ${b.title}` : b.title);
          btn.style.textAlign = 'left';
          btn.addEventListener('click', () => {
            selectedBeatId = b.beat_id;
            void (async () => {
              await refreshKbForSelection();
              renderPlayInspector();
            })();
          });
          list.appendChild(btn);
        }
      };

      const renderDetail = () => {
        detail.innerHTML = '';
        if (!selectedBeatId) return;
        const b = beatsCache.find((x) => x.beat_id === selectedBeatId);
        if (!b) return;

        detail.appendChild(rowHeader('Beat Details'));
        const tTitle = textInput(b.title ?? '');
        const tStatus = textInput(b.status ?? '');
        const tLink = textInput(b.link ?? '');
        const tNotes = textArea(b.notes ?? '', 80);
        const save = smallButton('Save Beat');

        detail.appendChild(label('Title'));
        detail.appendChild(tTitle);
        detail.appendChild(label('Status'));
        detail.appendChild(tStatus);
        detail.appendChild(label('Link'));
        detail.appendChild(tLink);
        detail.appendChild(label('Notes'));
        detail.appendChild(tNotes);
        detail.appendChild(save);

        save.addEventListener('click', () => {
          void (async () => {
            if (!activeActId || !selectedSceneId || !selectedBeatId) return;
            await kernelRequest('play/beats/update', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              title: tTitle.value,
              status: tStatus.value,
              link: tLink.value || null,
              notes: tNotes.value
            });
            await refreshBeats(activeActId, selectedSceneId);
            renderPlayInspector();
          })();
        });
      };

      createBtn.addEventListener('click', () => {
        void (async () => {
          const title = newTitle.value.trim();
          if (!title) return;
          await kernelRequest('play/beats/create', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            title,
            status: newStatus.value
          });
          await refreshBeats(activeActId, selectedSceneId);
          renderPlayInspector();
        })();
      });

      renderList();
      renderDetail();
    };

    const renderKb = () => {
      kbSection.innerHTML = '';
      kbSection.appendChild(rowHeader('Mini Knowledgebase'));

      const who = el('div');
      who.style.fontSize = '12px';
      who.style.opacity = '0.8';
      who.style.marginBottom = '6px';
      who.textContent = selectedBeatId
        ? `Beat KB`
        : selectedSceneId
          ? `Scene KB`
          : `Act KB`;
      kbSection.appendChild(who);

      const fileRow = el('div');
      fileRow.style.display = 'flex';
      fileRow.style.gap = '8px';
      const pathInput = textInput(kbSelectedPath);
      const loadBtn = smallButton('Load');
      fileRow.appendChild(pathInput);
      fileRow.appendChild(loadBtn);
      kbSection.appendChild(fileRow);

      const listWrap = el('div');
      listWrap.style.display = 'flex';
      listWrap.style.flexWrap = 'wrap';
      listWrap.style.gap = '6px';
      listWrap.style.margin = '8px 0';
      kbSection.appendChild(listWrap);

      const editor = textArea(kbTextDraft, 180);
      kbSection.appendChild(editor);

      const btnRow = el('div');
      btnRow.style.display = 'flex';
      btnRow.style.gap = '8px';
      btnRow.style.marginTop = '8px';
      const previewBtn = smallButton('Preview');
      const applyBtn = smallButton('Apply');
      btnRow.appendChild(previewBtn);
      btnRow.appendChild(applyBtn);
      kbSection.appendChild(btnRow);

      const diffPre = el('pre');
      diffPre.style.whiteSpace = 'pre-wrap';
      diffPre.style.fontSize = '12px';
      diffPre.style.marginTop = '8px';
      diffPre.style.padding = '8px 10px';
      diffPre.style.borderRadius = '10px';
      diffPre.style.border = '1px solid rgba(209, 213, 219, 0.65)';
      diffPre.style.background = 'rgba(255, 255, 255, 0.35)';
      diffPre.textContent = kbPreview ? kbPreview.diff : '';
      kbSection.appendChild(diffPre);

      const errorLine = el('div');
      errorLine.style.fontSize = '12px';
      errorLine.style.marginTop = '6px';
      errorLine.style.opacity = '0.85';
      kbSection.appendChild(errorLine);

      editor.addEventListener('input', () => {
        kbTextDraft = editor.value;
      });

      pathInput.addEventListener('input', () => {
        kbSelectedPath = pathInput.value;
      });

      loadBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          kbSelectedPath = pathInput.value || 'kb.md';
          await refreshKbForSelection();
          renderPlayInspector();
        })();
      });

      previewBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          if (!activeActId) return;
          try {
            const res = (await kernelRequest('play/kb/write_preview', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              path: kbSelectedPath,
              text: editor.value
            })) as PlayKbWritePreviewResult;
            kbPreview = res;
            diffPre.textContent = res.diff ?? '';
          } catch (e) {
            errorLine.textContent = `Preview error: ${String(e)}`;
          }
        })();
      });

      applyBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          if (!activeActId) return;
          if (!kbPreview) {
            errorLine.textContent = 'Preview first.';
            return;
          }
          try {
            const res = (await kernelRequest('play/kb/write_apply', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              path: kbSelectedPath,
              text: editor.value,
              expected_sha256_current: kbPreview.expected_sha256_current
            })) as PlayKbWriteApplyResult;
            void res;
            await refreshKbForSelection();
            renderPlayInspector();
          } catch (e) {
            if (e instanceof KernelError && e.code === -32009) {
              errorLine.textContent = 'Conflict: file changed since preview. Re-preview to continue.';
            } else {
              errorLine.textContent = `Apply error: ${String(e)}`;
            }
          }
        })();
      });

      // Render file pills if we already have them cached.
      void (async () => {
        try {
          if (!activeActId) return;
          const filesRes = (await kernelRequest('play/kb/list', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            beat_id: selectedBeatId
          })) as PlayKbListResult;
          const files = filesRes.files ?? [];
          listWrap.innerHTML = '';
          for (const f of files) {
            const pill = smallButton(f);
            pill.addEventListener('click', () => {
              kbSelectedPath = f;
              void (async () => {
                await refreshKbForSelection();
                renderPlayInspector();
              })();
            });
            listWrap.appendChild(pill);
          }
        } catch {
          // ignore
        }
      })();
    };

    sceneCreateBtn.addEventListener('click', () => {
      void (async () => {
        const title = sceneCreateTitle.value.trim();
        if (!title) return;
        await kernelRequest('play/scenes/create', { act_id: activeActId, title });
        await refreshScenes(activeActId);
        renderPlayInspector();
      })();
    });

    renderScenesList();
    renderSceneDetails();
    renderBeats();
    void (async () => {
      await refreshKbForSelection();
      renderKb();
    })();
  }

  async function refreshActs() {
    const res = (await kernelRequest('play/acts/list', {})) as PlayActsListResult;
    activeActId = res.active_act_id ?? null;
    actsCache = res.acts ?? [];

    actsList.innerHTML = '';
    for (const a of actsCache) {
      const btn = el('button');
      btn.textContent = a.act_id === activeActId ? `• ${a.title}` : a.title;
      btn.addEventListener('click', async () => {
        const setRes = (await kernelRequest('play/acts/set_active', { act_id: a.act_id })) as PlayActsListResult;
        activeActId = setRes.active_act_id ?? null;
        selectedSceneId = null;
        selectedBeatId = null;
        await refreshActs();
        if (activeActId) await refreshScenes(activeActId);
      });
      actsList.appendChild(btn);
    }

    if (actsCache.length === 0) {
      const empty = el('div');
      empty.textContent = '(no acts yet)';
      empty.style.opacity = '0.7';
      actsList.appendChild(empty);
    }

    renderPlayInspector();
  }

  async function refreshScenes(actId: string) {
    const res = (await kernelRequest('play/scenes/list', { act_id: actId })) as PlayScenesListResult;
    scenesCache = res.scenes ?? [];
    if (selectedSceneId && !scenesCache.some((s) => s.scene_id === selectedSceneId)) {
      selectedSceneId = null;
      selectedBeatId = null;
    }
    if (activeActId) {
      if (selectedSceneId) {
        await refreshBeats(activeActId, selectedSceneId);
      } else {
        beatsCache = [];
      }
    }
    renderPlayInspector();
  }


  async function onSend() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    append('user', text);

    // Immediately show an empty ReOS bubble with a thinking animation.
    const pending = appendThinking();

    // Ensure the browser paints the new bubbles before we start the kernel RPC.
    // Note: `requestAnimationFrame` alone can resume into a microtask that still
    // runs before paint, so we also yield a macrotask.
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));

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
      await refreshActs();
      if (activeActId) await refreshScenes(activeActId);
    } catch (e) {
      showJsonInInspector('Startup error', { error: String(e) });
    }
  })();
}

async function buildMeWindow() {
  const root = document.getElementById('app');
  if (!root) return;
  root.innerHTML = '';

  const wrap = el('div');
  wrap.style.padding = '12px';
  wrap.style.height = '100vh';
  wrap.style.boxSizing = 'border-box';
  wrap.style.overflow = 'auto';

  const title = el('div');
  title.textContent = 'Me (The Play)';
  title.style.fontWeight = '600';
  title.style.marginBottom = '10px';

  const body = el('pre');
  body.style.margin = '0';
  body.style.whiteSpace = 'pre-wrap';

  wrap.appendChild(title);
  wrap.appendChild(body);
  root.appendChild(wrap);

  try {
    const res = (await kernelRequest('play/me/read', {})) as PlayMeReadResult;
    body.textContent = res.markdown ?? '';
  } catch (e) {
    body.textContent = `Error: ${String(e)}`;
  }
}

// Entry point: Show login screen first, then main UI after successful login
function start() {
  const query = new URLSearchParams(window.location.search);

  // Secondary windows (like "Me") skip login
  if (query.get('view')) {
    buildUi();
    return;
  }

  // Show login screen for main window
  buildLoginScreen(() => {
    buildUi();
  });
}

start();
