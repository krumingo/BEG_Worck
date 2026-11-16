// LAB-AKORD-01 (FLOW-028, Р100) — акордно количество по реда от „Отчет на труда“.
// Mirrors backend/app/services/labor_quantity_service.py:
//  - quantity: entered by the worker for himself, Technician / SiteManager of the object, office;
//  - approve / reject: Admin, Owner or the SiteManager of the object — never the worker nor the
//    person who entered the quantity (four-eyes, checked by the server);
//  - the unit labor price (единична цена труд) is visible / editable for finance roles only (R31).

export const FINANCE_ROLES = ["Owner", "Admin", "Accountant"];
export const APPROVER_ROLES = ["Owner", "Admin", "SiteManager"];

export const canSetPrice = (role) => FINANCE_ROLES.includes(role);
export const canApproveRole = (role) => APPROVER_ROLES.includes(role);

export const STATE_LABELS = {
  no_quantity: "Няма количество",
  pending: "Чака одобрение",
  approved: "Одобрено",
  rejected: "Отказано",
};

export const RECORD_LABELS = {
  pending: "чака",
  approved: "одобрено",
  rejected: "отказано",
  superseded: "заменено",
};

// A quantity / price typed by a person: finite and > 0, else null (nothing is sent).
export function parsePositive(value) {
  if (value === "" || value === null || value === undefined) return null;
  const n = Number(String(value).replace(",", "."));
  return Number.isFinite(n) && n > 0 ? n : null;
}

// "20 m2 × 12 = 240 EUR" for finance roles; without a price only "20 m2".
export function akordFormula(quantity, unit, pieceRate) {
  const q = parsePositive(quantity);
  if (q === null) return "";
  const u = unit ? ` ${unit}` : "";
  const r = parsePositive(pieceRate);
  if (r === null) return `${q}${u}`;
  return `${q}${u} × ${r} = ${Math.round(q * r * 100) / 100} EUR`;
}
