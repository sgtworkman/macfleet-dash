import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import test from 'node:test';
import {VIEWER_VERSION} from '../viewer/fleet-model.mjs';
const read=path=>readFileSync(new URL('../'+path,import.meta.url),'utf8');

test('viewer version, static assets, changelog and guide link share a release identity',()=>{
  const html=read('viewer/index.html'),notes=read('CHANGELOG.md'),app=read('viewer/fleet-app.mjs');
  assert.match(VIEWER_VERSION,/^\d+\.\d+\.\d+$/);
  assert.equal(html.match(/name="macfleet-viewer-version" content="([^"]+)"/)?.[1],VIEWER_VERSION);
  assert.equal(notes.match(/^## \[([^\]]+)\]/m)?.[1],VIEWER_VERSION);
  assert.ok(html.includes('fleet.css?v='+VIEWER_VERSION));
  assert.ok(html.includes('fleet-app.mjs?v='+VIEWER_VERSION));
  assert.ok(read('README.md').includes('Viewer release v'+VIEWER_VERSION));
  assert.ok(app.includes('blob/v${VIEWER_VERSION}/windows/README.md'));
});

test('public source excludes runtime records and operator-specific pilot inventory',()=>{
  const ignored=read('.gitignore').split(/\r?\n/);
  for(const path of ['state/','viewer/data.json','viewer/token-usage.json','viewer/windows.json','viewer/fleet-registry.json','windows-fleet.json','macfleet.toml','macfleet.json']) assert.ok(ignored.includes(path),path);
  for(const path of ['viewer/fleet-app.mjs','windows/README.md']){
    const text=read(path);
    assert.doesNotMatch(text,/\/Users\/|RANGE42S1|WFTRAININGSERVE|WFTrainingServer/);
  }
  assert.ok(read('windows/README.md').includes('not installed'));
});

// Source archives do not contain Git metadata; the publish gate separately
// checks their file inventory. Never treat an absent Git index as proof.
test('Git checkout does not track private runtime records',{skip:!existsSync(new URL('../.git',import.meta.url))},()=>{
  const tracked=execFileSync('git',['ls-files'],{cwd:new URL('..',import.meta.url),encoding:'utf8'}).trim().split('\n');
  assert.deepEqual(tracked.filter(path=>/^state\/|^viewer\/(?:data|token-usage|windows|fleet-registry)\.json$|^windows-fleet\.json$|^macfleet\.(?:toml|json)$/.test(path)),[]);
});
