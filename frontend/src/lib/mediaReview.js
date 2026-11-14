/**
 * MEDIA-SEC-01 — the existing media review APIs (no new rules):
 *
 *   GET  /media-retire-requests                    pending retire requests (Owner/Admin)
 *   POST /media/retire-requests/{id}/approve       Owner; reason optional
 *   POST /media/retire-requests/{id}/reject        Owner; reason required
 *   GET  /media-retired                            retired files (Owner/Admin)
 *   POST /media/{id}/restore                       Owner; reason required (R88)
 *
 * Every write carries an Idempotency-Key (R29). The caller passes the key of ITS submission
 * (``createKeyHolder``): a retry after a network error reuses it, so the server answers the
 * same instead of acting twice.
 */
import API from "@/lib/api";
import { idempotencyHeaders } from "@/lib/idempotency";

export const listRetireRequests = () =>
  API.get("/media-retire-requests", { params: { status: "pending" } }).then((r) => r.data || []);

export const listRetiredMedia = () => API.get("/media-retired").then((r) => r.data || []);

export const approveRetire = (requestId, reason, key) =>
  API.post(`/media/retire-requests/${requestId}/approve`, reason ? { reason } : {},
    idempotencyHeaders(key));

export const rejectRetire = (requestId, reason, key) =>
  API.post(`/media/retire-requests/${requestId}/reject`, { reason }, idempotencyHeaders(key));

export const restoreMedia = (mediaId, reason, key) =>
  API.post(`/media/${mediaId}/restore`, { reason }, idempotencyHeaders(key));
