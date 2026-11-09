/**
 * MaterialWastePanel — Material variance: planned vs issued vs waste.
 *
 * 5C-C23 F-15: the waste column and the summary include the canonical
 * write-offs from the project (read by the backend through the shared
 * material-cost helper, no second register). They are listed separately
 * and marked „отписване от склада"; the manual register entries stay.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { createIdempotencyHolder, idempotencyHeaders, apiErrorText } from "@/lib/idempotency";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Package, Loader2, ChevronDown, ChevronRight, Plus, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CFG = {
  ok: { color: "text-emerald-400", dot: "bg-emerald-500" },
  warning: { color: "text-amber-400", dot: "bg-amber-500" },
  overuse: { color: "text-red-400", dot: "bg-red-500" },
};

const WASTE_TYPES = [
  { value: "damaged", label: "Повреден" },
  { value: "broken", label: "Счупен" },
  { value: "lost", label: "Загубен" },
  { value: "unused", label: "Неизползван" },
  { value: "returnable", label: "За връщане" },
  { value: "other", label: "Друго" },
];

export default function MaterialWastePanel({ projectId }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const EMPTY = { item_id: "", material_name: "", qty: "", unit: "бр", waste_type: "damaged", notes: "" };
  const [form, setForm] = useState(EMPTY);
  const [onProject, setOnProject] = useState([]);
  const [evidence, setEvidence] = useState(null);
  const [saving, setSaving] = useState(false);
  // main 4bca18a (SEC-01): one key per endpoint + payload until the server answers.
  const [wasteKeys] = useState(() => createIdempotencyHolder());
  // the evidence is uploaded ONCE per chosen file: a retry re-sends the same
  // payload (same file_id) → the same Idempotency-Key → never a second write-off.
  const [uploaded, setUploaded] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/material-waste`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  // The materials that can be written off: Master items with stock ON the project.
  const openAdd = async () => {
    setShowAdd(true);
    try {
      const res = await API.get(`/project-material-ledger/${projectId}`);
      const rows = (res?.data?.ledger || []).filter(m => m.item_id && (m.remaining_on_project || 0) > 0);
      setOnProject(rows);
    } catch { setOnProject([]); }
  };

  const pickItem = (itemId) => {
    const m = onProject.find(r => r.item_id === itemId);
    setForm(f => ({ ...f, item_id: itemId, material_name: m?.material_name || "", unit: m?.unit || f.unit }));
  };

  const handleAdd = async () => {
    if (!form.item_id || !form.qty) { toast.error(t("materialWaste.fillRequired")); return; }
    if (!evidence) { toast.error(t("materialWaste.evidenceRequired")); return; }
    setSaving(true);
    let err = null;
    try {
      let fileId = uploaded && uploaded.file === evidence ? uploaded.id : null;
      if (!fileId) {
        const fd = new FormData();
        fd.append("file", evidence);
        fd.append("context_type", "project");
        fd.append("context_id", projectId);
        const up = await API.post("/media/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
        fileId = up.data.id;
        setUploaded({ file: evidence, id: fileId });
      }
      const reason = (WASTE_TYPES.find(w => w.value === form.waste_type) || {}).label || form.waste_type;
      const endpoint = `/projects/${projectId}/material-waste`;
      const payload = { ...form, qty: parseFloat(form.qty), reason, file_ids: [fileId] };
      await API.post(endpoint, payload, idempotencyHeaders(wasteKeys.keyFor(endpoint, payload)));
      wasteKeys.done();
      setUploaded(null);
      toast.success(t("materialWaste.added"));
      setShowAdd(false);
      setForm(EMPTY);
      setEvidence(null);
      load();
    } catch (e) {
      err = e;
      toast.error(wasteErrorText(e, t));
    } finally {
      // a refusal from the server ends this submission's key; a lost
      // connection keeps it (the retry is the same request)
      if (err && err.response) wasteKeys.done();
      setSaving(false);
    }
  };

  if (loading) return <div className="flex items-center justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const { summary, materials } = data;
  const writeoffs = data.writeoffs || [];

  return (
    <div className="space-y-3" data-testid="material-waste-panel">
      <div className="flex items-center justify-between">
        <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-2">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          <Package className="w-4 h-4 text-orange-400" />
          <span className="font-semibold text-sm">{t("materialWaste.title")}</span>
          {summary.overuse_count > 0 && <Badge className="bg-red-500/20 text-red-400 text-[9px]">{summary.overuse_count} overuse</Badge>}
        </button>
        <Button size="sm" variant="outline" onClick={openAdd} data-testid="add-waste-btn">
          <Plus className="w-3.5 h-3.5 mr-1" /> {t("materialWaste.addWaste")}
        </Button>
      </div>

      {expanded && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div><p className="font-mono font-bold">{summary.materials_count}</p><p className="text-[9px] text-muted-foreground">{t("materialWaste.materials")}</p></div>
            <div><p className="font-mono font-bold">{summary.total_waste_items}</p><p className="text-[9px] text-muted-foreground">{t("materialWaste.wasteEntries")}</p></div>
            <div><p className="font-mono font-bold">{summary.total_waste_qty}</p><p className="text-[9px] text-muted-foreground">{t("materialWaste.wasteQty")}</p></div>
            <div><p className={`font-mono font-bold ${summary.overuse_count > 0 ? "text-red-400" : "text-emerald-400"}`}>{summary.overuse_count}</p><p className="text-[9px] text-muted-foreground">{t("materialWaste.overuse")}</p></div>
          </div>

          {/* 5C-C23 F-15: manual entries vs canonical write-offs */}
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground" data-testid="waste-sources">
            <span data-testid="waste-manual-count">{t("materialWaste.manualEntries")}: <span className="font-mono">{summary.manual_waste_items ?? summary.total_waste_items}</span> · <span className="font-mono">{summary.manual_waste_qty ?? summary.total_waste_qty}</span></span>
            <span data-testid="waste-writeoff-count">{t("materialWaste.writeOffs")}: <span className="font-mono">{summary.writeoff_items ?? 0}</span> · <span className="font-mono">{summary.writeoff_qty ?? 0}</span></span>
          </div>

          {/* Header */}
          <div className="flex items-center gap-2 text-[9px] text-muted-foreground px-1">
            <span className="w-2" /><span className="flex-1">{t("materialWaste.material")}</span>
            <span className="w-12 text-right">{t("materialWaste.plan")}</span>
            <span className="w-12 text-right">{t("materialWaste.issued")}</span>
            <span className="w-12 text-right">{t("materialWaste.waste")}</span>
            <span className="w-14 text-right">{t("materialWaste.variance")}</span>
          </div>

          {/* Rows */}
          <div className="max-h-[200px] overflow-y-auto space-y-0.5">
            {materials.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-4">{t("materialWaste.noData")}</p>
            ) : materials.map((m, i) => {
              const st = STATUS_CFG[m.status] || STATUS_CFG.ok;
              return (
                <div key={i} className="flex items-center gap-2 py-1 px-1 text-xs rounded hover:bg-muted/10">
                  <span className={`w-2 h-2 rounded-full ${st.dot} flex-shrink-0`} />
                  <span className="flex-1 truncate">{m.material_name}</span>
                  <span className="font-mono w-12 text-right text-muted-foreground">{m.planned_qty}</span>
                  <span className="font-mono w-12 text-right">{m.issued_qty}</span>
                  <span className="font-mono w-12 text-right text-orange-400">{m.wasted_qty > 0 ? m.wasted_qty : "-"}</span>
                  <span className={`font-mono w-14 text-right font-bold ${st.color}`}>
                    {m.variance_vs_planned > 0 ? "+" : ""}{m.variance_vs_planned || 0}
                  </span>
                </div>
              );
            })}
          </div>

          {writeoffs.length > 0 && (
            <div className="space-y-0.5" data-testid="waste-writeoffs">
              <p className="text-[10px] font-semibold text-muted-foreground px-1">{t("materialWaste.writeOffsTitle")}</p>
              {writeoffs.map((w) => (
                <div key={w.id || w.movement_id} className="flex flex-wrap items-center gap-2 py-1 px-1 text-xs rounded hover:bg-muted/10" data-testid="waste-writeoff-row">
                  <Badge className="bg-orange-500/20 text-orange-500 text-[9px]" data-testid="waste-writeoff-badge">{t("materialWaste.writeOffBadge")}</Badge>
                  <span className="flex-1 min-w-0 truncate">{w.material_name}</span>
                  <span className="font-mono text-right text-orange-400">{w.qty} {w.unit}</span>
                  {w.date && <span className="font-mono text-[10px] text-muted-foreground">{w.date}</span>}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Add Waste Dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("materialWaste.addWaste")}</DialogTitle>
            <DialogDescription>{t("materialWaste.addDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">{t("materialWaste.material")} *</Label>
              <select className="w-full h-9 rounded-md border bg-transparent px-2 text-sm" value={form.item_id}
                      onChange={e => pickItem(e.target.value)} data-testid="waste-material">
                <option value="">{t("materialWaste.pickMaterial")}</option>
                {onProject.map(m => (
                  <option key={m.item_id} value={m.item_id}>{m.material_name} ({m.remaining_on_project} {m.unit})</option>
                ))}
              </select>
              {onProject.length === 0 && <p className="text-[10px] text-muted-foreground" data-testid="waste-no-stock">{t("materialWaste.noStockOnProject")}</p>}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">{t("materialWaste.qty")} *</Label><Input type="number" value={form.qty} onChange={e => setForm(f => ({ ...f, qty: e.target.value }))} data-testid="waste-qty" /></div>
              <div className="space-y-1"><Label className="text-xs">{t("materialWaste.unit")}</Label><Input value={form.unit} onChange={e => setForm(f => ({ ...f, unit: e.target.value }))} /></div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t("materialWaste.wasteType")}</Label>
              <Select value={form.waste_type} onValueChange={v => setForm(f => ({ ...f, waste_type: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{WASTE_TYPES.map(wt => <SelectItem key={wt.value} value={wt.value}>{wt.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label className="text-xs">{t("materialWaste.notes")}</Label><Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} /></div>
            <div className="space-y-1">
              <Label className="text-xs">{t("materialWaste.evidence")} *</Label>
              <Input type="file" accept="image/*,application/pdf" onChange={e => setEvidence(e.target.files?.[0] || null)} data-testid="waste-evidence" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAdd(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleAdd} disabled={saving} data-testid="submit-waste">{t("common.save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// WH-FIX-01 — the backend's error codes in Bulgarian (fallback: its message).
const WASTE_ERRORS = {
  MASTER_IDENTITY_MISSING: "materialWaste.errors.item",
  IDEMPOTENCY_KEY_REQUIRED: "materialWaste.errors.key",
  INVALID_WASTE: "materialWaste.errors.invalid",
  PERMISSION_DENIED: "materialWaste.errors.forbidden",
  NEGATIVE_STOCK: "materialWaste.errors.noStock",
  FILE_REGISTRY_UNAVAILABLE: "materialWaste.errors.evidence",
  IDEMPOTENCY_CONFLICT: "materialWaste.errors.conflict",
};

export function wasteErrorText(err, t) {
  const d = err?.response?.data?.detail;
  const code = d && typeof d === "object" ? d.error_code : null;
  if (code && WASTE_ERRORS[code]) return t(WASTE_ERRORS[code]);
  return apiErrorText(err, t("materialWaste.errors.generic"));
}
