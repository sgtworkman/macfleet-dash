import assert from 'node:assert/strict';
import test from 'node:test';
import {readSources} from '../viewer/fleet-read.mjs';

test('seven snapshot reads never exceed three active connections and retain source order',async()=>{
  let active=0,peak=0;
  const read=async value=>{active++;peak=Math.max(peak,active);await new Promise(resolve=>setTimeout(resolve,2));active--;return value;};
  const result=await readSources([1,2,3,4,5,6,7],read);
  assert.equal(peak,3);assert.deepEqual(result.map(r=>r.value),[1,2,3,4,5,6,7]);
});
test('failed and synchronous source errors remain failures while independent reads continue',async()=>{
  const result=await readSources(['good','reset','model','other'],value=>{if(value==='reset')throw Error('connection reset');return value;});
  assert.deepEqual(result.map(row=>row.status),['fulfilled','rejected','fulfilled','fulfilled']);
  assert.equal(result[1].reason.message,'connection reset');assert.equal(result[3].value,'other');
  await assert.rejects(readSources([],()=>null,0),RangeError);
});
