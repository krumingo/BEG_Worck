/**
 * SEC-02 (R20): the finance menus are for Owner/Admin/Accountant only. The Technical
 * Manager (SiteManager) keeps the grouped admin navigation but no finance entry, so he
 * never lands on an empty screen the backend refuses (backend/app/permissions/finance_read.py).
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

function renderAs(role, at) {
  mockRole = role;
  mockPath = at;
  render(<DashboardLayout><div /></DashboardLayout>);
  return screen.getByTestId("sidebar-nav");
}

const FINANCE_LINKS = [
  ["/finance", "/finance"], ["/pay-runs", "/pay-runs"], ["/overhead", "/overhead"],
  ["/reports/finance-details", "/reports/finance-details"],
  ["/data/prices", "/data/prices"], ["/data/turnover", "/data/turnover"], ["/pricing", "/pricing"],
];

test.each(["Admin", "Owner", "Accountant"])("%s sees the finance menus", (role) => {
  for (const [at, href] of FINANCE_LINKS) {
    const nav = renderAs(role, at);
    expect(nav.querySelector(`a[href="${href}"]`)).not.toBeNull();
    document.body.innerHTML = "";
  }
});

test("SiteManager keeps the admin navigation but gets no finance entry", () => {
  for (const [at, href] of FINANCE_LINKS) {
    const nav = renderAs("SiteManager", at);
    expect(nav.querySelector(`a[href="${href}"]`)).toBeNull();
    document.body.innerHTML = "";
  }
  const nav = renderAs("SiteManager", "/projects");
  expect(nav.querySelector('a[href="/projects"]')).not.toBeNull();
  expect(nav.querySelector('a[href="/all-reports"]')).toBeNull();   // group closed here
});
