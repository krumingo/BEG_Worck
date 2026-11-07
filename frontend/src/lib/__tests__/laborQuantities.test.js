import {
  akordFormula, canApproveQuantities, canSeePieceRates, newIdempotencyKey, parseQuantity,
} from "../laborQuantities";

describe("LAB-02 labor quantities helpers", () => {
  test("piece rates only for finance roles (R31)", () => {
    expect(canSeePieceRates("Owner")).toBe(true);
    expect(canSeePieceRates("Admin")).toBe(true);
    expect(canSeePieceRates("Accountant")).toBe(true);
    expect(canSeePieceRates("SiteManager")).toBe(false);
    expect(canSeePieceRates("Technician")).toBe(false);
  });

  test("approvers are Owner / Admin / SiteManager", () => {
    expect(canApproveQuantities("SiteManager")).toBe(true);
    expect(canApproveQuantities("Accountant")).toBe(false);
    expect(canApproveQuantities("Worker")).toBe(false);
  });

  test("quantities: finite and not negative, comma accepted", () => {
    expect(parseQuantity("120")).toBe(120);
    expect(parseQuantity("12,5")).toBe(12.5);
    expect(parseQuantity("-1")).toBe(null);
    expect(parseQuantity("abc")).toBe(null);
    expect(parseQuantity("")).toBe(null);
  });

  test("akord formula — 120 м2 × 5 = 600", () => {
    expect(akordFormula(120, "м2", 5)).toBe("120 м2 × 5 = 600");
    expect(akordFormula(120, "м2", null)).toBe("120 м2");
  });

  test("idempotency keys are unique", () => {
    expect(newIdempotencyKey()).not.toEqual(newIdempotencyKey());
  });
});
