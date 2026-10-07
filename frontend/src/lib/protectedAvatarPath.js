/*
 * W0-06B — which image sources are PROTECTED avatars.
 *
 * GET /api/media/avatar/{filename} needs a signed-in session of the same
 * tenant, so any such src must be loaded through components/AuthImage.js
 * (authenticated fetch + principal-bound cache), never a plain <img src>.
 * Returns the API-relative path ("/media/avatar/<name>") to fetch, or null
 * for anything that is not a protected avatar (external URL, data: URL,
 * another route, a malformed or traversing name).
 *
 * Pure, so the rule is tested directly in Node
 * (frontend/tests/protected_avatar_consumers.test.mjs).
 */
export const AVATAR_PREFIX = "/api/media/avatar/";

export function protectedAvatarPath(src, backend = process.env.REACT_APP_BACKEND_URL || "") {
  if (typeof src !== "string" || !src) return null;
  let path = src;
  if (backend && path.startsWith(backend)) path = path.slice(backend.length);
  if (!path.startsWith(AVATAR_PREFIX)) return null;
  const name = path.slice(AVATAR_PREFIX.length);
  if (!name || name.includes("/") || name.includes("\\") || name.includes("..")) return null;
  return "/media/avatar/" + encodeURIComponent(name); // relative to API baseURL (…/api)
}
