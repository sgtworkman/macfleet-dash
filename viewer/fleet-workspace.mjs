// Personal workspace state. Never publish this browser's activity with source.
import {freshness,hostAlerts} from './fleet-model.mjs?v=0.11.0';
import {locationName,locationsDocument} from './fleet-locations.mjs?v=0.11.0';

export const ACTIVITY_STORAGE_KEY='macfleet-activity-v1';
export const MAX_ACTIVITY=200;
const hostId=/^[a-z0-9][a-z0-9.-]{0,62}$/;
const object=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
const text=value=>typeof value==='string'&&[...value].length<=600&&!/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(value);
const timestamp=value=>typeof value==='string'&&Number.isFinite(Date.parse(value));
const states=['not-enrolled','pilot','client-unavailable','unavailable','unverified','stale','current'];
export const emptyActivity=()=>({schema:'macfleet.activity.v1',startedAt:null,baseline:{},events:[]});
export function checkedActivity(value){
  if(!object(value)||value.schema!=='macfleet.activity.v1'||Object.keys(value).some(k=>!['schema','startedAt','baseline','events'].includes(k))||value.startedAt!==null&&!timestamp(value.startedAt)||!object(value.baseline)||Object.keys(value.baseline).length>512||!Array.isArray(value.events)||value.events.length>MAX_ACTIVITY)throw Error('Saved activity format is invalid.');
  for(const [id,row] of Object.entries(value.baseline)){
    if(!hostId.test(id)||!object(row)||Object.keys(row).some(k=>!['state','site','alerts'].includes(k))||!states.includes(row.state)||!text(row.site)||!object(row.alerts)||Object.keys(row.alerts).length>64||Object.entries(row.alerts).some(([key,label])=>!text(key)||!text(label)))throw Error('Saved activity baseline is invalid.');
  }
  for(const event of value.events)if(!object(event)||Object.keys(event).some(k=>!['at','host','kind','text'].includes(k))||!timestamp(event.at)||!hostId.test(event.host)||!['connection','alert','location'].includes(event.kind)||!text(event.text))throw Error('Saved activity event is invalid.');
  return JSON.parse(JSON.stringify(value));
}
function alertKey(label){
  if(label.startsWith('Low storage '))return 'storage:'+label.split(' ')[2];
  for(const [prefix,key] of [['Low storage:','storage'],['Windows clock','clock'],['High swap:','swap'],['Memory nearly full:','memory'],['High reported memory use:','memory'],['Some Windows readings','partial'],['Windows answered','resources']])if(label.startsWith(prefix))return key;
  return label;
}
export function observeActivity(saved,hosts,now=Date.now()){
  const result=checkedActivity(saved);
  if(!Array.isArray(hosts)||hosts.length>512||hosts.some(r=>!hostId.test(r?.host)))throw Error('Activity computer identities are invalid.');
  const at=new Date(now).toISOString(),baseline={};
  const append=(host,kind,label)=>result.events.push({at,host,kind,text:label});
  for(const row of hosts){
    const current=freshness(row,now),old=result.baseline[row.host],site=locationName(row.site||'');
    const alerts=current.state==='current'?Object.fromEntries(hostAlerts(row,now).map(a=>[alertKey(a.text),a.text])):{};
    baseline[row.host]={state:current.state,site,alerts};
    // The first snapshot is a baseline, not invented historical activity.
    if(!result.startedAt)continue;
    if(!old){append(row.host,'connection','Inventory entry first observed in this browser · '+current.label+'.');continue;}
    if(old.state!==current.state)append(row.host,'connection','Reading status: '+current.label+'. This describes monitoring, not proof of power state.');
    if(old.site!==site)append(row.host,'location','Location changed from '+old.site+' to '+site+'.');
    for(const [key,label] of Object.entries(alerts))if(!Object.hasOwn(old.alerts,key))append(row.host,'alert','Alert observed: '+label);
    if(current.state==='current'&&old.state==='current')for(const [key,label] of Object.entries(old.alerts))if(!Object.hasOwn(alerts,key))append(row.host,'alert','Alert no longer present in current readings: '+label);
  }
  result.startedAt=result.startedAt||at;result.baseline=baseline;result.events=result.events.slice(-MAX_ACTIVITY);
  return checkedActivity(result);
}
export function stageBulkLocations(hosts,edits,selected,label){
  const allowed=new Set(hosts.map(r=>r.host)),ids=[...new Set(selected)],location=locationName(label);
  if(!ids.length)throw Error('Select at least one computer.');
  if(ids.some(id=>!allowed.has(id)))throw Error('A selected computer changed. Refresh before assigning.');
  return locationsDocument({...locationsDocument(edits).locations,...Object.fromEntries(ids.map(id=>[id,location]))}).locations;
}
export const starterConfig=()=>({interval:300,hosts:{'this-computer':{method:'local',name:'This computer',role:'My computer'}}});

// Generic application notes only: no operator inventory, IPs or private events.
export const APP_CHANGES=[
  {version:'0.11.0',at:'2026-10-31T02:42:31.771631Z',by:'Codex',label:'Source prepared',items:['Rename the dashboard to Workman Fleet for Mac, Linux, Windows, server and range-computer monitoring.','Preserve existing collector configuration, native sender identifiers and private snapshots during the rename.']},
  {version:'0.10.0',at:'2026-10-20T05:28:51Z',by:'Codex',label:'Source prepared',items:['Optional read-only SparkDash AI reports: reported model, speed, queues and slot capacity.','Separate 1h, 6h and 24h engine token windows by machine/model, with partial-hour boundaries disclosed.','Resource and AI history with fixed-scale CPU/GPU charts, source gaps and inspectable headroom/network/rates.','Includes the prepared coverage, saved-profile and configuration-refresh improvements from 0.9.5. No SparkDash settings or AI services changed.']},
  {version:'0.9.5',at:'2026-10-20T04:28:15Z',by:'Codex',label:'Source prepared',items:['Coverage and repairs: missing readings, pending identities and current resource/clock warnings.','Computer and saved-profile selectors for private aggregate Hermes counters; separate histories and explicit missing coverage.','Collector v0.6.1 reads saved configuration during its existing refresh cycle; requires one collector reload to adopt.','Reported memory use stays distinct from actual memory pressure.']},
  {version:'0.9.4',at:'2026-10-16T04:34:55Z',by:'Codex',label:'GitHub release published',items:['Current model on computer cards and in details, separate from saved roles and benchmark history.','Read-only private llama.cpp identity, artifact, quantization and per-slot context checks through the existing snapshot refresh.','Unavailable, stale, catalog-only and multiple-model results remain explicitly unverified.']},
  {version:'0.9.3',at:'2026-10-16T03:36:34Z',by:'Codex',label:'GitHub release published',items:['First-computer setup and snapshot connection check.','Direct location editing, bulk drafts and clearer save scope.','Private browser activity and timestamped application change notes.','Separate failed-check times from successful readings.','Public archive privacy checks and fresh-install regression coverage.']},
  {version:'0.9.2',at:'2026-10-15T04:51:17Z',by:'Codex',label:'GitHub release published',items:['Self-service locations with browser-only saves and shared configuration export.']}
];
