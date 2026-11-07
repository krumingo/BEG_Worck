// R29 (Krum, 06.11.2026; PAY-01-C01 Addendum B): every money write carries an
// Idempotency-Key. Without one the backend refuses it (428 IDEMPOTENCY_KEY_REQUIRED).
//
// One key per submitted form: a double click or a retry after a lost connection sends
// the SAME key, so the backend replays the first result instead of paying twice. Once the
// server has answered (success or a refusal), the next submit gets a fresh key.

export function newIdempotencyKey() {
  if (typeof window !== "undefined" && window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

export function createKeyHolder() {
  let key = null;
  return {
    // The key of the current submission (created on first use).
    get() {
      if (!key) key = newIdempotencyKey();
      return key;
    },
    // After a request: keep the key only when the server never answered (network error),
    // so the retry is recognised as the same request.
    settle(err) {
      if (!err || err.response) key = null;
    },
  };
}

export function idempotencyHeaders(key) {
  return { headers: { "Idempotency-Key": key } };
}

// The finance API answers with a string detail, or an object { error_code, message }.
export function apiErrorText(err, fallback) {
  const d = err?.response?.data?.detail;
  if (typeof d === "string" && d) return d;
  if (d && typeof d === "object" && !Array.isArray(d) && d.message) return d.message;
  return fallback;
}
