/**
 * Kernel communication utilities for ReOS.
 * Handles JSON-RPC communication with the Python kernel via Tauri.
 */
import { invoke } from '@tauri-apps/api/core';
import { JsonRpcResponseSchema } from './types';

export class KernelError extends Error {
  code: number;

  constructor(message: string, code: number) {
    super(message);
    this.name = 'KernelError';
    this.code = code;
  }
}

/**
 * Send a JSON-RPC request to the Python kernel.
 * @param method - The RPC method name (e.g., 'chat/respond', 'tools/call')
 * @param params - The parameters for the method
 * @returns The result from the kernel
 * @throws KernelError if the kernel returns an error
 */
export async function kernelRequest(method: string, params: unknown): Promise<unknown> {
  const raw = await invoke('kernel_request', { method, params });
  const parsed = JsonRpcResponseSchema.parse(raw);
  if (parsed.error) {
    throw new KernelError(parsed.error.message, parsed.error.code);
  }
  return parsed.result;
}
