import { connectivityStore, isOffline, markNetworkFailure, markNetworkOk, watchConnectivity, isNetworkError } from "@/lib/pwa/connectivity";

beforeEach(() => connectivityStore.set({ browserOnline: true, networkFailed: false }));

test("browser offline/online events drive the state", () => {
  const stop = watchConnectivity(window);
  window.dispatchEvent(new Event("offline"));
  expect(isOffline(connectivityStore.get())).toBe(true);
  window.dispatchEvent(new Event("online"));
  expect(isOffline(connectivityStore.get())).toBe(false);
  stop();
});

test("a failed request marks offline until the next good response", () => {
  markNetworkFailure();
  expect(isOffline(connectivityStore.get())).toBe(true);
  markNetworkOk();
  expect(isOffline(connectivityStore.get())).toBe(false);
});

test("only real network errors count", () => {
  expect(isNetworkError({ code: "ERR_NETWORK", message: "Network Error" })).toBe(true);
  expect(isNetworkError({ code: "ERR_CANCELED" })).toBe(false);
  expect(isNetworkError({ code: "ERR_BAD_RESPONSE", response: { status: 500 } })).toBe(false);
  expect(isNetworkError(null)).toBe(false);
});
