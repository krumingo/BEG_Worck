// PWA-01 evidence — serves a production build the way nginx.conf does (SPA fallback,
// /api and /uploads go to "the backend"), with a small in-memory mock backend.
// Usage: node server.js <build-dir> <port>
const http = require("http");
const fs = require("fs");
const path = require("path");

const root = path.resolve(process.argv[2]);
const port = Number(process.argv[3] || 4173);
let swBump = 0;

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css", ".json": "application/json", ".webmanifest": "application/manifest+json", ".png": "image/png", ".svg": "image/svg+xml", ".map": "application/json" };
const TENANTS = { "org-a": { id: "org-a", name: "Тест Фирма А ЕООД" }, "org-b": { id: "org-b", name: "Тест Фирма Б ООД" } };
const userFor = (org) => ({ id: `u-${org}`, email: `${org}@example.test`, first_name: "Иван", last_name: "Петров", name: "Иван Петров", role: "Technician", org_id: org });

function json(res, code, body) {
  res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  res.end(JSON.stringify(body));
}

function api(req, res, url) {
  const auth = req.headers.authorization || "";
  const org = auth.startsWith("Bearer token-") ? auth.slice("Bearer token-".length) : null;
  const p = url.pathname.replace(/^\/api/, "");
  if (p === "/auth/login" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const { email } = JSON.parse(body || "{}");
      const o = String(email || "").startsWith("b") ? "org-b" : "org-a";
      json(res, 200, { token: `token-${o}`, user: userFor(o) });
    });
    return;
  }
  if (p === "/version") return json(res, 200, { build_sha: "unknown" });
  if (!org || !TENANTS[org]) return json(res, 401, { detail: "Not authenticated" });
  if (p === "/auth/me") return json(res, 200, userFor(org));
  if (p === "/organization") return json(res, 200, TENANTS[org]);
  // A "sensitive" payload the service worker must never store.
  if (p === "/payments") return json(res, 200, { items: [{ id: "pay-1", amount: 1234.56, iban: "BG00TEST00000000000000" }] });
  if (p === "/technician/my-sites") return json(res, 200, []);
  return json(res, 200, { items: [] });
}

http
  .createServer((req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname === "/__test/bump-sw") { swBump += 1; return json(res, 200, { swBump }); }
    if (url.pathname.startsWith("/api/") || url.pathname === "/api") return api(req, res, url);
    if (url.pathname.startsWith("/uploads/")) {
      res.writeHead(200, { "Content-Type": "image/png" });
      return res.end(fs.readFileSync(path.join(root, "icons/favicon-32.png")));
    }
    let file = path.join(root, decodeURIComponent(url.pathname));
    if (!file.startsWith(root)) { res.writeHead(403); return res.end(); }
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, "index.html");
    let body = fs.readFileSync(file);
    const headers = { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" };
    if (path.basename(file) === "service-worker.js") {
      headers["Cache-Control"] = "no-cache";
      if (swBump) body = Buffer.concat([body, Buffer.from(`\n// test bump ${swBump}\n`)]);
    }
    res.writeHead(200, headers);
    res.end(body);
  })
  .listen(port, () => console.log(`serving ${root} on http://localhost:${port}`));
