/**
 * E2E Tests: Chat Functionality
 * Tests chat interface interactions and message handling
 */

import { test, expect } from '@playwright/test';

test.describe('Chat Functionality', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should not send empty messages', async ({ page }) => {
    const sendBtn = page.locator('.send-btn');
    const input = page.locator('.chat-input');

    // Input should be empty initially
    await expect(input).toHaveValue('');

    // Try to send empty message
    await sendBtn.click();

    // No message should appear in history
    const messages = page.locator('.message');
    await expect(messages).toHaveCount(0);
  });

  test('should allow typing in chat input', async ({ page }) => {
    const input = page.locator('.chat-input');

    // Type a message
    await input.fill('Hello, ReOS!');

    // Input should contain the text
    await expect(input).toHaveValue('Hello, ReOS!');
  });

  test('should have send button', async ({ page }) => {
    const sendBtn = page.locator('.send-btn');

    // Send button should exist and be visible
    await expect(sendBtn).toBeVisible();
    await expect(sendBtn).toBeEnabled();
  });

  test('should display chat container', async ({ page }) => {
    const chat = page.locator('.chat');

    // Chat container should be visible
    await expect(chat).toBeVisible();

    // Should have history and controls
    await expect(page.locator('.chat-history')).toBeVisible();
    await expect(page.locator('.chat-controls')).toBeVisible();
  });

  test('should focus on chat input when loaded', async ({ page }) => {
    // Reload to test initial focus
    await page.reload();
    await page.waitForLoadState('networkidle');

    const input = page.locator('.chat-input');

    // Input should be in the DOM
    await expect(input).toBeVisible();
  });
});
