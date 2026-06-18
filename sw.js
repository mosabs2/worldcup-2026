// World Cup 2026 — service worker.
// Network-first so the app is always fresh when online (no stale home-screen
// clips), with a cache fallback so it still opens offline. Bump VERSION only
// to force a hard cache purge; day-to-day content freshness needs no bump,
// because every navigation goes to the network first.
const VERSION = 'v4';
const CACHE = 'wc26-' + VERSION;
const OFFLINE_URLS = ['./', './index.html', './manifest.json'];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(OFFLINE_URLS)).catch(() => {}));
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k.startsWith('wc26-') && k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  // Only manage same-origin GETs; let the ESPN feed, fonts, etc. pass straight through.
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  // version.json is the deploy marker the page polls to self-update — never cache it,
  // or an offline resume could read a stale builtAt and skip a needed reload.
  const noCache = url.pathname.endsWith('/version.json');
  e.respondWith((async () => {
    try {
      const fresh = await fetch(req);
      if (fresh && fresh.ok && !noCache) {
        const c = await caches.open(CACHE);
        c.put(req, fresh.clone());
      }
      return fresh;
    } catch (err) {
      const cached = await caches.match(req);
      if (cached) return cached;
      // navigation offline fallback -> last good app shell
      if (req.mode === 'navigate') {
        const shell = await caches.match('./index.html') || await caches.match('./');
        if (shell) return shell;
      }
      throw err;
    }
  })());
});
