// SEC-02 (R20): the UI mirror of who reads money. The backend test
// tests/test_sec_02_finance_read.py checks the same lists against the catalog.
import { canReadFinance, canReadBudgetView, FINANCE_ROLES, BUDGET_VIEW_ROLES } from "@/lib/financeAccess";

test("finance roles", () => {
  expect(FINANCE_ROLES.sort()).toEqual(["Accountant", "Admin", "Owner"]);
  for (const r of ["Admin", "Owner", "Accountant"]) expect(canReadFinance(r)).toBe(true);
  for (const r of ["SiteManager", "Technician", "Viewer", "Driver", "Warehousekeeper", undefined]) {
    expect(canReadFinance(r)).toBe(false);
  }
});

test("the budget view adds only the Technical Manager", () => {
  expect(BUDGET_VIEW_ROLES.filter((r) => !FINANCE_ROLES.includes(r))).toEqual(["SiteManager"]);
  expect(canReadBudgetView("SiteManager")).toBe(true);
  for (const r of ["Technician", "Viewer", "Driver", "Warehousekeeper"]) expect(canReadBudgetView(r)).toBe(false);
});
