// LAB-02 (R33) — „Количества и акорд“: одобрение на изработено количество по СМР
// (Admin / Owner / SiteManager на обекта) и акордни цени по СМР (само финансови роли, R31).
// Backend: backend/app/routes/labor_quantities.py. Всеки запис на пари/одобрение носи
// Idempotency-Key (R29) и AuditEvent; нищо не се трие.
import { useCallback, useEffect, useState } from "react";
import API from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Loader2, CheckCircle2, PauseCircle, Save } from "lucide-react";
import {
  COST_TYPE_LABELS, PAY_TYPE_LABELS, STATE_LABELS, akordFormula, canApproveQuantities,
  canSeePieceRates, newIdempotencyKey, parseQuantity,
} from "@/lib/laborQuantities";

const errText = (err) => {
  const d = err?.response?.data?.detail;
  if (!d) return "Грешка";
  return typeof d === "string" ? d : (d.message || JSON.stringify(d));
};

function ApprovalCard({ item, packages, showPrice, onDone }) {
  const [qty, setQty] = useState(item.approval?.approved_quantity ?? item.quantity ?? "");
  const [pkg, setPkg] = useState(item.approval?.execution_package_id || item.suggested_package_id || packages[0]?.id || "");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const unit = packages.find((p) => p.id === pkg)?.unit || "";

  const approve = async () => {
    const q = parseQuantity(qty);
    if (q === null) { toast.error("Въведете количество (число ≥ 0)"); return; }
    if (!pkg) { toast.error("Изберете СМР"); return; }
    setBusy(true);
    try {
      await API.post("/labor-quantities/approve", {
        report_id: item.report_id, entry_id: item.entry_id, report_version: item.report_version,
        approved_quantity: q, execution_package_id: pkg, note,
        // LAB-02-C (FG-101): a correction names the approval it replaces
        replaces_approval_id: item.approval?.id || null,
      }, { headers: { "Idempotency-Key": newIdempotencyKey() } });
      toast.success("Количеството е одобрено");
      onDone();
    } catch (err) { toast.error(errText(err)); } finally { setBusy(false); }
  };

  const markDowntime = async () => {
    if (!reason.trim()) { toast.error("Напишете причина за престоя"); return; }
    setBusy(true);
    try {
      await API.post("/labor-quantities/classify", {
        report_id: item.report_id, entry_id: item.entry_id, report_version: item.report_version,
        cost_type: "DOWNTIME", reason,
      }, { headers: { "Idempotency-Key": newIdempotencyKey() } });
      toast.success("Редът е отбелязан като престой");
      onDone();
    } catch (err) { toast.error(errText(err)); } finally { setBusy(false); }
  };

  return (
    <div className="rounded-xl border bg-card p-3 space-y-3" data-testid={`lq-item-${item.report_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium truncate">{item.worker_name || item.worker_id}</div>
          <div className="text-xs text-muted-foreground">{item.date} · {item.smr_type || "—"} · {item.hours ?? 0} ч</div>
        </div>
        <Badge variant={item.state === "approved" ? "default" : "secondary"}>{STATE_LABELS[item.state] || item.state}</Badge>
      </div>
      <div className="text-sm">
        Въведено от работника: <b>{item.quantity ?? "—"}</b>
        {item.approval && (
          <span className="ml-2 text-emerald-700">
            одобрено: {showPrice ? akordFormula(item.approval.approved_quantity, item.approval.unit, item.approval.piece_rate)
                                  : `${item.approval.approved_quantity} ${item.approval.unit || ""}`}
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <label className="text-xs text-muted-foreground">Количество {unit && `(${unit})`}
          <Input inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} className="h-11 mt-1"
                 data-testid="lq-qty" />
        </label>
        <label className="text-xs text-muted-foreground">СМР
          <select value={pkg} onChange={(e) => setPkg(e.target.value)}
                  className="mt-1 h-11 w-full rounded-md border bg-background px-2 text-sm" data-testid="lq-pkg">
            {packages.map((p) => <option key={p.id} value={p.id}>{p.activity_name} {p.unit ? `(${p.unit})` : ""}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted-foreground">Бележка
          <Input value={note} onChange={(e) => setNote(e.target.value)} className="h-11 mt-1" />
        </label>
      </div>
      <div className="flex flex-col sm:flex-row gap-2">
        <Button onClick={approve} disabled={busy} className="h-11 flex-1" data-testid="lq-approve">
          {busy ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <CheckCircle2 className="w-4 h-4 mr-2" />}
          {item.approval ? "Коригирай одобрението" : "Одобри количеството"}
        </Button>
        <div className="flex flex-1 gap-2">
          <Input placeholder="Причина за престой" value={reason} onChange={(e) => setReason(e.target.value)} className="h-11" />
          <Button variant="outline" onClick={markDowntime} disabled={busy} className="h-11" data-testid="lq-downtime">
            <PauseCircle className="w-4 h-4 mr-1" />{COST_TYPE_LABELS.DOWNTIME}
          </Button>
        </div>
      </div>
    </div>
  );
}

function PieceRateRow({ pkg, onSaved }) {
  const [payType, setPayType] = useState(pkg.labor_pay_type || "");
  const [rate, setRate] = useState(pkg.labor_piece_rate ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    const r = rate === "" ? null : parseQuantity(rate);
    if (rate !== "" && r === null) { toast.error("Цената трябва да е число ≥ 0"); return; }
    setBusy(true);
    try {
      await API.put(`/labor-terms/${pkg.id}`, { labor_pay_type: payType || null, labor_piece_rate: r, reason },
                    { headers: { "Idempotency-Key": newIdempotencyKey() } });
      toast.success("Акордната цена е записана");
      onSaved();
    } catch (err) { toast.error(errText(err)); } finally { setBusy(false); }
  };
  return (
    <div className="rounded-xl border bg-card p-3 space-y-2" data-testid={`lt-row-${pkg.id}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium truncate">{pkg.activity_name}</div>
        <span className="text-xs text-muted-foreground">версия {pkg.labor_terms_version || 0}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-2">
        <select value={payType} onChange={(e) => setPayType(e.target.value)}
                className="h-11 rounded-md border bg-background px-2 text-sm" data-testid="lt-paytype">
          <option value="">— по профила —</option>
          {Object.entries(PAY_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <Input inputMode="decimal" placeholder={`EUR / ${pkg.unit || "ед."}`} value={rate}
               onChange={(e) => setRate(e.target.value)} className="h-11" data-testid="lt-rate" />
        <Input placeholder="Основание (договор, анекс…)" value={reason} onChange={(e) => setReason(e.target.value)} className="h-11" />
        <Button onClick={save} disabled={busy} className="h-11" data-testid="lt-save">
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
  const showPrice = canSeePieceRates(role);
  const canApprove = canApproveQuantities(role);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [tab, setTab] = useState(canApprove ? "approve" : "rates");
  const [pending, setPending] = useState(null);
  const [terms, setTerms] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    API.get("/projects").then((r) => {
      const list = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      setProjects(list);
      if (list.length && !projectId) setProjectId(list[0].id);
    }).catch(() => setProjects([]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      if (canApprove) setPending((await API.get("/labor-quantities/pending", { params: { project_id: projectId } })).data);
      if (showPrice) setTerms((await API.get("/labor-terms", { params: { project_id: projectId } })).data);
    } catch (err) { toast.error(errText(err)); } finally { setLoading(false); }
  }, [projectId, canApprove, showPrice]);

  useEffect(() => { load(); }, [load]);

  const items = (pending?.items || []).filter((i) => i.state !== "no_quantity" || i.approval);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 px-4 py-4" data-testid="labor-quantities-page">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">Количества и акорд</h1>
        <p className="text-sm text-muted-foreground">
          Акордът се плаща само по одобрено количество × акордна цена по СМР.
        </p>
      </div>
      <select value={projectId} onChange={(e) => setProjectId(e.target.value)}
              className="h-11 w-full rounded-md border bg-background px-2 text-sm" data-testid="lq-project">
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name || p.code || p.id}</option>)}
      </select>
      <div className="flex gap-2">
        {canApprove && (
          <Button variant={tab === "approve" ? "default" : "outline"} className="h-10 flex-1" onClick={() => setTab("approve")}>
            За одобрение {pending ? `(${pending.waiting})` : ""}
          </Button>
        )}
        {showPrice && (
          <Button variant={tab === "rates" ? "default" : "outline"} className="h-10 flex-1" onClick={() => setTab("rates")}>
            Акордни цени
          </Button>
        )}
      </div>
      {loading && <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 animate-spin" /></div>}
      {!loading && tab === "approve" && canApprove && (
        <div className="space-y-3">
          {items.length === 0 && <p className="text-sm text-muted-foreground">Няма редове с въведено количество.</p>}
          {items.map((it) => (
            <ApprovalCard key={`${it.report_id}-${it.entry_id || ""}-${it.report_version}`} item={it}
                          packages={pending.packages || []} showPrice={showPrice} onDone={load} />
          ))}
        </div>
      )}
      {!loading && tab === "rates" && showPrice && (
        <div className="space-y-3">
          {(terms?.items || []).length === 0 && <p className="text-sm text-muted-foreground">Няма СМР пакети за обекта.</p>}
          {(terms?.items || []).map((p) => <PieceRateRow key={`${p.id}-${p.labor_terms_version || 0}`} pkg={p} onSaved={load} />)}
        </div>
      )}
      {!canApprove && !showPrice && <p className="text-sm text-muted-foreground">Нямате достъп до този екран.</p>}
    </div>
  );
}
