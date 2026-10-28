import test from 'node:test';
import assert from 'node:assert/strict';
import { routeAttachments, isImage } from './attachments.js';

test('attachments route to vision evidence and keep non-image files', async () => {
  const image = { uri: 'file:///tmp/screen.png', name: 'screen.png' };
  const source = { uri: 'file:///tmp/main.ts' };
  const prompt = { text: 'Review this layout', files: [image, source] };
  assert.equal(await routeAttachments(prompt, async input => {
    assert.deepEqual(input.files, [image]);
    return { hardware: 'rtx3060ti', model: 'vision-fixed', description: 'A blue button.' };
  }), true);
  assert.deepEqual(prompt.files, [source]);
  assert.match(prompt.text, /vision=rtx3060ti/);
  assert.match(prompt.text, /A blue button/);
  assert.match(prompt.text, /untrusted visual evidence/);
});

test('vision failure cannot silently strip image attachments', async () => {
  const prompt = { text: 'Read this', files: [{ uri: 'data:image/png;base64,eA==' }] };
  const original = structuredClone(prompt);
  await assert.rejects(routeAttachments(prompt, async () => { throw new Error('Both vision cards unavailable'); }), /unavailable/);
  assert.deepEqual(prompt, original);
});

test('plain text stays unchanged and remote image references are not fetched', async () => {
  const prompt = { text: 'Write code', files: [{ uri: 'file:///tmp/source.txt' }] };
  assert.equal(await routeAttachments(prompt, () => { throw new Error('should not run'); }), false);
  assert.equal(isImage({ uri: 'https://example.com/private.png' }), false);
  assert.equal(isImage({ uri: 'file:///tmp/screen.JPEG' }), true);
});

import { routeRequestImages } from './attachments.js';
const imageRequest = () => new Request('http://localhost/v1/chat/completions', {
  method: 'POST', headers: { 'content-type': 'application/json', 'X-Lario-Session': 'session' },
  body: JSON.stringify({messages: [{role:'user',content:[{type:'text',text:'Review spacing'},
    {type:'image_url',image_url:{url:'data:image/png;base64,eA=='}}]}]})
});
test('outbound tool/history images become evidence and preserve text and identity', async () => {
  const request = imageRequest();
  const output = await routeRequestImages(request, async ({files}) => {
    assert.equal(files[0].uri, 'data:image/png;base64,eA==');
    return {hardware:'rtx3060ti',model:'vision',description:'The heading touches the left edge.'};
  });
  const body = await output.json();
  assert.equal(body.messages[0].content[0].text, 'Review spacing');
  assert.match(body.messages[0].content[1].text, /heading touches/);
  assert.doesNotMatch(JSON.stringify(body), /image_url|data:image/);
  assert.equal(output.headers.get('X-Lario-Session'), 'session');
  assert.match(await request.text(), /image_url/);
});
test('outbound vision failure preserves retryable history', async () => {
  const request = imageRequest();
  await assert.rejects(routeRequestImages(request, async () => {throw new Error('Vision unavailable');}), /unavailable/);
  assert.match(await request.text(), /data:image/);
});
test('text-only requests do not invoke vision', async () => {
  const request = new Request('http://localhost', {method:'POST',headers:{'content-type':'application/json'},body:'{"messages":[{"role":"user","content":"hello"}]}'});
  assert.equal(await routeRequestImages(request, () => {throw new Error('unexpected');}), request);
});
