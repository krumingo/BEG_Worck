import { useEffect, useRef, useState } from "react";
import API from "@/lib/api";

/*
 * W0-06B/C02 — an <img> for protected avatar files.
 *
 * GET /api/media/avatar/{filename} now requires a signed-in session of the
 * same tenant (FLOW-002), so a plain <img src> — which sends no Authorization
 * header — can no longer load it. AuthImage fetches the file with the
 * session's Bearer token (lib/api.js) and shows it through a short-lived,
 * in-memory object URL that exists only in this browser tab and expires after
 * CACHE_TTL_MS. There is no public or permanent avatar URL.
 *
 * Any other src (an absolute external URL, a data: URL, a non-avatar path)
 * is rendered exactly as a normal <img>.
 */

const AVATAR_PREFIX = "/api/media/avatar/";
const CACHE_TTL_MS = 5 * 60 * 1000;
const PLACEHOLDER = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
const cache = new Map(); // path -> { promise, expires }

export function protectedAvatarPath(src) {
  if (typeof src !== "string" || !src) return null;
  let path = src;
  const backend = process.env.REACT_APP_BACKEND_URL || "";
  if (backend && path.startsWith(backend)) path = path.slice(backend.length);
  if (!path.startsWith(AVATAR_PREFIX)) return null;
  const name = path.slice(AVATAR_PREFIX.length);
  if (!name || name.includes("/") || name.includes("\\") || name.includes("..")) return null;
  return "/media/avatar/" + encodeURIComponent(name); // relative to API baseURL (…/api)
}

function load(path) {
  const now = Date.now();
  const hit = cache.get(path);
  if (hit && hit.expires > now) return hit.promise;
  if (hit) {
    hit.promise.then((url) => URL.revokeObjectURL(url)).catch(() => {});
    cache.delete(path);
  }
  const promise = API.get(path, { responseType: "blob" }).then((res) => URL.createObjectURL(res.data));
  cache.set(path, { promise, expires: now + CACHE_TTL_MS });
  promise.catch(() => cache.delete(path));
  return promise;
}

export default function AuthImage({ src, onError, alt = "", ...rest }) {
  const path = protectedAvatarPath(src);
  const [resolved, setResolved] = useState(path ? null : src);
  const ref = useRef(null);

  useEffect(() => {
    if (!path) {
      setResolved(src);
      return undefined;
    }
    let alive = true;
    setResolved(null);
    load(path)
      .then((url) => { if (alive) setResolved(url); })
      .catch(() => {
        if (alive && onError) onError({ target: ref.current, currentTarget: ref.current });
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, path]);

  return <img ref={ref} alt={alt} {...rest} src={resolved || (path ? PLACEHOLDER : src)} onError={onError} />;
}
