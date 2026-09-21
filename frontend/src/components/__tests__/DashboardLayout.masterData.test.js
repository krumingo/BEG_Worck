/**
 * The office does not get the grouped admin navigation, so without its own
 * entry it could reach the Master Data screen only by typing the URL. The
 * sidebar now shows the entry to any non-admin role that may read the queue —
 * and to nobody else.
 */
import React from "react";
import { render, screen } from "@testing-library/react";

// See MasterDataRoute.test.js: jest 27 cannot load react-router-dom 7. The
// layout only needs links, the current path and a navigate function.
let mockPath = "/tech";
jest.mock("react-router-dom", () => ({
  __esModule: true,
  NavLink: ({ to, children, className, end, ...rest }) => (
    <a href={to} {...rest}>{typeof children === "function" ? children({ isActive: false }) : children}</a>
  ),
  useLocation: () => ({ pathname: mockPath }),
  useNavigate: () => () => {},
}), { virtual: true });

let mockRole = "office";
jest.mock("@/contexts/AuthContext", () => ({
  __esModule: true,
  useAuth: () => ({ user: { id: "u-1", role: mockRole, first_name: "A", last_name: "B" }, org: null, logout: jest.fn() }),
}));
jest.mock("@/contexts/ProjectContext", () => ({
  __esModule: true,
  useActiveProject: () => ({ activeProject: null, clearActiveProject: jest.fn() }),
}));
jest.mock("react-i18next", () => ({ __esModule: true, useTranslation: () => ({ t: (key) => key }) }));
jest.mock("@/components/NotificationBell", () => ({ __esModule: true, default: () => null }));
jest.mock("@/components/LanguageSwitcher", () => ({ __esModule: true, default: () => null }));
jest.mock("@/components/ChangePasswordModal", () => ({ __esModule: true, default: () => null }));

import DashboardLayout from "@/components/DashboardLayout";

function renderAs(role, at = "/tech") {
  mockRole = role;
  mockPath = at;
  render(<DashboardLayout><div /></DashboardLayout>);
  return screen.getByTestId("sidebar-nav");
}

test("the office finds the Master Data screen in its sidebar", () => {
  const nav = renderAs("office");
  expect(nav.querySelector('a[href="/data/master-data"]')).not.toBeNull();
});

test.each(["Technician", "Driver", "Viewer", "Warehousekeeper"])(
  "%s, who may not read the queue, gets no Master Data entry", (role) => {
    const nav = renderAs(role);
    expect(nav.querySelector('a[href="/data/master-data"]')).toBeNull();
  });

test.each(["Admin", "SiteManager"])("%s keeps finding it in the grouped admin navigation", (role) => {
  const nav = renderAs(role, "/data/master-data");  // the group opens on its own page
  expect(nav.querySelector('a[href="/data/master-data"]')).not.toBeNull();
});
