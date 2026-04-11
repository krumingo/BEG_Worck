import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  ChevronLeft, ChevronRight, DollarSign, Check, AlertTriangle,
  Plus, Minus, Eye, Loader2, Banknote, MapPin,
} from "lucide-react";
import { toast } from "sonner";

const BG_DAY_SHORT = ["Съб", "Нед", "Пон", "Вт", "Ср", "Чет", "Пет"];

function getPayrollWeek(refDate) {
  const d = new Date(refDate + "T12:00:00");
  const day = d.getDay();
  const daysSinceSat = (day - 6 + 7) % 7;
  const sat = new Date(d);
  sat.setDate(d.getDate() - daysSinceSat);
  return sat.toISOString().slice(0, 10);
}

function formatWeekLabel(satStr) {
  const sat = new Date(satStr + "T12:00:00");
  const fri = new Date(sat);
  fri.setDate(sat.getDate() + 6);
  const fmt = (d) => `${d.getDate().toString().padStart(2, "0")}.${(d.getMonth() + 1).toString().padStart(2, "0")}`;
  return `${fmt(sat)} – ${fmt(fri)}.${fri.getFullYear()}`;
}

const BATCH_STATUS_BADGE = {
  batched: { label: "В пакет", cls: "bg-violet-500/15 text-violet-400 border-violet-500/30" },
  paid:    { label: "Платен", cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
};

export default function PayrollBatchSection() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [weekStart, setWeekStart] = useState(() => getPayrollWeek(new Date().toISOString().slice(0, 10)));
  const [includedDays, setIncludedDays] = useState(new Set());
  const [adjustments, setAdjustments] = useState({});
  const [saving, setSaving] = useState(false);
  const [paying, setPaying] = useState(false);
  const [workerDetail, setWorkerDetail] = useState(null);
  const [adjDialog, setAdjDialog] = useState(null);
  const [adjType, setAdjType] = useState("deduction");
  const [adjAmount, setAdjAmount] = useState("");
  const [adjNote, setAdjNote] = useState("");
  const [allocations, setAllocations] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setAllocations(null);
    try {
      const res = await API.get(`/payroll-batch/eligible?week_of=${weekStart}`);
      setData(res.data);
      // Default: include all days that have data
      const allDatesWithData = new Set();
      for (const w of res.data.workers || []) {
        for (const d of w.days || []) {
          if (d.has_data) allDatesWithData.add(d.date);
        }
      }
      setIncludedDays(allDatesWithData);
      setAdjustments({});
      // Load allocations if batch exists and is paid
      if (res.data.existing_batch?.status === "paid") {
        try {
          const allocRes = await API.get(`/payroll-batch/${res.data.existing_batch.id}/allocations`);
          setAllocations(allocRes.data);
        } catch { /* */ }
      }
    } catch { setData(null); }
    finally { setLoading(false); }
  }, [weekStart]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const prevWeek = () => {
    const d = new Date(weekStart + "T12:00:00");
    d.setDate(d.getDate() - 7);
    setWeekStart(d.toISOString().slice(0, 10));
  };
  const nextWeek = () => {
    const d = new Date(weekStart + "T12:00:00");
    d.setDate(d.getDate() + 7);
    setWeekStart(d.toISOString().slice(0, 10));
  };
  const goToday = () => setWeekStart(getPayrollWeek(new Date().toISOString().slice(0, 10)));

  const toggleDay = (date) => {
    setIncludedDays(prev => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date);
      else next.add(date);
      return next;
    });
  };

  // Compute worker totals based on included days + adjustments
  const computeWorkerTotals = (w) => {
    let hours = 0, normal = 0, overtime = 0, days = 0;
    for (const d of w.days) {
      if (includedDays.has(d.date) && d.has_data) {
        hours += d.hours;
        normal += d.normal;
        overtime += d.overtime;
        days += 1;
      }
    }
    const gross = Math.round(hours * w.hourly_rate * 100) / 100;
    const wAdj = adjustments[w.worker_id] || [];
    const bonuses = wAdj.filter(a => a.type === "bonus").reduce((s, a) => s + a.amount, 0);
    const deductions = wAdj.filter(a => a.type !== "bonus").reduce((s, a) => s + a.amount, 0);
    const net = Math.round((gross + bonuses - deductions) * 100) / 100;
    return { hours: Math.round(hours * 10) / 10, normal: Math.round(normal * 10) / 10, overtime: Math.round(overtime * 10) / 10, days, gross, bonuses, deductions, net };
  };

  const addAdjustment = () => {
    if (!adjDialog || !adjAmount) return;
    const wid = adjDialog.worker_id;
    setAdjustments(prev => ({
      ...prev,
      [wid]: [...(prev[wid] || []), { type: adjType, amount: parseFloat(adjAmount) || 0, note: adjNote }],
    }));
    setAdjDialog(null);
    setAdjAmount("");
    setAdjNote("");
  };

  const removeAdjustment = (wid, idx) => {
    setAdjustments(prev => ({
      ...prev,
      [wid]: (prev[wid] || []).filter((_, i) => i !== idx),
    }));
  };

  const handleCreateBatch = async () => {
    if (!data) return;
    const adjList = [];
    for (const [wid, adjs] of Object.entries(adjustments)) {
      for (const a of adjs) {
        adjList.push({ worker_id: wid, type: a.type, amount: a.amount, note: a.note });
      }
    }
    setSaving(true);
    try {
      await API.post("/payroll-batch", {
        week_of: weekStart,
        included_days: Array.from(includedDays).sort(),
        adjustments: adjList,
      });
      toast.success(t("payroll.batchCreated"));
      fetchData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Error");
    }
    finally { setSaving(false); }
  };

  const handleMarkPaid = async () => {
    if (!data?.existing_batch) return;
    setPaying(true);
    try {
      await API.post(`/payroll-batch/${data.existing_batch.id}/pay`, {});
      toast.success(t("payroll.batchPaid"));
      fetchData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Error");
    }
    finally { setPaying(false); }
  };

  // Grand totals
  const grandTotals = (data?.workers || []).reduce((acc, w) => {
    const t = computeWorkerTotals(w);
    return {
      hours: acc.hours + t.hours,
      gross: acc.gross + t.gross,
      bonuses: acc.bonuses + t.bonuses,
      deductions: acc.deductions + t.deductions,
      net: acc.net + t.net,
      workers: acc.workers + (t.hours > 0 ? 1 : 0),
    };
  }, { hours: 0, gross: 0, bonuses: 0, deductions: 0, net: 0, workers: 0 });

  const hasBatch = data?.existing_batch;
  const batchStatus = hasBatch?.status;

  return (
    <div data-testid="payroll-batch-section">
      {/* Week Picker */}
      <div className="flex items-center justify-between mb-4" data-testid="payroll-week-picker">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={prevWeek} className="h-8 w-8 p-0"><ChevronLeft className="w-4 h-4" /></Button>
          <div className="text-center min-w-[180px]">
            <p className="text-sm font-bold">{formatWeekLabel(data?.week_start || weekStart)}</p>
            <p className="text-[10px] text-muted-foreground">{t("weekly.satToFri")}</p>
          </div>
          <Button variant="outline" size="sm" onClick={nextWeek} className="h-8 w-8 p-0"><ChevronRight className="w-4 h-4" /></Button>
          <Button variant="ghost" size="sm" onClick={goToday} className="text-xs ml-2">{t("weekly.today")}</Button>
        </div>
        {hasBatch && (
          <Badge variant="outline" className={`${(BATCH_STATUS_BADGE[batchStatus] || {}).cls || ""}`}>
            {(BATCH_STATUS_BADGE[batchStatus] || {}).label || batchStatus}
          </Badge>
        )}
      </div>

      {loading ? (
        <div className="rounded-xl border border-border bg-card p-12 flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : !data || (data.workers.length === 0 && !allocations) ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground" data-testid="no-eligible">
          {t("payroll.noEligible")}
        </div>
      ) : (
        <>
          {/* Day Selection — only show when there are workers */}
          {data.workers.length > 0 && (
          <div className="flex items-center gap-3 mb-4 flex-wrap" data-testid="day-selection">
            <span className="text-xs text-muted-foreground">{t("payroll.includeDays")}:</span>
            {(data.dates || []).map((d, i) => {
              const dt = new Date(d + "T12:00:00");
              const hasAnyData = data.workers.some(w => w.days[i]?.has_data);
              const isIncluded = includedDays.has(d);
              return (
                <label key={d} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs cursor-pointer transition-colors ${
                  isIncluded ? "border-primary bg-primary/10 text-primary" : hasAnyData ? "border-border hover:border-muted-foreground" : "border-border/50 text-muted-foreground/50 cursor-default"
                }`}>
                  <Checkbox
                    checked={isIncluded}
                    onCheckedChange={() => hasAnyData && toggleDay(d)}
                    disabled={!hasAnyData || !!hasBatch}
                    className="h-3.5 w-3.5"
                  />
                  <span>{BG_DAY_SHORT[i]}</span>
                  <span className="text-[9px] text-muted-foreground">{dt.getDate()}.{(dt.getMonth() + 1).toString().padStart(2, "0")}</span>
                </label>
              );
            })}
          </div>
          )}

          {/* Summary + Table + Actions — only when there are workers */}
          {data.workers.length > 0 && (
          <>
          {/* Summary Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4" data-testid="payroll-summary">
            <div className="rounded-lg bg-card border border-border p-3 text-center">
              <p className="text-xl font-bold font-mono">{grandTotals.hours}<span className="text-sm text-muted-foreground">ч</span></p>
              <p className="text-[10px] text-muted-foreground">{t("payroll.totalHours")}</p>
            </div>
            <div className="rounded-lg bg-card border border-border p-3 text-center">
              <p className="text-xl font-bold font-mono text-primary">{grandTotals.gross.toFixed(0)}<span className="text-sm text-muted-foreground"> EUR</span></p>
              <p className="text-[10px] text-muted-foreground">{t("payroll.grossLabel")}</p>
            </div>
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3 text-center">
              <p className="text-xl font-bold font-mono text-emerald-400">{grandTotals.bonuses.toFixed(0)}<span className="text-sm text-emerald-400/60"> EUR</span></p>
              <p className="text-[10px] text-emerald-400/70">{t("payroll.bonuses")}</p>
            </div>
            <div className="rounded-lg bg-red-500/5 border border-red-500/20 p-3 text-center">
              <p className="text-xl font-bold font-mono text-red-400">{grandTotals.deductions.toFixed(0)}<span className="text-sm text-red-400/60"> EUR</span></p>
              <p className="text-[10px] text-red-400/70">{t("payroll.deductions")}</p>
            </div>
            <div className="rounded-lg bg-primary/5 border border-primary/20 p-3 text-center">
              <p className="text-xl font-bold font-mono text-primary">{grandTotals.net.toFixed(0)}<span className="text-sm text-muted-foreground"> EUR</span></p>
              <p className="text-[10px] text-muted-foreground">{t("payroll.netPay")}</p>
            </div>
          </div>

          {/* Workers Table */}
          <div className="rounded-xl border border-border bg-card overflow-hidden mb-4" data-testid="payroll-table">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-[10px] min-w-[160px]">{t("payroll.worker")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payroll.incDays")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payroll.hours")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payroll.normalH")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payroll.overtimeH")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payroll.rate")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payroll.grossLabel")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payroll.bonuses")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payroll.deductions")}</TableHead>
                    <TableHead className="text-[10px] text-center bg-primary/5">{t("payroll.netPay")}</TableHead>
                    <TableHead className="text-[10px] w-[70px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.workers.map(w => {
                    const tots = computeWorkerTotals(w);
                    const wAdj = adjustments[w.worker_id] || [];
                    if (tots.hours === 0) return null;
                    return (
                      <TableRow key={w.worker_id} className="hover:bg-muted/10" data-testid={`payroll-row-${w.worker_id}`}>
                        <TableCell>
                          <div className="flex items-center gap-2 cursor-pointer" onClick={() => navigate(`/employees/${w.worker_id}?tab=payroll-weeks`)}>
                            {w.avatar_url ? (
                              <img src={`${process.env.REACT_APP_BACKEND_URL}${w.avatar_url}`} className="w-7 h-7 rounded-full object-cover" alt="" />
                            ) : (
                              <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary">
                                {(w.first_name?.[0] || "")}{(w.last_name?.[0] || "")}
                              </div>
                            )}
                            <div>
                              <p className="text-xs font-medium hover:text-primary transition-colors">{w.first_name} {w.last_name}</p>
                              <p className="text-[9px] text-muted-foreground">{w.position || w.pay_type || "—"}</p>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-center text-xs font-mono">{tots.days}</TableCell>
                        <TableCell className="text-center text-xs font-mono font-bold">{tots.hours}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-emerald-400">{tots.normal}</TableCell>
                        <TableCell className={`text-center text-xs font-mono ${tots.overtime > 0 ? "text-amber-400 font-bold" : "text-muted-foreground"}`}>{tots.overtime > 0 ? `+${tots.overtime}` : "—"}</TableCell>
                        <TableCell className="text-center text-[10px] font-mono text-muted-foreground">{w.hourly_rate || "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-primary">{tots.gross > 0 ? tots.gross.toFixed(0) : "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-emerald-400">{tots.bonuses > 0 ? tots.bonuses.toFixed(0) : "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-red-400">{tots.deductions > 0 ? `-${tots.deductions.toFixed(0)}` : "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono font-bold text-primary bg-primary/5">{tots.net > 0 ? tots.net.toFixed(0) : "—"}</TableCell>
                        <TableCell>
                          <div className="flex gap-1">
                            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setWorkerDetail(w)} data-testid={`detail-${w.worker_id}`}>
                              <Eye className="w-3.5 h-3.5" />
                            </Button>
                            {!hasBatch && (
                              <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => { setAdjDialog(w); setAdjType("deduction"); setAdjAmount(""); setAdjNote(""); }}>
                                <Plus className="w-3.5 h-3.5" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between" data-testid="payroll-actions">
            <p className="text-[10px] text-muted-foreground max-w-[400px]">{t("payroll.valueDisclaimer")}</p>
            <div className="flex gap-2">
              {!hasBatch && (
                <Button onClick={handleCreateBatch} disabled={saving || grandTotals.hours === 0} className="gap-1.5" data-testid="create-batch-btn">
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Banknote className="w-4 h-4" />}
                  {t("payroll.createBatch")}
                </Button>
              )}
              {hasBatch && batchStatus === "batched" && (
                <Button onClick={handleMarkPaid} disabled={paying} className="gap-1.5 bg-emerald-600 hover:bg-emerald-700" data-testid="mark-paid-btn">
                  {paying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  {t("payroll.markPaid")}
                </Button>
              )}
              {hasBatch && batchStatus === "paid" && (
                <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-sm px-4 py-2">
                  <Check className="w-4 h-4 mr-1" />{t("payroll.alreadyPaid")}
                </Badge>
              )}
            </div>
          </div>
          </>
          )}

          {/* Allocation Summary (shown after paid — always visible even with 0 workers) */}
          {allocations && allocations.by_project?.length > 0 && (
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 mt-4" data-testid="allocation-summary">
              <div className="flex items-center gap-2 mb-3">
                <Check className="w-4 h-4 text-emerald-400" />
                <h3 className="text-sm font-semibold text-emerald-400">{t("payroll.allocationTitle")}</h3>
                <Badge variant="outline" className="text-[9px] bg-emerald-500/15 text-emerald-400 border-emerald-500/30">
                  {allocations.by_project.length} {t("payroll.projects")}
                </Badge>
                <span className="text-xs font-mono text-emerald-400 ml-auto">{allocations.total_allocated?.toFixed(0)} EUR</span>
              </div>
              <div className="space-y-2">
                {allocations.by_project.map(p => (
                  <div key={p.project_id} className="flex items-center justify-between rounded-lg bg-card border border-border px-3 py-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <MapPin className="w-3 h-3 text-primary flex-shrink-0" />
                      <span className="text-xs font-medium truncate">{p.project_name || p.project_id}</span>
                      <span className="text-[9px] text-muted-foreground">{p.worker_count} {t("payroll.workersShort")}</span>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className="text-[10px] text-muted-foreground">{p.allocated_hours}ч</span>
                      <span className="text-xs font-mono font-bold text-primary">{p.allocated_gross?.toFixed(0)} EUR</span>
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-[9px] text-emerald-400/60 mt-2">{t("payroll.allocationNote")}</p>
            </div>
          )}
        </>
      )}

      {/* Adjustment Dialog */}
      <Dialog open={!!adjDialog} onOpenChange={() => setAdjDialog(null)}>
        <DialogContent className="max-w-sm" data-testid="adjustment-dialog">
          <DialogHeader>
            <DialogTitle>{t("payroll.addAdjustment")}: {adjDialog?.first_name} {adjDialog?.last_name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Select value={adjType} onValueChange={setAdjType}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="bonus">{t("payroll.adjBonus")}</SelectItem>
                <SelectItem value="deduction">{t("payroll.adjDeduction")}</SelectItem>
                <SelectItem value="loan">{t("payroll.adjLoan")}</SelectItem>
                <SelectItem value="rent">{t("payroll.adjRent")}</SelectItem>
                <SelectItem value="fine">{t("payroll.adjFine")}</SelectItem>
              </SelectContent>
            </Select>
            <Input type="number" value={adjAmount} onChange={e => setAdjAmount(e.target.value)} placeholder="EUR" className="h-9" />
            <Input value={adjNote} onChange={e => setAdjNote(e.target.value)} placeholder={t("payroll.adjNote")} className="h-9" />
            <Button onClick={addAdjustment} disabled={!adjAmount} className="w-full">{t("payroll.addBtn")}</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Worker Detail Dialog */}
      <Dialog open={!!workerDetail} onOpenChange={() => setWorkerDetail(null)}>
        <DialogContent className="max-w-lg" data-testid="worker-payroll-detail">
          <DialogHeader>
            <DialogTitle>{workerDetail?.first_name} {workerDetail?.last_name} — {t("payroll.weekDetail")}</DialogTitle>
          </DialogHeader>
          {workerDetail && (() => {
            const tots = computeWorkerTotals(workerDetail);
            const wAdj = adjustments[workerDetail.worker_id] || [];
            return (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-2">
                  <div className="rounded-lg bg-muted/30 p-2 text-center">
                    <p className="text-lg font-bold font-mono">{tots.hours}<span className="text-xs">ч</span></p>
                    <p className="text-[9px] text-muted-foreground">{t("payroll.hours")}</p>
                  </div>
                  <div className="rounded-lg bg-muted/30 p-2 text-center">
                    <p className="text-lg font-bold font-mono text-primary">{tots.gross.toFixed(0)}<span className="text-xs"> EUR</span></p>
                    <p className="text-[9px] text-muted-foreground">{t("payroll.grossLabel")}</p>
                  </div>
                  <div className="rounded-lg bg-primary/10 p-2 text-center">
                    <p className="text-lg font-bold font-mono text-primary">{tots.net.toFixed(0)}<span className="text-xs"> EUR</span></p>
                    <p className="text-[9px] text-muted-foreground">{t("payroll.netPay")}</p>
                  </div>
                </div>
                {/* Day entries */}
                {workerDetail.days.filter(d => includedDays.has(d.date) && d.has_data).map((d, i) => (
                  <div key={d.date} className="rounded-lg border border-border p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium">{BG_DAY_SHORT[(data?.dates || []).indexOf(d.date)]} {new Date(d.date + "T12:00:00").getDate()}.{(new Date(d.date + "T12:00:00").getMonth() + 1).toString().padStart(2, "0")}</span>
                      <span className="text-xs font-mono font-bold">{d.hours}ч</span>
                    </div>
                    {d.entries.map((e, ei) => (
                      <div key={ei} className="flex items-center justify-between text-[10px] text-muted-foreground mt-0.5">
                        <span>{e.smr || "—"} {e.project_name && <span className="text-primary">@ {e.project_name}</span>}</span>
                        <span className="font-mono">{e.hours}ч</span>
                      </div>
                    ))}
                  </div>
                ))}
                {/* Adjustments */}
                {wAdj.length > 0 && (
                  <div>
                    <p className="text-[10px] text-muted-foreground mb-1">{t("payroll.adjustments")}:</p>
                    {wAdj.map((a, i) => (
                      <div key={i} className="flex items-center justify-between text-xs py-1">
                        <span className={a.type === "bonus" ? "text-emerald-400" : "text-red-400"}>
                          {t(`payroll.adj${a.type.charAt(0).toUpperCase() + a.type.slice(1)}`)} {a.note && `(${a.note})`}
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="font-mono">{a.type === "bonus" ? "+" : "-"}{a.amount} EUR</span>
                          {!hasBatch && <button onClick={() => removeAdjustment(workerDetail.worker_id, i)} className="text-red-400 hover:text-red-300"><Minus className="w-3 h-3" /></button>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {workerDetail.pending_advances > 0 && (
                  <div className="rounded-lg bg-amber-500/10 p-2 text-xs text-amber-400 flex items-center gap-2">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {t("payroll.pendingAdvances")}: {workerDetail.pending_advances.toFixed(2)} EUR
                  </div>
                )}
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}
