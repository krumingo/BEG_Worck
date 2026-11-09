// PWA-01 — the service worker is registered in production only; an update waits for the user.
import { registerServiceWorker, applyUpdate, updateStore } from "@/lib/pwa/serviceWorker";
import { isNeverCachedPath } from "@/lib/pwa/constants";

function fakeEnv({ controller = {}, waiting = null } = {}) {
  const regListeners = {};
  const reg = {
    waiting,
    installing: null,
    update: jest.fn(() => Promise.resolve()),
    addEventListener: (n, fn) => { regListeners[n] = fn; },
  };
  const swListeners = {};
  const nav = {
    serviceWorker: {
      controller,
      register: jest.fn(() => Promise.resolve(reg)),
      addEventListener: (n, fn) => { swListeners[n] = fn; },
    },
  };
  const win = {
    document: { readyState: "complete" },
    addEventListener: jest.fn(),
    setInterval: jest.fn(),
    location: { reload: jest.fn() },
  };
  return { reg, regListeners, nav, swListeners, win };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => updateStore.set({ waiting: null }));

test("not registered outside a production build", () => {
  const { nav, win } = fakeEnv();
  expect(registerServiceWorker({ env: "development", nav, win })).toBe(false);
  expect(registerServiceWorker({ env: "test", nav, win })).toBe(false);
  expect(nav.serviceWorker.register).not.toHaveBeenCalled();
});

test("not registered when the browser has no service worker support", () => {
  const { win } = fakeEnv();
  expect(registerServiceWorker({ env: "production", nav: {}, win })).toBe(false);
});

test("registered in production with scope /", async () => {
  const { nav, win } = fakeEnv();
  expect(registerServiceWorker({ env: "production", nav, win })).toBe(true);
  await flush();
  expect(nav.serviceWorker.register).toHaveBeenCalledWith("/service-worker.js", { scope: "/" });
});

test("an already waiting new version is offered, not activated", async () => {
  const waiting = { postMessage: jest.fn() };
  const { nav, win } = fakeEnv({ waiting });
  registerServiceWorker({ env: "production", nav, win });
  await flush();
  expect(updateStore.get().waiting).toBe(waiting);
  expect(waiting.postMessage).not.toHaveBeenCalled();
  expect(win.location.reload).not.toHaveBeenCalled();
});

test("the first install (no controller yet) shows no update bar", async () => {
  const { nav, win } = fakeEnv({ controller: null, waiting: { postMessage: jest.fn() } });
  registerServiceWorker({ env: "production", nav, win });
  await flush();
  expect(updateStore.get().waiting).toBeNull();
});

test("a version found later is offered once it is installed", async () => {
  const { nav, win, reg, regListeners } = fakeEnv();
  registerServiceWorker({ env: "production", nav, win });
  await flush();
  const listeners = {};
  const installing = { state: "installing", addEventListener: (n, fn) => { listeners[n] = fn; } };
  reg.installing = installing;
  regListeners.updatefound();
  installing.state = "installed";
  reg.waiting = installing;
  listeners.statechange();
  expect(updateStore.get().waiting).toBe(installing);
});

test("Обнови: SKIP_WAITING is sent, the page reloads only after the new worker takes control", () => {
  const waiting = { postMessage: jest.fn() };
  const { nav, win, swListeners } = fakeEnv();
  updateStore.set({ waiting });
  expect(applyUpdate({ nav, win })).toBe(true);
  expect(waiting.postMessage).toHaveBeenCalledWith({ type: "SKIP_WAITING" });
  expect(win.location.reload).not.toHaveBeenCalled();
  swListeners.controllerchange();
  swListeners.controllerchange();
  expect(win.location.reload).toHaveBeenCalledTimes(1);
});

test("nothing happens without a waiting version", () => {
  const { nav, win } = fakeEnv();
  expect(applyUpdate({ nav, win })).toBe(false);
});

test.each(["/api/payments", "/api", "/api/", "/uploads/a.jpg", "/ws"])("%s is never cached", (p) => {
  expect(isNeverCachedPath(p)).toBe(true);
});

test.each(["/", "/index.html", "/static/js/main.js", "/apis-docs", "/projects/1"])("%s may be served from the shell", (p) => {
  expect(isNeverCachedPath(p)).toBe(false);
});
