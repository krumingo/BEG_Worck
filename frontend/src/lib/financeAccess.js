/**
 * SEC-02 (R20, Krum 06.11.2026) — who sees money in the UI.
 *
 * The backend decides: every finance read is authorized server-side
 * (backend/app/permissions/finance_read.py). This mirror only keeps the UI honest:
 * finance menus, pages and widgets are shown to the roles that can read them, so
 * nobody gets an empty screen with zeros or a 403.
 *
 *   FINANCE_ROLES        company finance and project money (R20 rules 1-2):
 *                        Owner / Admin / Accountant.
 *   BUDGET_VIEW_ROLES    the project budget view (budget + spent + remaining per SMR,
 *                        R20-2B): the finance roles and the Technical Manager
 *                        (SiteManager), the latter only on projects he is a member of —
 *                        the backend checks the membership.
 *
 *   PEOPLE_VIEW_ROLES    FIX-PERM-01 (Р98, Krum 16.11.2026): the people screens
 *                        ("Служители", "Служител", "Календар на работниците") —
 *                        the finance roles with money, the Technical Manager
 *                        (SiteManager) WITHOUT money (no rates, salaries, advances,
 *                        overhead). Mirror of backend/app/permissions/people_read.py
 *                        PEOPLE_READ_ROLES; the money part is FINANCE_ROLES above.
 *
 * A backend test (tests/test_sec_02_finance_read.py; tests/test_fix_perm_01_people_read.py
 * for PEOPLE_VIEW_ROLES) fails when these lists drift from the backend.
 */
export const FINANCE_ROLES = ["Admin", "Owner", "Accountant"];
export const BUDGET_VIEW_ROLES = ["Admin", "Owner", "Accountant", "SiteManager"];
export const PEOPLE_VIEW_ROLES = ["Admin", "Owner", "Accountant", "SiteManager"];

export function canReadFinance(role) {
  return FINANCE_ROLES.includes(role);
}

export function canReadBudgetView(role) {
  return BUDGET_VIEW_ROLES.includes(role);
}

export function canReadPeople(role) {
  return PEOPLE_VIEW_ROLES.includes(role);
}
