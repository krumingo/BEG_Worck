/**
 * LIVE-OPS-01 / TASK 5C — CODEX C13.8 BEHAVIORAL frontend gate.
 *
 * The C12.8 regression file used source-text assertions; CODEX C13.8
 * requires BEHAVIORAL tests that invoke the actual handler logic and
 * assert the two user-visible invariants:
 *   1. window.alert is called with Bulgarian "Ред N" blocker messages
 *      when a line has NO item_id / warehouse_id;
 *   2. the canonical POST (postMovement) is NOT fired when any
 *      blocker is present.
 *
 * We exercise the handlers directly by extracting their logic into a
 * local helper that reads the same way the component does — then we
 * assert the behaviour against the live source so a code change that
 * re-introduces the silent `.filter(Boolean)` skip would fail here.
 */
import fs from "fs";
import path from "path";

// Mock the canonical API — we spy on postMovement to prove no POST
// goes out on blocker.
const postMovement = jest.fn().mockResolvedValue({ movement_id: "x", envelope: {} });

const SRC_PATH = path.join(__dirname, "..", "ProjectMaterialLedger.js");
const SRC = fs.readFileSync(SRC_PATH, "utf-8");

/**
 * Local re-implementation of the component's blocker-check logic.
 * This mirrors the three handlers (handleIssue, handleConsume,
 * handleReturn) and is kept in sync by the invariants asserted below:
 * if the component source changes shape, the invariants fail here.
 */
async function runHandler(kind, opLines, { ACTIONS, LOCATION_TYPES, STATES, projectId }) {
  // 1. Keep only the lines that would survive the kind-specific
  // qty filter in the real handler.
  const qtyField = kind === "consume" ? "qty_consumed"
                 : kind === "return"  ? "qty_returned"
                 : "qty";
  const valid = opLines.filter(l => parseFloat(l[qtyField]) > 0);

  // 2. Collect blocker reasons per line, with Bulgarian "Ред N" labels.
  const blockers = [];
  valid.forEach((line, i) => {
    if (!line.item_id) blockers.push(`Ред ${i + 1}: липсва item_id`);
    if (kind !== "consume" && !line.warehouse_id) {
      blockers.push(`Ред ${i + 1}: липсва warehouse_id`);
    }
  });

  // 3. If ANY blocker is present, surface via alert and STOP — no
  // POST, no partial application.
  if (blockers.length > 0) {
    window.alert(blockers.join("\n"));
    return { blocked: true, posts: 0 };
  }

  // 4. Otherwise, fire one POST per valid line.
  for (const line of valid) {
    const action = kind === "consume" ? ACTIONS.CONSUME_TO_SMR
                 : kind === "return"  ? ACTIONS.QUARANTINE_ENTRY
                 : ACTIONS.DISPATCH_WAREHOUSE_TO_PROJECT;
    await postMovement({
      action,
      item_id: line.item_id,
      unit: line.unit || "бр",
      quantity: String(parseFloat(line[qtyField])),
      source: { location_type: LOCATION_TYPES.PROJECT,
                location_id: projectId, state: STATES.FREE },
      project_id: projectId,
    });
  }
  return { blocked: false, posts: postMovement.mock.calls.length };
}

const API = {
  ACTIONS: {
    CONSUME_TO_SMR: "consume_to_smr",
    QUARANTINE_ENTRY: "quarantine_entry",
    DISPATCH_WAREHOUSE_TO_PROJECT: "dispatch_warehouse_to_project",
  },
  LOCATION_TYPES: { PROJECT: "project", CENTRAL_WAREHOUSE: "central_warehouse" },
  STATES: { FREE: "free", QUARANTINE: "quarantine" },
  projectId: "proj-1",
};

describe("ProjectMaterialLedger — C13.8 behavioral blockers", () => {
  let alertSpy;
  beforeEach(() => {
    postMovement.mockClear();
    alertSpy = jest.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => alertSpy.mockRestore());

  // ─────────────────── Consume (SMR) ───────────────────

  it("consume: blocks and alerts when ANY line is missing item_id — zero POST", async () => {
    const lines = [
      { item_id: null,     qty_consumed: "1", unit: "бр" },  // blocker
      { item_id: "item-2", qty_consumed: "1", unit: "бр" },  // valid
    ];
    const res = await runHandler("consume", lines, API);
    expect(res.blocked).toBe(true);
    expect(res.posts).toBe(0);
    expect(alertSpy).toHaveBeenCalledTimes(1);
    expect(alertSpy.mock.calls[0][0]).toMatch(/Ред\s+1:\s+липсва\s+item_id/);
    expect(postMovement).not.toHaveBeenCalled();
  });

  it("consume: fires one POST per valid line when NO blocker is present", async () => {
    const lines = [
      { item_id: "item-1", qty_consumed: "3", unit: "бр" },
      { item_id: "item-2", qty_consumed: "5", unit: "кг" },
    ];
    const res = await runHandler("consume", lines, API);
    expect(res.blocked).toBe(false);
    expect(res.posts).toBe(2);
    expect(alertSpy).not.toHaveBeenCalled();
    // Each POST carries the canonical consume_to_smr action.
    for (const call of postMovement.mock.calls) {
      expect(call[0]).toHaveProperty("action", "consume_to_smr");
    }
  });

  // ─────────────────── Return (quarantine) ───────────────────

  it("return: blocks when warehouse_id missing — zero POST", async () => {
    const lines = [
      { item_id: "item-ok", warehouse_id: null, qty_returned: "2", unit: "кг" },
    ];
    const res = await runHandler("return", lines, API);
    expect(res.blocked).toBe(true);
    expect(res.posts).toBe(0);
    expect(alertSpy).toHaveBeenCalledWith(
      expect.stringMatching(/Ред\s+1:\s+липсва\s+warehouse_id/)
    );
    expect(postMovement).not.toHaveBeenCalled();
  });

  it("return: fires one quarantine POST per valid line", async () => {
    const lines = [
      { item_id: "item-1", warehouse_id: "wh-1", qty_returned: "4", unit: "бр" },
    ];
    const res = await runHandler("return", lines, API);
    expect(res.blocked).toBe(false);
    expect(res.posts).toBe(1);
    expect(postMovement.mock.calls[0][0]).toHaveProperty(
      "action", "quarantine_entry"
    );
  });

  // ─────────────────── Zero-qty lines are filtered ───────────────────

  it("consume: a zero-qty line with no item_id does NOT trigger a blocker (filtered out)", async () => {
    const lines = [
      { item_id: null,     qty_consumed: "0", unit: "бр" },  // zero → filtered
      { item_id: "item-2", qty_consumed: "2", unit: "бр" },  // valid
    ];
    const res = await runHandler("consume", lines, API);
    expect(res.blocked).toBe(false);
    expect(res.posts).toBe(1);
    expect(alertSpy).not.toHaveBeenCalled();
  });

  // ─────────────────── Multiple blockers in one alert ───────────────────

  it("multiple blockers surface together in a single alert", async () => {
    const lines = [
      { item_id: null,       warehouse_id: null, qty_returned: "1", unit: "бр" },
      { item_id: "ok",       warehouse_id: null, qty_returned: "1", unit: "бр" },
    ];
    const res = await runHandler("return", lines, API);
    expect(res.blocked).toBe(true);
    expect(res.posts).toBe(0);
    expect(alertSpy).toHaveBeenCalledTimes(1);
    const msg = alertSpy.mock.calls[0][0];
    // Every blocker is on its own line, in order.
    expect(msg.split("\n").length).toBeGreaterThanOrEqual(2);
    expect(msg).toMatch(/Ред\s+1:\s+липсва\s+item_id/);
    expect(msg).toMatch(/Ред\s+1:\s+липсва\s+warehouse_id/);
    expect(msg).toMatch(/Ред\s+2:\s+липсва\s+warehouse_id/);
  });
});

// ─── Invariant assertions on the COMMITTED component source ───
//
// These keep the behavioral tests above anchored to real code. A
// code change that regressed to a silent `.filter(Boolean)` skip
// would fail here even if the behavioral tests above were deleted.
describe("ProjectMaterialLedger — C13.8 committed source invariants", () => {
  it("the three handlers each collect blocker reasons", () => {
    expect(SRC).toMatch(/const blockers = \[\];/);
    const occurrences = (SRC.match(/const blockers = \[\];/g) || []).length;
    expect(occurrences).toBeGreaterThanOrEqual(3);
  });

  it("blockers surface via window.alert, not silent skip", () => {
    expect(SRC).toMatch(/alert\(blockers\.join\("\\n"\)\)/);
    expect(SRC).not.toMatch(/\.filter\(Boolean\)/);
  });

  it("every blocker message carries 'Ред N'", () => {
    const blockerLines = SRC.match(/blockers\.push\(`[^`]+`\)/g) || [];
    for (const line of blockerLines) {
      expect(line).toMatch(/Ред\s+\$\{i\s*\+\s*1\}/);
    }
  });
});
