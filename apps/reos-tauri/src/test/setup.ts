/**
 * Vitest setup file
 * Runs before each test file
 */

import { expect, vi } from 'vitest';

// Mock Tauri APIs
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn()
}));

vi.mock('@tauri-apps/api/webviewWindow', () => ({
  WebviewWindow: vi.fn()
}));

// Add custom matchers if needed
expect.extend({
  // Custom matchers can go here
});

// Global test utilities
export function createMockKernelRequest() {
  return vi.fn();
}

export function mockRpcResponse(result: unknown) {
  return {
    jsonrpc: '2.0' as const,
    id: 1,
    result
  };
}

export function mockRpcError(code: number, message: string, data?: unknown) {
  return {
    jsonrpc: '2.0' as const,
    id: 1,
    error: {
      code,
      message,
      data
    }
  };
}
