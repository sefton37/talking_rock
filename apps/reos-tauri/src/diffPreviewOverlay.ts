/**
 * Diff Preview Overlay - Modal view of code changes before applying.
 *
 * Shows a full-screen modal with all pending file changes, allowing users
 * to review, approve, or reject changes before they are applied.
 *
 * Features:
 * - Full diff view with syntax highlighting
 * - Apply/reject individual files or all at once
 * - Keyboard shortcuts: Enter to apply all, Escape to close
 * - Click outside to close
 */

import { el, smallButton } from './dom';
import { kernelRequest } from './kernel';
import type {
  DiffPreview,
  DiffFileChange,
  DiffHunk,
  CodeDiffApplyResult,
  CodeDiffRejectResult,
} from './types';

// Color scheme for diff display
const COLORS = {
  added: '#22c55e',
  addedBg: 'rgba(34, 197, 94, 0.15)',
  removed: '#ef4444',
  removedBg: 'rgba(239, 68, 68, 0.15)',
  context: '#9ca3af',
  header: '#60a5fa',
  filename: '#fbbf24',
  lineNumber: '#6b7280',
  border: '#374151',
  bgDark: '#1e1e1e',
  bgMedium: '#262626',
  bgLight: '#2d2d2d',
};

export interface DiffPreviewOverlay {
  element: HTMLElement;
  show: (preview: DiffPreview, sessionId: string, onComplete?: () => void) => void;
  hide: () => void;
  isVisible: () => boolean;
}

export function createDiffPreviewOverlay(): DiffPreviewOverlay {
  let currentPreview: DiffPreview | null = null;
  let currentSessionId: string | null = null;
  let onCompleteCallback: (() => void) | null = null;
  let remainingChanges: Set<string> = new Set();

  // Create overlay container
  const overlay = el('div');
  overlay.className = 'diff-preview-overlay';
  overlay.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.85);
    display: none;
    z-index: 1001;
    justify-content: center;
    align-items: center;
  `;

  // Modal container
  const modal = el('div');
  modal.className = 'diff-preview-modal';
  modal.style.cssText = `
    width: 900px;
    max-width: 95vw;
    max-height: 90vh;
    background: ${COLORS.bgDark};
    border-radius: 12px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
    border: 1px solid ${COLORS.border};
  `;

  // Header
  const header = el('div');
  header.style.cssText = `
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid ${COLORS.border};
    background: ${COLORS.bgMedium};
  `;

  const titleArea = el('div');
  titleArea.style.cssText = 'display: flex; align-items: center; gap: 12px;';

  const titleIcon = el('span');
  titleIcon.textContent = '📝';
  titleIcon.style.fontSize = '20px';

  const titleText = el('div');
  titleText.style.cssText = 'font-size: 18px; font-weight: 600; color: #fff;';
  titleText.textContent = 'Review Changes';

  const summaryText = el('span');
  summaryText.className = 'diff-summary';
  summaryText.style.cssText = `
    font-size: 13px;
    color: ${COLORS.context};
    margin-left: 12px;
    font-weight: 400;
  `;

  titleArea.appendChild(titleIcon);
  titleArea.appendChild(titleText);
  titleArea.appendChild(summaryText);

  const headerActions = el('div');
  headerActions.style.cssText = 'display: flex; align-items: center; gap: 12px;';

  // Keyboard hint
  const keyHint = el('span');
  keyHint.style.cssText = `
    font-size: 11px;
    color: ${COLORS.context};
    padding: 4px 8px;
    background: ${COLORS.bgLight};
    border-radius: 4px;
  `;
  keyHint.innerHTML = '<kbd style="font-family: monospace; color: #fff;">Enter</kbd> Apply All &nbsp; <kbd style="font-family: monospace; color: #fff;">Esc</kbd> Close';

  const closeBtn = el('button');
  closeBtn.textContent = '✕';
  closeBtn.style.cssText = `
    background: none;
    border: none;
    color: rgba(255,255,255,0.6);
    font-size: 20px;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: all 0.15s;
  `;
  closeBtn.addEventListener('mouseenter', () => {
    closeBtn.style.color = '#fff';
    closeBtn.style.background = 'rgba(255,255,255,0.1)';
  });
  closeBtn.addEventListener('mouseleave', () => {
    closeBtn.style.color = 'rgba(255,255,255,0.6)';
    closeBtn.style.background = 'none';
  });
  closeBtn.addEventListener('click', hide);

  headerActions.appendChild(keyHint);
  headerActions.appendChild(closeBtn);

  header.appendChild(titleArea);
  header.appendChild(headerActions);

  // Content area
  const content = el('div');
  content.className = 'diff-content';
  content.style.cssText = `
    flex: 1;
    overflow: auto;
    padding: 16px;
  `;

  // Footer with global actions
  const footer = el('div');
  footer.style.cssText = `
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    padding: 16px 20px;
    border-top: 1px solid ${COLORS.border};
    background: ${COLORS.bgMedium};
  `;

  const rejectAllBtn = el('button');
  rejectAllBtn.textContent = 'Reject All';
  rejectAllBtn.style.cssText = `
    padding: 10px 20px;
    background: transparent;
    border: 1px solid ${COLORS.removed};
    border-radius: 6px;
    color: ${COLORS.removed};
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  `;
  rejectAllBtn.addEventListener('mouseenter', () => {
    rejectAllBtn.style.background = COLORS.removedBg;
  });
  rejectAllBtn.addEventListener('mouseleave', () => {
    rejectAllBtn.style.background = 'transparent';
  });

  const applyAllBtn = el('button');
  applyAllBtn.textContent = 'Apply All Changes';
  applyAllBtn.style.cssText = `
    padding: 10px 24px;
    background: ${COLORS.added};
    border: none;
    border-radius: 6px;
    color: #000;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  `;
  applyAllBtn.addEventListener('mouseenter', () => {
    applyAllBtn.style.background = '#16a34a';
  });
  applyAllBtn.addEventListener('mouseleave', () => {
    applyAllBtn.style.background = COLORS.added;
  });

  footer.appendChild(rejectAllBtn);
  footer.appendChild(applyAllBtn);

  modal.appendChild(header);
  modal.appendChild(content);
  modal.appendChild(footer);
  overlay.appendChild(modal);

  // Event handlers
  rejectAllBtn.addEventListener('click', handleRejectAll);
  applyAllBtn.addEventListener('click', handleApplyAll);

  // Close on backdrop click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) hide();
  });

  // Keyboard handler
  function handleKeydown(e: KeyboardEvent) {
    if (overlay.style.display === 'none') return;

    if (e.key === 'Escape') {
      hide();
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleApplyAll();
    }
  }

  document.addEventListener('keydown', handleKeydown);

  async function handleApplyAll() {
    if (!currentSessionId) return;

    try {
      applyAllBtn.disabled = true;
      applyAllBtn.textContent = 'Applying...';

      await kernelRequest('code/diff/apply', {
        session_id: currentSessionId,
      }) as CodeDiffApplyResult;

      hide();
      if (onCompleteCallback) onCompleteCallback();
    } catch (err) {
      console.error('Failed to apply changes:', err);
      applyAllBtn.textContent = 'Apply All Changes';
      applyAllBtn.disabled = false;
    }
  }

  async function handleRejectAll() {
    if (!currentSessionId) return;

    try {
      rejectAllBtn.disabled = true;
      rejectAllBtn.textContent = 'Rejecting...';

      await kernelRequest('code/diff/reject', {
        session_id: currentSessionId,
      }) as CodeDiffRejectResult;

      hide();
      if (onCompleteCallback) onCompleteCallback();
    } catch (err) {
      console.error('Failed to reject changes:', err);
      rejectAllBtn.textContent = 'Reject All';
      rejectAllBtn.disabled = false;
    }
  }

  function renderHunk(hunk: DiffHunk): HTMLElement {
    const container = el('div');
    container.style.cssText = `
      font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
      font-size: 12px;
      line-height: 1.6;
      margin-bottom: 12px;
    `;

    // Hunk header
    const headerEl = el('div');
    headerEl.textContent = hunk.header;
    headerEl.style.cssText = `
      color: ${COLORS.header};
      padding: 6px 12px;
      background: rgba(96, 165, 250, 0.1);
      border-radius: 4px 4px 0 0;
      border-left: 3px solid ${COLORS.header};
    `;
    container.appendChild(headerEl);

    // Lines container
    const linesContainer = el('div');
    linesContainer.style.cssText = `
      border-left: 3px solid ${COLORS.border};
      background: ${COLORS.bgLight};
      border-radius: 0 0 4px 0;
    `;

    let oldLineNum = hunk.old_start;
    let newLineNum = hunk.new_start;

    for (const line of hunk.lines) {
      const lineEl = el('div');
      lineEl.style.cssText = `
        display: flex;
        align-items: stretch;
        min-height: 22px;
      `;

      // Line number column
      const lineNumEl = el('span');
      lineNumEl.style.cssText = `
        color: ${COLORS.lineNumber};
        width: 80px;
        text-align: right;
        padding: 0 12px;
        user-select: none;
        flex-shrink: 0;
        font-size: 11px;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        background: rgba(0,0,0,0.2);
      `;

      // Content column
      const contentEl = el('span');
      contentEl.style.cssText = `
        flex: 1;
        padding: 0 12px;
        white-space: pre;
        overflow-x: auto;
        display: flex;
        align-items: center;
      `;

      const prefix = line.charAt(0);
      const text = line.slice(1) || ' ';

      if (prefix === '+') {
        lineEl.style.backgroundColor = COLORS.addedBg;
        contentEl.style.color = COLORS.added;
        lineNumEl.textContent = `     ${newLineNum}`;
        newLineNum++;
      } else if (prefix === '-') {
        lineEl.style.backgroundColor = COLORS.removedBg;
        contentEl.style.color = COLORS.removed;
        lineNumEl.textContent = `${oldLineNum}     `;
        oldLineNum++;
      } else {
        contentEl.style.color = COLORS.context;
        lineNumEl.textContent = `${oldLineNum}  ${newLineNum}`;
        oldLineNum++;
        newLineNum++;
      }

      contentEl.textContent = prefix + text;
      lineEl.appendChild(lineNumEl);
      lineEl.appendChild(contentEl);
      linesContainer.appendChild(lineEl);
    }

    container.appendChild(linesContainer);
    return container;
  }

  function renderFileChange(change: DiffFileChange): HTMLElement {
    const container = el('div');
    container.className = 'diff-file-change';
    container.style.cssText = `
      margin-bottom: 20px;
      border: 1px solid ${COLORS.border};
      border-radius: 8px;
      overflow: hidden;
      background: ${COLORS.bgMedium};
    `;

    // File header
    const fileHeader = el('div');
    fileHeader.style.cssText = `
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      background: ${COLORS.bgLight};
      border-bottom: 1px solid ${COLORS.border};
    `;

    // File info
    const fileInfo = el('div');
    fileInfo.style.cssText = 'display: flex; align-items: center; gap: 10px;';

    // Change type badge
    const badge = el('span');
    badge.style.cssText = `
      font-size: 10px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    `;

    switch (change.change_type) {
      case 'create':
        badge.textContent = 'new';
        badge.style.backgroundColor = COLORS.addedBg;
        badge.style.color = COLORS.added;
        break;
      case 'delete':
        badge.textContent = 'del';
        badge.style.backgroundColor = COLORS.removedBg;
        badge.style.color = COLORS.removed;
        break;
      case 'modify':
        badge.textContent = 'mod';
        badge.style.backgroundColor = 'rgba(96, 165, 250, 0.15)';
        badge.style.color = COLORS.header;
        break;
      case 'rename':
        badge.textContent = 'ren';
        badge.style.backgroundColor = 'rgba(168, 85, 247, 0.15)';
        badge.style.color = '#a855f7';
        break;
    }
    fileInfo.appendChild(badge);

    // Filename
    const filenameEl = el('span');
    filenameEl.textContent = change.path;
    filenameEl.style.cssText = `
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      font-weight: 500;
      color: ${COLORS.filename};
    `;
    fileInfo.appendChild(filenameEl);

    // Stats
    const statsEl = el('span');
    statsEl.style.cssText = 'font-size: 12px; margin-left: 8px;';
    if (change.additions > 0) {
      const addSpan = el('span');
      addSpan.textContent = `+${change.additions}`;
      addSpan.style.color = COLORS.added;
      addSpan.style.marginRight = '6px';
      statsEl.appendChild(addSpan);
    }
    if (change.deletions > 0) {
      const delSpan = el('span');
      delSpan.textContent = `-${change.deletions}`;
      delSpan.style.color = COLORS.removed;
      statsEl.appendChild(delSpan);
    }
    fileInfo.appendChild(statsEl);

    fileHeader.appendChild(fileInfo);

    // Per-file actions
    const fileActions = el('div');
    fileActions.style.cssText = 'display: flex; gap: 8px;';

    const applyFileBtn = smallButton('Apply');
    applyFileBtn.style.cssText = `
      font-size: 11px;
      padding: 5px 12px;
      background: transparent;
      border: 1px solid ${COLORS.added};
      color: ${COLORS.added};
      border-radius: 4px;
      cursor: pointer;
    `;
    applyFileBtn.addEventListener('click', async () => {
      if (!currentSessionId) return;
      try {
        await kernelRequest('code/diff/apply', {
          session_id: currentSessionId,
          path: change.path,
        }) as CodeDiffApplyResult;
        remainingChanges.delete(change.path);
        container.remove();
        updateSummary();
        if (remainingChanges.size === 0) {
          hide();
          if (onCompleteCallback) onCompleteCallback();
        }
      } catch (err) {
        console.error('Failed to apply file:', err);
      }
    });

    const rejectFileBtn = smallButton('Reject');
    rejectFileBtn.style.cssText = `
      font-size: 11px;
      padding: 5px 12px;
      background: transparent;
      border: 1px solid ${COLORS.removed};
      color: ${COLORS.removed};
      border-radius: 4px;
      cursor: pointer;
    `;
    rejectFileBtn.addEventListener('click', async () => {
      if (!currentSessionId) return;
      try {
        await kernelRequest('code/diff/reject', {
          session_id: currentSessionId,
          path: change.path,
        }) as CodeDiffRejectResult;
        remainingChanges.delete(change.path);
        container.remove();
        updateSummary();
        if (remainingChanges.size === 0) {
          hide();
          if (onCompleteCallback) onCompleteCallback();
        }
      } catch (err) {
        console.error('Failed to reject file:', err);
      }
    });

    fileActions.appendChild(applyFileBtn);
    fileActions.appendChild(rejectFileBtn);
    fileHeader.appendChild(fileActions);

    container.appendChild(fileHeader);

    // Diff content
    const diffContent = el('div');
    diffContent.style.cssText = 'padding: 12px; max-height: 400px; overflow: auto;';

    if (change.binary) {
      const binaryNote = el('div');
      binaryNote.textContent = 'Binary file changed';
      binaryNote.style.cssText = `
        color: ${COLORS.context};
        font-style: italic;
        padding: 16px;
        text-align: center;
      `;
      diffContent.appendChild(binaryNote);
    } else if (change.hunks.length === 0 && change.change_type !== 'delete') {
      const noChanges = el('div');
      noChanges.textContent = 'No textual changes';
      noChanges.style.cssText = `
        color: ${COLORS.context};
        font-style: italic;
        padding: 16px;
        text-align: center;
      `;
      diffContent.appendChild(noChanges);
    } else {
      for (const hunk of change.hunks) {
        diffContent.appendChild(renderHunk(hunk));
      }
    }

    container.appendChild(diffContent);
    return container;
  }

  function updateSummary() {
    if (!currentPreview) return;

    const remaining = remainingChanges.size;
    const total = currentPreview.total_files;
    const applied = total - remaining;

    if (remaining === 0) {
      summaryText.textContent = 'All changes processed';
    } else if (applied > 0) {
      summaryText.textContent = `${remaining} of ${total} files remaining`;
    } else {
      let text = `${total} file(s)`;
      if (currentPreview.total_additions > 0) {
        text += ` +${currentPreview.total_additions}`;
      }
      if (currentPreview.total_deletions > 0) {
        text += ` -${currentPreview.total_deletions}`;
      }
      summaryText.textContent = text;
    }
  }

  function render() {
    content.innerHTML = '';

    if (!currentPreview || currentPreview.changes.length === 0) {
      const emptyState = el('div');
      emptyState.textContent = 'No changes to preview';
      emptyState.style.cssText = `
        color: ${COLORS.context};
        text-align: center;
        padding: 40px;
        font-size: 14px;
      `;
      content.appendChild(emptyState);
      return;
    }

    for (const change of currentPreview.changes) {
      content.appendChild(renderFileChange(change));
    }

    updateSummary();
  }

  function show(preview: DiffPreview, sessionId: string, onComplete?: () => void) {
    currentPreview = preview;
    currentSessionId = sessionId;
    onCompleteCallback = onComplete || null;
    remainingChanges = new Set(preview.changes.map(c => c.path));

    // Reset button states
    applyAllBtn.disabled = false;
    applyAllBtn.textContent = 'Apply All Changes';
    rejectAllBtn.disabled = false;
    rejectAllBtn.textContent = 'Reject All';

    render();
    overlay.style.display = 'flex';
  }

  function hide() {
    overlay.style.display = 'none';
    currentPreview = null;
    currentSessionId = null;
    onCompleteCallback = null;
    remainingChanges.clear();
  }

  function isVisible() {
    return overlay.style.display !== 'none';
  }

  return {
    element: overlay,
    show,
    hide,
    isVisible,
  };
}
