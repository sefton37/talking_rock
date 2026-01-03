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
