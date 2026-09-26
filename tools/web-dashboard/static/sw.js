/*
 * Service worker: makes the dashboard installable and lets the shell open offline.
 *
 * The one rule that matters: /api/state and /healthz are never cached and never served
 * from a cache. Those carry the verification verdict and the OFFLINE/STALE marking, and
 * a cached copy would present a stale snapshot as a current one — the precise failure
 * this dashboard exists to prevent. Only the static shell is cached, and if the shell
 * cannot be fetched, the browser's own error is shown rather than a stale reading.
 */
'use strict';

const CACHE = 'begwork-shell-v2';
const SHELL = ['/', '/index.html', '/app.css', '/app.js', '/manifest.webmanifest', '/favicon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  /* Live data bypasses the cache entirely, in both directions. Acceptance scenarios
   * are included: a cached synthetic page reappearing later, without its context,
   * would be exactly the confusion the synthetic banner exists to prevent. */
  if (url.pathname === '/api/state'
      || url.pathname === '/healthz'
      || url.pathname.startsWith('/api/acceptance')) return;

  /* Shell: network first so a redeployed container is picked up on the next load,
   * falling back to the cached copy only when the network genuinely fails. */
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
        }
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || Response.error()))
  );
});
