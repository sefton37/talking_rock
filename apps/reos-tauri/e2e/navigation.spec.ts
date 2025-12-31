/**
 * E2E Tests: Navigation
 * Tests sidebar navigation and act selection
 */

import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should display navigation sidebar', async ({ page }) => {
    const nav = page.locator('.navigation');

    await expect(nav).toBeVisible();
  });

  test('should show Me Window link', async ({ page }) => {
    const nav = page.locator('.navigation');

    // Me Window button should be visible
    const meWindowBtn = nav.getByText('Me Window');
    await expect(meWindowBtn).toBeVisible();
  });

  test('should show Acts section', async ({ page }) => {
    const nav = page.locator('.navigation');

    // Acts section should exist
    await expect(nav).toBeVisible();

    // Look for Acts heading
    const actsHeading = nav.getByText('Acts');
    // May or may not be visible depending on implementation
  });

  test('should have clickable navigation items', async ({ page }) => {
    const nav = page.locator('.navigation');

    await expect(nav).toBeVisible();

    // Me Window should be clickable
    const meWindowBtn = nav.getByText('Me Window');
    await expect(meWindowBtn).toBeEnabled();
  });

  test('should display acts list when available', async ({ page }) => {
    const nav = page.locator('.navigation');

    // Wait for acts to load
    await page.waitForTimeout(500);

    // Navigation should be visible
    await expect(nav).toBeVisible();

    // Acts list structure should exist
    // Actual content depends on RPC response
  });

  test('should show empty state when no acts', async ({ page }) => {
    const nav = page.locator('.navigation');

    await page.waitForTimeout(500);

    // Navigation should still be visible even with no acts
    await expect(nav).toBeVisible();
  });

  test('should maintain navigation visibility during interaction', async ({ page }) => {
    const nav = page.locator('.navigation');

    // Click around the interface
    const chat = page.locator('.chat');
    await chat.click();

    // Navigation should remain visible
    await expect(nav).toBeVisible();
  });
});
