/**
 * CAIRN View - Conversational interface for the Attention Minder.
 *
 * CAIRN surfaces what needs attention without being coercive:
 * - Priority-driven surfacing
 * - Calendar and time awareness
 * - Knowledge base queries
 * - Gentle nudges, never guilt-trips
 */

import { el } from './dom';
import type { ChatRespondResult } from './types';

interface CairnViewCallbacks {
  onSendMessage: (message: string) => Promise<void>;
  kernelRequest: <T>(method: string, params?: Record<string, unknown>) => Promise<T>;
}

interface CairnViewState {
  chatMessages: Array<{ role: 'user' | 'assistant'; content: string }>;
  surfacedItems: Array<{ title: string; reason: string; urgency: string }>;
}

/**
 * Creates the CAIRN conversational view.
 */
export function createCairnView(
  callbacks: CairnViewCallbacks
): {
  container: HTMLElement;
  addChatMessage: (role: 'user' | 'assistant', content: string) => void;
  clearChat: () => void;
  getChatInput: () => HTMLInputElement;
  updateSurfaced: (items: Array<{ title: string; reason: string; urgency: string }>) => void;
} {
  const state: CairnViewState = {
    chatMessages: [],
    surfacedItems: [],
  };

  // Main container
  const container = el('div');
  container.className = 'cairn-view';
  container.style.cssText = `
    display: flex;
    flex: 1;
    height: 100%;
    overflow: hidden;
  `;

  // ============ LEFT: Surfaced Items Panel ============
  const surfacedPanel = el('div');
  surfacedPanel.className = 'surfaced-panel';
  surfacedPanel.style.cssText = `
    width: 320px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-right: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.1);
  `;

  // Surfaced header
  const surfacedHeader = el('div');
  surfacedHeader.style.cssText = `
    padding: 16px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.2);
  `;

  const surfacedTitle = el('div');
  surfacedTitle.style.cssText = `
    font-size: 16px;
    font-weight: 600;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 8px;
  `;
  surfacedTitle.innerHTML = '🪨 What Needs Attention';

  const surfacedSubtitle = el('div');
  surfacedSubtitle.style.cssText = `
    font-size: 12px;
    color: rgba(255,255,255,0.5);
    margin-top: 4px;
  `;
  surfacedSubtitle.textContent = 'Surfaced by priority and time';

  surfacedHeader.appendChild(surfacedTitle);
  surfacedHeader.appendChild(surfacedSubtitle);

  // Surfaced items list
  const surfacedList = el('div');
  surfacedList.className = 'surfaced-list';
  surfacedList.style.cssText = `
    flex: 1;
    overflow-y: auto;
    padding: 12px;
  `;

  // Quick actions
  const quickActions = el('div');
  quickActions.style.cssText = `
    padding: 12px;
    border-top: 1px solid rgba(255,255,255,0.1);
    display: flex;
    flex-direction: column;
    gap: 8px;
  `;

  const actionButtons = [
    { label: "What's next?", icon: '🎯', action: "What should I focus on next?" },
    { label: "Today's plan", icon: '📅', action: "What's on my calendar today?" },
    { label: 'Waiting on', icon: '⏳', action: "What am I waiting on?" },
    { label: 'Stale items', icon: '📦', action: "What have I been neglecting?" },
  ];

  actionButtons.forEach(({ label, icon, action }) => {
    const btn = el('button');
    btn.innerHTML = `${icon} ${label}`;
    btn.style.cssText = `
      padding: 10px 12px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 6px;
      color: rgba(255,255,255,0.8);
      cursor: pointer;
      font-size: 12px;
      text-align: left;
      transition: background 0.2s;
    `;
    btn.addEventListener('mouseenter', () => {
      btn.style.background = 'rgba(255,255,255,0.1)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.background = 'rgba(255,255,255,0.05)';
    });
    btn.addEventListener('click', () => {
      callbacks.onSendMessage(action);
    });
    quickActions.appendChild(btn);
  });

  surfacedPanel.appendChild(surfacedHeader);
  surfacedPanel.appendChild(surfacedList);
  surfacedPanel.appendChild(quickActions);

  // ============ RIGHT: Chat Panel ============
  const chatPanel = el('div');
  chatPanel.className = 'chat-panel';
  chatPanel.style.cssText = `
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  `;

  // Chat header
  const chatHeader = el('div');
  chatHeader.style.cssText = `
    padding: 16px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.2);
  `;

  const chatTitle = el('div');
  chatTitle.style.cssText = `
    font-size: 16px;
    font-weight: 600;
    color: #fff;
  `;
  chatTitle.textContent = 'CAIRN';

  const chatSubtitle = el('div');
  chatSubtitle.style.cssText = `
    font-size: 12px;
    color: rgba(255,255,255,0.5);
    margin-top: 4px;
  `;
  chatSubtitle.textContent = 'Your attention minder';

  chatHeader.appendChild(chatTitle);
  chatHeader.appendChild(chatSubtitle);

  // Chat messages area
  const chatMessages = el('div');
  chatMessages.className = 'chat-messages';
  chatMessages.style.cssText = `
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  `;

  // Welcome message
  const welcomeMsg = el('div');
  welcomeMsg.style.cssText = `
    background: rgba(59, 130, 246, 0.1);
    border: 1px solid rgba(59, 130, 246, 0.2);
    border-radius: 12px;
    padding: 16px;
    color: rgba(255,255,255,0.9);
  `;
  welcomeMsg.innerHTML = `
    <div style="font-weight: 600; margin-bottom: 8px;">Welcome to CAIRN</div>
    <div style="font-size: 13px; line-height: 1.5; color: rgba(255,255,255,0.7);">
      I help you stay on top of what matters. Ask me about your priorities,
      what needs attention, or what you should focus on next.
    </div>
  `;
  chatMessages.appendChild(welcomeMsg);

  // Thunderbird integration prompt (shown if not connected)
  const thunderbirdPrompt = el('div');
  thunderbirdPrompt.style.cssText = `
    background: rgba(245, 158, 11, 0.1);
    border: 1px solid rgba(245, 158, 11, 0.3);
    border-radius: 12px;
    padding: 16px;
    color: rgba(255,255,255,0.9);
    display: none;
  `;
  thunderbirdPrompt.innerHTML = `
    <div style="display: flex; align-items: flex-start; gap: 12px;">
      <span style="font-size: 24px;">📧</span>
      <div style="flex: 1;">
        <div style="font-weight: 600; margin-bottom: 6px; color: #f59e0b;">Connect Thunderbird?</div>
        <div style="font-size: 13px; line-height: 1.5; color: rgba(255,255,255,0.7); margin-bottom: 12px;">
          CAIRN can integrate with Thunderbird to help manage your calendar events and contacts.
          This enables time-aware surfacing and contact-linked knowledge items.
        </div>
        <div style="font-size: 12px; color: rgba(255,255,255,0.5);">
          Install <a href="https://www.thunderbird.net" target="_blank" style="color: #60a5fa;">Thunderbird</a> and create a profile to enable this feature.
        </div>
      </div>
    </div>
  `;
  chatMessages.appendChild(thunderbirdPrompt);

  // Check Thunderbird status on load
  void (async () => {
    try {
      const status = await callbacks.kernelRequest<{ available: boolean; message?: string }>('cairn/thunderbird/status', {});
      if (!status.available) {
        thunderbirdPrompt.style.display = 'block';
      }
    } catch (e) {
      // Silently ignore - Thunderbird check is optional
      console.log('Thunderbird status check failed:', e);
    }
  })();

  // Chat input area
  const inputArea = el('div');
  inputArea.style.cssText = `
    padding: 16px;
    border-top: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.1);
  `;

  const inputRow = el('div');
  inputRow.style.cssText = `
    display: flex;
    gap: 8px;
  `;

  const chatInput = el('input') as HTMLInputElement;
  chatInput.type = 'text';
  chatInput.placeholder = 'Ask CAIRN anything...';
  chatInput.style.cssText = `
    flex: 1;
    padding: 12px 16px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    color: #fff;
    font-size: 14px;
    outline: none;
  `;

  const sendBtn = el('button');
  sendBtn.textContent = 'Send';
  sendBtn.style.cssText = `
    padding: 12px 20px;
    background: #3b82f6;
    border: none;
    border-radius: 8px;
    color: #fff;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s;
  `;

  const handleSend = async () => {
    const message = chatInput.value.trim();
    if (!message) return;

    chatInput.value = '';
    addChatMessage('user', message);
    await callbacks.onSendMessage(message);
  };

  chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleSend();
  });
  sendBtn.addEventListener('click', handleSend);

  inputRow.appendChild(chatInput);
  inputRow.appendChild(sendBtn);
  inputArea.appendChild(inputRow);

  chatPanel.appendChild(chatHeader);
  chatPanel.appendChild(chatMessages);
  chatPanel.appendChild(inputArea);

  // Assemble container
  container.appendChild(surfacedPanel);
  container.appendChild(chatPanel);

  // ============ Functions ============

  function renderChatMessage(role: 'user' | 'assistant', content: string): HTMLElement {
    const msgEl = el('div');
    msgEl.style.cssText = `
      max-width: 85%;
      padding: 12px 16px;
      border-radius: 12px;
      font-size: 14px;
      line-height: 1.5;
      ${role === 'user'
        ? 'background: #3b82f6; color: #fff; align-self: flex-end; margin-left: auto;'
        : 'background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.9); align-self: flex-start;'
      }
    `;
    msgEl.textContent = content;
    return msgEl;
  }

  function addChatMessage(role: 'user' | 'assistant', content: string): void {
    state.chatMessages.push({ role, content });
    const msgEl = renderChatMessage(role, content);
    chatMessages.appendChild(msgEl);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function clearChat(): void {
    state.chatMessages = [];
    chatMessages.innerHTML = '';
    chatMessages.appendChild(welcomeMsg);
  }

  function getChatInput(): HTMLInputElement {
    return chatInput;
  }

  function updateSurfaced(items: Array<{ title: string; reason: string; urgency: string }>): void {
    state.surfacedItems = items;
    surfacedList.innerHTML = '';

    if (items.length === 0) {
      const emptyMsg = el('div');
      emptyMsg.style.cssText = `
        text-align: center;
        padding: 20px;
        color: rgba(255,255,255,0.4);
        font-size: 13px;
      `;
      emptyMsg.textContent = 'Nothing surfaced yet';
      surfacedList.appendChild(emptyMsg);
      return;
    }

    items.forEach(item => {
      const itemEl = el('div');
      itemEl.style.cssText = `
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
        cursor: pointer;
        transition: background 0.2s;
      `;

      const urgencyColor = item.urgency === 'critical' ? '#ef4444'
        : item.urgency === 'high' ? '#f97316'
        : item.urgency === 'medium' ? '#eab308'
        : '#22c55e';

      itemEl.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
          <span style="width: 8px; height: 8px; border-radius: 50%; background: ${urgencyColor};"></span>
          <span style="font-weight: 500; color: #fff; font-size: 13px;">${item.title}</span>
        </div>
        <div style="font-size: 12px; color: rgba(255,255,255,0.5); padding-left: 16px;">
          ${item.reason}
        </div>
      `;

      itemEl.addEventListener('mouseenter', () => {
        itemEl.style.background = 'rgba(255,255,255,0.08)';
      });
      itemEl.addEventListener('mouseleave', () => {
        itemEl.style.background = 'rgba(255,255,255,0.05)';
      });

      surfacedList.appendChild(itemEl);
    });
  }

  return {
    container,
    addChatMessage,
    clearChat,
    getChatInput,
    updateSurfaced,
  };
}
