// PWA-02 (FLOW-037 §14, R61) — the console for Owner/Admin: devices and their last sync,
// conflicts (both versions + diff), late records waiting for the office, items that came
// from a blocked device, and „Блокирай устройство“. A projection of the server's sync
// collections, never a second source of truth.
import { useCallback, useEffect, useState } from "react";
import { Smartphone, ShieldOff, AlertTriangle, Clock, Inbox, RefreshCw } from "lucide-react";
import API from "@/lib/api";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("bg-BG") : "—");
const newKey = () => (globalThis.crypto && globalThis.crypto.randomUUID ? globalThis.crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

const OP_LABELS = { "attendance.mark": "Присъствие", "technician.daily_report": "Дневен отчет", "media.upload": "Снимка" };
const LATE_REASONS = { previous_day: "записано в предишен ден", clock_skew: "часовникът на телефона е разминат" };
const KIND_LABELS = { version: "офисът е променил записа", approved: "записът е одобрен", paid: "записът е платен",
  already_recorded: "вече записано от офиса" };

function Section({ icon: Icon, title, count, children, testId }) {
  return (
    <section className="rounded-xl border border-border bg-card" data-testid={testId}>
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Icon className="h-4 w-4 text-primary" />
        <h2 className="flex-1 text-sm font-semibold">{title}</h2>
        <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{count}</span>
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

const CORRECTION_ONLY = ["approved", "paid", "closed"];
const ATT_STATUSES = ["Present", "Late", "Absent", "SickLeave", "Vacation"];

// One decision row: a reason (required) and the buttons; posts with an Idempotency-Key.
function Decide({ url, actions, onDone, testId, extra = null }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [key] = useState(newKey);
  const go = async (decision, payload) => {
    setBusy(true);
    setError(null);
    try {
      await API.post(url, { decision, reason, ...(payload ? { payload } : {}) }, { headers: { "Idempotency-Key": `${key}:${decision}` } });
      onDone();
    } catch (e) {
      const d = e.response && e.response.data && e.response.data.detail;
      setError((d && d.message) || "Неуспешно");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-3 space-y-2" data-testid={testId}>
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Причина (задължително)"
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" data-testid={`${testId}-reason`} />
      {extra}
      <div className="flex flex-wrap gap-2">
        {actions.map((a) => (
          <button key={a.decision} type="button" disabled={busy || reason.trim().length < 3 || a.disabled}
            onClick={() => go(a.decision, a.payload && a.payload())} title={a.title || ""}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-40 ${a.tone || "border border-border hover:bg-muted"}`}
            data-testid={`${testId}-${a.decision}`}>{a.label}</button>
        ))}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function LateDecision({ item, onDone }) {
  const [status, setStatus] = useState((item.payload && item.payload.status) || "Present");
  const isAtt = item.op_type === "attendance.mark";
  const actions = [
    { decision: "confirm", label: "Потвърди", tone: "bg-primary text-primary-foreground" },
    ...(isAtt ? [{ decision: "correct", label: "Коригирай", payload: () => ({ ...item.payload, status }) }] : []),
    { decision: "reject", label: "Откажи", tone: "border border-destructive/50 text-destructive" },
  ];
  const extra = isAtt ? (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">Статус при корекция
      <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded border border-border bg-background px-2 py-1 text-foreground">
        {ATT_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
    </label>
  ) : null;
  return <Decide url={`/sync/late/${item.id}/decide`} actions={actions} onDone={onDone} testId="late-decide" extra={extra} />;
}

function ConflictDecision({ item, onDone }) {
  const locked = CORRECTION_ONLY.includes(item.kind);
  const actions = [
    { decision: "keep_office", label: "Остави офисната", tone: "bg-primary text-primary-foreground" },
    { decision: "accept_field", label: "Приеми теренната", disabled: locked,
      title: locked ? "Одобрен/платен запис — само корекция или сторно" : "" },
  ];
  return (
    <>
      {locked && <p className="mt-2 text-xs text-amber-400">Записът е одобрен или платен — теренната версия може да влезе само чрез корекция или сторно в съответния модул.</p>}
      <Decide url={`/sync/conflicts/${item.id}/resolve`} actions={actions} onDone={onDone} testId="conflict-decide" />
    </>
  );
}

const Empty = ({ text }) => <p className="px-1 py-2 text-sm text-muted-foreground">{text}</p>;

export function RevokeDialog({ device, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [key] = useState(newKey);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await API.post(`/sync/devices/${device.id}/revoke`, { reason }, { headers: { "Idempotency-Key": key } });
      onDone();
    } catch (e) {
      setError((e.response && e.response.data && e.response.data.detail && e.response.data.detail.message) || "Неуспешно блокиране");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" data-testid="revoke-dialog">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-xl">
        <h3 className="mb-1 font-semibold">Блокирай устройство</h3>
        <p className="mb-3 text-sm text-muted-foreground">{device.label || "Устройство"} · {device.last_user_name || "—"}. Сървърът спира да приема данни от него; при следващо свързване телефонът изтрива локалните данни.</p>
        <label className="mb-1 block text-xs text-muted-foreground" htmlFor="revoke-reason">Причина</label>
        <input id="revoke-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="напр. Изгубен телефон"
          className="mb-2 w-full rounded-md border border-border bg-background px-3 py-2 text-sm" data-testid="revoke-reason" />
        {error && <p className="mb-2 text-sm text-destructive">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-2 text-sm hover:bg-muted">Отказ</button>
          <button type="button" onClick={submit} disabled={busy || reason.trim().length < 3}
            className="rounded-md bg-destructive px-3 py-2 text-sm font-semibold text-destructive-foreground disabled:opacity-50" data-testid="revoke-confirm">Блокирай</button>
        </div>
      </div>
    </div>
  );
}

export default function SyncConsolePage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [revoking, setRevoking] = useState(null);
  const load = useCallback(async () => {
    try {
      setData((await API.get("/sync/console")).data);
      setError(null);
    } catch (e) {
      setError("Конзолата не може да се зареди");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (error) return <div className="p-6 text-sm text-destructive">{error}</div>;
  if (!data) return <div className="p-6 text-sm text-muted-foreground">Зареждане…</div>;
  const c = data.counts || {};
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6" data-testid="sync-console-page">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Работа без интернет — конзола</h1>
          <p className="text-sm text-muted-foreground">{data.enabled ? "Включена" : "Изключена за фирмата"} · {fmt(data.server_time)}</p>
        </div>
        <button type="button" onClick={load} className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm hover:bg-muted"><RefreshCw className="h-4 w-4" />Обнови</button>
      </div>

      <Section icon={AlertTriangle} title="Конфликти" count={c.conflicts || 0} testId="console-conflicts">
        {!data.conflicts.length ? <Empty text="Няма конфликти." /> : data.conflicts.map((x) => (
          <article key={x.id} className="mb-3 rounded-lg border border-border p-3 last:mb-0" data-testid="console-conflict">
            <p className="text-sm font-medium">{OP_LABELS[x.op_type] || x.op_type} · {KIND_LABELS[x.kind] || x.kind}</p>
            <p className="mb-2 text-xs text-muted-foreground">{x.author_name} · записано {fmt(x.captured_at)} · получено {fmt(x.received_at)}</p>
            <table className="w-full text-xs">
              <thead><tr className="text-left text-muted-foreground"><th className="py-1">Поле</th><th>Офис</th><th>Телефон</th></tr></thead>
              <tbody>{(x.diff || []).map((d) => (
                <tr key={d.field} className="border-t border-border"><td className="py-1 font-mono">{d.field}</td><td>{String(d.office ?? "—")}</td><td className="text-amber-400">{String(d.phone ?? "—")}</td></tr>
              ))}</tbody>
            </table>
            <ConflictDecision item={x} onDone={load} />
          </article>
        ))}
      </Section>

      <Section icon={Clock} title="Закъснели — чакат офиса" count={c.late || 0} testId="console-late">
        {!data.late.length ? <Empty text="Няма закъснели записи." /> : (
          <ul className="space-y-2">{data.late.map((x) => (
            <li key={x.id} className="rounded-lg border border-border p-3 text-sm" data-testid="console-late-item">
              <p className="font-medium">{OP_LABELS[x.op_type] || x.op_type} · {LATE_REASONS[x.reason] || x.reason}</p>
              <p className="text-xs text-muted-foreground">{x.author_name} · записано {fmt(x.captured_at)} · получено {fmt(x.received_at)}</p>
              <LateDecision item={x} onDone={load} />
            </li>
          ))}</ul>
        )}
      </Section>

      <Section icon={Inbox} title="От блокирано устройство" count={c.quarantine || 0} testId="console-quarantine">
        {!data.quarantine.length ? <Empty text="Няма." /> : (
          <ul className="space-y-2">{data.quarantine.map((x) => (
            <li key={x.id} className="rounded-lg border border-border p-3 text-sm">
              <p className="font-medium">{OP_LABELS[x.op_type] || x.op_type}</p>
              <p className="text-xs text-muted-foreground">{x.author_name} · записано {fmt(x.captured_at)} · получено {fmt(x.received_at)} · не влиза автоматично</p>
            </li>
          ))}</ul>
        )}
      </Section>

      <Section icon={Smartphone} title="Устройства" count={c.devices || 0} testId="console-devices">
        {!data.devices.length ? <Empty text="Няма регистрирани устройства." /> : (
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1">Устройство</th><th>Потребител</th><th>Последна синхронизация</th><th>30 дни</th><th /></tr></thead>
            <tbody>{data.devices.map((d) => {
              const r = d.receipts_30d || {};
              return (
                <tr key={d.id} className="border-t border-border" data-testid="console-device">
                  <td className="py-2">{d.label || "Устройство"}<div className="font-mono text-[10px] text-muted-foreground">{d.id.slice(0, 8)}</div></td>
                  <td>{d.last_user_name || "—"}</td>
                  <td>{fmt(d.last_sync_at)}</td>
                  <td className="text-xs">{r.synced || 0} ✓ · {(r.conflict || 0) + (r.late || 0)} ⚠ · {r.rejected || 0} ✕</td>
                  <td className="text-right">{d.revoked_at
                    ? <span className="inline-flex items-center gap-1 text-xs text-destructive"><ShieldOff className="h-3.5 w-3.5" />блокирано {fmt(d.revoked_at)}</span>
                    : <button type="button" onClick={() => setRevoking(d)} className="rounded-md border border-destructive/50 px-2 py-1 text-xs text-destructive hover:bg-destructive/10" data-testid="console-revoke">Блокирай устройство</button>}</td>
                </tr>
              );
            })}</tbody>
          </table></div>
        )}
      </Section>
      {revoking && <RevokeDialog device={revoking} onClose={() => setRevoking(null)} onDone={() => { setRevoking(null); load(); }} />}
    </div>
  );
}
