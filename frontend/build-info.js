// RC-01 — build identity baked into the frontend bundle at build time.
//
// Source order (the backend uses the same one, app/core/build_info.py):
//   1. frontend/BUILD_INFO.json (beg.build-info/v1), written from Git objects by
//      ops/release/write_build_info.py. Git-ignored; it wins.
//   2. REACT_APP_BUILD_SHA / REACT_APP_BUILD_TIME — fallback only.
//   3. neither -> "unknown"; the UI says the build is unverified.
//
// craco.config.js copies the result into process.env.REACT_APP_BUILD_SHA /
// REACT_APP_BUILD_TIME before CRA reads the environment, so it ends up as a constant
// in the bundle. Not a runtime setting: changing it needs a new build.
const fs = require("fs");
const path = require("path");

const SCHEMA = "beg.build-info/v1";
const UNKNOWN = "unknown";
const SHA_RE = /^[0-9a-f]{40}$/;
const TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

function readFile(file) {
  let data;
  try {
    data = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (e) {
    return null;
  }
  if (!data || data.schema !== SCHEMA || !SHA_RE.test(data.build_sha || "")) return null;
  return { build_sha: data.build_sha, build_time: TIME_RE.test(data.build_time || "") ? data.build_time : "" };
}

function resolveBuildInfo(dir = __dirname, env = process.env) {
  const file = readFile(path.join(dir, "BUILD_INFO.json"));
  const envSha = SHA_RE.test(env.REACT_APP_BUILD_SHA || "") ? env.REACT_APP_BUILD_SHA : null;
  if (file) {
    if (envSha && envSha !== file.build_sha) {
      // eslint-disable-next-line no-console
      console.warn(`RC-01: REACT_APP_BUILD_SHA ${envSha.slice(0, 12)} disagrees with BUILD_INFO.json ${file.build_sha.slice(0, 12)}; using the file`);
    }
    return { ...file, source: "build-info-file" };
  }
  if (envSha) {
    const t = env.REACT_APP_BUILD_TIME || "";
    return { build_sha: envSha, build_time: TIME_RE.test(t) ? t : "", source: "env" };
  }
  return { build_sha: UNKNOWN, build_time: "", source: "none" };
}

module.exports = { resolveBuildInfo, UNKNOWN };

if (require.main === module) {
  process.stdout.write(JSON.stringify(resolveBuildInfo(process.argv[2] || __dirname)) + "\n");
}
