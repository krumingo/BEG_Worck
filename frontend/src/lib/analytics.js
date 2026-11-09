// R68 (Krum, 09.11.2026, FG-317) — PostHog: anonymous page views and errors only.
//
// * Session recording / replay is OFF and is never started.
// * No autocapture: no clicks, no element text, no input values, no heatmaps.
// * Only two events may leave the app: "$pageview" and "app_error". Every other event
//   is dropped in before_send. Their properties are reduced to an allow-list, the URL
//   loses its query string and hash, and an error carries only its type (Error.name) —
//   never its message, which could hold field content (ЕГН, IBAN, amounts, names).
// * No user is identified (person_profiles: "identified_only" and identify is never called).
// * Without REACT_APP_POSTHOG_KEY nothing is loaded at all.
// Loader: PostHog's own snippet, minus the session-recording stubs. No npm dependency.

const DEFAULT_HOST = "https://us.i.posthog.com";

export const ALLOWED_EVENTS = ["$pageview", "app_error"];

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
    mask_all_text: true,
    mask_all_element_attributes: true,
    advanced_disable_decide: false,
    before_send: sanitizeEvent,
    loaded: (ph) => {
      // Belt and braces: even if remote config tries to enable it, recording stays off.
      if (ph && typeof ph.stopSessionRecording === "function") ph.stopSessionRecording();
    },
  };
}

function stripUrl(u) {
  if (typeof u !== "string") return undefined;
  try {
    const url = new URL(u);
    return `${url.origin}${url.pathname}`;
  } catch {
    return undefined;
  }
}

export function sanitizeEvent(event) {
  if (!event || !ALLOWED_EVENTS.includes(event.event)) return null;
  const props = {};
  Object.entries(event.properties || {}).forEach(([k, v]) => {
    if (ALLOWED_PROPS.has(k)) props[k] = v;
  });
  if (props.$current_url) props.$current_url = stripUrl(props.$current_url);
  if (event.event === "app_error") {
    props.error_kind = /^[A-Za-z]{1,40}$/.test(props.error_kind || "") ? props.error_kind : "Error";
  }
  return { ...event, properties: props, $set: undefined, $set_once: undefined };
}

// PostHog's loader snippet (MIT), with the session-recording methods removed from the stub.
const STUB_METHODS =
  "init capture register register_once unregister opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing reset get_distinct_id get_session_id onFeatureFlags".split(" ");

function installSnippet(win, doc, host) {
  if (win.posthog && win.posthog.__SV) return win.posthog;
  const ph = win.posthog || [];
  ph._i = [];
  ph.init = function init(key, options, name) {
    const target = name ? (ph[name] = []) : ph;
    STUB_METHODS.forEach((m) => {
      target[m] = (...args) => target.push([m, ...args]);
    });
    ph._i.push([key, options, name]);
  };
  ph.__SV = 1;
  win.posthog = ph;
  const script = doc.createElement("script");
  script.type = "text/javascript";
  script.crossOrigin = "anonymous";
  script.async = true;
  script.src = `${host.replace(".i.posthog.com", "-assets.i.posthog.com")}/static/array.js`;
  script.setAttribute("data-analytics", "posthog");
  doc.head.appendChild(script);
  return ph;
}

const wiredWindows = new WeakSet();

export function initAnalytics({
  key = process.env.REACT_APP_POSTHOG_KEY,
  host = process.env.REACT_APP_POSTHOG_HOST || DEFAULT_HOST,
  win = typeof window !== "undefined" ? window : undefined,
  doc = typeof document !== "undefined" ? document : undefined,
} = {}) {
  if (!key || !win || !doc) return null; // no key → nothing loads
  const options = analyticsOptions({ host });
  const ph = installSnippet(win, doc, host);
  ph.init(key, options);
  if (!wiredWindows.has(win)) {
    wiredWindows.add(win);
    const report = (kind) => {
      try { win.posthog && win.posthog.capture && win.posthog.capture("app_error", { error_kind: kind }); } catch { /* ignore */ }
    };
    win.addEventListener("error", (e) => report((e && e.error && e.error.name) || "Error"));
    win.addEventListener("unhandledrejection", (e) => report((e && e.reason && e.reason.name) || "UnhandledRejection"));
  }
  return options;
}
