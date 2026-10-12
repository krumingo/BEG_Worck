/**
 * Thin client for the canonical warehouse / stock core (LIVE-OPS-01 TASK 5C).
 *
 * All reads and writes go through this file so the UI never dials a legacy
 * writer by hand. Writing a legacy endpoint from the UI is a bug — the
 * server now answers those with HTTP 410 Gone.
 */
import API from "@/lib/api";

const BASE = "/warehouse/canonical";

const ACTIONS = Object.freeze({
  RECEIVE_FROM_SUPPLIER: "receive_from_supplier",
  RECEIVE_FROM_SUPPLIER_TO_PROJECT: "receive_from_supplier_to_project",
  RESERVE: "reserve",
  RELEASE_RESERVATION: "release_reservation",
  DISPATCH_WAREHOUSE_TO_PROJECT: "dispatch_warehouse_to_project",
  ACCEPT_PROJECT_DELIVERY: "accept_project_delivery",
  TRANSFER_PROJECT_TO_WAREHOUSE: "transfer_project_to_warehouse",
  TRANSFER_PROJECT_TO_PROJECT: "transfer_project_to_project",
  TRANSFER_WAREHOUSE_TO_WAREHOUSE: "transfer_warehouse_to_warehouse",
  CONSUME_TO_SMR: "consume_to_smr",
  RETURN_TO_SUPPLIER: "return_to_supplier",
  WRITE_OFF: "write_off",
  REVISION_ADJUSTMENT: "revision_adjustment",
  QUARANTINE_ENTRY: "quarantine_entry",
  QUARANTINE_RELEASE: "quarantine_release",
});

const LOCATION_TYPES = Object.freeze({
  CENTRAL_WAREHOUSE: "central_warehouse",
  SMALL_WAREHOUSE: "small_warehouse",
  PROJECT: "project",
  SUBPROJECT: "subproject",
  PERSON: "person",
  VEHICLE: "vehicle",
  SUPPLIER: "supplier",
  IN_TRANSIT: "in_transit",
  UNRESOLVED: "unresolved",
});

const STATES = Object.freeze({
  FREE: "free",
  RESERVED: "reserved",
  QUARANTINE: "quarantine",
  IN_TRANSIT: "in_transit",
  UNRESOLVED: "unresolved",
});

function freshIdempotencyKey(action) {
  const rand = (crypto?.randomUUID?.() ?? Math.random().toString(16).slice(2));
  return `${action}-${Date.now()}-${rand}`;
}

async function postMovement(payload) {
  // Permission-aware named action. Permission denial renders as 403 with a
  // reason code the UI can show the user ("you can accept deliveries on
  // this project, but not consume on SMR").
  const body = { idempotency_key: freshIdempotencyKey(payload.action), ...payload };
  const { data } = await API.post(`${BASE}/movements`, body);
  return data;
}

async function readStock({ itemId, locationType, locationId, state = STATES.FREE }) {
  const { data } = await API.get(`${BASE}/stock/${encodeURIComponent(itemId)}`, {
    params: { location_type: locationType, location_id: locationId, state },
  });
  return data;
}

async function readBalance({ itemId }) {
  const { data } = await API.get(`${BASE}/balance/${encodeURIComponent(itemId)}`);
  return data;
}

async function readHistory({ itemId, projectId, locationType, locationId,
                             since, until, limit = 50, cursorAfter } = {}) {
  const { data } = await API.get(`${BASE}/history`, {
    params: {
      item_id: itemId, project_id: projectId,
      location_type: locationType, location_id: locationId,
      since, until, limit, cursor_after: cursorAfter,
    },
  });
  return data;
}

async function readIntegrityWarnings() {
  const { data } = await API.get(`${BASE}/integrity-warnings`);
  return data;
}

async function readMigrationReadiness(scope) {
  const map = {
    "free-text-to-item": "free-text-to-item",
    "main-to-central": "main-to-central",
    "legacy-writer-inventory": "legacy-writer-inventory",
    "ledger-batch-reconciliation": "ledger-batch-reconciliation",
  };
  const path = map[scope];
  if (!path) throw new Error(`unknown readiness scope: ${scope}`);
  const { data } = await API.get(`/warehouse/migration-readiness/${path}`);
  return data;
}

export {
  ACTIONS, LOCATION_TYPES, STATES,
  postMovement, readStock, readBalance, readHistory,
  readIntegrityWarnings, readMigrationReadiness,
};
