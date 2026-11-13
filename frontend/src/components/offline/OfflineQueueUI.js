// PWA-02 — what the field user sees of the offline queue: the unsent counter in the header,
// the „Моите неизпратени“ screen, the logout warning (R61-5) and the blocked-device page.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CloudOff, RefreshCw, ShieldAlert, AlertTriangle } from "lucide-react";
import { offlineQueue, useOfflineQueue, STATUS } from "@/lib/offline";

const OP_LABELS = {
  "attendance.mark": "Присъствие",
  "technician.daily_report": "Дневен отчет",
  "media.upload": "Снимка",
};

export function statusLabel(row) {
  if (row.status === "needs_review" && row.sub === "late") return STATUS.late;
  return STATUS[row.status] || row.status;
}

const TONE = {
  synced: "text-emerald-400", conflict: "text-red-400", needs_review: "text-amber-400",
  error: "text-red-400", syncing: "text-sky-400", pending: "text-muted-foreground",
  saved: "text-muted-foreground", waiting_file: "text-amber-400",
};

export function UnsentBadge({ className = "" }) {
  const { enabled, unsent } = useOfflineQueue();
  if (!enabled || !unsent) return null;
  return (
    <Link to="/my-unsent" className={`relative inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-1 text-xs font-semibold text-amber-400 ${className}`}
      data-testid="offline-unsent-badge" title="Моите неизпратени">
      <CloudOff className="h-3.5 w-3.5" />{unsent}
    </Link>
  );
}

export function MyUnsentPage() {
  const { enabled, items, unsent, lastSyncAt } = useOfflineQueue();
  const [busy, setBusy] = useState(false);
  const sync = async () => {
    setBusy(true);
    try { await offlineQueue.flush({ force: true }); } finally { setBusy(false); }
  };
  return (
    <div className="mx-auto max-w-2xl p-4 md:p-6" data-testid="my-unsent-page">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Моите неизпратени</h1>
          <p className="text-sm text-muted-foreground">
            {enabled ? `${unsent} неизпратени` : "Работата без интернет не е включена"}
            {lastSyncAt ? ` · последна синхронизация ${new Date(lastSyncAt).toLocaleString("bg-BG")}` : ""}
          </p>
        </div>
        <button type="button" onClick={sync} disabled={busy || !enabled}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          data-testid="offline-sync-now">
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />Изпрати сега
        </button>
      </div>
      {!items.length && <p className="rounded-lg border border-border p-6 text-center text-sm text-muted-foreground">Няма записи на телефона.</p>}
      <ul className="space-y-2">
        {items.map((r) => (
          <li key={r.local_id} className="flex items-center gap-3 rounded-lg border border-border bg-card p-3" data-testid="offline-item">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{OP_LABELS[r.op_type] || r.op_type}</p>
              <p className="text-xs text-muted-foreground">записано {new Date(r.captured_at).toLocaleString("bg-BG")}</p>
            </div>
            <span className={`text-xs font-semibold ${TONE[r.status] || ""}`} data-testid="offline-item-status">{statusLabel(r)}</span>
            {(r.status === "needs_review" && r.sub !== "late") || r.status === "error" ? (
              <button type="button" onClick={() => offlineQueue.retry(r.local_id)} className="rounded px-2 py-1 text-xs text-primary hover:bg-primary/10">Опитай пак</button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

// R61-5: logging out with unsent records — they stay encrypted and go when the SAME user
// logs in again. Returns a promise of true (log out) / false (stay).
export function LogoutGuard({ open, count, onConfirm, onCancel }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[90] flex items-end justify-center bg-black/60 p-4 sm:items-center" role="dialog" aria-modal="true" data-testid="offline-logout-dialog">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-5 text-foreground shadow-xl">
        <div className="mb-3 flex items-center gap-2"><AlertTriangle className="h-5 w-5 text-amber-400" /><h2 className="font-semibold">Неизпратени записи</h2></div>
        <p className="text-sm">Имате {count} неизпратени записа. Ако излезете, те остават на телефона и ще се изпратят, когато влезете отново.</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-md px-3 py-2 text-sm hover:bg-muted" data-testid="offline-logout-stay">Остани</button>
          <button type="button" onClick={onConfirm} className="rounded-md bg-destructive px-3 py-2 text-sm font-semibold text-destructive-foreground" data-testid="offline-logout-confirm">Излез</button>
        </div>
      </div>
    </div>
  );
}

export function useLogoutGuard(doLogout) {
  const [pending, setPending] = useState(0);
  const request = async () => {
    const n = offlineQueue.isEnabled() ? await offlineQueue.unsentCount() : 0;
    if (n > 0) setPending(n);
    else await doLogout();
  };
  const dialog = (
    <LogoutGuard open={pending > 0} count={pending}
      onCancel={() => setPending(0)}
      onConfirm={async () => { setPending(0); await doLogout(); }} />
  );
  return { request, dialog };
}

export function DeviceBlockedPage() {
  useEffect(() => { offlineQueue.wipe().catch(() => {}); }, []);
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6" data-testid="device-blocked-page">
      <div className="max-w-sm text-center">
        <ShieldAlert className="mx-auto mb-3 h-10 w-10 text-destructive" />
        <h1 className="mb-2 text-lg font-semibold">Устройството е блокирано</h1>
        <p className="text-sm text-muted-foreground">Собственикът или администраторът блокира това устройство. Данните на телефона са изтрити. Свържете се с офиса.</p>
        <Link to="/login" className="mt-4 inline-block text-sm text-primary hover:underline">Към входа</Link>
      </div>
    </div>
  );
}
