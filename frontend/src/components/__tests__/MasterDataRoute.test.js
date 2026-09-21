/**
 * W0-03 — who reaches the Master Data review screen.
 *
 * The screen used to sit behind AdminRoute, which admits Admin, Owner,
 * SiteManager and Accountant: the office — the role FLOW-032 gives the mapping
 * to, and the only non-admin role that may approve and reject — was sent away,
 * while roles that may only read were let in as if they could decide. The
 * screen now has its own guard built from the canonical rights, and AdminRoute
 * itself is not widened.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, screen } from "@testing-library/react";

// react-router-dom 7 declares a "main" file it does not ship and jest 27 does
// not read "exports", so no test in this app can load the real router. The
// guard only uses <Navigate>; this stand-in records where it would send you.
jest.mock("react-router-dom", () => ({
  __esModule: true,
  Navigate: ({ to, replace }) => (
    <div data-testid="redirect" data-to={to} data-replace={String(Boolean(replace))} />
  ),
}), { virtual: true });

let mockAuth = { user: null, loading: false };
jest.mock("@/contexts/AuthContext", () => ({
  __esModule: true,
  useAuth: () => mockAuth,
}));
jest.mock("@/components/DashboardLayout", () => ({
  __esModule: true,
  default: ({ children }) => <div data-testid="app-shell">{children}</div>,
}));

import MasterDataRoute from "@/components/MasterDataRoute";

function visitAs(session) {
  mockAuth = session;
  render(<MasterDataRoute><div data-testid="md-screen" /></MasterDataRoute>);
}

const redirectedTo = () => {
  const r = screen.queryByTestId("redirect");
  return r ? [r.getAttribute("data-to"), r.getAttribute("data-replace")] : null;
};

const as = (role) => ({ user: { id: "u-1", role }, loading: false });

test("the office reaches the screen, inside the application shell", () => {
  visitAs(as("office"));
  expect(screen.getByTestId("app-shell")).toContainElement(screen.getByTestId("md-screen"));
  expect(redirectedTo()).toBeNull();
});

test.each(["Admin", "Owner", "admin", "owner"])("%s reaches the screen", (role) => {
  visitAs(as(role));
  expect(screen.getByTestId("md-screen")).toBeInTheDocument();
  expect(redirectedTo()).toBeNull();
});

test.each(["SiteManager", "Accountant", "site_manager", "accountant", "project_manager"])(
  "%s may read the queue, so it reaches the screen", (role) => {
    visitAs(as(role));
    expect(screen.getByTestId("md-screen")).toBeInTheDocument();
    expect(redirectedTo()).toBeNull();
  });

test.each(["Technician", "Viewer", "Driver", "Warehousekeeper", "Worker",
            "warehouse", "procurement", "worker", "driver", "ai_service",
            "", "constructor", "__proto__", null, undefined])(
  "a role without the right to read the queue (%p) is sent to /tech and never sees it", (role) => {
    visitAs(as(role));
    expect(redirectedTo()).toEqual(["/tech", "true"]);
    expect(screen.queryByTestId("md-screen")).not.toBeInTheDocument();
    expect(screen.queryByTestId("app-shell")).not.toBeInTheDocument();
  });

test("without a session the screen sends the visitor to the login", () => {
  visitAs({ user: null, loading: false });
  expect(redirectedTo()).toEqual(["/login", "true"]);
  expect(screen.queryByTestId("md-screen")).not.toBeInTheDocument();
});

test("while the session is loading, nothing of the screen is shown", () => {
  visitAs({ user: null, loading: true });
  expect(screen.getByTestId("md-route-loading")).toBeInTheDocument();
  expect(screen.queryByTestId("md-screen")).not.toBeInTheDocument();
});

test("App routes this screen through its own guard and leaves AdminRoute as it was", () => {
  const app = fs.readFileSync(path.join(__dirname, "..", "..", "App.js"), "utf8");
  expect(app).toMatch(/<Route path="\/data\/master-data" element=\{<MasterDataRoute><MasterDataReviewPage \/><\/MasterDataRoute>\} \/>/);
  expect(app).not.toMatch(/<AdminRoute><MasterDataReviewPage/);
  expect(app).toMatch(/const ADMIN_ROLES = \["Admin", "Owner", "SiteManager", "Accountant"\];/);
});
