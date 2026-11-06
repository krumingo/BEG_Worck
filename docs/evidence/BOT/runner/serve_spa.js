// Minimal static server with SPA fallback: node serve_spa.js <dir> <port>
const http = require('http'), fs = require('fs'), path = require('path');
const [dir, port] = [process.argv[2], +process.argv[3] || 3000];
const types = {'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json','.png':'image/png','.svg':'image/svg+xml','.ico':'image/x-icon','.woff2':'font/woff2','.map':'application/json'};
http.createServer((req, res) => {
  let p = path.join(dir, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(dir) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) p = path.join(dir, 'index.html');
  res.writeHead(200, {'content-type': types[path.extname(p)] || 'application/octet-stream'});
  fs.createReadStream(p).pipe(res);
}).listen(port, '127.0.0.1');
