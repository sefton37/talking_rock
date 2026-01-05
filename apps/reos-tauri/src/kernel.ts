/**
 * Kernel communication utilities for ReOS.
 * Handles JSON-RPC communication with the Python kernel via Tauri.
 *
 * Security:
 * - All kernel requests require a valid session token
 * - Session tokens are stored in sessionStorage (cleared on window close)
 * - Tokens are 256-bit CSPRNG, validated by Rust on every request
 */
import { invoke } from '@tauri-apps/api/core';
import { JsonRpcResponseSchema } from './types';

// Session token storage
const SESSION_TOKEN_KEY = 'reos_session_token';
const SESSION_USERNAME_KEY = 'reos_session_username';

export class KernelError extends Error {
  code: number;

  constructor(message: string, code: number) {
    super(message);
    this.name = 'KernelError';
    this.code = code;
  }
}

export class AuthenticationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuthenticationError';
  }
}

/**
 * Get the current session token.
 * @returns Session token or null if not authenticated
 */
export function getSessionToken(): string | null {
  return sessionStorage.getItem(SESSION_TOKEN_KEY);
}

/**
 * Get the current username.
 * @returns Username or null if not authenticated
 */
export function getSessionUsername(): string | null {
  return sessionStorage.getItem(SESSION_USERNAME_KEY);
}

/**
 * Check if user is authenticated.
 * @returns True if a session token exists
 */
export function isAuthenticated(): boolean {
  return getSessionToken() !== null;
}

/**
 * Store session credentials after successful login.
 * @param token - Session token from auth
 * @param username - Authenticated username
 */
export function setSession(token: string, username: string): void {
  sessionStorage.setItem(SESSION_TOKEN_KEY, token);
  sessionStorage.setItem(SESSION_USERNAME_KEY, username);
}

/**
 * Clear session credentials on logout.
 */
export function clearSession(): void {
  sessionStorage.removeItem(SESSION_TOKEN_KEY);
  sessionStorage.removeItem(SESSION_USERNAME_KEY);
}

/**
 * Login result from authentication.
 */
export interface AuthResult {
  success: boolean;
  session_token?: string;
  username?: string;
  error?: string;
}

/**
 * Authenticate user via PAM.
 * @param username - Linux username
 * @param password - User password
 * @returns Authentication result
 */
export async function login(username: string, password: string): Promise<AuthResult> {
  const result = await invoke<AuthResult>('auth_login', { username, password });

  if (result.success && result.session_token && result.username) {
    setSession(result.session_token, result.username);
  }

  return result;
}

/**
 * Logout and destroy session.
 * @returns True if logout succeeded
 */
export async function logout(): Promise<boolean> {
  const token = getSessionToken();
  if (!token) return false;

  try {
    await invoke('auth_logout', { sessionToken: token });
  } catch {
    // Ignore errors, clear local session anyway
  }

  clearSession();
  return true;
}

/**
 * Validate current session.
 * @returns True if session is valid
 */
export async function validateSession(): Promise<boolean> {
  const token = getSessionToken();
  if (!token) return false;

  try {
    const result = await invoke<boolean>('auth_validate', { sessionToken: token });
    if (!result) {
      clearSession();
    }
    return result;
  } catch {
    clearSession();
    return false;
  }
}

/**
 * Refresh session activity timestamp.
 * @returns True if refresh succeeded
 */
export async function refreshSession(): Promise<boolean> {
  const token = getSessionToken();
  if (!token) return false;

  try {
    await invoke('auth_refresh', { sessionToken: token });
    return true;
  } catch {
    return false;
  }
}

/**
 * Send a JSON-RPC request to the Python kernel.
 * Requires an authenticated session.
 *
 * @param method - The RPC method name (e.g., 'chat/respond', 'tools/call')
 * @param params - The parameters for the method
 * @returns The result from the kernel
 * @throws AuthenticationError if not authenticated
 * @throws KernelError if the kernel returns an error
 */
export async function kernelRequest(method: string, params: unknown): Promise<unknown> {
  const sessionToken = getSessionToken();

  if (!sessionToken) {
    throw new AuthenticationError('Not authenticated. Please login first.');
  }

  const raw = await invoke('kernel_request', { sessionToken, method, params });
  const parsed = JsonRpcResponseSchema.parse(raw);

  if (parsed.error) {
    // Check for session errors
    if (parsed.error.code === -32003) {
      clearSession();
      throw new AuthenticationError('Session expired. Please login again.');
    }
    throw new KernelError(parsed.error.message, parsed.error.code);
  }

  return parsed.result;
}
