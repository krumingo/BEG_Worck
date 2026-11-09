/**
 * SEC-03 (M-5): HTML-escape a value before it is interpolated into markup that is
 * written with document.write (print windows are same-origin, so an unescaped
 * name such as `<img src=x onerror=…>` would run with the user's session).
 * null/undefined → "". Everything else is converted with String().
 */
const MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };

export function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"'`]/g, (ch) => MAP[ch]);
}

export default escapeHtml;
