/**
 * Who may see and act on the Master Data review screen (/data/master-data).
 *
 * The backend decides: every request is authorized server-side against the
 * canonical catalog (backend/app/permissions/catalog.py), so nothing here can
 * grant anything. This mirror only keeps the UI honest — a role is let onto the
 * screen when it may read the queue, and sees the approve / reject controls only
 * when it holds those rights. It is deliberately narrow: it does not touch the
 * global AdminRoute.
 *
 * masterDataAccess.json is a copy of the catalog for exactly these actions; a
 * backend test fails when the two drift apart.
 */
import access from "./masterDataAccess.json";

export const MD_READ = "master_data.pending.read";
export const MD_APPROVE = "master_data.pending.approve";
export const MD_REJECT = "master_data.pending.reject";

const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

/** The screen's actions a session role holds. Sessions still carry the legacy
 * role strings (Admin, SiteManager, …); a canonical role id (e.g. "office")
 * is used as it is — the same translation the backend applies. */
export function masterDataActions(role) {
  if (!role || typeof role !== "string") return new Set();
  const canonical = own(access.legacy_role_map, role) ? access.legacy_role_map[role] : role;
  return new Set(own(access.role_actions, canonical) ? access.role_actions[canonical] : []);
}

export const canReadMasterData = (role) => masterDataActions(role).has(MD_READ);
export const canApproveMasterData = (role) => masterDataActions(role).has(MD_APPROVE);
export const canRejectMasterData = (role) => masterDataActions(role).has(MD_REJECT);
