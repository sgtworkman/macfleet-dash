import {escapeHtml as esc,format,ageMs} from './fleet-model.mjs?v=0.10.0';

const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const label=v=>typeof v==='string'&&v.trim().length>0&&v.length<=200&&!/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/.test(v);
const id=v=>typeof v==='string'&&/^[a-z0-9][a-z0-9.-]{0,62}$/.test(v);
const num=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1e15;
const integer=v=>Number.isSafeInteger(v)&&v>=0;
const time=v=>typeof v==='string'&&Number.isFinite(Date.parse(v));
const nullable=(v,check)=>v===null||check(v);
const historyRanges=['1h','6h','24h','7d','30d'];
const counterFields=['promptTokens','completionTokens','cachedTokens'];
const endpointFields=['generationTps','prefillTps','cachedPrefillTps','uncachedPrefillTps','slotsActive','slotsTotal','requestsRunning','requestsWaiting','kvCacheUsage'];
const stamp=v=>v===null||v===undefined?'Unavailable':new Date(v).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
const envelope=v=>object(v)&&['available','unavailable'].includes(v.status)&&nullable(v.observedAt,time)&&time(v.lastAttemptAt)&&nullable(v.reason,label);
const points=(rows,fields)=>Array.isArray(rows)&&rows.length<=600&&rows.every((row,i)=>object(row)&&integer(row.t)&&(!i||row.t>rows[i-1].t)&&Object.entries(row).every(([key,value])=>key==='t'||fields.includes(key)&&object(value)&&num(value.avg)&&num(value.max)&&value.avg<=value.max&&(value.min===undefined||num(value.min)&&value.min<=value.avg)));
const history=v=>envelope(v)&&(v.status==='unavailable'&&v.enabled===undefined&&v.points===undefined&&v.llm===undefined||typeof v.enabled==='boolean'&&historyRanges.includes(v.range)&&Array.isArray(v.points)&&Array.isArray(v.llm)&&(v.enabled===false?v.points.length===0&&v.llm.length===0:integer(v.stepMs)&&v.stepMs>0&&integer(v.from)&&integer(v.to)&&v.from<v.to&&points(v.points,['gpuUtil','gpuTemp','gpuPower','memUsedMB','memFreeMB','cpuUtil','cpuTemp','ramUsedMB','netRx','netTx'])&&v.llm.length<=16&&new Set(v.llm.map(r=>r.port)).size===v.llm.length&&v.llm.every(r=>object(r)&&integer(r.port)&&r.port>0&&r.port<=65535&&points(r.points,['genTps','prefillTps','kvUsage']))));

function tokenReport(value,units){
  if(!envelope(value))return false;
  if(value.rows===undefined)return value.status==='unavailable';
  if(!Array.isArray(value.rows)||value.rows.length>4096)return false;
  const seen=new Set();
  return value.rows.every(row=>{
    if(!object(row)||!units.some(unit=>unit.id===row.unit)||!integer(row.port)||row.port===0||row.port>65535||!label(row.model)||!integer(row.sourceUpdatedAt)||!counterFields.every(field=>nullable(row[field],integer)))return false;
    const key=JSON.stringify([row.unit,row.port,row.model]);
    if(seen.has(key))return false;
    seen.add(key);return true;
  });
}

export function validSparkdashPayload(value){
  return object(value)&&value.schema==='macfleet.sparkdash.v1'&&time(value.observedAt)&&['not-configured','available','partial','unavailable'].includes(value.status)&&nullable(value.sourceId,v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v))&&nullable(value.reason,label)&&Array.isArray(value.units)&&value.units.length<=4&&new Set(value.units.map(row=>row?.id)).size===value.units.length&&value.units.every(row=>object(row)&&id(row.id)&&label(row.name)&&nullable(row.host,id)&&envelope(row)&&nullable(row.online,v=>typeof v==='boolean')&&nullable(row.worker,v=>typeof v==='boolean')&&Array.isArray(row.endpoints)&&row.endpoints.length<=16&&new Set(row.endpoints.map(e=>e?.port)).size===row.endpoints.length&&row.endpoints.every(e=>object(e)&&integer(e.port)&&e.port>0&&e.port<=65535&&typeof e.available==='boolean'&&['backend','modelId','generationTpsSource'].every(k=>nullable(e[k],label))&&endpointFields.every(k=>nullable(e[k],num))&&['decodeActive','prefillActive'].every(k=>nullable(e[k],v=>typeof v==='boolean')))&&object(row.history)&&historyRanges.every(range=>history(row.history[range])))&&object(value.totals)&&['1h','6h','24h'].every(range=>value.status==='not-configured'||!value.units.length||tokenReport(value.totals[range],value.units));
}

export function freshSparkRead(value,failed=false,now=Date.now()){
  const age=ageMs(value?.observedAt,now);
  return !failed&&value?.status==='available'&&age!==null&&age<=600000;
}

export function engineTokenRows(payload,range='24h',unit='all'){
  const rows=payload?.totals?.[range]?.rows||[],grouped=new Map();
  for(const row of rows){
    if(unit!=='all'&&row.unit!==unit)continue;
    const key=JSON.stringify([row.unit,row.model]);
    const target=grouped.get(key)||{unit:row.unit,model:row.model,ports:[],promptTokens:0,completionTokens:0,cachedTokens:0};
    target.ports.push(row.port);
    for(const field of counterFields){const sum=target[field]!==null&&row[field]!==null?target[field]+row[field]:null;target[field]=integer(sum)?sum:null;}
    grouped.set(key,target);
  }
  return [...grouped.values()];
}

function notice(value,failed){
  if(freshSparkRead(value,failed))return '';
  return `<p class="notice">${value?.status==='unavailable'?'Latest SparkDash read failed.':failed?'Latest local snapshot read failed.':'SparkDash snapshot is stale or its time is unverified.'} ${value?.observedAt?'Retained report received '+esc(stamp(value.observedAt))+'. ':''}These are not current readings.</p>`;
}

function endpointFacts(endpoint,usable){
  const rate=(value,active)=>!usable?'Unverified':value===null?'Not reported':value===0&&active!==true?'No active rate reported':format(value,1)+' tokens/s';
  return `<dl class="ai-facts"><div><dt>Decode · reported</dt><dd>${esc(rate(endpoint.generationTps,endpoint.decodeActive))}</dd></div><div><dt>Prefill · reported</dt><dd>${esc(rate(endpoint.prefillTps,endpoint.prefillActive))}</dd></div><div><dt>Running / queued</dt><dd>${usable?format(endpoint.requestsRunning,0)+' / '+format(endpoint.requestsWaiting,0):'Unverified'}</dd></div><div><dt>Occupied / total slots</dt><dd>${usable?format(endpoint.slotsActive,0)+' / '+format(endpoint.slotsTotal,0):'Unverified'}</dd></div></dl>`;
}

function unitCard(unit,failed=false){
  const usable=freshSparkRead(unit,failed)&&unit.online===true;
  return `<article class="panel ai-unit" data-ai-unit="${esc(unit.id)}"><div class="section-head"><h2>${esc(unit.name)}</h2><span class="status ${usable?'good':'warn'}">${usable?'Snapshot received':unit.online===false?'Reported offline':'Unverified'}</span></div>${notice(unit,failed)}${unit.worker?'<p class="muted">Worker node. A shared head model is not a second token-producing engine.</p>':''}${unit.endpoints.length?unit.endpoints.map(endpoint=>`<section class="ai-endpoint"><p class="ai-model">${esc(usable&&endpoint.available?endpoint.modelId||'Model not reported':'Model unverified')}</p><p class="muted">${esc(endpoint.backend||'Engine not reported')} · port ${endpoint.port}${!endpoint.available?' · endpoint unavailable':''}</p>${endpointFacts(endpoint,usable&&endpoint.available)}</section>`).join(''):'<p class="empty">No separate monitored AI endpoint reported.</p>'}<p class="last-seen">Snapshot received ${esc(stamp(unit.observedAt))}${unit.host?` · <a href="#host/${encodeURIComponent(unit.host)}">Computer details →</a>`:' · not mapped into MacFleet computer counts'}</p></article>`;
}

export function sparkHostBrief(row,payload,failed=false){
  const unit=payload?.units?.find(unit=>unit.host===row.host);
  if(!unit)return '';
  const live=freshSparkRead(unit,failed)&&unit.online===true,endpoint=unit.endpoints.find(endpoint=>endpoint.available);
  return `<div class="current-model-brief ai-brief"><small>AI report · SparkDash</small><strong class="${live&&endpoint?'good':'warn'}">${esc(live&&endpoint?endpoint.modelId||'Model not reported':'AI report unverified')}</strong>${endpoint?endpointFacts(endpoint,live):'<small>No monitored endpoint reported</small>'}<small>Received ${esc(stamp(unit.observedAt))} · individual probe age not supplied</small><a class="action-link" href="#ai">AI engines, token windows &amp; history →</a></div>`;
}

export function historyPath(rows,field,stat,from,to,step){
  let previous=null,path='';
  for(const point of rows){
    const value=point[field]?.[stat];
    if(!num(value)||value>100){previous=null;continue;}
    const x=50+(point.t-from)/(to-from)*700,y=140-value*1.2;
    path+=(previous!==null&&point.t-previous<=step*1.5?'L':'M')+x.toFixed(2)+' '+y.toFixed(2)+' ';
    previous=point.t;
  }
  return path.trim();
}

function historySection(unit,range,failed){
  const data=unit.history[range];
  if(!data)return '<p class="notice">History unavailable for this unit.</p>';
  if(data.enabled===false)return `<section class="panel"><h2>${esc(unit.name)} · history</h2>${notice(data,failed)}<p class="empty">Metrics history is off in the last SparkDash report. MacFleet does not enable it or invent earlier samples.</p></section>`;
  const rows=data.points||[],llm=new Map((data.llm||[]).map(endpoint=>[endpoint.port,new Map(endpoint.points.map(point=>[point.t,point]))]));
  const timestamps=[...new Set([...rows.map(p=>p.t),...(data.llm||[]).flatMap(e=>e.points.map(p=>p.t))])].sort((a,b)=>b-a),byTime=new Map(rows.map(p=>[p.t,p]));
  const avgPeak=(stat,unit='')=>stat?format(stat.avg,1,unit)+' / '+format(stat.max,1,unit):'Unavailable';
  const chart=data.from&&rows.length?`<div class="ai-chart"><svg viewBox="0 0 780 178" role="img" aria-label="${esc(unit.name)} CPU and GPU history. Fixed zero to one hundred percent scale; missing readings are gaps."><path d="M50 20H750 M50 80H750 M50 140H750" class="ai-gridline"/><text x="4" y="24">100%</text><text x="12" y="84">50%</text><text x="20" y="144">0%</text>${[['gpuUtil','gpu'],['cpuUtil','cpu']].flatMap(([field,color])=>['avg','max'].map(stat=>`<path d="${historyPath(rows,field,stat,data.from,data.to,data.stepMs)}" class="ai-trace ${color} ${stat}"/>`)).join('')}<text x="50" y="169">${esc(stamp(data.from))}</text><text x="750" y="169" text-anchor="end">${esc(stamp(data.to))}</text></svg><p class="ai-legend"><span>GPU · purple</span><span>CPU · amber</span><span>Solid: average · dashed: peak</span><span>Fixed 0–100% scale</span></p></div>`:'';
  return `<section class="panel ai-history"><div class="section-head"><h2>${esc(unit.name)} · history</h2><small>${rows.length} resource buckets${data.stepMs?' · '+format(data.stepMs/60000,0)+' min resolution':''}</small></div>${notice(data,failed)}${chart}${!timestamps.length?'<p class="empty">No recorded history in this window. Missing samples are not zero.</p>':`<details class="ai-records" open><summary>Memory headroom, network and AI performance · ${timestamps.length} recorded times</summary><div class="ai-table-scroll"><table class="token-table"><caption>Newest first. Resource and rate cells show average / peak; headroom shows the minimum. A missing bucket is unavailable.</caption><thead><tr><th>Time</th><th>GPU %</th><th>CPU %</th><th>Headroom minimum · MB</th><th>Network ↓ / ↑ · B/s average</th><th>AI decode / prefill · tokens/s average (peak)</th></tr></thead><tbody>${timestamps.map(at=>{const point=byTime.get(at)||{};return `<tr><td>${esc(stamp(at))}</td><td>${avgPeak(point.gpuUtil)}</td><td>${avgPeak(point.cpuUtil)}</td><td>${format(point.memFreeMB?.min,1)}</td><td>${format(point.netRx?.avg,0)} / ${format(point.netTx?.avg,0)}</td><td>${[...llm].map(([port,values])=>{const item=values.get(at);return `<span class="ai-history-rate">:${port} · ${format(item?.genTps?.avg,1)} (${format(item?.genTps?.max,1)}) / ${format(item?.prefillTps?.avg,1)} (${format(item?.prefillTps?.max,1)})</span>`;}).join('')||'No endpoint samples'}</td></tr>`;}).join('')}</tbody></table></div></details>`}<p class="last-seen">History received ${esc(stamp(data.observedAt))}. Ranges show retained data only; older history is not backfilled.</p></section>`;
}

function tokensSection(payload,range,unit,failed){
  const report=payload.totals[range],rows=engineTokenRows(payload,range,unit),names=new Map(payload.units.map(row=>[row.id,row.name]));
  const total=field=>rows.length&&rows.every(row=>row[field]!==null)?rows.reduce((sum,row)=>sum+row[field],0):null;
  return `<section class="panel"><h2>Engine token totals · ${esc(range)}</h2>${notice(report,failed)}<p class="model-note">Counted by SparkDash at the local engines—not Hermes client records or cloud billing. Hourly UTC buckets cover up to ${esc(range)}; the current hour is partial. Cached tokens are part of prompt tokens, not added again.</p><div class="summary">${[['completionTokens','Generated'],['promptTokens','Prompt · includes cached'],['cachedTokens','Cached']].map(([field,title])=>`<div class="panel"><strong>${format(total(field),0)}</strong><small>${esc(title)}</small></div>`).join('')}<div class="panel"><strong>${rows.length}</strong><small>Machine / model rows</small></div></div>${rows.length?`<div class="ai-table-scroll"><table class="token-table"><caption>Per machine and model; ports serving the same model on a machine are combined.</caption><thead><tr><th>Machine / model</th><th>Generated</th><th>Prompt</th><th>Cached</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(names.get(row.unit))}<small>${esc(row.model)} · ports ${row.ports.join(', ')}</small></td>${['completionTokens','promptTokens','cachedTokens'].map(field=>`<td class="num">${format(row[field],0)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p class="empty">No counted model rows in this selection. This does not establish zero fleet traffic.</p>'}<p class="last-seen">Ledger received ${esc(stamp(report?.observedAt))}. Only the configured SparkDash units are included.</p></section>`;
}

export function sparkdashPage(payload,{view='engines',unit='all',range='24h',historyRange='1h',failed=false}={}){
  const tabs=`<nav class="tabs ai-tabs" aria-label="AI views"><a href="#ai" ${view==='engines'?'aria-current="page"':''}>Engines</a><a href="#ai/tokens" ${view==='tokens'?'aria-current="page"':''}>Engine tokens</a><a href="#ai/history" ${view==='history'?'aria-current="page"':''}>History</a><a href="#tokens">Hermes / cloud counters</a></nav>`;
  if(!payload||payload.status==='not-configured'||!payload.units.length)return tabs+`<section class="panel"><h2>Connect an existing SparkDash</h2>${payload?.reason?'<p class="notice">'+esc(payload.reason)+'</p>':''}<p class="empty">No verified SparkDash source is configured. MacFleet still works independently.</p><p>Enable the optional private connector in your own MacFleet configuration, then use the existing snapshot refresh. No credentials, computer list or live data comes with the download.</p><a class="view-detail" href="#setup">Setup &amp; connection checks →</a></section>`;
  if(!payload.units.some(row=>row.id===unit))unit='all';
  const units=payload.units.filter(row=>unit==='all'||row.id===unit),selected=view==='history'?historyRange:range;
  const controls=`<div class="usage-controls ai-controls"><label>AI machine<select id="aiUnit"><option value="all">All configured AI machines</option>${payload.units.map(row=>`<option value="${esc(row.id)}" ${row.id===unit?'selected':''}>${esc(row.name)}</option>`).join('')}</select></label>${view==='engines'?'':`<label>${view==='history'?'History window':'Token window'}<select id="aiRange">${(view==='history'?historyRanges:['1h','6h','24h']).map(value=>`<option value="${value}" ${value===selected?'selected':''}>${value}</option>`).join('')}</select></label>`}</div>`;
  return tabs+controls+(view==='engines'?`<div class="grid ai-units">${units.map(row=>unitCard(row,failed)).join('')}</div><details class="connection-guide"><summary>About these AI readings</summary><p>These are cached, read-only SparkDash reports. Receipt time is shown; this API does not supply individual engine-probe timestamps, so a recently received snapshot alone does not verify probe age. Missing queues, capacity and rates stay unavailable. An engine report does not establish computer health.</p><p>MacFleet does not poll engines again, send prompts, start benchmarks or change model routing. Worker nodes and linked computer views are not extra token-producing engines.</p></details>`:view==='tokens'?tokensSection(payload,range,unit,failed):`<div class="ai-history-list">${units.map(row=>historySection(row,historyRange,failed)).join('')}</div>`);
}
