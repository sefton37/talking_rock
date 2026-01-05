/**
 * Settings Overlay - Configuration panel for ReOS
 *
 * Tabs:
 * - LLM Provider: Ollama connection, model selection, downloads
 * - Agent Persona: Prompts review, parameters, customization
 */

import { kernelRequest } from './kernel';
import { el } from './dom';

type SettingsTab = 'llm' | 'persona';

interface OllamaStatus {
  url: string;
  model: string;
  reachable: boolean;
  model_count: number | null;
  error: string | null;
  available_models: string[];
}

interface PersonaData {
  id: string;
  name: string;
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

export function createSettingsOverlay(onClose?: () => void): SettingsOverlay {
  // State
  let activeTab: SettingsTab = 'llm';
  let ollamaStatus: OllamaStatus | null = null;
  let personas: PersonaData[] = [];
  let activePersonaId: string | null = null;
  let customContext: string = '';

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

  tabsContainer.appendChild(llmTab);
  tabsContainer.appendChild(personaTab);

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
    try {
      // Load Ollama status
      ollamaStatus = await kernelRequest('ollama/status', {}) as OllamaStatus;

      // Load personas
      const personasResult = await kernelRequest('personas/list', {}) as {
        personas: PersonaData[];
        active_persona_id: string | null;
      };
      personas = personasResult.personas || [];
      activePersonaId = personasResult.active_persona_id;

      render();
    } catch (e) {
      console.error('Failed to load settings:', e);
    }
  }

  function render() {
    // Update tab styles
    llmTab.style.color = activeTab === 'llm' ? '#fff' : 'rgba(255,255,255,0.6)';
    llmTab.style.borderBottomColor = activeTab === 'llm' ? '#3b82f6' : 'transparent';
    personaTab.style.color = activeTab === 'persona' ? '#fff' : 'rgba(255,255,255,0.6)';
    personaTab.style.borderBottomColor = activeTab === 'persona' ? '#3b82f6' : 'transparent';

    content.innerHTML = '';

    if (activeTab === 'llm') {
      renderLLMTab();
    } else {
      renderPersonaTab();
    }
  }

  function renderLLMTab() {
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
      try {
        const result = await kernelRequest('ollama/test_connection', {}) as { reachable: boolean };
        await loadData();
      } catch (e) {
        console.error('Test failed:', e);
      }
      testBtn.textContent = 'Test Connection';
    });

    statusBox.appendChild(statusIndicator);
    statusBox.appendChild(statusText);
    statusBox.appendChild(testBtn);
    statusSection.appendChild(statusBox);

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

    // Model Selection Section
    const modelSection = createSection('Model Selection');

    const currentModelBox = el('div');
    currentModelBox.style.cssText = `
      padding: 12px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
      margin-bottom: 16px;
    `;
    currentModelBox.innerHTML = `
      <div style="margin-bottom: 8px; color: rgba(255,255,255,0.7); font-size: 12px;">Current Model</div>
      <div style="font-size: 16px; font-weight: 500; color: #fff;">${ollamaStatus?.model || 'Not set'}</div>
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

    // Download new model
    const downloadRow = createSettingRow('Download New Model', 'Enter a model name from ollama.com/library');
    const downloadInput = el('input') as HTMLInputElement;
    downloadInput.type = 'text';
    downloadInput.placeholder = 'e.g., llama3.2, mistral, codellama';
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
    `;
    downloadBtn.addEventListener('click', async () => {
      const modelName = downloadInput.value.trim();
      if (!modelName) return;

      downloadBtn.textContent = 'Downloading...';
      downloadBtn.style.background = '#6b7280';

      try {
        const result = await kernelRequest('ollama/pull_model', { model: modelName }) as { message: string };
        alert(result.message);
        downloadInput.value = '';
        // Refresh after a delay to see new model
        setTimeout(() => void loadData(), 3000);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        alert('Download failed: ' + msg);
      }

      downloadBtn.textContent = 'Download';
      downloadBtn.style.background = '#22c55e';
    });

    downloadRow.appendChild(downloadInput);
    downloadRow.appendChild(downloadBtn);
    modelSection.appendChild(downloadRow);

    content.appendChild(modelSection);
  }

  function renderPersonaTab() {
    const activePersona = personas.find(p => p.id === activePersonaId) || personas[0];

    // Prompts Review Section
    const promptsSection = createSection('System Prompts & Context');
    promptsSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.7); font-size: 13px; margin-bottom: 12px;">
        These prompts shape how ReOS understands and responds to you. They're read-only for stability.
      </div>
    `;

    if (activePersona) {
      // System Prompt
      const systemPromptBox = createPromptBox(
        'System Prompt',
        'The core instructions that define ReOS personality and behavior',
        activePersona.system_prompt
      );
      promptsSection.appendChild(systemPromptBox);

      // Default Context
      const contextBox = createPromptBox(
        'Default Context',
        'Additional context provided to every conversation',
        activePersona.default_context || '(No default context set)'
      );
      promptsSection.appendChild(contextBox);
    }

    content.appendChild(promptsSection);

    // Parameters Section
    const paramsSection = createSection('LLM Parameters');

    if (activePersona) {
      // Temperature
      const tempParam = createParameterControl(
        'Temperature',
        activePersona.temperature,
        0, 2, 0.1,
        'Controls randomness in responses. Lower values (0.1-0.3) make responses more focused and deterministic. Higher values (0.7-1.0) make responses more creative and varied. Very high values (1.5+) can produce chaotic output.',
        async (val) => {
          activePersona.temperature = val;
          await savePersona(activePersona);
        }
      );
      paramsSection.appendChild(tempParam);

      // Top P
      const topPParam = createParameterControl(
        'Top P (Nucleus Sampling)',
        activePersona.top_p,
        0, 1, 0.05,
        'Controls diversity by limiting to top probability tokens. At 0.9, only tokens in the top 90% probability mass are considered. Lower values (0.5) give more predictable outputs. Higher values (0.95) allow more variety.',
        async (val) => {
          activePersona.top_p = val;
          await savePersona(activePersona);
        }
      );
      paramsSection.appendChild(topPParam);

      // Tool Call Limit
      const toolParam = createParameterControl(
        'Tool Call Limit',
        activePersona.tool_call_limit,
        1, 10, 1,
        'Maximum number of tools ReOS can use in a single response. Higher values let ReOS gather more information but may slow responses. Lower values keep responses quick but may limit capability.',
        async (val) => {
          activePersona.tool_call_limit = Math.round(val);
          await savePersona(activePersona);
        }
      );
      paramsSection.appendChild(toolParam);
    }

    content.appendChild(paramsSection);

    // Custom Context Section
    const customSection = createSection('Custom Persona Text');
    customSection.innerHTML += `
      <div style="color: rgba(255,255,255,0.7); font-size: 13px; margin-bottom: 12px;">
        Add your own text to customize how ReOS interacts with you. This is appended to the system prompt.
      </div>
    `;

    const customTextarea = el('textarea') as HTMLTextAreaElement;
    customTextarea.value = activePersona?.default_context || '';
    customTextarea.placeholder = 'Add custom instructions, preferences, or context here...\n\nExamples:\n- "Always explain technical concepts simply"\n- "I prefer concise responses"\n- "When writing code, add comments"';
    customTextarea.style.cssText = `
      width: 100%;
      min-height: 120px;
      padding: 12px;
      background: rgba(0,0,0,0.3);
      border: 1px solid #444;
      border-radius: 8px;
      color: #fff;
      font-size: 13px;
      resize: vertical;
      margin-bottom: 12px;
    `;

    const saveCustomBtn = el('button');
    saveCustomBtn.textContent = 'Save Custom Context';
    saveCustomBtn.style.cssText = `
      padding: 10px 20px;
      background: #3b82f6;
      border: none;
      border-radius: 6px;
      color: #fff;
      cursor: pointer;
      font-size: 13px;
    `;
    saveCustomBtn.addEventListener('click', async () => {
      if (activePersona) {
        activePersona.default_context = customTextarea.value;
        await savePersona(activePersona);
        saveCustomBtn.textContent = 'Saved!';
        setTimeout(() => { saveCustomBtn.textContent = 'Save Custom Context'; }, 1500);
      }
    });

    customSection.appendChild(customTextarea);
    customSection.appendChild(saveCustomBtn);

    content.appendChild(customSection);
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
