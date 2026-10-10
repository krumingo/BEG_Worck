/*
 * W0-06B/C04 — every protected-avatar consumer goes through AuthImage.
 *
 *   node --test frontend/tests/protected_avatar_consumers.test.mjs
 *
 * Codex C03 review: the report screens still rendered `worker_avatar` (the
 * user's /api/media/avatar/... URL, backend/app/routes/all_reports.py) with a
 * plain <img src={backend + worker_avatar}>. A plain image request carries no
 * Bearer header, so the now-protected route answers 401/403 and the photos
 * broke. This file proves, deterministically and with zero dependencies:
 *
 *  1. the three report consumers render AuthImage, keep their CSS classes and
 *     alt text, and no longer build a backend-prefixed URL;
 *  2. NO file under frontend/src renders a plain <img> whose src is built from
 *     the backend URL or from an avatar field — so a fourth consumer cannot
 *     slip back in silently;
 *  3. the value those screens pass (a /api/media/avatar/ URL) is classified as
 *     protected by the very helper AuthImage uses, and goes through the
 *     principal-bound cache with the session token: same session → fetched
 *     with that token and reused; no session → nothing fetched; another
 *     principal → fetched again as that principal, never the old image.
 *
 * The server-side half (no session 401/403, cross-tenant 404, same-tenant
 * 200, non-avatar media 404) is backend/tests/test_w0_06b_avatar_route.py.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

import { protectedAvatarPath } from "../src/lib/protectedAvatarPath.js";
import { createProtectedImageCache } from "../src/lib/protectedImageCache.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");
const read = (rel) => readFileSync(join(SRC, rel), "utf8");

/** The three consumers named by the C03 review, with their exact markup. */
const REPORT_CONSUMERS = [
  { file: "pages/AllReportsPage.js", expr: "r.worker_avatar", cls: "w-6 h-6 rounded-full object-cover" },
  { file: "pages/AllReportsPage.js", expr: "detail.worker_avatar", cls: "w-10 h-10 rounded-full object-cover" },
  { file: "components/GroupedReportsTable.js", expr: "g.worker_avatar", cls: "w-7 h-7 rounded-full object-cover" },
];

function sourceFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full));
    else if (/\.(js|jsx|ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

/** Every <img ...> opening tag in a file, possibly spanning lines. */
function imgTags(text) {
  const tags = [];
  const re = /<img\b/g;
  let m;
  while ((m = re.exec(text))) {
    let depth = 0;
    let i = m.index;
    for (; i < text.length; i += 1) {
      const c = text[i];
      if (c === "{") depth += 1;
      else if (c === "}") depth -= 1;
      else if (c === ">" && depth === 0) break;
    }
    const line = text.slice(0, m.index).split("\n").length;
    tags.push({ tag: text.slice(m.index, i + 1), line });
  }
  return tags;
}

// ═════════════════════════════════════════ 1. the three report consumers
for (const c of REPORT_CONSUMERS) {
  test(`${c.file}: ${c.expr} renders through AuthImage with unchanged markup`, () => {
    const text = read(c.file);
    const expected = `<AuthImage src={${c.expr}} className="${c.cls}" alt="" />`;
    assert.ok(text.includes(expected), "expected exactly: " + expected);
    assert.ok(!text.includes("${" + c.expr + "}"), "no backend-prefixed template of " + c.expr);
  });
}

test("both report files import the authenticated AuthImage component", () => {
  for (const file of new Set(REPORT_CONSUMERS.map((c) => c.file))) {
    assert.match(read(file), /^import AuthImage from "@\/components\/AuthImage";$/m, file);
  }
});

test("the report screens keep exactly their three avatar renderers", () => {
  const all = read("pages/AllReportsPage.js") + read("components/GroupedReportsTable.js");
  assert.equal((all.match(/<AuthImage src=\{[a-z]+\.worker_avatar\}/g) || []).length, 3);
  assert.equal((all.match(/<img\b/g) || []).length, 0, "no plain <img> left in the report screens");
});

// ═══════════════════════════ 2. no plain protected-avatar <img> anywhere
test("no file renders a plain <img> from the backend URL or an avatar field", () => {
  const offenders = [];
  for (const full of sourceFiles(SRC)) {
    const text = readFileSync(full, "utf8");
    for (const { tag, line } of imgTags(text)) {
      const src = (tag.match(/\bsrc=\{([\s\S]*?)\}\s*(?:\w+=|\/?>)/) || [])[1] || "";
      const fromBackend = /REACT_APP_BACKEND_URL/.test(src);
      const fromAvatarField = /avatar/i.test(src) && !/avatarPreview/.test(src);
      const literalAvatar = /\/api\/media\/avatar\//.test(tag);
      if (fromBackend && /avatar/i.test(src)) offenders.push(`${relative(SRC, full)}:${line}`);
      else if (fromAvatarField || literalAvatar) offenders.push(`${relative(SRC, full)}:${line}`);
    }
  }
  assert.deepEqual(offenders, [], "plain protected-avatar <img>: " + offenders.join(", "));
});

test("the scan itself catches the C03 shape (mutation check)", () => {
  const c03 = '<img src={`${process.env.REACT_APP_BACKEND_URL}${g.worker_avatar}`} className="x" alt="" />';
  const [{ tag }] = imgTags(c03);
  const src = (tag.match(/\bsrc=\{([\s\S]*?)\}\s*(?:\w+=|\/?>)/) || [])[1] || "";
  assert.ok(/REACT_APP_BACKEND_URL/.test(src) && /avatar/i.test(src));
});

// ═══════════════════ 3. the passed value takes the authenticated path
const WORKER_AVATAR = "/api/media/avatar/2f7c-worker.png"; // what all_reports.py returns

test("a worker_avatar value is a protected avatar for AuthImage", () => {
  assert.equal(protectedAvatarPath(WORKER_AVATAR, ""), "/media/avatar/2f7c-worker.png");
  assert.equal(protectedAvatarPath("https://be.example" + WORKER_AVATAR, "https://be.example"),
               "/media/avatar/2f7c-worker.png");
  // not avatars → never routed through the protected fetch
  assert.equal(protectedAvatarPath("/api/media/file/invoice.jpg", ""), null);
  assert.equal(protectedAvatarPath("/api/media/avatar/../x", ""), null);
  assert.equal(protectedAvatarPath(null, ""), null);
});

function session(initialToken) {
  const env = { token: initialToken, fetches: [] };
  const cache = createProtectedImageCache({
    getPrincipal: () => env.token,
    fetchBlob: (path, principal) => {
      env.fetches.push({ path, principal });
      return Promise.resolve({ owner: principal });
    },
    createObjectURL: (blob) => "blob:" + blob.owner,
    revokeObjectURL: () => {},
    setTimer: () => null,
    clearTimer: () => {},
  });
  return { env, cache };
}

test("all three report avatars are fetched with the session token and reused", async () => {
  const { env, cache } = session("tenant-A-session");
  const path = protectedAvatarPath(WORKER_AVATAR, "");
  const urls = await Promise.all(REPORT_CONSUMERS.map(() => cache.load(path)));
  assert.deepEqual(urls, ["blob:tenant-A-session", "blob:tenant-A-session", "blob:tenant-A-session"]);
  assert.deepEqual(env.fetches, [{ path, principal: "tenant-A-session" }],
                   "one authenticated request, carrying the current session's token");
});

test("without a session no report avatar is fetched or shown", async () => {
  const { env, cache } = session(null);
  const path = protectedAvatarPath(WORKER_AVATAR, "");
  for (const _ of REPORT_CONSUMERS) {
    await assert.rejects(cache.load(path), (e) => e.code === "NO_SESSION");
  }
  assert.equal(env.fetches.length, 0);
});

test("after a switch to another tenant the report avatar is fetched again as that tenant", async () => {
  const { env, cache } = session("tenant-A-session");
  const path = protectedAvatarPath(WORKER_AVATAR, "");
  assert.equal(await cache.load(path), "blob:tenant-A-session");
  env.token = "tenant-B-session";
  assert.equal(await cache.load(path), "blob:tenant-B-session");
  assert.deepEqual(env.fetches.map((f) => f.principal), ["tenant-A-session", "tenant-B-session"]);
});

test("AuthImage uses this same helper and the principal-bound cache", () => {
  const src = read("components/AuthImage.js");
  assert.match(src, /import \{ protectedAvatarPath \} from "@\/lib\/protectedAvatarPath";/);
  assert.match(src, /const path = protectedAvatarPath\(src\);/);
  assert.match(src, /avatarCache\.load\(path\)/);
  assert.match(src, /Authorization: `Bearer \$\{principal\}`/);
});
