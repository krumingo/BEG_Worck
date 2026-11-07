/**
 * 5C-C19 F-6 — who reaches /warehouse/canonical.
 *
 * The screen used to sit behind AdminRoute: the Warehousekeeper (allowed to
 * receive / dispatch / accept on the API) was sent to /tech. The guard now
 * follows the canonical catalog (read_stock or read_history).
 */
import React from "react";
import { render, screen } from "@testing-library/react";

jest.mock("react-router-dom", () => ({
  __esModule: true,
  Navigate: ({ to }) => <div data-testid="redirect" data-to={to} />,
}), { virtual: true });

let mockAuth = { user: null, loading: false };
jest.mock("@/contexts/AuthContext", () => ({ __esModule: true, useAuth: () => mockAuth }));
jest.mock("@/components/DashboardLayout", () => ({
  __esModule: true,
  default: ({ children }) => <div data-testid="app-shell">{children}</div>,
}));

import CanonicalWarehouseRoute from "@/components/CanonicalWarehouseRoute";

function visitAs(session) {
  mockAuth = session;
  render(<CanonicalWarehouseRoute><div data-testid="wh-screen" /></CanonicalWarehouseRoute>);
}
const as = (role) => ({ user: { id: "u", role }, loading: false });
const redirect = () => screen.queryByTestId("redirect")?.getAttribute("data-to") ?? null;

// 5C-C26j — Р35: the Technician reads the central warehouse and its projects'
// price history, so it now reaches the screen (with only those two tabs).
test.each(["Warehousekeeper", "Owner", "Admin", "SiteManager", "Accountant", "procurement",
           "Technician"])(
  "%s reaches the screen inside the shell", (role) => {
    visitAs(as(role));
    expect(screen.getByTestId("wh-screen")).toBeInTheDocument();
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(redirect()).toBeNull();
  });

test.each(["Viewer", "Driver", "worker"])("%s is sent to /tech", (role) => {
  visitAs(as(role));
  expect(redirect()).toBe("/tech");
  expect(screen.queryByTestId("wh-screen")).toBeNull();
});

test("no session → /login; loading → spinner only", () => {
  visitAs({ user: null, loading: false });
  expect(redirect()).toBe("/login");
  document.body.innerHTML = "";
  visitAs({ user: null, loading: true });
  expect(screen.getByTestId("wh-route-loading")).toBeInTheDocument();
  expect(screen.queryByTestId("wh-screen")).toBeNull();
});
