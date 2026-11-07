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
import { stateLabel } from "@/lib/warehouseLabels";
import { useAuth } from "@/contexts/AuthContext";
import {
  allowedCommandActions, canReadWarehouseHistory, canReadWarehouseStock,
} from "@/lib/warehouseCanonicalAccess";

// 5C-C19 F-6: each panel names the right it needs; the page shows only the
// panels the session role holds (same catalog as the Permission Service).
const PANELS = [
  { id: "stock", label: "Наличност", needs: "stock" },
  { id: "history", label: "История", needs: "history" },
  { id: "commands", label: "Движения", needs: "write" },
  { id: "warnings", label: "Аларми", needs: "stock" },
];

/** The panels a role may open (5C-C19 F-6). */
export function visiblePanels(role) {
  const rights = {
    stock: canReadWarehouseStock(role),
    history: canReadWarehouseHistory(role),
    write: allowedCommandActions(role).length > 0,
  };
  return PANELS.filter((p) => rights[p.needs]);
}

/** Render an API failure as `CODE: message` (never as an empty result). */
function describeError(e) {
  const code = e?.response?.data?.detail?.error_code
    || (e?.response?.status ? `HTTP_${e.response.status}` : "NETWORK_ERROR");
  const msg = e?.response?.data?.detail?.message || e?.message || "";
  return msg ? `${code}: ${msg}` : code;
}

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
function CommandForm({ onResult, allowedActions }) {
  // 5C-C19 F-6: only the canonical actions the role holds are offered.
  const actions = allowedActions && allowedActions.length
    ? allowedActions : Object.values(ACTIONS);
  const [action, setAction] = useState(actions[0]);
  const [itemId, setItemId] = useState("");
  const [unit, setUnit] = useState("bag");
  const [quantity, setQuantity] = useState("");
  const [unitValue, setUnitValue] = useState("");
  const [sourceType, setSourceType] = useState(LOCATION_TYPES.SUPPLIER);
  const [sourceId, setSourceId] = useState("");
  const [destType, setDestType] = useState(LOCATION_TYPES.CENTRAL_WAREHOUSE);
  const [destId, setDestId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [smrId, setSmrId] = useState("");
  const [dispatchMovementId, setDispatchMovementId] = useState("");
  const [acceptedQuantity, setAcceptedQuantity] = useState("");
  // 5C-C25 (Р18): a returned lot is accepted into the warehouse QUARANTINE.
  const [acceptState, setAcceptState] = useState(STATES.FREE);
  const [requestedQuantity, setRequestedQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [itemPending, setItemPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const needsAcceptance = action === ACTIONS.ACCEPT_PROJECT_DELIVERY;
  // 5C-C19 F-4: a dispatch always goes to in_transit/pending (Rule B); the
  // project is credited only by its acceptance. The server enforces it; the
  // form does not even offer another destination.
  const isDispatch = action === ACTIONS.DISPATCH_WAREHOUSE_TO_PROJECT;
  // 5C-C21 F-13 (Р11) + 5C-C25 (Р18): EVERY transfer (warehouse→warehouse,
  // project→warehouse, project→project) is in transit; the receiving
  // location is the `transfer_target`, credited only on acceptance. A return
  // to a warehouse targets its QUARANTINE (quality check before reuse).
  const isWhTransfer = action === ACTIONS.TRANSFER_WAREHOUSE_TO_WAREHOUSE;
  const isReturn = action === ACTIONS.TRANSFER_PROJECT_TO_WAREHOUSE;
  const isProjectTransfer = action === ACTIONS.TRANSFER_PROJECT_TO_PROJECT;
  const isTransfer = isWhTransfer || isReturn || isProjectTransfer;
  const inTransit = isDispatch || isTransfer;
  const targetTypes = isProjectTransfer
    ? [LOCATION_TYPES.PROJECT, LOCATION_TYPES.SUBPROJECT]
    : [LOCATION_TYPES.CENTRAL_WAREHOUSE, LOCATION_TYPES.SMALL_WAREHOUSE];
  const targetType = targetTypes.includes(destType) ? destType : targetTypes[0];
  const targetState = isReturn ? STATES.QUARANTINE : STATES.FREE;
  // 5C-C19 F-6: consumption is bound to an SMR.
  const isConsume = action === ACTIONS.CONSUME_TO_SMR;
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
      if (inTransit) {
        payload.destination = {
          location_type: LOCATION_TYPES.IN_TRANSIT, location_id: "pending",
          state: STATES.IN_TRANSIT,
        };
        if (isTransfer && destId) payload.transfer_target = {
          location_type: targetType, location_id: destId, state: targetState,
        };
      } else if (destId) payload.destination = {
        location_type: destType, location_id: destId,
        state: (itemPending || (needsAcceptance && acceptState === STATES.QUARANTINE))
          ? STATES.QUARANTINE : STATES.FREE,
      };
      if (projectId) payload.project_id = projectId;
      if (isConsume && smrId) payload.smr_id = smrId.trim();
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
      setSmrId("");
    } catch (e) {
      const code = e?.response?.data?.detail?.error_code || "UNKNOWN";
      const msg = e?.response?.data?.detail?.message || e.message;
      setErr(`${code}: ${msg}`);
      onResult?.({ ok: false, error_code: code, message: msg });
    } finally {
      setBusy(false);
    }
  }, [action, itemId, unit, quantity, unitValue, sourceType, sourceId,
      destType, destId, projectId, smrId, dispatchMovementId, acceptedQuantity,
      requestedQuantity, reason, notes, itemPending, outbound, isDispatch,
      isTransfer, targetType, targetState, acceptState, needsAcceptance,
      inTransit, isConsume, onResult]);

  return (
    <div className="wh-form">
      <Field label="Действие">
        <select value={action} onChange={e => setAction(e.target.value)}
                data-testid="wh-action-select">
          {actions.map((v) =>
            <option key={v} value={v}>{v.replace(/_/g, " ")}</option>
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

      {inTransit ? (
        <Field label="Дестинация"
               hint={isTransfer
                 ? "Трансферът остава „в транзит“, докато целта не го приеме (Rule B, Р18)."
                 : "Изпращането остава „в транзит“, докато обектът не го приеме (Rule B)."}>
          <div className="wh-fixed" data-testid="wh-dispatch-in-transit">
            {stateLabel("in_transit")} · очаква приемане
          </div>
        </Field>
      ) : null}
      {isTransfer ? (
        <Field label={isProjectTransfer
                 ? "Целеви обект (кредитира се само при приемане)"
                 : "Целеви склад (кредитира се само при приемане)"}
               hint={isReturn
                 ? "Връщането влиза в КАРАНТИНА на склада (проверка на качеството, Р18)."
                 : undefined}>
          <div className="wh-row">
            <select value={targetType} data-testid="wh-transfer-target-type"
                    onChange={e => setDestType(e.target.value)}>
              {targetTypes.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <input value={destId} onChange={e => setDestId(e.target.value)}
                   placeholder="ID" data-testid="wh-transfer-target-id" />
          </div>
        </Field>
      ) : inTransit ? null : (
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
      )}

      <Field label={isDispatch ? "Проект (за кой обект е изпращането)" : "Проект (ако е приложим)"}>
        <input value={projectId}
               onChange={e => setProjectId(e.target.value)} />
      </Field>

      {isConsume && (
        <Field label="СМР (smr_id)"
               hint="Разходът се записва по тази СМР позиция.">
          <input value={smrId} onChange={e => setSmrId(e.target.value)}
                 data-testid="wh-smr-id" />
        </Field>
      )}

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
          <Field label="Приемане в"
                 hint="Върнат от обект материал се приема в карантина (Р18).">
            <select value={acceptState} data-testid="wh-accept-state"
                    onChange={e => setAcceptState(e.target.value)}>
              <option value={STATES.FREE}>свободна наличност</option>
              <option value={STATES.QUARANTINE}>карантина</option>
            </select>
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

      <Button onClick={submit}
              disabled={busy || !itemId || !quantity || (isConsume && !smrId.trim())}>
        {busy ? "Запис..." : "Запиши движение"}
      </Button>
    </div>
  );
}


function StockPanel() {
  const [itemId, setItemId] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    if (!itemId) return;
    setLoading(true);
    setError("");
    try {
      const d = await readBalance({ itemId: itemId.trim() });
      setRows(d.balances || []);
    } catch (e) {
      setRows([]);
      setError(describeError(e));
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
              {r.location_type === "in_transit"
                ? stateLabel("in_transit") : r.location_type}:{r.location_id}{" "}
              <span data-testid="wh-stock-state">({stateLabel(r.state)})</span>
            </div>
            <div className="wh-stock-qty">{r.quantity}</div>
          </div>
        )}
        {error
          ? <div className="wh-error" role="alert">Наличността не е прочетена — {error}</div>
          : null}
        {rows.length === 0 && !loading && !error
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
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await readHistory({ itemId: itemId.trim(), projectId: projectId.trim() || undefined });
      setRows(d.rows || []);
    } catch (e) {
      setRows([]);
      setError(describeError(e));
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
      {error
        ? <div className="wh-error" role="alert">Историята не е прочетена — {error}</div>
        : null}
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


/**
 * WarningsPanel — FLOW-009 integrity alarms.
 *
 * 5C-C19 F-3: "no alarms" is shown ONLY for a successful answer that really
 * carries an empty `warnings` list. A failed request (500, 403, network) or a
 * malformed answer is an error state — never a false all-clear.
 */
export function WarningsPanel({ load = readIntegrityWarnings }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const d = await load();
        if (cancelled) return;
        if (!d || !Array.isArray(d.warnings)) {
          setData(null);
          setError("INVALID_RESPONSE: отговорът няма списък с аларми");
        } else {
          setData(d);
        }
      } catch (e) {
        if (!cancelled) {
          setData(null);
          setError(describeError(e));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [load]);
  if (loading) return <div className="wh-panel">Четене...</div>;
  if (error) {
    return (
      <div className="wh-panel">
        <div className="wh-error" role="alert" data-testid="wh-warnings-error">
          Алармите не са проверени — състоянието е НЕИЗВЕСТНО. {error}
        </div>
      </div>
    );
  }
  const warnings = data.warnings;
  return (
    <div className="wh-panel">
      <div className="wh-warnings-header">
        <span>Актуализирано: {data.fresh_at}</span>
      </div>
      {warnings.length === 0
        ? <div className="wh-empty" data-testid="wh-warnings-empty">Няма активни аларми по интегритет.</div>
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
  const { user } = useAuth();
  const role = user?.role;
  const panels = useMemo(() => visiblePanels(role), [role]);
  const allowedActions = useMemo(() => allowedCommandActions(role), [role]);
  const [tab, setTab] = useState(panels[0]?.id ?? "stock");
  const [lastResult, setLastResult] = useState(null);
  const activeTab = panels.some((p) => p.id === tab) ? tab : panels[0]?.id;
  return (
    <div className="wh-canonical-page">
      <style>{CANONICAL_WAREHOUSE_CSS}</style>
      <header className="wh-header">
        <h1>Склад (каноничен)</h1>
        <div className="wh-sub">FLOW-009 · TASK 5C · append-only ledger</div>
      </header>
      <nav className="wh-tabs" aria-label="warehouse panels">
        {panels.map(p =>
          <button key={p.id} data-testid={`wh-tab-${p.id}`}
                  className={`wh-tab ${activeTab === p.id ? "wh-tab-active" : ""}`}
                  onClick={() => setTab(p.id)}>
            {p.label}
          </button>
        )}
      </nav>
      <main className="wh-main">
        {activeTab === "stock" && <StockPanel />}
        {activeTab === "history" && <HistoryPanel />}
        {activeTab === "warnings" && <WarningsPanel />}
        {activeTab === "commands" && allowedActions.length > 0 && (
          <CommandForm onResult={setLastResult} allowedActions={allowedActions} />
        )}
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
.wh-fixed { padding: 10px; border: 1px dashed #d1d5db; border-radius: 8px; font-size: 14px; color: #333; }
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
