/**
 * Lock Screen for ReOS
 *
 * Provides login UI and session lock functionality.
 * Used for:
 * - Initial login on app launch
 * - Re-authentication after session expiry
 * - Manual lock (via system sleep/lock events)
 */
import { login, getSessionUsername, isAuthenticated, validateSession } from './kernel';
import { el } from './dom';

export interface LockScreenOptions {
  /** Called after successful login */
  onLogin: (username: string) => void;
  /** If true, shows as re-authentication (username pre-filled, not editable) */
  isReauth?: boolean;
  /** Username to pre-fill for re-authentication */
  username?: string;
}

/**
 * Show the login/lock screen.
 * Replaces the app content with a login form.
 *
 * @param root - The root element to render into
 * @param options - Lock screen options
 */
export function showLockScreen(root: HTMLElement, options: LockScreenOptions): void {
  root.innerHTML = '';

  const container = el('div');
  container.className = 'lock-screen';
  container.style.cssText = `
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    font-family: system-ui, -apple-system, sans-serif;
  `;

  const card = el('div');
  card.className = 'lock-card';
  card.style.cssText = `
    background: rgba(30, 41, 59, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    padding: 40px;
    width: 320px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
  `;

  // Logo/Title
  const logo = el('div');
  logo.style.cssText = `
    text-align: center;
    margin-bottom: 32px;
  `;

  const logoText = el('div');
  logoText.textContent = 'ReOS';
  logoText.style.cssText = `
    font-size: 32px;
    font-weight: 700;
    color: #f1f5f9;
    letter-spacing: -0.5px;
  `;

  const subtitle = el('div');
  subtitle.textContent = options.isReauth ? 'Session Locked' : 'Natural Language Linux';
  subtitle.style.cssText = `
    font-size: 14px;
    color: rgba(148, 163, 184, 0.8);
    margin-top: 4px;
  `;

  logo.appendChild(logoText);
  logo.appendChild(subtitle);

  // Form
  const form = el('form') as HTMLFormElement;
  form.style.cssText = `
    display: flex;
    flex-direction: column;
    gap: 16px;
  `;

  // Username field
  const usernameGroup = el('div');
  usernameGroup.style.cssText = `display: flex; flex-direction: column; gap: 6px;`;

  const usernameLabel = el('label');
  usernameLabel.textContent = 'Username';
  usernameLabel.style.cssText = `
    font-size: 12px;
    font-weight: 500;
    color: #94a3b8;
  `;

  const usernameInput = el('input') as HTMLInputElement;
  usernameInput.type = 'text';
  usernameInput.name = 'username';
  usernameInput.autocomplete = 'username';
  usernameInput.placeholder = 'Linux username';
  usernameInput.required = true;
  if (options.username) {
    usernameInput.value = options.username;
    if (options.isReauth) {
      usernameInput.readOnly = true;
      usernameInput.style.opacity = '0.7';
    }
  }
  usernameInput.style.cssText = `
    padding: 12px 14px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 8px;
    background: rgba(15, 23, 42, 0.6);
    color: #f1f5f9;
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s;
  `;
  usernameInput.addEventListener('focus', () => {
    usernameInput.style.borderColor = 'rgba(59, 130, 246, 0.5)';
  });
  usernameInput.addEventListener('blur', () => {
    usernameInput.style.borderColor = 'rgba(255, 255, 255, 0.15)';
  });

  usernameGroup.appendChild(usernameLabel);
  usernameGroup.appendChild(usernameInput);

  // Password field
  const passwordGroup = el('div');
  passwordGroup.style.cssText = `display: flex; flex-direction: column; gap: 6px;`;

  const passwordLabel = el('label');
  passwordLabel.textContent = 'Password';
  passwordLabel.style.cssText = `
    font-size: 12px;
    font-weight: 500;
    color: #94a3b8;
  `;

  const passwordInput = el('input') as HTMLInputElement;
  passwordInput.type = 'password';
  passwordInput.name = 'password';
  passwordInput.autocomplete = 'current-password';
  passwordInput.placeholder = 'Linux password';
  passwordInput.required = true;
  passwordInput.style.cssText = usernameInput.style.cssText;
  passwordInput.addEventListener('focus', () => {
    passwordInput.style.borderColor = 'rgba(59, 130, 246, 0.5)';
  });
  passwordInput.addEventListener('blur', () => {
    passwordInput.style.borderColor = 'rgba(255, 255, 255, 0.15)';
  });

  passwordGroup.appendChild(passwordLabel);
  passwordGroup.appendChild(passwordInput);

  // Error message
  const errorMsg = el('div');
  errorMsg.className = 'login-error';
  errorMsg.style.cssText = `
    display: none;
    padding: 10px 12px;
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 6px;
    color: #fca5a5;
    font-size: 13px;
  `;

  // Submit button
  const submitBtn = el('button') as HTMLButtonElement;
  submitBtn.type = 'submit';
  submitBtn.textContent = options.isReauth ? 'Unlock' : 'Login';
  submitBtn.style.cssText = `
    padding: 12px;
    border: none;
    border-radius: 8px;
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s;
    margin-top: 8px;
  `;
  submitBtn.addEventListener('mouseenter', () => {
    submitBtn.style.opacity = '0.9';
  });
  submitBtn.addEventListener('mouseleave', () => {
    submitBtn.style.opacity = '1';
  });
  submitBtn.addEventListener('mousedown', () => {
    submitBtn.style.transform = 'scale(0.98)';
  });
  submitBtn.addEventListener('mouseup', () => {
    submitBtn.style.transform = 'scale(1)';
  });

  // Loading state
  let isLoading = false;
  const setLoading = (loading: boolean) => {
    isLoading = loading;
    submitBtn.disabled = loading;
    submitBtn.textContent = loading ? 'Authenticating...' : (options.isReauth ? 'Unlock' : 'Login');
    submitBtn.style.opacity = loading ? '0.6' : '1';
    usernameInput.disabled = loading;
    passwordInput.disabled = loading;
  };

  // Form submit handler
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (isLoading) return;

    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    if (!username || !password) {
      errorMsg.textContent = 'Please enter both username and password';
      errorMsg.style.display = 'block';
      return;
    }

    setLoading(true);
    errorMsg.style.display = 'none';

    try {
      const result = await login(username, password);

      if (result.success) {
        options.onLogin(username);
      } else {
        errorMsg.textContent = result.error || 'Authentication failed';
        errorMsg.style.display = 'block';
        passwordInput.value = '';
        passwordInput.focus();
      }
    } catch (err) {
      errorMsg.textContent = err instanceof Error ? err.message : 'Login failed';
      errorMsg.style.display = 'block';
      passwordInput.value = '';
    } finally {
      setLoading(false);
    }
  });

  form.appendChild(usernameGroup);
  form.appendChild(passwordGroup);
  form.appendChild(errorMsg);
  form.appendChild(submitBtn);

  card.appendChild(logo);
  card.appendChild(form);
  container.appendChild(card);

  // Security note
  const secNote = el('div');
  secNote.style.cssText = `
    margin-top: 24px;
    font-size: 11px;
    color: rgba(148, 163, 184, 0.5);
    text-align: center;
    max-width: 280px;
  `;
  secNote.textContent = 'Authenticated via Linux PAM. Your password is validated locally and never stored.';
  container.appendChild(secNote);

  root.appendChild(container);

  // Focus appropriate field
  if (options.isReauth || options.username) {
    passwordInput.focus();
  } else {
    usernameInput.focus();
  }
}

/**
 * Show lock screen overlay on top of existing content.
 * Used when session expires or device locks.
 *
 * @param onUnlock - Called after successful re-authentication
 */
export function showLockOverlay(onUnlock: () => void): void {
  const username = getSessionUsername();
  if (!username) {
    // No session, trigger full reload to show login
    window.location.reload();
    return;
  }

  // Create overlay
  const overlay = el('div');
  overlay.id = 'lock-overlay';
  overlay.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 10000;
    background: rgba(15, 23, 42, 0.95);
    backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: system-ui, -apple-system, sans-serif;
  `;

  const card = el('div');
  card.style.cssText = `
    background: rgba(30, 41, 59, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    padding: 32px;
    width: 300px;
    text-align: center;
  `;

  const lockIcon = el('div');
  lockIcon.textContent = '🔒';
  lockIcon.style.cssText = `font-size: 48px; margin-bottom: 16px;`;

  const title = el('div');
  title.textContent = 'Session Locked';
  title.style.cssText = `
    font-size: 18px;
    font-weight: 600;
    color: #f1f5f9;
    margin-bottom: 8px;
  `;

  const userDisplay = el('div');
  userDisplay.textContent = username;
  userDisplay.style.cssText = `
    font-size: 14px;
    color: #94a3b8;
    margin-bottom: 20px;
  `;

  const passwordInput = el('input') as HTMLInputElement;
  passwordInput.type = 'password';
  passwordInput.placeholder = 'Password';
  passwordInput.autocomplete = 'current-password';
  passwordInput.style.cssText = `
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 8px;
    background: rgba(15, 23, 42, 0.6);
    color: #f1f5f9;
    font-size: 14px;
    margin-bottom: 12px;
    outline: none;
  `;

  const errorMsg = el('div');
  errorMsg.style.cssText = `
    display: none;
    color: #fca5a5;
    font-size: 13px;
    margin-bottom: 12px;
  `;

  const unlockBtn = el('button') as HTMLButtonElement;
  unlockBtn.textContent = 'Unlock';
  unlockBtn.style.cssText = `
    width: 100%;
    padding: 12px;
    border: none;
    border-radius: 8px;
    background: #3b82f6;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  `;

  let isLoading = false;
  const handleUnlock = async () => {
    if (isLoading) return;

    const password = passwordInput.value;
    if (!password) {
      errorMsg.textContent = 'Please enter your password';
      errorMsg.style.display = 'block';
      return;
    }

    isLoading = true;
    unlockBtn.textContent = 'Unlocking...';
    unlockBtn.disabled = true;
    errorMsg.style.display = 'none';

    try {
      const result = await login(username, password);

      if (result.success) {
        overlay.remove();
        onUnlock();
      } else {
        errorMsg.textContent = result.error || 'Authentication failed';
        errorMsg.style.display = 'block';
        passwordInput.value = '';
        passwordInput.focus();
      }
    } catch (err) {
      errorMsg.textContent = err instanceof Error ? err.message : 'Unlock failed';
      errorMsg.style.display = 'block';
      passwordInput.value = '';
    } finally {
      isLoading = false;
      unlockBtn.textContent = 'Unlock';
      unlockBtn.disabled = false;
    }
  };

  passwordInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      handleUnlock();
    }
  });
  unlockBtn.addEventListener('click', handleUnlock);

  card.appendChild(lockIcon);
  card.appendChild(title);
  card.appendChild(userDisplay);
  card.appendChild(passwordInput);
  card.appendChild(errorMsg);
  card.appendChild(unlockBtn);
  overlay.appendChild(card);

  document.body.appendChild(overlay);
  passwordInput.focus();
}

/**
 * Remove lock overlay if present.
 */
export function hideLockOverlay(): void {
  const overlay = document.getElementById('lock-overlay');
  if (overlay) {
    overlay.remove();
  }
}

/**
 * Check session validity and show lock screen if needed.
 * @param onLogin - Called after successful login
 * @returns True if session is valid, false if login is required
 */
export async function checkSessionOrLogin(
  root: HTMLElement,
  onLogin: (username: string) => void
): Promise<boolean> {
  // Check if we have a session token
  if (!isAuthenticated()) {
    showLockScreen(root, { onLogin });
    return false;
  }

  // Validate the session with the server
  const isValid = await validateSession();
  if (!isValid) {
    const username = getSessionUsername();
    showLockScreen(root, {
      onLogin,
      isReauth: !!username,
      username: username || undefined,
    });
    return false;
  }

  return true;
}
