/**
 * LIVE-OPS-01 / TASK 5C — C12.8 regression gate (frontend).
 *
 * Previous implementation silently dropped ledger rows that lacked
 * `item_id` or `warehouse_id` using a `continue` inside a map/filter
 * chain. The user then saw a "success" with no visible failure.
 *
 * C12.8 — the three dialog handlers (issue, consume, return) must now
 * collect blocker reasons per line and surface them with `alert(...)`
 * before any canonical POST goes out.
 *
 * This is a pure source-level gate: it reads the committed React file
 * and asserts the shape, so it runs in the DB-free jest suite with no
 * live API dependency.
 */
import fs from "fs";
import path from "path";

const SRC_PATH = path.join(
  __dirname, "..", "ProjectMaterialLedger.js",
);
const SRC = fs.readFileSync(SRC_PATH, "utf-8");

describe("ProjectMaterialLedger — C12.8 no silent skips", () => {
  it("collects blockers in each of the three handlers", () => {
    const occurrences = (SRC.match(/const blockers = \[\];/g) || []).length;
    expect(occurrences).toBeGreaterThanOrEqual(3);
  });

  it("surfaces blockers via alert, not console.error or silent return", () => {
    // The exact pattern we require:
    expect(SRC).toMatch(/alert\(blockers\.join\("\\n"\)\)/);
    // The old silent-skip pattern must be gone:
    expect(SRC).not.toMatch(/\.filter\(Boolean\)/);
  });

  it("preserves item_id and warehouse_id when opening the dialogs", () => {
    expect(SRC).toMatch(/item_id:\s*m\.item_id/);
    expect(SRC).toMatch(/warehouse_id:\s*m\.warehouse_id/);
  });

  it("every blocker message names the row index in Bulgarian", () => {
    // Every blocker line must address "Ред N" so the user can act:
    const blockerLines = SRC.match(/blockers\.push\(`[^`]+`\)/g) || [];
    expect(blockerLines.length).toBeGreaterThanOrEqual(6);
    for (const line of blockerLines) {
      expect(line).toMatch(/Ред\s+\$\{i\s*\+\s*1\}/);
    }
  });
});
