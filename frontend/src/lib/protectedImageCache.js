/*
 * W0-06B/C03 — the protected-image cache, bound to ONE session principal.
 *
 * Why this exists. GET /api/media/avatar/{filename} answers only to a signed-in
 * user of the photo's own tenant (FLOW-002). The browser therefore loads those
 * images with the session's Bearer token and shows them through object URLs.
 * The C02 cache kept those object URLs in a map keyed by PATH ONLY: after a
 * logout and a login as another account / tenant in the same tab, the same
 * path returned the previous principal's image without asking the server
 * (Codex C02 review). Its 5-minute lifetime was also only checked lazily, so
 * a stale object URL stayed valid indefinitely.
 *
 * The rules this module enforces:
 *
 *  1. Every entry belongs to the principal (the session token) that fetched
 *     it. The cache holds entries of at most ONE principal: when `load` sees a
 *     different principal than the cache owner, it clears and revokes
 *     everything first. There is no lookup path that can return another
 *     principal's object URL.
 *  2. No principal (logged out) → nothing is fetched, and everything is
 *     cleared and revoked.
 *  3. A response that arrives after the principal changed (a request started
 *     under A, finished after a switch to B) is discarded. It never becomes an
 *     object URL and never reaches the caller.
 *  4. Lifetime is enforced by a TIMER. Each entry is revoked and dropped
 *     `ttlMs` after it was created, whether or not anyone reads it again. Reads
 *     also reject an expired entry.
 *  5. `clear()` (logout, login, session change) revokes every object URL and
 *     notifies subscribers, so a still-mounted image stops showing old bytes
 *     and reloads under the new principal.
 *
 * Pure: no React, no axios, no browser globals. Everything environmental is
 * injected, so the rules above are tested deterministically in Node
 * (frontend/tests/protected_image_cache.test.mjs).
 */

export const DEFAULT_TTL_MS = 5 * 60 * 1000;

export class ProtectedImageError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

export function createProtectedImageCache({
  fetchBlob,              // (path, principal) => Promise<Blob>
  getPrincipal,           // () => string | null   (the current session token)
  createObjectURL,        // (blob) => string
  revokeObjectURL,        // (url) => void
  ttlMs = DEFAULT_TTL_MS,
  now = () => Date.now(),
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = (handle) => clearTimeout(handle),
}) {
  const entries = new Map(); // path -> { principal, promise, url, expires, timer }
  const listeners = new Set();
  let owner = null;          // the ONE principal whose entries the map holds
  let generation = 0;        // bumps on every clear; stale responses carry an old value

  function notify(event) {
    for (const fn of Array.from(listeners)) {
      try { fn(event); } catch (e) { /* a listener never breaks the cache */ }
    }
  }

  function drop(path, expected) {
    const entry = entries.get(path);
    if (!entry || (expected && entry !== expected)) return false;
    entries.delete(path);
    clearTimer(entry.timer);
    if (entry.url) revokeObjectURL(entry.url);
    return true;
  }

  function clear() {
    for (const path of Array.from(entries.keys())) drop(path);
    owner = null;
    generation += 1;
    notify({ type: "cleared" });
  }

  function expire(path, entry) {
    // Rule 4: the timer, not a later read, ends an entry's life. A mounted
    // image is told so it can fetch again under the CURRENT session.
    if (drop(path, entry)) notify({ type: "expired", path });
  }

  function load(path) {
    const principal = getPrincipal();
    if (!principal) {
      if (owner !== null || entries.size) clear();
      return Promise.reject(new ProtectedImageError("NO_SESSION"));
    }
    if (owner !== principal) {
      if (owner !== null || entries.size) clear();
      owner = principal;
    }
    const hit = entries.get(path);
    if (hit && hit.principal === principal && hit.expires > now()) return hit.promise;
    if (hit) drop(path, hit);

    const gen = generation;
    const entry = { principal, url: null, expires: now() + ttlMs, timer: null, promise: null };
    entry.promise = Promise.resolve()
      .then(() => fetchBlob(path, principal))
      .then((blob) => {
        // Rule 3: the session moved on while we were waiting — discard.
        if (gen !== generation || owner !== principal || getPrincipal() !== principal
            || entries.get(path) !== entry) {
          throw new ProtectedImageError("SESSION_CHANGED");
        }
        entry.url = createObjectURL(blob);
        return entry.url;
      });
    entry.timer = setTimer(() => expire(path, entry), ttlMs);
    entries.set(path, entry);
    entry.promise.catch(() => drop(path, entry));
    return entry.promise;
  }

  /** fn({type: "cleared"} | {type: "expired", path}) */
  function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  return {
    load,
    clear,
    subscribe,
    size: () => entries.size,
    owner: () => owner,
  };
}
