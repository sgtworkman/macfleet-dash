export const VIEWER_VERSION = '0.7.0';
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
  if (row?.status !== 'available') return {state:'unavailable',label:'No answer',tone:'bad'};
  const age = ageMs(row.observedAt, now);
  if (age === null) return {state:'unverified',label:'Time unverified',tone:'warn'};
  return age > STALE_MS ? {state:'stale',label:'Data stale',tone:'warn'} : {state:'current',label:'Responding',tone:'good'};
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
  const current = hosts.filter(row=>freshness(row,now).state === 'current');
  const mem = current.map(memory).filter(Boolean), disks = current.map(storage).filter(Boolean);
  const sum = (rows,key) => rows.length ? rows.reduce((n,row)=>n+row[key],0) : null;
  return {monitored:hosts.length,responding:current.length,memUsed:sum(mem,'used'),memTotal:sum(mem,'total'),memKnown:mem.length,
    diskFree:sum(disks,'free'),diskKnown:disks.length};
}
export function hostAlerts(row, now = Date.now()) {
  const state = freshness(row,now);
  if (state.state !== 'current') return [{host:row.host,name:row.name||row.host,text:state.state === 'unavailable' ? 'Probe did not answer. Readings unavailable.' : state.label + '. Last sample is not current.'}];
  const result = [], disk = storage(row), mem = memory(row);
  if (disk && disk.free < 20) result.push({host:row.host,name:row.name||row.host,text:`Low storage: ${format(disk.free)} GB available (${format(disk.pct,0)}% used).`});
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
