import test from 'node:test';
import assert from 'node:assert/strict';
import {combineFleet,filterFleet,fleetSummary,freshness,validWindowsPayload,hostAlerts,operatingExpectation,mergeWindowsSources} from '../viewer/fleet-model.mjs';
const now=Date.parse('2026-10-14T18:00:00Z');
const at=new Date(now).toISOString();
const mac={app:'macfleet-dash',schema:1,hosts:[{host:'fixture-mac',os:'macOS',status:'available',observedAt:at,ramGb:16,memUsedGb:8,diskTotalGb:100,diskFreeGb:50}],history:{hosts:{},week:{}}};
const server={host:'fixture-server',name:'Server',platform:'windows',kind:'server',site:'Unassigned',enrollment:'enrolled',status:'available',observedAt:at,clockState:'skewed',clockSkewSeconds:1800,ramGb:16,memUsedGb:8,diskTotalGb:100,diskFreeGb:50,disks:[{drive:'C:',status:'available',freeGb:2,totalGb:10,usedGb:8},{drive:'E:',status:'available',freeGb:48,totalGb:90,usedGb:42}]};
const pending={host:'fixture-classroom',platform:'windows',kind:'range',site:'Brunswick',enrollment:'not-enrolled',status:'not-enrolled',observedAt:null};
const win={schema:'macfleet.windows.v1',hosts:[server,pending],history:{hosts:{},week:{}}};
test('OS, role and site groups intersect without duplicating host totals',()=>{
  const data=combineFleet(mac,win,{schema:'macfleet.registry.v1',hosts:{'fixture-mac':{kind:'server',site:'Norton'}}});
  assert.equal(data.hosts.length,3);assert.equal(filterFleet(data.hosts,'servers').length,2);
  assert.equal(filterFleet(data.hosts,'windows').length,2);assert.equal(filterFleet(data.hosts,'range','Brunswick').length,1);
  assert.equal(filterFleet(data.hosts,'servers','Norton').length,1);assert.equal(filterFleet(data.hosts,'servers','Brunswick').length,0);
  assert.equal(filterFleet(data.hosts,'all','all').length,3);
  const all=fleetSummary(data.hosts,now);assert.equal(all.registered,3);assert.equal(all.monitored,2);assert.equal(all.pending,1);assert.equal(all.responding,2);assert.equal(all.memUsed,16);
});
test('pending endpoints are not failures, fresh readings or zero resource usage',()=>{
  assert.equal(freshness(pending,now).state,'not-enrolled');assert.deepEqual(hostAlerts(pending,now),[]);
  const sum=fleetSummary([pending],now);assert.equal(sum.responding,0);assert.equal(sum.monitored,0);assert.equal(sum.pending,1);assert.equal(sum.memUsed,null);
});
test('one missing source does not hide verified rows from the other source',()=>{
  const data=combineFleet(null,win);assert.equal(data.hosts.length,2);assert.equal(data.version,null);
  const noWindows=combineFleet(mac);assert.equal(noWindows.hosts.length,1);
});
test('a client route failure is not a claim that Windows is offline',()=>{
  const row={...server,source:'windows-winrm',status:'unavailable',probeError:'ConnectionError',probeErrno:[65]};
  assert.equal(freshness(row,now).state,'client-unavailable');assert.equal(freshness(row,now).tone,'warn');
  assert.match(hostAlerts(row,now)[0].text,/not confirmed offline/);assert.equal(fleetSummary([row],now).responding,0);
});
test('clock warnings stay visible and each disk is checked rather than the machine free-space total',()=>{
  assert.equal(freshness(server,now).tone,'warn');assert.match(freshness(server,now).label,/clock/);
  const alerts=hostAlerts(server,now);assert.ok(alerts.some(a=>a.text.includes('Windows clock')));assert.ok(alerts.some(a=>a.text.includes('C:')));
  assert.equal(hostAlerts({...server,observedAt:'bad'},now)[0].text.includes('Time unverified'),true);
});
test('offline expectations honor explicit operating hours without guessing range opening times',()=>{
  const policy={timeZone:'America/New_York',days:{wed:[{start:'09:00',end:'17:00'}]}};
  assert.equal(operatingExpectation({expectedHours:policy},new Date('2026-10-14T18:00:00Z')),true);
  assert.equal(operatingExpectation({expectedHours:policy},new Date('2026-10-14T23:00:00Z')),false);
  assert.equal(operatingExpectation({kind:'range'}),null);
  const invalidHours={...policy,days:{wed:[{start:'99:99',end:'99:99'}]}};
  assert.equal(operatingExpectation({expectedHours:invalidHours},new Date(now)),null);
  assert.deepEqual(hostAlerts({...server,status:'unavailable',expectedHours:policy},Date.parse('2026-10-14T23:00:00Z')),[]);
  assert.equal(hostAlerts({...server,status:'unavailable',expectedHours:policy},now).length,1);
});
test('invalid/duplicate Windows identities are rejected rather than overwriting another source',()=>{
  assert.ok(validWindowsPayload(win));assert.equal(validWindowsPayload({...win,hosts:[server,server]}),false);
  assert.equal(validWindowsPayload({...win,hosts:[{...server,hostname:'FIXTURE-PC'},{...server,host:'other-alias',hostname:'fixture-pc'}]}),false);
  assert.throws(()=>combineFleet(mac,{...win,hosts:[{...server,host:'fixture-mac'}]}),/Duplicate/);
  assert.throws(()=>combineFleet(mac,{schema:'wrong',hosts:[]}),/schema/);
});
test('an answering host without resource readings is not labelled healthy',()=>{
  const row={...server,clockState:'verified',sampleState:'unavailable'};
  assert.equal(freshness(row,now).tone,'warn');assert.match(freshness(row,now).label,/readings unavailable/);
  assert.ok(hostAlerts(row,now).some(a=>a.text.includes('not a healthy')));
});
test('CCW, POS and 4473 filters intersect OS/location and All restores the same population',()=>{
  const rows=[{...pending,purpose:'ccw'},{...pending,host:'pos',purpose:'pos'},{...pending,host:'forms',site:'Norton',purpose:'4473'}];
  assert.equal(filterFleet(rows,'range','Brunswick','pos').length,1);
  assert.equal(filterFleet(rows,'range','Brunswick','4473').length,0);
  assert.equal(filterFleet(rows,'all','Norton','4473').length,1);
  assert.equal(filterFleet(rows,'all','all','all').length,3);
  assert.deepEqual(filterFleet(rows,'all','all','guessed'),[]);
});
test('a pinned push replaces its pending entry without changing counts or erasing WinRM rows',()=>{
  const row={...pending,hostname:'FIXTURE-CLASSROOM',enrollment:'enrolled',status:'available',observedAt:at,source:'windows-tailnet'};
  const tailnet={schema:win.schema,hosts:[row],history:{hosts:{[row.host]:[[at,2]]},week:{}}};
  const result=combineFleet(mac,win,null,tailnet);
  assert.equal(result.hosts.length,3);assert.equal(fleetSummary(result.hosts,now).pending,0);
  assert.equal(result.hosts.find(h=>h.host===pending.host).source,'windows-tailnet');
  assert.equal(result.hosts.find(h=>h.host===server.host).status,'available');
  assert.equal(result.history.hosts[row.host].length,1);
  assert.throws(()=>mergeWindowsSources({...win,hosts:[server,{...pending,enrollment:'enrolled',status:'available'}]},tailnet),/owners/);
  assert.throws(()=>mergeWindowsSources({...win,hosts:[server,{...pending,hostname:'WRONG-PC'}]},tailnet),/identity/);
});
test('a pilot shows actual readings but never counts as automatic or healthy coverage',()=>{
  const pilot={...server,source:'windows-tailnet',hostname:'FIXTURE-PC',enrollment:'pilot'};
  assert.ok(validWindowsPayload({...win,hosts:[pilot]}));
  assert.equal(freshness(pilot,now).state,'pilot');assert.deepEqual(hostAlerts(pilot,now),[]);
  const sum=fleetSummary([pilot],now);assert.equal(sum.monitored,0);assert.equal(sum.pending,1);assert.equal(sum.responding,0);assert.equal(sum.memUsed,null);
});
test('staged collector hosts stay pending and disappear as duplicates when the real source arrives',()=>{
  const draft={host:'fixture-pending-linux',hostname:'fixture-linux',kind:'server',platform:'linux',name:'Pending server',pendingReason:'Collector reload pending',cpuUsedPct:99};
  const registry={schema:'macfleet.registry.v1',hosts:{},pendingHosts:[draft]};
  const data=combineFleet(mac,win,registry);
  assert.equal(data.hosts.length,4);const row=data.hosts.find(h=>h.host===draft.host);
  assert.equal(row.status,'not-enrolled');assert.equal(row.cpuUsedPct,undefined);assert.equal(fleetSummary([row],now).monitored,0);
  assert.equal(filterFleet([row],'mac-linux').length,1);assert.equal(filterFleet([row],'servers').length,1);assert.equal(filterFleet([row],'windows').length,0);
  const fresh={...mac,hosts:[...mac.hosts,{host:draft.host,hostname:draft.hostname,os:'Linux',status:'available',observedAt:at}]};
  assert.equal(combineFleet(fresh,win,registry).hosts.length,4);
  assert.equal(combineFleet(fresh,win,registry).hosts.find(h=>h.host===draft.host).status,'available');
  assert.throws(()=>combineFleet(mac,win,{...registry,pendingHosts:[draft,draft]}),/identities/);
});
