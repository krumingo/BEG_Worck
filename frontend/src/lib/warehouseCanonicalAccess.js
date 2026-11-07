/**
 * Who may see and act on the canonical warehouse screen (/warehouse/canonical).
 * 5C-C19 F-6.
 *
 * The backend decides: every request is authorized server-side by the
 * Permission Service against the canonical catalog
 * (backend/app/permissions/catalog.py). This mirror only keeps the UI honest:
 *   - a role is let onto the screen when it may read stock or history;
 *   - the "Движения" (write) tab and each action in its picker are shown only
 *     for the canonical actions the role holds.
 * So a read-only Accountant never sees a write form, and a Warehousekeeper
 * (who may receive / dispatch / accept) gets the screen instead of /tech.
 *
 * warehouseCanonicalAccess.json is a copy of the catalog for exactly these
 * actions; a backend test fails when the two drift apart. Same pattern as
 * masterDataAccess.js.
 */
import access from "./warehouseCanonicalAccess.json";

export const WH_READ_STOCK = "warehouse.read_stock";
export const WH_READ_HISTORY = "warehouse.read_history";
export const WH_WRITE_COMMAND = "warehouse.write_command";

/** Canonical action → Permission Service action — the JSON's copy of backend
 * `actions.py::PERMISSION_ACTION` (the same backend test pins it). Its order
 * is the order the action picker shows. */
export const PERMISSION_FOR_ACTION = Object.freeze({ ...access.permission_for_action });

const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

/** The screen's permission actions a session role holds. Sessions carry the
 * legacy role strings (Admin, Warehousekeeper, …); a canonical role id is used
 * as it is — the same translation the backend applies. */
export function warehouseActions(role) {
  if (!role || typeof role !== "string") return new Set();
  const canonical = own(access.legacy_role_map, role) ? access.legacy_role_map[role] : role;
  return new Set(own(access.role_actions, canonical) ? access.role_actions[canonical] : []);
}

export const canReadWarehouseStock = (role) => warehouseActions(role).has(WH_READ_STOCK);
export const canReadWarehouseHistory = (role) => warehouseActions(role).has(WH_READ_HISTORY);
export const canOpenCanonicalWarehouse = (role) =>
  canReadWarehouseStock(role) || canReadWarehouseHistory(role);

/** Canonical actions this role may post, in picker order.
 * Needs both the outer route gate and the per-action right. */
export function allowedCommandActions(role) {
  const held = warehouseActions(role);
  if (!held.has(WH_WRITE_COMMAND)) return [];
  return Object.keys(PERMISSION_FOR_ACTION).filter((a) => held.has(PERMISSION_FOR_ACTION[a]));
}

export const canWriteWarehouse = (role) => allowedCommandActions(role).length > 0;
