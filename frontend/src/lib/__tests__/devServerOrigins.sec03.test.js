// SEC-03 R93: the dev/test server does NOT trust *.emergent.sh (nor the Emergent
// agent domain). The test drives the real /edit-file preflight handler of the
// dev-server plugin with a fake express app and reads the CORS answer.
const setupDevServer = require("../../../plugins/visual-edits/dev-server-setup");

function preflightFor(origin) {
  const routes = {};
  const app = {
    use: () => {},
    get: (p, h) => { routes[`GET ${p}`] = h; },
    post: (p, h) => { routes[`POST ${p}`] = h; },
    options: (p, h) => { routes[`OPTIONS ${p}`] = h; },
  };
  const config = setupDevServer({});
  config.setupMiddlewares([], { app });
  const headers = {};
  let status = null;
  const req = { get: (h) => (h.toLowerCase() === "origin" ? origin : undefined) };
  const res = {
    header: (k, v) => { headers[k] = v; return res; },
    sendStatus: (s) => { status = s; return res; },
  };
  routes["OPTIONS /edit-file"](req, res);
  return { status, allowOrigin: headers["Access-Control-Allow-Origin"] };
}

test.each([
  "https://emergent.sh",
  "https://app.emergent.sh",
  "https://preview-123.emergent.sh",
  "https://emergentagent.com",
  "https://x.emergentagent.com",
])("forbidden: the dev server does not trust %s", (origin) => {
  const r = preflightFor(origin);
  expect(r.status).toBe(403);
  expect(r.allowOrigin).toBeUndefined();
});

test.each(["http://localhost:3000", "http://127.0.0.1:8080"])(
  "positive: local origin %s is still allowed",
  (origin) => {
    const r = preflightFor(origin);
    expect(r.status).toBe(200);
    expect(r.allowOrigin).toBe(origin);
  },
);

test.each(["https://emergent.sh.evil.example", "https://evil.example"])(
  "forbidden: an unrelated origin %s is refused",
  (origin) => {
    expect(preflightFor(origin).status).toBe(403);
  },
);
