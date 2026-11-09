// PWA-01 — start-up wiring for the installable shell.
import { registerServiceWorker } from "./serviceWorker";
import { watchConnectivity } from "./connectivity";
import { watchInstallPrompt } from "./install";

export function initPwa() {
  watchInstallPrompt();
  watchConnectivity();
  registerServiceWorker();
}
