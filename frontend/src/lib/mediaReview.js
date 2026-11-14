/**
 * MEDIA-SEC-01 — the existing media review APIs (no new rules):
 *
 *   GET  /media-retire-requests?skip&limit         pending retire requests (Owner/Admin), paged
 *   POST /media/retire-requests/{id}/approve       Owner; reason optional
 *   POST /media/retire-requests/{id}/reject        Owner; reason required
 *   GET  /media-retired?skip&limit                 retired files (Owner/Admin), paged
 *   POST /media/{id}/restore                       Owner; reason required (R88)
 *
 * Every write carries an Idempotency-Key (R29). The caller passes the key of ITS submission
 * (``createKeyHolder``): a retry after a network error reuses it, so the server answers the
 * same instead of acting twice.
 */
import API from "@/lib/api";
import { idempotencyHeaders } from "@/lib/idempotency";

/** FG-693: both lists page — ``{items, total, skip, limit, next_skip}``. */
export const PAGE_SIZE = 50;

const asPage = (data) => {
  if (data && Array.isArray(data.items)) {
    return { items: data.items, total: data.total ?? data.items.length, next: data.next_skip ?? null };
  }
  const items = Array.isArray(data) ? data : [];
  return { items, total: items.length, next: null };
};

export const listRetireRequests = (skip = 0) =>
  API.get("/media-retire-requests", { params: { status: "pending", skip, limit: PAGE_SIZE } })
    .then((r) => asPage(r.data));

export const listRetiredMedia = (skip = 0) =>
  API.get("/media-retired", { params: { skip, limit: PAGE_SIZE } }).then((r) => asPage(r.data));

export const approveRetire = (requestId, reason, key) =>
  API.post(`/media/retire-requests/${requestId}/approve`, reason ? { reason } : {},
    idempotencyHeaders(key));

export const rejectRetire = (requestId, reason, key) =>
  API.post(`/media/retire-requests/${requestId}/reject`, { reason }, idempotencyHeaders(key));

export const restoreMedia = (mediaId, reason, key) =>
  API.post(`/media/${mediaId}/restore`, { reason }, idempotencyHeaders(key));
