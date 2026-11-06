// RC-01 — visible build identity: the first 12 characters of the frontend build SHA
// (full SHA in the tooltip), the server's environment label, and a warning when the
// frontend and the server (/api/version) are not the same verified build.
import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { compareBuilds, frontendBuild, shortSha, versionUrl } from "@/lib/buildInfo";

const MESSAGES = {
  mismatch: "Версията на интерфейса и сървъра се различава",
  unknown: "Непотвърдена версия: липсва build SHA",
  unreachable: "Версията на сървъра не може да се провери",
};

export default function BuildIdentity({ className = "" }) {
  const fe = frontendBuild();
  // undefined = still asking, null = no usable answer, object = /api/version body
  const [server, setServer] = useState(undefined);

  useEffect(() => {
    let alive = true;
    if (typeof fetch !== "function") {
      setServer(null);
      return undefined;
    }
    fetch(versionUrl(), { headers: { Accept: "application/json" }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => { if (alive) setServer(body && typeof body === "object" ? body : null); })
      .catch(() => { if (alive) setServer(null); });
    return () => { alive = false; };
  }, []);

  const status = compareBuilds(fe.build_sha, server);
  const env = server?.environment_label;
  const warn = MESSAGES[status];
  const serverSha = server?.build_sha;

  return (
    <div className={`text-[11px] leading-tight text-muted-foreground font-mono min-w-0 ${className}`}
      data-testid="build-identity" data-build-status={status}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span title={fe.build_sha} data-testid="build-sha" data-full-sha={fe.build_sha}>
          v {shortSha(fe.build_sha)}
        </span>
        {env && <span data-testid="build-env" className="uppercase tracking-wide">{env}</span>}
      </div>
      {warn && (
        <div role="alert" data-testid={`build-warning-${status}`}
          className="mt-1 flex items-start gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-1 text-amber-700 dark:text-amber-400 font-sans break-words">
          <AlertTriangle className="w-3 h-3 mt-[1px] shrink-0" />
          <span className="min-w-0">
            {warn}
            {status === "mismatch" && (
              <span className="block font-mono" data-testid="build-server-sha" title={serverSha}>
                сървър: {shortSha(serverSha)}
              </span>
            )}
          </span>
        </div>
      )}
    </div>
  );
}
