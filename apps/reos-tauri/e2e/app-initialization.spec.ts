/**
 * E2E Tests: Application Initialization
 * Tests that the app loads correctly and all main components render
 */

import { test, expect } from '@playwright/test';

test.describe('Application Initialization', () => {
  test('should load the application', async ({ page }) => {
    await page.goto('/');

    // Wait for app to be ready
    await page.waitForLoadState('networkidle');

    // Check that main elements exist
    await expect(page.locator('#shell')).toBeVisible();
    await expect(page.locator('#inspection')).toBeVisible();
  });

  test('should display navigation sidebar', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Navigation should be visible
    const navigation = page.locator('.navigation');
    await expect(navigation).toBeVisible();

    // Should have "Me" window link
    await expect(navigation.getByText('Me Window')).toBeVisible();
  });

  test('should display chat interface', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Chat should be visible
    const chat = page.locator('.chat');
    await expect(chat).toBeVisible();

    // Should have input field and send button
    await expect(page.locator('.chat-input')).toBeVisible();
    await expect(page.locator('.send-btn')).toBeVisible();
  });

  test('should display play inspector', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Play inspector should be visible
    const inspector = page.locator('.play-inspector');
    await expect(inspector).toBeVisible();

    // Should show "The Play" heading
    await expect(inspector.getByText('The Play')).toBeVisible();
  });

  test('should have correct page title', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/ReOS/);
  });
});
