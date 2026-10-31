import {escapeHtml as esc} from './fleet-model.mjs?v=0.12.0';
export const validLayout=v=>v?.schema==='workman.fleet.layout.v1'&&typeof v.revision==='string'&&/^[a-f0-9]{64}$/.test(v.revision)&&Array.isArray(v.order)&&v.order.length<=512&&v.order.every(s=>typeof s==='string'&&/^[a-z0-9][a-z0-9.-]{0,62}$/.test(s))&&new Set(v.order).size===v.order.length&&v.panels&&['tokens','models','spark'].every(k=>typeof v.panels[k]==='boolean');
export function orderedHosts(hosts,layout){
  const order=new Map((layout?.order||[]).map((h,i)=>[h,i]));
  return [...hosts].sort((a,b)=>(order.get(a.host)??512)-(order.get(b.host)??512));
}
export function layoutPage(hosts,value){
  return `<section class="panel"><h2>Shared dashboard layout</h2><p class="muted">Saved computer order and optional panels apply to every browser on this installation. Incidents and coverage stay visible.</p>${!value?'<p class="notice">The shared settings service is unavailable. No settings can be saved.</p>':`<form id="layoutForm"><fieldset><legend>Optional overview panels</legend>${[['tokens','Token summary'],['models','Current model'],['spark','SparkDash host summary']].map(([k,label])=>`<label class="layout-choice"><input type="checkbox" name="${k}" ${value.panels[k]?'checked':''}> ${label}</label>`).join('')}</fieldset><ol id="layoutOrder" class="incident-list">${orderedHosts(hosts,value).map(h=>`<li data-order-host="${esc(h.host)}"><strong>${esc(h.name||h.host)}</strong><div class="layout-buttons"><button type="button" data-move="up" aria-label="Move ${esc(h.name||h.host)} up">↑ Up</button><button type="button" data-move="down" aria-label="Move ${esc(h.name||h.host)} down">↓ Down</button></div></li>`).join('')}</ol><button type="submit">Save shared layout</button><p id="layoutStatus" role="status"></p></form>`}</section>`;
}
export function wireLayout(value,saved){
  const form=document.getElementById('layoutForm');if(!form||!value)return;
  form.addEventListener('click',event=>{const b=event.target.closest('[data-move]');if(!b)return;form.dataset.dirty='true';const row=b.closest('[data-order-host]');if(b.dataset.move==='up'&&row.previousElementSibling)row.previousElementSibling.before(row);if(b.dataset.move==='down'&&row.nextElementSibling)row.nextElementSibling.after(row);b.focus();});
  form.addEventListener('change',()=>{form.dataset.dirty='true';});
  form.addEventListener('submit',async event=>{
    event.preventDefault();const button=form.querySelector('[type=submit]'),status=document.getElementById('layoutStatus');button.disabled=true;
    const patch={revision:value.revision,order:[...form.querySelectorAll('[data-order-host]')].map(el=>el.dataset.orderHost),panels:Object.fromEntries(['tokens','models','spark'].map(k=>[k,form.elements[k].checked]))};
    try{const response=await fetch('api/preferences',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch),signal:AbortSignal.timeout(8000)});const next=await response.json();if(!response.ok||!validLayout(next))throw Error('not saved');const retained=await fetch('api/preferences',{cache:'no-store',signal:AbortSignal.timeout(8000)});const readback=await retained.json();if(!retained.ok||!validLayout(readback)||readback.revision!==next.revision||JSON.stringify(readback.order)!==JSON.stringify(patch.order)||JSON.stringify(readback.panels)!==JSON.stringify(patch.panels))throw Error('readback mismatch');form.dataset.dirty='false';saved(readback);document.getElementById('layoutStatus').textContent='Shared layout saved and read back.';}catch{status.textContent='Not saved or readback unverified. Reload shared settings before retrying; other saved settings are preserved.';}finally{button.disabled=false;}
  });
}
