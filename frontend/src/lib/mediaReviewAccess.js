/**
 * MEDIA-SEC-01 — who sees and acts on the "Файлове за преглед" screen (/media/review).
 *
 * The backend decides: every call is checked server-side (backend/app/routes/media.py with
 * the roles in backend/app/services/media_policy.py), so nothing here grants anything. This
 * mirror only keeps the UI honest — nobody is shown a button the server refuses.
 *
 *   REVIEW_ROLES   see both lists (retire requests, retired files) — FG-558: Owner / Admin
 *   DECIDE_ROLES   approve / reject a retire request — R83(2): the Owner
 *   RESTORE_ROLES  restore a retired file — R88 (14.11.2026): the Owner
 *
 * The retired list also carries the server's own ``can_restore`` per row; the restore
 * button needs both.
 */
export const REVIEW_ROLES = ["Owner", "Admin"];
export const DECIDE_ROLES = ["Owner"];
export const RESTORE_ROLES = ["Owner"];

export const canOpenMediaReview = (role) => REVIEW_ROLES.includes(role);
export const canDecideRetire = (role) => DECIDE_ROLES.includes(role);
export const canRestoreMedia = (role) => RESTORE_ROLES.includes(role);
