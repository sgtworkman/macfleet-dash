import test from 'node:test';
import assert from 'node:assert/strict';
import {validModelPayload,withModels,currentModel,modelBrief,modelPanel} from '../viewer/fleet-model-status.mjs';
import {combineFleet,fleetSummary} from '../viewer/fleet-model.mjs';

const now=Date.parse('2026-10-16T04:30:00Z'),at=new Date(now).toISOString();
const base={app:'macfleet-dash',schema:1,observedAt:at,hosts:[{host:'demo',name:'Demo computer',role:'Old saved model label',status:'available',observedAt:at,os:'macOS',ramGb:16,memUsedGb:8}]};
const model={host:'demo',status:'available',observedAt:at,modelId:'demo-vlm',models:['demo-vlm'],artifact:'demo-vlm-Q4_K_M.gguf',engine:'llama.cpp',quantization:'Q4_K - Medium',contextTokens:16384,parameterCount:35000000000,source:'GET /v1/models + /props',reason:null};
const payload={schema:'macfleet.models.v1',observedAt:at,hosts:[model]};
const row=(snapshot=payload,failed=false)=>withModels(base,snapshot,failed).hosts[0];

test('fresh current model comes from exact endpoint metadata, not the role or benchmark',()=>{
  assert.ok(validModelPayload(payload));
  assert.equal(currentModel(row(),now).label,'demo-vlm');
  assert.equal(currentModel(row(),now).current,true);
  const html=modelPanel(row(),now);
  for(const label of ['Current model','demo-vlm','demo-vlm-Q4_K_M.gguf','16,384 tokens','Q4_K - Medium','Model checked'])assert.ok(html.includes(label),label);
  assert.doesNotMatch(html,/Old saved model label/);
  assert.match(html,/Metadata only/);
});
test('model identity changes update without pinning the previous model',()=>{
  const newer={...payload,hosts:[{...model,modelId:'new-model',models:['new-model'],artifact:'new-model.gguf'}]};
  assert.equal(currentModel(row(newer),now).label,'new-model');
  assert.doesNotMatch(modelBrief(row(newer),now),/demo-vlm/);
});
test('stale, future and failed model reads never render retained names as current',()=>{
  for(const [value,clock] of [[row(),now+600001],[row({...payload,observedAt:new Date(now+120000).toISOString()}),now],[row(payload,true),now]]){
    assert.equal(currentModel(value,clock).current,false);
    assert.match(modelPanel(value,clock),/Unverified/);
    assert.doesNotMatch(modelBrief(value,clock),/<strong[^>]*>demo-vlm<\/strong>/);
  }
  assert.match(modelPanel(row(),now+600001),/Last reported model/);
});
test('missing, failed, catalog-only and multiple rows are not a selected active model',()=>{
  assert.equal(currentModel(base.hosts[0],now).configured,false);
  assert.equal(modelBrief(base.hosts[0],now),'');
  for(const [status,names] of [['unavailable',[]],['catalog',['catalog-one']],['multiple',['one','two']]]){
    const candidate={...model,status,modelId:null,models:names,artifact:null,engine:null,quantization:null,contextTokens:null,parameterCount:null,reason:'Not verified'};
    const value={...payload,hosts:[candidate]};
    assert.ok(validModelPayload(value));assert.equal(currentModel(row(value),now).current,false);
    assert.match(modelPanel(row(value),now),/Unverified/);
  }
});
test('model source cannot change host health, counts, resource values or add computers',()=>{
  const before=structuredClone(base);
  const combined=withModels(base,{...payload,hosts:[model,{...model,host:'not-registered'}]});
  assert.equal(combined.hosts.length,1);
  assert.deepEqual(fleetSummary(combined.hosts,now),fleetSummary(base.hosts,now));
  assert.deepEqual(base,before);
  for(const field of ['host','status','observedAt','ramGb','memUsedGb','role'])assert.equal(combined.hosts[0][field],base.hosts[0][field]);
  const failed={...base.hosts[0],status:'unavailable'};
  assert.equal(withModels({...base,hosts:[failed]},payload).hosts[0].status,'unavailable');
});
test('invalid model schemas, duplicate identities and fabricated missing numbers are rejected',()=>{
  for(const value of [null,{}, {...payload,hosts:[model,model]}, {...payload,hosts:[{...model,contextTokens:true}]}, {...payload,hosts:[{...model,modelId:'wrong'}]}, {...payload,hosts:[{...model,artifact:'/private\npath'}]}, {...payload,hosts:[{...model,host:123}]}])assert.equal(validModelPayload(value),false);
});
test('model and artifact labels are escaped and absent metadata stays unknown',()=>{
  const value=row({...payload,hosts:[{...model,modelId:'<script>x</script>',models:['<script>x</script>'],artifact:'<img src=x>',contextTokens:null,parameterCount:null}]});
  const html=modelPanel(value,now);
  assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('&lt;img'));assert.doesNotMatch(html,/<script>|<img/);
  assert.match(html,/Not reported/);assert.doesNotMatch(html,/0 tokens/);
});
test('saved role corrections do not pretend to detect or change a model',()=>{
  const data=combineFleet(base,null,{schema:'macfleet.registry.v1',hosts:{demo:{role:'Local AI · vision and text'}}});
  assert.equal(data.hosts[0].role,'Local AI · vision and text');
  assert.equal(currentModel(data.hosts[0],now).configured,false);
  assert.deepEqual(fleetSummary(data.hosts,now),fleetSummary(base.hosts,now));
});
