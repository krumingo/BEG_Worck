/* eslint-disable no-restricted-globals */
// PWA-01 — app-shell service worker (MODERN_FIELD_EXPERIENCE §5/§14, CLAUDE.md §3).
//
// What it does:
//   * precaches ONLY the static build files (html/js/css/fonts/icons) that CRA's
//     InjectManifest step lists in self.__WB_MANIFEST, plus the public icons/manifest;
//   * answers navigations network-first and falls back to the cached index.html, so
//     the shell opens without a connection;
//   * never touches /api/*, /uploads/*, /ws, non-GET requests or other origins: the
//     browser handles those itself, so no money, personal or tenant data, no token
//     and no uploaded file is ever written to Cache Storage by this worker.
// What it does not do (PWA-02): offline write queue, background sync, push.
//
// No workbox runtime is imported: the worker is plain code, so no new dependency.

import { SHELL_PREFIX, isNeverCachedPath } from "./lib/pwa/constants";

const BUILD_SHA = process.env.REACT_APP_BUILD_SHA || "unknown";
const MANIFEST = self.__WB_MANIFEST || [];

// Files in public/ are not webpack assets, so InjectManifest does not list them.
const PUBLIC_SHELL = [
  "/manifest.webmanifest",
  "/icons/icon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-192.png",
  "/icons/icon-maskable-512.png",
  "/icons/apple-touch-icon.png",
  "/icons/favicon-32.png",
];

function hash(text) {
  let h = 5381;
  for (let i = 0; i < text.length; i += 1) h = ((h << 5) + h + text.charCodeAt(i)) >>> 0;
  return h.toString(16);
}

// The cache name carries the build identity (RC-01) and a hash of the precache list,
// so every build gets its own shell cache and the old one is dropped on activate.
const SHELL_CACHE = `${SHELL_PREFIX}${BUILD_SHA.slice(0, 12)}-${hash(JSON.stringify(MANIFEST))}`;
const INDEX_URL = "/index.html";

const SHELL_URLS = Array.from(
  new Set([...MANIFEST.map((e) => (typeof e === "string" ? e : e.url)), ...PUBLIC_SHELL, INDEX_URL]),
).map((u) => new URL(u, self.location.origin).pathname);
const SHELL_PATHS = new Set(SHELL_URLS);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) =>
      Promise.all(
        SHELL_URLS.map((url) =>
          fetch(new Request(url, { cache: "reload", credentials: "same-origin" })).then((res) => {
            if (!res.ok) throw new Error(`precache ${url}: ${res.status}`);
            return cache.put(url, res);
          }),
        ),
      ),
    ),
  );
  // No skipWaiting here: a new version waits until the user presses "Обнови".
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n.startsWith(SHELL_PREFIX) && n !== SHELL_CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  const type = event.data && event.data.type;
  if (type === "SKIP_WAITING") self.skipWaiting();
  if (type === "GET_VERSION" && event.ports && event.ports[0]) {
    event.ports[0].postMessage({ build_sha: BUILD_SHA, cache: SHELL_CACHE });
  }
});

async function navigationResponse(request) {
  try {
    return await fetch(request);
  } catch (err) {
    const cached = await caches.match(INDEX_URL, { cacheName: SHELL_CACHE });
    if (cached) return cached;
    throw err;
  }
}

async function shellResponse(request, pathname) {
  const cached = await caches.match(pathname, { cacheName: SHELL_CACHE });
  return cached || fetch(request);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // other origins: untouched
  if (isNeverCachedPath(url.pathname)) return; // /api, /uploads, /ws: network only, never stored
  if (request.mode === "navigate") {
    event.respondWith(navigationResponse(request));
    return;
  }
  if (SHELL_PATHS.has(url.pathname)) event.respondWith(shellResponse(request, url.pathname));
  // Anything else: no respondWith → plain network, nothing stored.
});
