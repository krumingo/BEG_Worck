/**
 * PRJ-01 — the project lifecycle without hard delete (FLOW-001 P-04, P-07, P-08; R54).
 *
 * Every call carries an Idempotency-Key (R29) and, where the server asks for one, a reason.
 * The server answers a refusal with { error_code, message }; ``apiErrorText`` shows it.
 */
import API from "@/lib/api";
import { idempotencyHeaders, newIdempotencyKey } from "@/lib/idempotency";

// FLOW-001 P-08: why a closed project is opened again.
export const REOPEN_KINDS = {
  warranty: "Гаранционна работа",
  defect: "Дефект",
  completion: "Довършване",
  additional_work: "Допълнително СМР",
  correction: "Корекция",
};

// Statuses that go through their own endpoint (reason + Owner/Admin + AuditEvent).
export const LIFECYCLE_ENDPOINT = { Archived: "archive", Cancelled: "cancel" };

export function deleteProject(id) {
  return API.delete(`/projects/${id}`, idempotencyHeaders(newIdempotencyKey()));
}

export function changeProjectStatus(id, status, reason) {
  return API.post(`/projects/${id}/${LIFECYCLE_ENDPOINT[status]}`, { reason },
    idempotencyHeaders(newIdempotencyKey()));
}

export function reopenProject(id, kind, reason) {
  return API.post(`/projects/${id}/reopen`, { kind, reason },
    idempotencyHeaders(newIdempotencyKey()));
}

// R56(1): the technical manager (SiteManager) only requests a reopen; Owner/Admin reopen.
export function requestProjectReopen(id, kind, reason) {
  return API.post(`/projects/${id}/reopen-request`, { kind, reason },
    idempotencyHeaders(newIdempotencyKey()));
}
