/**
 * Code Mode View - Main execution view for watching code creation.
 *
 * This is the primary view when working with Code Mode, showing:
 * - Phase progression (Intent → Contract → Build → Verify → Complete)
 * - Current step details
 * - Debug/exploration state
 * - Output and file changes
 * - Contract criteria status
 *
 * The chat is integrated as a companion panel alongside this view.
 */

import { el, smallButton } from './dom';
import { kernelRequest } from './kernel';
import type { CodeExecutionState, CodeExecutionStep, ChatRespondResult } from './types';

// Escape HTML to prevent XSS in output display
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Phase icons for progress visualization
const PHASE_ICONS: Record<string, string> = {
  'pending': '⏳',
  'discovering_intent': '🔍',
  'building_contract': '📋',
  'decomposing': '🔨',
  'executing_step': '⚙️',
  'verifying': '✅',
  'debug': '🔧',
  'exploring': '🔀',
  'analyzing_gap': '📊',
  'completed': '✅',
  'failed': '❌',
  'approval': '⏸️',
};

// Phase descriptions for the phase timeline
// These are the semantic phases of Code Mode - backend sends phase KEY to match
const PHASES = [
  { key: 'intent', label: 'Intent', icon: '🔍', description: 'Understanding request' },
  { key: 'contract', label: 'Contract', icon: '📋', description: 'Defining criteria' },
  { key: 'decompose', label: 'Steps', icon: '🔨', description: 'Breaking into steps' },
  { key: 'approval', label: 'Approve', icon: '⏸️', description: 'Awaiting approval' },
  { key: 'build', label: 'Build', icon: '⚙️', description: 'Writing code' },
  { key: 'verify', label: 'Verify', icon: '✅', description: 'Running tests' },
  { key: 'integrate', label: 'Integrate', icon: '📥', description: 'Merging changes' },
  { key: 'complete', label: 'Done', icon: '🎉', description: 'Complete' },
];

// Map backend phase names to UI phase keys
const PHASE_KEY_MAP: Record<string, string> = {
  // Planning phases (from PLANNING_PHASES in streaming.py)
  'starting': 'intent',
  'analyzing_prompt': 'intent',
  'reading_context': 'intent',
  'scanning_codebase': 'intent',
  'synthesizing': 'intent',
  'generating_criteria': 'contract',
  'decomposing': 'decompose',
  'ready': 'approval',  // Plan ready for user approval
  // Execution phases (from PHASE_INFO in streaming.py)
  'pending': 'intent',
  'intent': 'intent',
  'contract': 'contract',
  'decompose': 'decompose',
  'build': 'build',
  'verify': 'verify',
  'debug': 'verify',  // Debug is part of verify cycle
  'exploring': 'verify',
  'integrate': 'integrate',
  'gap': 'integrate',
  'completed': 'complete',
  'complete': 'complete',
  'failed': 'complete',
  'error': 'complete',  // Error maps to complete for UI display
  'approval': 'approval',
  // Legacy/fallback
  'planning': 'intent',
};

export type CodeModeViewState = {
  executionState: Partial<CodeExecutionState> | null;
  isPolling: boolean;
  chatMessages: Array<{ role: 'user' | 'assistant'; content: string; data?: ChatRespondResult }>;
};

export type CodeModeViewCallbacks = {
  onSendMessage: (message: string) => Promise<ChatRespondResult>;
  onCancelExecution: () => Promise<void>;
  kernelRequest: typeof kernelRequest;
};

/**
 * Creates the Code Mode view with execution panel and chat sidebar.
 */
export function createCodeModeView(
  callbacks: CodeModeViewCallbacks
): {
  container: HTMLElement;
  updateExecutionState: (state: Partial<CodeExecutionState> | null) => void;
  addChatMessage: (role: 'user' | 'assistant', content: string, data?: ChatRespondResult) => void;
  clearChat: () => void;
  getChatInput: () => HTMLInputElement;
} {
  const state: CodeModeViewState = {
    executionState: null,
    isPolling: false,
    chatMessages: [],
  };

  // Main container - splits into execution panel and chat sidebar
  const container = el('div');
  container.className = 'code-mode-view';
  container.style.cssText = `
    display: flex;
    flex: 1;
    height: 100%;
    overflow: hidden;
  `;

  // ============ LEFT: Execution Panel (main view) ============
  const executionPanel = el('div');
  executionPanel.className = 'execution-panel';
  executionPanel.style.cssText = `
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-right: 1px solid rgba(255,255,255,0.1);
  `;

  // Execution header
  const execHeader = el('div');
  execHeader.className = 'exec-header';
  execHeader.style.cssText = `
    padding: 16px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.2);
  `;

  const execTitle = el('div');
  execTitle.style.cssText = `
    font-size: 18px;
    font-weight: 600;
    color: rgba(255,255,255,0.95);
    display: flex;
    align-items: center;
    gap: 10px;
  `;
  execTitle.innerHTML = `<span class="exec-status-icon">⚡</span> Code Mode`;
  execHeader.appendChild(execTitle);

  // Phase timeline (horizontal progress)
  const phaseTimeline = el('div');
  phaseTimeline.className = 'phase-timeline';
  phaseTimeline.style.cssText = `
    display: flex;
    gap: 4px;
    margin-top: 12px;
    padding: 8px 0;
  `;

  for (const phase of PHASES) {
    const phaseItem = el('div');
    phaseItem.className = `phase-item phase-${phase.key}`;
    phaseItem.style.cssText = `
      flex: 1;
      text-align: center;
      padding: 6px 4px;
      border-radius: 4px;
      font-size: 10px;
      background: rgba(255,255,255,0.05);
      color: rgba(255,255,255,0.5);
      transition: all 0.3s ease;
    `;
    phaseItem.innerHTML = `<div style="font-size: 14px">${phase.icon}</div><div>${phase.label}</div>`;
    phaseItem.title = phase.description;
    phaseTimeline.appendChild(phaseItem);
  }
  execHeader.appendChild(phaseTimeline);

  executionPanel.appendChild(execHeader);

  // Execution content (scrollable)
  const execContent = el('div');
  execContent.className = 'exec-content';
  execContent.style.cssText = `
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
  `;

  // Placeholder when no execution
  const execPlaceholder = el('div');
  execPlaceholder.className = 'exec-placeholder';
  execPlaceholder.style.cssText = `
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: rgba(255,255,255,0.4);
    text-align: center;
    padding: 40px;
  `;
  execPlaceholder.innerHTML = `
    <div style="font-size: 48px; margin-bottom: 16px;">🚀</div>
    <div style="font-size: 18px; font-weight: 500; margin-bottom: 8px;">Ready for Code Mode</div>
    <div style="font-size: 13px; max-width: 400px; line-height: 1.5;">
      Ask ReOS to build something in the chat panel.<br>
      When you approve a plan, you'll see every step of the execution here.
    </div>
  `;
  execContent.appendChild(execPlaceholder);

  executionPanel.appendChild(execContent);

  // ============ RIGHT: Chat Sidebar ============
  const chatSidebar = el('div');
  chatSidebar.className = 'chat-sidebar';
  chatSidebar.style.cssText = `
    width: 380px;
    display: flex;
    flex-direction: column;
    background: rgba(0,0,0,0.15);
  `;

  // Chat header
  const chatHeader = el('div');
  chatHeader.style.cssText = `
    padding: 12px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    font-weight: 600;
    font-size: 14px;
    color: rgba(255,255,255,0.9);
  `;
  chatHeader.textContent = 'Chat';
  chatSidebar.appendChild(chatHeader);

  // Chat messages
  const chatMessages = el('div');
  chatMessages.className = 'chat-messages';
  chatMessages.style.cssText = `
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  `;
  chatSidebar.appendChild(chatMessages);

  // Chat input
  const chatInputRow = el('div');
  chatInputRow.style.cssText = `
    padding: 12px;
    border-top: 1px solid rgba(255,255,255,0.1);
    display: flex;
    gap: 8px;
  `;

  const chatInput = el('input') as HTMLInputElement;
  chatInput.type = 'text';
  chatInput.placeholder = 'Ask ReOS to build something...';
  chatInput.style.cssText = `
    flex: 1;
    padding: 10px 12px;
    border: 1px solid rgba(255,255,255,0.2);
    border-radius: 8px;
    background: rgba(255,255,255,0.05);
    color: rgba(255,255,255,0.95);
    font-size: 13px;
    outline: none;
  `;

  const chatSendBtn = el('button');
  chatSendBtn.textContent = 'Send';
  chatSendBtn.style.cssText = `
    padding: 10px 16px;
    border: 1px solid rgba(59, 130, 246, 0.5);
    border-radius: 8px;
    background: rgba(59, 130, 246, 0.2);
    color: #60a5fa;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
  `;

  chatInputRow.appendChild(chatInput);
  chatInputRow.appendChild(chatSendBtn);
  chatSidebar.appendChild(chatInputRow);

  // Assemble
  container.appendChild(executionPanel);
  container.appendChild(chatSidebar);

  // ============ Render Functions ============

  function renderPhaseTimeline(execState: Partial<CodeExecutionState> | null) {
    const phaseItems = phaseTimeline.querySelectorAll('.phase-item') as NodeListOf<HTMLElement>;
    const isComplete = execState?.is_complete ?? false;
    const success = execState?.success ?? false;

    // Get current phase KEY from status and map to UI phase
    const backendPhase = execState?.status ?? 'pending';
    const uiPhaseKey = PHASE_KEY_MAP[backendPhase] ?? 'intent';
    const currentPhaseIndex = PHASES.findIndex(p => p.key === uiPhaseKey);

    phaseItems.forEach((item, idx) => {
      // Reset styles first
      item.style.fontWeight = 'normal';

      if (isComplete) {
        if (success) {
          // All phases green on success
          item.style.background = 'rgba(34, 197, 94, 0.2)';
          item.style.color = '#22c55e';
        } else {
          // Show progress up to failure point in red
          item.style.background = idx <= currentPhaseIndex ? 'rgba(239, 68, 68, 0.2)' : 'rgba(255,255,255,0.05)';
          item.style.color = idx <= currentPhaseIndex ? '#ef4444' : 'rgba(255,255,255,0.5)';
        }
      } else if (idx < currentPhaseIndex) {
        // Completed phases - green
        item.style.background = 'rgba(34, 197, 94, 0.2)';
        item.style.color = '#22c55e';
      } else if (idx === currentPhaseIndex) {
        // Current phase - blue and bold
        item.style.background = 'rgba(59, 130, 246, 0.3)';
        item.style.color = '#3b82f6';
        item.style.fontWeight = '600';
      } else {
        // Future phases - dim
        item.style.background = 'rgba(255,255,255,0.05)';
        item.style.color = 'rgba(255,255,255,0.5)';
      }
    });
  }

  function renderExecutionContent(execState: Partial<CodeExecutionState> | null) {
    execContent.innerHTML = '';

    if (!execState) {
      execContent.appendChild(execPlaceholder.cloneNode(true));
      return;
    }

    // Status section
    const statusSection = el('div');
    statusSection.style.cssText = `
      margin-bottom: 20px;
      padding: 16px;
      background: rgba(255,255,255,0.05);
      border-radius: 12px;
    `;

    const statusRow = el('div');
    statusRow.style.cssText = 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;';

    const statusText = el('div');
    statusText.style.cssText = 'font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px;';
    statusText.innerHTML = `<span>${PHASE_ICONS[execState.status ?? 'pending'] || '⏳'}</span> ${execState.phase_description ?? 'Loading...'}`;
    statusRow.appendChild(statusText);

    if (!execState.is_complete) {
      const cancelBtn = smallButton('Cancel');
      cancelBtn.style.cssText = `
        padding: 6px 12px;
        background: rgba(239, 68, 68, 0.2);
        border: 1px solid rgba(239, 68, 68, 0.5);
        border-radius: 6px;
        color: #ef4444;
        font-size: 12px;
        cursor: pointer;
      `;
      cancelBtn.addEventListener('click', () => void callbacks.onCancelExecution());
      statusRow.appendChild(cancelBtn);
    }

    statusSection.appendChild(statusRow);

    // Progress bar
    const progressBar = el('div');
    progressBar.style.cssText = `
      height: 8px;
      background: rgba(255,255,255,0.1);
      border-radius: 4px;
      overflow: hidden;
      margin-bottom: 8px;
    `;
    const progressFill = el('div');
    const progressPercent = Math.min(100, ((execState.steps_completed || 0) / Math.max(1, execState.steps_total || 1)) * 100);
    progressFill.style.cssText = `
      height: 100%;
      width: ${progressPercent}%;
      background: ${execState.is_complete ? (execState.success ? '#22c55e' : '#ef4444') : '#3b82f6'};
      transition: width 0.3s ease;
    `;
    progressBar.appendChild(progressFill);
    statusSection.appendChild(progressBar);

    // Progress text
    const progressText = el('div');
    progressText.style.cssText = 'font-size: 12px; color: rgba(255,255,255,0.6);';
    progressText.textContent = `Plan Step ${execState.steps_completed ?? 0}/${execState.steps_total ?? 0} • Loop ${execState.iteration ?? 0}/${execState.max_iterations ?? 0} • ${(execState.elapsed_seconds ?? 0).toFixed(1)}s`;
    statusSection.appendChild(progressText);

    execContent.appendChild(statusSection);

    // Current step
    if (execState.current_step) {
      const stepSection = el('div');
      stepSection.style.cssText = `
        margin-bottom: 20px;
        padding: 16px;
        background: rgba(59, 130, 246, 0.1);
        border: 1px solid rgba(59, 130, 246, 0.3);
        border-radius: 12px;
      `;

      const stepHeader = el('div');
      stepHeader.style.cssText = 'font-weight: 600; margin-bottom: 8px; font-size: 14px;';
      stepHeader.textContent = `Current Step`;
      stepSection.appendChild(stepHeader);

      const stepDesc = el('div');
      stepDesc.style.cssText = 'font-size: 13px; color: rgba(255,255,255,0.9);';
      stepDesc.textContent = execState.current_step.description;
      stepSection.appendChild(stepDesc);

      if (execState.current_step.target_file) {
        const targetFile = el('div');
        targetFile.style.cssText = 'font-size: 12px; color: rgba(255,255,255,0.6); margin-top: 8px; font-family: monospace;';
        targetFile.textContent = `📁 ${execState.current_step.target_file}`;
        stepSection.appendChild(targetFile);
      }

      execContent.appendChild(stepSection);
    }

    // Debug section
    if (execState.status === 'debug' && execState.debug_diagnosis) {
      const debugSection = el('div');
      debugSection.style.cssText = `
        margin-bottom: 20px;
        padding: 16px;
        background: rgba(245, 158, 11, 0.1);
        border: 1px solid rgba(245, 158, 11, 0.3);
        border-radius: 12px;
      `;

      const debugHeader = el('div');
      debugHeader.style.cssText = 'font-weight: 600; margin-bottom: 8px; font-size: 14px;';
      debugHeader.textContent = `🔧 Debug Attempt ${execState.debug_attempt}`;
      debugSection.appendChild(debugHeader);

      const rootCause = el('div');
      rootCause.style.cssText = 'font-size: 13px; color: rgba(255,255,255,0.9);';
      rootCause.textContent = execState.debug_diagnosis.root_cause;
      debugSection.appendChild(rootCause);

      const confidence = el('div');
      confidence.style.cssText = 'font-size: 12px; color: rgba(255,255,255,0.6); margin-top: 8px;';
      confidence.textContent = `Confidence: ${execState.debug_diagnosis.confidence}`;
      debugSection.appendChild(confidence);

      execContent.appendChild(debugSection);
    }

    // Exploration section
    const explorationResults = execState.exploration_results ?? [];
    if (execState.is_exploring || explorationResults.length > 0) {
      const exploreSection = el('div');
      exploreSection.style.cssText = `
        margin-bottom: 20px;
        padding: 16px;
        background: rgba(139, 92, 246, 0.1);
        border: 1px solid rgba(139, 92, 246, 0.3);
        border-radius: 12px;
      `;

      const exploreHeader = el('div');
      exploreHeader.style.cssText = 'font-weight: 600; margin-bottom: 8px; font-size: 14px;';
      exploreHeader.textContent = `🔀 Exploring Alternatives (${(execState.exploration_current_idx ?? 0) + 1}/${execState.exploration_alternatives_total ?? 0})`;
      exploreSection.appendChild(exploreHeader);

      if (execState.exploration_current_alternative) {
        const currentAlt = el('div');
        currentAlt.style.cssText = `
          background: rgba(139, 92, 246, 0.15);
          border-radius: 6px;
          padding: 10px;
          margin-bottom: 10px;
        `;
        currentAlt.innerHTML = `
          <div style="font-weight: 500; margin-bottom: 4px;">→ ${execState.exploration_current_alternative.approach}</div>
          <div style="font-size: 11px; color: rgba(255,255,255,0.6);">
            Score: ${(execState.exploration_current_alternative.score * 100).toFixed(0)}% • ${execState.exploration_current_alternative.rationale}
          </div>
        `;
        exploreSection.appendChild(currentAlt);
      }

      if (explorationResults.length > 0) {
        const resultsList = el('div');
        resultsList.style.cssText = 'display: flex; flex-wrap: wrap; gap: 6px;';
        for (const result of explorationResults) {
          const resultItem = el('span');
          resultItem.style.cssText = `
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 4px;
            background: ${result.success ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)'};
            color: ${result.success ? '#22c55e' : '#ef4444'};
          `;
          resultItem.textContent = `${result.success ? '✓' : '✗'} ${result.approach}`;
          resultsList.appendChild(resultItem);
        }
        exploreSection.appendChild(resultsList);
      }

      execContent.appendChild(exploreSection);
    }

    // Output section - PRIMARY VISIBILITY INTO WHAT'S HAPPENING
    const outputSection = el('div');
    outputSection.style.cssText = 'margin-bottom: 20px; flex: 1; display: flex; flex-direction: column;';

    const outputHeader = el('div');
    outputHeader.style.cssText = 'font-weight: 600; margin-bottom: 8px; font-size: 14px; display: flex; justify-content: space-between; align-items: center;';
    const outputLines = execState.output_lines ?? [];
    outputHeader.innerHTML = `<span>📄 Live Output</span><span style="font-size: 11px; color: rgba(255,255,255,0.5);">${outputLines.length} lines</span>`;
    outputSection.appendChild(outputHeader);

    const outputBox = el('div');
    outputBox.className = 'output-box';
    outputBox.style.cssText = `
      background: rgba(0,0,0,0.5);
      border-radius: 8px;
      padding: 12px;
      font-family: 'SF Mono', 'Fira Code', monospace;
      font-size: 12px;
      min-height: 300px;
      max-height: 500px;
      overflow-y: auto;
      overflow-x: hidden;
      white-space: pre-wrap;
      word-wrap: break-word;
      word-break: break-word;
      overflow-wrap: break-word;
      color: rgba(255,255,255,0.9);
      line-height: 1.5;
      border: 1px solid rgba(255,255,255,0.1);
    `;

    // Show all output (up to 100 lines) and auto-scroll to bottom
    const displayLines = outputLines.slice(-100);
    if (displayLines.length > 0) {
      // Color-code different types of output
      outputBox.innerHTML = displayLines.map(line => {
        if (line.startsWith('[') && line.includes(']')) {
          // Module output like [IntentDiscoverer]
          const match = line.match(/^\[([^\]]+)\]/);
          const module = match ? match[1] : '';
          const rest = line.slice(match ? match[0].length : 0);
          return `<span style="color: #60a5fa;">[${module}]</span>${escapeHtml(rest)}`;
        } else if (line.startsWith('  ▸')) {
          // Sub-activity
          return `<span style="color: #a78bfa;">${escapeHtml(line)}</span>`;
        } else if (line.startsWith('◆')) {
          // Phase transition
          return `<span style="color: #34d399; font-weight: 600;">${escapeHtml(line)}</span>`;
        } else if (line.toLowerCase().includes('error') || line.toLowerCase().includes('failed')) {
          return `<span style="color: #f87171;">${escapeHtml(line)}</span>`;
        } else if (line.toLowerCase().includes('success') || line.toLowerCase().includes('✓')) {
          return `<span style="color: #22c55e;">${escapeHtml(line)}</span>`;
        }
        return escapeHtml(line);
      }).join('\n');
    } else {
      outputBox.innerHTML = '<span style="opacity: 0.5;">Waiting for output...</span>';
    }
    outputSection.appendChild(outputBox);

    // Auto-scroll to bottom - use double RAF for reliable timing after layout
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        outputBox.scrollTop = outputBox.scrollHeight;
      });
    });

    execContent.appendChild(outputSection);

    // Files changed
    const filesChanged = execState.files_changed ?? [];
    if (filesChanged.length > 0) {
      const filesSection = el('div');
      filesSection.style.cssText = 'margin-bottom: 20px;';

      const filesHeader = el('div');
      filesHeader.style.cssText = 'font-weight: 600; margin-bottom: 8px; font-size: 14px;';
      filesHeader.textContent = '📂 Files Changed';
      filesSection.appendChild(filesHeader);

      const filesList = el('div');
      filesList.style.cssText = 'display: flex; flex-direction: column; gap: 4px;';
      for (const f of filesChanged) {
        const fileItem = el('div');
        fileItem.style.cssText = 'font-size: 12px; font-family: monospace; color: rgba(255,255,255,0.7);';
        fileItem.textContent = `• ${f}`;
        filesList.appendChild(fileItem);
      }
      filesSection.appendChild(filesList);

      execContent.appendChild(filesSection);
    }

    // Completion summary
    if (execState.is_complete) {
      const completeSection = el('div');
      completeSection.style.cssText = `
        padding: 16px;
        background: ${execState.success ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)'};
        border: 1px solid ${execState.success ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'};
        border-radius: 12px;
      `;

      const completeHeader = el('div');
      completeHeader.style.cssText = 'font-weight: 600; font-size: 16px; margin-bottom: 8px;';
      completeHeader.textContent = execState.success ? '✅ Execution Complete' : '❌ Execution Failed';
      completeSection.appendChild(completeHeader);

      if (execState.result_message) {
        const msg = el('div');
        msg.style.cssText = 'font-size: 13px; color: rgba(255,255,255,0.8);';
        msg.textContent = execState.result_message;
        completeSection.appendChild(msg);
      }

      if (execState.error) {
        const errMsg = el('div');
        errMsg.style.cssText = 'font-size: 12px; color: #ef4444; margin-top: 8px;';
        errMsg.textContent = execState.error;
        completeSection.appendChild(errMsg);
      }

      execContent.appendChild(completeSection);
    }
  }

  function renderChatMessage(role: 'user' | 'assistant', content: string, data?: ChatRespondResult) {
    const msgEl = el('div');
    msgEl.style.cssText = `
      padding: 10px 12px;
      border-radius: 14px;
      font-size: 13px;
      line-height: 1.35;
      max-width: 85%;
      color: rgba(255, 255, 255, 0.97);
      white-space: pre-wrap;
      box-shadow: 0 2px 10px rgba(17, 24, 39, 0.12);
      ${role === 'user'
        ? 'background: rgba(43, 108, 176, 0.74); align-self: flex-end; margin-left: auto;'
        : 'background: rgba(34, 197, 94, 0.72); align-self: flex-start;'}
    `;

    // Render markdown-like content simply
    msgEl.innerHTML = content
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');

    return msgEl;
  }

  function addChatMessageToView(role: 'user' | 'assistant', content: string, data?: ChatRespondResult) {
    state.chatMessages.push({ role, content, data });
    const msgEl = renderChatMessage(role, content, data);
    chatMessages.appendChild(msgEl);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // ============ Event Handlers ============

  async function handleSendMessage() {
    const message = chatInput.value.trim();
    if (!message) return;

    chatInput.value = '';
    chatInput.disabled = true;
    chatSendBtn.disabled = true;
    addChatMessageToView('user', message);

    // Add thinking indicator
    const thinkingEl = el('div');
    thinkingEl.className = 'thinking-indicator';
    thinkingEl.style.cssText = `
      padding: 10px 12px;
      border-radius: 14px;
      font-size: 13px;
      background: rgba(34, 197, 94, 0.3);
      align-self: flex-start;
      color: rgba(255, 255, 255, 0.7);
      display: flex;
      align-items: center;
      gap: 8px;
    `;
    thinkingEl.innerHTML = `
      <span class="thinking-dots" style="display: inline-flex; gap: 2px;">
        <span style="animation: pulse 1.4s infinite; animation-delay: 0s;">●</span>
        <span style="animation: pulse 1.4s infinite; animation-delay: 0.2s;">●</span>
        <span style="animation: pulse 1.4s infinite; animation-delay: 0.4s;">●</span>
      </span>
      <span>Thinking...</span>
    `;
    chatMessages.appendChild(thinkingEl);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
      const result = await callbacks.onSendMessage(message);
      thinkingEl.remove();
      addChatMessageToView('assistant', result.answer, result);
    } catch (err) {
      thinkingEl.remove();
      addChatMessageToView('assistant', `Error: ${err}`);
    } finally {
      chatInput.disabled = false;
      chatSendBtn.disabled = false;
      chatInput.focus();
    }
  }

  chatSendBtn.addEventListener('click', () => void handleSendMessage());
  chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') void handleSendMessage();
  });

  // ============ Public API ============

  function updateExecutionState(newState: Partial<CodeExecutionState> | null) {
    state.executionState = newState;
    renderPhaseTimeline(newState);
    renderExecutionContent(newState);

    // Update header icon
    const statusIcon = execTitle.querySelector('.exec-status-icon');
    if (statusIcon) {
      if (newState?.is_complete) {
        statusIcon.textContent = newState.success ? '✅' : '❌';
      } else if (newState) {
        statusIcon.textContent = PHASE_ICONS[newState.status ?? 'pending'] || '⚡';
      } else {
        statusIcon.textContent = '⚡';
      }
    }
  }

  function clearChat() {
    state.chatMessages = [];
    chatMessages.innerHTML = '';
  }

  function getChatInput() {
    return chatInput;
  }

  return {
    container,
    updateExecutionState,
    addChatMessage: addChatMessageToView,
    clearChat,
    getChatInput,
  };
}
