import { test, expect, type Page, type Route } from '@playwright/test';

const customers = [{ id: 1, name: '甲', tax_id: '00000001', level: 'A' }, { id: 2, name: '乙', tax_id: '00000002', level: 'B' }];
const product = { id: 1, name: '零成本產品', cost: '0', list_price: '100' };
const listing = (data: unknown[], total = data.length) => ({ data, total, page: 1, page_size: 100 });
async function fixtures(page: Page) {
  await page.route('**/api/v1/customers?*', r => r.fulfill({ json: listing(customers) }));
  await page.route('**/api/v1/products?*', r => r.fulfill({ json: listing([product]) }));
  await page.route('**/api/v1/pricing-factor/*', r => r.fulfill({ json: { pricing_factor: '1' } }));
}

test('zero cost yields full profit and a 100 percent margin', async ({ page }) => {
  await fixtures(page);
  await page.goto('/quotations/new');
  await page.locator('select').nth(0).selectOption('1');
  await expect(page.locator('input[type=number]').first()).toHaveValue('1');
  await page.locator('select').nth(1).selectOption('1');
  await expect(page.getByText('獲利金額', { exact: true }).locator('..')).toContainText('100.00');
  await expect(page.getByText('獲利率', { exact: true }).locator('..')).toContainText('100.0%');
});

test('a late customer default cannot overwrite the latest selection', async ({ page }) => {
  await fixtures(page);
  let first: Route | undefined;
  await page.route('**/api/v1/pricing-factor/A', async r => { first = r; });
  await page.route('**/api/v1/pricing-factor/B', r => r.fulfill({ json: { pricing_factor: '0.8' } }));
  await page.goto('/quotations/new');
  await page.locator('select').first().selectOption('1');
  await expect.poll(() => !!first).toBeTruthy();
  await page.locator('select').first().selectOption('2');
  await expect(page.locator('input[type=number]').first()).toHaveValue('0.8');
  await first!.fulfill({ json: { pricing_factor: '0.9' } });
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('button', { name: '儲存草稿' })).toBeEnabled();
  await expect(page.locator('input[type=number]').first()).toHaveValue('0.8');
});

test('manual factor survives a pending customer default response', async ({ page }) => {
  await fixtures(page);
  let held: Route | undefined;
  await page.route('**/api/v1/pricing-factor/A', async r => { held = r; });
  await page.goto('/quotations/new');
  await page.locator('select').first().selectOption('1');
  await expect.poll(() => !!held).toBeTruthy();
  await page.locator('input[type=number]').first().fill('1.2');
  await held!.fulfill({ json: { pricing_factor: '0.9' } });
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('button', { name: '儲存草稿' })).toBeEnabled();
  await expect(page.locator('input[type=number]').first()).toHaveValue('1.2');
});

test('dependency failure is visible, blocks saving, and can be retried', async ({ page }) => {
  await fixtures(page);
  let broken = true;
  await page.route('**/api/v1/products?*', r => broken ? r.fulfill({ status: 503, json: { error: 'unavailable' } }) : r.fulfill({ json: listing([product]) }));
  await page.goto('/quotations/new');
  await expect(page.getByRole('alert')).toContainText('報價資料載入失敗');
  await expect(page.getByRole('button', { name: '儲存草稿' })).toBeDisabled();
  broken = false;
  await page.getByRole('button', { name: '重新載入資料' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.locator('select').first().selectOption('1');
  await expect(page.getByRole('button', { name: '儲存草稿' })).toBeEnabled();
});

test('factor failure is visible and manual recovery enables saving', async ({ page }) => {
  await fixtures(page);
  await page.route('**/api/v1/pricing-factor/*', r => r.fulfill({ status: 503, json: { error: 'unavailable' } }));
  await page.goto('/quotations/new');
  await page.locator('select').first().selectOption('1');
  await expect(page.getByRole('alert')).toContainText('客戶報價因子載入失敗');
  await expect(page.getByRole('button', { name: '儲存草稿' })).toBeDisabled();
  await page.locator('input[type=number]').first().fill('1.2');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '儲存草稿' })).toBeEnabled();
});

test('both option lists include record 101 from the second page', async ({ page }) => {
  await fixtures(page);
  for (const kind of ['customers', 'products']) {
    await page.route(`**/api/v1/${kind}?*`, r => {
      const second = new URL(r.request().url()).searchParams.get('page') === '2';
      const ids = second ? [101] : Array.from({ length: 100 }, (_, i) => i + 1);
      return r.fulfill({ json: listing(ids.map(id => ({ ...(kind === 'customers' ? customers[0] : product), id, name: `選項${id}` })), 101) });
    });
  }
  await page.goto('/quotations/new');
  await page.locator('select').nth(0).selectOption('101');
  await page.locator('select').nth(1).selectOption('101');
  await expect(page.locator('select').nth(0)).toHaveValue('101');
  await expect(page.locator('select').nth(1)).toHaveValue('101');
});

test('empty successful SSE displays uncertain-result warning', async ({ page }) => {
  await page.route('**/agent-api/apps/*/users/*/sessions', r => r.fulfill({ json: { id: 'test-empty' } }));
  await page.route('**/agent-api/run_sse', r => r.fulfill({ contentType: 'text/event-stream', body: '' }));
  await page.goto('/agent');
  await page.getByPlaceholder('輸入您的指令...').fill('請複製報價單 QT-20260330-001');
  await page.getByRole('button', { name: '送出' }).click();
  await expect(page.getByText(/操作結果尚未確認/)).toBeVisible();
  await expect(page.getByRole('button', { name: '送出' })).toBeDisabled();
});

for (const sample of [
  { price: '650', factor: '0.3333', quantity: '3', unit: '216.65', total: '649.95' },
  { price: '1', factor: '1.0050', quantity: '3', unit: '1.01', total: '3.03' },
  { price: '0.01', factor: '0.5000', quantity: '1000', unit: '0.01', total: '10.00' },
]) {
  test(`rounded units drive preview and profit: ${sample.price} x ${sample.factor}`, async ({ page }) => {
    await fixtures(page);
    await page.route('**/api/v1/products?*', r => r.fulfill({ json: listing([{ ...product, list_price: sample.price }]) }));
    await page.goto('/quotations/new');
    await page.locator('select').first().selectOption('1');
    await page.waitForLoadState('networkidle');
    await page.locator('select').nth(1).selectOption('1');
    await page.locator('input[type=number]').first().fill(sample.factor);
    await page.locator('tbody input[type=number]').fill(sample.quantity);
    const cells=page.locator('tbody tr').first().locator('td');
    await expect(cells.nth(2)).toHaveText(sample.unit);
    await expect(cells.nth(4)).toHaveText(sample.total);
    await expect(page.getByText('總價', { exact: true }).locator('..')).toContainText(sample.total);
    await expect(page.getByText('獲利金額', { exact: true }).locator('..')).toContainText(sample.total);
  });
}

// 外部檢查回報：詳情頁讀不到一直顯示「載入中」、發佈／複製／刪除失敗沒有提示
const draft = {
  id: 900010, quotation_number: 'QT-TEST-ERR', customer_id: 1, customer: { id: 1, name: '甲' },
  customer_level: 'A', pricing_factor: '0.9', notes: '', status: 'draft',
  total_price: '90', profit_amount: '90', profit_rate: '1',
  items: [{ id: 1, product_id: 1, product_name: '零成本產品', list_price: '100', unit_price: '90', quantity: 1, subtotal: '90' }],
};
const apiError = (status: number, message: string) => ({ status, json: { error: { code: 'BAD_REQUEST', message } } });

test('detail pages show the load error instead of loading forever', async ({ page }) => {
  await page.route('**/api/v1/quotations/900010', r => r.fulfill(apiError(404, '報價單不存在')));
  await page.route('**/api/v1/orders/900010', r => r.fulfill(apiError(404, '訂單不存在')));
  await page.goto('/quotations/900010');
  await expect(page.getByRole('alert')).toHaveText('讀取報價單失敗：報價單不存在');
  await expect(page.getByText('載入中...')).toHaveCount(0);
  await page.goto('/orders/900010');
  await expect(page.getByRole('alert')).toHaveText('讀取訂單失敗：訂單不存在');
  await page.getByRole('button', { name: '返回列表' }).click();
  await expect(page).toHaveURL(/\/orders$/);
});

test('publish and duplicate failures show the backend message', async ({ page }) => {
  await page.route('**/api/v1/quotations/900010', r => r.fulfill({ json: draft }));
  await page.route('**/api/v1/quotations/900010/publish', r => r.fulfill(apiError(500, '資料庫暫時無法使用')));
  await page.route('**/api/v1/quotations/900010/duplicate', r => r.fulfill(apiError(400, '來源報價單不存在')));
  await page.goto('/quotations/900010');
  await page.getByRole('button', { name: '發佈' }).click();
  await expect(page.getByRole('alert')).toHaveText('發佈失敗：資料庫暫時無法使用');
  await page.getByRole('button', { name: '複製' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '複製失敗' })).toHaveText('複製失敗：來源報價單不存在');
  await expect(page).toHaveURL(/\/quotations\/900010$/);
});

test('failed delete closes the dialog and explains why', async ({ page }) => {
  await page.route('**/api/v1/quotations?*', r => r.fulfill({ json: listing([draft]) }));
  await page.route('**/api/v1/quotations/900010', r => r.request().method() === 'DELETE'
    ? r.fulfill(apiError(500, '已發佈的報價單不可刪除')) : r.fulfill({ json: draft }));
  await page.goto('/quotations');
  await page.getByRole('button', { name: '刪除' }).click();
  await page.getByRole('button', { name: '確認' }).click();
  await expect(page.getByText('確定要刪除此報價單嗎？')).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveText('刪除報價單失敗：已發佈的報價單不可刪除');
});
