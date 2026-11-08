// R29 (PAY-01-C01 Addendum B; SEC-01-C03): every money write carries an Idempotency-Key.
import {
  apiErrorText, createIdempotencyHolder, createKeyHolder, idempotencyHeaders, newIdempotencyKey,
} from "../idempotency";

describe("idempotency keys (createKeyHolder, #70)", () => {
  test("a new key is non-empty and unique", () => {
    const a = newIdempotencyKey();
    const b = newIdempotencyKey();
    expect(a).toBeTruthy();
    expect(a).not.toEqual(b);
  });

  test("one key per submission: a double click reuses it", () => {
    const h = createKeyHolder();
    expect(h.get()).toEqual(h.get());
  });

  test("a network error (no response) keeps the key for the retry", () => {
    const h = createKeyHolder();
    const k = h.get();
    h.settle(new Error("Network Error"));
    expect(h.get()).toEqual(k);
  });

  test("once the server answered, the next submission gets a fresh key", () => {
    const h = createKeyHolder();
    const k1 = h.get();
    h.settle();                                   // success
    const k2 = h.get();
    expect(k2).not.toEqual(k1);
    h.settle({ response: { status: 400 } });      // a refusal
    expect(h.get()).not.toEqual(k2);
  });

  test("the header is named Idempotency-Key", () => {
    expect(idempotencyHeaders("abc")).toEqual({ headers: { "Idempotency-Key": "abc" } });
  });

  test("error text handles string and object details", () => {
    expect(apiErrorText({ response: { data: { detail: "Сумата" } } }, "x")).toEqual("Сумата");
    expect(apiErrorText({ response: { data: { detail: { error_code: "E", message: "Съобщение" } } } }, "x"))
      .toEqual("Съобщение");
    expect(apiErrorText({ response: { data: { detail: [{ msg: "pydantic" }] } } }, "fallback")).toEqual("fallback");
    expect(apiErrorText(new Error("Network Error"), "fallback")).toEqual("fallback");
  });
});

describe("idempotency keys per payload (createIdempotencyHolder, SEC-01-C03)", () => {
  test("a retry of the same submission reuses the key", () => {
    const h = createIdempotencyHolder();
    const k1 = h.keyFor("/subcontractor-payments", { amount: 10, package_id: "p" });
    const k2 = h.keyFor("/subcontractor-payments", { amount: 10, package_id: "p" });
    expect(k2).toBe(k1);
  });

  test("a changed payload or another endpoint gets a new key", () => {
    const h = createIdempotencyHolder();
    const k1 = h.keyFor("/subcontractor-payments", { amount: 10 });
    expect(h.keyFor("/subcontractor-payments", { amount: 11 })).not.toBe(k1);
    expect(h.keyFor("/overhead-snapshots", { amount: 11 })).not.toBe(k1);
  });

  test("after a success the next submission is a new operation", () => {
    const h = createIdempotencyHolder();
    const k1 = h.keyFor("/x", { amount: 1 });
    h.done();
    expect(h.keyFor("/x", { amount: 1 })).not.toBe(k1);
  });
});
