import test from 'node:test';
import assert from 'node:assert/strict';
import {number,percent,escapeHtml,format,freshness,storage,memory,fleetSummary,validPayload,validTokenPayload,hostAlerts,benchmark,hourlyHistory} from '../viewer/fleet-model.mjs';
const now=Date.parse('2026-10-14T12:00:00Z');
const row={host:'mini2',name:'Mini',status:'available',observedAt:'2026-10-14T11:57:00Z',diskTotalGb:926.4,diskFreeGb:12.4,diskUsedGb:12.7,ramGb:16,memUsedGb:14,swapUsedGb:3};
test('token envelopes must reconcile recorded category counters; unknown/nulls remain unknown',()=>{
  const group={category:'local',model:'fixture',provider:'custom',recordCount:1,inputTokens:100,outputTokens:10,cacheReadTokens:50,cacheWriteTokens:0};
  const empty={recordCount:0,inputTokens:null,outputTokens:null,cacheReadTokens:null,cacheWriteTokens:null};
  const d={schema:'macfleet.tokens.v1',status:'available',observedAt:'2026-10-14T11:57:00Z',groups:[group],totals:{local:{...group},cloud:{...empty},unknown:{...empty}}};
  assert.ok(validTokenPayload(d));const wrong=structuredClone(d);wrong.totals.local.inputTokens=150;assert.equal(validTokenPayload(wrong),false);
  assert.equal(validTokenPayload({...d,groups:[]}),false);assert.equal(validTokenPayload({...d,observedAt:'bad'}),false);
  const unknown=structuredClone(d);unknown.groups[0].inputTokens=null;unknown.totals.local.inputTokens=null;assert.ok(validTokenPayload(unknown));
});
test('absent, string, boolean, negative and nonfinite values never become zero',()=>{
  for(const v of [null,undefined,'0',false,-1,NaN,Infinity]){assert.equal(number(v),null);assert.equal(format(v),'Unavailable');}
  assert.equal(number(0),0);assert.equal(percent(101),null);assert.equal(percent(0),0);
});
test('APFS storage capacity reconciles used plus available independently of root filesystem used',()=>{
  const s=storage(row);assert.equal(s.used,914);assert.equal(s.used+s.free,s.total);assert.equal(row.diskUsedGb,12.7);
  for(const r of [{},{diskTotalGb:0,diskFreeGb:0},{diskTotalGb:20,diskFreeGb:21}])assert.equal(storage(r),null);
  assert.equal(memory({...row,memUsedGb:17}),null);assert.equal(memory(row).free,2);
});
test('reachability comes from fresh host rows, not optimistic header counts',()=>{
  assert.equal(freshness(row,now).state,'current');assert.equal(freshness({...row,observedAt:'2026-10-14T11:40:00Z'},now).state,'stale');
  assert.equal(freshness({...row,observedAt:'bad'},now).state,'unverified');assert.equal(freshness({...row,observedAt:'2026-10-14T14:00:00Z'},now).state,'unverified');
  const s=fleetSummary([row,{...row,host:'down',status:'unavailable'},{...row,host:'stale',observedAt:'2026-10-14T01:00:00Z'}],now);
  assert.equal(s.responding,1);assert.equal(s.memUsed,14);assert.equal(s.memKnown,1);assert.equal(fleetSummary([],now).memUsed,null);
});
test('alerts preserve unavailable/stale readings and expose actual low capacity',()=>{
  assert.match(hostAlerts(row,now)[0].text,/Low storage/);assert.match(hostAlerts({...row,status:'unavailable'},now)[0].text,/unavailable/);
  assert.match(hostAlerts({...row,observedAt:'2026-10-14T10:00:00Z'},now)[0].text,/not current/);
});
test('benchmark never invents usage or treats standalone tokPerS as verified throughput',()=>{
  assert.equal(benchmark({serving:{tokPerS:99}}),null);
  assert.deepEqual(benchmark({serving:{bench:{tokPerS:25.1,completionTokens:81,wallS:3.23}}}),{rate:25.1,output:81,seconds:3.23});
  assert.equal(benchmark({serving:{bench:{tokPerS:25,completionTokens:81,wallS:0}}}),null);
});
test('more than 400 week points work; averages exclude nulls and duplicate timestamps, blank hours are unknown',()=>{
  const points=Array.from({length:500},(_,i)=>[new Date(now-1000-i*300000).toISOString(),i%100,0,8]);
  const data={history:{week:{mini2:points}}},hours=hourlyHistory(data,'mini2','week',now);
  assert.equal(hours.reduce((n,h)=>n+h.count,0),500);assert.equal(hours.filter(h=>!h.count)[0].cpu.avg,null);
  const at='2026-10-14T11:30:00Z',h=hourlyHistory({history:{hosts:{mini2:[[at,0,null,8],[at,100,20,10],['2026-10-14T11:35:00Z',null,10,8]]}}},'mini2','day',now).find(h=>h.at==='2026-10-14T11:00:00.000Z');
  assert.equal(h.count,2);assert.equal(h.cpu.avg,0);assert.equal(h.cpu.count,1);assert.equal(h.gpu.avg,10);
});
test('labels are escaped and duplicate/invalid host payloads are rejected',()=>{
  assert.equal(escapeHtml('<img onerror="x">'), '&lt;img onerror=&quot;x&quot;&gt;');
  const p={app:'macfleet-dash',schema:1,hosts:[row]};assert.ok(validPayload(p));assert.equal(validPayload({...p,hosts:[row,row]}),false);
  assert.equal(validPayload({...p,hosts:[{host:null}]}),false);
});
