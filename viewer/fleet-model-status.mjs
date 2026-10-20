import {ageMs,escapeHtml as esc,format,lastUpdateAge} from './fleet-model.mjs?v=0.10.0';

const object=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
const text=(value,max=200)=>typeof value==='string'&&value.trim().length>0&&value.length<=max&&!/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(value);
const integer=value=>value===null||Number.isSafeInteger(value)&&value>0&&value<=1e13;
const nullable=(value,max=200)=>value===null||text(value,max);
const when=at=>ageMs(at)===null?'Time unavailable':new Date(at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});

export function validModelPayload(value){
  return object(value)&&value.schema==='macfleet.models.v1'&&typeof value.observedAt==='string'&&Number.isFinite(Date.parse(value.observedAt))&&Array.isArray(value.hosts)&&value.hosts.length<=8&&
    new Set(value.hosts.map(row=>row?.host)).size===value.hosts.length&&value.hosts.every(row=>object(row)&&typeof row.host==='string'&&/^[a-z0-9][a-z0-9.-]{0,62}$/.test(row.host)&&['available','unavailable','multiple','catalog'].includes(row.status)&&typeof row.observedAt==='string'&&Number.isFinite(Date.parse(row.observedAt))&&Array.isArray(row.models)&&row.models.length<=32&&row.models.every(id=>text(id))&&new Set(row.models).size===row.models.length&&nullable(row.modelId)&&nullable(row.artifact)&&nullable(row.engine,80)&&nullable(row.quantization,80)&&integer(row.contextTokens)&&integer(row.parameterCount)&&text(row.source,80)&&nullable(row.reason)&&
      (row.status==='available'?row.engine==='llama.cpp'&&row.models.length===1&&row.modelId===row.models[0]&&row.reason===null:row.modelId===null&&row.artifact===null&&row.engine===null&&row.quantization===null&&row.contextTokens===null&&row.parameterCount===null&&text(row.reason)&& (row.status==='multiple'?row.models.length>1:row.status==='catalog'?row.models.length===1:row.models.length===0)));
}

export function withModels(data,models,readFailed=false){
  if(!data)return data;
  const rows=new Map(validModelPayload(models)?models.hosts.map(row=>[row.host,row]):[]);
  return {...data,hosts:data.hosts.map(row=>({...row,currentModel:rows.has(row.host)?{...rows.get(row.host),snapshotAt:models.observedAt,readFailed}:null}))};
}

export function currentModel(row,now=Date.now()){
  const model=row?.currentModel;
  if(!model)return {configured:false,current:false,label:'Not configured',tone:'muted',message:'No verified current-model snapshot is available.'};
  const age=ageMs(model.observedAt,now),snapshotAge=ageMs(model.snapshotAt,now);
  if(model.readFailed)return {configured:true,current:false,label:'Unverified',tone:'warn',message:'Latest model snapshot could not be read. Retained identity is not current.'};
  if(age===null||snapshotAge===null)return {configured:true,current:false,label:'Time unverified',tone:'warn',message:'Model-check time is invalid or in the future.'};
  if(age>600000||snapshotAge>600000)return {configured:true,current:false,label:'Model check stale',tone:'warn',message:'No fresh model check within 10 minutes. Retained identity is not current.'};
  if(model.status!=='available')return {configured:true,current:false,label:model.status==='unavailable'?'Unavailable':model.status==='multiple'?'Multiple reported':'Catalog only',tone:'warn',message:model.reason};
  return {configured:true,current:true,label:model.modelId,tone:'good',message:'Reported by the configured llama.cpp endpoint; not inferred from the computer role.'};
}

export function modelBrief(row,now=Date.now()){
  const state=currentModel(row,now),model=row?.currentModel;
  if(!state.configured)return '';
  return `<div class="current-model-brief"><small>Current model</small><strong class="${state.tone}">${esc(state.current?model.modelId:state.label)}</strong><small>${state.current?'Checked '+esc(lastUpdateAge({observedAt:model.observedAt},now)):esc(state.message)}</small></div>`;
}

export function modelPanel(row,now=Date.now()){
  const state=currentModel(row,now),model=row?.currentModel;
  if(!state.configured)return '';
  const facts=items=>`<dl class="facts">${items.map(([label,value])=>`<dt>${esc(label)}</dt><dd>${esc(value??'Not reported')}</dd>`).join('')}</dl>`;
  const retained=!state.current&&model.status==='available';
  return `<section class="panel current-model-panel" aria-label="Current model"><div class="section-head"><h2>Current model</h2><span class="status ${state.tone}">${esc(state.current?'Fresh endpoint report':state.label)}</span></div><p class="current-model-name">${esc(state.current?model.modelId:'Unverified')}</p><p class="muted">${esc(state.message)}</p>
    ${state.current?facts([['Model artifact',model.artifact],['Quantization',model.quantization],['Context per slot',model.contextTokens===null?'Not reported':format(model.contextTokens,0)+' tokens'],['Model parameters',model.parameterCount===null?'Not reported':format(model.parameterCount/1e9,2)+' billion'],['Serving engine',model.engine],['Model checked',when(model.observedAt)],['Evidence',model.source]]):facts([['Latest model check',when(model.observedAt)],['Last reported model',retained?model.modelId:'Not retained'],...(model.models.length&&model.status!=='available'?[['Endpoint catalog',model.models.join(', ')]]:[])])}
    <p class="model-note">Metadata only—no prompts, model loads or restarts. Model identity does not establish throughput, token usage, successful requests or computer health. Role labels are saved descriptions, not live model detection.</p></section>`;
}
