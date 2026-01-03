/**
 * ReOS Desktop Application - Natural Language Linux
 *
 * Main entry point for the Tauri-based desktop UI.
 * Communicates with the Python kernel via JSON-RPC over stdio.
 */
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';

import './style.css';

// Modular imports
import { kernelRequest, KernelError } from './kernel';
import { el, rowHeader, label, textInput, textArea, smallButton } from './dom';
import type {
  ChatRespondResult,
  SystemInfoResult,
  PlayMeReadResult,
  PlayActsListResult,
  PlayScenesListResult,
  PlayBeatsListResult,
  PlayActsCreateResult,
  PlayKbListResult,
  PlayKbReadResult,
  PlayKbWritePreviewResult,
  PlayKbWriteApplyResult
} from './types';

const REOS_ASCII = `
██████╗           ██████╗  ███████╗
██╔══██╗         ██╔═══██╗ ██╔════╝
██████╔╝  █████╗ ██║   ██║ ███████╗
██╔══██╗ ██╔══██╗██║   ██║ ╚════██║
██║  ██║ ███████║██║   ██║      ██║
██║  ██║ ██╔════╝██║   ██║      ██║
██║  ██║ ╚█████╗ ╚██████╔╝ ███████║
╚═╝  ╚═╝  ╚════╝  ╚═════╝  ╚══════╝
`.trim();

function buildLoginScreen(onLogin: () => void) {
  const root = document.getElementById('app');
  if (!root) return;

  root.innerHTML = '';

  const screen = el('div');
  screen.className = 'login-screen';

  // Top section (above center): ASCII art + tagline
  const top = el('div');
  top.className = 'login-top';

  // ASCII Art Title
  const ascii = el('pre');
  ascii.className = 'login-ascii';
  ascii.textContent = REOS_ASCII;

  // Tagline
  const tagline = el('div');
  tagline.className = 'login-tagline';
  tagline.textContent = 'attention is labor';

  top.appendChild(ascii);
  top.appendChild(tagline);

  // Byline - positioned at exact center of screen
  const byline = el('div');
  byline.className = 'login-byline';
  byline.textContent = 'Talking Rock';

  // Bottom section (below center): Login card
  const bottom = el('div');
  bottom.className = 'login-bottom';

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

  bottom.appendChild(card);

  screen.appendChild(top);
  screen.appendChild(byline);
  screen.appendChild(bottom);

  root.appendChild(screen);

  // Handle login with PAM authentication
  const handleLogin = async () => {
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

    // Disable inputs during authentication
    loginBtn.textContent = 'Authenticating...';
    loginBtn.disabled = true;
    usernameInput.disabled = true;
    passwordInput.disabled = true;
    errorMsg.textContent = '';

    try {
      await invoke('pam_authenticate', { username, password });
      onLogin();
    } catch (e) {
      errorMsg.textContent = 'Invalid credentials';
      loginBtn.textContent = 'Sign In';
      loginBtn.disabled = false;
      usernameInput.disabled = false;
      passwordInput.disabled = false;
      passwordInput.value = '';
      passwordInput.focus();
    }
  };

  loginBtn.addEventListener('click', () => void handleLogin());
  passwordInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') void handleLogin();
  });
  usernameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') passwordInput.focus();
  });

  // Handle recovery
  recovery.addEventListener('click', () => {
    errorMsg.textContent = 'Recovery feature coming soon...';
  });

  // Auto-fill username with current system user and focus appropriately
  void (async () => {
    try {
      const currentUser = await invoke('get_current_user') as string;
      usernameInput.value = currentUser;
      passwordInput.focus();
    } catch {
      usernameInput.focus();
    }
  })();
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
  nav.style.width = '280px';
  nav.style.borderRight = '1px solid #ddd';
  nav.style.padding = '12px';
  nav.style.overflow = 'auto';

  const navTitle = el('div');
  navTitle.textContent = 'ReOS for Linux';
  navTitle.style.fontWeight = '600';
  navTitle.style.fontSize = '16px';
  navTitle.style.marginBottom = '12px';

  // System Status Section
  const systemSection = el('div');
  systemSection.className = 'system-section';

  const systemHeader = el('div');
  systemHeader.textContent = 'System Status';
  systemHeader.style.fontWeight = '600';
  systemHeader.style.marginBottom = '8px';
  systemHeader.style.fontSize = '13px';
  systemHeader.style.color = '#666';

  const systemStatus = el('div');
  systemStatus.className = 'system-status';
  systemStatus.style.fontSize = '12px';
  systemStatus.style.marginBottom = '12px';
  systemStatus.innerHTML = '<span style="opacity: 0.6">Loading...</span>';

  systemSection.appendChild(systemHeader);
  systemSection.appendChild(systemStatus);

  // Quick Actions Section
  const actionsHeader = el('div');
  actionsHeader.textContent = 'Quick Actions';
  actionsHeader.style.fontWeight = '600';
  actionsHeader.style.marginTop = '12px';
  actionsHeader.style.marginBottom = '8px';
  actionsHeader.style.fontSize = '13px';
  actionsHeader.style.color = '#666';

  const quickActions = el('div');
  quickActions.className = 'quick-actions';
  quickActions.style.display = 'flex';
  quickActions.style.flexDirection = 'column';
  quickActions.style.gap = '4px';
  quickActions.style.marginBottom = '16px';

  const quickActionItems = [
    { label: 'System Info', prompt: 'Show me my system information' },
    { label: 'Disk Usage', prompt: 'How much disk space do I have?' },
    { label: 'Top Processes', prompt: 'What processes are using the most CPU?' },
    { label: 'Running Services', prompt: 'Show me the active services' },
    { label: 'Network Info', prompt: 'Show me my network interfaces and IP addresses' },
    { label: 'Update System', prompt: 'How do I update my system packages?' },
  ];

  for (const action of quickActionItems) {
    const btn = el('button');
    btn.className = 'quick-action-btn';
    btn.textContent = action.label;
    btn.style.textAlign = 'left';
    btn.style.padding = '8px 10px';
    btn.style.fontSize = '12px';
    btn.style.border = '1px solid rgba(209, 213, 219, 0.5)';
    btn.style.borderRadius = '8px';
    btn.style.background = 'rgba(255, 255, 255, 0.3)';
    btn.style.cursor = 'pointer';
    btn.addEventListener('click', () => {
      input.value = action.prompt;
      void onSend();
    });
    quickActions.appendChild(btn);
  }

  // The Play Section
  const meHeader = el('div');
  meHeader.textContent = 'The Play';
  meHeader.style.marginTop = '16px';
  meHeader.style.fontWeight = '600';
  meHeader.style.marginBottom = '8px';
  meHeader.style.fontSize = '13px';
  meHeader.style.color = '#666';

  const meBtn = el('button');
  meBtn.textContent = 'Open Me File';
  meBtn.style.padding = '8px 10px';
  meBtn.style.fontSize = '12px';
  meBtn.style.border = '1px solid rgba(209, 213, 219, 0.5)';
  meBtn.style.borderRadius = '8px';
  meBtn.style.background = 'rgba(255, 255, 255, 0.3)';

  const actsHeader = el('div');
  actsHeader.textContent = 'Acts';
  actsHeader.style.marginTop = '12px';
  actsHeader.style.fontWeight = '600';
  actsHeader.style.fontSize = '12px';

  const actsList = el('div');
  actsList.style.display = 'flex';
  actsList.style.flexDirection = 'column';
  actsList.style.gap = '4px';
  actsList.style.marginTop = '6px';

  nav.appendChild(navTitle);
  nav.appendChild(systemSection);
  nav.appendChild(actionsHeader);
  nav.appendChild(quickActions);
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
  input.placeholder = 'Ask me anything about your Linux system…';
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

  // Helper functions (rowHeader, label, textInput, textArea, smallButton)
  // are now imported from ./dom.ts

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
          if (!activeActId || !selectedSceneId) return;
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
        if (!title || !activeActId) return;
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

  // Load system status
  async function refreshSystemStatus() {
    try {
      const result = await kernelRequest('tools/call', {
        name: 'linux_system_info',
        arguments: {}
      }) as { result: SystemInfoResult };

      const info = result.result ?? result as unknown as SystemInfoResult;

      const memPercent = info.memory_percent ?? 0;
      const diskPercent = info.disk_percent ?? 0;
      const loadAvg = info.load_avg ?? [0, 0, 0];

      systemStatus.innerHTML = `
        <div style="margin-bottom: 6px"><strong>${info.hostname ?? 'Unknown'}</strong></div>
        <div style="opacity: 0.8; margin-bottom: 4px">${info.distro ?? 'Linux'}</div>
        <div style="margin-bottom: 4px">Kernel: ${info.kernel ?? 'N/A'}</div>
        <div style="margin-bottom: 4px">Uptime: ${info.uptime ?? 'N/A'}</div>
        <div style="margin-bottom: 6px">
          <div style="display: flex; justify-content: space-between;">
            <span>Memory</span>
            <span>${memPercent.toFixed(0)}%</span>
          </div>
          <div style="height: 4px; background: #e5e7eb; border-radius: 2px; overflow: hidden;">
            <div style="height: 100%; width: ${memPercent}%; background: ${memPercent > 80 ? '#ef4444' : memPercent > 60 ? '#f59e0b' : '#22c55e'}"></div>
          </div>
        </div>
        <div style="margin-bottom: 6px">
          <div style="display: flex; justify-content: space-between;">
            <span>Disk (/)</span>
            <span>${diskPercent.toFixed(0)}%</span>
          </div>
          <div style="height: 4px; background: #e5e7eb; border-radius: 2px; overflow: hidden;">
            <div style="height: 100%; width: ${diskPercent}%; background: ${diskPercent > 90 ? '#ef4444' : diskPercent > 75 ? '#f59e0b' : '#22c55e'}"></div>
          </div>
        </div>
        <div style="opacity: 0.8">Load: ${loadAvg[0].toFixed(2)} ${loadAvg[1].toFixed(2)} ${loadAvg[2].toFixed(2)}</div>
      `;
    } catch (e) {
      systemStatus.innerHTML = `<span style="opacity: 0.6">Could not load system info</span>`;
    }
  }

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // Ctrl+K or Cmd+K to focus input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      input.focus();
      input.select();
    }

    // Ctrl+L to clear chat
    if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
      e.preventDefault();
      chatLog.innerHTML = '';
      append('reos', 'Chat cleared. How can I help you with your Linux system?');
    }

    // Ctrl+R to refresh system status
    if ((e.ctrlKey || e.metaKey) && e.key === 'r' && !e.shiftKey) {
      e.preventDefault();
      void refreshSystemStatus();
    }

    // Escape to clear input
    if (e.key === 'Escape' && document.activeElement === input) {
      input.value = '';
      input.blur();
    }
  });

  // Initial load
  void (async () => {
    try {
      // Load system status
      await refreshSystemStatus();
      // Refresh system status every 30 seconds
      setInterval(() => void refreshSystemStatus(), 30000);

      await refreshActs();
      if (activeActId) await refreshScenes(activeActId);

      // Welcome message
      append('reos', 'Welcome to ReOS! I\'m your Linux assistant. Ask me anything about your system, or use the quick actions on the left. Keyboard shortcuts: Ctrl+K to focus, Ctrl+L to clear, Ctrl+R to refresh status.');
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
