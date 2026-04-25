/* guru-review service worker (todo:dbefad31).
 * App-shell only — no API caching. The data is what the server has, period. */
const SHELL_CACHE = 'guru-review-shell-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API requests: never cache. Always go to network. Let the app's retry
  // logic handle offline.
  if (url.pathname.startsWith('/api/')) return;

  // Navigation: try network, fall back to cached shell so the app loads
  // on flaky connections.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/index.html')),
    );
    return;
  }

  // Static assets (JS/CSS/manifest/icons): network-first with cache fallback.
  // Vite emits hashed filenames so stale-while-revalidate isn't needed.
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(SHELL_CACHE).then((c) => c.put(event.request, copy));
        return res;
      })
      .catch(() => caches.match(event.request)),
  );
});
