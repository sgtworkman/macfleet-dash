import {escapeHtml as esc,format} from './fleet-model.mjs?v=0.12.0';
let selectedDays=1;
export async function loadSharedHistory(container,host){
  if(!container)return;
  const days=selectedDays;
  try{
    const response=await fetch('api/history?host='+encodeURIComponent(host)+'&days='+days,{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('Unavailable');
    const data=await response.json();
    if(data.schema!=='workman.fleet.history.v1'||data.host!==host||data.days!==days||!Array.isArray(data.rows)||data.rows.length>720||!data.rows.every(r=>Number.isSafeInteger(r.count)&&r.count>=0&&typeof r.at==='string'&&Number.isFinite(Date.parse(r.at))&&['cpuAvg','cpuPeak','gpuAvg','memoryAvg','diskFreeMin','rxAvg','txAvg'].every(k=>r[k]===null||Number.isFinite(r[k])&&r[k]>=0)&&['cpuCount','gpuCount','memoryCount'].every(k=>Number.isSafeInteger(r[k])&&r[k]>=0)))throw Error('Invalid');
    if(!container.isConnected||days!==selectedDays)return;
    container.innerHTML=`<section class="panel"><div class="history-head"><h2>Shared resource history</h2><label>Window <select id="sharedHistoryDays">${[1,7,30].map(n=>`<option value="${n}" ${days===n?'selected':''}>${n} day${n===1?'':'s'}</option>`).join('')}</select></label></div><p class="muted">${esc(data.basis)} ${data.rows.length} sampled hours. Windows and Unix use the same retained history.</p>${data.rows.length?`<div class="history-list">${data.rows.map(r=>`<div class="history-row shared-history-row"><div>${esc(new Date(r.at).toLocaleString())}<small>${r.count} distinct samples</small></div><div><span class="history-mobile-label">CPU</span>${format(r.cpuAvg,1,'%')} avg · ${format(r.cpuPeak,1,'%')} peak<small>${r.cpuCount} CPU readings</small></div><div><span class="history-mobile-label">GPU</span>${format(r.gpuAvg,1,'%')}<small>${r.gpuCount} GPU readings</small></div><div><span class="history-mobile-label">Memory</span>${format(r.memoryAvg,1,' GB')}<small>${r.memoryCount} memory readings</small></div><div><span class="history-mobile-label">Storage minimum</span>${format(r.diskFreeMin,1,' GB free')}</div></div>`).join('')}</div>`:'<p class="empty">No distinct samples retained in this window yet. History starts when this version is installed.</p>'}</section>`;
    container.querySelector('select').addEventListener('change',e=>{selectedDays=Number(e.target.value);loadSharedHistory(container,host);});
  }catch{
    if(container.isConnected)container.innerHTML='<section class="panel"><h2>Shared resource history</h2><p class="notice">The history service is unavailable. Earlier collector history below keeps its original timestamps.</p></section>';
  }
}
