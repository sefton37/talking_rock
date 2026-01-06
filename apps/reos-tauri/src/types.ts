/**
 * Type definitions for ReOS Tauri frontend.
 */
import { z } from 'zod';

export const JsonRpcResponseSchema = z.object({
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

export type ChatRespondResult = {
  answer: string;
  conversation_id: string;
  message_id: string;
  message_type: string;
  tool_calls: Array<{
    name: string;
    arguments: Record<string, unknown>;
    ok: boolean;
    result?: unknown;
    error?: { code: string; message: string; data?: unknown };
  }>;
  thinking_steps: string[];  // Chain of thought - reasoning steps before final answer
  pending_approval_id: string | null;
  intent_handled?: 'approval' | 'rejection';  // Phase 6: Set when a conversational intent was handled
  // Code Mode: Diff preview for pending file changes
  diff_preview?: {
    session_id: string;
    preview: DiffPreview;
  };
};

// Conversation types
export type ConversationStartResult = {
  conversation_id: string;
};

export type ConversationListResult = {
  conversations: Array<{
    id: string;
    title: string | null;
    started_at: string;
    last_active_at: string;
  }>;
};

export type ConversationMessagesResult = {
  messages: Array<{
    id: string;
    role: string;
    content: string;
    message_type: string;
    metadata: string | null;
    created_at: string;
  }>;
};

// Approval types
export type ApprovalPendingResult = {
  approvals: Array<{
    id: string;
    conversation_id: string;
    command: string;
    explanation: string | null;
    risk_level: 'safe' | 'low' | 'medium' | 'high' | 'critical';
    affected_paths: string[];
    undo_command: string | null;
    plan_id: string | null;
    step_id: string | null;
    created_at: string;
  }>;
};

export type ApprovalRespondResult = {
  status: 'executed' | 'rejected' | 'error';
  result: {
    success?: boolean;
    stdout?: string;
    stderr?: string;
    return_code?: number;
    command?: string;
    error?: string;
  } | null;
};

export type ApprovalExplainResult = {
  command: string;
  explanation: string;
  detailed_explanation: string;
  is_destructive: boolean;
  can_undo: boolean;
  undo_command: string | null;
  affected_paths: string[];
  warnings: string[];
};

// Plan types (Phase 3)
export type PlanPreviewResult = {
  has_plan: boolean;
  plan_id?: string;
  title?: string;
  steps?: Array<{
    number: number;
    id: string;
    title: string;
    command: string | null;
    explanation: string | null;
    risk: {
      level?: string;
      requires_confirmation?: boolean;
      reversible?: boolean;
    };
  }>;
  needs_approval?: boolean;
  response: string;
  complexity?: string;
};

export type PlanApproveResult = {
  status: 'executed' | 'no_execution';
  response: string;
  execution_id: string | null;
};

export type ExecutionStatusResult = {
  execution_id: string;
  state: string;
  current_step: number;
  total_steps: number;
  completed_steps: Array<{
    step_id: string;
    success: boolean;
    output_preview: string;
  }>;
};

// Streaming execution types (Phase 4)
export type ExecutionStartResult = {
  execution_id: string;
  status: 'started';
};

export type ExecutionOutputResult = {
  lines: string[];
  is_complete: boolean;
  next_line: number;
  return_code?: number;
  success?: boolean;
  error?: string | null;
  duration_seconds?: number;
};

export type ExecutionKillResult = {
  ok: boolean;
  message: string;
};

// System Dashboard types (Phase 5)
export type SystemLiveStateResult = {
  cpu_percent: number;
  memory: {
    used_mb: number;
    total_mb: number;
    percent: number;
  };
  disks: Array<{
    mount: string;
    used_gb: number;
    total_gb: number;
    percent: number;
  }>;
  load_avg: [number, number, number];
  services: Array<{
    name: string;
    status: string;
    active: boolean;
  }>;
  containers: Array<{
    id: string;
    name: string;
    image: string;
    status: string;
    ports: string;
  }>;
  network: Array<{
    interface: string;
    ip: string;
    state: string;
  }>;
  ports: Array<{
    port: number;
    protocol: string;
    address: string;
    process: string;
    pid: number | null;
  }>;
  traffic: Array<{
    interface: string;
    rx_bytes: number;
    tx_bytes: number;
    rx_formatted: string;
    tx_formatted: string;
  }>;
};

export type ServiceActionResult = {
  ok?: boolean;
  requires_approval?: boolean;
  approval_id?: string;
  command?: string;
  message?: string;
  logs?: string;
  status?: string;
  active?: boolean;
  error?: string;
};

export type ContainerActionResult = {
  ok: boolean;
  logs?: string;
  message?: string;
  error?: string | null;
};

export type SystemInfoResult = {
  hostname: string;
  kernel: string;
  distro: string;
  uptime: string;
  cpu_model: string;
  cpu_cores: number;
  memory_total_mb: number;
  memory_used_mb: number;
  memory_percent: number;
  disk_total_gb: number;
  disk_used_gb: number;
  disk_percent: number;
  load_avg: [number, number, number];
};

export type ToolCallResult = {
  result?: unknown;
  error?: { code: string; message: string };
};

export type PlayMeReadResult = {
  markdown: string;
};

export type PlayActsListResult = {
  active_act_id: string | null;
  acts: Array<{ act_id: string; title: string; active: boolean; notes: string }>;
};

export type PlayScenesListResult = {
  scenes: Array<{
    scene_id: string;
    title: string;
    intent: string;
    status: string;
    time_horizon: string;
    notes: string;
  }>;
};

export type PlayBeatsListResult = {
  beats: Array<{ beat_id: string; title: string; status: string; notes: string; link: string | null }>;
};

export type PlayActsCreateResult = {
  created_act_id: string;
  acts: Array<{ act_id: string; title: string; active: boolean; notes: string }>;
};

export type PlayScenesMutationResult = {
  scenes: PlayScenesListResult['scenes'];
};

export type PlayBeatsMutationResult = {
  beats: PlayBeatsListResult['beats'];
};

export type PlayKbListResult = {
  files: string[];
};

export type PlayKbReadResult = {
  path: string;
  text: string;
};

export type PlayKbWritePreviewResult = {
  path: string;
  exists: boolean;
  sha256_current: string;
  expected_sha256_current: string;
  sha256_new: string;
  diff: string;
};

export type PlayKbWriteApplyResult = {
  ok: boolean;
  sha256_current: string;
};

// File attachment types
export type PlayAttachment = {
  attachment_id: string;
  file_path: string;
  file_name: string;
  file_type: string;
  added_at: string;
};

export type PlayAttachmentsListResult = {
  attachments: PlayAttachment[];
};

export type PlayAttachmentsMutationResult = {
  attachments: PlayAttachment[];
};

// Play levels for placeholder text
export type PlayLevel = 'play' | 'act' | 'scene' | 'beat';

// Intent detection types (Phase 6 - Conversational Troubleshooting)
export type IntentDetectResult = {
  detected: boolean;
  intent_type?: 'approval' | 'rejection' | 'choice' | 'reference';
  confidence?: number;
  choice_number?: number;
  reference_term?: string;
  resolved_entity?: {
    type: string;
    name?: string;
    id?: string;
    path?: string;
  };
};

// Context Meter types
export type ContextSource = {
  name: string;
  display_name: string;
  tokens: number;
  percent: number;
  enabled: boolean;
  description: string;
};

export type ContextStatsResult = {
  estimated_tokens: number;
  context_limit: number;
  reserved_tokens: number;
  available_tokens: number;
  usage_percent: number;
  message_count: number;
  warning_level: 'ok' | 'warning' | 'critical';
  sources?: ContextSource[];
};

export type ContextToggleResult = {
  ok: boolean;
  disabled_sources: string[];
};

// Archive types
export type ArchiveSaveResult = {
  archive_id: string;
  title: string;
  message_count: number;
  archived_at: string;
  summary: string;
};

export type ArchiveListResult = {
  archives: Array<{
    archive_id: string;
    act_id: string | null;
    title: string;
    created_at: string;
    archived_at: string;
    message_count: number;
    summary: string;
  }>;
};

export type ArchiveGetResult = {
  archive_id: string;
  act_id: string | null;
  title: string;
  created_at: string;
  archived_at: string;
  message_count: number;
  messages: Array<{
    role: string;
    content: string;
    created_at?: string;
  }>;
  summary: string;
};

// Compact types
export type CompactPreviewResult = {
  entries: Array<{
    category: 'fact' | 'lesson' | 'decision' | 'preference' | 'observation';
    content: string;
  }>;
  message_count: number;
  existing_entry_count: number;
};

export type CompactApplyResult = {
  added_count: number;
  archive_id: string | null;
  total_entries: number;
};

// Learned knowledge types
export type LearnedGetResult = {
  act_id: string | null;
  entry_count: number;
  last_updated: string;
  markdown: string;
  entries: Array<{
    entry_id: string;
    category: string;
    content: string;
    learned_at: string;
    source_archive_id: string | null;
  }>;
};

// Code Mode Diff Preview types
export type DiffHunk = {
  old_start: number;
  old_count: number;
  new_start: number;
  new_count: number;
  lines: string[];
  header: string;
};

export type DiffFileChange = {
  path: string;
  change_type: 'create' | 'modify' | 'delete' | 'rename';
  hunks: DiffHunk[];
  diff_text: string;
  old_sha256: string | null;
  new_sha256: string | null;
  additions: number;
  deletions: number;
  binary: boolean;
};

export type DiffPreview = {
  preview_id: string;
  changes: DiffFileChange[];
  total_additions: number;
  total_deletions: number;
  total_files: number;
  created_at: string;
};

export type CodeDiffPreviewResult = {
  preview: DiffPreview | null;
  message: string;
};

export type CodeDiffAddChangeResult = {
  ok: boolean;
  change: DiffFileChange;
};

export type CodeDiffApplyResult = {
  ok: boolean;
  applied: string[];
};

export type CodeDiffRejectResult = {
  ok: boolean;
  rejected: string[] | 'all';
};

export type CodeDiffClearResult = {
  ok: boolean;
};
