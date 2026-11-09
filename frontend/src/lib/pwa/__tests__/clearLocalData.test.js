// PWA-01 — logout and tenant switch leave no tenant data on the device.
import { clearTenantLocalData, noteActiveTenant, TENANT_MARKER_KEY, CLEARED_EVENT } from "@/lib/pwa/clearLocalData";

function fakeCaches(names) {
  const store = new Set(names);
  return {
    keys: jest.fn(async () => [...store]),
    delete: jest.fn(async (n) => store.delete(n)),
    names: () => [...store].sort(),
  };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem("bw_token", "tok");
  localStorage.setItem("bw_user", "{}");
  localStorage.setItem(TENANT_MARKER_KEY, "org-a");
  localStorage.setItem("lang", "bg");
  localStorage.setItem("bw_platform_token", "ptok");
  localStorage.setItem("some_tenant_draft", "secret");
  sessionStorage.setItem("x", "y");
});

test("logout: tenant keys, session storage and non-shell caches are removed", async () => {
  const caches = fakeCaches(["bw-shell-abc-1", "bw-api-leftover", "other"]);
  const seen = jest.fn();
  window.addEventListener(CLEARED_EVENT, seen);
  const res = await clearTenantLocalData({ cacheStorage: caches });
  window.removeEventListener(CLEARED_EVENT, seen);

  expect(localStorage.getItem("bw_token")).toBeNull();
  expect(localStorage.getItem("bw_user")).toBeNull();
  expect(localStorage.getItem(TENANT_MARKER_KEY)).toBeNull();
  expect(localStorage.getItem("some_tenant_draft")).toBeNull();
  expect(localStorage.getItem("lang")).toBe("bg");
  expect(localStorage.getItem("bw_platform_token")).toBe("ptok");
  expect(sessionStorage.length).toBe(0);
  expect(caches.names()).toEqual(["bw-shell-abc-1"]);
  expect(res.deletedCaches.sort()).toEqual(["bw-api-leftover", "other"]);
  expect(seen).toHaveBeenCalledTimes(1);
});

test("tenant switch: previous tenant's data is cleared, the new login is kept", async () => {
  const caches = fakeCaches(["bw-shell-abc-1", "leftover"]);
  const res = await noteActiveTenant("org-b", { cacheStorage: caches });
  expect(res).toEqual({ switched: true, previous: "org-a" });
  expect(localStorage.getItem("bw_token")).toBe("tok");
  expect(localStorage.getItem("bw_user")).toBe("{}");
  expect(localStorage.getItem("some_tenant_draft")).toBeNull();
  expect(sessionStorage.length).toBe(0);
  expect(caches.names()).toEqual(["bw-shell-abc-1"]);
  expect(localStorage.getItem(TENANT_MARKER_KEY)).toBe("org-b");
});

test("same tenant again: nothing is cleared", async () => {
  const caches = fakeCaches(["leftover"]);
  const res = await noteActiveTenant("org-a", { cacheStorage: caches });
  expect(res.switched).toBe(false);
  expect(localStorage.getItem("some_tenant_draft")).toBe("secret");
  expect(caches.delete).not.toHaveBeenCalled();
});

test("first tenant on this device: marker is written, nothing cleared", async () => {
  localStorage.removeItem(TENANT_MARKER_KEY);
  const res = await noteActiveTenant("org-a", { cacheStorage: fakeCaches([]) });
  expect(res.switched).toBe(false);
  expect(localStorage.getItem(TENANT_MARKER_KEY)).toBe("org-a");
  expect(localStorage.getItem("some_tenant_draft")).toBe("secret");
});

test("no tenant id: no-op", async () => {
  expect(await noteActiveTenant(undefined)).toEqual({ switched: false });
  expect(localStorage.getItem(TENANT_MARKER_KEY)).toBe("org-a");
});

test("works without Cache Storage (old browser / jsdom)", async () => {
  await expect(clearTenantLocalData({ cacheStorage: undefined })).resolves.toMatchObject({ deletedCaches: [] });
});

test("logout expires the analytics cookies (ph_*) and leaves others", async () => {
  document.cookie = "ph_phc_test_posthog=%7B%22distinct_id%22%3A%22x%22%7D; path=/";
  document.cookie = "other=keep; path=/";
  const res = await clearTenantLocalData({ cacheStorage: undefined });
  expect(document.cookie).not.toMatch(/ph_/);
  expect(document.cookie).toMatch(/other=keep/);
  expect(res.removed).toContain("cookie:ph_phc_test_posthog");
});
