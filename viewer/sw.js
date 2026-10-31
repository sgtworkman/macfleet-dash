// App shell only. Never cache telemetry, inventory, incidents, API responses,
// credentials or other JSON. An offline shell cannot establish fleet health.
const CACHE='workman-fleet-shell-0.12.0';
const VERSION='0.12.0';
const MODULES=['fleet-app','fleet-model','fleet-locations','fleet-workspace','fleet-pages','fleet-model-status','fleet-usage','fleet-sparkdash','fleet-read','fleet-operations','fleet-history','fleet-energy','fleet-layout'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(['./','./icon.svg','./manifest.webmanifest','./fleet.css?v='+VERSION,...MODULES.map(m=>'./'+m+'.mjs?v='+VERSION)]))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('workman-fleet-shell-')&&k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||url.pathname.includes('/api/')||url.pathname.endsWith('.json'))return;
  if(!(event.request.mode==='navigate'||/\.(mjs|css|svg|webmanifest)$/.test(url.pathname)))return;
  event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();event.waitUntil(caches.open(CACHE).then(cache=>cache.put(event.request,copy)));}return response;}).catch(async()=>await caches.match(event.request)||(event.request.mode==='navigate'?await caches.match('./'):null)||Response.error()));
});
