/**
 * LIVE-OPS-01 / TASK 5B — Заявки за материали (safe-write core).
 *
 * Phone-first: create, quick view, submit, approve/reject when allowed.
 * Desktop-first: list, filters, detail with history and review context.
 *
 * What the screen promises, and the tests hold it to:
 *   * every write is a NAMED command (create / draft / submit / approve /
 *     reject / cancel) — there is no raw status edit anywhere;
 *   * every write carries an Idempotency-Key; a retry after a network failure
 *     reuses the SAME key, so a double tap or a weak signal never acts twice;
 *   * buttons follow the server's Permission Service answer, and a refusal is
 *     shown with its reason — never hidden as a silent no-op;
 *   * quantities are the server's: requested, approved, cancelled, accepted
 *     and remaining are shown apart, and remaining is never computed here;
 *   * a line without a confirmed Master material is visibly "чака мапване";
 *   * no warehouse, asset, QR or migration control exists on this screen.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import API from "@/lib/api";

export const STATE_BG = {
  draft: "Чернова",
  submitted: "Подадена",
  approved: "Одобрена",
  rejected: "Отхвърлена",
  cancelled: "Анулирана",
};
const STATE_COLORS = {
  draft: "bg-gray-500/20 text-gray-300",
  submitted: "bg-blue-500/20 text-blue-300",
  approved: "bg-emerald-500/20 text-emerald-300",
  rejected: "bg-red-500/20 text-red-300",
  cancelled: "bg-zinc-500/20 text-zinc-300",
};
const PRIORITY_BG = { low: "Нисък", normal: "Нормален", high: "Висок", urgent: "Спешен" };

/** Human reasons for a Permission Service refusal (FLOW-002 reason codes). */
export const REASON_BG = {
  NO_ASSIGNMENT: "Нямате роля в този обект.",
  ACTION_NOT_ALLOWED: "Ролята ви в обекта не позволява това действие.",
  SCOPE_MISMATCH: "Правата ви са за друг обект.",
  ASSIGNMENT_REVOKED: "Правата ви са оттеглени.",
  ASSIGNMENT_EXPIRED: "Правата ви са изтекли.",
  ASSIGNMENT_INACTIVE: "Правата ви не са активни.",
  ASSIGNMENT_INVALID_DATA: "Правата ви са невалидни — свържете се с администратор.",
  PERMISSION_SERVICE_NOT_ENFORCED: "Записът е изключен, докато правата не се проверяват (enforce).",
  PERMISSION_EVALUATION_UNAVAILABLE: "Правата не могат да бъдат проверени в момента.",
  INVALID_STATE: "Не е възможно в текущото състояние.",
};

const ACTION_BG = {
  edit_draft: "Редактирай",
  submit: "Подай",
  approve: "Одобри",
  reject: "Откажи",
  cancel: "Анулирай",
};

function newKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return "mr-" + crypto.randomUUID();
  return "mr-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
}

function fmtQty(v) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

function fmtDate(v) {
  if (!v) return "—";
  try { return new Date(v).toLocaleDateString("bg-BG"); } catch (e) { return v; }
}

function errorText(err) {
  const detail = err?.response?.data?.detail;
  if (!err?.response) return "Няма връзка със сървъра. Опитайте пак — повторението е безопасно.";
  if (detail && typeof detail === "object") {
    if (detail.error_code === "PERMISSION_DENIED") {
      return "Отказано: " + (REASON_BG[detail.reason] || detail.reason || "нямате право.");
    }
    return detail.message || detail.error_code;
  }
  return typeof detail === "string" ? detail : "Грешка " + err.response.status;
}

/** True while the viewport is phone-sized. Read from the window, so it is testable. */
export function useIsPhone() {
  const get = () => (typeof window !== "undefined" ? window.innerWidth < 768 : false);
  const [phone, setPhone] = useState(get);
  useEffect(() => {
    const on = () => setPhone(get());
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return phone;
}

function StateBadge({ state, legacy }) {
  if (!state) {
    return (
      <span className="text-[11px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-300" data-testid="legacy-status">
        Стар статус: {legacy || "—"} (непотвърден)
      </span>
    );
  }
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded ${STATE_COLORS[state] || ""}`} data-testid="state-badge">
      {STATE_BG[state] || state}
    </span>
  );
}

function MappingBadge({ line }) {
  if (line.mapping_status === "confirmed") {
    return <span className="text-[10px] text-emerald-400">Master ✓</span>;
  }
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300" data-testid="unmapped-badge">
      Чака мапване
    </span>
  );
}

// ═══════════════════════════════════════════════════════════════ form
const emptyLine = () => ({ item_id: null, item_label: "", material_name: "", qty_requested: "", unit: "бр" });

function LineEditor({ line, index, onChange, onRemove, writesEnabled }) {
  const [q, setQ] = useState("");
  const [options, setOptions] = useState(null);
  const search = async () => {
    try {
      const r = await API.get("/material-requests/item-options", { params: { q } });
      setOptions(r.data?.items || []);
    } catch (e) { setOptions([]); }
  };
  return (
    <div className="rounded-lg border border-border p-3 space-y-2" data-testid={`line-editor-${index}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Ред {index + 1}</span>
        {line.item_id ? <MappingBadge line={{ mapping_status: "confirmed" }} />
          : <MappingBadge line={{ mapping_status: "pending_mapping" }} />}
      </div>
      <input
        className="w-full bg-background border border-border rounded px-3 py-2 text-sm"
        placeholder="Материал (както го наричате)"
        value={line.material_name}
        onChange={(e) => onChange({ ...line, material_name: e.target.value })}
        data-testid={`line-name-${index}`}
      />
      <div className="flex gap-2">
        <input
          className="flex-1 bg-background border border-border rounded px-3 py-2 text-sm"
          placeholder="Търси Master материал"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          data-testid={`line-search-${index}`}
        />
        <button type="button" className="px-3 py-2 text-sm rounded border border-border" onClick={search}
          disabled={!writesEnabled} data-testid={`line-search-btn-${index}`}>
          Търси
        </button>
      </div>
      {options && (
        <div className="text-sm space-y-1" data-testid={`line-options-${index}`}>
          {options.length === 0 && (
            <p className="text-xs text-muted-foreground">
              Няма съвпадение. Редът остава „чака мапване“ — офисът ще го свърже с Master материал.
            </p>
          )}
          {options.map((o) => (
            <button type="button" key={o.id} className="block w-full text-left px-2 py-1 rounded hover:bg-muted"
              onClick={() => { onChange({ ...line, item_id: o.id, item_label: o.display_name,
                material_name: line.material_name || o.display_name }); setOptions(null); }}
              data-testid={`line-option-${o.id}`}>
              {o.display_name}
            </button>
          ))}
        </div>
      )}
      {line.item_id && (
        <p className="text-xs text-emerald-400">
          Master: {line.item_label || line.item_id}{" "}
          <button type="button" className="underline" onClick={() => onChange({ ...line, item_id: null, item_label: "" })}>
            махни
          </button>
        </p>
      )}
      <div className="flex gap-2">
        <input type="number" inputMode="decimal" min="0" step="any"
          className="w-28 bg-background border border-border rounded px-3 py-2 text-sm"
          placeholder="Кол."
          value={line.qty_requested}
          onChange={(e) => onChange({ ...line, qty_requested: e.target.value })}
          data-testid={`line-qty-${index}`} />
        <input className="w-24 bg-background border border-border rounded px-3 py-2 text-sm"
          placeholder="Мярка" value={line.unit}
          onChange={(e) => onChange({ ...line, unit: e.target.value })}
          data-testid={`line-unit-${index}`} />
        <button type="button" className="ml-auto text-xs text-red-400" onClick={onRemove}>Премахни</button>
      </div>
    </div>
  );
}

function RequestForm({ initial, projects, isPhone, writesEnabled, onCancel, onSave, busy, error, onRetry }) {
  const [f, setF] = useState(initial);
  const [warehouses, setWarehouses] = useState(null);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  useEffect(() => {
    if (f.destination_type === "warehouse" && warehouses === null) {
      API.get("/warehouses").then((r) => setWarehouses(r.data?.items || r.data || []))
        .catch(() => setWarehouses([]));
    }
  }, [f.destination_type, warehouses]);

  const lineOk = (l) => Number(l.qty_requested) > 0 && l.unit && (l.item_id || l.material_name.trim());
  const valid = f.project_id && f.lines.length > 0 && f.lines.every(lineOk);
  const shell = isPhone
    ? "fixed inset-0 z-50 bg-background overflow-y-auto p-4"
    : "rounded-xl border border-border bg-card p-5";

  return (
    <div className={shell} data-testid="request-form" data-layout={isPhone ? "phone" : "desktop"}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">{f.id ? "Редакция на чернова" : "Нова заявка"}</h2>
        <button type="button" className="text-sm text-muted-foreground" onClick={onCancel}>Затвори</button>
      </div>
      <div className="space-y-3">
        <label className="block text-sm">
          Обект
          <select className="mt-1 w-full bg-background border border-border rounded px-3 py-2"
            value={f.project_id} disabled={!!f.id}
            onChange={(e) => set("project_id", e.target.value)} data-testid="form-project">
            <option value="">— изберете —</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.code} {p.name}</option>)}
          </select>
          {!f.id && projects.length === 0 && (
            <span className="block text-xs text-amber-300 mt-1" data-testid="no-project-options">
              Нямате право да създавате заявки в нито един обект.
            </span>
          )}
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-sm">
            Нужна дата
            <input type="date" className="mt-1 w-full bg-background border border-border rounded px-3 py-2"
              value={f.needed_date || ""} onChange={(e) => set("needed_date", e.target.value)}
              data-testid="form-needed-date" />
          </label>
          <label className="block text-sm">
            Приоритет
            <select className="mt-1 w-full bg-background border border-border rounded px-3 py-2"
              value={f.priority} onChange={(e) => set("priority", e.target.value)} data-testid="form-priority">
              {Object.entries(PRIORITY_BG).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
        <fieldset className="text-sm">
          <legend>Доставка</legend>
          <label className="mr-4"><input type="radio" name="dest" checked={f.destination_type === "project"}
            onChange={() => set("destination_type", "project")} data-testid="dest-project" /> Директно на обекта</label>
          <label><input type="radio" name="dest" checked={f.destination_type === "warehouse"}
            onChange={() => set("destination_type", "warehouse")} data-testid="dest-warehouse" /> В склад</label>
        </fieldset>
        {f.destination_type === "warehouse" && (
          <select className="w-full bg-background border border-border rounded px-3 py-2 text-sm"
            value={f.destination_id || ""} onChange={(e) => set("destination_id", e.target.value)}
            data-testid="form-warehouse">
            <option value="">— изберете склад —</option>
            {(warehouses || []).map((w) => (
              <option key={w.id} value={w.id}>{w.name || "Склад без име"}{w.code ? ` (${w.code})` : ""}</option>
            ))}
          </select>
        )}
        <textarea className="w-full bg-background border border-border rounded px-3 py-2 text-sm" rows={2}
          placeholder="Причина / за кое СМР" value={f.reason || ""} onChange={(e) => set("reason", e.target.value)}
          data-testid="form-reason" />
        <div className="space-y-2">
          {f.lines.map((l, i) => (
            <LineEditor key={l.id || i} line={l} index={i} writesEnabled={writesEnabled}
              onChange={(nl) => set("lines", f.lines.map((x, j) => (j === i ? nl : x)))}
              onRemove={() => set("lines", f.lines.filter((_, j) => j !== i))} />
          ))}
          <button type="button" className="text-sm text-primary" onClick={() => set("lines", [...f.lines, emptyLine()])}
            data-testid="add-line">
            + Добави материал
          </button>
        </div>
        {error && (
          <div className="rounded border border-red-500/40 bg-red-500/10 p-2 text-sm text-red-300" data-testid="form-error">
            {error.text}
            {error.retryable && (
              <button type="button" className="ml-2 underline" onClick={onRetry} data-testid="form-retry">Опитай пак</button>
            )}
          </div>
        )}
        <button type="button"
          className="w-full py-3 rounded-lg bg-primary text-primary-foreground font-medium disabled:opacity-50"
          disabled={!valid || busy || !writesEnabled} onClick={() => onSave(f)} data-testid="form-save">
          {busy ? "Записване…" : f.id ? "Запази черновата" : "Създай чернова"}
        </button>
        {!writesEnabled && (
          <p className="text-xs text-amber-300">Записът е изключен — вижте съобщението горе.</p>
        )}
      </div>
    </div>
  );
}

function toPayload(f, { create }) {
  const body = {
    needed_date: f.needed_date || null,
    priority: f.priority || "normal",
    reason: f.reason || null,
    notes: f.notes || null,
    destination_type: f.destination_type || null,
    destination_id: f.destination_type === "warehouse" ? f.destination_id || null : null,
    lines: f.lines.map((l) => {
      const out = {
        material_name: l.material_name || null,
        qty_requested: Number(l.qty_requested),
        unit: l.unit,
      };
      if (l.id) out.id = l.id;
      if (l.item_id) out.item_id = l.item_id;
      return out;
    }),
  };
  if (create) body.project_id = f.project_id;
  else body.expected_version = f.version;
  return body;
}

function fromRequest(r) {
  return {
    id: r.id, version: r.version, project_id: r.project_id, needed_date: r.needed_date || "",
    priority: r.priority || "normal", reason: r.reason || "", notes: r.notes || "",
    destination_type: r.destination_type || "project", destination_id: r.destination_id || "",
    lines: (r.lines || []).map((l) => ({
      id: l.id, item_id: l.item_id || null, item_label: l.item_id ? l.material_name : "",
      material_name: l.material_name || "", qty_requested: l.qty_requested, unit: l.unit,
    })),
  };
}

// ═══════════════════════════════════════════════════════════════ detail
function Detail({ view, isPhone, onCommand, busy, error, onRetry, onEdit, onClose, loadedAt }) {
  const r = view.request;
  const allowed = view.allowed_actions || {};
  const [reason, setReason] = useState("");
  const [approveQty, setApproveQty] = useState({});
  const [mode, setMode] = useState(null); // "reject" | "cancel" | "approve"
  const shell = isPhone ? "fixed inset-0 z-40 bg-background overflow-y-auto p-4" : "rounded-xl border border-border bg-card p-5";
  const actionButton = (code, onClick) => {
    const a = allowed[code] || { allowed: false };
    if (a.reason === "INVALID_STATE") return null;
    return (
      <div key={code} className={isPhone ? "w-full" : ""}>
        <button type="button" disabled={!a.allowed || busy} onClick={onClick}
          className={`px-4 py-2 rounded-lg text-sm font-medium border border-border disabled:opacity-40 ${isPhone ? "w-full py-3" : ""}`}
          data-testid={`action-${code}`}>
          {ACTION_BG[code]}
        </button>
        {!a.allowed && (
          <p className="text-[11px] text-amber-300 mt-1" data-testid={`denied-${code}`}>
            {REASON_BG[a.reason] || a.reason}
          </p>
        )}
      </div>
    );
  };

  return (
    <div className={shell} data-testid="request-detail" data-layout={isPhone ? "phone" : "desktop"}>
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <h2 className="text-lg font-semibold font-mono">{r.request_number}</h2>
          <p className="text-sm text-muted-foreground">{r.project_code} {r.project_name}</p>
        </div>
        <div className="text-right space-y-1">
          <StateBadge state={r.request_state} legacy={r.legacy_status} />
          <div><button type="button" className="text-xs text-muted-foreground" onClick={onClose}>Затвори</button></div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm mb-3">
        <div>Нужна дата: <b>{fmtDate(r.needed_date)}</b></div>
        <div>Приоритет: <b>{PRIORITY_BG[r.priority] || r.priority || "—"}</b></div>
        <div>Доставка: <b>{r.destination_type === "warehouse" ? "В склад" : r.destination_type === "project" ? "Директно на обекта" : "—"}</b></div>
        <div>Версия: <b>{r.version}</b></div>
      </div>
      {r.unmapped_lines > 0 && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-sm text-amber-200 mb-3" data-testid="unmapped-warning">
          {r.unmapped_lines} ред(а) чакат мапване към Master материал. Одобрението е блокирано, докато офисът
          не ги свърже. Нищо не се създава автоматично.
        </div>
      )}
      {r.has_partial_facts && (
        <div className="rounded border border-blue-500/40 bg-blue-500/10 p-2 text-sm text-blue-200 mb-3" data-testid="partial-info">
          Частично изпълнение: остатъкът е показан по редове.
        </div>
      )}
      <div className={isPhone ? "space-y-2" : "overflow-x-auto"} data-testid="detail-lines">
        {isPhone ? r.lines.map((l) => (
          <div key={l.id} className="rounded border border-border p-2 text-sm" data-testid={`dline-${l.id}`}>
            <div className="flex justify-between"><span>{l.material_name}</span><MappingBadge line={l} /></div>
            <div className="text-xs text-muted-foreground">
              Заявено {fmtQty(l.qty_requested)} {l.unit} · Одобрено {fmtQty(l.qty_approved)} · Прието {fmtQty(l.facts?.accepted_qty)}
              {" "}· Анулирано {fmtQty(l.qty_cancelled)}
            </div>
            <div className="text-sm">Остатък: <b data-testid={`remaining-${l.id}`}>{fmtQty(l.remaining_qty)}</b> {l.unit}</div>
          </div>
        )) : (
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-muted-foreground text-left">
              <th className="py-1">Материал</th><th>Master</th><th>Заявено</th><th>Одобрено</th>
              <th>Анулирано</th><th>Прието</th><th>Остатък</th><th>Мярка</th>
            </tr></thead>
            <tbody>
              {r.lines.map((l) => (
                <tr key={l.id} className="border-t border-border" data-testid={`dline-${l.id}`}>
                  <td className="py-1">{l.material_name}</td><td><MappingBadge line={l} /></td>
                  <td>{fmtQty(l.qty_requested)}</td><td>{fmtQty(l.qty_approved)}</td>
                  <td>{fmtQty(l.qty_cancelled)}</td><td>{fmtQty(l.facts?.accepted_qty)}</td>
                  <td><b data-testid={`remaining-${l.id}`}>{fmtQty(l.remaining_qty)}</b>
                    {l.over_qty > 0 && <span className="text-amber-300"> (+{fmtQty(l.over_qty)} над)</span>}</td>
                  <td>{l.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground mt-2" data-testid="facts-source">
        Количествата „прието“ и „остатък“ са изчислени от сървъра по складовия регистър (само четене);
        заредено {loadedAt ? loadedAt.toLocaleTimeString("bg-BG") : "—"}.
      </p>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-2 text-sm text-red-300 mt-3" data-testid="action-error">
          {error.text}
          {error.retryable && (
            <button type="button" className="ml-2 underline" onClick={onRetry} data-testid="action-retry">Опитай пак</button>
          )}
        </div>
      )}

      {mode === "approve" && (
        <div className="mt-3 space-y-2" data-testid="approve-panel">
          {r.lines.map((l) => (
            <label key={l.id} className="flex items-center gap-2 text-sm">
              <span className="flex-1">{l.material_name}</span>
              <input type="number" min="0" step="any" className="w-24 bg-background border border-border rounded px-2 py-1"
                defaultValue={l.qty_requested}
                onChange={(e) => setApproveQty((x) => ({ ...x, [l.id]: e.target.value }))}
                data-testid={`approve-qty-${l.id}`} />
              <span>{l.unit}</span>
            </label>
          ))}
          <button type="button" className="w-full py-2 rounded-lg bg-emerald-600 text-white" disabled={busy}
            onClick={() => onCommand("approve", {
              lines: Object.entries(approveQty).filter(([, v]) => v !== "")
                .map(([line_id, v]) => ({ line_id, qty_approved: Number(v) })),
            })} data-testid="approve-confirm">
            Потвърди одобрението
          </button>
        </div>
      )}
      {(mode === "reject" || mode === "cancel") && (
        <div className="mt-3 space-y-2" data-testid={`${mode}-panel`}>
          <textarea className="w-full bg-background border border-border rounded px-3 py-2 text-sm" rows={2}
            placeholder="Причина (задължително)" value={reason} onChange={(e) => setReason(e.target.value)}
            data-testid="reason-input" />
          {mode === "cancel" && r.request_state === "approved" && (
            <p className="text-xs text-muted-foreground">Анулира се само оставащото количество; изпълненото остава в историята.</p>
          )}
          <button type="button" className="w-full py-2 rounded-lg bg-red-600 text-white disabled:opacity-50"
            disabled={!reason.trim() || busy} onClick={() => onCommand(mode, { reason: reason.trim() })}
            data-testid="reason-confirm">
            {mode === "reject" ? "Потвърди отказа" : "Потвърди анулирането"}
          </button>
        </div>
      )}

      <div className={`mt-4 ${isPhone ? "space-y-2" : "flex flex-wrap gap-3"}`} data-testid="detail-actions">
        {actionButton("edit_draft", onEdit)}
        {actionButton("submit", () => onCommand("submit", {}))}
        {actionButton("approve", () => setMode("approve"))}
        {actionButton("reject", () => setMode("reject"))}
        {actionButton("cancel", () => setMode("cancel"))}
      </div>

      <div className="mt-5" data-testid="history">
        <h3 className="text-sm font-semibold mb-2">История</h3>
        {view.history?.status !== "ok" ? (
          <p className="text-xs text-muted-foreground">{view.history?.message || "Историята не е налична."}</p>
        ) : (
          <ol className="space-y-1 text-xs">
            {view.history.events.map((e) => (
              <li key={e.event_id} className="flex gap-2" data-testid="history-event">
                <span className="text-muted-foreground">{e.occurred_at ? new Date(e.occurred_at).toLocaleString("bg-BG") : ""}</span>
                <span>{e.action}</span>
                <span className={e.result === "success" ? "text-emerald-400" : "text-amber-300"}>{e.result}</span>
                {e.error_code && <span className="text-amber-300">{e.error_code}</span>}
                <span className="text-muted-foreground">{e.actor_id}</span>
              </li>
            ))}
          </ol>
        )}
        <p className="text-[10px] text-muted-foreground mt-1">Източник: каноничен AuditEvent.</p>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════ page
export default function MaterialRequestsPage() {
  const isPhone = useIsPhone();
  const { requestId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [requests, setRequests] = useState([]);
  const [projects, setProjects] = useState([]);
  const [writeStatus, setWriteStatus] = useState({ writes_enabled: false });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [filters, setFilters] = useState({ state: "", project: "", q: "" });
  const [view, setView] = useState(null);
  const [viewLoadedAt, setViewLoadedAt] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const keys = useRef({});
  const lastCall = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      // Create options come from the SAME Permission Service authority the create
      // command enforces — not from the legacy team list (CODEX C01 F-02).
      const [rq, ws, pr] = await Promise.all([
        API.get("/material-requests"),
        API.get("/material-requests/write-status").catch(() => ({ data: { writes_enabled: false } })),
        API.get("/material-requests/project-options").catch(() => ({ data: { projects: [] } })),
      ]);
      setRequests(Array.isArray(rq.data) ? rq.data : []);
      setWriteStatus(ws.data || { writes_enabled: false });
      setProjects(Array.isArray(pr.data?.projects) ? pr.data.projects : []);
    } catch (e) {
      setLoadError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const openView = useCallback(async (id) => {
    setError(null);
    try {
      const r = await API.get(`/material-requests/${id}/view`);
      setView(r.data);
      setViewLoadedAt(new Date());
    } catch (e) {
      setView(null);
      setLoadError(errorText(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (requestId) openView(requestId); }, [requestId, openView]);
  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setForm({ project_id: searchParams.get("project") || "", needed_date: "", priority: "normal",
        destination_type: "project", destination_id: "", reason: "", notes: "", lines: [emptyLine()] });
    }
  }, [searchParams]);

  /**
   * Send one command. The key is kept per intent until the server gives a
   * definitive answer, so "Опитай пак" after a lost response replays safely.
   */
  const send = useCallback(async (intent, method, path, body) => {
    const key = keys.current[intent] || newKey();
    keys.current[intent] = key;
    lastCall.current = { intent, method, path, body };
    setBusy(true);
    setError(null);
    try {
      const r = await API.request({
        method, url: path, data: body,
        headers: { "Idempotency-Key": key, "X-Client-Channel": isPhone ? "phone" : "desktop" },
      });
      delete keys.current[intent];
      return r.data;
    } catch (e) {
      const status = e?.response?.status;
      const retryable = !e?.response || status >= 500 || (status === 409 &&
        e.response.data?.detail?.error_code === "CONCURRENT_COMMAND");
      if (!retryable) delete keys.current[intent];
      setError({ text: errorText(e), retryable });
      return null;
    } finally {
      setBusy(false);
    }
  }, [isPhone]);

  const retry = async () => {
    const c = lastCall.current;
    if (!c) return;
    const out = await send(c.intent, c.method, c.path, c.body);
    if (out) await after(out);
  };

  const after = async (out) => {
    setForm(null);
    await load();
    if (out?.request?.id) await openView(out.request.id);
  };

  const saveForm = async (f) => {
    const out = f.id
      ? await send(`draft:${f.id}`, "patch", `/material-requests/${f.id}/draft`, toPayload(f, { create: false }))
      : await send("create", "post", "/material-requests", toPayload(f, { create: true }));
    if (out) await after(out);
  };

  const command = async (code, body) => {
    const id = view.request.id;
    const out = await send(`${code}:${id}`, "post", `/material-requests/${id}/${code}`, body);
    if (out) await after(out);
  };

  // Filter by any project that has a visible request (read scope), not only by
  // projects this user may create in.
  const filterProjects = Object.values(requests.reduce((acc, r) => {
    if (r.project_id && !acc[r.project_id]) {
      acc[r.project_id] = { id: r.project_id, code: r.project_code, name: r.project_name };
    }
    return acc;
  }, {}));

  const shown = requests.filter((r) =>
    (!filters.state || r.request_state === filters.state || (filters.state === "legacy" && !r.request_state))
    && (!filters.project || r.project_id === filters.project)
    && (!filters.q || `${r.request_number} ${r.project_code} ${r.project_name}`.toLowerCase()
      .includes(filters.q.toLowerCase())));

  const startCreate = () => {
    setError(null);
    setForm({ project_id: "", needed_date: "", priority: "normal", destination_type: "project",
      destination_id: "", reason: "", notes: "", lines: [emptyLine()] });
  };

  return (
    <div className={isPhone ? "p-3" : "p-6 max-w-[1400px]"} data-testid="material-requests-page"
      data-layout={isPhone ? "phone" : "desktop"}>
      <div className="flex items-center justify-between mb-4 gap-2">
        <div>
          <h1 className="text-xl font-bold">Заявки за материали</h1>
          {!isPhone && <p className="text-sm text-muted-foreground">Чернова → подадена → одобрена / отхвърлена. Складът не се променя оттук.</p>}
        </div>
        <button type="button" className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
          disabled={!writeStatus.writes_enabled} onClick={startCreate} data-testid="new-request">
          + Нова заявка
        </button>
      </div>

      {!writeStatus.writes_enabled && !loading && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200 mb-4" data-testid="writes-disabled">
          {writeStatus.message || "Записът на заявки е изключен."} Можете само да преглеждате.
        </div>
      )}
      {loadError && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300 mb-4" data-testid="load-error">
          {loadError} <button type="button" className="underline" onClick={load}>Опитай пак</button>
        </div>
      )}

      {form && (
        <div className="mb-4">
          <RequestForm initial={form} projects={projects} isPhone={isPhone} writesEnabled={writeStatus.writes_enabled}
            busy={busy} error={error} onRetry={retry}
            onCancel={() => { setForm(null); setError(null); }} onSave={saveForm} />
        </div>
      )}

      {!isPhone && (
        <div className="flex flex-wrap gap-2 mb-3" data-testid="filters">
          <input className="bg-card border border-border rounded px-3 py-2 text-sm" placeholder="Търсене…"
            value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} data-testid="filter-q" />
          <select className="bg-card border border-border rounded px-3 py-2 text-sm" value={filters.state}
            onChange={(e) => setFilters({ ...filters, state: e.target.value })} data-testid="filter-state">
            <option value="">Всички състояния</option>
            {Object.entries(STATE_BG).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            <option value="legacy">Стар статус</option>
          </select>
          <select className="bg-card border border-border rounded px-3 py-2 text-sm" value={filters.project}
            onChange={(e) => setFilters({ ...filters, project: e.target.value })} data-testid="filter-project">
            <option value="">Всички обекти</option>
            {filterProjects.map((p) => <option key={p.id} value={p.id}>{p.code} {p.name}</option>)}
          </select>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground" data-testid="loading">Зареждане…</p>
      ) : (
        <div className={isPhone ? "" : "grid grid-cols-1 xl:grid-cols-[1fr_520px] gap-4"}>
          {isPhone ? (
            <div className="space-y-2" data-testid="request-cards">
              {shown.length === 0 && <p className="text-sm text-muted-foreground" data-testid="empty">Няма заявки.</p>}
              {shown.map((r) => (
                <button type="button" key={r.id} className="w-full text-left rounded-lg border border-border p-3"
                  onClick={() => navigate(`/material-requests/${r.id}`)} data-testid={`req-card-${r.id}`}>
                  <div className="flex justify-between"><b className="font-mono">{r.request_number}</b>
                    <StateBadge state={r.request_state} legacy={r.legacy_status} /></div>
                  <div className="text-xs text-muted-foreground">{r.project_code} {r.project_name} · нужно {fmtDate(r.needed_date)}</div>
                  <div className="text-xs">Остатък общо: {fmtQty(r.remaining_qty_total)}
                    {r.unmapped_lines > 0 && <span className="text-amber-300"> · {r.unmapped_lines} чакат мапване</span>}</div>
                </button>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="request-table">
              <table className="w-full text-sm">
                <thead><tr className="text-xs text-muted-foreground text-left">
                  <th className="p-2">Номер</th><th>Обект</th><th>Състояние</th><th>Нужна дата</th>
                  <th>Редове</th><th>Остатък</th><th>Мапване</th></tr></thead>
                <tbody>
                  {shown.length === 0 && (
                    <tr><td colSpan={7} className="p-6 text-center text-muted-foreground" data-testid="empty">Няма заявки.</td></tr>
                  )}
                  {shown.map((r) => (
                    <tr key={r.id} className="border-t border-border cursor-pointer hover:bg-muted/30"
                      onClick={() => navigate(`/material-requests/${r.id}`)} data-testid={`req-row-${r.id}`}>
                      <td className="p-2 font-mono">{r.request_number}</td>
                      <td>{r.project_code} {r.project_name}</td>
                      <td><StateBadge state={r.request_state} legacy={r.legacy_status} /></td>
                      <td>{fmtDate(r.needed_date)}</td>
                      <td>{r.lines?.length || 0}</td>
                      <td>{fmtQty(r.remaining_qty_total)}</td>
                      <td>{r.unmapped_lines > 0 ? <span className="text-amber-300">{r.unmapped_lines} чакат</span> : "✓"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {view && (
            <Detail view={view} isPhone={isPhone} busy={busy} error={error} onRetry={retry}
              loadedAt={viewLoadedAt}
              onCommand={command}
              onEdit={() => { setError(null); setForm(fromRequest(view.request)); }}
              onClose={() => { setView(null); navigate("/material-requests"); }} />
          )}
        </div>
      )}
    </div>
  );
}
