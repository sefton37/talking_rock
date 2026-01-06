/**
 * Diff Preview Component for Code Mode.
 *
 * Displays file changes with syntax-highlighted diffs, allowing users
 * to approve or reject changes before they are applied.
 */

import { el, smallButton } from './dom';
import type {
  DiffPreview,
  DiffFileChange,
  DiffHunk,
  CodeDiffApplyResult,
  CodeDiffRejectResult,
} from './types';
import { kernelRequest } from './kernel';

// Color scheme for diff display
const COLORS = {
  added: '#22c55e',        // Green for additions
  addedBg: 'rgba(34, 197, 94, 0.15)',
  removed: '#ef4444',      // Red for deletions
  removedBg: 'rgba(239, 68, 68, 0.15)',
  context: '#6b7280',      // Gray for context lines
  header: '#3b82f6',       // Blue for hunk headers
  filename: '#f59e0b',     // Amber for filenames
  lineNumber: '#9ca3af',   // Light gray for line numbers
};

/**
 * Render a diff hunk with line numbers and syntax highlighting.
 */
function renderHunk(hunk: DiffHunk): HTMLElement {
  const container = el('div');
  container.style.fontFamily = 'monospace';
  container.style.fontSize = '12px';
  container.style.lineHeight = '1.5';
  container.style.marginBottom = '8px';

  // Hunk header
  const headerEl = el('div');
  headerEl.textContent = hunk.header;
  headerEl.style.color = COLORS.header;
  headerEl.style.padding = '4px 8px';
  headerEl.style.backgroundColor = 'rgba(59, 130, 246, 0.1)';
  headerEl.style.borderRadius = '4px 4px 0 0';
  container.appendChild(headerEl);

  // Lines container
  const linesContainer = el('div');
  linesContainer.style.borderLeft = '3px solid rgba(0, 0, 0, 0.1)';
  linesContainer.style.paddingLeft = '8px';

  let oldLineNum = hunk.old_start;
  let newLineNum = hunk.new_start;

  for (const line of hunk.lines) {
    const lineEl = el('div');
    lineEl.style.whiteSpace = 'pre';
    lineEl.style.display = 'flex';
    lineEl.style.alignItems = 'flex-start';

    // Line number column
    const lineNumEl = el('span');
    lineNumEl.style.color = COLORS.lineNumber;
    lineNumEl.style.width = '70px';
    lineNumEl.style.textAlign = 'right';
    lineNumEl.style.paddingRight = '8px';
    lineNumEl.style.userSelect = 'none';
    lineNumEl.style.flexShrink = '0';

    // Content column
    const contentEl = el('span');
    contentEl.style.flex = '1';
    contentEl.style.overflow = 'hidden';
    contentEl.style.textOverflow = 'ellipsis';

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

/**
 * Render a single file change with its hunks.
 */
function renderFileChange(
  change: DiffFileChange,
  sessionId: string,
  onApply: () => void,
  onReject: () => void
): HTMLElement {
  const container = el('div');
  container.style.marginBottom = '16px';
  container.style.border = '1px solid rgba(0, 0, 0, 0.15)';
  container.style.borderRadius = '8px';
  container.style.overflow = 'hidden';
  container.style.backgroundColor = 'rgba(255, 255, 255, 0.6)';

  // File header
  const header = el('div');
  header.style.display = 'flex';
  header.style.alignItems = 'center';
  header.style.justifyContent = 'space-between';
  header.style.padding = '8px 12px';
  header.style.backgroundColor = 'rgba(0, 0, 0, 0.03)';
  header.style.borderBottom = '1px solid rgba(0, 0, 0, 0.1)';

  // File info (left side)
  const fileInfo = el('div');
  fileInfo.style.display = 'flex';
  fileInfo.style.alignItems = 'center';
  fileInfo.style.gap = '8px';

  // Change type badge
  const badge = el('span');
  badge.style.fontSize = '10px';
  badge.style.fontWeight = '600';
  badge.style.padding = '2px 6px';
  badge.style.borderRadius = '4px';
  badge.style.textTransform = 'uppercase';

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
      badge.style.backgroundColor = 'rgba(59, 130, 246, 0.15)';
      badge.style.color = '#3b82f6';
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
  filenameEl.style.fontFamily = 'monospace';
  filenameEl.style.fontSize = '13px';
  filenameEl.style.fontWeight = '500';
  filenameEl.style.color = COLORS.filename;
  fileInfo.appendChild(filenameEl);

  // Stats
  const statsEl = el('span');
  statsEl.style.fontSize = '11px';
  statsEl.style.marginLeft = '8px';
  if (change.additions > 0) {
    const addSpan = el('span');
    addSpan.textContent = `+${change.additions}`;
    addSpan.style.color = COLORS.added;
    addSpan.style.marginRight = '4px';
    statsEl.appendChild(addSpan);
  }
  if (change.deletions > 0) {
    const delSpan = el('span');
    delSpan.textContent = `-${change.deletions}`;
    delSpan.style.color = COLORS.removed;
    statsEl.appendChild(delSpan);
  }
  fileInfo.appendChild(statsEl);

  header.appendChild(fileInfo);

  // Action buttons (right side)
  const actions = el('div');
  actions.style.display = 'flex';
  actions.style.gap = '6px';

  const applyBtn = smallButton('Apply');
  applyBtn.style.fontSize = '11px';
  applyBtn.style.padding = '4px 8px';
  applyBtn.style.backgroundColor = 'rgba(34, 197, 94, 0.2)';
  applyBtn.style.borderColor = COLORS.added;
  applyBtn.onclick = async () => {
    try {
      await kernelRequest('code/diff/apply', {
        session_id: sessionId,
        path: change.path,
      }) as CodeDiffApplyResult;
      onApply();
    } catch (err) {
      console.error('Failed to apply change:', err);
    }
  };

  const rejectBtn = smallButton('Reject');
  rejectBtn.style.fontSize = '11px';
  rejectBtn.style.padding = '4px 8px';
  rejectBtn.style.backgroundColor = 'rgba(239, 68, 68, 0.2)';
  rejectBtn.style.borderColor = COLORS.removed;
  rejectBtn.onclick = async () => {
    try {
      await kernelRequest('code/diff/reject', {
        session_id: sessionId,
        path: change.path,
      }) as CodeDiffRejectResult;
      onReject();
    } catch (err) {
      console.error('Failed to reject change:', err);
    }
  };

  actions.appendChild(applyBtn);
  actions.appendChild(rejectBtn);
  header.appendChild(actions);
  container.appendChild(header);

  // Diff content
  const diffContent = el('div');
  diffContent.style.padding = '8px 12px';
  diffContent.style.maxHeight = '400px';
  diffContent.style.overflow = 'auto';

  if (change.binary) {
    const binaryNote = el('div');
    binaryNote.textContent = 'Binary file changed';
    binaryNote.style.color = COLORS.context;
    binaryNote.style.fontStyle = 'italic';
    binaryNote.style.padding = '12px';
    diffContent.appendChild(binaryNote);
  } else if (change.hunks.length === 0 && change.change_type !== 'delete') {
    // No changes (identical content)
    const noChanges = el('div');
    noChanges.textContent = 'No changes';
    noChanges.style.color = COLORS.context;
    noChanges.style.fontStyle = 'italic';
    noChanges.style.padding = '12px';
    diffContent.appendChild(noChanges);
  } else {
    for (const hunk of change.hunks) {
      diffContent.appendChild(renderHunk(hunk));
    }
  }

  container.appendChild(diffContent);
  return container;
}

/**
 * Render the complete diff preview with all file changes.
 */
export function renderDiffPreview(
  preview: DiffPreview,
  sessionId: string,
  onComplete: () => void
): HTMLElement {
  const container = el('div');
  container.className = 'diff-preview';
  container.style.padding = '12px';
  container.style.backgroundColor = 'rgba(248, 250, 252, 0.95)';
  container.style.borderRadius = '12px';
  container.style.marginTop = '12px';
  container.style.marginBottom = '12px';
  container.style.border = '1px solid rgba(0, 0, 0, 0.1)';

  // Header
  const header = el('div');
  header.style.display = 'flex';
  header.style.justifyContent = 'space-between';
  header.style.alignItems = 'center';
  header.style.marginBottom = '12px';

  const title = el('div');
  title.style.fontWeight = '600';
  title.style.fontSize = '14px';
  title.innerHTML = `<span style="color: ${COLORS.header}">Changes Preview</span>`;

  const summary = el('span');
  summary.style.fontSize = '12px';
  summary.style.marginLeft = '12px';
  summary.style.color = COLORS.context;
  summary.textContent = `${preview.total_files} file(s)`;
  if (preview.total_additions > 0) {
    summary.innerHTML += ` <span style="color: ${COLORS.added}">+${preview.total_additions}</span>`;
  }
  if (preview.total_deletions > 0) {
    summary.innerHTML += ` <span style="color: ${COLORS.removed}">-${preview.total_deletions}</span>`;
  }
  title.appendChild(summary);
  header.appendChild(title);

  // Global actions
  const globalActions = el('div');
  globalActions.style.display = 'flex';
  globalActions.style.gap = '8px';

  const applyAllBtn = smallButton('Apply All');
  applyAllBtn.style.backgroundColor = 'rgba(34, 197, 94, 0.25)';
  applyAllBtn.style.borderColor = COLORS.added;
  applyAllBtn.onclick = async () => {
    try {
      await kernelRequest('code/diff/apply', {
        session_id: sessionId,
      }) as CodeDiffApplyResult;
      onComplete();
    } catch (err) {
      console.error('Failed to apply all changes:', err);
    }
  };

  const rejectAllBtn = smallButton('Reject All');
  rejectAllBtn.style.backgroundColor = 'rgba(239, 68, 68, 0.25)';
  rejectAllBtn.style.borderColor = COLORS.removed;
  rejectAllBtn.onclick = async () => {
    try {
      await kernelRequest('code/diff/reject', {
        session_id: sessionId,
      }) as CodeDiffRejectResult;
      onComplete();
    } catch (err) {
      console.error('Failed to reject all changes:', err);
    }
  };

  globalActions.appendChild(applyAllBtn);
  globalActions.appendChild(rejectAllBtn);
  header.appendChild(globalActions);
  container.appendChild(header);

  // File changes
  const changesContainer = el('div');
  changesContainer.style.maxHeight = '600px';
  changesContainer.style.overflow = 'auto';

  let remainingChanges = new Set(preview.changes.map((c) => c.path));

  const refreshPreview = () => {
    if (remainingChanges.size === 0) {
      onComplete();
    }
  };

  for (const change of preview.changes) {
    const changeEl = renderFileChange(
      change,
      sessionId,
      () => {
        remainingChanges.delete(change.path);
        changeEl.remove();
        refreshPreview();
      },
      () => {
        remainingChanges.delete(change.path);
        changeEl.remove();
        refreshPreview();
      }
    );
    changesContainer.appendChild(changeEl);
  }

  container.appendChild(changesContainer);
  return container;
}

/**
 * Create a collapsed diff preview that can be expanded.
 */
export function renderCollapsedDiffPreview(
  preview: DiffPreview,
  sessionId: string,
  onComplete: () => void
): HTMLElement {
  const container = el('div');
  container.className = 'diff-preview-collapsed';
  container.style.padding = '10px 14px';
  container.style.backgroundColor = 'rgba(59, 130, 246, 0.08)';
  container.style.borderRadius = '10px';
  container.style.marginTop = '10px';
  container.style.border = '1px solid rgba(59, 130, 246, 0.2)';
  container.style.cursor = 'pointer';

  const header = el('div');
  header.style.display = 'flex';
  header.style.justifyContent = 'space-between';
  header.style.alignItems = 'center';

  const info = el('div');
  info.style.display = 'flex';
  info.style.alignItems = 'center';
  info.style.gap = '8px';

  const icon = el('span');
  icon.textContent = '📝';
  info.appendChild(icon);

  const text = el('span');
  text.style.fontSize = '13px';
  text.innerHTML = `<strong>${preview.total_files} file(s)</strong> changed`;
  if (preview.total_additions > 0) {
    text.innerHTML += ` <span style="color: ${COLORS.added}">+${preview.total_additions}</span>`;
  }
  if (preview.total_deletions > 0) {
    text.innerHTML += ` <span style="color: ${COLORS.removed}">-${preview.total_deletions}</span>`;
  }
  info.appendChild(text);
  header.appendChild(info);

  const expandHint = el('span');
  expandHint.textContent = 'Click to preview';
  expandHint.style.fontSize = '11px';
  expandHint.style.color = COLORS.context;
  header.appendChild(expandHint);
  container.appendChild(header);

  let expanded = false;
  let expandedContent: HTMLElement | null = null;

  container.onclick = () => {
    if (expanded) {
      if (expandedContent) {
        expandedContent.remove();
        expandedContent = null;
      }
      expandHint.textContent = 'Click to preview';
      container.style.backgroundColor = 'rgba(59, 130, 246, 0.08)';
      expanded = false;
    } else {
      expandedContent = renderDiffPreview(preview, sessionId, () => {
        container.remove();
        onComplete();
      });
      container.appendChild(expandedContent);
      expandHint.textContent = 'Click to collapse';
      container.style.backgroundColor = 'rgba(255, 255, 255, 0.95)';
      expanded = true;
    }
  };

  return container;
}
