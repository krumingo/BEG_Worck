// R29 (PAY-01-C01 Addendum B): every money write carries an Idempotency-Key.
import { apiErrorText, createKeyHolder, idempotencyHeaders, newIdempotencyKey } from "../idempotency";

describe("idempotency keys", () => {
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
