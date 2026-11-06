/**
 * SEC-01-C03: a money form keeps one Idempotency-Key while its payload stays the same.
 */
import { createIdempotencyHolder, idempotencyHeaders, newIdempotencyKey } from "@/lib/idempotency";

test("a retry of the same submission reuses the key", () => {
  const h = createIdempotencyHolder();
  const k1 = h.keyFor("/subcontractor-payments", { amount: "10", package_id: "p" });
  const k2 = h.keyFor("/subcontractor-payments", { amount: "10", package_id: "p" });
  expect(k2).toBe(k1);
});

test("a changed payload or another endpoint gets a new key", () => {
  const h = createIdempotencyHolder();
  const k1 = h.keyFor("/subcontractor-payments", { amount: "10" });
  expect(h.keyFor("/subcontractor-payments", { amount: "11" })).not.toBe(k1);
  expect(h.keyFor("/overhead-snapshots", { amount: "11" })).not.toBe(k1);
});

test("after a success the next submission is a new operation", () => {
  const h = createIdempotencyHolder();
  const k1 = h.keyFor("/x", { amount: 1 });
  h.done();
  expect(h.keyFor("/x", { amount: 1 })).not.toBe(k1);
});

test("keys are distinct and the header has the canonical name", () => {
  expect(newIdempotencyKey()).not.toBe(newIdempotencyKey());
  expect(idempotencyHeaders("abc")).toEqual({ headers: { "Idempotency-Key": "abc" } });
});
