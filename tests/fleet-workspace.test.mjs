import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyActivity,checkedActivity,observeActivity,MAX_ACTIVITY,starterConfig,stageBulkLocations,APP_CHANGES} from '../viewer/fleet-workspace.mjs';
import {setupPage,activityPage} from '../viewer/fleet-pages.mjs';
import {VIEWER_VERSION} from '../viewer/fleet-model.mjs';
const now=Date.parse('2026-10-16T02:00:00Z');
const host={host:'my-computer',name:'My computer',site:'Home',status:'available',enrollment:'enrolled',observedAt:new Date(now).toISOString(),ramGb:16,memUsedGb:8};

test('first snapshot establishes a baseline without inventing old activity',()=>{
  const first=observeActivity(emptyActivity(),[host],now);
  assert.deepEqual(first.events,[]);assert.equal(first.startedAt,new Date(now).toISOString());
  assert.deepEqual(observeActivity(first,[host],now+1000).events,[]);
});
test('observed stale and recovered readings are not described as power state',()=>{
  const first=observeActivity(emptyActivity(),[host],now);
  const stale=observeActivity(first,[host],now+11*60000);
  assert.equal(stale.events.length,1);assert.match(stale.events[0].text,/Data stale/);
  assert.doesNotMatch(stale.events[0].text,/powered off|is offline/);
  const fresh={...host,observedAt:new Date(now+12*60000).toISOString()};
  const recovered=observeActivity(stale,[fresh],now+12*60000);
  assert.equal(recovered.events.length,2);assert.match(recovered.events[1].text,/Responding/);
  assert.equal(first.events.length,0);
});
test('location events reflect saved effective values, not draft edits',()=>{
  const first=observeActivity(emptyActivity(),[host],now);
  const edits=stageBulkLocations([host],{},[host.host],'Office');
  assert.equal(edits[host.host],'Office');assert.deepEqual(first.events,[]);
  const changed=observeActivity(first,[{...host,site:'Office'}],now+1000);
  assert.equal(changed.events.length,1);assert.equal(changed.events[0].kind,'location');
  assert.match(changed.events[0].text,/Home to Office/);
  assert.equal(observeActivity(changed,[{...host,site:'Office'}],now+2000).events.length,1);
});
test('important alert changes are recorded without numeric-sample spam',()=>{
  const first=observeActivity(emptyActivity(),[host],now);
  const warning=observeActivity(first,[{...host,memUsedGb:15.5}],now+1000);
  assert.equal(warning.events.length,1);assert.match(warning.events[0].text,/Memory nearly full/);
  const next=observeActivity(warning,[{...host,memUsedGb:15.8}],now+2000);
  assert.equal(next.events.length,1);
  assert.match(observeActivity(next,[host],now+3000).events[1].text,/no longer present/);
});
test('activity is bounded, strictly validated and contains no raw telemetry',()=>{
  let value=observeActivity(emptyActivity(),[host],now);
  for(let i=1;i<=220;i++)value=observeActivity(value,[{...host,site:i%2?'Office':'Home'}],now+i*1000);
  assert.equal(value.events.length,MAX_ACTIVITY);
  const encoded=JSON.stringify(value);
  assert.doesNotMatch(encoded,/ramGb|memUsedGb|observedAt|credentials|endpoint/);
  for(const bad of [null,[],{...value,secret:'not permitted'},{...value,events:[{at:'bad',host:'../bad',kind:'connection',text:'bad'}]},{...value,baseline:{'../bad':{}}}])assert.throws(()=>checkedActivity(bad));
});
test('bulk locations preserve earlier draft edits and require current selection',()=>{
  const second={...host,host:'laptop'};
  assert.deepEqual(stageBulkLocations([host,second],{laptop:'Lab'},[host.host],' Home office '),{'my-computer':'Home office',laptop:'Lab'});
  assert.equal(host.site,'Home');
  assert.throws(()=>stageBulkLocations([host],{},[],'Home'));
  assert.throws(()=>stageBulkLocations([host],{},['missing'],'Home'));
  assert.throws(()=>stageBulkLocations([host],{},[host.host],'all'));
});
test('starter config contains only the new owner local computer',()=>{
  assert.deepEqual(starterConfig(),{interval:300,hosts:{'this-computer':{method:'local',name:'This computer',role:'My computer'}}});
  assert.doesNotMatch(JSON.stringify(starterConfig()),/100\.|192\.|workman|mini|studio|backup|token/i);
});
test('fresh setup renders guidance and snapshot checks instead of perpetual loading',()=>{
  const html=setupPage(null,[{name:'Mac / Linux readings',label:'Not configured / no snapshot yet'}],true,new Date(now).toISOString());
  assert.match(html,/Connect your first computer/);assert.match(html,/Download starter config/);
  assert.match(html,/Check connection/);assert.match(html,/No computers are available/);assert.doesNotMatch(html,/Loading fleet readings/);
  assert.match(html,/No verified inventory snapshot yet/);assert.doesNotMatch(html,/0 responding/);
  assert.match(html,/does not contact computers directly/);
});
test('activity and source check HTML escape untrusted computer and event labels',()=>{
  const value=observeActivity(emptyActivity(),[host],now);
  value.events=[{at:new Date(now).toISOString(),host:host.host,kind:'location',text:'<script>test</script>'}];
  const html=activityPage(value,[{...host,name:'<img src=x>'}],'');
  assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('&lt;img'));assert.doesNotMatch(html,/<script>|<img/);
  assert.match(html,/not a complete unattended audit log/);
});
test('generic change notes track current version and disclose deployment limits',()=>{
  assert.equal(APP_CHANGES[0].version,VIEWER_VERSION);
  assert.equal(APP_CHANGES[0].by,'Codex');assert.ok(Number.isFinite(Date.parse(APP_CHANGES[0].at)));
  assert.doesNotMatch(JSON.stringify(APP_CHANGES),/getscreen|192\.168|RANGE42S1|WFTRAININGSERVE|\/Users\//);
});
