import { test, expect } from '@playwright/test';

test.describe('Agent Chat UI', () => {
  test('should render chat page with welcome message', async ({ page }) => {
    await page.goto('/agent');
    await expect(page.locator('h2')).toHaveText('智能助理');

    // Should show the welcome message
    await expect(page.getByText('EZStore 報價單管理助手')).toBeVisible();
    await expect(page.getByText('查詢、複製、修改報價單')).toBeVisible();

    // Should have input field and send button
    await expect(page.getByPlaceholder('輸入您的指令...')).toBeVisible();
    await expect(page.getByRole('button', { name: '送出' })).toBeVisible();
  });

  test('should have agent link in sidebar navigation', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('aside');
    await expect(sidebar.getByText('智能助理')).toBeVisible();

    // Click and verify navigation
    await sidebar.getByText('智能助理').click();
    await expect(page).toHaveURL(/\/agent$/);
    await expect(page.locator('h2')).toHaveText('智能助理');
  });

  test('should show user message in chat after typing and sending', async ({ page }) => {
    await page.goto('/agent');

    const input = page.getByPlaceholder('輸入您的指令...');
    await input.fill('我要查詢報價單');

    // Send button should be enabled
    const sendButton = page.getByRole('button', { name: '送出' });
    await expect(sendButton).toBeEnabled();

    await sendButton.click();

    // User message should appear
    await expect(page.getByText('我要查詢報價單')).toBeVisible();

    // Input should be cleared
    await expect(input).toHaveValue('');
  });

  test('recovers once when an Agent restart invalidates the browser session', async ({ page }) => {
    let sessionCalls = 0;
    let runCalls = 0;
    await page.route('**/agent-api/apps/quotation_agent/users/web-user/sessions', async route => {
      sessionCalls += 1;
      await route.fulfill({ json: { id: sessionCalls === 1 ? 'stale-session' : 'fresh-session' } });
    });
    await page.route('**/agent-api/run_sse', async route => {
      runCalls += 1;
      const body = route.request().postDataJSON();
      if (runCalls === 1) {
        expect(body.session_id).toBe('stale-session');
        await route.fulfill({ status: 404, body: 'session not found' });
        return;
      }
      expect(body.session_id).toBe('fresh-session');
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"author":"quotation_agent","nodeInfo":{"path":"quotation_agent@1/respond@1"},"content":{"parts":[{"text":"重新連線成功"}]}}\n\n',
      });
    });

    await page.goto('/agent');
    await page.getByPlaceholder('輸入您的指令...').fill('查詢報價單 QT-20260330-001');
    await page.getByRole('button', { name: '送出' }).click();

    await expect(page.getByText('重新連線成功')).toBeVisible();
    await expect(page.getByText(/Agent request failed/)).toHaveCount(0);
    expect(sessionCalls).toBe(2);
    expect(runCalls).toBe(2);
  });
});
