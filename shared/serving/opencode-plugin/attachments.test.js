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
