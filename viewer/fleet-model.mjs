export const VIEWER_VERSION = '0.8.0';
export const STALE_MS = 10 * 60 * 1000;
export const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
export const percent = value => number(value) !== null && value <= 100 ? value : null;
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
export const format = (value, digits = 1, suffix = '') => number(value) === null ? 'Unavailable' : value.toLocaleString(undefined, {maximumFractionDigits:digits}) + suffix;
export function ageMs(at, now = Date.now()) {
  const timestamp = typeof at === 'string' ? Date.parse(at) : NaN;
  return Number.isFinite(timestamp) && timestamp <= now + 90000 ? Math.max(0, now - timestamp) : null;
}
export function freshness(row, now = Date.now()) {
  if (row?.enrollment === 'not-enrolled') return {state:'not-enrolled',label:'Not enrolled',tone:'muted'};
  if(row?.status!=='available'&&row?.source==='windows-winrm'&&row?.probeErrno?.includes(65))return {state:'client-unavailable',label:'Client LAN unavailable',tone:'warn'};
  if (row?.status !== 'available') return {state:'unavailable',label:'No answer',tone:'bad'};
  const age = ageMs(row.observedAt, now);
  if (age === null) return {state:'unverified',label:'Time unverified',tone:'warn'};
  return age > STALE_MS ? {state:'stale',label:'Data stale',tone:'warn'} : {state:'current',label:row.clockState==='skewed'?'Responding · clock warning':row.sampleState==='partial'?'Responding · partial readings':row.sampleState==='unavailable'?'Responding · readings unavailable':'Responding',tone:row.clockState==='skewed'||['partial','unavailable'].includes(row.sampleState)?'warn':'good'};
}
export const FLEET_GROUPS = [{id:'all',label:'All computers'},{id:'mac-linux',label:'Mac / Linux'},{id:'windows',label:'Windows'},{id:'servers',label:'Servers'},{id:'range',label:'Range computers'}];
export function platform(row) {
  if (row?.platform==='windows') return 'windows';
  if (/^macOS/i.test(row?.os||'')) return 'mac';
  if (/linux/i.test(row?.os||'')) return 'linux';
  return 'unknown';
}
export function validWindowsPayload(value) {
  return value?.schema==='macfleet.windows.v1' && Array.isArray(value.hosts)
    && value.hosts.every(r=>r && typeof r.host==='string' && r.host.length>0 && ['windows','unknown'].includes(r.platform) && ['enrolled','not-enrolled'].includes(r.enrollment) && ['available','unavailable','not-enrolled'].includes(r.status) && (r.enrollment!=='not-enrolled'||r.status==='not-enrolled') && (r.enrollment!=='enrolled'||r.platform==='windows'))
    && new Set(value.hosts.map(r=>r.host)).size===value.hosts.length
    && (()=>{const names=value.hosts.filter(r=>r.enrollment==='enrolled'&&typeof r.hostname==='string').map(r=>r.hostname.toLocaleLowerCase());return new Set(names).size===names.length;})();
}
export function combineFleet(base,windows=null,registry=null) {
  if (!base&&!windows) return null;
  if (base&&!validPayload(base) || windows&&!validWindowsPayload(windows)) throw Error('Fleet source schema unverified');
  const seed=base||{app:'macfleet-dash',schema:1,hosts:[],history:{},version:null,observedAt:null};
  const metadata=registry?.schema==='macfleet.registry.v1'&&registry.hosts&&typeof registry.hosts==='object'?registry.hosts:{};
  const hosts=seed.hosts.map(r=>({...r,kind:metadata[r.host]?.kind||'computer',site:metadata[r.host]?.site||'Unassigned'}));
  for(const row of windows?.hosts||[]) {
    if(hosts.some(r=>r.host===row.host)) throw Error('Duplicate host identity across sources');
    hosts.push({...row,site:row.site||'Unassigned'});
  }
  const history={hosts:{...seed.history?.hosts,...windows?.history?.hosts},week:{...seed.history?.week,...windows?.history?.week}};
  return {...seed,hosts,history};
}
export function filterFleet(hosts,group='all',site='all') {
  if(!FLEET_GROUPS.some(g=>g.id===group)) return [];
  return hosts.filter(r=>(site==='all'||(r.site||'Unassigned')===site) && (group==='all'||group==='mac-linux'&&['mac','linux'].includes(platform(r))||group==='windows'&&platform(r)==='windows'||group==='servers'&&r.kind==='server'||group==='range'&&r.kind==='range'));
}
export function operatingExpectation(row,at=new Date()) {
  const hours=row?.expectedHours;
  if(hours==='always')return true;
  if(!hours || typeof hours!=='object' || !hours.timeZone || !hours.days)return null;
  try {
    const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:hours.timeZone,weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(at).map(p=>[p.type,p.value]));
    const intervals=hours.days[parts.weekday.toLowerCase()];
    if(!Array.isArray(intervals))return null;
    const clock=parts.hour+':'+parts.minute;
    const validClock=/^(?:[01]\d|2[0-3]):[0-5]\d$/;
    if(intervals.some(p=>!validClock.test(p?.start||'')||!validClock.test(p?.end||'')||p.start>=p.end))return null;
    return intervals.some(p=>p.start<=clock&&clock<p.end);
  }catch{return null;}
}
export function storage(row) {
  const total = number(row?.diskTotalGb), free = number(row?.diskFreeGb);
  if (total === null || total === 0 || free === null || free > total) return null;
  return {total,free,used:Math.round((total-free)*10)/10,pct:(total-free)/total*100};
}
export function memory(row) {
  const total = number(row?.ramGb), used = number(row?.memUsedGb);
  if (total === null || total === 0 || used === null || used > total) return null;
  return {total,used,free:Math.round((total-used)*10)/10,pct:used/total*100};
}
export function validPayload(data) {
  return data?.app === 'macfleet-dash' && data.schema === 1 && Array.isArray(data.hosts)
    && data.hosts.every(row => row && typeof row.host === 'string' && row.host.length > 0)
    && new Set(data.hosts.map(row=>row.host)).size === data.hosts.length;
}
export function validTokenPayload(data) {
  if (data?.schema !== 'macfleet.tokens.v1' || !['available','partial','unavailable'].includes(data.status) || !Array.isArray(data.groups)) return false;
  if (data.status !== 'unavailable' && (!data.groups.length || !Number.isFinite(Date.parse(data.observedAt)))) return false;
  const fields=['inputTokens','outputTokens','cacheReadTokens','cacheWriteTokens'];
  for(const group of data.groups) {
    if(!['local','cloud','unknown'].includes(group?.category) || typeof group.model!=='string' || typeof group.provider!=='string' || !Number.isSafeInteger(group.recordCount) || group.recordCount<=0) return false;
    if(fields.some(key=>group[key]!==null && (!Number.isSafeInteger(group[key]) || group[key]<0))) return false;
  }
  for(const category of ['local','cloud','unknown']) {
    const rows=data.groups.filter(row=>row.category===category),total=data.totals?.[category];
    if(!total || total.recordCount!==rows.reduce((n,row)=>n+row.recordCount,0)) return false;
    for(const key of fields) {
      const expected=rows.length && rows.every(row=>row[key]!==null) ? rows.reduce((n,row)=>n+row[key],0) : null;
      if(total[key]!==expected) return false;
    }
  }
  return true;
}
export function fleetSummary(hosts, now = Date.now()) {
  const enrolled=hosts.filter(row=>row.enrollment!=='not-enrolled'),current = enrolled.filter(row=>freshness(row,now).state === 'current');
  const mem = current.map(memory).filter(Boolean), disks = current.map(storage).filter(Boolean);
  const sum = (rows,key) => rows.length ? rows.reduce((n,row)=>n+row[key],0) : null;
  return {monitored:enrolled.length,pending:hosts.length-enrolled.length,registered:hosts.length,responding:current.length,memUsed:sum(mem,'used'),memTotal:sum(mem,'total'),memKnown:mem.length,
    diskFree:sum(disks,'free'),diskKnown:disks.length};
}
export function hostAlerts(row, now = Date.now()) {
  const state = freshness(row,now);
  if(state.state==='not-enrolled')return [];
  if(operatingExpectation(row,new Date(now))===false && state.state!=='current')return [];
  if(state.state==='client-unavailable')return [{host:row.host,name:row.name||row.host,text:'The scheduled client cannot reach the LAN. Windows availability is unverified, not confirmed offline.'}];
  if (state.state !== 'current') return [{host:row.host,name:row.name||row.host,text:state.state === 'unavailable' ? 'Probe did not answer. Readings unavailable.' : state.label + '. Last sample is not current.'}];
  const result = [], disk = storage(row), mem = memory(row);
  if(row.clockState==='skewed') result.push({host:row.host,name:row.name||row.host,text:`Windows clock differs by ${format(Math.abs(row.clockSkewSeconds)/60)} min. Freshness uses the authenticated poll receipt.`});
  if(row.sampleState==='partial') result.push({host:row.host,name:row.name||row.host,text:'Some Windows readings are unavailable. No missing counter is treated as zero.'});
  if(row.sampleState==='unavailable') result.push({host:row.host,name:row.name||row.host,text:'Windows answered, but resource readings are unavailable. This is not a healthy resource report.'});
  if(Array.isArray(row.disks)) {
    for(const drive of row.disks)if(drive.status==='available'&&number(drive.freeGb)!==null&&drive.freeGb<20)result.push({host:row.host,name:row.name||row.host,text:`Low storage ${drive.drive}: ${format(drive.freeGb)} GiB available.`});
  } else if (disk && disk.free < 20) result.push({host:row.host,name:row.name||row.host,text:`Low storage: ${format(disk.free)} GB available (${format(disk.pct,0)}% used).`});
  if (number(row.swapUsedGb) !== null && row.swapUsedGb > 8) result.push({host:row.host,name:row.name||row.host,text:`High swap: ${format(row.swapUsedGb)} GB in use.`});
  if (mem && mem.pct >= 95) result.push({host:row.host,name:row.name||row.host,text:`Memory nearly full: ${format(mem.pct,0)}% used.`});
  return result;
}
export function benchmark(row) {
  const source = row?.serving?.bench;
  if (!source || number(source.tokPerS) === null || number(source.completionTokens) === null || !(number(source.wallS) > 0)) return null;
  return {rate:source.tokPerS,output:source.completionTokens,seconds:source.wallS};
}
export function hourlyHistory(data, host, period = 'day', now = Date.now()) {
  const hours = period === 'week' ? 168 : 24, start = now - hours*3600000;
  const series = (period === 'week' ? data?.history?.week : data?.history?.hosts)?.[host];
  const buckets = new Map();
  for (let hour = Math.floor(start/3600000)*3600000; hour <= now; hour += 3600000) buckets.set(hour,[]);
  const seen = new Set();
  for (const point of Array.isArray(series) ? series : []) {
    if (!Array.isArray(point)) continue;
    const at = Date.parse(point[0]);
    if (!Number.isFinite(at) || at < start || at > now || seen.has(at)) continue;
    seen.add(at); buckets.get(Math.floor(at/3600000)*3600000)?.push(point);
  }
  const stats = (rows,index,validator = number) => {
    const values = rows.map(point=>validator(point[index])).filter(value=>value !== null);
    return {count:values.length,avg:values.length ? values.reduce((a,b)=>a+b,0)/values.length : null,peak:values.length ? Math.max(...values) : null};
  };
  return [...buckets].reverse().map(([at,rows])=>({at:new Date(at).toISOString(),count:rows.length,cpu:stats(rows,1,percent),gpu:stats(rows,2,percent),mem:stats(rows,3)}));
}
