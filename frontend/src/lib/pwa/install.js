// PWA-01 — "Инсталирай приложението": the browser's install prompt, or the iOS steps.
import { createStore } from "./store";

// { prompt: BeforeInstallPromptEvent | null, installed: boolean }
export const installStore = createStore({ prompt: null, installed: false });

export function isStandalone(win = typeof window !== "undefined" ? window : undefined) {
  if (!win) return false;
  const mm = typeof win.matchMedia === "function" && win.matchMedia("(display-mode: standalone)");
  return !!((mm && mm.matches) || (win.navigator && win.navigator.standalone === true));
}

// iPhone/iPad Safari has no install prompt: the user adds the app from the Share sheet.
export function isIOS(nav = typeof navigator !== "undefined" ? navigator : undefined) {
  if (!nav) return false;
  const ua = nav.userAgent || "";
  return /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && (nav.maxTouchPoints || 0) > 1);
}

// The event can fire before React mounts, so it is captured at startup.
export function watchInstallPrompt(win = typeof window !== "undefined" ? window : undefined) {
  if (!win) return () => {};
  const onPrompt = (e) => {
    e.preventDefault();
    installStore.set({ prompt: e, installed: false });
  };
  const onInstalled = () => installStore.set({ prompt: null, installed: true });
  win.addEventListener("beforeinstallprompt", onPrompt);
  win.addEventListener("appinstalled", onInstalled);
  return () => {
    win.removeEventListener("beforeinstallprompt", onPrompt);
    win.removeEventListener("appinstalled", onInstalled);
  };
}

export async function promptInstall() {
  const { prompt } = installStore.get();
  if (!prompt) return "unavailable";
  prompt.prompt();
  const choice = await prompt.userChoice.catch(() => ({ outcome: "dismissed" }));
  // A prompt event can be used once only.
  installStore.set({ prompt: null, installed: choice.outcome === "accepted" });
  return choice.outcome;
}
