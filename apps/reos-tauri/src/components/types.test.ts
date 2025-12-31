/**
 * Tests for shared types and utilities
 */

import { describe, it, expect } from 'vitest';
import { KernelError, el, rowHeader, label, textInput, textArea, smallButton } from './types';

describe('KernelError', () => {
  it('should create error with message and code', () => {
    const error = new KernelError('Test error', -32600);
    expect(error.message).toBe('Test error');
    expect(error.code).toBe(-32600);
    expect(error.name).toBe('KernelError');
  });

  it('should be instanceof Error', () => {
    const error = new KernelError('Test', -32000);
    expect(error).toBeInstanceOf(Error);
  });
});

describe('el', () => {
  it('should create HTML element', () => {
    const div = el('div');
    expect(div.tagName).toBe('DIV');
  });

  it('should set attributes', () => {
    const input = el('input', { type: 'text', placeholder: 'Test' });
    expect(input.getAttribute('type')).toBe('text');
    expect(input.getAttribute('placeholder')).toBe('Test');
  });

  it('should create different element types', () => {
    expect(el('button').tagName).toBe('BUTTON');
    expect(el('span').tagName).toBe('SPAN');
    expect(el('textarea').tagName).toBe('TEXTAREA');
  });
});

describe('rowHeader', () => {
  it('should create header with title', () => {
    const header = rowHeader('Test Header');
    expect(header.textContent).toBe('Test Header');
    expect(header.style.fontWeight).toBe('600');
  });

  it('should have proper margins', () => {
    const header = rowHeader('Test');
    expect(header.style.marginTop).toBe('12px');
    expect(header.style.marginBottom).toBe('4px');
  });
});

describe('label', () => {
  it('should create label with text', () => {
    const lbl = label('Test Label');
    expect(lbl.textContent).toBe('Test Label');
    expect(lbl.style.fontSize).toBe('12px');
  });

  it('should have proper margins', () => {
    const lbl = label('Test');
    expect(lbl.style.marginTop).toBe('8px');
    expect(lbl.style.marginBottom).toBe('2px');
  });
});

describe('textInput', () => {
  it('should create input with value', () => {
    const input = textInput('test value');
    expect(input.value).toBe('test value');
    expect(input.type).toBe('text');
  });

  it('should have proper styling', () => {
    const input = textInput('');
    expect(input.style.width).toBe('100%');
    expect(input.style.border).toBe('1px solid #ccc');
  });
});

describe('textArea', () => {
  it('should create textarea with value', () => {
    const area = textArea('test content');
    expect(area.value).toBe('test content');
  });

  it('should set custom height', () => {
    const area = textArea('', 200);
    expect(area.style.minHeight).toBe('200px');
  });

  it('should use default height', () => {
    const area = textArea('');
    expect(area.style.minHeight).toBe('90px');
  });

  it('should have monospace font', () => {
    const area = textArea('');
    expect(area.style.fontFamily).toBe('monospace');
  });
});

describe('smallButton', () => {
  it('should create button with text', () => {
    const btn = smallButton('Click Me');
    expect(btn.textContent).toBe('Click Me');
  });

  it('should have small styling', () => {
    const btn = smallButton('Test');
    expect(btn.style.fontSize).toBe('12px');
    expect(btn.style.padding).toBe('4px 8px');
  });
});
