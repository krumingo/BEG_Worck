/**
 * The screen-side mirror of the canonical rights (backend/app/permissions/
 * catalog.py). The backend decides every request; these tests pin what the UI
 * shows. A backend test keeps masterDataAccess.json equal to the catalog.
 */
import {
  canApproveMasterData, canReadMasterData, canRejectMasterData, masterDataActions,
} from "@/lib/masterDataAccess";

const rights = (role) => [canReadMasterData(role), canApproveMasterData(role), canRejectMasterData(role)];

test.each([
  // role            read   approve reject
  ["office",         true,  true,   true],
  ["Owner",          true,  true,   true],
  ["Admin",          true,  true,   true],
  ["owner",          true,  true,   true],
  ["admin",          true,  true,   true],
  ["SiteManager",    true,  false,  false],
  ["Accountant",     true,  false,  false],
  ["project_manager", true, false,  false],
  ["Technician",     false, false,  false],
  ["Viewer",         false, false,  false],
  ["Driver",         false, false,  false],
  ["Warehousekeeper", false, false, false],
  ["procurement",    false, false,  false],
  ["worker",         false, false,  false],
  ["ai_service",     false, false,  false],
])("%s: read=%s approve=%s reject=%s", (role, read, approve, reject) => {
  expect(rights(role)).toEqual([read, approve, reject]);
});

test.each([null, undefined, "", 42, {}, "constructor", "__proto__", "toString", "Office", "OFFICE"])(
  "an unknown or malformed role (%p) gets nothing", (role) => {
    expect(masterDataActions(role).size).toBe(0);
  });
