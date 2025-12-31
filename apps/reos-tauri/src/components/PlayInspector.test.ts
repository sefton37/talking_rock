/**
 * Tests for PlayInspector component
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PlayInspector } from './PlayInspector';
import { KernelError } from './types';
import { createMockKernelRequest } from '../test/setup';

describe('PlayInspector', () => {
  let mockKernelRequest: ReturnType<typeof createMockKernelRequest>;
  let inspector: PlayInspector;

  beforeEach(() => {
    mockKernelRequest = createMockKernelRequest();
    inspector = new PlayInspector(mockKernelRequest);
  });

  describe('initialization', () => {
    it('should create inspector component', () => {
      expect(inspector).toBeDefined();
    });

    it('should render with title', () => {
      const container = inspector.render();
      expect(container.className).toBe('play-inspector');
      expect(container.textContent).toContain('The Play');
    });

    it('should fetch acts on init', async () => {
      mockKernelRequest.mockResolvedValue({
        active_act_id: null,
        acts: []
      });

      await inspector.init();

      expect(mockKernelRequest).toHaveBeenCalledWith('play/acts/list', {});
    });
  });

  describe('no acts state', () => {
    it('should show empty state when no acts', async () => {
      mockKernelRequest.mockResolvedValue({
        active_act_id: null,
        acts: []
      });

      const container = inspector.render();
      await inspector.init();

      expect(container.textContent).toContain('Create an Act to begin');
    });

    it('should show create act form', async () => {
      mockKernelRequest.mockResolvedValue({
        active_act_id: null,
        acts: []
      });

      const container = inspector.render();
      await inspector.init();

      const input = container.querySelector('input[placeholder="New act title"]');
      expect(input).toBeTruthy();

      const createBtn = Array.from(container.querySelectorAll('button'))
        .find(btn => btn.textContent === 'Create');
      expect(createBtn).toBeTruthy();
    });
  });

  describe('acts management', () => {
    it('should display act editor when act exists', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: 'Test notes' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      const container = inspector.render();
      await inspector.init();

      expect(container.textContent).toContain('Act');
      expect(container.textContent).toContain('Title');
      expect(container.textContent).toContain('Notes');
    });

    it('should show breadcrumb status', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      const container = inspector.render();
      await inspector.init();

      expect(container.textContent).toContain('Act');
    });
  });

  describe('scenes management', () => {
    it('should show scenes section', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      const container = inspector.render();
      await inspector.init();

      expect(container.textContent).toContain('Scenes');
    });

    it('should show empty scenes state', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      const container = inspector.render();
      await inspector.init();

      expect(container.textContent).toContain('(no scenes yet)');
    });

    it('should fetch scenes for active act', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      await inspector.init();

      expect(mockKernelRequest).toHaveBeenCalledWith('play/scenes/list', {
        act_id: 'act-1'
      });
    });
  });

  describe('knowledge base integration', () => {
    it('should show KB section header', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      const container = inspector.render();
      await inspector.init();

      // Wait for async KB rendering
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(container.textContent).toContain('Mini Knowledgebase');
    });

    it('should show Act KB context label', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      const container = inspector.render();
      await inspector.init();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(container.textContent).toContain('Act KB');
    });

    it('should have KB file path input', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      const container = inspector.render();
      await inspector.init();

      await new Promise(resolve => setTimeout(resolve, 50));

      const inputs = container.querySelectorAll('input');
      const pathInput = Array.from(inputs).find(
        input => input.value === 'kb.md' || input.placeholder?.includes('kb')
      );
      expect(pathInput).toBeTruthy();
    });

    it('should have Preview and Apply buttons', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        });

      const container = inspector.render();
      await inspector.init();

      await new Promise(resolve => setTimeout(resolve, 50));

      const buttons = Array.from(container.querySelectorAll('button'));
      const previewBtn = buttons.find(btn => btn.textContent === 'Preview');
      const applyBtn = buttons.find(btn => btn.textContent === 'Apply');

      expect(previewBtn).toBeTruthy();
      expect(applyBtn).toBeTruthy();
    });
  });

  describe('error handling', () => {
    it('should handle acts fetch error', async () => {
      mockKernelRequest.mockRejectedValue(new Error('Network error'));

      const container = inspector.render();
      await expect(inspector.init()).resolves.toBeUndefined();

      // Should show empty state
      expect(container.textContent).toContain('Create an Act to begin');
    });

    it('should handle KB conflict error', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          scenes: []
        })
        .mockRejectedValueOnce(new KernelError('Conflict detected', -32009));

      const container = inspector.render();
      await inspector.init();

      await new Promise(resolve => setTimeout(resolve, 50));

      const applyBtn = Array.from(container.querySelectorAll('button'))
        .find(btn => btn.textContent === 'Apply');

      applyBtn?.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(container.textContent).toContain('Conflict');
    });
  });

  describe('cleanup', () => {
    it('should have destroy method', () => {
      expect(typeof inspector.destroy).toBe('function');
    });

    it('should not throw on destroy', () => {
      expect(() => inspector.destroy()).not.toThrow();
    });
  });
});
