// LAB-AKORD-01 (FLOW-028, Р100) — „Акорд: количества“: въвеждане, одобрение и отказ на
// измереното количество по акордните редове от „Отчет на труда“, и единичната цена труд по СМР
// (само финансови роли, R31). Backend: backend/app/routes/labor_quantities.py.
// Всеки запис носи Idempotency-Key (R29) и AuditEvent; нищо не се трие — поправката е нова версия.
import { useCallback, useEffect, useMemo, useState } from "react";
import API from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { CheckCircle2, Loader2, Save, XCircle } from "lucide-react";
import { apiErrorText, createKeyHolder, idempotencyHeaders } from "@/lib/idempotency";
import {
  RECORD_LABELS, STATE_LABELS, akordFormula, canApproveRole, canSetPrice, parsePositive,
} from "@/lib/laborQuantities";

const STATE_VARIANT = { approved: "default", pending: "secondary", rejected: "destructive", no_quantity: "outline" };

function useKey() {
  return useMemo(() => createKeyHolder(), []);
}

async function send(holder, call) {
  try {
    const res = await call(idempotencyHeaders(holder.get()));
    holder.settle(null);
    return res;
  } catch (err) {
    holder.settle(err);
    throw err;
  }
}

function LineCard({ item, packages, showPrice, canApprove, onDone }) {
  const [qty, setQty] = useState("");
  const [pkg, setPkg] = useState(item.approved?.execution_package_id || packages[0]?.id || "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const enterKey = useKey();
  const decideKey = useKey();
  const locked = item.payroll_status !== "none";
  const unit = packages.find((p) => p.id === pkg)?.unit || item.approved?.unit || "";

  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); toast.success(ok); setQty(""); setReason(""); onDone(); }
    catch (err) { toast.error(apiErrorText(err, "Грешка")); }
    finally { setBusy(false); }
  };

  const enter = () => {
    const q = parsePositive(qty);
    if (q === null) { toast.error("Въведете количество (число > 0)"); return; }
    run(() => send(enterKey, (cfg) => API.post("/labor-quantities",
      { line_id: item.line_id, quantity: q, execution_package_id: pkg || null }, cfg)),
    item.approved ? "Поправката е въведена — чака одобрение" : "Количеството е въведено — чака одобрение");
  };
  const approve = () => run(() => send(decideKey, (cfg) => API.post(
    `/labor-quantities/${item.pending.id}/approve`, { execution_package_id: pkg || null }, cfg)),
  "Количеството е одобрено");
  const reject = (rec) => {
    if (!reason.trim()) { toast.error("Напишете причина за отказа"); return; }
    run(() => send(decideKey, (cfg) => API.post(`/labor-quantities/${rec.id}/reject`, { reason }, cfg)),
      "Количеството е отказано");
  };

  const show = (rec) => (showPrice ? akordFormula(rec.approved_quantity ?? rec.entered_quantity, rec.unit, rec.piece_rate)
    : `${rec.approved_quantity ?? rec.entered_quantity} ${rec.unit || ""}`);

  return (
    <div className="rounded-xl border bg-card p-3 space-y-3" data-testid={`akord-line-${item.line_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium truncate">{item.worker_name || item.worker_id}</div>
          <div className="text-xs text-muted-foreground">
            {item.date} · {item.smr_type || "—"} · {item.hours ?? 0} ч · часове: {item.line_status === "APPROVED" ? "одобрени" : "подадени"}
          </div>
        </div>
        <Badge variant={STATE_VARIANT[item.state] || "outline"}>{STATE_LABELS[item.state] || item.state}</Badge>
      </div>
      {item.approved && <div className="text-sm">Одобрено: <b>{show(item.approved)}</b></div>}
      {item.pending && <div className="text-sm">Чака одобрение: <b>{show(item.pending)}</b>
        {item.pending.replaces && <span className="text-muted-foreground"> (поправка)</span>}</div>}
      {locked && <p className="text-xs text-muted-foreground">
        Редът е {item.payroll_status === "paid" ? "платен" : "във ведомост"} — количеството е заключено;
        поправка само през заплатите (отваряне / сторно).</p>}
      {!locked && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {packages.length > 0 && (
            <select value={pkg} onChange={(e) => setPkg(e.target.value)} disabled={busy}
                    className="h-11 w-full rounded-md border bg-background px-2 text-sm" data-testid="akord-pkg">
              {packages.map((p) => <option key={p.id} value={p.id}>{p.activity_name} {p.unit ? `(${p.unit})` : ""}</option>)}
            </select>
          )}
          {!item.pending && (
            <>
              <Input inputMode="decimal" placeholder={`Количество ${unit}`} value={qty}
                     onChange={(e) => setQty(e.target.value)} className="h-11" data-testid="akord-qty" />
              <Button onClick={enter} disabled={busy} className="h-11" data-testid="akord-enter">
                {busy ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Save className="w-4 h-4 mr-2" />}
                {item.approved ? "Въведи поправка" : "Въведи количество"}
              </Button>
            </>
          )}
        </div>
      )}
      {!locked && canApprove && (item.pending || item.approved) && (
        <div className="flex flex-col sm:flex-row gap-2">
          {item.pending && (
            <Button onClick={approve} disabled={busy || item.line_status !== "APPROVED"} className="h-11 flex-1"
                    data-testid="akord-approve" title={item.line_status !== "APPROVED" ? "Първо се одобряват часовете" : ""}>
              <CheckCircle2 className="w-4 h-4 mr-2" />Одобри
            </Button>
          )}
          <div className="flex flex-1 gap-2">
            <Input placeholder="Причина за отказ" value={reason} onChange={(e) => setReason(e.target.value)} className="h-11" />
            <Button variant="outline" onClick={() => reject(item.pending || item.approved)} disabled={busy}
                    className="h-11" data-testid="akord-reject">
              <XCircle className="w-4 h-4 mr-1" />{item.pending ? "Откажи" : "Откажи одобреното"}
            </Button>
          </div>
        </div>
      )}
      {item.history.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary>История ({item.history.length})</summary>
          <ul className="mt-1 space-y-1">
            {item.history.map((h) => (
              <li key={h.id}>
                v{h.quantity_version}: {show(h)} — {RECORD_LABELS[h.status] || h.status}; въвел {h.entered_by_name || h.entered_by}
                {h.approved_by && `, одобрил ${h.approved_by_name || h.approved_by}`}
                {h.rejected_by && `, отказал ${h.rejected_by_name || h.rejected_by}: ${h.reject_reason || ""}`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function PriceRow({ pkg, onSaved }) {
  const [rate, setRate] = useState(pkg.labor_piece_rate ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const holder = useKey();
  const save = async () => {
    const r = parsePositive(rate);
    if (r === null) { toast.error("Цената трябва да е число > 0"); return; }
    if (!reason.trim()) { toast.error("Посочете основание (договор, анекс…)"); return; }
    setBusy(true);
    try {
      await send(holder, (cfg) => API.put(`/labor-terms/${pkg.id}`, { labor_piece_rate: r, reason }, cfg));
      toast.success("Единичната цена труд е записана");
      onSaved();
    } catch (err) { toast.error(apiErrorText(err, "Грешка")); } finally { setBusy(false); }
  };
  return (
    <div className="rounded-xl border bg-card p-3 space-y-2" data-testid={`akord-price-${pkg.id}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium truncate">{pkg.activity_name}</div>
        <span className="text-xs text-muted-foreground">версия {pkg.labor_terms_version || 0}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <Input inputMode="decimal" placeholder={`EUR / ${pkg.unit || "ед."}`} value={rate}
               onChange={(e) => setRate(e.target.value)} className="h-11" data-testid="akord-rate" />
        <Input placeholder="Основание (договор, анекс…)" value={reason} onChange={(e) => setReason(e.target.value)} className="h-11" />
        <Button onClick={save} disabled={busy} className="h-11" data-testid="akord-rate-save">
          {busy ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Save className="w-4 h-4 mr-2" />}Запиши
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">Промяна на цената не променя вече одобрени количества.</p>
    </div>
  );
}

export default function LaborQuantitiesPage() {
  const { user } = useAuth();
  const role = user?.role;
  const showPrice = canSetPrice(role);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [tab, setTab] = useState("lines");
  const [data, setData] = useState(null);
  const [terms, setTerms] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    API.get("/projects").then((r) => {
      const list = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      setProjects(list);
      if (list.length) setProjectId((cur) => cur || list[0].id);
    }).catch(() => setProjects([]));
  }, []);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      setData((await API.get("/labor-quantities", { params: { project_id: projectId } })).data);
      if (showPrice) setTerms((await API.get("/labor-terms", { params: { project_id: projectId } })).data);
    } catch (err) { toast.error(apiErrorText(err, "Грешка при зареждане")); } finally { setLoading(false); }
  }, [projectId, showPrice]);

  useEffect(() => { load(); }, [load]);

  const canApprove = canApproveRole(role) && !!data?.can_approve;
  const items = data?.items || [];

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 px-4 py-4" data-testid="labor-quantities-page">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">Акорд: количества</h1>
        <p className="text-sm text-muted-foreground">
          Акордът се плаща само по одобрено измерено количество × договорена единична цена труд.
          Одобрява друг човек — не работникът и не този, който е въвел количеството.
        </p>
      </div>
      <select value={projectId} onChange={(e) => setProjectId(e.target.value)}
              className="h-11 w-full rounded-md border bg-background px-2 text-sm" data-testid="akord-project">
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name || p.code || p.id}</option>)}
      </select>
      {showPrice && (
        <div className="flex gap-2">
          <Button variant={tab === "lines" ? "default" : "outline"} className="h-10 flex-1" onClick={() => setTab("lines")}>
            Редове {data ? `(${data.waiting} чакат)` : ""}
          </Button>
          <Button variant={tab === "prices" ? "default" : "outline"} className="h-10 flex-1" onClick={() => setTab("prices")}>
            Единични цени труд
          </Button>
        </div>
      )}
      {loading && <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 animate-spin" /></div>}
      {!loading && tab === "lines" && (
        <div className="space-y-3">
          {items.length === 0 && <p className="text-sm text-muted-foreground">Няма акордни редове за този обект.</p>}
          {items.map((it) => (
            <LineCard key={`${it.line_id}-${it.history.length}-${it.state}`} item={it} packages={data.packages || []}
                      showPrice={showPrice} canApprove={canApprove} onDone={load} />
          ))}
        </div>
      )}
      {!loading && tab === "prices" && showPrice && (
        <div className="space-y-3">
          {(terms?.items || []).length === 0 && <p className="text-sm text-muted-foreground">Няма СМР пакети за обекта.</p>}
          {(terms?.items || []).map((p) => <PriceRow key={`${p.id}-${p.labor_terms_version || 0}`} pkg={p} onSaved={load} />)}
        </div>
      )}
    </div>
  );
}
