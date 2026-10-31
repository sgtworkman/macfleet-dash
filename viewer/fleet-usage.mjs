import {validTokenPayload,escapeHtml as esc,ageMs} from './fleet-model.mjs?v=0.12.0';
const label=value=>typeof value==='string'&&value.trim().length>0&&value.length<=160&&!/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(value);
const identity=value=>typeof value==='string'&&/^[a-z0-9][a-z0-9.-]{0,62}$/.test(value);
export function validComputerUsagePayload(value){
  if(!validTokenPayload(value)||value.groups.some(row=>row.agentProfile!==undefined&&!label(row.agentProfile)))return false;
  if(value.computers===undefined)return true;
  return Array.isArray(value.computers)&&value.computers.length<=512&&new Set(value.computers.map(row=>row?.host)).size===value.computers.length&&value.computers.every(row=>row&&identity(row.host)&&label(row.name)&&['available','partial','unavailable','not-configured'].includes(row.status)&&(row.receivedAt===null||typeof row.receivedAt==='string'&&Number.isFinite(Date.parse(row.receivedAt)))&&(row.reason===null||label(row.reason))&&(row.usage===null?['unavailable','not-configured'].includes(row.status):row.usage.computers===undefined&&validTokenPayload(row.usage)&&row.usage.groups.every(group=>group.agentProfile===undefined||label(group.agentProfile))&&row.status===row.usage.status));
}
export function usageSelection(payload,hosts=[],requested=null,agent='all'){
  let computers=[];
  if(validComputerUsagePayload(payload))computers=payload.computers?[...payload.computers]:[{host:identity(payload.clientHost)?payload.clientHost:'localhost',name:'This collector',status:payload.status,usage:payload,reason:null,receivedAt:payload.observedAt}];
  const known=new Set(computers.map(row=>row.host));
  for(const host of hosts)if(identity(host.host)&&!known.has(host.host)){computers.push({host:host.host,name:host.name||host.host,status:'not-configured',usage:null,receivedAt:null,reason:'No aggregate usage collector configured for this computer'});known.add(host.host);}
  const computer=computers.find(row=>row.host===requested)||computers[0]||null;
  const profiles=[...new Set((computer?.usage?.groups||[]).map(row=>row.agentProfile||'Not recorded'))].sort();
  return {computers,computer,usage:computer?.usage||null,profiles,agent:agent==='all'||profiles.includes(agent)?agent:'all'};
}
export function usageControls(selection){
  const {computers,computer,profiles,agent}=selection;
  const readable=computers.filter(row=>['available','partial'].includes(row.status)&&ageMs(row.usage?.observedAt)!==null&&ageMs(row.usage?.observedAt)<=600000).length;
  return `<section class="panel usage-source-panel"><h2>Choose a computer and saved profile</h2><div class="usage-controls"><label>Read counters from<select id="tokenComputer" ${computers.length?'':'disabled'}>${computers.map(row=>`<option value="${esc(row.host)}" ${row.host===computer?.host?'selected':''}>${esc(row.name)}${row.status==='not-configured'?' · not configured':row.status==='unavailable'?' · unavailable':''}</option>`).join('')}</select></label><label>Saved agent / profile<select id="tokenAgent"><option value="all">All profiles</option>${profiles.map(profile=>`<option ${profile===agent?'selected':''} value="${esc(profile)}">${esc(profile)}</option>`).join('')}</select></label></div><p class="muted">${readable} / ${computers.length} listed computers have fresh readable Hermes counters. This is usage-source coverage, not computer-health or agent-process coverage.</p><p class="model-note">One source computer at a time—copied or migrated histories are not added into a fleet total. A saved profile identifies the retained database, not a proven running agent. Codex desktop, other clients, provider invoices and unrecorded traffic remain outside this coverage.</p>${computer&&!computer.usage?`<p class="notice">${esc(computer.name)}: ${esc(computer.reason||'Usage source unavailable')}. Missing usage is not zero.</p>`:''}<p class="muted">Historical recorded models below are separate from the current loaded-model panel. Unclassified endpoints remain unclassified; no model-name or price guess is used.</p></section>`;
}
