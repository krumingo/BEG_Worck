// PWA-01 — names shared by the service worker and the page.

// Every app-shell cache is named `${SHELL_PREFIX}<build>-<hash>`. It holds only the
// static build files, never tenant data, so it survives logout / tenant switch.
export const SHELL_PREFIX = "bw-shell-";

// Same-origin paths the service worker never answers and never stores: the backend API
// (money, personal and tenant data, tokens), uploaded files and the websocket.
const NEVER_CACHED = [/^\/api(\/|$)/, /^\/uploads(\/|$)/, /^\/ws(\/|$)/];

export function isNeverCachedPath(pathname) {
  return NEVER_CACHED.some((re) => re.test(pathname || ""));
}

export const SW_URL = "/service-worker.js";
