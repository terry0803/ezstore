import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Exercise the production handlers without a browser, backend, or model service.
const readSource = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const chat = readSource('src/pages/AgentChatPage.tsx');
const keyHandler = chat.match(/const handleKeyDown = \(e: React\.KeyboardEvent\) => \{([\s\S]*?)\n  \};/);
assert.ok(keyHandler, 'Chat key handler must be available for the regression check');
const keydown = new Function('e', 'handleSend', keyHandler[1]);

function pressEnter({ isComposing = false, keyCode = 13, shiftKey = false } = {}) {
  let sends = 0;
  let prevented = 0;
  keydown({
    key: 'Enter', shiftKey, nativeEvent: { isComposing, keyCode },
    preventDefault() { prevented++; },
  }, () => { sends++; });
  return { sends, prevented };
}

test('IME candidate confirmation does not send or cancel composition', () => {
  assert.deepEqual(pressEnter({ isComposing: true }), { sends: 0, prevented: 0 });
  // Some browsers report the composition-ending Enter through keyCode 229.
  assert.deepEqual(pressEnter({ keyCode: 229 }), { sends: 0, prevented: 0 });
});

test('normal Enter still sends once; Shift+Enter does not send', () => {
  assert.deepEqual(pressEnter(), { sends: 1, prevented: 1 });
  assert.deepEqual(pressEnter({ shiftKey: true }), { sends: 0, prevented: 0 });
});

const form = readSource('src/pages/QuotationFormPage.tsx');
const calculation = form.match(/const computedItems = items\.map[\s\S]*?const profitRate = [^;]+;/);
assert.ok(calculation, 'Quotation preview calculation must be available');
const calculate = new Function('items', 'products', 'pricingFactor',
  `${calculation[0]}\nreturn { totalPrice, profitAmount, profitRate };`);
const quote = (listPrice, cost, factor = 1, quantity = 1) => calculate(
  [{ product_id: 1, quantity }],
  [{ id: 1, name: 'test product', list_price: String(listPrice), cost: String(cost) }],
  factor,
);

test('zero cost retains revenue as profit', () => {
  assert.deepEqual(quote(100, 0, 1, 2), { totalPrice: 200, profitAmount: 200, profitRate: 1 });
});

test('zero unit price retains the cost as a loss', () => {
  assert.deepEqual(quote(100, 40, 0, 2), { totalPrice: 0, profitAmount: -80, profitRate: 0 });
});

test('normal pricing and unselected products retain their expected totals', () => {
  assert.deepEqual(quote(100, 40, 0.8, 2), { totalPrice: 160, profitAmount: 80, profitRate: 0.5 });
  assert.deepEqual(calculate([{ product_id: 0, quantity: 1 }], [], 1),
    { totalPrice: 0, profitAmount: 0, profitRate: 0 });
});

const configSource = readSource('vite.config.ts')
  .replace(/^import .*\r?\n/gm, '')
  .replace('export default defineConfig(', 'return defineConfig(');
const config = new Function('defineConfig', 'react', 'tailwindcss', configSource)(
  (value) => value, () => ({}), () => ({}),
);

test('development Agent requests reach ADK with the prefix removed', () => {
  const proxy = config.server.proxy['/agent-api'];
  assert.equal(proxy.target, 'http://127.0.0.1:8501');
  assert.equal(proxy.rewrite('/agent-api/apps/quotation_agent/users/u/sessions'),
    '/apps/quotation_agent/users/u/sessions');
  assert.equal(proxy.rewrite('/agent-api/run_sse'), '/run_sse');
  assert.equal(proxy.rewrite('/agent-api/run_sse?stream=true'), '/run_sse?stream=true');
  assert.equal(config.server.proxy['/api'].target, 'http://localhost:8080');
});
