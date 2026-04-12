import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  DollarSign, Loader2, Check, ChevronLeft, ChevronRight,
  FileText, Users, Clock, AlertTriangle, Eye, MapPin,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CFG = {
  confirmed: { label: "Потвърден", cls: "bg-violet-500/15 text-violet-400 border-violet-500/30" },
  paid:      { label: "Платен",    cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
  draft:     { label: "Чернова",   cls: "bg-gray-500/15 text-gray-400 border-gray-500/30" },
};

export default function PayRunsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [tab, setTab] = useState("generate"); // generate | history
  const [periodStart, setPeriodStart] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 6);
    return d.toISOString().slice(0, 10);
  });
  const [periodEnd, setPeriodEnd] = useState(() => new Date().toISOString().slice(0, 10));

  // Generate tab
  const [preview, setPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [overrides, setOverrides] = useState({}); // eid -> {paid, bonuses, deductions, notes}
  const [creating, setCreating] = useState(false);

  // History tab
  const [runs, setRuns] = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [detailRun, setDetailRun] = useState(null);

  const loadPreview = useCallback(async () => {
    setLoadingPreview(true);
    try {
      const res = await API.get(`/pay-runs/generate?period_start=${periodStart}&period_end=${periodEnd}`);
      setPreview(res.data);
      setOverrides({});
    } catch { setPreview(null); }
    finally { setLoadingPreview(false); }
  }, [periodStart, periodEnd]);

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true);
    try {
      const res = await API.get("/pay-runs");
      setRuns(res.data.items || []);
    } catch { setRuns([]); }
    finally { setLoadingRuns(false); }
  }, []);

  useEffect(() => { if (tab === "generate") loadPreview(); }, [tab, loadPreview]);
  useEffect(() => { if (tab === "history") loadRuns(); }, [tab, loadRuns]);

  const setOverride = (eid, field, value) => {
    setOverrides(prev => ({
      ...prev,
      [eid]: { ...(prev[eid] || {}), [field]: value },
    }));
  };

  const getRowTotals = (row) => {
    const ovr = overrides[row.employee_id] || {};
    const paid = parseFloat(ovr.paid) || 0;
    const bonuses = parseFloat(ovr.bonuses) || 0;
    const deductions = parseFloat(ovr.deductions) || 0;
    const remaining = Math.round((row.earned_amount + bonuses - deductions - row.previously_paid - paid) * 100) / 100;
    return { paid, bonuses, deductions, remaining };
  };

  const handleCreate = async () => {
    if (!preview) return;
    setCreating(true);
    try {
      const rows = preview.rows.map(r => {
        const ovr = overrides[r.employee_id] || {};
        return {
          employee_id: r.employee_id,
          paid_now_amount: parseFloat(ovr.paid) || r.remaining_after_payment,
          bonuses_amount: parseFloat(ovr.bonuses) || 0,
          deductions_amount: parseFloat(ovr.deductions) || 0,
          notes: ovr.notes || "",
        };
      });
      await API.post("/pay-runs", {
        run_type: "weekly",
        period_start: periodStart,
        period_end: periodEnd,
        rows,
      });
      toast.success("Pay Run създаден");
      setTab("history");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    }
    finally { setCreating(false); }
  };

  const handleMarkPaid = async (runId) => {
    try {
      await API.post(`/pay-runs/${runId}/mark-paid`);
      toast.success("Маркиран като платен");
      loadRuns();
      setDetailRun(null);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    }
  };

  const loadDetail = async (runId) => {
    try {
      const res = await API.get(`/pay-runs/${runId}`);
      setDetailRun(res.data);
    } catch { /* */ }
  };

  const totals = preview?.totals || {};

  return (
    <div className="p-6 lg:p-8 max-w-[1400px]" data-testid="pay-runs-page">
      <div className="mb-4">
        <h1 className="text-2xl font-bold">Разплащане</h1>
        <p className="text-sm text-muted-foreground">Заработено / Платено / Остатък по служители</p>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 border-b border-border" data-testid="pay-runs-tabs">
        <button onClick={() => setTab("generate")} className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${tab === "generate" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`} data-testid="tab-generate">
          <DollarSign className="w-3.5 h-3.5 inline mr-1" />Ново разплащане
        </button>
        <button onClick={() => setTab("history")} className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${tab === "history" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`} data-testid="tab-history">
          <FileText className="w-3.5 h-3.5 inline mr-1" />История
        </button>
      </div>

      {/* ═══ GENERATE TAB ═══ */}
      {tab === "generate" && (
        <>
          {/* Period picker */}
          <div className="flex items-center gap-3 mb-4 flex-wrap" data-testid="period-picker">
            <div>
              <label className="text-[10px] text-muted-foreground">От</label>
              <Input type="date" value={periodStart} onChange={e => setPeriodStart(e.target.value)} className="h-9 text-xs w-[140px]" />
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">До</label>
              <Input type="date" value={periodEnd} onChange={e => setPeriodEnd(e.target.value)} className="h-9 text-xs w-[140px]" />
            </div>
            <Button variant="outline" size="sm" onClick={loadPreview} className="mt-4">Зареди</Button>
          </div>

          {loadingPreview ? (
            <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          ) : !preview || preview.rows.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">Няма одобрени отчети за периода</div>
          ) : (
            <>
              {/* Summary */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4" data-testid="generate-summary">
                <div className="rounded-lg bg-card border border-border p-3 text-center">
                  <p className="text-xl font-bold font-mono">{totals.employees}</p>
                  <p className="text-[10px] text-muted-foreground">Служители</p>
                </div>
                <div className="rounded-lg bg-card border border-border p-3 text-center">
                  <p className="text-xl font-bold font-mono">{totals.hours}<span className="text-sm text-muted-foreground">ч</span></p>
                  <p className="text-[10px] text-muted-foreground">Часове</p>
                </div>
                <div className="rounded-lg bg-card border border-border p-3 text-center">
                  <p className="text-xl font-bold font-mono text-primary">{totals.earned?.toFixed(0)}<span className="text-sm text-muted-foreground"> EUR</span></p>
                  <p className="text-[10px] text-muted-foreground">Изработено</p>
                </div>
                <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3 text-center">
                  <p className="text-xl font-bold font-mono text-amber-400">{totals.remaining?.toFixed(0)}<span className="text-sm text-amber-400/60"> EUR</span></p>
                  <p className="text-[10px] text-amber-400/70">Остатък</p>
                </div>
              </div>

              {/* Editable table */}
              <div className="rounded-xl border border-border bg-card overflow-hidden mb-4" data-testid="generate-table">
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-[10px] min-w-[150px]">Човек</TableHead>
                        <TableHead className="text-[10px] text-center">Дни</TableHead>
                        <TableHead className="text-[10px] text-center">Часове</TableHead>
                        <TableHead className="text-[10px] text-center">Ставка</TableHead>
                        <TableHead className="text-[10px] text-center">Изработено</TableHead>
                        <TableHead className="text-[10px] text-center">Вече платено</TableHead>
                        <TableHead className="text-[10px] text-center min-w-[80px]">Бонуси</TableHead>
                        <TableHead className="text-[10px] text-center min-w-[80px]">Удръжки</TableHead>
                        <TableHead className="text-[10px] text-center min-w-[90px]">Плащане</TableHead>
                        <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {preview.rows.filter(r => r.earned_amount > 0).map(row => {
                        const ovr = overrides[row.employee_id] || {};
                        const t = getRowTotals(row);
                        return (
                          <TableRow key={row.employee_id} data-testid={`gen-row-${row.employee_id}`}>
                            <TableCell>
                              <div className="flex items-center gap-2 cursor-pointer" onClick={() => navigate(`/employees/${row.employee_id}?tab=payroll-weeks`)}>
                                {row.avatar_url ? (
                                  <img src={`${process.env.REACT_APP_BACKEND_URL}${row.avatar_url}`} className="w-7 h-7 rounded-full object-cover" alt="" />
                                ) : (
                                  <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary">
                                    {(row.first_name?.[0] || "")}{(row.last_name?.[0] || "")}
                                  </div>
                                )}
                                <div>
                                  <p className="text-xs font-medium hover:text-primary">{row.first_name} {row.last_name}</p>
                                  <p className="text-[9px] text-muted-foreground">{row.position || row.pay_type || "—"}</p>
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="text-center text-xs font-mono">{row.approved_days}</TableCell>
                            <TableCell className="text-center text-xs font-mono font-bold">{row.approved_hours}</TableCell>
                            <TableCell className="text-center text-[10px] font-mono text-muted-foreground">{row.hourly_rate}</TableCell>
                            <TableCell className="text-center text-xs font-mono text-primary">{row.earned_amount.toFixed(0)}</TableCell>
                            <TableCell className="text-center text-xs font-mono text-muted-foreground">{row.previously_paid > 0 ? row.previously_paid.toFixed(0) : "—"}</TableCell>
                            <TableCell className="text-center"><Input type="number" value={ovr.bonuses ?? ""} onChange={e => setOverride(row.employee_id, "bonuses", e.target.value)} placeholder="0" className="h-7 w-16 text-xs font-mono text-center text-emerald-400 mx-auto" /></TableCell>
                            <TableCell className="text-center"><Input type="number" value={ovr.deductions ?? ""} onChange={e => setOverride(row.employee_id, "deductions", e.target.value)} placeholder="0" className="h-7 w-16 text-xs font-mono text-center text-red-400 mx-auto" /></TableCell>
                            <TableCell className="text-center"><Input type="number" value={ovr.paid ?? row.remaining_after_payment.toFixed(0)} onChange={e => setOverride(row.employee_id, "paid", e.target.value)} className="h-7 w-20 text-xs font-mono text-center text-primary mx-auto font-bold" /></TableCell>
                            <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${t.remaining < 0 ? "text-red-400" : t.remaining > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                              {t.remaining.toFixed(0)}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>

              {/* Actions */}
              <div className="flex justify-end">
                <Button onClick={handleCreate} disabled={creating} className="gap-1.5" data-testid="create-payrun-btn">
                  {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  Потвърди и запази Pay Run
                </Button>
              </div>
            </>
          )}
        </>
      )}

      {/* ═══ HISTORY TAB ═══ */}
      {tab === "history" && (
        <>
          {loadingRuns ? (
            <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          ) : runs.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">Няма Pay Run-ове</div>
          ) : (
            <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="history-table">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-[10px]">№</TableHead>
                    <TableHead className="text-[10px]">Тип</TableHead>
                    <TableHead className="text-[10px]">Период</TableHead>
                    <TableHead className="text-[10px] text-center">Сед. №</TableHead>
                    <TableHead className="text-[10px] text-center">Хора</TableHead>
                    <TableHead className="text-[10px] text-center">Часове</TableHead>
                    <TableHead className="text-[10px] text-center">Изработено</TableHead>
                    <TableHead className="text-[10px] text-center">Платено</TableHead>
                    <TableHead className="text-[10px] text-center">Остатък</TableHead>
                    <TableHead className="text-[10px]">Статус</TableHead>
                    <TableHead className="text-[10px] w-[50px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map(r => {
                    const t = r.totals || {};
                    const scfg = STATUS_CFG[r.status] || STATUS_CFG.draft;
                    return (
                      <TableRow key={r.id} className="hover:bg-muted/10" data-testid={`run-${r.id}`}>
                        <TableCell className="text-xs font-mono font-bold">{r.number}</TableCell>
                        <TableCell className="text-[10px] text-muted-foreground">{r.run_type}</TableCell>
                        <TableCell className="text-xs font-mono">{r.period_start} → {r.period_end}</TableCell>
                        <TableCell className="text-center text-xs font-mono">{r.week_number || "—"}</TableCell>
                        <TableCell className="text-center text-xs">{t.employees}</TableCell>
                        <TableCell className="text-center text-xs font-mono">{t.hours}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-primary">{t.earned?.toFixed(0)}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-emerald-400">{t.paid?.toFixed(0)}</TableCell>
                        <TableCell className={`text-center text-xs font-mono ${t.remaining > 0 ? "text-amber-400" : "text-muted-foreground"}`}>{t.remaining?.toFixed(0)}</TableCell>
                        <TableCell><Badge variant="outline" className={`text-[9px] ${scfg.cls}`}>{scfg.label}</Badge></TableCell>
                        <TableCell>
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => loadDetail(r.id)} data-testid={`detail-${r.id}`}>
                            <Eye className="w-3.5 h-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      )}

      {/* Detail Dialog */}
      <Dialog open={!!detailRun} onOpenChange={() => setDetailRun(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto" data-testid="payrun-detail-modal">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="w-4 h-4" /> Pay Run {detailRun?.number}
            </DialogTitle>
          </DialogHeader>
          {detailRun && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="text-xs text-muted-foreground">
                  {detailRun.period_start} → {detailRun.period_end} | Сед. {detailRun.week_number} | {detailRun.run_type}
                </div>
                <Badge variant="outline" className={(STATUS_CFG[detailRun.status] || STATUS_CFG.draft).cls}>
                  {(STATUS_CFG[detailRun.status] || STATUS_CFG.draft).label}
                </Badge>
              </div>

              <div className="rounded-lg border border-border overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-[10px]">Човек</TableHead>
                      <TableHead className="text-[10px] text-center">Дни</TableHead>
                      <TableHead className="text-[10px] text-center">Часове</TableHead>
                      <TableHead className="text-[10px] text-center">Изработено</TableHead>
                      <TableHead className="text-[10px] text-center">Удръжки</TableHead>
                      <TableHead className="text-[10px] text-center">Платено</TableHead>
                      <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detailRun.employee_rows?.map(r => (
                      <TableRow key={r.employee_id}>
                        <TableCell className="text-xs font-medium">{r.first_name} {r.last_name}</TableCell>
                        <TableCell className="text-center text-xs font-mono">{r.approved_days}</TableCell>
                        <TableCell className="text-center text-xs font-mono">{r.approved_hours}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-primary">{r.earned_amount?.toFixed(0)}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-red-400">{r.deductions_amount > 0 ? `-${r.deductions_amount.toFixed(0)}` : "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-emerald-400">{r.paid_now_amount?.toFixed(0)}</TableCell>
                        <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${r.remaining_after_payment > 0 ? "text-amber-400" : r.remaining_after_payment < 0 ? "text-red-400" : "text-emerald-400"}`}>
                          {r.remaining_after_payment?.toFixed(0)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {detailRun.status === "confirmed" && (
                <div className="flex justify-end">
                  <Button onClick={() => handleMarkPaid(detailRun.id)} className="gap-1.5 bg-emerald-600 hover:bg-emerald-700" data-testid="mark-paid-btn">
                    <Check className="w-4 h-4" /> Маркирай платен
                  </Button>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
