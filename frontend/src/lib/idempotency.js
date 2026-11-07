/**
 * SEC-01-C03 — one Idempotency-Key per money submission (CLAUDE.md §14).
 *
 * The server replays a request it already performed when the same key comes again
 * with the same body (no second payment), and answers 409 when the same key comes
 * with a different body. So a form keeps ONE key while its payload stays the same —
 * a retry after a timeout or a double click reuses it — and takes a new key as soon
 * as the payload changes or the submission succeeded.
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

export function idempotencyHeaders(key) {
  return { headers: { "Idempotency-Key": key } };
}
