/**
 * Settings Overlay - Configuration panel for ReOS
 *
 * Tabs:
 * - LLM Provider: Ollama connection, model selection, downloads
 * - Agent Persona: Prompts review, parameters, customization
 */

import { kernelRequest } from './kernel';
import { el } from './dom';

type SettingsTab = 'llm' | 'persona' | 'safety';

interface OllamaStatus {
  url: string;
  model: string;
  reachable: boolean;
  model_count: number | null;
  error: string | null;
  available_models: string[];
  gpu_enabled: boolean;
  gpu_available: boolean;
  gpu_name: string | null;
  gpu_vram_gb: number | null;
  num_ctx: number | null;
  hardware: {
    ram_gb: number;
    gpu_available: boolean;
    gpu_name: string | null;
    gpu_vram_gb: number | null;
    gpu_type: string | null;
    recommended_max_params: string;
  };
}

interface ModelInfo {
  model: string;
  parameter_size: string | null;
  family: string;
  families: string[];
  quantization: string;
  context_length: number | null;
  format: string;
  capabilities: {
    vision: boolean;
    tools: boolean;
    thinking: boolean;
    embedding: boolean;
  };
  error?: string;
}

type AgentType = 'cairn' | 'riva' | 'reos';

interface PersonaData {
  id: string;
  name: string;
  agent_type: AgentType;
  system_prompt: string;
  default_context: string;
  temperature: number;
  top_p: number;
  tool_call_limit: number;
}

interface SettingsOverlay {
  element: HTMLElement;
  show: () => void;
  hide: () => void;
}

interface PullStatus {
  model: string;
  status: string;
  progress: number;
  total: number;
  completed: number;
  error: string | null;
  done: boolean;
}

interface PullStartResult {
  pull_id: string;
  model: string;
}

// Provider Types
interface ProviderInfo {
  id: string;
  name: string;
  description: string;
  is_local: boolean;
  requires_api_key: boolean;
  has_api_key?: boolean | null;
}

interface ProvidersListResult {
  current_provider: string;
  available_providers: ProviderInfo[];
  keyring_available: boolean;
}

interface AnthropicModel {
  name: string;
  context_length: number;
  capabilities: string[];
  description: string;
}

interface AnthropicStatus {
  has_api_key: boolean;
  keyring_available: boolean;
  model: string;
  available_models: AnthropicModel[];
  health: {
    reachable: boolean;
    model_count?: number;
    error?: string | null;
    current_model?: string | null;
  };
}

interface OllamaInstallStatus {
  installed: boolean;
  install_command: string;
}

// Safety & Security Types
interface RateLimitConfig {
  max_requests: number;
  window_seconds: number;
  name: string;
}

interface SafetySettings {
  // Rate limits
  rate_limits: Record<string, RateLimitConfig>;
  // Sudo escalation
  max_sudo_escalations: number;
  current_sudo_count: number;
  // Command limits
  max_command_length: number;
  // Agent execution limits
  max_iterations: number;
  wall_clock_timeout_seconds: number;
  // Validation limits
  max_service_name_length: number;
  max_container_id_length: number;
  max_package_name_length: number;
  // Dangerous pattern count (readonly)
  dangerous_pattern_count: number;
  injection_pattern_count: number;
}

/**
 * Download a model with progress tracking.
 * @param modelName Model to download
 * @param onProgress Called with progress updates
 * @returns Final status
 */
async function downloadModelWithProgress(
  modelName: string,
  onProgress: (status: PullStatus) => void
): Promise<PullStatus> {
  // Start the pull
  const startResult = await kernelRequest('ollama/pull_start', { model: modelName }) as PullStartResult;
  const pullId = startResult.pull_id;

  // Poll for status
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const status = await kernelRequest('ollama/pull_status', { pull_id: pullId }) as PullStatus;
        onProgress(status);

        if (status.done) {
          if (status.error) {
            reject(new Error(status.error));
          } else {
            resolve(status);
          }
        } else {
          // Poll again in 500ms
          setTimeout(poll, 500);
        }
      } catch (e) {
        reject(e);
      }
    };
    poll();
  });
}

/**
 * Format bytes to human readable string
 */
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function createSettingsOverlay(onClose?: () => void): SettingsOverlay {
  // State
  let activeTab: SettingsTab = 'llm';
  let ollamaStatus: OllamaStatus | null = null;
  let selectedModelInfo: ModelInfo | null = null;
  let personas: PersonaData[] = [];
  let activePersonaId: string | null = null;
  let customContext: string = '';
  let selectedPersonaAgent: AgentType = 'cairn';

  // Provider state
  let providersInfo: ProvidersListResult | null = null;
  let anthropicStatus: AnthropicStatus | null = null;
  let ollamaInstallStatus: OllamaInstallStatus | null = null;

  // Safety state
  let safetySettings: SafetySettings | null = null;

  // Create overlay container
  const overlay = el('div');
  overlay.className = 'settings-overlay';
  overlay.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.8);
    display: none;
    z-index: 1000;
    justify-content: center;
    align-items: center;
  `;

  // Modal container
  const modal = el('div');
  modal.className = 'settings-modal';
  modal.style.cssText = `
    width: 800px;
    max-width: 90vw;
    height: 600px;
    max-height: 85vh;
    background: #1e1e1e;
    border-radius: 12px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  `;

  // Header
  const header = el('div');
  header.style.cssText = `
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid #333;
  `;

  const title = el('div');
  title.textContent = '⚙️ Settings';
  title.style.cssText = 'font-size: 18px; font-weight: 600; color: #fff;';

  const closeBtn = el('button');
  closeBtn.textContent = '✕';
  closeBtn.style.cssText = `
    background: none;
    border: none;
    color: rgba(255,255,255,0.6);
    font-size: 20px;
    cursor: pointer;
    padding: 4px 8px;
  `;
  closeBtn.addEventListener('click', hide);

  header.appendChild(title);
  header.appendChild(closeBtn);

  // Tabs
  const tabsContainer = el('div');
  tabsContainer.style.cssText = `
    display: flex;
    border-bottom: 1px solid #333;
    background: rgba(0,0,0,0.2);
  `;

  const createTab = (id: SettingsTab, label: string, icon: string) => {
    const tab = el('button');
    tab.className = `settings-tab ${id}`;
    tab.textContent = `${icon} ${label}`;
    tab.style.cssText = `
      padding: 12px 24px;
      background: none;
      border: none;
      color: rgba(255,255,255,0.6);
      cursor: pointer;
      font-size: 13px;
      border-bottom: 2px solid transparent;
      transition: all 0.2s;
    `;
    tab.addEventListener('click', () => {
      activeTab = id;
      render();
    });
    return tab;
  };

  const llmTab = createTab('llm', 'LLM Provider', '🤖');
  const personaTab = createTab('persona', 'Agent Persona', '🎭');
  const safetyTab = createTab('safety', 'Safety', '🛡️');

  tabsContainer.appendChild(llmTab);
  tabsContainer.appendChild(personaTab);
  tabsContainer.appendChild(safetyTab);

  // Content area
  const content = el('div');
  content.className = 'settings-content';
  content.style.cssText = `
    flex: 1;
    overflow: auto;
    padding: 20px;
  `;

  modal.appendChild(header);
  modal.appendChild(tabsContainer);
  modal.appendChild(content);
  overlay.appendChild(modal);

  // Close on backdrop click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) hide();
  });

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && overlay.style.display === 'flex') hide();
  });

  function show() {
    overlay.style.display = 'flex';
    void loadData();
  }

  function hide() {
    overlay.style.display = 'none';
    onClose?.();
  }

  async function loadData() {
    // Load provider info first
    try {
      providersInfo = await kernelRequest('providers/list', {}) as ProvidersListResult;
    } catch {
      providersInfo = {
        current_provider: 'ollama',
        available_providers: [
          { id: 'ollama', name: 'Ollama (Local)', description: 'Private, runs on your machine', is_local: true, requires_api_key: false },
        ],
        keyring_available: false,
      };
    }

    // Load Ollama status (always, since it's the default)
    try {
      ollamaStatus = await kernelRequest('ollama/status', {}) as OllamaStatus;

      // Load model info for selected model
      if (ollamaStatus.model && ollamaStatus.reachable) {
        try {
          selectedModelInfo = await kernelRequest('ollama/model_info', { model: ollamaStatus.model }) as ModelInfo;
        } catch {
          selectedModelInfo = null;
        }
      }
    } catch (e) {
      // Set error state so UI can show what went wrong
      ollamaStatus = {
        url: 'http://127.0.0.1:11434',
        model: '',
        reachable: false,
        model_count: null,
        error: e instanceof Error ? e.message : 'Failed to fetch status',
        available_models: [],
        gpu_enabled: true,
        gpu_available: false,
        gpu_name: null,
        gpu_vram_gb: null,
        num_ctx: null,
        hardware: {
          ram_gb: 0,
          gpu_available: false,
          gpu_name: null,
          gpu_vram_gb: null,
          gpu_type: null,
          recommended_max_params: '3b',
        },
      };
    }

    // Load Ollama install status
    try {
      ollamaInstallStatus = await kernelRequest('ollama/check_installed', {}) as OllamaInstallStatus;
    } catch {
      ollamaInstallStatus = { installed: false, install_command: '' };
    }

    // Load Anthropic status if available
    try {
      anthropicStatus = await kernelRequest('anthropic/status', {}) as AnthropicStatus;
    } catch {
      anthropicStatus = null;
    }

    try {
      // Load personas
      const personasResult = await kernelRequest('personas/list', {}) as {
        personas: PersonaData[];
        active_persona_id: string | null;
      };
      personas = personasResult.personas || [];
      activePersonaId = personasResult.active_persona_id;
    } catch {
      // Personas not loaded, continue with empty list
    }

    // Load safety settings
    try {
      safetySettings = await kernelRequest('safety/settings', {}) as SafetySettings;
    } catch {
      // Default safety settings if endpoint not available
      safetySettings = {
        rate_limits: {
          auth: { max_requests: 5, window_seconds: 60, name: 'Login attempts' },
          sudo: { max_requests: 10, window_seconds: 60, name: 'Sudo commands' },
          service: { max_requests: 20, window_seconds: 60, name: 'Service operations' },
          container: { max_requests: 30, window_seconds: 60, name: 'Container operations' },
          package: { max_requests: 5, window_seconds: 300, name: 'Package operations' },
          approval: { max_requests: 20, window_seconds: 60, name: 'Approval actions' },
        },
        max_sudo_escalations: 3,
        current_sudo_count: 0,
        max_command_length: 4096,
        max_iterations: 10,
        wall_clock_timeout_seconds: 300,
        max_service_name_length: 256,
        max_container_id_length: 256,
        max_package_name_length: 256,
        dangerous_pattern_count: 18,
        injection_pattern_count: 13,
      };
    }

    render();
  }

  function render() {
    // Update tab styles
    llmTab.style.color = activeTab === 'llm' ? '#fff' : 'rgba(255,255,255,0.6)';
    llmTab.style.borderBottomColor = activeTab === 'llm' ? '#3b82f6' : 'transparent';
    personaTab.style.color = activeTab === 'persona' ? '#fff' : 'rgba(255,255,255,0.6)';
    personaTab.style.borderBottomColor = activeTab === 'persona' ? '#3b82f6' : 'transparent';
    safetyTab.style.color = activeTab === 'safety' ? '#fff' : 'rgba(255,255,255,0.6)';
    safetyTab.style.borderBottomColor = activeTab === 'safety' ? '#3b82f6' : 'transparent';

    content.innerHTML = '';

    if (activeTab === 'llm') {
      renderLLMTab();
    } else if (activeTab === 'persona') {
      renderPersonaTab();
    } else {
      renderSafetyTab();
    }
  }

  function renderLLMTab() {
    const currentProvider = providersInfo?.current_provider || 'ollama';

    // Provider Selection Section
    const providerSection = createSection('Provider');

    const providerRow = el('div');
    providerRow.style.cssText = `
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
    `;

    const providerSelect = el('select') as HTMLSelectElement;
    providerSelect.style.cssText = `
      flex: 1;
      padding: 10px 14px;
      background: #2a2a2a;
      border: 1px solid #444;
      border-radius: 6px;
      color: #fff;
      font-size: 14px;
      cursor: pointer;
    `;

    for (const p of providersInfo?.available_providers || []) {
      const option = el('option') as HTMLOptionElement;
      option.value = p.id;
      option.textContent = p.name;
      option.style.cssText = 'background: #2a2a2a; color: #fff;';
      if (p.id === currentProvider) option.selected = true;
      providerSelect.appendChild(option);
    }

    providerSelect.addEventListener('change', async () => {
      try {
        await kernelRequest('providers/set', { provider: providerSelect.value });
        await loadData();
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        alert('Failed to switch provider: ' + msg);
        await loadData();
      }
    });

    const providerDesc = el('div');
    const currentProviderInfo = providersInfo?.available_providers.find(p => p.id === currentProvider);
    providerDesc.innerHTML = currentProviderInfo
      ? `<span style="color: rgba(255,255,255,0.6); font-size: 12px;">${currentProviderInfo.description}</span>`
      : '';

    providerRow.appendChild(providerSelect);
    providerSection.appendChild(providerRow);
    providerSection.appendChild(providerDesc);
    content.appendChild(providerSection);

    // Render provider-specific settings
    if (currentProvider === 'anthropic') {
      renderAnthropicSettings();
    } else {
      renderOllamaSettings();
    }
  }

  function renderAnthropicSettings() {
    // Status Section
    const statusSection = createSection('Anthropic Status');

    const statusBox = el('div');
    statusBox.style.cssText = `
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
      margin-bottom: 16px;
    `;

    const isConnected = anthropicStatus?.health?.reachable || false;
    const statusIndicator = el('div');
    statusIndicator.style.cssText = `
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: ${isConnected ? '#22c55e' : anthropicStatus?.has_api_key ? '#f59e0b' : '#ef4444'};
    `;

    const statusText = el('div');
    if (isConnected) {
      statusText.innerHTML = `<strong style="color: #22c55e;">Connected</strong> <span style="color: rgba(255,255,255,0.7);">- ${anthropicStatus?.model || 'claude-sonnet-4-20250514'}</span>`;
    } else if (anthropicStatus?.has_api_key) {
      statusText.innerHTML = `<strong style="color: #f59e0b;">API Key Set</strong> <span style="color: rgba(255,255,255,0.7);">- ${anthropicStatus.health?.error || 'Not tested'}</span>`;
    } else {
      statusText.innerHTML = `<strong style="color: #ef4444;">Not Configured</strong> <span style="color: rgba(255,255,255,0.7);">- Add your API key below</span>`;
    }
    statusText.style.cssText = 'flex: 1;';

    statusBox.appendChild(statusIndicator);
    statusBox.appendChild(statusText);
    statusSection.appendChild(statusBox);

    // Keyring status
    if (!providersInfo?.keyring_available) {
      const keyringWarning = el('div');
      keyringWarning.innerHTML = `<span style="color: #f59e0b;">⚠️ System keyring not available. API keys cannot be stored securely.</span>`;
      keyringWarning.style.cssText = 'font-size: 12px; margin-bottom: 16px;';
      statusSection.appendChild(keyringWarning);
    }

    // API Key Input
    const apiKeyRow = createSettingRow('API Key', 'Your Anthropic API key (stored in system keyring)');
    const apiKeyInput = el('input') as HTMLInputElement;
    apiKeyInput.type = 'password';
    apiKeyInput.placeholder = anthropicStatus?.has_api_key ? '••••••••••••••••' : 'sk-ant-...';
    apiKeyInput.style.cssText = `
      flex: 1;
      padding: 8px 12px;
      background: rgba(0,0,0,0.3);
      border: 1px solid #444;
      border-radius: 4px;
      color: #fff;
      font-family: monospace;
      font-size: 13px;
    `;

    const saveKeyBtn = el('button');
    saveKeyBtn.textContent = anthropicStatus?.has_api_key ? 'Update' : 'Save';
    saveKeyBtn.style.cssText = `
      padding: 8px 16px;
      background: #3b82f6;
      border: none;
      border-radius: 4px;
      color: #fff;
      cursor: pointer;
      font-size: 13px;
    `;
    saveKeyBtn.addEventListener('click', async () => {
      if (!apiKeyInput.value) {
        alert('Please enter an API key');
        return;
      }
      saveKeyBtn.textContent = 'Saving...';
      saveKeyBtn.style.opacity = '0.6';
      try {
        await kernelRequest('anthropic/set_key', { api_key: apiKeyInput.value });
        apiKeyInput.value = '';
        await loadData();
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        alert('Failed to save API key: ' + msg);
      }
      saveKeyBtn.style.opacity = '1';
      saveKeyBtn.textContent = 'Save';
    });

    apiKeyRow.appendChild(apiKeyInput);
    apiKeyRow.appendChild(saveKeyBtn);

    // Delete key button (if key exists)
    if (anthropicStatus?.has_api_key) {
      const deleteKeyBtn = el('button');
      deleteKeyBtn.textContent = 'Delete';
      deleteKeyBtn.style.cssText = `
        padding: 8px 16px;
        background: rgba(239, 68, 68, 0.2);
        border: 1px solid rgba(239, 68, 68, 0.4);
        border-radius: 4px;
        color: #ef4444;
        cursor: pointer;
        font-size: 13px;
        margin-left: 8px;
      `;
      deleteKeyBtn.addEventListener('click', async () => {
        if (!confirm('Delete your Anthropic API key?')) return;
        try {
          await kernelRequest('anthropic/delete_key', {});
          await loadData();
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e);
          alert('Failed to delete API key: ' + msg);
        }
      });
      apiKeyRow.appendChild(deleteKeyBtn);
    }

    statusSection.appendChild(apiKeyRow);
    content.appendChild(statusSection);

    // Model Selection Section
    const modelSection = createSection('Model');

    const modelRow = el('div');
    modelRow.style.cssText = `
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 16px;
    `;

    const currentModel = anthropicStatus?.model || 'claude-sonnet-4-20250514';
    for (const model of anthropicStatus?.available_models || []) {
      const modelBtn = el('button');
      const isSelected = model.name === currentModel;
      modelBtn.innerHTML = `
        <strong>${model.name.replace('claude-', '').replace(/-20\d+$/, '')}</strong>
        <span style="font-size: 11px; opacity: 0.7; display: block;">${model.description}</span>
      `;
      modelBtn.style.cssText = `
        padding: 12px 16px;
        background: ${isSelected ? 'rgba(59, 130, 246, 0.3)' : 'rgba(0,0,0,0.2)'};
        border: 1px solid ${isSelected ? '#3b82f6' : '#444'};
        border-radius: 8px;
        color: #fff;
        cursor: pointer;
        text-align: left;
        min-width: 180px;
      `;
      modelBtn.addEventListener('click', async () => {
        try {
          await kernelRequest('anthropic/set_model', { model: model.name });
          await loadData();
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e);
          alert('Failed to set model: ' + msg);
        }
      });
      modelRow.appendChild(modelBtn);
    }

    modelSection.appendChild(modelRow);
    content.appendChild(modelSection);

    // Info section
    const infoSection = createSection('About Anthropic');
    const infoText = el('div');
    infoText.innerHTML = `
      <p style="margin: 0 0 8px 0; color: rgba(255,255,255,0.7);">
        Anthropic's Claude models are accessed via cloud API. Your prompts are sent to Anthropic's servers.
      </p>
      <p style="margin: 0; color: rgba(255,255,255,0.5); font-size: 12px;">
        Get your API key at <a href="https://console.anthropic.com" target="_blank" style="color: #3b82f6;">console.anthropic.com</a>
      </p>
    `;
    infoSection.appendChild(infoText);
    content.appendChild(infoSection);
  }

  function renderOllamaSettings() {
    // Connection Status Section
    const statusSection = createSection('Connection Status');

    const statusBox = el('div');
    statusBox.style.cssText = `
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
      margin-bottom: 16px;
    `;

    const statusIndicator = el('div');
    statusIndicator.style.cssText = `
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: ${ollamaStatus?.reachable ? '#22c55e' : '#ef4444'};
    `;

    const statusText = el('div');
    statusText.innerHTML = ollamaStatus?.reachable
      ? `<strong style="color: #22c55e;">Connected</strong> <span style="color: rgba(255,255,255,0.7);">- ${ollamaStatus.model_count} models available</span>`
      : `<strong style="color: #ef4444;">Not Connected</strong> <span style="color: rgba(255,255,255,0.7);">- ${ollamaStatus?.error || 'Unknown error'}</span>`;
    statusText.style.cssText = 'flex: 1;';

    const testBtn = el('button');
    testBtn.textContent = 'Test Connection';
    testBtn.style.cssText = `
      padding: 6px 12px;
      background: rgba(59, 130, 246, 0.2);
      border: 1px solid rgba(59, 130, 246, 0.4);
      border-radius: 4px;
      color: #3b82f6;
      cursor: pointer;
      font-size: 12px;
    `;
    testBtn.addEventListener('click', async () => {
      testBtn.textContent = 'Testing...';
      testBtn.style.opacity = '0.6';
      try {
        const result = await kernelRequest('ollama/test_connection', {}) as { reachable: boolean; error?: string };
        if (result.reachable) {
          testBtn.textContent = '✓ Connected!';
          testBtn.style.color = '#22c55e';
          testBtn.style.borderColor = '#22c55e';
        } else {
          testBtn.textContent = '✗ Failed';
          testBtn.style.color = '#ef4444';
          testBtn.style.borderColor = '#ef4444';
        }
        await loadData();
      } catch {
        testBtn.textContent = '✗ Error';
        testBtn.style.color = '#ef4444';
      }
      testBtn.style.opacity = '1';
      setTimeout(() => {
        testBtn.textContent = 'Test Connection';
        testBtn.style.color = '#3b82f6';
        testBtn.style.borderColor = 'rgba(59, 130, 246, 0.4)';
      }, 2000);
    });

    statusBox.appendChild(statusIndicator);
    statusBox.appendChild(statusText);
    statusBox.appendChild(testBtn);
    statusSection.appendChild(statusBox);

    // Show install prompt if Ollama not installed
    if (ollamaInstallStatus && !ollamaInstallStatus.installed) {
      const installBox = el('div');
      installBox.style.cssText = `
        padding: 16px;
        background: rgba(245, 158, 11, 0.1);
        border: 1px solid rgba(245, 158, 11, 0.3);
        border-radius: 8px;
        margin-bottom: 16px;
      `;
      installBox.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px;">
          <span style="font-size: 24px;">⚠️</span>
          <div style="flex: 1;">
            <strong style="color: #f59e0b;">Ollama Not Installed</strong>
            <p style="margin: 4px 0 0 0; color: rgba(255,255,255,0.7); font-size: 13px;">
              Install Ollama for local AI inference. Your data stays on your machine.
            </p>
          </div>
        </div>
        <div style="margin-top: 12px; display: flex; align-items: center; gap: 8px;">
          <code style="flex: 1; padding: 8px 12px; background: rgba(0,0,0,0.3); border-radius: 4px; font-size: 12px; color: #a5f3fc;">
            ${ollamaInstallStatus.install_command}
          </code>
          <button id="copyOllamaInstallCmd" style="padding: 8px 12px; background: #3b82f6; border: none; border-radius: 4px; color: #fff; cursor: pointer; font-size: 12px; white-space: nowrap;">
            Copy
          </button>
        </div>
      `;
      statusSection.appendChild(installBox);

      // Wire up copy button
      const copyBtn = document.getElementById('copyOllamaInstallCmd');
      const installCmd = ollamaInstallStatus.install_command;
      if (copyBtn && installCmd) {
        copyBtn.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(installCmd);
            copyBtn.textContent = 'Copied!';
            setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
          } catch {
            copyBtn.textContent = 'Failed';
            setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
          }
        });
      }
    }

    content.appendChild(statusSection);


    // URL Setting
    const urlRow = createSettingRow('Ollama URL', 'The address where Ollama is running');
    const urlInput = el('input') as HTMLInputElement;
    urlInput.type = 'text';
    urlInput.value = ollamaStatus?.url || 'http://localhost:11434';
    urlInput.style.cssText = `
      flex: 1;
      padding: 8px 12px;
      background: rgba(0,0,0,0.3);
      border: 1px solid #444;
      border-radius: 4px;
      color: #fff;
      font-family: monospace;
      font-size: 13px;
    `;

    const urlSaveBtn = el('button');
    urlSaveBtn.textContent = 'Save';
    urlSaveBtn.style.cssText = `
      padding: 8px 16px;
      background: #3b82f6;
      border: none;
      border-radius: 4px;
      color: #fff;
      cursor: pointer;
      font-size: 13px;
    `;
    urlSaveBtn.addEventListener('click', async () => {
      try {
        await kernelRequest('ollama/set_url', { url: urlInput.value });
        await loadData();
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        alert('Failed to save URL: ' + msg);
      }
    });

    urlRow.appendChild(urlInput);
    urlRow.appendChild(urlSaveBtn);
    statusSection.appendChild(urlRow);

    content.appendChild(statusSection);

    // Hardware & Inference Section
    const hardwareSection = createSection('Hardware & Inference');

    // Hardware info box
    const hw = ollamaStatus?.hardware;
    const hardwareBox = el('div');
    hardwareBox.style.cssText = `
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
      margin-bottom: 16px;
    `;

    // RAM info
    const ramBox = el('div');
    ramBox.style.cssText = `
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
    `;
    ramBox.innerHTML = `
      <div style="font-size: 11px; color: rgba(255,255,255,0.5); margin-bottom: 4px;">System RAM</div>
      <div style="font-size: 16px; font-weight: 500; color: #fff;">${hw?.ram_gb || 0} GB</div>
    `;
    hardwareBox.appendChild(ramBox);

    // GPU info
    const gpuBox = el('div');
    gpuBox.style.cssText = `
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
    `;
    if (hw?.gpu_available) {
      gpuBox.innerHTML = `
        <div style="font-size: 11px; color: rgba(255,255,255,0.5); margin-bottom: 4px;">GPU (${hw.gpu_type?.toUpperCase() || 'GPU'})</div>
        <div style="font-size: 14px; font-weight: 500; color: #22c55e;">${hw.gpu_name || 'Available'}</div>
        <div style="font-size: 12px; color: rgba(255,255,255,0.6);">${hw.gpu_vram_gb || '?'} GB VRAM</div>
      `;
    } else {
      gpuBox.innerHTML = `
        <div style="font-size: 11px; color: rgba(255,255,255,0.5); margin-bottom: 4px;">GPU</div>
        <div style="font-size: 14px; font-weight: 500; color: #f59e0b;">Not Detected</div>
        <div style="font-size: 11px; color: rgba(255,255,255,0.5);">CPU inference only</div>
      `;
    }
    hardwareBox.appendChild(gpuBox);
    hardwareSection.appendChild(hardwareBox);

    // Recommended models note
    const recommendedNote = el('div');
    recommendedNote.style.cssText = `
      padding: 10px 12px;
      background: rgba(59, 130, 246, 0.1);
      border: 1px solid rgba(59, 130, 246, 0.3);
      border-radius: 6px;
      font-size: 12px;
      color: rgba(255,255,255,0.8);
      margin-bottom: 16px;
    `;
    const maxParams = hw?.recommended_max_params?.toUpperCase() || '3B';
    const gpuVram = hw?.gpu_vram_gb || 0;
    const sysRam = hw?.ram_gb || 0;

    let speedNote = '';
    if (hw?.gpu_available && sysRam > gpuVram * 2) {
      speedNote = `<div style="margin-top: 6px; font-size: 11px; color: rgba(255,255,255,0.6);">
        ⚡ Models ≤${gpuVram}GB run fully on GPU (fastest). Larger models use CPU offloading (slower but possible up to ${sysRam}GB).
      </div>`;
    }

    recommendedNote.innerHTML = `
      💡 <strong>Recommended:</strong> Based on your ${sysRam}GB RAM${hw?.gpu_available ? ` + ${gpuVram}GB VRAM` : ''}, models up to <strong>${maxParams} parameters</strong> should run.
      ${speedNote}
    `;
    hardwareSection.appendChild(recommendedNote);

    // GPU toggle (only show if GPU is available)
    if (hw?.gpu_available) {
      const gpuToggleRow = el('div');
      gpuToggleRow.style.cssText = `
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px;
        background: rgba(0,0,0,0.2);
        border-radius: 8px;
        margin-bottom: 12px;
      `;

      const gpuLabel = el('div');
      gpuLabel.innerHTML = `
        <div style="font-size: 13px; font-weight: 500; color: #fff;">GPU Acceleration</div>
        <div style="font-size: 11px; color: rgba(255,255,255,0.5);">Use GPU for faster inference (recommended)</div>
      `;

      const gpuToggle = el('button');
      const gpuEnabled = ollamaStatus?.gpu_enabled !== false;
      gpuToggle.textContent = gpuEnabled ? 'Enabled' : 'Disabled';
      gpuToggle.style.cssText = `
        padding: 6px 16px;
        background: ${gpuEnabled ? 'rgba(34, 197, 94, 0.2)' : 'rgba(255,255,255,0.1)'};
        border: 1px solid ${gpuEnabled ? '#22c55e' : '#444'};
        border-radius: 4px;
        color: ${gpuEnabled ? '#22c55e' : 'rgba(255,255,255,0.6)'};
        cursor: pointer;
        font-size: 12px;
        min-width: 80px;
      `;
      gpuToggle.addEventListener('click', async () => {
        const newValue = !gpuEnabled;
        try {
          await kernelRequest('ollama/set_gpu', { enabled: newValue });
          await loadData();
        } catch (e) {
          alert('Failed to update GPU setting');
        }
      });

      gpuToggleRow.appendChild(gpuLabel);
      gpuToggleRow.appendChild(gpuToggle);
      hardwareSection.appendChild(gpuToggleRow);
    } else {
      // Show warning that GPU is not available
      const gpuWarning = el('div');
      gpuWarning.style.cssText = `
        padding: 10px 12px;
        background: rgba(245, 158, 11, 0.1);
        border: 1px solid rgba(245, 158, 11, 0.3);
        border-radius: 6px;
        font-size: 12px;
        color: #f59e0b;
        margin-bottom: 12px;
      `;
      gpuWarning.innerHTML = `
        ⚠️ <strong>GPU not available for Ollama.</strong> Inference will use CPU only, which is slower.
        For GPU support, install NVIDIA CUDA drivers or AMD ROCm.
      `;
      hardwareSection.appendChild(gpuWarning);
    }

    // Context length setting
    const ctxRow = el('div');
    ctxRow.style.cssText = `
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
    `;

    const currentCtx = ollamaStatus?.num_ctx || selectedModelInfo?.context_length || 4096;
    const maxCtx = selectedModelInfo?.context_length || 8192;

    ctxRow.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <div>
          <div style="font-size: 13px; font-weight: 500; color: #fff;">Context Length</div>
          <div style="font-size: 11px; color: rgba(255,255,255,0.5);">Max tokens the model can remember (affects memory usage)</div>
        </div>
        <div style="font-family: monospace; font-size: 14px; color: #3b82f6;" id="ctx-value">${currentCtx.toLocaleString()}</div>
      </div>
    `;

    const ctxSlider = el('input') as HTMLInputElement;
    ctxSlider.type = 'range';
    ctxSlider.min = '512';
    ctxSlider.max = String(Math.min(maxCtx * 2, 131072));
    ctxSlider.step = '512';
    ctxSlider.value = String(currentCtx);
    ctxSlider.style.cssText = `
      width: 100%;
      accent-color: #3b82f6;
    `;

    ctxSlider.addEventListener('input', () => {
      const valueEl = ctxRow.querySelector('#ctx-value');
      if (valueEl) valueEl.textContent = parseInt(ctxSlider.value).toLocaleString();
    });

    ctxSlider.addEventListener('change', async () => {
      try {
        await kernelRequest('ollama/set_context', { num_ctx: parseInt(ctxSlider.value) });
      } catch (e) {
        alert('Failed to update context length');
      }
    });

    ctxRow.appendChild(ctxSlider);

    const ctxHint = el('div');
    ctxHint.style.cssText = 'font-size: 10px; color: rgba(255,255,255,0.4); margin-top: 6px;';
    ctxHint.textContent = `Model default: ${maxCtx.toLocaleString()} tokens. Higher values use more memory.`;
    ctxRow.appendChild(ctxHint);

    hardwareSection.appendChild(ctxRow);
    content.appendChild(hardwareSection);

    // Model Selection Section
    const modelSection = createSection('Model Selection');

    // Current model box with more details
    const currentModelBox = el('div');
    currentModelBox.style.cssText = `
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
      margin-bottom: 16px;
    `;

    const modelName = ollamaStatus?.model || 'Not set';
    const paramSize = selectedModelInfo?.parameter_size || '';
    const ctxLen = selectedModelInfo?.context_length;
    const quantization = selectedModelInfo?.quantization || '';
    const caps = selectedModelInfo?.capabilities;

    currentModelBox.innerHTML = `
      <div style="margin-bottom: 4px; color: rgba(255,255,255,0.7); font-size: 12px;">Current Model</div>
      <div style="font-size: 16px; font-weight: 500; color: #fff; margin-bottom: 8px;">${modelName}</div>
      ${paramSize || ctxLen || quantization ? `
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;">
          ${paramSize ? `<div style="font-size: 11px; padding: 3px 8px; background: rgba(59,130,246,0.2); border-radius: 4px; color: #60a5fa;">${paramSize} params</div>` : ''}
          ${ctxLen ? `<div style="font-size: 11px; padding: 3px 8px; background: rgba(34,197,94,0.2); border-radius: 4px; color: #4ade80;">${ctxLen.toLocaleString()} ctx</div>` : ''}
          ${quantization ? `<div style="font-size: 11px; padding: 3px 8px; background: rgba(168,85,247,0.2); border-radius: 4px; color: #c084fc;">${quantization}</div>` : ''}
        </div>
      ` : ''}
      ${caps ? `
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <div style="font-size: 10px; color: rgba(255,255,255,0.5);">Capabilities:</div>
          ${caps.tools ? `<div style="font-size: 10px; padding: 2px 6px; background: rgba(34,197,94,0.2); border-radius: 3px; color: #4ade80;">🔧 Tools</div>` : `<div style="font-size: 10px; padding: 2px 6px; background: rgba(255,255,255,0.05); border-radius: 3px; color: rgba(255,255,255,0.3);">🔧 Tools</div>`}
          ${caps.vision ? `<div style="font-size: 10px; padding: 2px 6px; background: rgba(34,197,94,0.2); border-radius: 3px; color: #4ade80;">👁️ Vision</div>` : `<div style="font-size: 10px; padding: 2px 6px; background: rgba(255,255,255,0.05); border-radius: 3px; color: rgba(255,255,255,0.3);">👁️ Vision</div>`}
          ${caps.thinking ? `<div style="font-size: 10px; padding: 2px 6px; background: rgba(34,197,94,0.2); border-radius: 3px; color: #4ade80;">🧠 Thinking</div>` : `<div style="font-size: 10px; padding: 2px 6px; background: rgba(255,255,255,0.05); border-radius: 3px; color: rgba(255,255,255,0.3);">🧠 Thinking</div>`}
          ${caps.embedding ? `<div style="font-size: 10px; padding: 2px 6px; background: rgba(34,197,94,0.2); border-radius: 3px; color: #4ade80;">📊 Embed</div>` : ''}
        </div>
      ` : ''}
    `;
    modelSection.appendChild(currentModelBox);

    // Available models
    if (ollamaStatus?.available_models && ollamaStatus.available_models.length > 0) {
      const modelsLabel = el('div');
      modelsLabel.textContent = 'Available Models';
      modelsLabel.style.cssText = 'margin-bottom: 8px; font-size: 13px; color: rgba(255,255,255,0.7);';
      modelSection.appendChild(modelsLabel);

      const modelsList = el('div');
      modelsList.style.cssText = `
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 16px;
      `;

      for (const model of ollamaStatus.available_models) {
        const modelBtn = el('button');
        modelBtn.textContent = model;
        const isActive = model === ollamaStatus.model;
        modelBtn.style.cssText = `
          padding: 6px 12px;
          background: ${isActive ? 'rgba(34, 197, 94, 0.2)' : 'rgba(255,255,255,0.05)'};
          border: 1px solid ${isActive ? '#22c55e' : '#444'};
          border-radius: 4px;
          color: ${isActive ? '#22c55e' : 'rgba(255,255,255,0.8)'};
          cursor: pointer;
          font-size: 12px;
        `;
        modelBtn.addEventListener('click', async () => {
          try {
            await kernelRequest('ollama/set_model', { model });
            await loadData();
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            alert('Failed to set model: ' + msg);
          }
        });
        modelsList.appendChild(modelBtn);
      }
      modelSection.appendChild(modelsList);
    }

    // Popular Models Section
    const popularLabel = el('div');
    popularLabel.textContent = 'Recommended Models';
    popularLabel.style.cssText = 'margin-bottom: 8px; font-size: 13px; color: rgba(255,255,255,0.7);';
    modelSection.appendChild(popularLabel);

    // Models with full specs - sorted by size for hardware recommendations
    // caps: { tools?, vision?, thinking? }
    const allPopularModels = [
      { name: 'phi3:mini', params: '3.8B', desc: 'Microsoft\'s compact model', size: '2.3GB', ramNeeded: 4, ctx: 4096, caps: {} },
      { name: 'llama3.2:3b', params: '3B', desc: 'Meta\'s efficient small model', size: '2.0GB', ramNeeded: 4, ctx: 8192, caps: { tools: true } },
      { name: 'gemma2:2b', params: '2B', desc: 'Google\'s tiny powerhouse', size: '1.6GB', ramNeeded: 3, ctx: 8192, caps: {} },
      { name: 'qwen2.5:3b', params: '3B', desc: 'Alibaba\'s multilingual', size: '2.0GB', ramNeeded: 4, ctx: 32768, caps: { tools: true } },
      { name: 'llava:7b', params: '7B', desc: 'Vision-language model', size: '4.7GB', ramNeeded: 8, ctx: 4096, caps: { vision: true } },
      { name: 'mistral:7b', params: '7B', desc: 'Fast & efficient', size: '4.1GB', ramNeeded: 8, ctx: 32768, caps: { tools: true } },
      { name: 'llama3.2:latest', params: '8B', desc: 'Meta\'s latest balanced', size: '4.7GB', ramNeeded: 8, ctx: 8192, caps: { tools: true } },
      { name: 'llama3.1:8b', params: '8B', desc: 'High quality general', size: '4.7GB', ramNeeded: 8, ctx: 8192, caps: { tools: true } },
      { name: 'qwq:latest', params: '32B', desc: 'Alibaba reasoning model', size: '20GB', ramNeeded: 24, ctx: 32768, caps: { thinking: true } },
      { name: 'deepseek-r1:7b', params: '7B', desc: 'DeepSeek reasoning', size: '4.7GB', ramNeeded: 8, ctx: 16384, caps: { thinking: true } },
      { name: 'deepseek-r1:14b', params: '14B', desc: 'DeepSeek reasoning', size: '9GB', ramNeeded: 16, ctx: 16384, caps: { thinking: true } },
      { name: 'codellama:7b', params: '7B', desc: 'Optimized for coding', size: '3.8GB', ramNeeded: 8, ctx: 16384, caps: {} },
      { name: 'deepseek-coder:6.7b', params: '6.7B', desc: 'Code specialist', size: '3.8GB', ramNeeded: 8, ctx: 16384, caps: {} },
      { name: 'gemma2:9b', params: '9B', desc: 'Google\'s capable model', size: '5.4GB', ramNeeded: 10, ctx: 8192, caps: {} },
      { name: 'llava:13b', params: '13B', desc: 'Larger vision model', size: '8GB', ramNeeded: 16, ctx: 4096, caps: { vision: true } },
      { name: 'qwen2.5:14b', params: '14B', desc: 'Strong multilingual', size: '9GB', ramNeeded: 16, ctx: 32768, caps: { tools: true } },
      { name: 'deepseek-r1:32b', params: '32B', desc: 'DeepSeek reasoning', size: '20GB', ramNeeded: 24, ctx: 16384, caps: { thinking: true } },
      { name: 'codellama:34b', params: '34B', desc: 'Advanced coding', size: '19GB', ramNeeded: 24, ctx: 16384, caps: {} },
      { name: 'llava:34b', params: '34B', desc: 'Large vision model', size: '20GB', ramNeeded: 24, ctx: 4096, caps: { vision: true } },
      { name: 'mixtral:8x7b', params: '47B', desc: 'MoE, fast for size', size: '26GB', ramNeeded: 32, ctx: 32768, caps: { tools: true } },
      { name: 'deepseek-r1:70b', params: '70B', desc: 'DeepSeek reasoning', size: '43GB', ramNeeded: 48, ctx: 16384, caps: { thinking: true } },
      { name: 'llama3.1:70b', params: '70B', desc: 'Meta\'s flagship', size: '40GB', ramNeeded: 48, ctx: 8192, caps: { tools: true } },
      { name: 'qwen2.5:72b', params: '72B', desc: 'Top-tier multilingual', size: '42GB', ramNeeded: 48, ctx: 32768, caps: { tools: true } },
      { name: 'deepseek-coder:33b', params: '33B', desc: 'Expert coder', size: '19GB', ramNeeded: 24, ctx: 16384, caps: {} },
      { name: 'llama3.1:405b', params: '405B', desc: 'Largest open model', size: '230GB', ramNeeded: 256, ctx: 8192, caps: { tools: true } },
    ];

    // Filter models based on available memory
    // Use max of GPU VRAM and RAM since Ollama can offload to CPU
    const gpuMem = hw?.gpu_vram_gb || 0;
    const ramMem = hw?.ram_gb || 8;
    const availableMem = Math.max(gpuMem, ramMem);
    const popularModels = allPopularModels.filter(m => m.ramNeeded <= availableMem + 4); // +4GB buffer

    const popularGrid = el('div');
    popularGrid.style.cssText = `
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
      margin-bottom: 16px;
    `;

    for (const model of popularModels) {
      const isInstalled = ollamaStatus?.available_models?.some(m => m.startsWith(model.name.split(':')[0]));
      const modelCard = el('button');
      modelCard.style.cssText = `
        padding: 10px 12px;
        background: ${isInstalled ? 'rgba(34, 197, 94, 0.1)' : 'rgba(255,255,255,0.03)'};
        border: 1px solid ${isInstalled ? 'rgba(34, 197, 94, 0.3)' : '#333'};
        border-radius: 6px;
        text-align: left;
        cursor: ${isInstalled ? 'default' : 'pointer'};
        transition: all 0.2s;
      `;
      if (!isInstalled) {
        modelCard.addEventListener('mouseenter', () => {
          modelCard.style.background = 'rgba(59, 130, 246, 0.1)';
          modelCard.style.borderColor = 'rgba(59, 130, 246, 0.4)';
        });
        modelCard.addEventListener('mouseleave', () => {
          modelCard.style.background = 'rgba(255,255,255,0.03)';
          modelCard.style.borderColor = '#333';
        });
      }

      // Build capability badges
      const capBadges: string[] = [];
      if (model.caps.tools) capBadges.push('<span style="color: #4ade80;">🔧</span>');
      if (model.caps.vision) capBadges.push('<span style="color: #60a5fa;">👁️</span>');
      if (model.caps.thinking) capBadges.push('<span style="color: #f472b6;">🧠</span>');
      const capBadgeHtml = capBadges.length > 0 ? `<span style="margin-left: 6px;">${capBadges.join(' ')}</span>` : '';

      modelCard.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px;">
          <div style="font-size: 13px; font-weight: 500; color: #fff;">
            ${model.name} ${isInstalled ? '<span style="color: #22c55e; font-size: 11px;">✓</span>' : ''}${capBadgeHtml}
          </div>
          <div style="font-size: 10px; padding: 2px 6px; background: rgba(59,130,246,0.2); border-radius: 3px; color: #60a5fa;">
            ${model.params}
          </div>
        </div>
        <div style="font-size: 11px; color: rgba(255,255,255,0.5); margin-bottom: 4px;">${model.desc}</div>
        <div style="display: flex; gap: 8px; font-size: 10px; color: rgba(255,255,255,0.4);">
          <span>📦 ${model.size}</span>
          <span>📝 ${model.ctx.toLocaleString()} ctx</span>
        </div>
      `;

      if (!isInstalled) {
        modelCard.addEventListener('click', async () => {
          // Disable hover effects during download
          modelCard.onmouseenter = null;
          modelCard.onmouseleave = null;
          modelCard.style.cursor = 'default';
          modelCard.style.background = 'rgba(59, 130, 246, 0.1)';
          modelCard.style.borderColor = 'rgba(59, 130, 246, 0.4)';

          modelCard.innerHTML = `
            <div style="font-size: 13px; font-weight: 500; color: #3b82f6; margin-bottom: 4px;">
              Downloading ${model.name}...
            </div>
            <div style="height: 6px; background: rgba(0,0,0,0.3); border-radius: 3px; overflow: hidden; margin-bottom: 4px;">
              <div class="progress-bar" style="height: 100%; width: 0%; background: #3b82f6; transition: width 0.3s;"></div>
            </div>
            <div class="progress-text" style="font-size: 11px; color: rgba(255,255,255,0.5);">Starting...</div>
          `;

          const progressBar = modelCard.querySelector('.progress-bar') as HTMLElement;
          const progressText = modelCard.querySelector('.progress-text') as HTMLElement;

          try {
            await downloadModelWithProgress(model.name, (status) => {
              if (progressBar) progressBar.style.width = `${status.progress}%`;
              if (progressText) {
                if (status.total > 0) {
                  progressText.textContent = `${status.progress}% - ${formatBytes(status.completed)} / ${formatBytes(status.total)}`;
                } else {
                  progressText.textContent = status.status || 'Downloading...';
                }
              }
            });

            modelCard.style.background = 'rgba(34, 197, 94, 0.1)';
            modelCard.style.borderColor = 'rgba(34, 197, 94, 0.3)';
            modelCard.innerHTML = `
              <div style="font-size: 13px; font-weight: 500; color: #22c55e; margin-bottom: 2px;">
                ✓ ${model.name}
              </div>
              <div style="font-size: 11px; color: rgba(255,255,255,0.5);">Download complete!</div>
            `;
            setTimeout(() => void loadData(), 1500);
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            modelCard.style.background = 'rgba(239, 68, 68, 0.1)';
            modelCard.style.borderColor = 'rgba(239, 68, 68, 0.3)';
            modelCard.innerHTML = `
              <div style="font-size: 13px; font-weight: 500; color: #ef4444; margin-bottom: 2px;">✗ Failed</div>
              <div style="font-size: 11px; color: rgba(255,255,255,0.5);">${msg}</div>
            `;
          }
        });
      }
      popularGrid.appendChild(modelCard);
    }
    modelSection.appendChild(popularGrid);

    // Custom model download
    const downloadRow = createSettingRow('Download Other Model', 'Enter any model from ollama.com/library');
    const downloadInput = el('input') as HTMLInputElement;
    downloadInput.type = 'text';
    downloadInput.placeholder = 'e.g., qwen2:7b, solar:10.7b';
    downloadInput.style.cssText = `
      flex: 1;
      padding: 8px 12px;
      background: rgba(0,0,0,0.3);
      border: 1px solid #444;
      border-radius: 4px;
      color: #fff;
      font-size: 13px;
    `;

    const downloadBtn = el('button');
    downloadBtn.textContent = 'Download';
    downloadBtn.style.cssText = `
      padding: 8px 16px;
      background: #22c55e;
      border: none;
      border-radius: 4px;
      color: #fff;
      cursor: pointer;
      font-size: 13px;
      min-width: 100px;
    `;

    // Progress indicator for custom download (replaces input row during download)
    const progressContainer = el('div');
    progressContainer.style.cssText = `
      display: none;
      flex-direction: column;
      gap: 4px;
      flex: 1;
    `;
    progressContainer.innerHTML = `
      <div class="dl-model-name" style="font-size: 13px; color: #3b82f6; font-weight: 500;"></div>
      <div style="height: 6px; background: rgba(0,0,0,0.3); border-radius: 3px; overflow: hidden;">
        <div class="dl-progress-bar" style="height: 100%; width: 0%; background: #3b82f6; transition: width 0.3s;"></div>
      </div>
      <div class="dl-progress-text" style="font-size: 11px; color: rgba(255,255,255,0.5);">Starting...</div>
    `;

    downloadBtn.addEventListener('click', async () => {
      const modelName = downloadInput.value.trim();
      if (!modelName) return;

      // Hide input, show progress
      downloadInput.style.display = 'none';
      downloadBtn.style.display = 'none';
      progressContainer.style.display = 'flex';

      const modelNameEl = progressContainer.querySelector('.dl-model-name') as HTMLElement;
      const progressBar = progressContainer.querySelector('.dl-progress-bar') as HTMLElement;
      const progressText = progressContainer.querySelector('.dl-progress-text') as HTMLElement;

      if (modelNameEl) modelNameEl.textContent = `Downloading ${modelName}...`;

      try {
        await downloadModelWithProgress(modelName, (status) => {
          if (progressBar) progressBar.style.width = `${status.progress}%`;
          if (progressText) {
            if (status.total > 0) {
              progressText.textContent = `${status.progress}% - ${formatBytes(status.completed)} / ${formatBytes(status.total)}`;
            } else {
              progressText.textContent = status.status || 'Downloading...';
            }
          }
        });

        if (modelNameEl) modelNameEl.textContent = `✓ ${modelName} downloaded!`;
        modelNameEl.style.color = '#22c55e';
        if (progressBar) progressBar.style.background = '#22c55e';
        if (progressText) progressText.textContent = 'Complete';

        downloadInput.value = '';
        setTimeout(() => void loadData(), 1500);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        if (modelNameEl) {
          modelNameEl.textContent = `✗ Failed: ${modelName}`;
          modelNameEl.style.color = '#ef4444';
        }
        if (progressBar) progressBar.style.background = '#ef4444';
        if (progressText) progressText.textContent = msg;
      }

      // Reset after a delay
      setTimeout(() => {
        progressContainer.style.display = 'none';
        downloadInput.style.display = 'block';
        downloadBtn.style.display = 'block';
        if (modelNameEl) modelNameEl.style.color = '#3b82f6';
        if (progressBar) {
          progressBar.style.width = '0%';
          progressBar.style.background = '#3b82f6';
        }
        if (progressText) progressText.textContent = 'Starting...';
      }, 3000);
    });

    downloadRow.appendChild(downloadInput);
    downloadRow.appendChild(progressContainer);
    downloadRow.appendChild(downloadBtn);
    modelSection.appendChild(downloadRow);

    content.appendChild(modelSection);
  }

  // Default values for Reset to Default - per agent type
  const DEFAULT_PROMPTS: Record<AgentType, { system: string; context: string }> = {
    cairn: {
      system: `You are CAIRN - the Contextual Attention & Information Resource Navigator.
You help users manage their attention and stay on top of what matters.

Core behaviors:
- Surface what needs attention based on priority and time
- Never guilt-trip or coerce - gentle nudges only
- Help users understand their commitments and priorities
- Connect calendar events with knowledge and context
- Be conversational and supportive

You surface the next thing, not everything. Priority is user-driven.`,
      context: `CAIRN principles:
- Time-aware: Consider calendar, deadlines, and patterns
- Priority-driven: User sets priority, CAIRN surfaces accordingly
- Contact-aware: Link knowledge to people when relevant
- Never gamifies: No streaks, scores, or manipulation
- Transparent: Explain why something is surfaced

When surfacing items:
- Explain the reason clearly
- Respect user's mental state
- Offer but don't push`,
    },
    riva: {
      system: `You are RIVA - the Recursive Intention-Verification Architecture.
You help users build and modify code through iterative refinement.

Core behaviors:
- Understand intent before writing code
- Break complex tasks into verifiable steps
- Write tests first when appropriate
- Explain your reasoning at each step
- Ask for clarification rather than assume

Principle: "If you can't verify it, decompose it."`,
      context: `RIVA principles:
- Intent first: Understand what the user wants before coding
- Verification: Each step should be testable
- Transparency: Show reasoning and decisions
- Safety: Never run destructive commands without confirmation
- Quality: Write clean, maintainable code

When coding:
- Start with understanding the codebase
- Plan before implementing
- Test changes when possible
- Explain what you're doing`,
    },
    reos: {
      system: `You are ReOS - the operating system interface.
You help users interact with their Linux system through natural language.

Core behaviors:
- Translate intent into system commands
- Explain what commands will do before running
- Protect the user from dangerous operations
- Provide context about system state
- Be efficient and direct

Safety is paramount. Never run risky commands without explicit confirmation.`,
      context: `ReOS principles:
- Permission-based: Ask before destructive actions
- Transparent: Show commands and explain effects
- Protective: Warn about risks and consequences
- Efficient: Minimize user effort for common tasks
- Educational: Help users understand their system

When executing:
- Preview commands before running
- Explain potential side effects
- Offer safer alternatives when available
- Respect system boundaries`,
    },
  };

  function renderPersonaTab() {
    // Agent selector tabs
    const agentTabs = el('div');
    agentTabs.style.cssText = `
      display: flex;
      gap: 4px;
      margin-bottom: 20px;
      padding: 4px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
    `;

    const agentConfig: Record<AgentType, { label: string; icon: string; description: string }> = {
      cairn: { label: 'CAIRN', icon: '🪨', description: 'Attention Minder - Conversations & Knowledge' },
      riva: { label: 'RIVA', icon: '⚡', description: 'Code Mode - Build & Modify Code' },
      reos: { label: 'ReOS', icon: '💻', description: 'Terminal - Direct System Access' },
    };

    for (const [agentType, config] of Object.entries(agentConfig)) {
      const btn = el('button');
      const isActive = selectedPersonaAgent === agentType;
      btn.innerHTML = `<span style="font-size: 14px;">${config.icon}</span> ${config.label}`;
      btn.title = config.description;
      btn.style.cssText = `
        flex: 1;
        padding: 10px 8px;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 12px;
        font-weight: 500;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        ${isActive
          ? 'background: rgba(59, 130, 246, 0.3); color: #fff;'
          : 'background: transparent; color: rgba(255,255,255,0.5);'
        }
      `;
      btn.addEventListener('click', () => {
        selectedPersonaAgent = agentType as AgentType;
        render();
      });
      agentTabs.appendChild(btn);
    }

    content.appendChild(agentTabs);

    // Agent description
    const agentDesc = el('div');
    agentDesc.style.cssText = `
      padding: 12px 16px;
      background: rgba(59, 130, 246, 0.1);
      border: 1px solid rgba(59, 130, 246, 0.2);
      border-radius: 8px;
      margin-bottom: 20px;
    `;
    agentDesc.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
        <span style="font-size: 18px;">${agentConfig[selectedPersonaAgent].icon}</span>
        <strong style="color: #fff;">${agentConfig[selectedPersonaAgent].label}</strong>
      </div>
      <div style="color: rgba(255,255,255,0.7); font-size: 12px;">
        ${agentConfig[selectedPersonaAgent].description}
      </div>
    `;
    content.appendChild(agentDesc);

    // Find or create persona for selected agent
    let agentPersona = personas.find(p => p.agent_type === selectedPersonaAgent);
    if (!agentPersona) {
      // Create default persona for this agent
      agentPersona = {
        id: `persona-${selectedPersonaAgent}`,
        name: `${agentConfig[selectedPersonaAgent].label} Persona`,
        agent_type: selectedPersonaAgent,
        system_prompt: DEFAULT_PROMPTS[selectedPersonaAgent].system,
        default_context: DEFAULT_PROMPTS[selectedPersonaAgent].context,
        temperature: selectedPersonaAgent === 'riva' ? 0.3 : 0.7,
        top_p: 0.9,
        tool_call_limit: selectedPersonaAgent === 'riva' ? 8 : 5,
      };
    }

    // System Prompt Section
    const promptsSection = createSection('System Prompt');
    promptsSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.7); font-size: 13px; margin-bottom: 12px;">
        The core instructions that define ${agentConfig[selectedPersonaAgent].label}'s personality and behavior.
      </div>
    `;

    const systemPromptTextarea = el('textarea') as HTMLTextAreaElement;
    systemPromptTextarea.value = agentPersona.system_prompt;
    systemPromptTextarea.style.cssText = `
      width: 100%;
      min-height: 180px;
      padding: 12px;
      background: rgba(0,0,0,0.3);
      border: 1px solid #444;
      border-radius: 8px;
      color: #fff;
      font-size: 12px;
      font-family: monospace;
      resize: vertical;
      margin-bottom: 12px;
    `;

    const systemPromptBtnRow = el('div');
    systemPromptBtnRow.style.cssText = 'display: flex; gap: 8px; margin-bottom: 16px;';

    const saveSystemPromptBtn = el('button');
    saveSystemPromptBtn.textContent = 'Save System Prompt';
    saveSystemPromptBtn.style.cssText = `
      padding: 8px 16px;
      background: #3b82f6;
      border: none;
      border-radius: 6px;
      color: #fff;
      cursor: pointer;
      font-size: 12px;
    `;
    saveSystemPromptBtn.addEventListener('click', async () => {
      agentPersona!.system_prompt = systemPromptTextarea.value;
      await savePersona(agentPersona!);
      saveSystemPromptBtn.textContent = 'Saved!';
      setTimeout(() => { saveSystemPromptBtn.textContent = 'Save System Prompt'; }, 1500);
    });

    const resetSystemPromptBtn = el('button');
    resetSystemPromptBtn.textContent = 'Reset to Default';
    resetSystemPromptBtn.style.cssText = `
      padding: 8px 16px;
      background: rgba(255,255,255,0.1);
      border: 1px solid #555;
      border-radius: 6px;
      color: rgba(255,255,255,0.8);
      cursor: pointer;
      font-size: 12px;
    `;
    resetSystemPromptBtn.addEventListener('click', async () => {
      const defaults = DEFAULT_PROMPTS[selectedPersonaAgent];
      systemPromptTextarea.value = defaults.system;
      agentPersona!.system_prompt = defaults.system;
      await savePersona(agentPersona!);
      resetSystemPromptBtn.textContent = 'Reset!';
      setTimeout(() => { resetSystemPromptBtn.textContent = 'Reset to Default'; }, 1500);
    });

    systemPromptBtnRow.appendChild(saveSystemPromptBtn);
    systemPromptBtnRow.appendChild(resetSystemPromptBtn);

    promptsSection.appendChild(systemPromptTextarea);
    promptsSection.appendChild(systemPromptBtnRow);
    content.appendChild(promptsSection);

    // Default Context Section
    const contextSection = createSection('Default Context');
    contextSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.7); font-size: 13px; margin-bottom: 12px;">
        Additional context provided to every ${agentConfig[selectedPersonaAgent].label} conversation.
      </div>
    `;

    const contextTextarea = el('textarea') as HTMLTextAreaElement;
    contextTextarea.value = agentPersona.default_context || '';
    contextTextarea.placeholder = 'Add custom instructions, preferences, or context here...';
    contextTextarea.style.cssText = `
      width: 100%;
      min-height: 120px;
      padding: 12px;
      background: rgba(0,0,0,0.3);
      border: 1px solid #444;
      border-radius: 8px;
      color: #fff;
      font-size: 12px;
      font-family: monospace;
      resize: vertical;
      margin-bottom: 12px;
    `;

    const contextBtnRow = el('div');
    contextBtnRow.style.cssText = 'display: flex; gap: 8px; margin-bottom: 16px;';

    const saveContextBtn = el('button');
    saveContextBtn.textContent = 'Save Default Context';
    saveContextBtn.style.cssText = `
      padding: 8px 16px;
      background: #3b82f6;
      border: none;
      border-radius: 6px;
      color: #fff;
      cursor: pointer;
      font-size: 12px;
    `;
    saveContextBtn.addEventListener('click', async () => {
      agentPersona!.default_context = contextTextarea.value;
      await savePersona(agentPersona!);
      saveContextBtn.textContent = 'Saved!';
      setTimeout(() => { saveContextBtn.textContent = 'Save Default Context'; }, 1500);
    });

    const resetContextBtn = el('button');
    resetContextBtn.textContent = 'Reset to Default';
    resetContextBtn.style.cssText = `
      padding: 8px 16px;
      background: rgba(255,255,255,0.1);
      border: 1px solid #555;
      border-radius: 6px;
      color: rgba(255,255,255,0.8);
      cursor: pointer;
      font-size: 12px;
    `;
    resetContextBtn.addEventListener('click', async () => {
      const defaults = DEFAULT_PROMPTS[selectedPersonaAgent];
      contextTextarea.value = defaults.context;
      agentPersona!.default_context = defaults.context;
      await savePersona(agentPersona!);
      resetContextBtn.textContent = 'Reset!';
      setTimeout(() => { resetContextBtn.textContent = 'Reset to Default'; }, 1500);
    });

    contextBtnRow.appendChild(saveContextBtn);
    contextBtnRow.appendChild(resetContextBtn);

    contextSection.appendChild(contextTextarea);
    contextSection.appendChild(contextBtnRow);
    content.appendChild(contextSection);

    // Parameters Section
    const paramsSection = createSection('LLM Parameters');

    // Temperature
    const tempParam = createParameterControl(
      'Temperature',
      agentPersona.temperature,
      0, 2, 0.1,
      'Controls randomness in responses. Lower values (0.1-0.3) make responses more focused and deterministic. Higher values (0.7-1.0) make responses more creative and varied.',
      async (val) => {
        agentPersona!.temperature = val;
        await savePersona(agentPersona!);
      }
    );
    paramsSection.appendChild(tempParam);

    // Top P
    const topPParam = createParameterControl(
      'Top P (Nucleus Sampling)',
      agentPersona.top_p,
      0, 1, 0.05,
      'Controls diversity by limiting to top probability tokens. At 0.9, only tokens in the top 90% probability mass are considered.',
      async (val) => {
        agentPersona!.top_p = val;
        await savePersona(agentPersona!);
      }
    );
    paramsSection.appendChild(topPParam);

    // Tool Call Limit
    const toolParam = createParameterControl(
      'Tool Call Limit',
      agentPersona.tool_call_limit,
      1, 10, 1,
      `Maximum number of tools ${agentConfig[selectedPersonaAgent].label} can use in a single response.`,
      async (val) => {
        agentPersona!.tool_call_limit = Math.round(val);
        await savePersona(agentPersona!);
      }
    );
    paramsSection.appendChild(toolParam);

    content.appendChild(paramsSection);
  }

  function renderSafetyTab() {
    // Header explanation
    const headerInfo = el('div');
    headerInfo.style.cssText = `
      padding: 16px;
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid rgba(239, 68, 68, 0.2);
      border-radius: 8px;
      margin-bottom: 20px;
    `;
    headerInfo.innerHTML = `
      <div style="display: flex; align-items: flex-start; gap: 12px;">
        <span style="font-size: 24px;">🛡️</span>
        <div>
          <div style="font-weight: 600; color: #fff; margin-bottom: 4px;">Safety Circuit Breakers</div>
          <div style="font-size: 13px; color: rgba(255,255,255,0.7); line-height: 1.5;">
            These hard limits prevent runaway behavior and protect your system from the "paperclip problem" -
            an AI optimizing without boundaries. These limits <strong>cannot be removed</strong>, but can be tuned
            within safe ranges.
          </div>
        </div>
      </div>
    `;
    content.appendChild(headerInfo);

    if (!safetySettings) {
      const loading = el('div');
      loading.textContent = 'Loading safety settings...';
      loading.style.cssText = 'color: rgba(255,255,255,0.6); text-align: center; padding: 20px;';
      content.appendChild(loading);
      return;
    }

    // ============ Rate Limits Section ============
    const rateLimitsSection = createSection('Rate Limits');
    rateLimitsSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.6); font-size: 12px; margin-bottom: 12px;">
        Limits on how frequently certain operations can be performed. Prevents resource exhaustion and brute-force attacks.
      </div>
    `;

    const rateLimitsGrid = el('div');
    rateLimitsGrid.style.cssText = `
      display: grid;
      gap: 12px;
    `;

    for (const [key, config] of Object.entries(safetySettings.rate_limits)) {
      const limitCard = el('div');
      limitCard.style.cssText = `
        padding: 12px;
        background: rgba(0,0,0,0.2);
        border-radius: 8px;
        border-left: 3px solid #3b82f6;
      `;

      const windowLabel = config.window_seconds >= 60
        ? `${config.window_seconds / 60} min`
        : `${config.window_seconds}s`;

      limitCard.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <div>
            <div style="font-weight: 500; color: #fff; font-size: 13px;">${config.name}</div>
            <div style="font-size: 11px; color: rgba(255,255,255,0.5);">Category: ${key}</div>
          </div>
          <div style="text-align: right;">
            <div style="font-family: monospace; color: #3b82f6; font-size: 14px;">
              ${config.max_requests} / ${windowLabel}
            </div>
          </div>
        </div>
      `;

      // Slider for max_requests
      const sliderRow = el('div');
      sliderRow.style.cssText = 'display: flex; align-items: center; gap: 8px;';

      const slider = el('input') as HTMLInputElement;
      slider.type = 'range';
      slider.min = '1';
      slider.max = key === 'auth' ? '10' : '50';
      slider.value = String(config.max_requests);
      slider.style.cssText = 'flex: 1; accent-color: #3b82f6;';

      const valueLabel = el('span');
      valueLabel.textContent = String(config.max_requests);
      valueLabel.style.cssText = 'font-family: monospace; color: #3b82f6; min-width: 30px; text-align: right;';

      slider.addEventListener('input', () => {
        valueLabel.textContent = slider.value;
      });

      slider.addEventListener('change', async () => {
        try {
          await kernelRequest('safety/set_rate_limit', {
            category: key,
            max_requests: parseInt(slider.value),
            window_seconds: config.window_seconds,
          });
          config.max_requests = parseInt(slider.value);
        } catch (e) {
          console.error('Failed to update rate limit:', e);
        }
      });

      sliderRow.appendChild(slider);
      sliderRow.appendChild(valueLabel);
      limitCard.appendChild(sliderRow);

      rateLimitsGrid.appendChild(limitCard);
    }

    rateLimitsSection.appendChild(rateLimitsGrid);
    content.appendChild(rateLimitsSection);

    // ============ Sudo Escalation Section ============
    const sudoSection = createSection('Sudo Escalation Limit');
    sudoSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.6); font-size: 12px; margin-bottom: 12px;">
        Maximum number of sudo commands allowed per session. Prevents privilege escalation spirals.
      </div>
    `;

    const sudoCard = el('div');
    sudoCard.style.cssText = `
      padding: 16px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
      border-left: 3px solid #f59e0b;
    `;

    sudoCard.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div>
          <div style="font-weight: 500; color: #fff;">Max Sudo Escalations</div>
          <div style="font-size: 11px; color: rgba(255,255,255,0.5);">
            Current session: ${safetySettings.current_sudo_count} / ${safetySettings.max_sudo_escalations} used
          </div>
        </div>
        <div id="sudo-value" style="font-family: monospace; font-size: 18px; color: #f59e0b;">
          ${safetySettings.max_sudo_escalations}
        </div>
      </div>
    `;

    const sudoSlider = el('input') as HTMLInputElement;
    sudoSlider.type = 'range';
    sudoSlider.min = '1';
    sudoSlider.max = '10';
    sudoSlider.value = String(safetySettings.max_sudo_escalations);
    sudoSlider.style.cssText = 'width: 100%; accent-color: #f59e0b;';

    sudoSlider.addEventListener('input', () => {
      const valueEl = sudoCard.querySelector('#sudo-value');
      if (valueEl) valueEl.textContent = sudoSlider.value;
    });

    sudoSlider.addEventListener('change', async () => {
      try {
        await kernelRequest('safety/set_sudo_limit', {
          max_escalations: parseInt(sudoSlider.value),
        });
        safetySettings!.max_sudo_escalations = parseInt(sudoSlider.value);
      } catch (e) {
        console.error('Failed to update sudo limit:', e);
      }
    });

    sudoCard.appendChild(sudoSlider);
    sudoSection.appendChild(sudoCard);
    content.appendChild(sudoSection);

    // ============ Command Length Section ============
    const commandSection = createSection('Command Length Limit');
    commandSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.6); font-size: 12px; margin-bottom: 12px;">
        Maximum length of shell commands. Prevents buffer overflow attacks and command injection.
      </div>
    `;

    const commandCard = el('div');
    commandCard.style.cssText = `
      padding: 16px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
    `;

    commandCard.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div style="font-weight: 500; color: #fff;">Max Command Length</div>
        <div id="cmd-value" style="font-family: monospace; font-size: 16px; color: #22c55e;">
          ${safetySettings.max_command_length.toLocaleString()} chars
        </div>
      </div>
    `;

    const cmdSlider = el('input') as HTMLInputElement;
    cmdSlider.type = 'range';
    cmdSlider.min = '1024';
    cmdSlider.max = '16384';
    cmdSlider.step = '512';
    cmdSlider.value = String(safetySettings.max_command_length);
    cmdSlider.style.cssText = 'width: 100%; accent-color: #22c55e;';

    cmdSlider.addEventListener('input', () => {
      const valueEl = commandCard.querySelector('#cmd-value');
      if (valueEl) valueEl.textContent = parseInt(cmdSlider.value).toLocaleString() + ' chars';
    });

    cmdSlider.addEventListener('change', async () => {
      try {
        await kernelRequest('safety/set_command_length', {
          max_length: parseInt(cmdSlider.value),
        });
        safetySettings!.max_command_length = parseInt(cmdSlider.value);
      } catch (e) {
        console.error('Failed to update command length:', e);
      }
    });

    commandCard.appendChild(cmdSlider);
    commandSection.appendChild(commandCard);
    content.appendChild(commandSection);

    // ============ Agent Execution Limits ============
    const agentSection = createSection('Agent Execution Limits');
    agentSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.6); font-size: 12px; margin-bottom: 12px;">
        Limits on how long agents can run. Prevents runaway execution and infinite loops.
      </div>
    `;

    const agentGrid = el('div');
    agentGrid.style.cssText = 'display: grid; grid-template-columns: 1fr 1fr; gap: 12px;';

    // Max Iterations
    const iterCard = el('div');
    iterCard.style.cssText = `
      padding: 16px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
      border-left: 3px solid #8b5cf6;
    `;
    iterCard.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div>
          <div style="font-weight: 500; color: #fff;">Max Iterations</div>
          <div style="font-size: 11px; color: rgba(255,255,255,0.5);">
            Loops before forced stop
          </div>
        </div>
        <div id="iter-value" style="font-family: monospace; font-size: 18px; color: #8b5cf6;">
          ${safetySettings.max_iterations}
        </div>
      </div>
    `;

    const iterSlider = el('input') as HTMLInputElement;
    iterSlider.type = 'range';
    iterSlider.min = '3';
    iterSlider.max = '50';
    iterSlider.value = String(safetySettings.max_iterations);
    iterSlider.style.cssText = 'width: 100%; accent-color: #8b5cf6;';

    iterSlider.addEventListener('input', () => {
      const valueEl = iterCard.querySelector('#iter-value');
      if (valueEl) valueEl.textContent = iterSlider.value;
    });

    iterSlider.addEventListener('change', async () => {
      try {
        await kernelRequest('safety/set_max_iterations', {
          max_iterations: parseInt(iterSlider.value),
        });
        safetySettings!.max_iterations = parseInt(iterSlider.value);
      } catch (e) {
        console.error('Failed to update max iterations:', e);
      }
    });

    iterCard.appendChild(iterSlider);
    agentGrid.appendChild(iterCard);

    // Wall Clock Timeout
    const timeoutCard = el('div');
    timeoutCard.style.cssText = `
      padding: 16px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
      border-left: 3px solid #ec4899;
    `;

    const formatTime = (seconds: number): string => {
      if (seconds >= 60) {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return secs > 0 ? `${mins}m ${secs}s` : `${mins} min`;
      }
      return `${seconds}s`;
    };

    timeoutCard.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div>
          <div style="font-weight: 500; color: #fff;">Wall Clock Timeout</div>
          <div style="font-size: 11px; color: rgba(255,255,255,0.5);">
            Max real-time execution
          </div>
        </div>
        <div id="timeout-value" style="font-family: monospace; font-size: 18px; color: #ec4899;">
          ${formatTime(safetySettings.wall_clock_timeout_seconds)}
        </div>
      </div>
    `;

    const timeoutSlider = el('input') as HTMLInputElement;
    timeoutSlider.type = 'range';
    timeoutSlider.min = '60';
    timeoutSlider.max = '1800';
    timeoutSlider.step = '30';
    timeoutSlider.value = String(safetySettings.wall_clock_timeout_seconds);
    timeoutSlider.style.cssText = 'width: 100%; accent-color: #ec4899;';

    timeoutSlider.addEventListener('input', () => {
      const valueEl = timeoutCard.querySelector('#timeout-value');
      if (valueEl) valueEl.textContent = formatTime(parseInt(timeoutSlider.value));
    });

    timeoutSlider.addEventListener('change', async () => {
      try {
        await kernelRequest('safety/set_wall_clock_timeout', {
          timeout_seconds: parseInt(timeoutSlider.value),
        });
        safetySettings!.wall_clock_timeout_seconds = parseInt(timeoutSlider.value);
      } catch (e) {
        console.error('Failed to update wall clock timeout:', e);
      }
    });

    timeoutCard.appendChild(timeoutSlider);
    agentGrid.appendChild(timeoutCard);

    agentSection.appendChild(agentGrid);
    content.appendChild(agentSection);

    // ============ Pattern Detection (Read-only) ============
    const patternsSection = createSection('Blocked Patterns (Read-only)');
    patternsSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.6); font-size: 12px; margin-bottom: 12px;">
        Hardcoded patterns that detect and block dangerous operations. These cannot be disabled.
      </div>
    `;

    const patternsGrid = el('div');
    patternsGrid.style.cssText = 'display: grid; grid-template-columns: 1fr 1fr; gap: 12px;';

    // Dangerous commands
    const dangerousCard = el('div');
    dangerousCard.style.cssText = `
      padding: 16px;
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid rgba(239, 68, 68, 0.2);
      border-radius: 8px;
    `;
    dangerousCard.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
        <span style="font-size: 18px;">🚫</span>
        <div style="font-weight: 500; color: #ef4444;">Dangerous Commands</div>
      </div>
      <div style="font-size: 24px; font-weight: 600; color: #fff; margin-bottom: 4px;">
        ${safetySettings.dangerous_pattern_count}
      </div>
      <div style="font-size: 11px; color: rgba(255,255,255,0.5);">
        Patterns blocked (rm -rf, dd, fork bombs, etc.)
      </div>
    `;
    patternsGrid.appendChild(dangerousCard);

    // Injection detection
    const injectionCard = el('div');
    injectionCard.style.cssText = `
      padding: 16px;
      background: rgba(168, 85, 247, 0.1);
      border: 1px solid rgba(168, 85, 247, 0.2);
      border-radius: 8px;
    `;
    injectionCard.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
        <span style="font-size: 18px;">🔍</span>
        <div style="font-weight: 500; color: #a855f7;">Prompt Injection</div>
      </div>
      <div style="font-size: 24px; font-weight: 600; color: #fff; margin-bottom: 4px;">
        ${safetySettings.injection_pattern_count}
      </div>
      <div style="font-size: 11px; color: rgba(255,255,255,0.5);">
        Patterns detected (jailbreaks, role changes, etc.)
      </div>
    `;
    patternsGrid.appendChild(injectionCard);

    patternsSection.appendChild(patternsGrid);
    content.appendChild(patternsSection);

    // ============ Input Validation (Read-only) ============
    const validationSection = createSection('Input Validation Limits');
    validationSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.6); font-size: 12px; margin-bottom: 12px;">
        Maximum lengths for various input types. Prevents buffer-based attacks.
      </div>
    `;

    const validationGrid = el('div');
    validationGrid.style.cssText = 'display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;';

    const validationLimits = [
      { name: 'Service Name', value: safetySettings.max_service_name_length },
      { name: 'Container ID', value: safetySettings.max_container_id_length },
      { name: 'Package Name', value: safetySettings.max_package_name_length },
    ];

    for (const limit of validationLimits) {
      const limitBox = el('div');
      limitBox.style.cssText = `
        padding: 12px;
        background: rgba(0,0,0,0.2);
        border-radius: 6px;
        text-align: center;
      `;
      limitBox.innerHTML = `
        <div style="font-size: 11px; color: rgba(255,255,255,0.5); margin-bottom: 4px;">${limit.name}</div>
        <div style="font-family: monospace; font-size: 16px; color: #fff;">${limit.value}</div>
        <div style="font-size: 10px; color: rgba(255,255,255,0.4);">max chars</div>
      `;
      validationGrid.appendChild(limitBox);
    }

    validationSection.appendChild(validationGrid);
    content.appendChild(validationSection);
  }

  function createSection(title: string): HTMLElement {
    const section = el('div');
    section.style.cssText = 'margin-bottom: 24px;';

    const header = el('div');
    header.textContent = title;
    header.style.cssText = `
      font-size: 15px;
      font-weight: 600;
      color: #fff;
      margin-bottom: 12px;
      padding-bottom: 8px;
      border-bottom: 1px solid #333;
    `;

    section.appendChild(header);
    return section;
  }

  function createSettingRow(label: string, description: string): HTMLElement {
    const row = el('div');
    row.style.cssText = 'margin-bottom: 12px;';

    const labelEl = el('div');
    labelEl.innerHTML = `<strong>${label}</strong>`;
    labelEl.style.cssText = 'margin-bottom: 4px; font-size: 13px; color: #fff;';

    const descEl = el('div');
    descEl.textContent = description;
    descEl.style.cssText = 'font-size: 11px; color: rgba(255,255,255,0.6); margin-bottom: 8px;';

    const inputRow = el('div');
    inputRow.style.cssText = 'display: flex; gap: 8px;';

    row.appendChild(labelEl);
    row.appendChild(descEl);
    row.appendChild(inputRow);

    return inputRow;
  }

  function createPromptBox(title: string, description: string, content: string): HTMLElement {
    const box = el('div');
    box.style.cssText = `
      margin-bottom: 16px;
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
      border-left: 3px solid #3b82f6;
    `;

    const titleEl = el('div');
    titleEl.innerHTML = `<strong>${title}</strong>`;
    titleEl.style.cssText = 'margin-bottom: 4px; font-size: 13px; color: #fff;';

    const descEl = el('div');
    descEl.textContent = description;
    descEl.style.cssText = 'font-size: 11px; color: rgba(255,255,255,0.6); margin-bottom: 8px;';

    const contentEl = el('pre');
    contentEl.textContent = content.length > 500 ? content.slice(0, 500) + '...' : content;
    contentEl.style.cssText = `
      margin: 0;
      padding: 8px;
      background: rgba(0,0,0,0.3);
      border-radius: 4px;
      font-size: 11px;
      color: rgba(255,255,255,0.8);
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 150px;
      overflow: auto;
    `;

    box.appendChild(titleEl);
    box.appendChild(descEl);
    box.appendChild(contentEl);

    return box;
  }

  function createParameterControl(
    name: string,
    value: number,
    min: number,
    max: number,
    step: number,
    description: string,
    onChange: (val: number) => Promise<void>
  ): HTMLElement {
    const container = el('div');
    container.style.cssText = `
      margin-bottom: 20px;
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
    `;

    const header = el('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;';

    const nameEl = el('div');
    nameEl.innerHTML = `<strong>${name}</strong>`;
    nameEl.style.cssText = 'font-size: 13px; color: #fff;';

    const valueEl = el('div');
    valueEl.textContent = value.toFixed(step < 1 ? 2 : 0);
    valueEl.style.cssText = 'font-family: monospace; font-size: 14px; color: #3b82f6;';

    header.appendChild(nameEl);
    header.appendChild(valueEl);

    const slider = el('input') as HTMLInputElement;
    slider.type = 'range';
    slider.min = String(min);
    slider.max = String(max);
    slider.step = String(step);
    slider.value = String(value);
    slider.style.cssText = `
      width: 100%;
      margin-bottom: 8px;
      accent-color: #3b82f6;
    `;

    slider.addEventListener('input', () => {
      valueEl.textContent = parseFloat(slider.value).toFixed(step < 1 ? 2 : 0);
    });

    slider.addEventListener('change', async () => {
      await onChange(parseFloat(slider.value));
    });

    const descEl = el('div');
    descEl.textContent = description;
    descEl.style.cssText = 'font-size: 11px; color: rgba(255,255,255,0.6); line-height: 1.4;';

    container.appendChild(header);
    container.appendChild(slider);
    container.appendChild(descEl);

    return container;
  }

  async function savePersona(persona: PersonaData) {
    try {
      await kernelRequest('personas/upsert', { persona });
    } catch (e) {
      console.error('Failed to save persona:', e);
    }
  }

  return {
    element: overlay,
    show,
    hide,
  };
}
