/**
 * MaterialWastePanel — Material variance: planned vs issued vs waste.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
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
  const [form, setForm] = useState({ material_name: "", qty: "", unit: "бр", waste_type: "damaged", notes: "" });

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/material-waste`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!form.material_name || !form.qty) { toast.error(t("materialWaste.fillRequired")); return; }
    try {
      await API.post(`/projects/${projectId}/material-waste`, { ...form, qty: parseFloat(form.qty) });
      toast.success(t("materialWaste.added"));
      setShowAdd(false);
      setForm({ material_name: "", qty: "", unit: "бр", waste_type: "damaged", notes: "" });
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  if (loading) return <div className="flex items-center justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const { summary, materials } = data;

  return (
    <div className="space-y-3" data-testid="material-waste-panel">
      <div className="flex items-center justify-between">
        <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-2">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          <Package className="w-4 h-4 text-orange-400" />
          <span className="font-semibold text-sm">{t("materialWaste.title")}</span>
          {summary.overuse_count > 0 && <Badge className="bg-red-500/20 text-red-400 text-[9px]">{summary.overuse_count} overuse</Badge>}
        </button>
        <Button size="sm" variant="outline" onClick={() => setShowAdd(true)} data-testid="add-waste-btn">
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
            <div className="space-y-1"><Label className="text-xs">{t("materialWaste.material")} *</Label><Input value={form.material_name} onChange={e => setForm(f => ({ ...f, material_name: e.target.value }))} placeholder={t("materialWaste.materialPlaceholder")} data-testid="waste-material" /></div>
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
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAdd(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleAdd} data-testid="submit-waste">{t("common.save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
