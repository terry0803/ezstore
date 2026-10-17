import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

// 後端失敗時畫面要說出原因，不能一直顯示「載入中」或按了沒反應。全部用 page.route 假資料，不碰真的資料庫。
const draft = {
  id: 900010, quotation_number: 'QT-TEST-ERR', customer_id: 1, customer: { id: 1, name: 'Customer' },
  customer_level: 'standard', pricing_factor: '0.9', notes: '', status: 'draft',
  total_price: '90', profit_amount: '50', profit_rate: '0.5555',
  items: [{ id: 1, product_id: 1, product_name: 'Product', list_price: '100', unit_price: '90', quantity: 1, subtotal: '90' }],
};

function backendError(status: number, message: string) {
  return { status, json: { error: { code: 'BAD_REQUEST', message } } };
}

async function mockApi(page: Page, handle: (method: string, path: string) => object | undefined) {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const reply = handle(route.request().method(), path);
    if (reply) return route.fulfill(reply);
    if (path === '/api/v1/customers') return route.fulfill({ json: { data: [{ id: 1, name: 'Customer', tax_id: '12345678', level: 'standard' }], total: 1 } });
    if (path === '/api/v1/products') return route.fulfill({ json: { data: [{ id: 1, name: 'Product', product_number: 'P-TEST', cost: '40', list_price: '100' }], total: 1 } });
    return route.fulfill(backendError(404, 'Unexpected fixture path'));
  });
}

test('quotation detail shows the load error instead of loading forever', async ({ page }) => {
  await mockApi(page, (_, path) => path === '/api/v1/quotations/900010' ? backendError(404, '找不到報價單') : undefined);
  await page.goto('/quotations/900010');
  await expect(page.getByRole('alert')).toHaveText('讀取報價單失敗：找不到報價單');
  await expect(page.getByText('載入中...')).toHaveCount(0);
  await page.getByRole('button', { name: '返回列表' }).click();
  await expect(page).toHaveURL(/\/quotations$/);
});

test('order detail shows the load error', async ({ page }) => {
  await mockApi(page, (_, path) => path === '/api/v1/orders/900010' ? backendError(404, '找不到訂單') : undefined);
  await page.goto('/orders/900010');
  await expect(page.getByRole('alert')).toHaveText('讀取訂單失敗：找不到訂單');
});

test('publish and duplicate failures show the backend message', async ({ page }) => {
  await mockApi(page, (method, path) => {
    if (path === '/api/v1/quotations/900010' && method === 'GET') return { json: draft };
    if (path === '/api/v1/quotations/900010/publish') return backendError(400, '報價單已經發佈');
    if (path === '/api/v1/quotations/900010/duplicate') return backendError(400, '來源報價單不存在');
    return undefined;
  });
  await page.goto('/quotations/900010');
  await page.getByRole('button', { name: '發佈' }).click();
  await expect(page.getByRole('alert')).toHaveText('發佈失敗：報價單已經發佈');
  await page.getByRole('button', { name: '複製' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '複製失敗' })).toHaveText('複製失敗：來源報價單不存在');
  await expect(page).toHaveURL(/\/quotations\/900010$/);
});

test('failed delete closes the dialog and explains why', async ({ page }) => {
  await mockApi(page, (method, path) => {
    if (path === '/api/v1/quotations' && method === 'GET') return { json: { data: [draft], total: 1 } };
    if (path === '/api/v1/quotations/900010' && method === 'DELETE') return backendError(500, '已發佈的報價單不可刪除');
    return undefined;
  });
  await page.goto('/quotations');
  await page.getByRole('button', { name: '刪除' }).click();
  await page.getByRole('button', { name: '確認' }).click();
  await expect(page.getByText('確定要刪除此報價單嗎？')).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveText('刪除報價單失敗：已發佈的報價單不可刪除');
});

test('list load failure is not shown as an empty list only', async ({ page }) => {
  await mockApi(page, (_, path) => path === '/api/v1/orders' ? { status: 503, body: 'unavailable' } : undefined);
  await page.goto('/orders');
  await expect(page.getByRole('alert')).toHaveText('讀取訂單清單失敗：後端回應 503');
});

test('edit form cannot save over the record when loading it failed', async ({ page }) => {
  const writes: string[] = [];
  await mockApi(page, (method, path) => {
    if (path === '/api/v1/customers/900010') {
      if (method !== 'GET') writes.push(method);
      return backendError(500, 'database unavailable');
    }
    return undefined;
  });
  await page.goto('/customers/900010/edit');
  await expect(page.getByRole('alert')).toHaveText('讀取客戶資料失敗：database unavailable');
  await expect(page.getByRole('button', { name: '儲存' })).toBeDisabled();
  expect(writes).toEqual([]);
});

test('form save failure shows the backend message, not the HTTP status text', async ({ page }) => {
  await mockApi(page, (method, path) => {
    if (path === '/api/v1/quotations/900010' && method === 'GET') return { json: draft };
    if (path === '/api/v1/quotations/900010' && method === 'PUT') return backendError(400, '報價因子不可超過 9.9999');
    return undefined;
  });
  await page.goto('/quotations/900010/edit');
  await page.getByRole('button', { name: '儲存草稿' }).click();
  await expect(page.getByText('報價因子不可超過 9.9999')).toBeVisible();
  await expect(page.getByText('Request failed with status code 400')).toHaveCount(0);
});
