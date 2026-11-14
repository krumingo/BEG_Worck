/**
 * MEDIA-SEC-01 (FG-540) — an image the server gives only to a logged-in user.
 *
 * Avatars (`/api/media/avatar/...`) and media files (`/api/media/file/...`) need the
 * session's Bearer token, which a plain <img src> never sends. This component fetches the
 * picture through the authenticated API client (the same blob pattern the app uses for PDF
 * downloads) and shows it as a `blob:` URL. While loading, or when the server says no
 * (401/403/404) or the network is down, it shows `fallback` (default: nothing).
 *
 * `src` is the stored value (`/api/media/avatar/x.jpg`, or the same with the backend
 * origin in front). A `blob:`/`data:` preview or a foreign http(s) URL is shown as is.
 */
import React, { useEffect, useState } from "react";
import API from "@/lib/api";

/** The path for the API client (relative to its `/api` base), or null if not ours. */
export function apiPathOf(src) {
  if (!src || typeof src !== "string") return null;
  let path = src;
  const backend = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "");
  if (/^https?:\/\//i.test(path)) {
    if (!backend || !path.startsWith(`${backend}/api/`)) return null;
    path = path.slice(backend.length);
  }
  if (!path.startsWith("/api/")) return null;
  return path.slice(4);   // "/api/media/avatar/x" -> "/media/avatar/x"
}

/** True when `src` must be shown as is (a local preview or a foreign URL). */
function isDirect(src) {
  return typeof src === "string" && (/^(blob|data):/i.test(src) ||
    (/^https?:\/\//i.test(src) && apiPathOf(src) === null));
}

export default function AuthImage({ src, fallback = null, ...imgProps }) {
  const [blobUrl, setBlobUrl] = useState(null);
  const [failed, setFailed] = useState(false);
  const direct = isDirect(src);

  useEffect(() => {
    let alive = true;
    let made = null;
    setBlobUrl(null);
    setFailed(false);
    if (direct) return undefined;
    const path = apiPathOf(src);
    if (!path) {
      setFailed(true);
      return undefined;
    }
    API.get(path, { responseType: "blob" })
      .then((res) => {
        if (!alive) return;
        made = URL.createObjectURL(res.data);
        setBlobUrl(made);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [src, direct]);

  if (direct) return <img src={src} alt="" {...imgProps} />;
  if (failed || !blobUrl) return fallback;
  return <img src={blobUrl} alt="" {...imgProps} onError={() => setFailed(true)} />;
}
