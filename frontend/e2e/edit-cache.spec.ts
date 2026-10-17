import { test, expect } from '@playwright/test';

const cases = [
  {
    collection: 'customers', field: 'name', input: 'input[name="name"]', save: '儲存',
    initial: { id: 900002, name: 'Original customer', tax_id: '12345678', level: 'standard', credit_score: 80 },
  },
  {
    collection: 'products', field: 'name', input: 'input[name="name"]', save: '儲存',
    initial: { id: 900002, name: 'Original product', product_number: 'P-CACHE', cost: '40', list_price: '100', inventory: 1 },
  },
  {
    collection: 'quotations', field: 'notes', input: 'textarea', save: '儲存草稿',
    initial: { id: 900002, quotation_number: 'QT-TEST-CACHE', customer_id: 1, pricing_factor: '0.9',
      notes: 'Original notes', status: 'draft', total_price: '90', profit_rate: '0.5',
      items: [{ product_id: 1, quantity: 1 }] },
  },
];

for (const sample of cases) {
  test(`${sample.collection}: reopening after save shows the saved values, not the cached old form`, async ({ page }) => {
    let stored: Record<string, unknown> = structuredClone(sample.initial);
    const updatedValue = `Saved ${sample.collection} value`;
    // All reads/writes for this regression use this local in-memory fixture.
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === `/api/v1/${sample.collection}/900002`) {
        if (route.request().method() === 'PUT') stored = { ...stored, ...route.request().postDataJSON() };
        return route.fulfill({ json: stored });
      }
      if (path === `/api/v1/${sample.collection}`) {
        return route.fulfill({ json: { data: [stored], total: 1 } });
      }
      if (path === '/api/v1/customers') {
        return route.fulfill({ json: { data: [{ id: 1, name: 'Customer', tax_id: '12345678', level: 'standard' }] } });
      }
      if (path === '/api/v1/products') {
        return route.fulfill({ json: { data: [{ id: 1, name: 'Product', product_number: 'P-TEST', cost: '40', list_price: '100' }] } });
      }
      return route.fulfill({ status: 404, json: { error: 'Unexpected fixture path' } });
    });

    await page.goto(`/${sample.collection}/900002/edit`);
    await expect(page.locator(sample.input)).toHaveValue(String(stored[sample.field]));
    await page.locator(sample.input).fill(updatedValue);
    await page.getByRole('button', { name: sample.save, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/${sample.collection}$`));
    expect(stored[sample.field]).toBe(updatedValue);
    await page.getByRole('button', { name: '編輯', exact: true }).click();
    await expect(page.locator(sample.input)).toHaveValue(updatedValue);
  });
}
