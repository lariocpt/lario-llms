const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={};
const source=fs.readFileSync(require('node:path').join(__dirname,'../shared/serving/web/app.js'),'utf8');
vm.runInNewContext(source.split('const el=')[0]+';globalThis.capacity=poolCapacity;globalThis.label=profileLabel;',context);
const regular={backend_id:'q4',shared_pool:'qwen-q4',context:245760};
const state={residents:[{id:'q4',busy:6,slots:10,context_budget:1572864,context_available:98304},
  {id:'supa',busy:0,slots:1,context_budget:245760,context_available:245760}],
  requests:Array.from({length:6},()=>({backend_id:'q4'}))};
test('six 240k reservations exhaust context despite unused stream slots',()=>{
  const c=context.capacity(regular,state);
  assert.equal(c.total,6);assert.equal(c.available,0);assert.equal(c.running,6);
  assert.equal(c.admitted,6);assert.equal(c.waiting,0);
});
test('Supa capacity is separate and reservations are not added to native occupancy',()=>{
  assert.equal(context.capacity({...regular,backend_id:'supa'},state).available,1);
  const s={...state,residents:[{...state.residents[0],busy:2,context_available:1081344}],
    requests:[{backend_id:'q4'},{backend_id:'q4'}]};
  const c=context.capacity(regular,s);
  assert.equal(c.available,4);assert.equal(c.waiting,0);
});
test('old shared profile labels lose stale fixed slot counts',()=>{
  assert.equal(context.label({...regular,name:'gkm-240k 4slt-qw3.8 smrt Q4 kv4'}),
    'gkm-240k shared-qw3.8 smrt Q4 kv4');
});
test('mixed Flash windows share remaining tokens with independent request limits',()=>{
  const s={residents:[{id:'flash',busy:4,slots:6,context_budget:786432,context_available:32768}],
    requests:Array.from({length:4},()=>({backend_id:'flash'}))};
  for(const [tokens,total] of [[131072,6],[245760,3]]){
    const c=context.capacity({backend_id:'flash',shared_pool:'flash-next',context:tokens},s);
    assert.equal(c.total,total);assert.equal(c.available,0);
  }
  s.residents[0].context_available+=245760;
  s.residents[0].busy=3;s.requests.pop();
  assert.equal(context.capacity({backend_id:'flash',shared_pool:'flash-next',context:131072},s).available,2);
  assert.equal(context.capacity({backend_id:'flash',shared_pool:'flash-next',context:245760},s).available,1);
});
