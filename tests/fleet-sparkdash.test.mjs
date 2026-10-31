import assert from 'node:assert/strict';
import test from 'node:test';
import {validSparkdashPayload,freshSparkRead,engineTokenRows,sparkdashPage,sparkHostBrief,historyPath} from '../viewer/fleet-sparkdash.mjs';

const now='2026-10-20T05:30:00Z',ms=Date.parse(now);
const envelope={status:'available',observedAt:now,lastAttemptAt:now,reason:null};
function fixture(){
  const history=Object.fromEntries(['1h','6h','24h','7d','30d'].map(range=>[range,{...envelope,enabled:true,range,stepMs:60000,from:ms-3600000,to:ms,points:[{t:ms-120000,gpuUtil:{avg:50,max:90},cpuUtil:{avg:20,max:30}},{t:ms-60000,memFreeMB:{avg:5000,max:5100,min:4900}}],llm:[{port:8888,points:[{t:ms-60000,genTps:{avg:25,max:30}}]}]}]));
  return {schema:'macfleet.sparkdash.v1',status:'available',observedAt:now,sourceId:'a'.repeat(64),reason:null,
    units:[{...envelope,id:'demo',host:'demo-host',name:'Demo AI',online:true,worker:false,history,endpoints:[{port:8888,available:true,backend:'tensorfold',modelId:'Demo model',generationTpsSource:null,generationTps:25.5,prefillTps:null,cachedPrefillTps:null,uncachedPrefillTps:null,slotsActive:1,slotsTotal:3,requestsRunning:1,requestsWaiting:null,kvCacheUsage:null,decodeActive:true,prefillActive:false}]}],
    totals:Object.fromEntries(['1h','6h','24h'].map((range,index)=>[range,{...envelope,rows:[{unit:'demo',port:8888,model:'Demo model',sourceUpdatedAt:ms,promptTokens:100*(index+1),completionTokens:20*(index+1),cachedTokens:40*(index+1)}]}]))};
}

test('normalized SparkDash schema supports complete, disabled and failed sources',()=>{
  const p=fixture();assert.equal(validSparkdashPayload(p),true);
  assert.equal(validSparkdashPayload({schema:p.schema,status:'not-configured',observedAt:now,sourceId:null,reason:null,units:[],totals:{}}),true);
  p.status='unavailable';p.units[0].status='unavailable';p.units[0].observedAt=null;
  assert.equal(validSparkdashPayload(p),true);
  p.units[0].history['1h']={...envelope,status:'unavailable',observedAt:null};
  assert.equal(validSparkdashPayload(p),true);
  p.units[0].history['1h'].points={malformed:true};assert.equal(validSparkdashPayload(p),false);
});

test('duplicates, bad counters, malformed history and recursive structures are rejected',()=>{
  for(const alter of [p=>p.totals['1h'].rows.push({...p.totals['1h'].rows[0]}),p=>p.totals['6h'].rows[0].promptTokens=-1,p=>p.units[0].history['1h'].points.reverse(),p=>p.units[0].history['1h'].points[0].gpuUtil.max=1,p=>p.units[0].endpoints[0].generationTps=Infinity]){
    const p=fixture();alter(p);assert.equal(validSparkdashPayload(p),false);
  }
});

test('engine rows group only same machine and model, never add cached into prompt',()=>{
  const p=fixture();p.totals['1h'].rows.push({...p.totals['1h'].rows[0],port:8889,promptTokens:200,completionTokens:30,cachedTokens:50});
  const rows=engineTokenRows(p,'1h');assert.equal(rows.length,1);
  assert.equal(rows[0].promptTokens,300);assert.equal(rows[0].completionTokens,50);assert.equal(rows[0].cachedTokens,90);
  p.totals['1h'].rows.push({...p.totals['1h'].rows[0],unit:'other'});
  assert.equal(engineTokenRows(p,'1h').length,2);assert.equal(engineTokenRows(p,'1h','demo').length,1);
  assert.equal(engineTokenRows(p,'24h','demo')[0].completionTokens,60);
  p.totals['1h'].rows[0].cachedTokens=null;assert.equal(engineTokenRows(p,'1h','demo')[0].cachedTokens,null);
});

test('changing token range and machine updates row population without mixing Hermes totals',()=>{
  const p=fixture();
  assert.match(sparkdashPage(p,{view:'tokens',range:'1h'}),/Engine token totals · 1h/);
  assert.match(sparkdashPage(p,{view:'tokens',range:'6h'}),/Engine token totals · 6h/);
  assert.match(sparkdashPage(p,{view:'tokens',range:'24h'}),/Hourly UTC buckets/);
  assert.match(sparkdashPage(p,{view:'tokens'}),/not Hermes client records or cloud billing/);
  assert.match(sparkdashPage(p,{view:'tokens'}),/Cached tokens are part of prompt tokens/);
});

test('stale and failed reports never become a fresh model or a zero queue',()=>{
  const p=fixture();assert.equal(freshSparkRead(p.units[0],false,ms),true);
  assert.equal(freshSparkRead(p.units[0],true,ms),false);
  assert.equal(freshSparkRead(p.units[0],false,ms+601000),false);
  const html=sparkdashPage(p,{failed:true});assert.match(html,/not current readings/);assert.match(html,/Model unverified/);
  assert.match(html,/Unverified<\/dd>/);assert.doesNotMatch(html,/0 \/ 0/);
  assert.match(sparkHostBrief({host:'demo-host'},p,true),/AI report unverified/);
  assert.equal(sparkHostBrief({host:'other'},p),'');
});

test('model labels are escaped and non-SparkDash installations remain independent',()=>{
  const p=fixture();p.units[0].name='<script>bad()</script>';
  const html=sparkdashPage(p);assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
  assert.match(sparkdashPage(null),/Workman Fleet still works independently/);
  p.units[0].history['1h']={...envelope,enabled:false,range:'1h',points:[],llm:[]};
  assert.match(sparkdashPage(p,{view:'history'}),/history is off/);
});

test('fixed percent chart does not rescale old peaks; missing values and time gaps break lines',()=>{
  const rows=[{t:0,gpuUtil:{avg:20,max:25}},{t:60000,gpuUtil:{avg:30,max:35}}];
  const before=historyPath(rows,'gpuUtil','avg',0,120000,60000);
  rows[1].gpuUtil.avg=90;const after=historyPath(rows,'gpuUtil','avg',0,120000,60000);
  assert.equal(before.split('L')[0],after.split('L')[0]);assert.match(before,/M50.00 116.00/);
  assert.equal(historyPath([rows[0],{t:60000}, {...rows[1],t:120000}],'gpuUtil','avg',0,180000,60000).split('M').length,3);
  assert.equal(historyPath([rows[0],{...rows[1],t:180000}],'gpuUtil','avg',0,240000,60000).split('M').length,3);
  const html=sparkdashPage(fixture(),{view:'history'});assert.match(html,/Fixed 0–100% scale/);assert.match(html,/Headroom minimum/);assert.match(html,/B\/s average/);
});
