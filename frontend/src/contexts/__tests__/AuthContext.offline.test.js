// PWA-01 D1 — an offline start keeps the session; only 401 (and 403 on /auth/me) ends it.
import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";

const mockGet = jest.fn();
jest.mock("@/lib/api", () => ({ __esModule: true, default: { get: (...a) => mockGet(...a), post: jest.fn() } }));

import { AuthProvider, useAuth } from "@/contexts/AuthContext";

const USER = { id: "u-1", first_name: "Иван", role: "Technician" };
const ORG = { id: "org-a", name: "А" };

function Probe() {
  const { user, loading, logout } = useAuth();
  return (
    <div>
      <span data-testid="state">{loading ? "loading" : user ? `user:${user.id}` : "anon"}</span>
      <button data-testid="logout" onClick={() => logout()} />
    </div>
  );
}

const networkError = (url) => Object.assign(new Error("Network Error"), { code: "ERR_NETWORK", config: { url } });
const httpError = (url, status) => Object.assign(new Error(`HTTP ${status}`), { response: { status }, config: { url } });

function failWith(errFor) {
  mockGet.mockImplementation((url) => (errFor(url) ? Promise.reject(errFor(url)) : Promise.resolve({ data: url === "/organization" ? ORG : USER })));
}

async function start() {
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByTestId("state").textContent).not.toBe("loading"));
  return screen.getByTestId("state").textContent;
}

beforeEach(() => {
  mockGet.mockReset();
  localStorage.clear();
  localStorage.setItem("bw_token", "tok");
  localStorage.setItem("bw_user", JSON.stringify(USER));
});

test("network error: token kept, user restored from bw_user", async () => {
  failWith((url) => networkError(url));
  expect(await start()).toBe("user:u-1");
  expect(localStorage.getItem("bw_token")).toBe("tok");
});

test("5xx: token kept, user restored", async () => {
  failWith((url) => (url === "/auth/me" ? httpError(url, 503) : null));
  expect(await start()).toBe("user:u-1");
  expect(localStorage.getItem("bw_token")).toBe("tok");
});

test("401: session cleared", async () => {
  failWith((url) => (url === "/auth/me" ? httpError(url, 401) : null));
  expect(await start()).toBe("anon");
  expect(localStorage.getItem("bw_token")).toBeNull();
  expect(localStorage.getItem("bw_user")).toBeNull();
});

test("403 on /auth/me: session cleared", async () => {
  failWith((url) => (url === "/auth/me" ? httpError(url, 403) : null));
  expect(await start()).toBe("anon");
  expect(localStorage.getItem("bw_token")).toBeNull();
});

test("403 on /organization only: session kept", async () => {
  failWith((url) => (url === "/organization" ? httpError(url, 403) : null));
  expect(await start()).toBe("user:u-1");
  expect(localStorage.getItem("bw_token")).toBe("tok");
});

test("network error without a stored user: no user, token still kept", async () => {
  localStorage.removeItem("bw_user");
  failWith((url) => networkError(url));
  expect(await start()).toBe("anon");
  expect(localStorage.getItem("bw_token")).toBe("tok");
});

test("logout awaits the cache clearing before signing out", async () => {
  failWith(() => null);
  expect(await start()).toBe("user:u-1");
  let release;
  const gate = new Promise((r) => { release = r; });
  const deleted = [];
  global.caches = {
    keys: jest.fn(async () => { await gate; return ["bw-api-left"]; }),
    delete: jest.fn(async (n) => { deleted.push(n); return true; }),
  };
  let done;
  await act(async () => { done = screen.getByTestId("logout").click(); });
  // still signed in while the caches are being cleared
  expect(screen.getByTestId("state").textContent).toBe("user:u-1");
  await act(async () => { release(); });
  await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("anon"));
  expect(deleted).toEqual(["bw-api-left"]);
  expect(localStorage.getItem("bw_token")).toBeNull();
  delete global.caches;
  void done;
});
