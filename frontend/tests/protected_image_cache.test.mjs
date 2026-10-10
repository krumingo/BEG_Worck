/*
 * W0-06B/C03 — deterministic regressions for the protected avatar cache.
 *
 *   node --test frontend/tests/
 *
 * Zero dependencies: node's built-in test runner, the pure cache module
 * (frontend/src/lib/protectedImageCache.js) with an injected fake fetch,
 * fake session token, fake clock/timers and recorded object-URL create/revoke.
 * The wiring of AuthImage / AuthContext is asserted from their source, since
 * React and the CRA toolchain are not part of this zero-dependency run.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import {
  createProtectedImageCache,
  DEFAULT_TTL_MS,
  ProtectedImageError,
} from "../src/lib/protectedImageCache.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");
const PATH = "/media/avatar/same-name.png"; // identical path in both tenants

function harness({ ttlMs = DEFAULT_TTL_MS, deferred = false } = {}) {
  const env = {
    token: "token-tenant-A-user-1",
    clock: 0,
    timers: [],
    fetches: [],
    created: [],
    revoked: [],
    events: [],
    pending: [],
  };
  const cache = createProtectedImageCache({
    getPrincipal: () => env.token,
    fetchBlob: (path, principal) => {
      env.fetches.push({ path, principal });
      const blob = { bytes: "image-of:" + principal + ":" + path };
      if (!deferred) return Promise.resolve(blob);
      return new Promise((resolve) => env.pending.push(() => resolve(blob)));
    },
    createObjectURL: (blob) => {
      const url = "blob:" + blob.bytes + "#" + env.created.length;
      env.created.push(url);
      return url;
    },
    revokeObjectURL: (url) => env.revoked.push(url),
    ttlMs,
    now: () => env.clock,
    setTimer: (fn, ms) => {
      const t = { fn, at: env.clock + ms, done: false };
      env.timers.push(t);
      return t;
    },
    clearTimer: (t) => { if (t) t.done = true; },
  });
  cache.subscribe((e) => env.events.push(e));
  env.advance = (ms) => {
    env.clock += ms;
    for (const t of env.timers) {
      if (!t.done && t.at <= env.clock) { t.done = true; t.fn(); }
    }
  };
  return { cache, env };
}

const settle = () => new Promise((r) => setImmediate(r));

// ═══════════════════════ the C02 defect: same tab, other tenant, same path
test("tenant switch in the same tab never returns the previous tenant's image", async () => {
  const { cache, env } = harness();
  const a = await cache.load(PATH);
  assert.match(a, /tenant-A/);

  env.token = "token-tenant-B-user-9";        // logout A + login B, no page reload
  const b = await cache.load(PATH);

  assert.match(b, /tenant-B/);
  assert.notEqual(b, a);
  assert.equal(env.fetches.length, 2, "B must be asked of the server, not served from A's cache");
  assert.deepEqual(env.fetches.map((f) => f.principal),
                   ["token-tenant-A-user-1", "token-tenant-B-user-9"]);
  assert.ok(env.revoked.includes(a), "A's object URL is revoked at the switch");
  assert.equal(cache.size(), 1);
  assert.equal(cache.owner(), "token-tenant-B-user-9");
});

test("another account of the SAME tenant is a different principal too", async () => {
  const { cache, env } = harness();
  const first = await cache.load(PATH);
  env.token = "token-tenant-A-user-2";
  const second = await cache.load(PATH);
  assert.notEqual(second, first);
  assert.equal(env.fetches.length, 2);
  assert.ok(env.revoked.includes(first));
});

test("the C02 path-only cache reproduces the defect (evidence for the fix)", async () => {
  // The C02 lookup, reduced to its essence: key = path, no principal.
  const map = new Map();
  let token = "A";
  let fetches = 0;
  const c02load = (path) => {
    if (map.has(path)) return map.get(path);
    fetches += 1;
    const p = Promise.resolve("blob:" + token);
    map.set(path, p);
    return p;
  };
  const a = await c02load(PATH);
  token = "B";
  const b = await c02load(PATH);
  assert.equal(b, a, "C02 returned A's blob to B");
  assert.equal(fetches, 1);
});

// ═══════════════════════════════════════════════════════════════ logout
test("logout (no token) fetches nothing and revokes everything", async () => {
  const { cache, env } = harness();
  const a = await cache.load(PATH);
  env.token = null;
  await assert.rejects(cache.load(PATH), (e) => e instanceof ProtectedImageError
                                                && e.code === "NO_SESSION");
  assert.equal(env.fetches.length, 1);
  assert.ok(env.revoked.includes(a));
  assert.equal(cache.size(), 0);
  assert.equal(cache.owner(), null);
});

test("explicit clear (login/logout hook) revokes every URL and notifies", async () => {
  const { cache, env } = harness();
  const a = await cache.load(PATH);
  const b = await cache.load("/media/avatar/other.png");
  cache.clear();
  assert.deepEqual([...env.revoked].sort(), [a, b].sort());
  assert.equal(cache.size(), 0);
  assert.deepEqual(env.events.at(-1), { type: "cleared" });
  // a later load under the same token fetches again — nothing survived
  await cache.load(PATH);
  assert.equal(env.fetches.length, 3);
});

// ═══════════════════════════════════════════════════════════════ expiry
test("an entry is revoked by its timer without any further read", async () => {
  const { cache, env } = harness({ ttlMs: 1000 });
  const a = await cache.load(PATH);
  env.advance(999);
  assert.equal(env.revoked.length, 0);
  env.advance(1);
  assert.deepEqual(env.revoked, [a], "revoked at the deadline by the timer");
  assert.equal(cache.size(), 0);
  assert.deepEqual(env.events.at(-1), { type: "expired", path: PATH });
  const again = await cache.load(PATH);
  assert.notEqual(again, a);
  assert.equal(env.fetches.length, 2);
});

test("a read after the deadline never returns the stale entry", async () => {
  const { cache, env } = harness({ ttlMs: 1000 });
  const a = await cache.load(PATH);
  env.clock += 5000;              // clock moved, timer not yet run
  const again = await cache.load(PATH);
  assert.notEqual(again, a);
  assert.ok(env.revoked.includes(a));
  assert.equal(env.fetches.length, 2);
});

test("the default lifetime is five minutes", () => {
  assert.equal(DEFAULT_TTL_MS, 5 * 60 * 1000);
});

// ═════════════════════════════════════════════ same-principal reuse (positive)
test("the same principal reuses its cached image within the lifetime", async () => {
  const { cache, env } = harness({ ttlMs: 1000 });
  const a1 = await cache.load(PATH);
  env.advance(500);
  const a2 = await cache.load(PATH);
  const [a3, a4] = await Promise.all([cache.load(PATH), cache.load(PATH)]);
  assert.equal(a2, a1);
  assert.equal(a3, a1);
  assert.equal(a4, a1);
  assert.equal(env.fetches.length, 1);
  assert.equal(env.revoked.length, 0);
});

test("concurrent first loads of one path share one request", async () => {
  const { cache, env } = harness({ deferred: true });
  const p1 = cache.load(PATH);
  const p2 = cache.load(PATH);
  await settle();
  env.pending.shift()();
  assert.equal(await p1, await p2);
  assert.equal(env.fetches.length, 1);
});

// ═══════════════════════════════════════════ in-flight response after switch
test("a response that arrives after the switch is discarded, never shown", async () => {
  const { cache, env } = harness({ deferred: true });
  const forA = cache.load(PATH);
  await settle();                       // A's request is in flight
  env.token = "token-tenant-B-user-9";  // switch before it answers
  const forB = cache.load(PATH);
  await settle();
  env.pending.shift()();                // A's answer arrives late
  await assert.rejects(forA, (e) => e.code === "SESSION_CHANGED");
  env.pending.shift()();                // B's answer
  const b = await forB;
  assert.match(b, /tenant-B/);
  assert.equal(env.created.length, 1, "no object URL was ever made from A's late bytes");
  assert.ok(!env.created.some((u) => /tenant-A/.test(u)));
});

test("a response that arrives after logout is discarded", async () => {
  const { cache, env } = harness({ deferred: true });
  const forA = cache.load(PATH);
  await settle();
  env.token = null;
  cache.clear();
  env.pending.shift()();
  await assert.rejects(forA, (e) => e.code === "SESSION_CHANGED");
  assert.equal(env.created.length, 0);
  assert.equal(cache.size(), 0);
});

test("a failed fetch is not cached", async () => {
  let fail = true;
  const cache = createProtectedImageCache({
    getPrincipal: () => "t",
    fetchBlob: () => (fail ? Promise.reject(new Error("404")) : Promise.resolve({})),
    createObjectURL: () => "blob:x",
    revokeObjectURL: () => {},
    setTimer: () => null,
    clearTimer: () => {},
  });
  await assert.rejects(cache.load(PATH));
  await settle();
  assert.equal(cache.size(), 0);
  fail = false;
  assert.equal(await cache.load(PATH), "blob:x");
});

// ═══════════════════════════════════════════ wiring (asserted from the source)
test("AuthImage uses the principal-bound cache and the session token", () => {
  const src = readFileSync(join(SRC, "components", "AuthImage.js"), "utf8");
  assert.match(src, /createProtectedImageCache\(/);
  assert.match(src, /getPrincipal:\s*currentPrincipal/);
  assert.match(src, /localStorage\.getItem\(TOKEN_KEY\)/);
  assert.match(src, /const TOKEN_KEY = "bw_token"/);
  assert.match(src, /addEventListener\("storage"/, "another tab's login/logout clears the cache");
  assert.match(src, /avatarCache\.subscribe\(/, "mounted images react to clear/expiry");
  assert.doesNotMatch(src, /new Map\(/, "no second, path-only cache in the component");
});

test("AuthContext clears protected images on login and logout", () => {
  const src = readFileSync(join(SRC, "contexts", "AuthContext.js"), "utf8");
  assert.match(src, /import \{ clearProtectedImages \} from "@\/components\/AuthImage"/);
  const login = src.slice(src.indexOf("const login = async"), src.indexOf("const logout ="));
  const logout = src.slice(src.indexOf("const logout ="), src.indexOf("const refreshOrg"));
  assert.match(login, /clearProtectedImages\(\)/);
  assert.match(logout, /clearProtectedImages\(\)/);
  assert.ok(login.indexOf("clearProtectedImages()") < login.indexOf('localStorage.setItem("bw_token"'),
            "cleared before the new token is stored");
});
