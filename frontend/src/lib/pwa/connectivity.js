// PWA-01 — "Без връзка" state: the browser's online flag plus failed API calls.
// A request that fails at the network level marks the app offline until the next
// successful response or the browser's `online` event.
import { createStore } from "./store";

const initialOnline = typeof navigator === "undefined" || navigator.onLine !== false;

// { browserOnline, networkFailed }
export const connectivityStore = createStore({ browserOnline: initialOnline, networkFailed: false });

export const isOffline = (s) => !s.browserOnline || s.networkFailed;

export function markNetworkFailure() {
  connectivityStore.set((s) => (s.networkFailed ? s : { ...s, networkFailed: true }));
}

export function markNetworkOk() {
  connectivityStore.set((s) => (s.networkFailed ? { ...s, networkFailed: false } : s));
}

export function watchConnectivity(win = typeof window !== "undefined" ? window : undefined) {
  if (!win) return () => {};
  const on = () => connectivityStore.set({ browserOnline: true, networkFailed: false });
  const off = () => connectivityStore.set((s) => ({ ...s, browserOnline: false }));
  win.addEventListener("online", on);
  win.addEventListener("offline", off);
  return () => {
    win.removeEventListener("online", on);
    win.removeEventListener("offline", off);
  };
}

// An axios error with no HTTP response at all (not a 4xx/5xx, not a cancel).
export function isNetworkError(err) {
  return !!err && !err.response && err.code !== "ERR_CANCELED" && (err.code === "ERR_NETWORK" || err.message === "Network Error");
}
