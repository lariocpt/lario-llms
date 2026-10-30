import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForMcpTools } from './mcp-readiness.js';

function fixture(states, catalogs) {
  let tick = 0;
  const at = values => values[Math.min(tick, values.length - 1)];
  return {
    ctx: {
      mcp: { list: async () => ({ data: at(states) }) },
      tool: { list: async () => at(catalogs).map(id => ({ id })) },
    },
    options: { timeoutMs: 300, now: () => tick * 100, sleep: async () => { tick++; } },
    ticks: () => tick,
  };
}
const server = (name, status = 'connected') => ({ name, status: { status } });

test('waits for a connected server to register tools', async () => {
  const f = fixture([[server('lario_web_testing')]], [[], ['lario_web_testing_web_accessibility']]);
  await waitForMcpTools(f.ctx, f.options);
  assert.equal(f.ticks(), 1);
});

test('waits for every managed server, including pending connections', async () => {
  const f = fixture([
    [server('lario_web_testing'), server('lario_images', 'pending')],
    [server('lario_web_testing'), server('lario_images')],
  ], [['lario_web_testing_web_accessibility'], ['lario_web_testing_web_accessibility', 'lario_images_image_describe']]);
  await waitForMcpTools(f.ctx, f.options);
  assert.equal(f.ticks(), 1);
});

test('does not silently send a prompt without the required catalog', async () => {
  const f = fixture([[server('lario_web_testing')]], [['shell']]);
  await assert.rejects(waitForMcpTools(f.ctx, f.options), /MCP tool catalog not ready: lario_web_testing/);
  assert.equal(f.ticks(), 3);
});

test('does not block for disabled, failed, or unrelated servers', async () => {
  const f = fixture([[server('lario_images', 'disabled'), server('lario_web_testing', 'failed'), server('other', 'pending')]], [[]]);
  await waitForMcpTools(f.ctx, f.options);
  assert.equal(f.ticks(), 0);
});
