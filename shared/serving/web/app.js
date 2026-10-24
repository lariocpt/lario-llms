let snapshot = {owners:{}}, csrf = '', pending = false;
const names = {geekom:'gkm', '7900xt':'rdn xt', rtx5080:'gfc rtx', arcB70:'b70'};
const compactModelName=name=>name.replace(/^Geekom(?= - | — )/,'gkm').replace(/^Radeon 7900 XT(?= - | — )/,'rdn xt').replace(/^RTX 5080(?= - | — )/,'gfc rtx').replace(/^Arc B70(?= - | — )/,'b70').replace(/\bmedium\b/gi,'md').replace(/\bsmart\b/gi,'smrt').replace(/\bqwen/gi,'qwen');
function profileLabel(p){
  if(p.shared_pool){
    const model=compactModelName(p.name).replace(/-\d+(?:\.\d+)?k (?:\d+slt|\d+ slots?)-/,'-'+p.context/1024+'k shared-');
    return model;
  }
  // Older owner processes keep their startup labels. Reformat those locally;
  // a cosmetic change must never require disconnecting inference streams.
  if(!p.name.includes(' — '))return compactModelName(p.name);
  const [hardware,rest]=p.name.split(' — '),[model,...details]=rest.split(' · ');
  const suffix=details.filter(x=>!/^\d[\d,]* tokens$/.test(x)&&!/^\d+ slots?$/.test(x));
  return compactModelName(`${hardware} - ${p.context/1024}k ${p.slots} ${p.slots===1?'slot':'slots'} - ${model} · ${suffix.join(' · ')}`);
}
function backendLabel(r){
  if(r.shared_pool==='qwen-q4')return `${names[r.hardware]||r.hardware} · Qwen3.8 Q4 weights / Q4 KV`;
  if(r.shared_pool==='supa')return `${names[r.hardware]||r.hardware} · Qwen3.8 Supa Q8 weights / Q8 KV`;
  return profileLabel(r);
}
function poolCapacity(p,s){
  const r=(s.residents||[]).find(r=>r.id===p.backend_id);
  if(!r||!p.shared_pool)return null;
  const admitted=(s.requests||[]).filter(x=>x.backend_id===p.backend_id).length;
  const occupied=Math.max(r.busy||0,admitted);
  return {running:r.busy||0,admitted,waiting:Math.max(0,admitted-(r.busy||0)),
    total:Math.min(r.slots,Math.floor(r.context_budget/p.context)),
    available:Math.max(0,Math.min(r.slots-occupied,Math.floor(r.context_available/p.context))),
    tokens:r.context_available};
}
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
const message=text=>document.getElementById('message').textContent=text;
const button=(text,callback,cls='',disabled=false)=>{const n=el('button',text,cls);n.type='button';n.disabled=disabled||pending;n.addEventListener('click',callback);return n};
async function operate(hardware,action,fields={}) {
  const entry=snapshot.owners[hardware];if(!entry||entry.offline)return;
  if(['off','cancel','cancel-all','cancel-and-off','disable','activate','unload'].includes(action)&&!confirm(`${names[hardware]}: ${action.replaceAll('-',' ')}? Active work may be interrupted only for cancellation actions. Conversations are kept.`))return;
  pending=true;render();message('Waiting for hardware owner…');
  try {
    const r=await fetch(`/api/operations/${hardware}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({action,expected_revision:entry.state.revision,idempotency_key:crypto.randomUUID(),...fields})});
    const d=await r.json();if(!r.ok)throw new Error(d.error?.message||'Operation refused; refresh state.');
    const outcomes=(d.agent_interruptions||[]).map(x=>`${x.client}: ${x.status}`).join('; ');
    message(`${names[hardware]}: ${action.replaceAll('-',' ')} accepted. ${outcomes} ${d.state?.busy&&action.startsWith('cancel')?'Backend slots remain occupied; completion is not confirmed.':''} ${action==='cancel-all'?'Admission stays paused until Resume.':''}`);
  } catch(e){message(e.message)}finally{pending=false;await refresh()}
}
function stat(value,label){const n=el('div',undefined,'stat');n.append(el('strong',String(value)),el('span',label));return n}
function render(){
  const hw=document.getElementById('hardware'),models=document.getElementById('models'),activity=document.getElementById('activity');hw.replaceChildren();models.replaceChildren();activity.replaceChildren();
  const search=document.getElementById('search').value.toLowerCase();let count=0;
  for(const hardware of Object.keys(names)){
    const entry=snapshot.owners[hardware]||{offline:true},s=entry.state||{};
    const stale=entry.offline||!entry.observed_at||Date.now()/1000-entry.observed_at>10;
    const state=stale?'offline':s.state||'unknown';
    const card=el('article',undefined,'card'),top=el('div',undefined,'card-top');top.append(el('h3',names[hardware]),el('span',state,'badge '+state));card.append(top,el('p',s.owner||'Owner unavailable','muted'));
    card.append(el('p',s.memory_budget?(s.residents||[]).map(backendLabel).join(' + ')||'No backend resident.':s.resident?profileLabel(s.resident):(state==='off'?'AI serving is off. Requests cannot wake this device.':'No model resident. An eligible request loads its exact profile.'),'resident'));
    const stats=el('div',undefined,'stats');
    if(s.memory_budget)stats.append(stat(s.busy??'—','admitted inference requests'),stat((s.residents||[]).length,'loaded backends'));
    else stats.append(stat(s.busy??'—','occupied slots'),stat(s.slots??'—','total slots'),stat(s.context?Math.round(s.context/1024)+' Ki':'—','tokens / slot'));
    card.append(stats);
    if(s.memory_budget){
      const m=s.memory_budget;
      card.append(el('p',`${m.allocated_gib.toFixed(1)} GiB allocated · ${m.available_gib.toFixed(1)} GiB available · ${m.reserve_gib} GiB safety reserve. Calculated allocations; runtime validation pending.`,'muted'));
      for(const r of s.residents||[]){
        const admitted=(s.requests||[]).filter(x=>x.backend_id===r.id).length;
        const waiting=Math.max(0,admitted-r.busy);
        card.append(el('p',`${backendLabel(r)} · ${r.busy} active / ${r.slots} stream slots${waiting?` · ${waiting} admitted and waiting`:''}`));
        card.append(el('p',`${r.context_reserved.toLocaleString()} / ${r.context_budget.toLocaleString()} tokens reserved · ${r.context_available.toLocaleString()} tokens free. Context capacity can fill before stream slots.`,'muted'));
      }
    }
    const actions=el('div',undefined,'actions');actions.append(button('Turn on',()=>operate(hardware,'on'),'',stale||s.enabled),button('Turn off',()=>operate(hardware,'off'),'quiet',stale||!s.enabled),button('Resume',()=>operate(hardware,'resume'),'quiet',stale||!s.enabled||!s.draining),button('Cancel inference',()=>operate(hardware,'cancel-all'),'danger',stale||!s.busy));
    card.append(actions);if(s.busy)card.append(button('Cancel and turn off',()=>operate(hardware,'cancel-and-off'),'danger',stale));
    if(stale)card.append(el('p','Last observation is stale. Controls are unavailable.','muted'));hw.append(card);
    const disabled=new Set(entry.catalog?.disabled||[]);
    for(const p of entry.catalog?.profiles||[]){
      const label=profileLabel(p);
      if(search&&!label.toLowerCase().includes(search)&&!hardware.includes(search))continue;
      const capacity=poolCapacity(p,s);
      const model=el('article',undefined,'model');model.append(el('h3',label),el('code',p.id),el('p',`${p.context.toLocaleString()} server tokens · ${(p.context-4096).toLocaleString()} OpenCode limit${p.shared_pool?'':` · ${p.slots-p.reserved} unreserved slots`}`));
      if(capacity)model.append(el('p',`${capacity.available} additional requests fit now · up to ${capacity.total} at this context with the pool empty · ${capacity.tokens.toLocaleString()} tokens free`));
      const availability=s.profile_availability?.[p.id];
      const resident=availability?availability.resident:s.profile_id===p.id;
      const reason=availability?.reason;
      model.append(el('p',disabled.has(p.id)?'Disabled':reason?reason.replaceAll('_',' '):resident?'Resident':p.experimental?'Available · provisional configuration':'Available',resident?'badge':'muted'));
      if(p.shared_pool)model.append(el('p',`Shared weights · ${p.reasoning_effort} thinking · up to ${p.pool_context.toLocaleString()} pooled tokens, sized from memory headroom · up to ${p.pool_slots} concurrent requests`,'muted'));
      model.append(button(s.memory_budget?'Load':'Load when idle',()=>operate(hardware,'activate',{profile_id:p.id}),'',stale||!s.enabled||s.draining||(!s.memory_budget&&!!s.busy)||!!s.loading_profile||resident||disabled.has(p.id)||availability?.selectable===false));
      if(s.memory_budget&&resident){
        const backend=(s.residents||[]).find(r=>r.id===p.backend_id);
        const reserved=(s.requests||[]).some(r=>r.backend_id===p.backend_id);
        model.append(button('Unload shared backend',()=>operate(hardware,'unload',{profile_id:p.id}),'quiet',stale||!!backend?.busy||reserved||!!s.loading_profile));
      }
      model.append(button(disabled.has(p.id)?'Enable':'Disable',()=>operate(hardware,disabled.has(p.id)?'enable':'disable',{profile_id:p.id}),'quiet',stale));models.append(model);
    }
    for(const r of s.requests||[]){count++;const row=el('div',undefined,'row');row.append(el('strong',`${names[hardware]} · ${r.client||r.role} · ${r.kind||'primary'} · ${r.phase}`),el('p',r.session_title||r.session_id||'Uninstrumented client — conversation identity unavailable'),el('p',`${Math.max(0,Math.round(Date.now()/1000-r.started))} seconds · ${r.profile_id}`,'muted'));if(r.run_id)row.append(el('code',`Run ${r.run_id}`));row.append(el('p',r.registered_client&&r.instance_id&&r.run_id?'Registered OpenCode client · guarded run control':'Inference control only · runner identity unavailable','muted'));row.append(button(r.registered_client&&r.instance_id&&r.run_id?'Cancel run':'Cancel request',()=>operate(hardware,'cancel',{request_id:r.id}),'danger',stale));activity.append(row)}
  }
  for(const p of snapshot.placements||[]){
    // Live owners already render their gated catalogue; do not duplicate a card.
    if(snapshot.owners[p.hardware])continue;
    const card=el('article',undefined,'card'),top=el('div',undefined,'card-top');
    top.append(el('h3',p.hardware),el('span',p.status,'badge'));card.append(top);
    card.append(el('p',`${p.host} · ${p.connection}`,'muted'));
    card.append(el('p',p.status==='partially-active'?'Owner is live; additional profiles below are still gated.':p.live_hardware_id?`Current service is ${p.live_hardware_id}; this name is prepared for migration.`:'Awaiting installation and runtime validation.','resident'));
    if(p.exclusive_with.length)card.append(el('p',`Same physical Radeon as ${p.exclusive_with.join(', ')}. Alternative placement; no additional capacity.`,'muted'));
    const logs=el('a','Metrics and operational logs');logs.href='https://models.logs.in.drlario.org';card.append(logs);hw.append(card);
    for(const model of p.profiles){
      const label=profileLabel(model);
      if(search&&!`${label} ${p.hardware}`.toLowerCase().includes(search))continue;
      const row=el('article',undefined,'model');
      row.append(el('h3',label),el('code',model.id),el('p',`Prepared for ${p.host}; not deployed or selectable. Existing model geometry is inherited; this placement is unverified.`,'muted'));
      models.append(row);
    }
  }
  if(!count)activity.append(el('p','No tracked inference requests. Backend occupancy is shown on the device cards; idle conversations do not reserve hardware.','muted'));
}
async function refresh(){try{const r=await fetch('/api/state');if(r.status===401){location.href='/login';return}const d=await r.json();csrf=d.csrf;snapshot=d;render()}catch(e){message('Unable to refresh. Previously displayed status may be stale.')}}
document.getElementById('search').addEventListener('input',render);
document.getElementById('logout').addEventListener('click',async()=>{await fetch('/logout',{method:'POST',headers:{'X-CSRF-Token':csrf}});location.href='/login'});
refresh();setInterval(refresh,2500);
