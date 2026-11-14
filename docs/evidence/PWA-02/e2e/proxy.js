// PWA-02 evidence — serves a production build like nginx.conf: /api → the real backend,
// everything else from the build with the SPA fallback.  node proxy.js <build> <port> <backend>
const http = require("http");
const fs = require("fs");
const path = require("path");

const root = path.resolve(process.argv[2]);
const port = Number(process.argv[3] || 4180);
const backend = new URL(process.argv[4] || "http://127.0.0.1:8001");
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
  ".json": "application/json", ".webmanifest": "application/manifest+json", ".png": "image/png", ".svg": "image/svg+xml" };

http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/uploads/")) {
    const fwd = http.request({ host: backend.hostname, port: backend.port, path: req.url, method: req.method,
      headers: { ...req.headers, host: `${backend.hostname}:${backend.port}` } }, (r) => {
      res.writeHead(r.statusCode, r.headers);
      r.pipe(res);
    });
    fwd.on("error", () => { res.writeHead(502); res.end(); });
    req.pipe(fwd);
    return;
  }
  let file = path.join(root, decodeURIComponent(url.pathname));
  if (!file.startsWith(root)) { res.writeHead(403); return res.end(); }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, "index.html");
  const headers = { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" };
  if (path.basename(file) === "service-worker.js") headers["Cache-Control"] = "no-cache";
  res.writeHead(200, headers);
  fs.createReadStream(file).pipe(res);
}).listen(port, () => console.log(`proxy ${root} :${port} -> ${backend.href}`));
