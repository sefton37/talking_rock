/**
 * DOM utility functions for ReOS UI.
 */

/**
 * Create an HTML element with optional attributes.
 */
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {}
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

/**
 * Create a section header element.
 */
export function rowHeader(text: string): HTMLDivElement {
  const h = el('div');
  h.textContent = text;
  h.style.fontWeight = '600';
  h.style.fontSize = '13px';
  h.style.margin = '10px 0 6px';
  return h;
}

/**
 * Create a label element.
 */
export function label(text: string): HTMLDivElement {
  const l = el('div');
  l.textContent = text;
  l.style.fontSize = '12px';
  l.style.opacity = '0.8';
  l.style.marginBottom = '4px';
  return l;
}

/**
 * Create a styled text input.
 */
export function textInput(value: string): HTMLInputElement {
  const i = el('input') as HTMLInputElement;
  i.type = 'text';
  i.value = value;
  i.style.width = '100%';
  i.style.boxSizing = 'border-box';
  i.style.padding = '8px 10px';
  i.style.border = '1px solid rgba(209, 213, 219, 0.7)';
  i.style.borderRadius = '10px';
  i.style.background = 'rgba(255, 255, 255, 0.55)';
  return i;
}

/**
 * Create a styled textarea.
 */
export function textArea(value: string, heightPx = 90): HTMLTextAreaElement {
  const t = el('textarea') as HTMLTextAreaElement;
  t.value = value;
  t.style.width = '100%';
  t.style.boxSizing = 'border-box';
  t.style.padding = '8px 10px';
  t.style.border = '1px solid rgba(209, 213, 219, 0.7)';
  t.style.borderRadius = '10px';
  t.style.background = 'rgba(255, 255, 255, 0.55)';
  t.style.minHeight = `${heightPx}px`;
  t.style.resize = 'vertical';
  return t;
}

/**
 * Create a small styled button.
 */
export function smallButton(text: string): HTMLButtonElement {
  const b = el('button') as HTMLButtonElement;
  b.textContent = text;
  b.style.padding = '8px 10px';
  b.style.border = '1px solid rgba(209, 213, 219, 0.65)';
  b.style.borderRadius = '10px';
  b.style.background = 'rgba(255, 255, 255, 0.35)';
  return b;
}
