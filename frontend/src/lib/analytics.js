// R68 (Krum, 09.11.2026, FG-317) — PostHog: anonymous page views and errors only.
//
// * Session recording / replay is OFF and is never started.
// * No autocapture: no clicks, no element text, no input values, no heatmaps.
// * Only two events may leave the app: "$pageview" and "app_error". Every other event
//   is dropped in before_send. Their properties are reduced to an allow-list, the URL
//   and pathname become the route TEMPLATE (no ids or tokens, no query, no hash — FG-470),
//   nothing is loaded or sent on token routes (/offers/review/*, /reset-password), and an error carries only its type (Error.name) —
//   never its message, which could hold field content (ЕГН, IBAN, amounts, names).
// * No user is identified (person_profiles: "identified_only" and identify is never called).
// * Without REACT_APP_POSTHOG_KEY nothing is loaded at all.
// Loader (PWA88-N1): posthog-js is BUNDLED from npm, pinned to 1.200.0 in yarn.lock, using
// its "no-external" build, which cannot load remote scripts (no surveys, toolbar, site apps,
// web experiments or recorder). No script is ever injected from a PostHog host into the
// origin that holds bw_token. /decide is disabled, so no remote config can turn anything on.
// The library is a lazy chunk: without a key it is never even fetched.

const DEFAULT_HOST = "https://us.i.posthog.com";

export const ALLOWED_EVENTS = ["$pageview", "app_error"];

// FG-470: public routes whose URL carries a credential (the client's offer magic link,
// the password-reset token). Analytics is never loaded there and any event from such a
// path is dropped.
export const NO_ANALYTICS_ROUTES = [/^\/offers\/review(\/|$)/, /^\/reset-password(\/|$)/];

export function isNoAnalyticsPath(pathname) {
  return NO_ANALYTICS_ROUTES.some((re) => re.test(pathname || ""));
}

// FG-470: only route TEMPLATES leave the app, never ids or tokens from the path.
// Must list every <Route path> in App.js (guarded by analytics.test.js).
export const ROUTE_TEMPLATES = [
  "/", "/login", "/signup", "/forgot-password", "/reset-password", "/plans", "/billing", "/billing/success", "/billing/cancel",
  "/offers/review/:reviewToken", "/projects", "/projects/:projectId", "/projects/:projectId/financial",
  "/projects/:projectId/novo-smr", "/projects/:projectId/operations", "/projects/:projectId/progress",
  "/projects/:projectId/smr-analysis/:analysisId", "/sites", "/sites/:siteId", "/my-day", "/attendance-history",
  "/my-payslips", "/tech", "/tech/tools", "/tech/my-money", "/s/:qrId", "/notifications", "/site-attendance",
  "/work-reports/new", "/work-reports/:reportId", "/review-reports", "/reports", "/reports/finance-details", "/reminders",
  "/offers", "/offers/new", "/offers/:offerId", "/historical-offers", "/activity-catalog", "/employees",
  "/employees/:userId", "/brigades", "/advances", "/pay-runs", "/finance", "/finance/accounts", "/finance/analysis",
  "/finance/invoices", "/finance/invoices/new", "/finance/invoices/:invoiceId", "/finance/invoices/:invoiceId/lines",
  "/finance/payments", "/finance/payments/new", "/overhead", "/overhead/snapshots/:snapshotId", "/data/warehouses",
  "/data/counterparties", "/data/items", "/data/clients", "/data/prices", "/data/turnover", "/data/master-data",
  "/assets/qr", "/assets/items", "/assets/units", "/assets/units/:unitId", "/assets/batch-intake",
  "/assets/intake-review", "/warehouse/canonical", "/sales", "/clients/:clientId", "/daily-logs", "/change-orders",
  "/ai-calibration", "/procurement", "/inventory", "/missing-smr", "/smr-analyses", "/contract-payments",
  "/worker-calendar", "/alarms", "/all-reports", "/ocr-invoices", "/pricing", "/users", "/settings", "/modules",
  "/mobile-settings", "/audit-log", "/my-unsent", "/device-blocked", "/sync-console", "/platform", "/platform/login", "/platform/logout", "/platform/billing",
  "/platform/modules", "/platform/audit-log", "/platform/mobile-settings",
];
const TEMPLATE_SEGMENTS = ROUTE_TEMPLATES.map((t) => t.split("/").filter(Boolean));

export function templatePath(pathname) {
  const segs = String(pathname || "/").split("/").filter(Boolean);
  // Static routes win over parameter routes (/offers/new before /offers/:offerId).
  let best = null;
  for (const tpl of TEMPLATE_SEGMENTS) {
    if (tpl.length !== segs.length) continue;
    if (!tpl.every((t, i) => t.startsWith(":") || t === segs[i])) continue;
    const params = tpl.filter((t) => t.startsWith(":")).length;
    if (!best || params < best.params) best = { tpl, params };
  }
  return best ? `/${best.tpl.join("/")}` : "/:unknown";
}

// Properties kept on an allowed event. Everything else is removed.
const ALLOWED_PROPS = new Set([
  "token", "distinct_id", "$device_id", "$session_id", "$window_id", "$insert_id", "$time",
  "$lib", "$lib_version", "$os", "$os_version", "$browser", "$browser_version", "$device_type",
  "$screen_height", "$screen_width", "$viewport_height", "$viewport_width",
  "$current_url", "$host", "$pathname", "$pageview_id", "$process_person_profile",
  "error_kind", "app_build",
]);

export function analyticsOptions({ host = DEFAULT_HOST } = {}) {
  return {
    api_host: host,
    person_profiles: "identified_only",
    disable_session_recording: true,
    session_recording: { maskAllInputs: true, maskTextSelector: "*", recordCrossOriginIframes: false },
    autocapture: false,
    capture_pageview: true,
    capture_pageleave: false,
    capture_dead_clicks: false,
    capture_heatmaps: false,
    enable_heatmaps: false,
    rageclick: false,
    capture_exceptions: false,
    capture_performance: false,
    disable_surveys: true,
    disable_web_experiments: true,
    opt_in_site_apps: false,
    advanced_disable_decide: true,
    advanced_disable_feature_flags: true,
    advanced_disable_feature_flags_on_first_load: true,
    advanced_disable_toolbar_metrics: true,
    mask_all_text: true,
    mask_all_element_attributes: true,
    before_send: sanitizeEvent,
    loaded: (ph) => {
      // Belt and braces: even if remote config tries to enable it, recording stays off.
      if (ph && typeof ph.stopSessionRecording === "function") ph.stopSessionRecording();
    },
  };
}

function originOf(u) {
  if (typeof u !== "string") return null;
  try {
    return new URL(u).origin;
  } catch {
    return null;
  }
}

function pathOf(u) {
  try { return new URL(u).pathname; } catch { return null; }
}

export function sanitizeEvent(event) {
  if (!event || !ALLOWED_EVENTS.includes(event.event)) return null;
  const raw = event.properties || {};
  const rawPath = raw.$pathname || pathOf(raw.$current_url) || "";
  // FG-470: never from a token route (checked on both the pathname and the full URL).
  if (isNoAnalyticsPath(rawPath) || isNoAnalyticsPath(pathOf(raw.$current_url))) return null;
  const props = {};
  Object.entries(raw).forEach(([k, v]) => {
    if (ALLOWED_PROPS.has(k)) props[k] = v;
  });
  const tpl = templatePath(rawPath);
  if (props.$current_url) {
    const origin = originOf(props.$current_url);
    props.$current_url = origin ? `${origin}${tpl}` : undefined;
  }
  if (props.$pathname) props.$pathname = tpl;
  if (event.event === "app_error") {
    props.error_kind = /^[A-Za-z]{1,40}$/.test(props.error_kind || "") ? props.error_kind : "Error";
  }
  return { ...event, properties: props, $set: undefined, $set_once: undefined };
}

const loadLibrary = () => import("posthog-js/dist/module.no-external");

const wiredWindows = new WeakSet();

export function initAnalytics({
  key = process.env.REACT_APP_POSTHOG_KEY,
  host = process.env.REACT_APP_POSTHOG_HOST || DEFAULT_HOST,
  win = typeof window !== "undefined" ? window : undefined,
  load = loadLibrary,
} = {}) {
  if (!key || !win) return null; // no key → nothing loads (the chunk is not even fetched)
  // FG-470: a client opening an offer link or a reset link never loads analytics.
  if (isNoAnalyticsPath(win.location && win.location.pathname)) return null;
  const options = analyticsOptions({ host });
  const ready = Promise.resolve()
    .then(load)
    .then((mod) => {
      const ph = (mod && (mod.default || mod.posthog)) || null;
      if (!ph || typeof ph.init !== "function") return null;
      ph.init(key, options);
      win.posthog = ph; // same-origin handle (error reporting, evidence checks)
      return ph;
    })
    .catch(() => null); // analytics must never break the app
  if (!wiredWindows.has(win)) {
    wiredWindows.add(win);
    const report = (kind) => {
      try { win.posthog && win.posthog.capture && win.posthog.capture("app_error", { error_kind: kind }); } catch { /* ignore */ }
    };
    win.addEventListener("error", (e) => report((e && e.error && e.error.name) || "Error"));
    win.addEventListener("unhandledrejection", (e) => report((e && e.reason && e.reason.name) || "UnhandledRejection"));
  }
  return { options, ready };
}
