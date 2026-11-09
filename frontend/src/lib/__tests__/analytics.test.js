// R68 — PostHog: no session recording, no autocapture, only anonymous page views and errors.
import { initAnalytics, analyticsOptions, sanitizeEvent, ALLOWED_EVENTS } from "@/lib/analytics";
import fs from "fs";
import path from "path";

function fakeDom() {
  const appended = [];
  const listeners = {};
  const doc = {
    head: { appendChild: (el) => appended.push(el) },
    createElement: () => ({ setAttribute(k, v) { this[k] = v; } }),
  };
  const win = { addEventListener: (n, fn) => { listeners[n] = fn; } };
  return { doc, win, appended, listeners };
}

test("no key: nothing is loaded, no posthog object", () => {
  const { doc, win, appended } = fakeDom();
  expect(initAnalytics({ key: "", win, doc })).toBeNull();
  expect(initAnalytics({ key: undefined, win, doc })).toBeNull();
  expect(appended).toHaveLength(0);
  expect(win.posthog).toBeUndefined();
});

test("session recording is disabled and no recording method is stubbed", () => {
  const { doc, win, appended } = fakeDom();
  const opts = initAnalytics({ key: "phc_test", host: "https://us.i.posthog.com", win, doc });
  expect(opts.disable_session_recording).toBe(true);
  expect(appended).toHaveLength(1);
  expect(appended[0].src).toBe("https://us-assets.i.posthog.com/static/array.js");
  expect(win.posthog.startSessionRecording).toBeUndefined();
  expect(win.posthog._i[0][1].disable_session_recording).toBe(true);
  const stop = jest.fn();
  opts.loaded({ stopSessionRecording: stop });
  expect(stop).toHaveBeenCalled();
});

test("autocapture of clicks, text and inputs is off; text and attributes masked", () => {
  const o = analyticsOptions();
  expect(o.autocapture).toBe(false);
  expect(o.capture_heatmaps).toBe(false);
  expect(o.capture_dead_clicks).toBe(false);
  expect(o.rageclick).toBe(false);
  expect(o.capture_exceptions).toBe(false);
  expect(o.mask_all_text).toBe(true);
  expect(o.mask_all_element_attributes).toBe(true);
  expect(o.session_recording.maskAllInputs).toBe(true);
  expect(o.person_profiles).toBe("identified_only");
});

test("only $pageview and app_error may leave the app", () => {
  expect(ALLOWED_EVENTS).toEqual(["$pageview", "app_error"]);
  for (const ev of ["$autocapture", "$snapshot", "$rageclick", "$exception", "$identify", "$set", "$pageleave", "custom"]) {
    expect(sanitizeEvent({ event: ev, properties: { $current_url: "https://x/" } })).toBeNull();
  }
});

test("properties are reduced to the allow-list; URL loses query and hash", () => {
  const out = sanitizeEvent({
    event: "$pageview",
    properties: {
      $current_url: "https://app.example/projects/7?iban=BG80BNBG96611020345678&egn=7501010010#amount=1200",
      $pathname: "/projects/7",
      $el_text: "Иван Петров",
      $elements: [{ text: "BG80BNBG96611020345678" }],
      amount: 1200,
      name: "Иван Петров",
      $browser: "Chrome",
    },
    $set: { email: "a@b.c" },
  });
  expect(out.properties).toEqual({ $current_url: "https://app.example/projects/7", $pathname: "/projects/7", $browser: "Chrome" });
  expect(JSON.stringify(out)).not.toMatch(/BG80|7501010010|1200|Иван|a@b\.c/);
});

test("app_error carries only the error type, never a message", () => {
  const out = sanitizeEvent({ event: "app_error", properties: { error_kind: "TypeError", message: "IBAN BG80… invalid", $exception_message: "x" } });
  expect(out.properties).toEqual({ error_kind: "TypeError" });
  const weird = sanitizeEvent({ event: "app_error", properties: { error_kind: "Bad name with spaces 7501010010" } });
  expect(weird.properties.error_kind).toBe("Error");
});

test("window errors are reported as app_error with the type only", () => {
  const { doc, win, listeners } = fakeDom();
  initAnalytics({ key: "phc_test", win, doc });
  const captured = [];
  win.posthog.capture = (...a) => captured.push(a);
  listeners.error({ error: { name: "RangeError", message: "ЕГН 7501010010" } });
  expect(captured).toEqual([["app_error", { error_kind: "RangeError" }]]);
});

test("index.html no longer carries the inline PostHog snippet or a key", () => {
  const html = fs.readFileSync(path.join(__dirname, "../../../public/index.html"), "utf8");
  expect(html).not.toMatch(/posthog\.init|phc_[A-Za-z0-9]+|startSessionRecording|session_recording/);
});
