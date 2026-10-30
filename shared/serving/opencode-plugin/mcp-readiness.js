/** OpenCode can report an MCP connected before registering its tool catalog. */
export async function waitForMcpTools(ctx, {
  timeoutMs = 15000,
  now = () => performance.now(),
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
} = {}) {
  const deadline = now() + timeoutMs;
  for (;;) {
    const { data: servers } = await ctx.mcp.list();
    const managed = servers.filter(server => server.name.startsWith('lario_') &&
      ['pending', 'connected'].includes(server.status.status));
    if (!managed.length) return;
    const tools = await ctx.tool.list();
    const missing = managed.filter(server => server.status.status !== 'connected' ||
      !tools.some(tool => tool.id.startsWith(server.name + '_')));
    if (!missing.length) return;
    if (now() >= deadline) {
      throw new Error('MCP tool catalog not ready: ' + missing.map(server => server.name).join(', ') +
        '. Prompt not sent; reconnect these MCP servers and retry.');
    }
    await sleep(Math.min(100, Math.max(0, deadline - now())));
  }
}
