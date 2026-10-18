import { test, expect, type Page, type Route } from '@playwright/test';

test('order form loads later pages of both option lists', async ({ page }) => {
  const pages: string[] = [];
  for (const kind of ['customers', 'products']) {
    await page.route(`**/api/v1/${kind}?*`, route => {
      const n = Number(new URL(route.request().url()).searchParams.get('page'));
      pages.push(`${kind}:${n}`);
      const ids = n === 1 ? Array.from({ length: 100 }, (_, i) => i + 1) : [101];
      return route.fulfill({ json: { total: 101, page: n, page_size: 100,
        data: ids.map(id => ({ id, name: `Record ${id}`, tax_id: `T${id}`,
          product_number: `P${id}`, list_price: '10', level: 'standard' })) } });
    });
  }
  await page.goto('/orders/new');
  const selects = page.locator('select');
  await expect(selects.nth(0).locator('option')).toHaveCount(102);
  await expect(selects.nth(1).locator('option')).toHaveCount(102);
  await selects.nth(0).selectOption('101');
  await selects.nth(1).selectOption('101');
  expect(pages).toEqual(expect.arrayContaining(['customers:2', 'products:2']));
  await expect(page.getByRole('button', { name: '儲存', exact: true })).toBeEnabled();
});

for (const brokenKind of ['customers', 'products']) {
  test(`order form blocks saving after ${brokenKind} failure and retry recovers`, async ({ page }) => {
    let broken = true;
    let writes = 0;
    await page.route('**/api/v1/orders', async route => {
      if (route.request().method() === 'POST') writes++;
      await route.fulfill({ json: { data: [], total: 0 } });
    });
    for (const kind of ['customers', 'products']) {
      await page.route(`**/api/v1/${kind}?*`, route => route.fulfill(broken && kind === brokenKind
        ? { status: 500, json: { error: { message: '選項讀取中斷' } } }
        : { json: { data: [{ id: 1, name: 'Recovered', tax_id: '1', product_number: 'P1', list_price: '10' }], total: 1 } }));
    }
    await page.goto('/orders/new');
    await expect(page.getByRole('alert')).toContainText('選項讀取中斷');
    await expect(page.getByRole('button', { name: '儲存', exact: true })).toBeDisabled();
    // A programmatic submit must also be blocked, not just clicking the button.
    await page.locator('form').dispatchEvent('submit');
    expect(writes).toBe(0);
    broken = false;
    await page.getByRole('button', { name: '重試', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect(page.getByRole('button', { name: '儲存', exact: true })).toBeEnabled();
    await expect(page.locator('select').first().locator('option')).toHaveCount(2);
  });
}

for (const [kind, label] of [['customers', '客戶'], ['products', '產品'], ['orders', '訂單']]) {
  test(`${kind}: failed list shows an error and retry recovers`, async ({ page }) => {
    let broken = true;
    await page.route(`**/api/v1/${kind}?*`, route => route.fulfill(broken
      ? { status: 500, json: { error: { message: '資料庫暫時無法使用' } } }
      : { json: { data: [], total: 0, page: 1, page_size: 20 } }));
    await page.goto(`/${kind}`);
    await expect(page.getByRole('alert')).toHaveText(`讀取${label}清單失敗：資料庫暫時無法使用`);
    await expect(page.getByText('目前沒有資料')).toHaveCount(0);
    broken = false;
    await page.getByRole('button', { name: '重新載入資料' }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect(page.getByText('目前沒有資料')).toBeVisible();
  });
}

for (const [kind, label] of [['customers', '客戶'], ['products', '產品']]) {
  test(`${kind}: failed edit load exposes no blank editable form`, async ({ page }) => {
    let broken = true;
    await page.route(`**/api/v1/${kind}/900050`, route => route.fulfill(broken
      ? { status: 500, json: { error: { message: '讀取中斷' } } }
      : { json: { id: 900050, name: 'Recovered record', tax_id: '12345678', level: 'standard', credit_score: 80,
          product_number: 'P-RECOVER', cost: '10', list_price: '20', inventory: 1 } }));
    await page.goto(`/${kind}/900050/edit`);
    await expect(page.getByRole('alert')).toHaveText(`讀取${label}失敗：讀取中斷`);
    await expect(page.locator('form')).toHaveCount(0);
    broken = false;
    await page.getByRole('button', { name: '重新載入資料' }).click();
    await expect(page.locator('input[name="name"]')).toHaveValue('Recovered record');
    await expect(page.getByRole('button', { name: '儲存', exact: true })).toBeEnabled();
  });

  test(`${kind}: delete rejection is visible and record stays`, async ({ page }) => {
    await page.route(`**/api/v1/${kind}?*`, route => route.fulfill({ json: {
      data: [{ id: 900050, name: 'Keep this record', tax_id: '12345678', level: 'standard',
        product_number: 'P-KEEP', cost: '10', list_price: '20', inventory: 1 }], total: 1, page: 1, page_size: 20,
    } }));
    await page.route(`**/api/v1/${kind}/900050`, route => route.fulfill({ status: 400,
      json: { error: { message: '資料仍被使用' } } }));
    await page.goto(`/${kind}`);
    await page.getByRole('button', { name: '刪除', exact: true }).click();
    await page.getByRole('button', { name: '確認', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveText(`刪除${label}失敗：資料仍被使用`);
    await expect(page.getByText('Keep this record')).toBeVisible();
    await expect(page.getByRole('button', { name: '確認', exact: true })).toHaveCount(0);
  });
}

test('expired chat session resets without replaying the failed instruction', async ({ page }) => {
  let sessions = 0;
  const messages: string[] = [];
  await page.route('**/agent-api/apps/*/users/*/sessions', r => r.fulfill({ json: { id: `session-${++sessions}` } }));
  await page.route('**/agent-api/run_sse', r => {
    const data = r.request().postDataJSON();
    messages.push(data.new_message.parts[0].text);
    if (messages.length === 2) return r.fulfill({ status: 404, json: { detail: `Session not found: ${data.session_id}` } });
    expect(data.session_id).toBe(messages.length === 1 ? 'session-1' : 'session-2');
    return r.fulfill({ contentType: 'text/event-stream', body: 'data: ' + JSON.stringify({ author: 'quotation_agent',
      nodeInfo: { path: '/respond@1' }, content: { parts: [{ text: '查詢完成' }] } }) + '\n\n' });
  });
  await page.goto('/agent');
  const input = page.getByPlaceholder('輸入您的指令...');
  const send = page.getByRole('button', { name: '送出' });
  await input.fill('查詢報價單 QT-20260330-001');
  await send.click();
  await expect(page.getByText('查詢完成', { exact: true })).toBeVisible();
  await input.fill('請複製報價單 QT-20260330-001');
  await send.click();
  await expect(page.getByText(/對話已失效/)).toBeVisible();
  expect(messages).toHaveLength(2);
  expect(sessions).toBe(1);
  await input.fill('查詢報價單 QT-20260330-001');
  await send.click();
  await expect(page.getByText('查詢完成', { exact: true })).toHaveCount(2);
  expect(sessions).toBe(2);
  expect(messages.filter(m => m.startsWith('請複製'))).toHaveLength(1);
});

test('generic HTTP failure does not reset a valid chat or resend an operation', async ({ page }) => {
  let sessions = 0;
  let sends = 0;
  await page.route('**/agent-api/apps/*/users/*/sessions', r => r.fulfill({ json: { id: `session-${++sessions}` } }));
  await page.route('**/agent-api/run_sse', r => {
    sends++;
    return r.fulfill({ status: 500, json: { detail: 'service error' } });
  });
  await page.goto('/agent');
  for (const text of ['請複製報價單 QT-20260330-001', '查詢報價單 QT-20260330-001']) {
    await page.getByPlaceholder('輸入您的指令...').fill(text);
    await page.getByRole('button', { name: '送出' }).click();
    await expect(page.getByText('Agent request failed: 500')).toBeVisible();
  }
  expect(sessions).toBe(1);
  expect(sends).toBe(2);
});

test('all list APIs return the normalized pagination used for rows', async ({ request }) => {
  for (const collection of ['customers', 'products', 'quotations', 'orders']) {
    for (const query of ['page=0&page_size=999', 'page=-5&page_size=0', 'page=abc&page_size=xyz']) {
      const response = await request.get(`/api/v1/${collection}?${query}`);
      expect(response.ok()).toBeTruthy();
      const body = await response.json();
      expect(body.page).toBe(1);
      expect(body.page_size).toBe(20);
      expect(body.data.length).toBeLessThanOrEqual(20);
    }
  }
});

test('conditional failure cleanup cannot remove a changed or converted draft', async ({ request }) => {
  const create = async () => {
    const response = await request.post('/api/v1/quotations/9/duplicate');
    expect(response.ok()).toBeTruthy();
    const quote = await response.json();
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()).replaceAll('-', '');
    expect(quote.quotation_number).toContain(`QT-${today}-`);
    return quote;
  };
  const fresh = await create();
  const removed = await request.delete(`/api/v1/quotations/${fresh.id}`, { params: { expected_updated_at: fresh.updated_at } });
  expect(removed.status()).toBe(204);
  expect((await request.get(`/api/v1/quotations/${fresh.id}`)).status()).toBe(404);

  const changed = await create();
  const update = await request.put(`/api/v1/quotations/${changed.id}`, { data: {
    customer_id: changed.customer_id, pricing_factor: changed.pricing_factor, notes: 'Another edit must survive',
    items: changed.items.map((i: { product_id: number; quantity: number }) => ({ product_id: i.product_id, quantity: i.quantity })),
  } });
  expect(update.ok()).toBeTruthy();
  expect((await request.delete(`/api/v1/quotations/${changed.id}`, { params: { expected_updated_at: changed.updated_at } })).ok()).toBeFalsy();
  expect((await (await request.get(`/api/v1/quotations/${changed.id}`)).json()).notes).toBe('Another edit must survive');

  const converted = await create();
  const order = await request.post('/api/v1/orders', { data: {
    quotation_id: converted.id, customer_id: converted.customer_id,
    items: converted.items.map((i: { product_id: number; unit_price: string; quantity: number }) =>
      ({ product_id: i.product_id, unit_price: Number(i.unit_price), quantity: i.quantity })),
  } });
  expect(order.ok()).toBeTruthy();
  expect((await order.json()).order_number.split('-')[1]).toBe(converted.quotation_number.split('-')[1]);
  expect((await request.delete(`/api/v1/quotations/${converted.id}`, { params: { expected_updated_at: converted.updated_at } })).ok()).toBeFalsy();
  expect((await request.get(`/api/v1/quotations/${converted.id}`)).ok()).toBeTruthy();
});

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

// 外部檢查：存檔後馬上重開編輯頁會載入快取裡的舊內容，再存一次就把剛才的修改蓋掉
const cacheCases = [
  { collection: 'customers', field: 'name', input: 'input[name="name"]', save: '儲存',
    initial: { id: 900002, name: 'Original customer', tax_id: '12345678', level: 'standard', credit_score: 80 } },
  { collection: 'products', field: 'name', input: 'input[name="name"]', save: '儲存',
    initial: { id: 900002, name: 'Original product', product_number: 'P-CACHE', cost: '40', list_price: '100', inventory: 1 } },
  { collection: 'quotations', field: 'notes', input: 'textarea', save: '儲存草稿',
    initial: { id: 900002, quotation_number: 'QT-TEST-CACHE', customer_id: 1, pricing_factor: '0.9', notes: 'Original notes',
      status: 'draft', total_price: '90', profit_rate: '0.5', items: [{ product_id: 1, quantity: 1 }] } },
];

async function cacheFixtures(page: Page, collection: string, initial: Record<string, unknown>, failPut = false) {
  const state = { stored: structuredClone(initial) as Record<string, unknown>, reads: 0, writes: 0, failReads: false };
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/v1/${collection}/900002`) {
      if (route.request().method() === 'PUT') {
        state.writes++;
        if (failPut) return route.fulfill({ status: 400, json: { error: { code: 'VALIDATION_ERROR', message: '報價因子必須大於 0、最多 9.9999' } } });
        state.stored = { ...state.stored, ...route.request().postDataJSON() };
      } else {
        state.reads++;
        if (state.failReads) return route.fulfill(apiError(500, '背景讀取暫時失敗'));
      }
      return route.fulfill({ json: state.stored });
    }
    if (path === `/api/v1/${collection}`) return route.fulfill({ json: listing([state.stored]) });
    if (path === '/api/v1/customers') return route.fulfill({ json: listing([{ id: 1, name: 'Customer', tax_id: '12345678', level: 'standard' }]) });
    if (path === '/api/v1/products') return route.fulfill({ json: listing([{ id: 1, name: 'Product', product_number: 'P-TEST', cost: '40', list_price: '100' }]) });
    return route.fulfill({ status: 404, json: { error: { message: 'Unexpected fixture path' } } });
  });
  return state;
}

for (const sample of cacheCases) {
  test(`${sample.collection}: reopening right after save shows the saved values`, async ({ page }) => {
    const state = await cacheFixtures(page, sample.collection, sample.initial);
    const updated = `Saved ${sample.collection} value`;
    await page.goto(`/${sample.collection}/900002/edit`);
    await expect(page.locator(sample.input)).toHaveValue(String(sample.initial[sample.field as keyof typeof sample.initial]));
    await page.locator(sample.input).fill(updated);
    await page.getByRole('button', { name: sample.save, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/${sample.collection}$`));
    expect(state.stored[sample.field]).toBe(updated);
    // 用網頁內的連結重開（不重新載入），才會用到快取
    await page.getByRole('button', { name: '編輯', exact: true }).click();
    await expect(page.locator(sample.input)).toHaveValue(updated);
  });
}

test('form save failure shows the backend reason, not the HTTP status text', async ({ page }) => {
  await cacheFixtures(page, 'quotations', cacheCases[2].initial, true);
  await page.goto('/quotations/900002/edit');
  await expect(page.locator('textarea')).toHaveValue('Original notes');
  await page.getByRole('button', { name: '儲存草稿', exact: true }).click();
  await expect(page.getByText('報價因子必須大於 0、最多 9.9999')).toBeVisible();
  await expect(page.getByText('Request failed with status code 400')).toHaveCount(0);
});


for (const sample of cacheCases) {
  test(`${sample.collection}: refetch preserves edits and requires explicit conflict resolution`, async ({ page }) => {
    await page.clock.install();
    const state = await cacheFixtures(page, sample.collection, sample.initial);
    await page.goto(`/${sample.collection}/900002/edit`);
    await expect(page.locator(sample.input)).toHaveValue(String(state.stored[sample.field]));
    await page.locator(sample.input).fill('My unsaved edit');
    const changedField = sample.collection === 'customers' ? 'contact_phone' : sample.collection === 'products' ? 'cost' : 'pricing_factor';
    state.stored = { ...state.stored, [changedField]: sample.collection === 'quotations' ? '1.1' : '42' };
    await page.clock.fastForward(31000);
    await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')));
    await expect.poll(() => state.reads).toBe(2);
    await expect(page.getByRole('alert')).toContainText('未儲存編輯已保留');
    await expect(page.locator(sample.input)).toHaveValue('My unsaved edit');
    await expect(page.getByRole('button', { name: sample.save, exact: true })).toBeDisabled();
    await page.locator('form').dispatchEvent('submit');
    expect(state.writes).toBe(0);
    await page.getByRole('button', { name: '捨棄未儲存編輯並載入新版' }).click();
    await expect(page.locator(sample.input)).toHaveValue(String(state.stored[sample.field]));
    await expect(page.getByRole('alert')).toHaveCount(0);
    await page.locator(sample.input).fill('Reapplied edit');
    await page.getByRole('button', { name: sample.save, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/${sample.collection}$`));
    expect(state.stored[sample.field]).toBe('Reapplied edit');
    expect(Number(state.stored[changedField])).toBe(sample.collection === 'quotations' ? 1.1 : 42);
    expect(state.writes).toBe(1);
  });

  test(`${sample.collection}: pristine forms accept refreshed server values`, async ({ page }) => {
    await page.clock.install();
    const state = await cacheFixtures(page, sample.collection, sample.initial);
    await page.goto(`/${sample.collection}/900002/edit`);
    await expect(page.locator(sample.input)).toHaveValue(String(state.stored[sample.field]));
    state.stored = { ...state.stored, [sample.field]: 'New server value' };
    await page.clock.fastForward(31000);
    await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')));
    await expect(page.locator(sample.input)).toHaveValue('New server value');
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect(state.writes).toBe(0);
  });

  test(`${sample.collection}: unchanged background data does not reset a draft`, async ({ page }) => {
    await page.clock.install();
    const state = await cacheFixtures(page, sample.collection, sample.initial);
    await page.goto(`/${sample.collection}/900002/edit`);
    await expect(page.locator(sample.input)).toHaveValue(String(state.stored[sample.field]));
    await page.locator(sample.input).fill('Still editing');
    await page.clock.fastForward(31000);
    await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')));
    await expect.poll(() => state.reads).toBe(2);
    await expect(page.locator(sample.input)).toHaveValue('Still editing');
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect(page.getByRole('button', { name: sample.save, exact: true })).toBeEnabled();
  });
}

test('IME confirmation never sends chat; a subsequent normal Enter sends exactly once', async ({ page }) => {
  let runs = 0;
  await page.route('**/agent-api/apps/**/sessions', r => r.fulfill({ json: { id: 'ime-test' } }));
  await page.route('**/agent-api/run_sse', r => {
    runs++;
    return r.fulfill({ contentType: 'text/event-stream', body: 'data: ' + JSON.stringify({ author: 'quotation_agent',
      nodeInfo: { path: 'respond' }, content: { parts: [{ text: 'IME test response' }] } }) + '\n\n' });
  });
  await page.goto('/agent');
  const input = page.getByRole('textbox');
  await input.fill('報價單查詢');
  await input.dispatchEvent('compositionstart');
  await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13 });
  await input.dispatchEvent('compositionend');
  await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 229 });
  await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true });
  await input.press('Shift+Enter');
  await expect(input).toHaveValue('報價單查詢');
  expect(runs).toBe(0);
  await input.press('Enter');
  await expect(page.getByText('IME test response')).toBeVisible();
  expect(runs).toBe(1);
  await expect(input).toHaveValue('');
});

for (const sample of cacheCases.slice(0, 2)) {
  test(`${sample.collection}: failed background refresh preserves the draft and offers retry`, async ({ page }) => {
    await page.clock.install();
    const state = await cacheFixtures(page, sample.collection, sample.initial);
    await page.goto(`/${sample.collection}/900002/edit`);
    await expect(page.locator(sample.input)).toHaveValue(String(state.stored[sample.field]));
    await page.locator(sample.input).fill('Draft during outage');
    state.failReads = true;
    await page.clock.fastForward(31000);
    await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')));
    await expect.poll(() => state.reads).toBeGreaterThanOrEqual(2);
    await page.clock.runFor(1500);
    await expect(page.getByRole('alert')).toContainText('背景讀取暫時失敗');
    await expect(page.locator(sample.input)).toHaveValue('Draft during outage');
    await expect(page.getByRole('button', { name: sample.save, exact: true })).toBeDisabled();
    state.failReads = false;
    await page.getByRole('button', { name: '重新載入資料' }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect(page.locator(sample.input)).toHaveValue('Draft during outage');
    await expect(page.getByRole('button', { name: sample.save, exact: true })).toBeEnabled();
    expect(state.writes).toBe(0);
  });
}


async function duplicateFixtures(page: Page) {
  await cacheFixtures(page, 'quotations', cacheCases[2].initial);
  const copy = { ...cacheCases[2].initial, id: 900003, quotation_number: 'QT-TEST-COPY' };
  await page.route('**/api/v1/quotations/900003', r => r.fulfill({ json: copy }));
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const state = { calls: 0, responses: 0, fail: false, release };
  await page.route('**/api/v1/quotations/900002/duplicate', async route => {
    state.calls++;
    await gate;
    await route.fulfill(state.fail ? apiError(503, '複製服務暫時失敗') : { json: copy });
    state.responses++;
  });
  return state;
}

test('list duplicate sends only once even for synchronous repeated clicks', async ({ page }) => {
  const state = await duplicateFixtures(page);
  await page.goto('/quotations');
  const duplicate = page.getByRole('button', { name: '複製', exact: true });
  await expect(duplicate).toBeVisible();
  await duplicate.evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect.poll(() => state.calls).toBe(1);
  await expect(duplicate).toBeDisabled();
  state.release();
  await expect(page).toHaveURL(/900003\/edit$/);
  await expect(page.locator('textarea')).toHaveValue('Original notes');
  await page.locator('textarea').fill('Keep my new edit');
  await expect.poll(() => state.responses).toBe(1);
  expect(state.calls).toBe(1);
  await expect(page.locator('textarea')).toHaveValue('Keep my new edit');
});

test('late duplicate response cannot navigate away after leaving the list', async ({ page }) => {
  const state = await duplicateFixtures(page);
  await page.goto('/quotations');
  await page.getByRole('button', { name: '複製', exact: true }).click();
  await expect.poll(() => state.calls).toBe(1);
  await page.getByRole('button', { name: '新增報價單', exact: true }).click();
  await expect(page).toHaveURL(/quotations\/new$/);
  await page.locator('textarea').fill('Keep this other draft');
  const response = page.waitForResponse('**/api/v1/quotations/900002/duplicate');
  state.release();
  await response;
  // Allow the response's onSuccess callback and a possible route render to run.
  await page.waitForTimeout(200);
  await expect(page).toHaveURL(/quotations\/new$/);
  await expect(page.locator('textarea')).toHaveValue('Keep this other draft');
});

test('failed duplicate releases the button and permits a deliberate retry', async ({ page }) => {
  const state = await duplicateFixtures(page);
  state.fail = true;
  await page.goto('/quotations');
  const duplicate = page.getByRole('button', { name: '複製', exact: true });
  await duplicate.click();
  await expect.poll(() => state.calls).toBe(1);
  state.release();
  await expect(page.getByRole('alert')).toContainText('複製服務暫時失敗');
  await expect(duplicate).toBeEnabled();
  state.fail = false;
  await duplicate.click();
  await expect(page).toHaveURL(/900003\/edit$/);
  expect(state.calls).toBe(2);
});
