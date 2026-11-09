// PWA-01 — service worker registration and the "Има нова версия — Обнови" flow.
//
// * Registered only in a production build (never in `craco start` or jest).
// * A new version installs in the background and WAITS. The page only shows the
//   update bar; nothing reloads until the user presses "Обнови", so a half-filled
//   form is never lost to a silent reload.
import { createStore } from "./store";
import { SW_URL } from "./constants";

// { waiting: ServiceWorker | null }
export const updateStore = createStore({ waiting: null });

const HOURLY = 60 * 60 * 1000;

function watchRegistration(reg, sw) {
  const offer = (worker) => {
    // Only an UPDATE is offered: the very first install has no controller yet.
    if (worker && sw.controller) updateStore.set({ waiting: worker });
  };
  if (reg.waiting) offer(reg.waiting);
  reg.addEventListener("updatefound", () => {
    const installing = reg.installing;
    if (!installing) return;
    installing.addEventListener("statechange", () => {
      if (installing.state === "installed") offer(reg.waiting || installing);
    });
  });
}

export function registerServiceWorker({
  env = process.env.NODE_ENV,
  nav = typeof navigator !== "undefined" ? navigator : undefined,
  win = typeof window !== "undefined" ? window : undefined,
} = {}) {
  if (env !== "production") return false;
  if (!nav || !("serviceWorker" in nav) || !win) return false;
  const sw = nav.serviceWorker;
  const start = () =>
    sw
      .register(SW_URL, { scope: "/" })
      .then((reg) => {
        watchRegistration(reg, sw);
        win.setInterval(() => reg.update().catch(() => {}), HOURLY);
        return reg;
      })
      .catch(() => null); // no SW → the app still works online, just not installable/offline
  if (win.document && win.document.readyState === "complete") start();
  else win.addEventListener("load", start, { once: true });
  return true;
}

// Called by the "Обнови" button: activate the waiting worker, reload once it controls.
export function applyUpdate({
  nav = typeof navigator !== "undefined" ? navigator : undefined,
  win = typeof window !== "undefined" ? window : undefined,
} = {}) {
  const { waiting } = updateStore.get();
  if (!waiting || !nav || !nav.serviceWorker) return false;
  let reloaded = false;
  nav.serviceWorker.addEventListener("controllerchange", () => {
    if (reloaded) return;
    reloaded = true;
    win.location.reload();
  });
  waiting.postMessage({ type: "SKIP_WAITING" });
  updateStore.set({ waiting: null });
  return true;
}
