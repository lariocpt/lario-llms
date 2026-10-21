import test from 'node:test';
import assert from 'node:assert/strict';
import { Runs } from './runs.js';

test('stale control never interrupts a newer turn or plugin instance', async()=>{
  const r=new Runs('instance'); r.begin('session','old'); r.begin('session','new');
  let called=false; const interrupt=async()=>{called=true;return {interrupted:true}};
  assert.equal((await r.cancel({session_id:'session',run_id:'old',instance_id:'instance'},interrupt)).status,'stale_run');
  assert.equal((await r.cancel({session_id:'session',run_id:'new',instance_id:'previous'},interrupt)).status,'stale_run');
  assert.equal(called,false);
});
test('new prompts cannot cross an in-flight interruption', async()=>{
  const r=new Runs('instance');r.begin('session','old');r.begin('other','other-run');
  let release; const wait=new Promise(resolve=>{release=resolve});
  const stopping=r.cancel({session_id:'session',run_id:'old',instance_id:'instance'},async()=>{await wait;return {interrupted:true}});
  assert.throws(()=>r.begin('session','new'),/Previous run/);
  assert.equal(r.begin('other','next-other'),'next-other');
  release();assert.equal((await stopping).status,'interrupted');
  assert.throws(()=>r.begin('session','old'),/cancelled/);
  assert.equal(r.begin('session','new'),'new');
});
test('idle cancellation keeps the conversation and allows a later turn', async()=>{
  const r=new Runs('instance');r.begin('session','old');
  assert.equal((await r.cancel({session_id:'session',run_id:'old',instance_id:'instance'},async()=>({interrupted:false}))).status,'idle');
  assert.equal(r.begin('session','new'),'new');
});
