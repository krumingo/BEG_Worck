/**
 * MEDIA-SEC-01 (FG-540) — avatars are served only with the session's Bearer token, so the
 * app no longer points a plain <img src> at /api/media/avatar/...: AuthImage fetches the
 * picture through the authenticated API client and shows a blob: URL.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

const mockGet = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockGet(...a) },
}));

// eslint-disable-next-line import/first
import AuthImage, { apiPathOf } from "@/components/AuthImage";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env.REACT_APP_BACKEND_URL = "http://api.test";
  mockGet.mockReset();
  global.URL.createObjectURL = jest.fn(() => "blob:avatar-1");
  global.URL.revokeObjectURL = jest.fn();
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

test("apiPathOf maps only our /api paths to the API client's relative path", () => {
  expect(apiPathOf("/api/media/avatar/a.jpg")).toBe("/media/avatar/a.jpg");
  expect(apiPathOf("http://api.test/api/media/avatar/a.jpg")).toBe("/media/avatar/a.jpg");
  expect(apiPathOf("https://elsewhere.test/api/media/avatar/a.jpg")).toBeNull();
  expect(apiPathOf("/static/a.jpg")).toBeNull();
  expect(apiPathOf(null)).toBeNull();
});

test("an avatar is fetched with the authenticated client as a blob, never as <img src=/api/...>", async () => {
  mockGet.mockResolvedValue({ data: new Blob(["x"], { type: "image/jpeg" }) });
  const { container } = render(<AuthImage src="/api/media/avatar/a.jpg" alt="Иван" fallback={<span>ИИ</span>} />);
  expect(screen.getByText("ИИ")).toBeTruthy();                 // while loading: the fallback
  await waitFor(() => expect(container.querySelector("img")).not.toBeNull());
  expect(mockGet).toHaveBeenCalledWith("/media/avatar/a.jpg", { responseType: "blob" });
  expect(container.querySelector("img").getAttribute("src")).toBe("blob:avatar-1");
  expect(container.innerHTML).not.toContain("/api/media/avatar");
});

test("a refused avatar (404 / 401) shows the fallback, not a broken image", async () => {
  mockGet.mockRejectedValue({ response: { status: 404 } });
  const { container } = render(<AuthImage src="/api/media/avatar/other.jpg" fallback={<span>ИИ</span>} />);
  await waitFor(() => expect(mockGet).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByText("ИИ")).toBeTruthy());
  expect(container.querySelector("img")).toBeNull();
});

test("a local blob: preview is shown as is, without a request", () => {
  const { container } = render(<AuthImage src="blob:local-preview" />);
  expect(container.querySelector("img").getAttribute("src")).toBe("blob:local-preview");
  expect(mockGet).not.toHaveBeenCalled();
});

test("no source file points a plain <img src> at an avatar URL any more", () => {
  const fs = require("fs");
  const path = require("path");
  const root = path.resolve(__dirname, "../..");
  const offenders = [];
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir)) {
      const full = path.join(dir, name);
      if (fs.statSync(full).isDirectory()) {
        if (name !== "__tests__" && name !== "node_modules") walk(full);
      } else if (/\.(js|jsx)$/.test(name)) {
        const text = fs.readFileSync(full, "utf8");
        if (/<img src=\{`\$\{process\.env\.REACT_APP_BACKEND_URL\}\$\{[^}]*avatar/i.test(text)) offenders.push(full);
      }
    }
  };
  walk(root);
  expect(offenders).toEqual([]);
});

test("FG-590a: a new avatar is a fresh PROFILE upload stored as /api/media/avatar/<name>", () => {
  const fs = require("fs");
  const path = require("path");
  const page = fs.readFileSync(path.resolve(__dirname, "../../pages/EmployeesPage.js"), "utf8");
  expect(page).not.toMatch(/append\("context_type",\s*"avatar"\)/);
  expect(page).toMatch(/append\("context_type",\s*"profile"\)/);
  expect(page).toMatch(/avatar_url:\s*`\/api\/media\/avatar\/\$\{stored\}`/);
});
