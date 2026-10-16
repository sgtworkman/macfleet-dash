import assert from 'node:assert/strict';
import test from 'node:test';
import {driveStorage,lastUpdateAge,hostAlerts,fleetSummary,sampleTimes,failureReason} from '../viewer/fleet-model.mjs';
import {readingMeta} from '../viewer/fleet-pages.mjs';
const now=Date.parse('2026-10-14T12:00:00Z');
const host={host:'fixture',name:'Fixture',enrollment:'enrolled',status:'available',observedAt:'2026-10-14T11:59:00Z'};

test('per-drive warnings cannot be hidden by another drive and invalid drives stay unknown',()=>{
  const system={drive:'C:',status:'available',totalGb:70,freeGb:12};
  assert.equal(driveStorage(system).free,12);
  for(const drive of [{...system,status:'unavailable'},{...system,totalGb:null},{...system,freeGb:null},{...system,freeGb:80},{...system,freeGb:false},{...system,drive:'unverified'}])assert.equal(driveStorage(drive),null);
  const alerts=hostAlerts({...host,diskFreeGb:572,diskTotalGb:830,disks:[system,{drive:'E:',status:'available',totalGb:760,freeGb:560}]},now);
  assert.equal(alerts.length,1);
  assert.match(alerts[0].text,/C: 12 GiB/);
  assert.doesNotMatch(alerts[0].text,/C::/);
  assert.match(alerts[0].text,/other drives do not offset/);
  assert.deepEqual(hostAlerts({...host,disks:[{...system,status:'unavailable'}]},now),[]);
});
test('missed-update alerts use actual receipt age without fabricating offline status',()=>{
  const stale={...host,observedAt:'2026-10-14T11:40:00Z'};
  assert.equal(lastUpdateAge(stale,now),'20 min ago');
  assert.match(hostAlerts(stale,now)[0].text,/Missed updates: last verified update 20 min ago/);
  assert.match(hostAlerts({...stale,status:'unavailable'},now)[0].text,/does not prove/);
  assert.equal(lastUpdateAge({...host,observedAt:null},now),'Time unverified');
  assert.equal(lastUpdateAge({...host,observedAt:'2026-10-14T14:00:00Z'},now),'Time unverified');
  assert.match(hostAlerts({...host,observedAt:'bad'},now)[0].text,/Time unverified/);
});
test('clock direction is explicit while receipt freshness remains independent',()=>{
  assert.match(hostAlerts({...host,clockState:'skewed',clockSkewSeconds:1800},now)[0].text,/30 min ahead of/);
  assert.match(hostAlerts({...host,clockState:'skewed',clockSkewSeconds:-1800},now)[0].text,/30 min behind/);
});
test('a failed Mac check timestamp is never presented as a successful reading',()=>{
  const row={...host,status:'unavailable',observedAt:'2026-10-14T11:59:00Z',refreshFailure:'http probe failed: connection refused'};
  assert.deepEqual(sampleTimes(row),{failed:true,readingAt:null,attemptAt:row.observedAt});
  const html=readingMeta(row),alert=hostAlerts(row,now)[0].text;
  assert.match(html,/Last successful reading: Not retained/);assert.match(html,/Latest failed check:/);
  assert.doesNotMatch(html,/(?:^|<br>)Last reading:/);
  assert.match(alert,/Last successful reading is not retained/);assert.doesNotMatch(alert,/last verified update/);
  assert.equal(failureReason(row),'Connection refused by the monitoring endpoint');
});
test('failed WinRM polls keep successful receipts distinct from newer attempts',()=>{
  const row={...host,source:'windows-winrm',status:'unavailable',receivedAt:'2026-10-14T11:20:00Z',observedAt:'2026-10-14T11:20:00Z',lastAttemptAt:'2026-10-14T11:59:00Z',probeError:'ConnectTimeout'};
  assert.deepEqual(sampleTimes(row),{failed:true,readingAt:row.receivedAt,attemptAt:row.lastAttemptAt});
  assert.match(readingMeta(row),/Last successful reading:/);assert.match(readingMeta(row),/Latest failed check:/);
  assert.match(hostAlerts(row,now)[0].text,/Last successful reading 40 min ago/);
  assert.equal(failureReason(row),'Monitoring connection timed out');
  assert.equal(sampleTimes({...row,receivedAt:null}).readingAt,null);
  assert.equal(sampleTimes({...row,lastAttemptAt:null}).attemptAt,null);
  assert.match(readingMeta(host),/^Last reading:/);
});
test('pilots and unconnected inventory remain separate and reconcile to registered rows',()=>{
  const rows=[host,{...host,host:'pilot',enrollment:'pilot'},{host:'pending',enrollment:'not-enrolled',status:'not-enrolled'}];
  const summary=fleetSummary(rows,now);
  assert.equal(summary.monitored,1);assert.equal(summary.responding,1);
  assert.equal(summary.pilots,1);assert.equal(summary.notEnrolled,1);assert.equal(summary.pending,2);
  assert.equal(summary.registered,summary.monitored+summary.pilots+summary.notEnrolled);
  assert.deepEqual(hostAlerts(rows[1],now),[]);assert.deepEqual(hostAlerts(rows[2],now),[]);
});
