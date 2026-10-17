import assert from 'node:assert/strict';
import { createServer as createHttpServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { createServer } from 'vite';

test('Vite forwards Agent POST requests and SSE through the configured rewrite', { timeout: 20_000 }, async () => {
  const received = [];
  const upstream = createHttpServer(async (request, response) => {
    let body = '';
    for await (const chunk of request) body += chunk;
    received.push({ path: request.url, method: request.method, body: JSON.parse(body) });
    if (request.url === '/run_sse') {
      response.writeHead(200, { 'Content-Type': 'text/event-stream' });
      response.end('data: {"author":"quotation_agent","content":{"parts":[{"text":"offline response"}]}}\n\n');
    } else {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ id: 'offline-session' }));
    }
  });
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  let vite;
  try {
    vite = await createServer({
      root: fileURLToPath(new URL('../', import.meta.url)),
      configFile: fileURLToPath(new URL('../vite.config.ts', import.meta.url)),
      logLevel: 'silent',
      server: {
        host: '127.0.0.1', port: 0, hmr: false, watch: null,
        // Change only the destination; retain the production rewrite configuration.
        proxy: { '/agent-api': { target: `http://127.0.0.1:${upstream.address().port}` } },
      },
    });
    await vite.listen();
    const base = `http://127.0.0.1:${vite.httpServer.address().port}`;
    const post = (path, body) => fetch(base + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const session = await post('/agent-api/apps/quotation_agent/users/offline/sessions', {});
    assert.equal(session.status, 200);
    assert.deepEqual(await session.json(), { id: 'offline-session' });
    const stream = await post('/agent-api/run_sse', { session_id: 'offline-session', streaming: true });
    assert.equal(stream.status, 200);
    assert.match(stream.headers.get('content-type'), /text\/event-stream/);
    assert.match(await stream.text(), /offline response/);
    assert.deepEqual(received, [
      { path: '/apps/quotation_agent/users/offline/sessions', method: 'POST', body: {} },
      { path: '/run_sse', method: 'POST', body: { session_id: 'offline-session', streaming: true } },
    ]);
  } finally {
    if (vite) await vite.close();
    upstream.closeAllConnections();
    await new Promise((resolve) => upstream.close(resolve));
  }
});
