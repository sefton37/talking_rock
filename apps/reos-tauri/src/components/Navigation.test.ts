/**
 * Tests for Navigation component
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Navigation } from './Navigation';
import { createMockKernelRequest } from '../test/setup';

describe('Navigation', () => {
  let mockKernelRequest: ReturnType<typeof createMockKernelRequest>;
  let navigation: Navigation;

  beforeEach(() => {
    mockKernelRequest = createMockKernelRequest();
    navigation = new Navigation(mockKernelRequest);
  });

  describe('initialization', () => {
    it('should create navigation component', () => {
      expect(navigation).toBeDefined();
    });

    it('should render navigation pane', () => {
      const container = navigation.render();
      expect(container.className).toBe('nav');
      expect(container.style.width).toBe('240px');
    });

    it('should show ReOS title', () => {
      const container = navigation.render();
      expect(container.textContent).toContain('ReOS');
    });

    it('should show Me button', () => {
      const container = navigation.render();
      const meButton = Array.from(container.querySelectorAll('button'))
        .find(btn => btn.textContent === 'Me');
      expect(meButton).toBeTruthy();
    });

    it('should show Acts header', () => {
      const container = navigation.render();
      expect(container.textContent).toContain('Acts');
    });
  });

  describe('acts loading', () => {
    it('should fetch acts on init', async () => {
      mockKernelRequest.mockResolvedValue({
        active_act_id: null,
        acts: []
      });

      await navigation.init();

      expect(mockKernelRequest).toHaveBeenCalledWith('play/acts/list', {});
    });

    it('should display empty state when no acts', async () => {
      mockKernelRequest.mockResolvedValue({
        active_act_id: null,
        acts: []
      });

      const container = navigation.render();
      await navigation.init();

      expect(container.textContent).toContain('(no acts yet)');
    });

    it('should display acts list', async () => {
      mockKernelRequest.mockResolvedValue({
        active_act_id: 'act-1',
        acts: [
          { act_id: 'act-1', title: 'First Act', active: true, notes: '' },
          { act_id: 'act-2', title: 'Second Act', active: false, notes: '' }
        ]
      });

      const container = navigation.render();
      await navigation.init();

      expect(container.textContent).toContain('First Act');
      expect(container.textContent).toContain('Second Act');
    });

    it('should mark active act with bullet', async () => {
      mockKernelRequest.mockResolvedValue({
        active_act_id: 'act-1',
        acts: [
          { act_id: 'act-1', title: 'Active Act', active: true, notes: '' },
          { act_id: 'act-2', title: 'Inactive Act', active: false, notes: '' }
        ]
      });

      const container = navigation.render();
      await navigation.init();

      const buttons = Array.from(container.querySelectorAll('button'));
      const activeButton = buttons.find(btn => btn.textContent === '• Active Act');
      const inactiveButton = buttons.find(btn => btn.textContent === 'Inactive Act');

      expect(activeButton).toBeTruthy();
      expect(inactiveButton).toBeTruthy();
    });

    it('should handle fetch error gracefully', async () => {
      mockKernelRequest.mockRejectedValue(new Error('Network error'));

      const container = navigation.render();
      await expect(navigation.init()).resolves.toBeUndefined();

      // Should show empty state
      expect(container.textContent).toContain('(no acts yet)');
    });
  });

  describe('act selection', () => {
    it('should call RPC when act is clicked', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: null,
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: false, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        });

      const container = navigation.render();
      await navigation.init();

      const actButton = Array.from(container.querySelectorAll('button'))
        .find(btn => btn.textContent === 'Test Act');

      actButton!.click();

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(mockKernelRequest).toHaveBeenCalledWith('play/acts/set_active', {
        act_id: 'act-1'
      });
    });

    it('should trigger callback when act is selected', async () => {
      mockKernelRequest
        .mockResolvedValueOnce({
          active_act_id: null,
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: false, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        })
        .mockResolvedValueOnce({
          active_act_id: 'act-1',
          acts: [
            { act_id: 'act-1', title: 'Test Act', active: true, notes: '' }
          ]
        });

      const callback = vi.fn();
      navigation.setOnActSelected(callback);

      const container = navigation.render();
      await navigation.init();

      const actButton = Array.from(container.querySelectorAll('button'))
        .find(btn => btn.textContent === 'Test Act');

      actButton!.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(callback).toHaveBeenCalledWith('act-1');
    });
  });

  describe('Me window', () => {
    it('should trigger callback when Me button is clicked', () => {
      const callback = vi.fn();
      navigation.setOnMeClick(callback);

      const container = navigation.render();
      const meButton = Array.from(container.querySelectorAll('button'))
        .find(btn => btn.textContent === 'Me');

      meButton!.click();

      expect(callback).toHaveBeenCalled();
    });
  });

  describe('refresh', () => {
    it('should have refreshActs method', () => {
      expect(typeof navigation.refreshActs).toBe('function');
    });

    it('should refetch acts when refreshed', async () => {
      mockKernelRequest.mockResolvedValue({
        active_act_id: null,
        acts: []
      });

      await navigation.refreshActs();

      expect(mockKernelRequest).toHaveBeenCalledWith('play/acts/list', {});
    });
  });

  describe('cleanup', () => {
    it('should have destroy method', () => {
      expect(typeof navigation.destroy).toBe('function');
    });

    it('should not throw on destroy', () => {
      expect(() => navigation.destroy()).not.toThrow();
    });
  });
});
