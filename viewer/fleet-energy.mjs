import {escapeHtml as esc,format} from './fleet-model.mjs?v=0.12.0';
let selectedDays=1;
export async function loadEnergy(container){
  if(!container)return;
  const days=selectedDays;
  try{
    const response=await fetch('api/energy?days='+days,{cache:'no-store',signal:AbortSignal.timeout(8000)});
    const value=await response.json();
    if(!response.ok||value.schema!=='workman.fleet.energy.v1'||value.days!==days||!Array.isArray(value.rows)||value.rows.length>1024||!value.rows.every(r=>typeof r.name==='string'&&typeof r.basis==='string'&&Number.isFinite(r.kwh)&&r.kwh>=0&&Number.isFinite(r.coveredSeconds)&&r.coveredSeconds>=0))throw Error('Invalid');
    if(!container.isConnected||days!==selectedDays)return;
    container.innerHTML=`<section class="panel"><div class="history-head"><h2>Energy from retained power readings</h2><label>Window <select>${[1,7,30].map(n=>`<option value="${n}" ${n===days?'selected':''}>${n} day${n===1?'':'s'}</option>`).join('')}</select></label></div><p class="muted">${esc(value.basis)} Component power and reported system power stay separate. No whole-fleet total is inferred.</p>${value.rows.length?`<div class="grid">${value.rows.map(r=>`<article class="panel"><h3>${esc(r.name)}</h3><strong>${format(r.kwh,5,' kWh')}</strong><p>${esc(r.basis)}</p><dl class="facts"><dt>Measured intervals</dt><dd>${format(r.coveredSeconds/3600,2,' h')} of ${days*24} h requested</dd><dt>Cost estimate</dt><dd>${Number.isFinite(r.costEstimate)&&r.rate?esc(r.rate.currency)+' '+format(r.costEstimate,4)+' at '+format(r.rate.pricePerKwh,4)+'/kWh':'Unavailable · no configured rate for this computer'}</dd></dl></article>`).join('')}</div>`:'<p class="empty">Two distinct power samples are needed. Computers without a working power source are excluded; missing power is not zero.</p>'}<p class="last-seen">Cost estimates cover only measured intervals and the configured rate. They are not utility bills or wall-meter readings.</p></section>`;
    container.querySelector('select').addEventListener('change',e=>{selectedDays=Number(e.target.value);loadEnergy(container);});
  }catch{
    if(container.isConnected)container.innerHTML='<section class="panel"><h2>Energy</h2><p class="notice">The energy service is unavailable. Usage and cost remain unverified.</p></section>';
  }
}
