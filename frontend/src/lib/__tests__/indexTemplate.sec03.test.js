// SEC-03 (H-1, M-4, L-6): the HTML template loads no third-party script and has
// a CSP that allows scripts from 'self' only.
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "../../../public/index.html"), "utf8");

test("no external <script src> and no remote loader of the former template", () => {
  expect(html).not.toMatch(/<script[^>]*\bsrc=/i);
  expect(html.toLowerCase()).not.toContain("emergent");
  expect(html).not.toContain("debug-monitor");
  expect(html).not.toContain("cdn.tailwindcss.com");
});

test("title and description are BEG_Work", () => {
  expect(html).toContain("<title>BEG_Work</title>");
  expect(html).toMatch(/<meta name="description" content="BEG_Work"/);
});

test("the CSP meta allows scripts from 'self' only", () => {
  const m = html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/);
  expect(m).not.toBeNull();
  const csp = m[1];
  expect(csp).toMatch(/default-src 'self'/);
  expect(csp).toMatch(/script-src 'self';/);
  expect(csp).not.toMatch(/unsafe-eval/);
  expect(csp).toMatch(/object-src 'none'/);
});
