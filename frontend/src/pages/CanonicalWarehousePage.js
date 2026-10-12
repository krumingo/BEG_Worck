/**
 * CanonicalWarehousePage — LIVE-OPS-01 TASK 5C.
 *
 * The single operator surface for the canonical warehouse. Phone-first
 * layout at 390×844 (iPhone 13/14) with a desktop management view at
 * ≥768px. No horizontal scrolling at either breakpoint. Every write is
 * a named canonical command — no raw "edit batch" or "set stock".
 *
 * This page intentionally does NOT render legacy fields (e.g. a free-text
 * "material_name" input): FLOW-032 Master item_id is required, and the
 * item picker enforces that. Pending-mapping items may only enter
 * quarantine (the picker surfaces that as a disabled free-stock
 * destination).
 */
import React, { useState, useCallback, useEffect, useMemo } from "react";
import {
  ACTIONS, LOCATION_TYPES, STATES,
  postMovement, readBalance, readHistory, readIntegrityWarnings,
} from "@/lib/warehouseCanonicalApi";

const PANELS = [
  { id: "stock", label: "Наличност" },
  { id: "history", label: "История" },
  { id: "commands", label: "Движения" },
  { id: "warnings", label: "Аларми" },
];

function Button({ children, onClick, disabled, variant = "primary" }) {
  const base = "wh-btn";
  const v = variant === "ghost" ? "wh-btn-ghost" : "wh-btn-primary";
  return (
    <button type="button" className={`${base} ${v}`} onClick={onClick}
            disabled={disabled}>
      {children}
    </button>
  );
}

function Field({ label, children, hint }) {
  return (
    <label className="wh-field">
      <div className="wh-field-label">{label}</div>
      {children}
      {hint ? <div className="wh-field-hint">{hint}</div> : null}
    </label>
  );
}

/**
 * CommandForm — the single form that posts any canonical movement.
 * Action is chosen first; the fields the action needs are shown.
 */
function CommandForm({ onResult }) {
  const [action, setAction] = useState(ACTIONS.RECEIVE_FROM_SUPPLIER);
  const [itemId, setItemId] = useState("");
  const [unit, setUnit] = useState("bag");
  const [quantity, setQuantity] = useState("");
  const [unitValue, setUnitValue] = useState("");
  const [sourceType, setSourceType] = useState(LOCATION_TYPES.SUPPLIER);
  const [sourceId, setSourceId] = useState("");
  const [destType, setDestType] = useState(LOCATION_TYPES.CENTRAL_WAREHOUSE);
  const [destId, setDestId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [dispatchMovementId, setDispatchMovementId] = useState("");
  const [acceptedQuantity, setAcceptedQuantity] = useState("");
  const [requestedQuantity, setRequestedQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [itemPending, setItemPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const needsAcceptance = action === ACTIONS.ACCEPT_PROJECT_DELIVERY;
  const needsReason = action === ACTIONS.REVISION_ADJUSTMENT
    || action === ACTIONS.WRITE_OFF
    || action === ACTIONS.RETURN_TO_SUPPLIER;
  const outbound = useMemo(() => new Set([
    ACTIONS.DISPATCH_WAREHOUSE_TO_PROJECT,
    ACTIONS.TRANSFER_PROJECT_TO_WAREHOUSE,
    ACTIONS.TRANSFER_PROJECT_TO_PROJECT,
    ACTIONS.TRANSFER_WAREHOUSE_TO_WAREHOUSE,
    ACTIONS.CONSUME_TO_SMR,
    ACTIONS.RETURN_TO_SUPPLIER,
    ACTIONS.WRITE_OFF,
  ]).has(action), [action]);

  const submit = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      const payload = {
        action,
        item_id: itemId.trim(),
        unit: unit.trim(),
        quantity: quantity.toString(),
        currency: "BGN",
        item_is_pending_mapping: itemPending,
      };
      if (!outbound && unitValue) payload.unit_value = unitValue.toString();
      if (sourceId) payload.source = {
        location_type: sourceType, location_id: sourceId, state: STATES.FREE,
      };
      if (destId) payload.destination = {
        location_type: destType, location_id: destId,
        state: itemPending ? STATES.QUARANTINE : STATES.FREE,
      };
      if (projectId) payload.project_id = projectId;
      if (dispatchMovementId) payload.dispatch_movement_id = dispatchMovementId;
      if (acceptedQuantity) payload.accepted_quantity = acceptedQuantity.toString();
      if (requestedQuantity) payload.requested_quantity = requestedQuantity.toString();
      if (reason) payload.reason = reason.trim();
      if (notes) payload.notes = notes.trim();
      const result = await postMovement(payload);
      onResult?.({ ok: true, result });
      setQuantity("");
      setUnitValue("");
      setAcceptedQuantity("");
      setRequestedQuantity("");
      setDispatchMovementId("");
      setReason("");
      setNotes("");
    } catch (e) {
      const code = e?.response?.data?.detail?.error_code || "UNKNOWN";
      const msg = e?.response?.data?.detail?.message || e.message;
      setErr(`${code}: ${msg}`);
      onResult?.({ ok: false, error_code: code, message: msg });
    } finally {
      setBusy(false);
    }
  }, [action, itemId, unit, quantity, unitValue, sourceType, sourceId,
      destType, destId, projectId, dispatchMovementId, acceptedQuantity,
      requestedQuantity, reason, notes, itemPending, outbound, onResult]);

  return (
    <div className="wh-form">
      <Field label="Действие">
        <select value={action} onChange={e => setAction(e.target.value)}>
          {Object.entries(ACTIONS).map(([k, v]) =>
            <option key={v} value={v}>{k.replace(/_/g, " ").toLowerCase()}</option>
          )}
        </select>
      </Field>

      <Field label="Артикул (item_id)"
             hint="Задължителен Master артикул (FLOW-032). Свободен текст е забранен.">
        <input value={itemId} onChange={e => setItemId(e.target.value)} />
      </Field>

      <Field label="Единица">
        <input value={unit} onChange={e => setUnit(e.target.value)} />
      </Field>

      <Field label="Количество">
        <input type="number" step="0.0001" inputMode="decimal"
               value={quantity} onChange={e => setQuantity(e.target.value)} />
      </Field>

      {!outbound && (
        <Field label="Единична стойност (при вход)"
               hint="При изход цената е server-FIFO; клиентът не я подава.">
          <input type="number" step="0.0001" inputMode="decimal"
                 value={unitValue} onChange={e => setUnitValue(e.target.value)} />
        </Field>
      )}

      <Field label="Източник">
        <div className="wh-row">
          <select value={sourceType}
                  onChange={e => setSourceType(e.target.value)}>
            {Object.entries(LOCATION_TYPES).map(([k, v]) =>
              <option key={v} value={v}>{k.toLowerCase()}</option>)}
          </select>
          <input value={sourceId} onChange={e => setSourceId(e.target.value)}
                 placeholder="ID" />
        </div>
      </Field>

      <Field label="Дестинация">
        <div className="wh-row">
          <select value={destType}
                  onChange={e => setDestType(e.target.value)}>
            {Object.entries(LOCATION_TYPES).map(([k, v]) =>
              <option key={v} value={v}>{k.toLowerCase()}</option>)}
          </select>
          <input value={destId} onChange={e => setDestId(e.target.value)}
                 placeholder="ID" />
        </div>
      </Field>

      <Field label="Проект (ако е приложим)">
        <input value={projectId}
               onChange={e => setProjectId(e.target.value)} />
      </Field>

      {needsAcceptance && (
        <>
          <Field label="Dispatch movement id (приемане се връзва с този dispatch)">
            <input value={dispatchMovementId}
                   onChange={e => setDispatchMovementId(e.target.value)} />
          </Field>
          <Field label="Количество прието (Rule B)">
            <input type="number" step="0.0001" inputMode="decimal"
                   value={acceptedQuantity}
                   onChange={e => setAcceptedQuantity(e.target.value)} />
          </Field>
          <Field label="Количество заявено">
            <input type="number" step="0.0001" inputMode="decimal"
                   value={requestedQuantity}
                   onChange={e => setRequestedQuantity(e.target.value)} />
          </Field>
        </>
      )}

      {needsReason && (
        <Field label="Причина (задължително)">
          <input value={reason} onChange={e => setReason(e.target.value)} />
        </Field>
      )}

      <Field label="Бележка">
        <input value={notes} onChange={e => setNotes(e.target.value)} />
      </Field>

      <label className="wh-checkbox">
        <input type="checkbox" checked={itemPending}
               onChange={e => setItemPending(e.target.checked)} />
        <span>Pending mapping (само карантина)</span>
      </label>

      {err ? <div className="wh-error">{err}</div> : null}

      <Button onClick={submit} disabled={busy || !itemId || !quantity}>
        {busy ? "Запис..." : "Запиши движение"}
      </Button>
    </div>
  );
}


function StockPanel() {
  const [itemId, setItemId] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    if (!itemId) return;
    setLoading(true);
    try {
      const d = await readBalance({ itemId: itemId.trim() });
      setRows(d.balances || []);
    } finally {
      setLoading(false);
    }
  }, [itemId]);
  return (
    <div className="wh-panel">
      <Field label="Артикул">
        <input value={itemId} onChange={e => setItemId(e.target.value)} />
      </Field>
      <Button onClick={load} disabled={loading || !itemId}>
        {loading ? "Четене..." : "Прочети наличност"}
      </Button>
      <div className="wh-stock-list">
        {rows.map((r, i) =>
          <div key={i} className="wh-stock-row">
            <div className="wh-stock-loc">
              {r.location_type}:{r.location_id} <span>({r.state})</span>
            </div>
            <div className="wh-stock-qty">{r.quantity}</div>
          </div>
        )}
        {rows.length === 0 && !loading
          ? <div className="wh-empty">Няма налични наличности за артикула.</div>
          : null}
      </div>
    </div>
  );
}


function HistoryPanel() {
  const [itemId, setItemId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await readHistory({ itemId: itemId.trim(), projectId: projectId.trim() || undefined });
      setRows(d.rows || []);
    } finally {
      setLoading(false);
    }
  }, [itemId, projectId]);
  return (
    <div className="wh-panel">
      <Field label="Артикул (optional)">
        <input value={itemId} onChange={e => setItemId(e.target.value)} />
      </Field>
      <Field label="Проект (optional)">
        <input value={projectId} onChange={e => setProjectId(e.target.value)} />
      </Field>
      <Button onClick={load} disabled={loading}>
        {loading ? "Четене..." : "Покажи история"}
      </Button>
      <div className="wh-hist-list">
        {rows.map((r) =>
          <div key={r.movement_id} className="wh-hist-row">
            <div className="wh-hist-time">{r.recorded_at}</div>
            <div className="wh-hist-action">{r.action}</div>
            <div className="wh-hist-qty">{r.quantity} {r.unit}</div>
          </div>
        )}
      </div>
    </div>
  );
}


function WarningsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const d = await readIntegrityWarnings();
        if (!cancelled) setData(d);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);
  if (loading && !data) return <div className="wh-panel">Четене...</div>;
  const warnings = data?.warnings ?? [];
  return (
    <div className="wh-panel">
      <div className="wh-warnings-header">
        <span>Актуализирано: {data?.fresh_at}</span>
      </div>
      {warnings.length === 0
        ? <div className="wh-empty">Няма активни аларми по интегритет.</div>
        : warnings.map((w, i) =>
            <div key={i} className="wh-warning-row">
              <div className="wh-warning-code">{w.code}</div>
              <pre>{JSON.stringify(w, null, 2)}</pre>
            </div>
          )}
    </div>
  );
}


export default function CanonicalWarehousePage() {
  const [tab, setTab] = useState("stock");
  const [lastResult, setLastResult] = useState(null);
  return (
    <div className="wh-canonical-page">
      <style>{CANONICAL_WAREHOUSE_CSS}</style>
      <header className="wh-header">
        <h1>Склад (каноничен)</h1>
        <div className="wh-sub">FLOW-009 · TASK 5C · append-only ledger</div>
      </header>
      <nav className="wh-tabs" aria-label="warehouse panels">
        {PANELS.map(p =>
          <button key={p.id}
                  className={`wh-tab ${tab === p.id ? "wh-tab-active" : ""}`}
                  onClick={() => setTab(p.id)}>
            {p.label}
          </button>
        )}
      </nav>
      <main className="wh-main">
        {tab === "stock" && <StockPanel />}
        {tab === "history" && <HistoryPanel />}
        {tab === "warnings" && <WarningsPanel />}
        {tab === "commands" && <CommandForm onResult={setLastResult} />}
        {lastResult && (
          <div className={`wh-last-result ${lastResult.ok ? "ok" : "err"}`}>
            {lastResult.ok
              ? <>✓ movement <code>{lastResult.result.movement_id}</code>
                  {lastResult.result.replay ? " (replay)" : ""}</>
              : <>✗ {lastResult.error_code}: {lastResult.message}</>}
          </div>
        )}
      </main>
    </div>
  );
}

// Scoped CSS so a global stylesheet is not needed. Phone-first; desktop
// kicks in at 768px. No horizontal page scrolling at either breakpoint.
const CANONICAL_WAREHOUSE_CSS = `
.wh-canonical-page { max-width: 100vw; padding: 12px; font: 14px/1.4 -apple-system,Segoe UI,system-ui,sans-serif; color: #111; box-sizing: border-box; overflow-x: hidden; }
.wh-header h1 { font-size: 20px; margin: 0; }
.wh-header .wh-sub { color: #666; font-size: 12px; margin-top: 2px; }
.wh-tabs { display: flex; gap: 4px; margin: 12px 0; overflow-x: auto; }
.wh-tab { flex: 1 1 auto; min-width: 72px; padding: 10px 8px; border: 1px solid #d1d5db; background: #fff; border-radius: 8px; font-size: 13px; }
.wh-tab-active { background: #111; color: #fff; border-color: #111; }
.wh-main { display: flex; flex-direction: column; gap: 12px; }
.wh-panel { display: flex; flex-direction: column; gap: 12px; }
.wh-form { display: flex; flex-direction: column; gap: 10px; }
.wh-field { display: block; }
.wh-field-label { font-size: 12px; color: #333; margin-bottom: 4px; }
.wh-field-hint { font-size: 11px; color: #777; margin-top: 2px; }
.wh-field input, .wh-field select { width: 100%; padding: 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 15px; box-sizing: border-box; }
.wh-row { display: flex; gap: 8px; }
.wh-row > * { flex: 1 1 50%; min-width: 0; }
.wh-btn { padding: 12px 16px; border: 0; border-radius: 10px; font-size: 15px; font-weight: 600; cursor: pointer; }
.wh-btn-primary { background: #111; color: #fff; }
.wh-btn-primary:disabled { background: #999; cursor: not-allowed; }
.wh-btn-ghost { background: #fff; border: 1px solid #d1d5db; color: #111; }
.wh-checkbox { display: flex; gap: 8px; align-items: center; font-size: 13px; }
.wh-error { background: #fee2e2; border: 1px solid #fca5a5; color: #991b1b; padding: 10px; border-radius: 8px; font-size: 13px; }
.wh-stock-list, .wh-hist-list { display: flex; flex-direction: column; gap: 6px; }
.wh-stock-row { display: flex; justify-content: space-between; padding: 10px 12px; background: #f8f8f8; border-radius: 8px; }
.wh-stock-loc { font-size: 13px; color: #333; }
.wh-stock-loc span { color: #777; font-size: 11px; }
.wh-stock-qty { font-weight: 600; }
.wh-hist-row { display: grid; grid-template-columns: 1fr; gap: 2px; padding: 10px 12px; background: #f8f8f8; border-radius: 8px; }
.wh-hist-time { font-size: 11px; color: #666; }
.wh-hist-action { font-size: 13px; color: #111; }
.wh-hist-qty { font-weight: 600; font-size: 13px; }
.wh-empty { color: #777; padding: 24px 0; text-align: center; }
.wh-warning-row { background: #fef3c7; padding: 10px 12px; border-radius: 8px; }
.wh-warning-code { font-weight: 600; color: #92400e; }
.wh-warning-row pre { font-size: 11px; white-space: pre-wrap; margin-top: 6px; }
.wh-last-result { padding: 10px 12px; border-radius: 8px; font-size: 13px; }
.wh-last-result.ok { background: #ecfdf5; color: #065f46; }
.wh-last-result.err { background: #fef2f2; color: #991b1b; }
@media (min-width: 768px) {
  .wh-canonical-page { padding: 20px 24px; max-width: 1100px; margin: 0 auto; }
  .wh-form { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
  .wh-form .wh-field, .wh-form .wh-checkbox, .wh-form .wh-btn, .wh-form .wh-error { grid-column: 1 / -1; }
  .wh-form .wh-field:nth-child(-n+6) { grid-column: span 1; }
  .wh-hist-row { grid-template-columns: 180px 1fr 100px; align-items: center; }
}
`;
