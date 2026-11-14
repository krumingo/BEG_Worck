/**
 * MEDIA-SEC-01 — „Файлове за преглед“ (/media/review): who reaches it, who sees which
 * button, and that every decision goes to the existing API with an Idempotency-Key and the
 * reason. The server decides each call; these tests keep the UI from offering a button the
 * server refuses (R83(2): the Owner decides; R88: the Owner restores; FG-558: Owner/Admin read).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

// jest 27 cannot load react-router-dom 7 (see MasterDataRoute.test.js): a stand-in.
let mockPath = "/media/review";
jest.mock("react-router-dom", () => ({
  __esModule: true,
  Navigate: ({ to }) => <div data-testid="redirect" data-to={to} />,
  NavLink: ({ to, children, className, end, ...rest }) => (
    <a href={to} {...rest}>{typeof children === "function" ? children({ isActive: false }) : children}</a>
  ),
  useLocation: () => ({ pathname: mockPath }),
  useNavigate: () => () => {},
}), { virtual: true });

let mockAuth = { user: { id: "u-1", role: "Owner", first_name: "A", last_name: "B" }, loading: false };
jest.mock("@/contexts/AuthContext", () => ({
  __esModule: true,
  useAuth: () => ({ ...mockAuth, org: null, logout: jest.fn() }),
}));
jest.mock("@/contexts/ProjectContext", () => ({
  __esModule: true,
  useActiveProject: () => ({ activeProject: null, clearActiveProject: jest.fn() }),
}));
jest.mock("react-i18next", () => ({ __esModule: true, useTranslation: () => ({ t: (key) => key }) }));
jest.mock("@/components/NotificationBell", () => ({ __esModule: true, default: () => null }));
jest.mock("@/components/LanguageSwitcher", () => ({ __esModule: true, default: () => null }));
jest.mock("@/components/ChangePasswordModal", () => ({ __esModule: true, default: () => null }));
// the layout's build badge fetches /version.json — no network in a unit test
jest.mock("@/components/BuildIdentity", () => ({ __esModule: true, default: () => null }));
jest.mock("@/components/pwa/InstallAppButton", () => ({ __esModule: true, default: () => null }));
jest.mock("sonner", () => ({ __esModule: true, toast: { success: jest.fn(), error: jest.fn() } }));

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) },
}));

/* eslint-disable import/first */
import MediaReviewPage from "@/pages/MediaReviewPage";
import MediaReviewRoute from "@/components/MediaReviewRoute";
import DashboardLayout from "@/components/DashboardLayout";
import { REVIEW_ROLES, DECIDE_ROLES, RESTORE_ROLES } from "@/lib/mediaReviewAccess";
/* eslint-enable import/first */

const REQUEST = {
  id: "rq-1", media_id: "m-used", reason: "грешна снимка", requested_by: "admin-1",
  requested_at: "2026-11-14T08:00:00+00:00", status: "pending", use_kinds: ["work_report"],
};
const RETIRED = (canRestore) => ({
  id: "m-ret", filename: "a.jpg", retired_reason: "дубликат", retired_by: "tech-1",
  retired_at: "2026-11-13T08:00:00+00:00", can_restore: canRestore,
});

const page = (items, total = items.length, next = null) =>
  ({ data: { items, total, skip: 0, limit: 50, next_skip: next } });

function serve({ canRestore = true } = {}) {
  mockGet.mockImplementation((url) => {
    if (url === "/media-retire-requests") return Promise.resolve(page([REQUEST]));
    if (url === "/media-retired") return Promise.resolve(page([RETIRED(canRestore)]));
    return Promise.reject({ response: { status: 404 } });
  });
  mockPost.mockResolvedValue({ data: { ok: true } });
}

async function renderPageAs(role, opts) {
  mockAuth = { user: { id: "u-1", role }, loading: false };
  serve(opts);
  render(<MediaReviewPage />);
  await screen.findByTestId("request-rq-1");
}

async function openRetiredTab() {
  // Radix Tabs switch on mouse down (left button)
  await act(async () => { fireEvent.mouseDown(screen.getByTestId("tab-retired"), { button: 0 }); });
  return screen.findByTestId("retired-m-ret");
}

beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); mockPath = "/media/review"; });

// ── who reaches the screen ───────────────────────────────────────────────
test.each(["Owner", "Admin"])("%s reaches the screen", (role) => {
  mockAuth = { user: { id: "u-1", role }, loading: false };
  render(<MediaReviewRoute><div data-testid="inside" /></MediaReviewRoute>);
  expect(screen.queryByTestId("redirect")).toBeNull();
});

test.each(["SiteManager", "Accountant", "Technician", "Viewer", "Driver", "Warehousekeeper"])(
  "%s is sent away (the server refuses these lists)", (role) => {
    mockAuth = { user: { id: "u-1", role }, loading: false };
    render(<MediaReviewRoute><div data-testid="inside" /></MediaReviewRoute>);
    expect(screen.getByTestId("redirect").getAttribute("data-to")).toBe("/");
    expect(screen.queryByTestId("inside")).toBeNull();
  });

test("no session → login", () => {
  mockAuth = { user: null, loading: false };
  render(<MediaReviewRoute><div /></MediaReviewRoute>);
  expect(screen.getByTestId("redirect").getAttribute("data-to")).toBe("/login");
});

// ── the sidebar entry ────────────────────────────────────────────────────
test.each([["Owner", true], ["Admin", true], ["SiteManager", false], ["Accountant", false]])(
  "%s — sidebar entry shown: %s", (role, shown) => {
    mockAuth = { user: { id: "u-1", role, first_name: "A", last_name: "B" }, loading: false };
    render(<DashboardLayout><div /></DashboardLayout>);
    const nav = screen.getByTestId("sidebar-nav");
    expect(Boolean(nav.querySelector('a[href="/media/review"]'))).toBe(shown);
  });

// ── tab 1: retire requests ───────────────────────────────────────────────
test("the Owner sees approve / reject; reject needs a reason and sends it with an Idempotency-Key", async () => {
  await renderPageAs("Owner");
  expect(screen.getByTestId("approve-rq-1")).toBeTruthy();
  expect(screen.queryByTestId("media-review-readonly")).toBeNull();
  fireEvent.click(screen.getByTestId("reject-rq-1"));
  const confirm = screen.getByTestId("reason-confirm-reject-rq-1");
  expect(confirm.disabled).toBe(true);                       // no reason → cannot confirm
  fireEvent.change(screen.getByTestId("reason-input-reject-rq-1"), { target: { value: "  не е грешна " } });
  expect(confirm.disabled).toBe(false);
  await act(async () => { fireEvent.click(confirm); });
  expect(mockPost).toHaveBeenCalledTimes(1);
  const [url, body, cfg] = mockPost.mock.calls[0];
  expect(url).toBe("/media/retire-requests/rq-1/reject");
  expect(body).toEqual({ reason: "не е грешна" });
  expect(cfg.headers["Idempotency-Key"]).toEqual(expect.any(String));
});

test("the Owner approves without a reason (optional) — the approve endpoint, a key", async () => {
  await renderPageAs("Owner");
  fireEvent.click(screen.getByTestId("approve-rq-1"));
  await act(async () => { fireEvent.click(screen.getByTestId("reason-confirm-approve-rq-1")); });
  const [url, body, cfg] = mockPost.mock.calls[0];
  expect(url).toBe("/media/retire-requests/rq-1/approve");
  expect(body).toEqual({});
  expect(cfg.headers["Idempotency-Key"]).toEqual(expect.any(String));
});

test("the Admin sees the request list but no approve / reject (the Owner decides)", async () => {
  await renderPageAs("Admin");
  expect(screen.getByText("грешна снимка")).toBeTruthy();
  expect(screen.queryByTestId("approve-rq-1")).toBeNull();
  expect(screen.queryByTestId("reject-rq-1")).toBeNull();
  expect(screen.getByTestId("media-review-readonly")).toBeTruthy();
});

test("a network error keeps the key for the retry; a server answer takes a new one", async () => {
  await renderPageAs("Owner");
  mockPost.mockRejectedValueOnce(new Error("offline"));      // no response → same submission
  fireEvent.click(screen.getByTestId("reject-rq-1"));
  fireEvent.change(screen.getByTestId("reason-input-reject-rq-1"), { target: { value: "x" } });
  await act(async () => { fireEvent.click(screen.getByTestId("reason-confirm-reject-rq-1")); });
  await act(async () => { fireEvent.click(screen.getByTestId("reason-confirm-reject-rq-1")); });
  const k1 = mockPost.mock.calls[0][2].headers["Idempotency-Key"];
  const k2 = mockPost.mock.calls[1][2].headers["Idempotency-Key"];
  expect(k2).toBe(k1);
});

// ── tab 2: retired files ─────────────────────────────────────────────────
test("the Owner restores a retired file with a reason and an Idempotency-Key", async () => {
  await renderPageAs("Owner");
  await openRetiredTab();
  fireEvent.click(screen.getByTestId("restore-m-ret"));
  const confirm = screen.getByTestId("reason-confirm-restore-m-ret");
  expect(confirm.disabled).toBe(true);
  fireEvent.change(screen.getByTestId("reason-input-restore-m-ret"), { target: { value: "нужен за отчета" } });
  await act(async () => { fireEvent.click(confirm); });
  const [url, body, cfg] = mockPost.mock.calls[0];
  expect(url).toBe("/media/m-ret/restore");
  expect(body).toEqual({ reason: "нужен за отчета" });
  expect(cfg.headers["Idempotency-Key"]).toEqual(expect.any(String));
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/media-retired", { params: { skip: 0, limit: 50 } }));
});

test("the Admin sees the retired list without a restore button", async () => {
  await renderPageAs("Admin", { canRestore: false });
  await openRetiredTab();
  expect(screen.getByText("дубликат")).toBeTruthy();
  expect(screen.queryByTestId("restore-m-ret")).toBeNull();
});

test("no restore button when the server says can_restore=false, even for the Owner", async () => {
  await renderPageAs("Owner", { canRestore: false });
  await openRetiredTab();
  expect(screen.queryByTestId("restore-m-ret")).toBeNull();
});

test("a 403 from the server shows a clear message, not an empty list", async () => {
  mockAuth = { user: { id: "u-1", role: "Owner" }, loading: false };
  mockGet.mockRejectedValue({ response: { status: 403, data: { detail: "Access denied" } } });
  render(<MediaReviewPage />);
  expect((await screen.findByTestId("requests-error")).textContent).toMatch(/Нямате достъп/);
});

// ── FG-693: paging — no retired file is unreachable ──────────────────────
test("the retired list loads the next page with „Покажи още“ until all are shown", async () => {
  mockAuth = { user: { id: "u-1", role: "Owner" }, loading: false };
  const r = (i) => ({ ...RETIRED(true), id: `m-${i}`, filename: `f${i}.jpg` });
  mockGet.mockImplementation((url, cfg) => {
    if (url === "/media-retire-requests") return Promise.resolve(page([REQUEST]));
    if (url === "/media-retired") {
      const skip = cfg?.params?.skip || 0;
      return Promise.resolve(skip === 0 ? page([r(1), r(2)], 3, 2) : page([r(3)], 3, null));
    }
    return Promise.reject({ response: { status: 404 } });
  });
  render(<MediaReviewPage />);
  await screen.findByTestId("request-rq-1");
  await act(async () => { fireEvent.mouseDown(screen.getByTestId("tab-retired"), { button: 0 }); });
  await screen.findByTestId("retired-m-2");
  expect(screen.queryByTestId("retired-m-3")).toBeNull();
  expect(screen.getByTestId("retired-count").textContent).toBe("2 от 3");
  await act(async () => { fireEvent.click(screen.getByTestId("retired-more")); });
  await screen.findByTestId("retired-m-3");
  expect(mockGet).toHaveBeenCalledWith("/media-retired", { params: { skip: 2, limit: 50 } });
  expect(screen.queryByTestId("retired-more")).toBeNull();        // everything is shown
});

test("the request list is asked for page by page too", async () => {
  await renderPageAs("Admin");
  expect(mockGet).toHaveBeenCalledWith("/media-retire-requests",
    { params: { status: "pending", skip: 0, limit: 50 } });
  expect(screen.queryByTestId("requests-more")).toBeNull();
});

// ── the mirror stays equal to the backend policy ─────────────────────────
test("the role lists mirror backend/app/services/media_policy.py", () => {
  const py = fs.readFileSync(
    path.resolve(__dirname, "../../../../backend/app/services/media_policy.py"), "utf8");
  const roles = (name) => {
    const m = py.match(new RegExp(`^${name} = frozenset\\(\\{([^}]*)\\}\\)`, "m"));
    return m ? m[1].split(",").map((s) => s.trim().replace(/"/g, "")).filter(Boolean).sort() : null;
  };
  expect(roles("RETIRED_LIST_ROLES")).toEqual([...REVIEW_ROLES].sort());
  expect(roles("RETIRE_APPROVER_ROLES")).toEqual([...DECIDE_ROLES].sort());
  expect(roles("RESTORE_ROLES")).toEqual([...RESTORE_ROLES].sort());
});
