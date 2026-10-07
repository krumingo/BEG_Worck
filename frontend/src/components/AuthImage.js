import { useEffect, useRef, useState } from "react";
import API from "@/lib/api";
import { createProtectedImageCache } from "@/lib/protectedImageCache";
import { protectedAvatarPath } from "@/lib/protectedAvatarPath";

/*
 * W0-06B — an <img> for protected avatar files.
 *
 * GET /api/media/avatar/{filename} requires a signed-in session of the same
 * tenant (FLOW-002), so a plain <img src>, which sends no Authorization header,
 * cannot load it. AuthImage fetches the file with the session's Bearer token
 * and shows it through an in-memory object URL.
 *
 * C03: the object-URL cache is bound to the CURRENT session principal (the
 * bw_token) — see lib/protectedImageCache.js. An entry of one account/tenant
 * is never returned to another. The cache is cleared and every object URL is
 * revoked on login, logout and any token change (also from another tab), and
 * each entry is revoked by a timer after 5 minutes. There is no public or
 * permanent avatar URL.
 *
 * Any other src (an absolute external URL, a data: URL, a non-avatar path)
 * is rendered exactly as a normal <img>.
 */

const TOKEN_KEY = "bw_token";
const PLACEHOLDER = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";

function currentPrincipal() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || null;
  } catch (e) {
    return null;
  }
}

const avatarCache = createProtectedImageCache({
  getPrincipal: currentPrincipal,
  fetchBlob: (path, principal) =>
    API.get(path, {
      responseType: "blob",
      headers: { Authorization: `Bearer ${principal}` },
    }).then((res) => res.data),
  createObjectURL: (blob) => URL.createObjectURL(blob),
  revokeObjectURL: (url) => URL.revokeObjectURL(url),
});

/** Revoke and forget every protected image. Called on login and logout. */
export function clearProtectedImages() {
  avatarCache.clear();
}

if (typeof window !== "undefined" && window.addEventListener) {
  // A login/logout in ANOTHER tab changes the token under this one.
  window.addEventListener("storage", (e) => {
    if (e.key === TOKEN_KEY || e.key === null) avatarCache.clear();
  });
}

export { protectedAvatarPath };

export default function AuthImage({ src, onError, alt = "", ...rest }) {
  const path = protectedAvatarPath(src);
  const [resolved, setResolved] = useState(path ? null : src);
  const [epoch, setEpoch] = useState(0);
  const ref = useRef(null);

  // Session cleared or this entry expired: stop showing the old object URL and
  // load again under the current principal (or show nothing if logged out).
  useEffect(() => {
    if (!path) return undefined;
    return avatarCache.subscribe((event) => {
      if (event.type === "cleared" || event.path === path) {
        setResolved(null);
        setEpoch((n) => n + 1);
      }
    });
  }, [path]);

  useEffect(() => {
    if (!path) {
      setResolved(src);
      return undefined;
    }
    let alive = true;
    setResolved(null);
    avatarCache.load(path)
      .then((url) => { if (alive) setResolved(url); })
      .catch((err) => {
        if (!alive || (err && err.code === "SESSION_CHANGED")) return; // a reload follows
        if (onError) onError({ target: ref.current, currentTarget: ref.current });
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, path, epoch]);

  return <img ref={ref} alt={alt} {...rest} src={resolved || (path ? PLACEHOLDER : src)} onError={onError} />;
}
