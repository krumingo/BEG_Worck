// SEC-03 FG-515: the CSP's connect-src names the analytics host ONLY when an
// analytics key is configured at build time (consistent with #88's
// REACT_APP_POSTHOG_KEY / REACT_APP_POSTHOG_HOST). craco.config.js sets
// REACT_APP_POSTHOG_HOST, which CRA interpolates into public/index.html.
const KEYS = ["REACT_APP_POSTHOG_KEY", "REACT_APP_POSTHOG_HOST", "REACT_APP_BACKEND_URL", "INLINE_RUNTIME_CHUNK"];
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

test("no analytics key -> no analytics host in the CSP, runtime chunk not inlined", () => {
  process.env.REACT_APP_POSTHOG_HOST = "https://eu.i.posthog.com";   // a host alone opens nothing
  loadCraco();
  expect(process.env.REACT_APP_POSTHOG_HOST).toBe("");
  expect(process.env.INLINE_RUNTIME_CHUNK).toBe("false");
  expect(process.env.REACT_APP_BACKEND_URL).toBe("");                 // never a literal %placeholder%
});

test("analytics key -> the default PostHog host", () => {
  process.env.REACT_APP_POSTHOG_KEY = "phc_test";
  loadCraco();
  expect(process.env.REACT_APP_POSTHOG_HOST).toBe("https://us.i.posthog.com");
});

test("analytics key + host -> exactly that host", () => {
  process.env.REACT_APP_POSTHOG_KEY = "phc_test";
  process.env.REACT_APP_POSTHOG_HOST = "https://eu.i.posthog.com";
  loadCraco();
  expect(process.env.REACT_APP_POSTHOG_HOST).toBe("https://eu.i.posthog.com");
});
