// SEC-03 FG-515 / SEC90-N5: the CSP's connect-src names the analytics ORIGIN only
// when an analytics key is configured at build time (#88's REACT_APP_POSTHOG_KEY /
// REACT_APP_POSTHOG_HOST). A CSP source with a path would match only that exact
// path, so the CSP gets new URL(host).origin — while REACT_APP_POSTHOG_HOST keeps
// its full value (with the proxy path) for posthog-js itself.
const KEYS = ["REACT_APP_POSTHOG_KEY", "REACT_APP_POSTHOG_HOST", "REACT_APP_BACKEND_URL", "INLINE_RUNTIME_CHUNK",
  "REACT_APP_CSP_API_ORIGIN", "REACT_APP_CSP_ANALYTICS_ORIGIN"];
let saved;

beforeEach(() => {
  saved = {};
  KEYS.forEach((k) => { saved[k] = process.env[k]; delete process.env[k]; });
});
afterEach(() => {
  KEYS.forEach((k) => { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]; });
});

function loadCraco() {
  jest.isolateModules(() => { require("../../../craco.config"); });
}

test("no analytics key -> no analytics origin in the CSP, runtime chunk not inlined", () => {
  process.env.REACT_APP_POSTHOG_HOST = "https://eu.i.posthog.com";   // a host alone opens nothing
  loadCraco();
  expect(process.env.REACT_APP_CSP_ANALYTICS_ORIGIN).toBe("");
  expect(process.env.INLINE_RUNTIME_CHUNK).toBe("false");
  expect(process.env.REACT_APP_BACKEND_URL).toBe("");                 // never a literal %placeholder%
  expect(process.env.REACT_APP_CSP_API_ORIGIN).toBe("");
});

test("analytics key, default host -> exactly https://us.i.posthog.com", () => {
  process.env.REACT_APP_POSTHOG_KEY = "phc_test";
  loadCraco();
  expect(process.env.REACT_APP_CSP_ANALYTICS_ORIGIN).toBe("https://us.i.posthog.com");
});

test("analytics key + another host -> exactly that origin", () => {
  process.env.REACT_APP_POSTHOG_KEY = "phc_test";
  process.env.REACT_APP_POSTHOG_HOST = "https://eu.i.posthog.com";
  loadCraco();
  expect(process.env.REACT_APP_CSP_ANALYTICS_ORIGIN).toBe("https://eu.i.posthog.com");
});

test.each([
  ["https://app.example.com/ingest", "https://app.example.com"],
  ["https://app.example.com/__posthog/", "https://app.example.com"],
  ["https://analytics.example.com:8443/a/b?x=1#y", "https://analytics.example.com:8443"],
])("SEC90-N5: a host with a path (%s) -> its ORIGIN in the CSP; the app keeps the full host", (host, origin) => {
  process.env.REACT_APP_POSTHOG_KEY = "phc_test";
  process.env.REACT_APP_POSTHOG_HOST = host;
  loadCraco();
  expect(process.env.REACT_APP_CSP_ANALYTICS_ORIGIN).toBe(origin);
  expect(process.env.REACT_APP_POSTHOG_HOST).toBe(host);
});

test("the API URL enters the CSP as its origin as well", () => {
  process.env.REACT_APP_BACKEND_URL = "https://erp.example.com/beg";
  loadCraco();
  expect(process.env.REACT_APP_CSP_API_ORIGIN).toBe("https://erp.example.com");
  expect(process.env.REACT_APP_BACKEND_URL).toBe("https://erp.example.com/beg");
});

test("an invalid analytics host fails the build instead of producing a broken CSP", () => {
  process.env.REACT_APP_POSTHOG_KEY = "phc_test";
  process.env.REACT_APP_POSTHOG_HOST = "not a url";
  expect(loadCraco).toThrow(/not a valid URL for the CSP/);
});
