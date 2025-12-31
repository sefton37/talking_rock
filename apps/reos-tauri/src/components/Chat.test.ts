/**
 * Tests for Chat component
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Chat } from './Chat';
import { createMockKernelRequest } from '../test/setup';

describe('Chat', () => {
  let mockKernelRequest: ReturnType<typeof createMockKernelRequest>;
  let chat: Chat;

  beforeEach(() => {
    mockKernelRequest = createMockKernelRequest();
    chat = new Chat(mockKernelRequest);
  });

  describe('initialization', () => {
    it('should create chat component', () => {
      expect(chat).toBeDefined();
    });

    it('should render with chat log and input', () => {
      const container = chat.render();
      expect(container.className).toBe('center');
      expect(container.querySelector('.chat-log')).toBeTruthy();
      expect(container.querySelector('.chat-input')).toBeTruthy();
      expect(container.querySelector('.send-btn')).toBeTruthy();
    });

    it('should initialize without errors', async () => {
      await expect(chat.init()).resolves.toBeUndefined();
    });
  });

  describe('message sending', () => {
    it('should not send empty messages', async () => {
      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;
      const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

      input.value = '   ';
      sendBtn.click();

      await new Promise(resolve => setTimeout(resolve, 10));
      expect(mockKernelRequest).not.toHaveBeenCalled();
    });

    it('should send non-empty messages', async () => {
      mockKernelRequest.mockResolvedValue({ answer: 'Test response' });

      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;
      const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

      input.value = 'Hello';
      sendBtn.click();

      // Wait for async operations
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(mockKernelRequest).toHaveBeenCalledWith('chat/respond', { text: 'Hello' });
    });

    it('should clear input after sending', async () => {
      mockKernelRequest.mockResolvedValue({ answer: 'Response' });

      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;
      const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

      input.value = 'Test message';
      sendBtn.click();

      expect(input.value).toBe('');
    });

    it('should handle Enter key press', async () => {
      mockKernelRequest.mockResolvedValue({ answer: 'Response' });

      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;

      input.value = 'Test';
      const event = new KeyboardEvent('keydown', { key: 'Enter' });
      input.dispatchEvent(event);

      await new Promise(resolve => setTimeout(resolve, 50));
      expect(mockKernelRequest).toHaveBeenCalled();
    });
  });

  describe('message display', () => {
    it('should display user message', async () => {
      mockKernelRequest.mockResolvedValue({ answer: 'Response' });

      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;
      const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

      input.value = 'User message';
      sendBtn.click();

      const chatLog = container.querySelector('.chat-log') as HTMLDivElement;
      const userBubbles = chatLog.querySelectorAll('.chat-bubble.user');
      expect(userBubbles.length).toBeGreaterThan(0);
      expect(userBubbles[0].textContent).toBe('User message');
    });

    it('should show thinking indicator', async () => {
      let resolvePromise: (value: unknown) => void;
      const promise = new Promise(resolve => {
        resolvePromise = resolve;
      });
      mockKernelRequest.mockReturnValue(promise);

      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;
      const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

      input.value = 'Test';
      sendBtn.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      const chatLog = container.querySelector('.chat-log') as HTMLDivElement;
      const thinkingBubbles = chatLog.querySelectorAll('.chat-bubble.thinking');
      expect(thinkingBubbles.length).toBeGreaterThan(0);

      // Resolve the promise
      resolvePromise!({ answer: 'Done' });
    });

    it('should display assistant response', async () => {
      mockKernelRequest.mockResolvedValue({ answer: 'Assistant response' });

      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;
      const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

      input.value = 'Question';
      sendBtn.click();

      await new Promise(resolve => setTimeout(resolve, 100));

      const chatLog = container.querySelector('.chat-log') as HTMLDivElement;
      const reosBubbles = chatLog.querySelectorAll('.chat-bubble.reos');
      const lastBubble = reosBubbles[reosBubbles.length - 1];
      expect(lastBubble.textContent).toContain('Assistant response');
    });
  });

  describe('error handling', () => {
    it('should display error message on RPC failure', async () => {
      mockKernelRequest.mockRejectedValue(new Error('Connection failed'));

      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;
      const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

      input.value = 'Test';
      sendBtn.click();

      await new Promise(resolve => setTimeout(resolve, 100));

      const chatLog = container.querySelector('.chat-log') as HTMLDivElement;
      const errorBubbles = chatLog.querySelectorAll('.chat-bubble.reos');
      const lastBubble = errorBubbles[errorBubbles.length - 1];
      expect(lastBubble.textContent).toContain('Error');
      expect(lastBubble.textContent).toContain('Connection failed');
    });

    it('should handle missing answer gracefully', async () => {
      mockKernelRequest.mockResolvedValue({});

      const container = chat.render();
      const input = container.querySelector('.chat-input') as HTMLInputElement;
      const sendBtn = container.querySelector('.send-btn') as HTMLButtonElement;

      input.value = 'Test';
      sendBtn.click();

      await new Promise(resolve => setTimeout(resolve, 100));

      const chatLog = container.querySelector('.chat-log') as HTMLDivElement;
      const bubbles = chatLog.querySelectorAll('.chat-bubble.reos');
      const lastBubble = bubbles[bubbles.length - 1];
      expect(lastBubble.textContent).toBe('(no answer)');
    });
  });

  describe('cleanup', () => {
    it('should have destroy method', () => {
      expect(typeof chat.destroy).toBe('function');
    });

    it('should not throw on destroy', () => {
      expect(() => chat.destroy()).not.toThrow();
    });
  });
});
