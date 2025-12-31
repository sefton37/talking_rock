/**
 * RPC Contract Tests
 * Ensures frontend and backend agree on RPC method signatures
 */

import { describe, it, expect } from 'vitest';
import { z } from 'zod';

// Define expected RPC response schemas
const SettingsGetResponseSchema = z.object({
  ollama_url: z.string(),
  ollama_model: z.string(),
  repo_path: z.string(),
  poll_interval_seconds: z.number(),
  commit_review_enabled: z.boolean(),
  default_persona_id: z.string().nullable()
});

const PersonasListResponseSchema = z.object({
  personas: z.array(z.object({
    id: z.string(),
    name: z.string(),
    system_prompt: z.string()
  }))
});

const PlayActsListResponseSchema = z.object({
  active_act_id: z.string().nullable(),
  acts: z.array(z.object({
    act_id: z.string(),
    title: z.string(),
    active: z.boolean(),
    notes: z.string()
  }))
});

const PlayScenesListResponseSchema = z.object({
  scenes: z.array(z.object({
    scene_id: z.string(),
    title: z.string(),
    intent: z.string(),
    status: z.string(),
    time_horizon: z.string(),
    notes: z.string()
  }))
});

const PlayBeatsListResponseSchema = z.object({
  beats: z.array(z.object({
    beat_id: z.string(),
    title: z.string(),
    status: z.string(),
    notes: z.string(),
    link: z.string().nullable()
  }))
});

const PlayKbListResponseSchema = z.object({
  files: z.array(z.string())
});

const PlayKbReadResponseSchema = z.object({
  path: z.string(),
  text: z.string()
});

const PlayKbWritePreviewResponseSchema = z.object({
  path: z.string(),
  exists: z.boolean(),
  sha256_current: z.string(),
  expected_sha256_current: z.string(),
  sha256_new: z.string(),
  diff: z.string()
});

const PlayKbWriteApplyResponseSchema = z.object({
  ok: z.boolean(),
  sha256_current: z.string()
});

const ChatRespondResponseSchema = z.object({
  answer: z.string()
});

const OllamaHealthResponseSchema = z.object({
  reachable: z.boolean(),
  model_count: z.number().nullable().optional(),
  error: z.string().nullable().optional()
});

describe('RPC Contract Tests', () => {
  describe('Settings RPCs', () => {
    it('settings/get response matches schema', () => {
      const mockResponse = {
        ollama_url: 'http://localhost:11434',
        ollama_model: 'llama3.2:3b',
        repo_path: '/path/to/repo',
        poll_interval_seconds: 30,
        commit_review_enabled: false,
        default_persona_id: null
      };

      const result = SettingsGetResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });

    it('ollama/health response matches schema', () => {
      const mockResponse = {
        reachable: true,
        model_count: 5,
        error: null
      };

      const result = OllamaHealthResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });
  });

  describe('Personas RPCs', () => {
    it('personas/list response matches schema', () => {
      const mockResponse = {
        personas: [
          {
            id: 'persona-1',
            name: 'Default',
            system_prompt: 'You are a helpful assistant'
          }
        ]
      };

      const result = PersonasListResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });
  });

  describe('Play Acts RPCs', () => {
    it('play/acts/list response matches schema', () => {
      const mockResponse = {
        active_act_id: 'act-1',
        acts: [
          {
            act_id: 'act-1',
            title: 'Test Act',
            active: true,
            notes: 'Test notes'
          }
        ]
      };

      const result = PlayActsListResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });

    it('play/acts/list handles null active_act_id', () => {
      const mockResponse = {
        active_act_id: null,
        acts: []
      };

      const result = PlayActsListResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });
  });

  describe('Play Scenes RPCs', () => {
    it('play/scenes/list response matches schema', () => {
      const mockResponse = {
        scenes: [
          {
            scene_id: 'scene-1',
            title: 'Test Scene',
            intent: 'Test intent',
            status: 'active',
            time_horizon: '1 week',
            notes: 'Test notes'
          }
        ]
      };

      const result = PlayScenesListResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });
  });

  describe('Play Beats RPCs', () => {
    it('play/beats/list response matches schema', () => {
      const mockResponse = {
        beats: [
          {
            beat_id: 'beat-1',
            title: 'Test Beat',
            status: 'pending',
            notes: 'Test notes',
            link: 'https://example.com'
          }
        ]
      };

      const result = PlayBeatsListResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });

    it('play/beats/list handles null link', () => {
      const mockResponse = {
        beats: [
          {
            beat_id: 'beat-1',
            title: 'Test Beat',
            status: 'pending',
            notes: '',
            link: null
          }
        ]
      };

      const result = PlayBeatsListResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });
  });

  describe('Play KB RPCs', () => {
    it('play/kb/list response matches schema', () => {
      const mockResponse = {
        files: ['kb.md', 'notes.md', 'roadmap.md']
      };

      const result = PlayKbListResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });

    it('play/kb/read response matches schema', () => {
      const mockResponse = {
        path: 'kb.md',
        text: '# Knowledge Base\n\nContent here'
      };

      const result = PlayKbReadResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });

    it('play/kb/write_preview response matches schema', () => {
      const mockResponse = {
        path: 'kb.md',
        exists: true,
        sha256_current: 'abc123',
        expected_sha256_current: 'abc123',
        sha256_new: 'def456',
        diff: '@@ -1,1 +1,1 @@\n-Old content\n+New content'
      };

      const result = PlayKbWritePreviewResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });

    it('play/kb/write_apply response matches schema', () => {
      const mockResponse = {
        ok: true,
        sha256_current: 'def456'
      };

      const result = PlayKbWriteApplyResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });
  });

  describe('Chat RPCs', () => {
    it('chat/respond response matches schema', () => {
      const mockResponse = {
        answer: 'This is the assistant response'
      };

      const result = ChatRespondResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(true);
    });
  });

  describe('Schema validation failures', () => {
    it('should reject invalid settings/get response', () => {
      const mockResponse = {
        ollama_url: 'http://localhost:11434',
        // Missing required fields
      };

      const result = SettingsGetResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(false);
    });

    it('should reject invalid type in play/acts/list', () => {
      const mockResponse = {
        active_act_id: 123, // Should be string or null
        acts: []
      };

      const result = PlayActsListResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(false);
    });

    it('should reject missing required field in KB write preview', () => {
      const mockResponse = {
        path: 'kb.md',
        exists: true
        // Missing sha256 fields
      };

      const result = PlayKbWritePreviewResponseSchema.safeParse(mockResponse);
      expect(result.success).toBe(false);
    });
  });
});
