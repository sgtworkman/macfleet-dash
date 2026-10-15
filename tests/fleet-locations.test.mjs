import test from 'node:test';
import assert from 'node:assert/strict';
import {checkedLocations,locationName,applyLocations,editedLocations,exportLocations} from '../viewer/fleet-locations.mjs';
import {combineFleet,filterFleet,fleetSummary} from '../viewer/fleet-model.mjs';

const document = locations => ({schema:'macfleet.locations.v1',locations});
test('locations are user-defined, trimmed, bounded and explicit when unknown',()=>{
  assert.deepEqual(checkedLocations(document({desktop:' Home office ',laptop:''})),{desktop:'Home office',laptop:'Unassigned'});
  for(const label of [null,7,'x'.repeat(81),'A\nB','A\u202eB','all'])assert.throws(()=>locationName(label));
  for(const value of [null,[],{schema:'wrong',locations:{}},document([]),document({'../bad':'Home'}),{...document({desktop:'Home'}),enrollment:'enrolled'}])assert.throws(()=>checkedLocations(value));
});
test('browser labels cannot change health, identities, enrollment, timestamps or totals',()=>{
  const row={host:'desktop',site:'Office',enrollment:'not-enrolled',status:'not-enrolled',observedAt:null,cpuUsedPct:null};
  const data={hosts:[row],history:{hosts:{desktop:[]}}},result=applyLocations(data,{desktop:'Home'});
  assert.deepEqual(result.hosts[0],{...row,site:'Home'});assert.equal(row.site,'Office');
  assert.deepEqual(fleetSummary(result.hosts),fleetSummary(data.hosts));assert.equal(result.history,data.history);
  assert.throws(()=>applyLocations(data,{desktop:{enrollment:'enrolled'}}));
});
test('editing reverts to shared defaults without pinning unchanged rows',()=>{
  const base=[{host:'desktop',site:'Home'},{host:'server',site:'Office'}];
  assert.deepEqual(editedLocations(base,{desktop:'Other',removed:'Archive'},{desktop:'Home',server:'Lab'}),{server:'Lab',removed:'Archive'});
  assert.throws(()=>editedLocations(base,{}, {missing:'Home'}));
  assert.deepEqual(exportLocations(base,{server:'Lab'}),document({desktop:'Home',server:'Lab'}));
});
test('shared registry locations apply uniformly to Mac, Windows and pending hosts',()=>{
  const base={app:'macfleet-dash',schema:1,hosts:[{host:'desktop',site:'Old',os:'macOS'}]};
  const win={schema:'macfleet.windows.v1',hosts:[{host:'server',platform:'windows',site:'Old',enrollment:'enrolled',status:'available'}]};
  const registry={schema:'macfleet.registry.v1',hosts:{desktop:{site:'Home'},server:{site:'Home'},pending:{site:'Home'}},pendingHosts:[{host:'pending',kind:'server',platform:'linux',site:'Old',pendingReason:'Not connected'}]};
  const data=combineFleet(base,win,registry);
  assert.equal(filterFleet(data.hosts,'all','Home').length,3);
  assert.equal(fleetSummary(data.hosts).monitored,2);assert.equal(fleetSummary(data.hosts).pending,1);
  assert.deepEqual(data.hosts.map(r=>r.site),['Home','Home','Home']);
});
test('a source location is retained when no shared location is configured',()=>{
  const base={app:'macfleet-dash',schema:1,hosts:[{host:'desktop',site:'Office',os:'macOS'}]};
  assert.equal(combineFleet(base).hosts[0].site,'Office');
});
