import assert from 'node:assert/strict';
import test from 'node:test';
import {validComputerUsagePayload,usageSelection,usageControls} from '../viewer/fleet-usage.mjs';
import {coveragePage} from '../viewer/fleet-pages.mjs';
const now=Date.now(),at=new Date(now).toISOString();
const empty={recordCount:0,inputTokens:null,outputTokens:null,cacheReadTokens:null,cacheWriteTokens:null};
const group={category:'local',provider:'custom',model:'demo-vlm',agentProfile:'demo-agent',targetName:'Demo AI',recordCount:1,inputTokens:100,outputTokens:10,cacheReadTokens:50,cacheWriteTokens:0};
const usage={schema:'macfleet.tokens.v1',status:'available',observedAt:at,clientHost:'localhost',groups:[group],totals:{local:{...group},cloud:empty,unknown:empty}};
const payload={...usage,computers:[{host:'localhost',name:'Demo local',status:'available',usage,receivedAt:at,reason:null},{host:'other',name:'Demo other',status:'unavailable',usage:null,receivedAt:at,reason:'Existing source unavailable'}]};
test('computer selection never combines histories or guesses a missing source total',()=>{
  assert.ok(validComputerUsagePayload(payload));
  const selected=usageSelection(payload,[{host:'pending',name:'Pending'}],'other');
  assert.equal(selected.usage,null);assert.equal(selected.computers.length,3);
  assert.match(usageControls(selected),/Missing usage is not zero/);
  assert.match(usageControls(selected),/never|not added into a fleet total/);
  assert.equal(usageSelection(payload).usage.totals.local.inputTokens,100);
});
test('saved profiles are selectable evidence labels, not running-agent claims',()=>{
  const selected=usageSelection(payload,[],'localhost','demo-agent');
  assert.equal(selected.agent,'demo-agent');assert.deepEqual(selected.profiles,['demo-agent']);
  assert.equal(usageSelection(payload,[],'localhost','missing').agent,'all');
  assert.match(usageControls(selected),/not a proven running agent/);
});
test('legacy snapshots still work but malformed nested records do not become coverage',()=>{
  assert.ok(validComputerUsagePayload(usage));
  assert.equal(usageSelection(usage).computer.host,'localhost');
  for(const value of [{...payload,computers:[payload.computers[0],payload.computers[0]]},{...payload,computers:[{...payload.computers[0],usage:{...usage,computers:[]}}]},{...payload,computers:[{...payload.computers[0],status:'not-configured'}]},{...payload,groups:[{...group,agentProfile:'bad\nlabel'}]}])assert.equal(validComputerUsagePayload(value),false);
});
test('usage controls escape labels and stale sources do not count fresh',()=>{
  const candidate={...payload,computers:[{...payload.computers[0],name:'<img src=x>',usage:{...usage,observedAt:new Date(now-700000).toISOString()}}]};
  const html=usageControls(usageSelection(candidate));
  assert.ok(html.includes('&lt;img'));assert.doesNotMatch(html,/<img/);assert.match(html,/0 \/ 1 listed computers/);
});
test('repair queue uses host rows, keeps pending separate and cannot claim power-off',()=>{
  const rows=[{host:'fresh',name:'Fresh',status:'available',observedAt:at,os:'macOS',ramGb:16,memUsedGb:10},{host:'stale',name:'Stale',status:'available',observedAt:new Date(now-700000).toISOString(),os:'macOS'},{host:'pending',name:'Pending <x>',status:'not-enrolled',enrollment:'not-enrolled',pendingReason:'Confirm native identity',observedAt:null}];
  const html=coveragePage(rows,now);
  assert.match(html,/1 fresh \/ 2 monitored/);assert.match(html,/1 pending/);assert.match(html,/does not prove power-off/);assert.match(html,/Pending &lt;x&gt;/);assert.match(html,/Confirm native identity/);
});
