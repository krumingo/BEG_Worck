/**
 * MEDIA-SEC-01 — the existing media review APIs (no new rules):
 *
 *   GET  /media-retire-requests?cursor&limit       pending retire requests (Owner/Admin), keyset
 *   POST /media/retire-requests/{id}/approve       Owner; reason optional
 *   POST /media/retire-requests/{id}/reject        Owner; reason required
 *   GET  /media-retired?cursor&limit               retired files (Owner/Admin), keyset
 *   POST /media/{id}/restore                       Owner; reason required (R88)
 *
 * Every write carries an Idempotency-Key (R29). The caller passes the key of ITS submission
 * (``createKeyHolder``): a retry after a network error reuses it, so the server answers the
 * same instead of acting twice.
 */
import API from "@/lib/api";
import { idempotencyHeaders } from "@/lib/idempotency";

/** FG-693 / FG-706: both lists page by keyset — ``{items, total, limit, next_cursor}``; the
 * next page is asked for with ``cursor = next_cursor`` (a row that leaves the list between
 * two pages — a restore, a decision — never makes the next page skip a row). */
export const PAGE_SIZE = 50;

const asPage = (data) => {
  if (data && Array.isArray(data.items)) {
    return { items: data.items, total: data.total ?? data.items.length, next: data.next_cursor || null };
  }
  const items = Array.isArray(data) ? data : [];
  return { items, total: items.length, next: null };
};

const pageParams = (cursor, extra = {}) =>
  ({ ...extra, limit: PAGE_SIZE, ...(cursor ? { cursor } : {}) });

export const listRetireRequests = (cursor = null) =>
  API.get("/media-retire-requests", { params: pageParams(cursor, { status: "pending" }) })
    .then((r) => asPage(r.data));

export const listRetiredMedia = (cursor = null) =>
  API.get("/media-retired", { params: pageParams(cursor) }).then((r) => asPage(r.data));

export const approveRetire = (requestId, reason, key) =>
  API.post(`/media/retire-requests/${requestId}/approve`, reason ? { reason } : {},
    idempotencyHeaders(key));

export const rejectRetire = (requestId, reason, key) =>
  API.post(`/media/retire-requests/${requestId}/reject`, { reason }, idempotencyHeaders(key));

export const restoreMedia = (mediaId, reason, key) =>
  API.post(`/media/${mediaId}/restore`, { reason }, idempotencyHeaders(key));
