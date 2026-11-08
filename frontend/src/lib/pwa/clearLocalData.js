// PWA-01 — clear what this device holds for a tenant, on logout and on tenant switch
// (CLAUDE.md §3 tenant isolation; R20/R48: no tenant data left on a shared phone).
//
// * Cache Storage: every cache except the app shell (static build files only) is
//   deleted. PWA-01 itself never caches /api, so normally there is nothing else; this
//   also removes anything an older build or a future step might have left.
// * sessionStorage: cleared completely.
// * localStorage: an ALLOW-LIST is kept (device preferences + the separate platform
//   admin session); everything else, including keys added later, is removed.
import { SHELL_PREFIX } from "./constants";

export const TENANT_MARKER_KEY = "bw_pwa_tenant";
export const SESSION_KEYS = ["bw_token", "bw_user"];
// Device preferences, not tenant data. The platform admin session is a separate login.
export const DEVICE_KEYS = ["lang", "allReports.viewMode", "offer_grouping_enabled", "bw_platform_token", "bw_platform_user"];
export const CLEARED_EVENT = "bw:tenant-data-cleared";

function storageKeys(storage) {
  const keys = [];
  for (let i = 0; i < storage.length; i += 1) keys.push(storage.key(i));
  return keys;
}

export async function clearTenantLocalData({
  keepSession = false,
  local = typeof localStorage !== "undefined" ? localStorage : undefined,
  session = typeof sessionStorage !== "undefined" ? sessionStorage : undefined,
  cacheStorage = typeof caches !== "undefined" ? caches : undefined,
  win = typeof window !== "undefined" ? window : undefined,
} = {}) {
  const keep = new Set([...DEVICE_KEYS, ...(keepSession ? [...SESSION_KEYS, TENANT_MARKER_KEY] : [])]);
  const removed = [];
  try {
    if (local) {
      storageKeys(local).forEach((k) => {
        if (!keep.has(k)) {
          local.removeItem(k);
          removed.push(k);
        }
      });
    }
  } catch { /* storage blocked: nothing stored either */ }
  try {
    if (session) session.clear();
  } catch { /* ignore */ }
  // In-memory state (e.g. the active project) listens for this.
  try {
    if (win && typeof win.dispatchEvent === "function") win.dispatchEvent(new win.Event(CLEARED_EVENT));
  } catch { /* ignore */ }
  const deletedCaches = [];
  try {
    if (cacheStorage) {
      const names = await cacheStorage.keys();
      await Promise.all(
        names
          .filter((n) => !n.startsWith(SHELL_PREFIX))
          .map((n) => cacheStorage.delete(n).then(() => deletedCaches.push(n))),
      );
    }
  } catch { /* ignore */ }
  return { removed, deletedCaches };
}

// Called whenever the active organization (tenant) is known. A different tenant than
// the one this device last held → clear the previous tenant's data, keep the new login.
export async function noteActiveTenant(tenantId, { local = typeof localStorage !== "undefined" ? localStorage : undefined, ...rest } = {}) {
  if (!tenantId || !local) return { switched: false };
  let previous = null;
  try { previous = local.getItem(TENANT_MARKER_KEY); } catch { return { switched: false }; }
  const switched = !!previous && previous !== String(tenantId);
  if (switched) await clearTenantLocalData({ keepSession: true, local, ...rest });
  try { local.setItem(TENANT_MARKER_KEY, String(tenantId)); } catch { /* ignore */ }
  return { switched, previous };
}
