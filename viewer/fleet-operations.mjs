import {escapeHtml as esc,ageMs} from './fleet-model.mjs?v=0.12.0';

const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const text=v=>typeof v==='string'&&v.length<=1200&&!/[\x00-\x1f\x7f]/.test(v);
const date=v=>typeof v==='string'&&Number.isFinite(Date.parse(v));
export function validOperations(v){
  return object(v)&&v.schema==='workman.fleet.operations.v1'&&v.status==='available'&&date(v.observedAt)&&
    Array.isArray(v.alerts)&&v.alerts.length<=4096&&v.alerts.every(a=>object(a)&&text(a.id)&&text(a.host)&&text(a.text)&&text(a.name)&&['pending','firing'].includes(a.state)&&['high','medium','low'].includes(a.severity)&&date(a.since)&&typeof a.suppressed==='boolean')&&
    new Set(v.alerts.map(a=>a.id)).size===v.alerts.length&&Array.isArray(v.events)&&v.events.length<=200&&v.events.every(e=>object(e)&&Number.isSafeInteger(e.id)&&text(e.host)&&text(e.kind)&&text(e.message)&&date(e.at));
}
const stamp=v=>date(v)?new Date(v).toLocaleString():'Unverified';
export function operationsCurrent(v,failed=false,now=Date.now()){
  const age=ageMs(v?.observedAt,now);return !failed&&validOperations(v)&&age!==null&&age<=90000;
}
export function operationsPanel(v,{failed=false,compact=false,hosts=null}={}){
  const current=operationsCurrent(v,failed),ids=hosts?new Set(hosts.map(h=>h.host)):null;
  const alerts=(v?.alerts||[]).filter(a=>!ids||ids.has(a.host));
  return `<section class="panel operations-panel"><div class="section-head"><h2>Persistent incidents</h2>${compact?'<a class="action-link" href="#operations">Incidents &amp; event history →</a>':''}</div>${!current?'<p class="notice">The server observation is unavailable, retained or stale. Incident clearance is unverified.</p>':''}<p class="muted">Conditions must persist for two minutes. Missing readings never clear a measured fault. ${v?'Evaluated '+esc(stamp(v.observedAt))+'.':'No server receipt yet.'}</p>${alerts.length?`<ul class="incident-list">${alerts.map(a=>`<li><a href="#host/${encodeURIComponent(a.host)}"><strong>${esc(a.name)}</strong></a><span class="status ${a.state==='firing'&&!a.suppressed?'warn':''}">${esc(a.suppressed?'Outside expected hours':a.state==='pending'?'Confirming':a.severity+' · active')}</span><p>${esc(a.text)}</p><small>Since ${esc(stamp(a.since))} · reading ${esc(stamp(a.readingAt))}${a.evidenceState!=='current'?' · source '+esc(a.evidenceState):''}</small></li>`).join('')}</ul>`:'<p class="empty">'+(current?'No persistent incidents in this view. Pending connections are excluded.':'No current incident state can be established.')+'</p>'}</section>`;
}
export function operationsPage(v,failed=false,health=null){
  const producers=v?.producers||[];
  return operationsPanel(v,{failed})+`<section class="panel"><h2>Monitoring health</h2><p class="muted">The existing collectors remain the only device probes. Receipt time and device sample time are separate.</p><div class="history-list">${producers.map(p=>`<div class="health-row"><strong>${esc(p.name)}</strong><span>${esc(p.state)}</span><small>Source report ${esc(stamp(p.observedAt))}</small><small>${esc(p.reason||'')}</small></div>`).join('')}</div><p class="last-seen">Operations service: ${esc(health?.status||'Unverified')} · collector ${esc(health?.collectorVersion||'Unverified')}</p></section><section class="panel"><h2>Server event history</h2><p class="muted">Retained while browsers are closed, across service restarts. The first observation is a baseline; earlier events are not reconstructed.</p>${v?.events?.length?`<ol class="incident-list">${v.events.map(e=>`<li><small>${esc(stamp(e.at))} · ${esc(e.host)} · ${esc(e.kind)}</small><p>${esc(e.message)}</p></li>`).join('')}</ol>`:'<p class="empty">No retained transitions yet.</p>'}</section>`;
}
