import { test, expect } from '@playwright/test';

test('editing notes preserves a four-decimal pricing factor accepted by the API', async ({ page }) => {
  const quotation = {
    id: 900001, customer_id: 1, pricing_factor: '0.7604', notes: 'original notes',
    items: [{ product_id: 1, quantity: 2 }],
  };
  let saved: typeof quotation | undefined;

  // Exercise the real form and browser validation without writing any database.
  await page.route('**/api/v1/customers?*', route => route.fulfill({ json: {
    data: [{ id: 1, name: 'Test customer', tax_id: '12345678', level: 'VIP' }],
  } }));
  await page.route('**/api/v1/products?*', route => route.fulfill({ json: {
    data: [{ id: 1, name: 'Test product', product_number: 'P-TEST', list_price: '100', cost: '40' }],
  } }));
  await page.route('**/api/v1/quotations/900001', async route => {
    if (route.request().method() === 'PUT') {
      saved = route.request().postDataJSON();
    }
    await route.fulfill({ json: quotation });
  });

  await page.goto('/quotations/900001/edit');
  const factor = page.locator('input[type="number"]').first();
  await expect(factor).toHaveValue('0.7604');
  await expect.poll(() => factor.evaluate((input: HTMLInputElement) => input.validity.stepMismatch)).toBe(false);
  await page.locator('textarea').fill('notes changed; keep the agreed price');
  await page.getByRole('button', { name: '儲存草稿' }).click();
  await expect(page).toHaveURL(/\/quotations$/);
  expect(saved).toMatchObject({ pricing_factor: 0.7604, notes: 'notes changed; keep the agreed price' });
});
