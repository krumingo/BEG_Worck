/**
 * SubcontractorPerformancePanel — Performance tracking for subcontractors.
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
  Users, Loader2, ChevronDown, ChevronRight, Plus, Clock,
  AlertTriangle, DollarSign, Star,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CFG = {
  on_time: { color: "text-emerald-400", dot: "bg-emerald-500", label: "Навреме" },
  delayed: { color: "text-amber-400", dot: "bg-amber-500", label: "Закъснял" },
  over_budget: { color: "text-orange-400", dot: "bg-orange-500", label: "Над бюджет" },
  mixed: { color: "text-red-400", dot: "bg-red-500", label: "Смесен риск" },
  unknown: { color: "text-muted-foreground", dot: "bg-zinc-500", label: "Неизвестен" },
};

export default function SubcontractorPerformancePanel({ projectId }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    subcontractor_id: "", project_id: projectId || "", promised_amount: "", actual_paid_amount: "",
    promised_end_date: "", actual_end_date: "", quality_score: "", notes: "",
  });

  const load = useCallback(async () => {
    try {
      const q = projectId ? `?project_id=${projectId}` : "";
      const res = await API.get(`/subcontractor-performance${q}`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!form.subcontractor_id) { toast.error(t("subcontractorPerformance.fillRequired")); return; }
    try {
      await API.post("/subcontractor-performance", {
        ...form,
        project_id: form.project_id || projectId,
        promised_amount: parseFloat(form.promised_amount) || null,
        actual_paid_amount: parseFloat(form.actual_paid_amount) || null,
        quality_score: parseInt(form.quality_score) || null,
      });
      toast.success(t("subcontractorPerformance.added"));
      setShowAdd(false);
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  if (loading) return <div className="flex items-center justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const { summary, items } = data;

  return (
    <div className="space-y-3" data-testid="subcontractor-performance-panel">
      <div className="flex items-center justify-between">
        <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-2">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          <Users className="w-4 h-4 text-violet-400" />
          <span className="font-semibold text-sm">{t("subcontractorPerformance.title")}</span>
          {summary.delayed_count + summary.mixed_count > 0 && (
            <Badge className="bg-red-500/20 text-red-400 text-[9px]">
              {summary.delayed_count + summary.mixed_count} {t("subcontractorPerformance.issues")}
            </Badge>
          )}
        </button>
        <Button size="sm" variant="outline" onClick={() => setShowAdd(true)} data-testid="add-perf-btn">
          <Plus className="w-3.5 h-3.5 mr-1" /> {t("subcontractorPerformance.addRecord")}
        </Button>
      </div>

      {expanded && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div><p className="font-mono font-bold">{summary.subcontractors_count}</p><p className="text-[9px] text-muted-foreground">{t("subcontractorPerformance.subs")}</p></div>
            <div><p className="font-mono font-bold text-amber-400">{summary.delayed_count}</p><p className="text-[9px] text-muted-foreground">{t("subcontractorPerformance.delayed")}</p></div>
            <div><p className="font-mono font-bold text-orange-400">{summary.over_budget_count}</p><p className="text-[9px] text-muted-foreground">{t("subcontractorPerformance.overBudget")}</p></div>
            <div><p className="font-mono font-bold text-red-400">{summary.mixed_count}</p><p className="text-[9px] text-muted-foreground">{t("subcontractorPerformance.mixed")}</p></div>
          </div>

          {/* Items */}
          <div className="max-h-[200px] overflow-y-auto space-y-1">
            {items.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-4">{t("subcontractorPerformance.noData")}</p>
            ) : items.map((it, i) => {
              const st = STATUS_CFG[it.status] || STATUS_CFG.unknown;
              return (
                <div key={i} className="flex items-center gap-2 py-1.5 px-1 text-xs rounded hover:bg-muted/10">
                  <span className={`w-2 h-2 rounded-full ${st.dot} flex-shrink-0`} />
                  <span className="flex-1 truncate">{it.subcontractor_id?.slice(0, 8)}</span>
                  <span className="font-mono w-16 text-right text-muted-foreground">{it.promised_amount?.toFixed(0) || "-"}</span>
                  <span className="font-mono w-16 text-right">{it.actual_paid_amount?.toFixed(0) || "-"}</span>
                  <span className={`font-mono w-16 text-right font-bold ${st.color}`}>
                    {it.variance_amount > 0 ? "+" : ""}{it.variance_amount?.toFixed(0) || "0"}
                  </span>
                  <Badge variant="outline" className={`text-[9px] ${st.color}`}>{st.label}</Badge>
                  {it.quality_score && <span className="flex items-center gap-0.5"><Star className="w-3 h-3 text-amber-400" />{it.quality_score}</span>}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Add Dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("subcontractorPerformance.addRecord")}</DialogTitle>
            <DialogDescription>{t("subcontractorPerformance.addDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1"><Label className="text-xs">{t("subcontractorPerformance.subId")} *</Label><Input value={form.subcontractor_id} onChange={e => setForm(f => ({ ...f, subcontractor_id: e.target.value }))} data-testid="perf-sub-id" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">{t("subcontractorPerformance.promised")}</Label><Input type="number" value={form.promised_amount} onChange={e => setForm(f => ({ ...f, promised_amount: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">{t("subcontractorPerformance.paid")}</Label><Input type="number" value={form.actual_paid_amount} onChange={e => setForm(f => ({ ...f, actual_paid_amount: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">{t("subcontractorPerformance.promisedDate")}</Label><Input type="date" value={form.promised_end_date} onChange={e => setForm(f => ({ ...f, promised_end_date: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">{t("subcontractorPerformance.actualDate")}</Label><Input type="date" value={form.actual_end_date} onChange={e => setForm(f => ({ ...f, actual_end_date: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">{t("subcontractorPerformance.quality")} (1-5)</Label><Input type="number" min="1" max="5" value={form.quality_score} onChange={e => setForm(f => ({ ...f, quality_score: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">{t("subcontractorPerformance.notes")}</Label><Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} /></div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAdd(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleAdd} data-testid="submit-perf">{t("common.save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
