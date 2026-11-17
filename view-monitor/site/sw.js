/* Big Bowl Studio PWA service worker: app-shell only, NEVER cache view-count JSON. */
const CACHE_NAME = 'bigbowl-live-shell-v1';
const SCOPE = self.registration.scope;
const APP_FILES = ['index.html','manifest.webmanifest','icon-192.png','icon-512.png'].map(f => new URL(f,SCOPE).href);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache=>cache.addAll(APP_FILES)).then(()=>self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(Promise.all([
    caches.keys().then(keys => Promise.all(keys.filter(k=>k.startsWith('bigbowl-live-shell-') && k!==CACHE_NAME).map(k=>caches.delete(k)))),
    self.clients.claim()
  ]));
});
self.addEventListener('fetch', event => {
  if(event.request.method!=='GET') return;
  const url=new URL(event.request.url);
  if(url.origin!==self.location.origin) return;
  // No stale historical data: do not intercept JSON/CSV or GitHub API requests.
  if(/\/data\/|\.json$|\.csv$/i.test(url.pathname)) return;
  if(event.request.mode==='navigate'){
    event.respondWith(fetch(event.request).catch(async()=> (await caches.match(new URL('index.html',SCOPE).href)) || Response.error()));
    return;
  }
  if(/\.(png|webmanifest)$/i.test(url.pathname)){
    event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request)));
  }
});
