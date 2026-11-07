/**
 * One Idempotency-Key per money submission (CLAUDE.md §14; R29, Krum 06.11.2026).
 *
 * The server replays a request it already performed when the same key comes again
 * with the same body (no second payment), answers 409 when the same key comes with a
 * different body, and refuses a money write without a key (428 IDEMPOTENCY_KEY_REQUIRED).
 *
 * Two holders, one per caller style (both kept on the merge of #69 SEC-01-C03 and
 * #70 PAY-01-C01 Addendum B, which added this file independently):
 *   createIdempotencyHolder() — keyed by endpoint + payload (SEC-01-C03 forms): the same
 *                               payload reuses the key until done();
 *   createKeyHolder()         — one key per submission (PAY-01 finance pages): a network
 *                               error keeps it for the retry, any server answer drops it.
 */

export function newIdempotencyKey() {
  const c = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

/**
 * A key holder for one form: ``holder.keyFor(endpoint, payload)`` returns the same key
 * for the same endpoint + payload until ``holder.done()`` is called.
 */
export function createIdempotencyHolder() {
  let current = null;
  return {
    keyFor(endpoint, payload) {
      const fingerprint = `${endpoint}\u001f${JSON.stringify(payload ?? null)}`;
      if (!current || current.fingerprint !== fingerprint) {
        current = { fingerprint, key: newIdempotencyKey() };
      }
      return current.key;
    },
    done() {
      current = null;
    },
  };
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
