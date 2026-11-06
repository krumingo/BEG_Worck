/**
 * RC-01 — the visible build identity. The frontend SHA is baked in at build time
 * (REACT_APP_BUILD_SHA via craco.config.js); the server SHA comes from /api/version.
 * Same verified build -> no warning; a different or an unknown SHA -> a visible warning.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import BuildIdentity from "@/components/BuildIdentity";
import { compareBuilds, frontendBuild, shortSha } from "@/lib/buildInfo";

const SHA_A = "c0e34e1f3037010311d352683d519c3c9d7dcbfa";
const SHA_B = "0b53bcd5b977ee27de8d4cee363fed41dd897482";
const ORIGINAL_ENV = { ...process.env };

function serverAnswers(body, ok = true) {
  global.fetch = jest.fn(() => Promise.resolve({ ok, json: () => Promise.resolve(body) }));
}

async function renderWith(frontendSha, server) {
  process.env.REACT_APP_BUILD_SHA = frontendSha;
  process.env.REACT_APP_BACKEND_URL = "http://api.test";
  if (server instanceof Error) global.fetch = jest.fn(() => Promise.reject(server));
  else serverAnswers(server);
  render(<BuildIdentity />);
  await waitFor(() => expect(screen.getByTestId("build-identity").dataset.buildStatus).not.toBe("checking"));
  return screen.getByTestId("build-identity");
}

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  delete global.fetch;
});

test("shows the first 12 characters of the build SHA with the full SHA in the tooltip", async () => {
  const box = await renderWith(SHA_A, { build_sha: SHA_A, build_time: null, environment_label: "staging", source: "build-info-file" });
  const sha = screen.getByTestId("build-sha");
  expect(sha.textContent).toContain(SHA_A.slice(0, 12));
  expect(sha.textContent).not.toContain(SHA_A);
  expect(sha.getAttribute("title")).toBe(SHA_A);
  expect(screen.getByTestId("build-env").textContent).toBe("staging");
  expect(box.dataset.buildStatus).toBe("match");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(global.fetch).toHaveBeenCalledWith("http://api.test/api/version", expect.anything());
});

test("a different server SHA shows the mismatch warning", async () => {
  const box = await renderWith(SHA_A, { build_sha: SHA_B, build_time: null, environment_label: "production", source: "build-info-file" });
  expect(box.dataset.buildStatus).toBe("mismatch");
  const alert = screen.getByTestId("build-warning-mismatch");
  expect(alert.textContent).toContain("Версията на интерфейса и сървъра се различава");
  expect(screen.getByTestId("build-server-sha").textContent).toContain(SHA_B.slice(0, 12));
});

test("an unknown frontend build shows the unverified warning", async () => {
  const box = await renderWith("unknown", { build_sha: SHA_A, build_time: null, environment_label: "test", source: "env" });
  expect(box.dataset.buildStatus).toBe("unknown");
  expect(screen.getByTestId("build-sha").textContent).toContain("unknown");
  expect(screen.getByTestId("build-warning-unknown")).toBeTruthy();
});

test("an unknown server build shows the unverified warning", async () => {
  await renderWith(SHA_A, { build_sha: "unknown", build_time: null, environment_label: "unknown", source: "none" });
  expect(screen.getByTestId("build-warning-unknown")).toBeTruthy();
});

test("an unreachable server is said so, not shown as a match", async () => {
  const box = await renderWith(SHA_A, new Error("network down"));
  expect(box.dataset.buildStatus).toBe("unreachable");
  expect(screen.getByTestId("build-warning-unreachable")).toBeTruthy();
});

test("a malformed frontend constant is treated as unknown", () => {
  expect(frontendBuild({ REACT_APP_BUILD_SHA: "C0E34E1F" }).build_sha).toBe("unknown");
  expect(frontendBuild({}).build_sha).toBe("unknown");
  expect(shortSha("nope")).toBe("unknown");
  expect(compareBuilds(SHA_A, undefined)).toBe("checking");
  expect(compareBuilds(SHA_A, { build_sha: SHA_A.toUpperCase() })).toBe("unknown");
});
