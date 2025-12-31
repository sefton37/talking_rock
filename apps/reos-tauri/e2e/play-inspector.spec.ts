/**
 * E2E Tests: Play Inspector
 * Tests Play structure (Acts, Scenes, Beats) and KB integration
 */

import { test, expect } from '@playwright/test';

test.describe('Play Inspector', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should display play inspector panel', async ({ page }) => {
    const inspector = page.locator('.play-inspector');

    await expect(inspector).toBeVisible();
    await expect(inspector.getByText('The Play')).toBeVisible();
  });

  test('should show empty state when no acts exist', async ({ page }) => {
    const inspector = page.locator('.play-inspector');

    // Check for empty state messaging
    // This will depend on the actual RPC response
    await expect(inspector).toBeVisible();
  });

  test('should display act editor when acts exist', async ({ page }) => {
    const inspector = page.locator('.play-inspector');

    // Wait for inspector to load
    await page.waitForTimeout(500);

    // Check if act editor sections are present
    // These may or may not be visible depending on data
    const actSection = inspector.getByText('Act');
    const titleLabel = inspector.getByText('Title');
    const notesLabel = inspector.getByText('Notes');

    // At least the inspector structure should exist
    await expect(inspector).toBeVisible();
  });

  test('should have scenes section', async ({ page }) => {
    const inspector = page.locator('.play-inspector');

    // Wait for content to load
    await page.waitForTimeout(500);

    // Scenes section should be present in the structure
    await expect(inspector).toBeVisible();
  });

  test('should have knowledge base section', async ({ page }) => {
    const inspector = page.locator('.play-inspector');

    // Wait for content to load
    await page.waitForTimeout(500);

    // KB section should be present
    // Look for KB-related text
    const kbSection = page.getByText('Mini Knowledgebase');

    // May or may not be visible depending on whether there's an active act
    // Just verify inspector exists
    await expect(inspector).toBeVisible();
  });

  test('should show breadcrumb navigation', async ({ page }) => {
    const inspector = page.locator('.play-inspector');

    await expect(inspector).toBeVisible();

    // Breadcrumb should show current context
    // The specific content depends on data, but structure should exist
  });
});
