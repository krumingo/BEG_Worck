// RC-01 — build identity of this frontend bundle and its comparison with /api/version.
// REACT_APP_BUILD_SHA / REACT_APP_BUILD_TIME are baked in at build time by
// craco.config.js (see frontend/build-info.js); they are not runtime settings.
export const UNKNOWN = "unknown";
const SHA_RE = /^[0-9a-f]{40}$/;

export function frontendBuild(env = process.env) {
  const sha = env.REACT_APP_BUILD_SHA;
  return {
    build_sha: SHA_RE.test(sha || "") ? sha : UNKNOWN,
    build_time: env.REACT_APP_BUILD_TIME || "",
  };
}

export function shortSha(sha) {
  return SHA_RE.test(sha || "") ? sha.slice(0, 12) : UNKNOWN;
}

// "checking" (no answer yet) | "unreachable" | "unknown" (either side unverified)
// | "mismatch" | "match"
export function compareBuilds(frontendSha, server) {
  if (server === undefined) return "checking";
  if (server === null) return "unreachable";
  const serverSha = server.build_sha;
  if (!SHA_RE.test(frontendSha || "") || !SHA_RE.test(serverSha || "")) return "unknown";
  return frontendSha === serverSha ? "match" : "mismatch";
}

export function versionUrl(base = process.env.REACT_APP_BACKEND_URL) {
  return `${base || ""}/api/version`;
}
