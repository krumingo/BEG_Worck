// LAB-R96 step 2 (Р100): a second entry for the same person × day × object × activity is a
// VISIBLE conflict. The server answers 409 (400 on the two legacy endpoints) with
// { error_code: "LABOR_LINE_EXISTS", message, existing: { worker_name, date, project_name,
// activity, status, entered_by_name, line_id, project_id, worker_id, ... } }.
import { toast } from "sonner";

export function laborConflict(err) {
  const d = err?.response?.data?.detail;
  return d && typeof d === "object" && d.error_code === "LABOR_LINE_EXISTS" ? d : null;
}

// "Вече има отчет за <човек> на <дата> по <обект>/<СМР> — отвори го"
export function laborConflictText(c) {
  const e = c.existing || {};
  const who = e.worker_name || e.worker_id || "";
  const where = [e.project_name || e.project_id, e.activity].filter(Boolean).join(" / ");
  const by = e.entered_by_name ? ` (въведен от ${e.entered_by_name}, ${e.status || ""})` : "";
  return `Вече има отчет за ${who} на ${e.date || ""} по ${where}${by} — отвори го.`;
}

// Where the existing line opens: the reports list filtered to that person and object.
export function laborConflictLink(c) {
  const e = c.existing || {};
  const q = new URLSearchParams();
  if (e.project_id) q.set("project_id", e.project_id);
  if (e.worker_id) q.set("worker_id", e.worker_id);
  return `/all-reports?${q.toString()}`;
}

// Any API error as one readable line (detail may be a string or { message }).
export function apiErrorText(err, fallback = "Грешка") {
  const c = laborConflict(err);
  if (c) return laborConflictText(c);
  const d = err?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && d.message) return d.message;
  return fallback;
}

// Toast with an "Отвори" action (canOpen: the user may see the reports list).
export function toastLaborConflict(err, navigate, canOpen = true) {
  const c = laborConflict(err);
  if (!c) return false;
  toast.error(laborConflictText(c), {
    duration: 12000,
    action: canOpen && navigate ? { label: "Отвори", onClick: () => navigate(laborConflictLink(c)) } : undefined,
  });
  return true;
}

// For screens that use alert(): confirm → open.
export function confirmLaborConflict(err, navigate, canOpen = true) {
  const c = laborConflict(err);
  if (!c) return false;
  if (canOpen && navigate) {
    if (window.confirm(`${laborConflictText(c)}\n\nОтвори съществуващия отчет?`)) navigate(laborConflictLink(c));
  } else {
    alert(laborConflictText(c));
  }
  return true;
}
