// LAB-02 (R33) — quantity approval and piece rates: who sees what, and small helpers.
// Mirrors the backend rules in backend/app/routes/labor_quantities.py:
//  - piece rates (акордни цени) are visible and editable for finance roles only (R31);
//  - quantities are approved by Admin / Owner / the project's SiteManager (the backend
//    checks the project membership and that the approver is not the worker).

export const FINANCE_ROLES = ["Owner", "Admin", "Accountant"];
export const APPROVER_ROLES = ["Owner", "Admin", "SiteManager"];

export const canSeePieceRates = (role) => FINANCE_ROLES.includes(role);
export const canApproveQuantities = (role) => APPROVER_ROLES.includes(role);

export const PAY_TYPE_LABELS = {
  Akord: "Акорд",
  Hourly: "Часова ставка",
  Daily: "Надница",
  Monthly: "Месечна заплата",
};

export const STATE_LABELS = {
  waiting: "Чака одобрение",
  approved: "Одобрено",
  no_quantity: "Няма количество",
};

export const COST_TYPE_LABELS = {
  LABOR: "Труд по СМР",
  DOWNTIME: "Престой",
  DOWNTIME_UNCLASSIFIED: "Неуточнен престой",
};

// R29: one key per request body; a retry of the same body reuses it.
export function newIdempotencyKey() {
  if (typeof window !== "undefined" && window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// A quantity entered by a person: finite and not negative, else null (nothing is sent).
export function parseQuantity(value) {
  if (value === "" || value === null || value === undefined) return null;
  const n = Number(String(value).replace(",", "."));
  return Number.isFinite(n) && n >= 0 ? n : null;
}

// "120 м2 × 5 = 600" for a finance user; the SiteManager never gets a price (R31).
export function akordFormula(quantity, unit, pieceRate) {
  const q = parseQuantity(quantity);
  const r = parseQuantity(pieceRate);
  if (q === null) return "";
  if (r === null) return `${q} ${unit || ""}`.trim();
  return `${q} ${unit || ""} × ${r} = ${Math.round(q * r * 100) / 100}`.replace(/\s+/g, " ");
}
