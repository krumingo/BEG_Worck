// PWA-02 — the app's offline queue (singleton) and its wiring to the session.
import API from "@/lib/api";
import { idbStore } from "./store";
import { createQueue, isOnlineOnly, ONLINE_ONLY_MESSAGE, STATUS } from "./queue";
import { useStore } from "../pwa/store";
import { clearTenantLocalData } from "../pwa/clearLocalData";

export { STATUS, isOnlineOnly, ONLINE_ONLY_MESSAGE };

export const BLOCKED_PATH = "/device-blocked";
const FLUSH_EVERY_MS = 60 * 1000;

export const offlineQueue = createQueue({
  store: idbStore(),
  api: API,
  onRevoked: () => {
    // R61-6: the local database is already destroyed; caches and storage go too.
    clearTenantLocalData().finally(() => {
      if (typeof window !== "undefined" && window.location.pathname !== BLOCKED_PATH) {
        window.location.href = BLOCKED_PATH;
      }
    });
  },
});

let timer = null;
let wired = false;

function wireOnce() {
  if (wired || typeof window === "undefined") return;
  wired = true;
  window.addEventListener("online", () => { offlineQueue.flush().catch(() => {}); });
  // Background Sync (where the browser has it): the service worker asks an open page to flush.
  if (navigator.serviceWorker) {
    navigator.serviceWorker.addEventListener("message", (e) => {
      if (e.data && e.data.type === "BW_SYNC_FLUSH") offlineQueue.flush().catch(() => {});
    });
  }
}

export async function startOfflineQueue(session) {
  wireOnce();
  const enabled = await offlineQueue.start(session).catch(() => false);
  if (timer) clearInterval(timer);
  timer = null;
  if (enabled) {
    offlineQueue.flush().catch(() => {});
    timer = setInterval(() => { offlineQueue.flush().catch(() => {}); }, FLUSH_EVERY_MS);
  }
  return enabled;
}

export function stopOfflineQueue() {
  if (timer) clearInterval(timer);
  timer = null;
  // R61-5: the records stay encrypted on the phone; only the session ends.
  return offlineQueue.start(null);
}

// Ask the browser for a one-off background sync after something was queued.
export async function requestBackgroundSync() {
  try {
    const reg = await navigator.serviceWorker.ready;
    if (reg && reg.sync) await reg.sync.register("bw-offline-queue");
  } catch { /* not supported: flushed on `online` and on open */ }
}

export function useOfflineQueue() {
  return useStore(offlineQueue.state);
}

// Is this an error that means "no connection" (so the record should be queued)?
export function isConnectivityError(err) {
  return !!err && !err.response && err.code !== "ERR_CANCELED";
}
