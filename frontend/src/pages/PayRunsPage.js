import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
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
  DollarSign, Loader2, Check, FileText, Eye, Plus, X, Receipt, Calendar, MapPin, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CFG = {
  confirmed: { label: "Потвърден", cls: "bg-violet-500/15 text-violet-400 border-violet-500/30" },
  paid:      { label: "Платен",    cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
};

const ADJ_TYPES = [
  { value: "bonus", label: "Бонус", color: "text-emerald-400" },
  { value: "advance", label: "Аванс", color: "text-blue-400" },
  { value: "loan_repayment", label: "Погасяване заем", color: "text-red-400" },
  { value: "deduction", label: "Удръжка", color: "text-red-400" },
  { value: "manual_correction", label: "Ръчна корекция", color: "text-amber-400" },
];

export default function PayRunsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("generate");

  const [periodStart, setPeriodStart] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 6);
    return d.toISOString().slice(0, 10);
  });
  const [periodEnd, setPeriodEnd] = useState(() => new Date().toISOString().slice(0, 10));

  const [preview, setPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [overrides, setOverrides] = useState({});
  const [creating, setCreating] = useState(false);

  const [runs, setRuns] = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [detailRun, setDetailRun] = useState(null);

  const [slips, setSlips] = useState([]);
  const [loadingSlips, setLoadingSlips] = useState(false);
  const [detailSlip, setDetailSlip] = useState(null);

  const [weeks, setWeeks] = useState([]);
  const [loadingWeeks, setLoadingWeeks] = useState(false);
  const [weeksFilter, setWeeksFilter] = useState("all"); // all | unpaid | partial | overpaid | with_slip | no_slip

  const [adjDialog, setAdjDialog] = useState(null);
  const [adjType, setAdjType] = useState("deduction");
  const [adjTitle, setAdjTitle] = useState("");
  const [adjAmount, setAdjAmount] = useState("");
  const [adjNote, setAdjNote] = useState("");

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
    try { const res = await API.get("/pay-runs"); setRuns(res.data.items || []); }
    catch { setRuns([]); }
    finally { setLoadingRuns(false); }
  }, []);

  const loadSlips = useCallback(async () => {
    setLoadingSlips(true);
    try { const res = await API.get("/payment-slips"); setSlips(res.data.items || []); }
    catch { setSlips([]); }
    finally { setLoadingSlips(false); }
  }, []);

  const loadWeeks = useCallback(async () => {
    setLoadingWeeks(true);
    try {
      const res = await API.get("/payroll-weeks");
      setWeeks(res.data.items || []);
    } catch { setWeeks([]); }
    finally { setLoadingWeeks(false); }
  }, []);

  useEffect(() => { if (tab === "generate") loadPreview(); }, [tab, loadPreview]);
  useEffect(() => { if (tab === "history") loadRuns(); }, [tab, loadRuns]);
  useEffect(() => { if (tab === "slips") loadSlips(); }, [tab, loadSlips]);
  useEffect(() => { if (tab === "weeks") loadWeeks(); }, [tab, loadWeeks]);

  const getOvr = (eid) => overrides[eid] || { paid: null, adjustments: [] };
  const setOvr = (eid, field, value) => {
    setOverrides(prev => ({ ...prev, [eid]: { ...getOvr(eid), ...prev[eid], [field]: value } }));
  };

  const addAdj = () => {
    if (!adjDialog || !adjAmount) return;
    const eid = adjDialog.employee_id;
    const cur = getOvr(eid);
    const adjs = [...(cur.adjustments || []), { type: adjType, title: adjTitle || ADJ_TYPES.find(t => t.value === adjType)?.label || adjType, amount: parseFloat(adjAmount) || 0, note: adjNote }];
    setOverrides(prev => ({ ...prev, [eid]: { ...cur, ...prev[eid], adjustments: adjs } }));
    setAdjDialog(null); setAdjTitle(""); setAdjAmount(""); setAdjNote("");
  };

  const removeAdj = (eid, idx) => {
    const cur = getOvr(eid);
    const adjs = (cur.adjustments || []).filter((_, i) => i !== idx);
    setOverrides(prev => ({ ...prev, [eid]: { ...cur, ...prev[eid], adjustments: adjs } }));
  };

  const getRowCalc = (row) => {
    const ovr = getOvr(row.employee_id);
    const adjs = ovr.adjustments || [];
    const bonuses = adjs.filter(a => a.type === "bonus").reduce((s, a) => s + a.amount, 0);
    const deductions = adjs.filter(a => a.type !== "bonus").reduce((s, a) => s + a.amount, 0);
    const paid = parseFloat(ovr.paid) || (ovr.paid === null ? row.remaining_after_payment : 0);
    const remaining = Math.round((row.earned_amount + bonuses - deductions - row.previously_paid - paid) * 100) / 100;
    return { bonuses, deductions, paid, remaining };
  };

  const handleCreate = async () => {
    if (!preview) return;
    setCreating(true);
    try {
      const rows = preview.rows.map(r => {
        const ovr = getOvr(r.employee_id);
        const calc = getRowCalc(r);
        return {
          employee_id: r.employee_id,
          paid_now_amount: calc.paid,
          adjustments: (ovr.adjustments || []).map(a => ({ type: a.type, title: a.title, amount: a.amount, note: a.note })),
          notes: ovr.notes || "",
        };
      });
      await API.post("/pay-runs", { run_type: "weekly", period_start: periodStart, period_end: periodEnd, rows });
      toast.success("Pay Run създаден + фишове генерирани");
      setTab("history");
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
    finally { setCreating(false); }
  };

  const handleMarkPaid = async (runId) => {
    try {
      await API.post(`/pay-runs/${runId}/mark-paid`);
      toast.success("Маркиран като платен");
      loadRuns(); setDetailRun(null);
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
  };

  const loadDetail = async (runId) => {
    try { const res = await API.get(`/pay-runs/${runId}`); setDetailRun(res.data); } catch {}
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
        {[
          { id: "generate", icon: DollarSign, label: "Ново разплащане" },
          { id: "weeks", icon: Calendar, label: "Седмици" },
          { id: "history", icon: FileText, label: "История" },
          { id: "slips", icon: Receipt, label: "Фишове" },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${tab === t.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`} data-testid={`tab-${t.id}`}>
            <t.icon className="w-3.5 h-3.5" />{t.label}
          </button>
        ))}
      </div>

      {/* ═══ GENERATE ═══ */}
      {tab === "generate" && (
        <>
          <div className="flex items-center gap-3 mb-4 flex-wrap" data-testid="period-picker">
            <div><label className="text-[10px] text-muted-foreground">От</label><Input type="date" value={periodStart} onChange={e => setPeriodStart(e.target.value)} className="h-9 text-xs w-[140px]" /></div>
            <div><label className="text-[10px] text-muted-foreground">До</label><Input type="date" value={periodEnd} onChange={e => setPeriodEnd(e.target.value)} className="h-9 text-xs w-[140px]" /></div>
            <Button variant="outline" size="sm" onClick={loadPreview} className="mt-4">Зареди</Button>
          </div>

          {loadingPreview ? <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          : !preview?.rows?.length ? <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">Няма одобрени отчети за периода</div>
          : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4" data-testid="generate-summary">
                <SumCard label="Служители" value={totals.employees} />
                <SumCard label="Часове" value={`${totals.hours}ч`} />
                <SumCard label="Изработено" value={`${totals.earned?.toFixed(0)} EUR`} color="text-primary" />
                <SumCard label="Остатък" value={`${totals.remaining?.toFixed(0)} EUR`} color="text-amber-400" border="border-amber-500/20" bg="bg-amber-500/5" />
              </div>

              <div className="rounded-xl border border-border bg-card overflow-hidden mb-4" data-testid="generate-table">
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-[10px] min-w-[150px]">Човек</TableHead>
                        <TableHead className="text-[10px] text-center">Дни</TableHead>
                        <TableHead className="text-[10px] text-center">Часове</TableHead>
                        <TableHead className="text-[10px] text-center">Изработено</TableHead>
                        <TableHead className="text-[10px] text-center">Корекции</TableHead>
                        <TableHead className="text-[10px] text-center min-w-[90px]">Плащане</TableHead>
                        <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
                        <TableHead className="text-[10px] w-[40px]" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {preview.rows.filter(r => r.earned_amount > 0).map(row => {
                        const calc = getRowCalc(row);
                        const ovr = getOvr(row.employee_id);
                        const adjs = ovr.adjustments || [];
                        return (
                          <TableRow key={row.employee_id} data-testid={`gen-row-${row.employee_id}`}>
                            <TableCell>
                              <div className="flex items-center gap-2 cursor-pointer" onClick={() => navigate(`/employees/${row.employee_id}?tab=payroll-weeks`)}>
                                {row.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${row.avatar_url}`} className="w-7 h-7 rounded-full object-cover" alt="" /> : <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary">{(row.first_name?.[0] || "")}{(row.last_name?.[0] || "")}</div>}
                                <div>
                                  <p className="text-xs font-medium hover:text-primary">{row.first_name} {row.last_name}</p>
                                  <p className="text-[9px] text-muted-foreground">{row.position || row.pay_type || "—"} {row.rate_type && `(${row.rate_type})`}</p>
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="text-center text-xs font-mono">{row.approved_days}</TableCell>
                            <TableCell className="text-center text-xs font-mono font-bold">{row.approved_hours}</TableCell>
                            <TableCell className="text-center text-xs font-mono text-primary">{row.earned_amount.toFixed(0)}</TableCell>
                            <TableCell className="text-center">
                              <div className="flex flex-col items-center gap-0.5">
                                {adjs.map((a, i) => (
                                  <div key={i} className="flex items-center gap-1 text-[9px]">
                                    <span className={a.type === "bonus" ? "text-emerald-400" : "text-red-400"}>{a.type === "bonus" ? "+" : "-"}{a.amount}</span>
                                    <button onClick={() => removeAdj(row.employee_id, i)} className="text-muted-foreground hover:text-red-400"><X className="w-2.5 h-2.5" /></button>
                                  </div>
                                ))}
                                {calc.bonuses > 0 && <span className="text-[8px] text-emerald-400">+{calc.bonuses}</span>}
                                {calc.deductions > 0 && <span className="text-[8px] text-red-400">-{calc.deductions}</span>}
                              </div>
                            </TableCell>
                            <TableCell className="text-center"><Input type="number" value={ovr.paid ?? row.remaining_after_payment.toFixed(0)} onChange={e => setOvr(row.employee_id, "paid", e.target.value)} className="h-7 w-20 text-xs font-mono text-center text-primary mx-auto font-bold" /></TableCell>
                            <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${calc.remaining < 0 ? "text-red-400" : calc.remaining > 0 ? "text-amber-400" : "text-emerald-400"}`}>{calc.remaining.toFixed(0)}</TableCell>
                            <TableCell>
                              <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => { setAdjDialog(row); setAdjType("deduction"); setAdjTitle(""); setAdjAmount(""); setAdjNote(""); }}>
                                <Plus className="w-3.5 h-3.5" />
                              </Button>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>

              {/* Guardrails */}
              {preview.rows.filter(r => r.earned_amount > 0).some(r => getRowCalc(r).remaining < 0) && (
                <div className="flex items-center gap-2 text-xs text-amber-400 mb-2">
                  <AlertTriangle className="w-3.5 h-3.5" /> Внимание: Има служители с надплащане (остатък &lt; 0). Проверете сумите.
                </div>
              )}

              <div className="flex justify-end">
                <Button onClick={handleCreate} disabled={creating} className="gap-1.5" data-testid="create-payrun-btn">
                  {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  Потвърди и запази
                </Button>
              </div>
            </>
          )}
        </>
      )}

      {/* ═══ HISTORY ═══ */}
      {tab === "history" && (
        loadingRuns ? <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
        : runs.length === 0 ? <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">Няма Pay Run-ове</div>
        : <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="history-table">
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-[10px]">№</TableHead>
                <TableHead className="text-[10px]">Период</TableHead>
                <TableHead className="text-[10px] text-center">Сед.</TableHead>
                <TableHead className="text-[10px] text-center">Хора</TableHead>
                <TableHead className="text-[10px] text-center">Часове</TableHead>
                <TableHead className="text-[10px] text-center">Изработено</TableHead>
                <TableHead className="text-[10px] text-center">Платено</TableHead>
                <TableHead className="text-[10px] text-center">Остатък</TableHead>
                <TableHead className="text-[10px]">Статус</TableHead>
                <TableHead className="text-[10px] w-[40px]" />
              </TableRow></TableHeader>
              <TableBody>
                {runs.map(r => {
                  const t = r.totals || {};
                  return (
                    <TableRow key={r.id} className="hover:bg-muted/10" data-testid={`run-${r.id}`}>
                      <TableCell className="text-xs font-mono font-bold">{r.number}</TableCell>
                      <TableCell className="text-xs font-mono">{r.period_start} → {r.period_end}</TableCell>
                      <TableCell className="text-center text-xs font-mono">{r.week_number || "—"}</TableCell>
                      <TableCell className="text-center text-xs">{t.employees}</TableCell>
                      <TableCell className="text-center text-xs font-mono">{t.hours}</TableCell>
                      <TableCell className="text-center text-xs font-mono text-primary">{t.earned?.toFixed(0)}</TableCell>
                      <TableCell className="text-center text-xs font-mono text-emerald-400">{t.paid?.toFixed(0)}</TableCell>
                      <TableCell className={`text-center text-xs font-mono ${t.remaining > 0 ? "text-amber-400" : "text-muted-foreground"}`}>{t.remaining?.toFixed(0)}</TableCell>
                      <TableCell><Badge variant="outline" className={`text-[9px] ${(STATUS_CFG[r.status] || {}).cls || ""}`}>{(STATUS_CFG[r.status] || {}).label || r.status}</Badge></TableCell>
                      <TableCell><Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => loadDetail(r.id)}><Eye className="w-3.5 h-3.5" /></Button></TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
      )}

      {/* ═══ WEEKS ═══ */}
      {tab === "weeks" && (() => {
        const filteredWeeks = weeks.filter(w => {
          if (weeksFilter === "unpaid") return w.run_status !== "paid";
          if (weeksFilter === "partial") return w.remaining_after_payment > 0 && w.paid_now_amount > 0;
          if (weeksFilter === "overpaid") return w.remaining_after_payment < 0;
          if (weeksFilter === "with_slip") return !!w.slip_number;
          if (weeksFilter === "no_slip") return !w.slip_number;
          return true;
        });
        return (
        <>
          <div className="flex items-center gap-2 mb-4 flex-wrap" data-testid="weeks-filters">
            {[
              { id: "all", label: "Всички" },
              { id: "unpaid", label: "Неплатени" },
              { id: "partial", label: "Частично" },
              { id: "overpaid", label: "Надплатени" },
              { id: "with_slip", label: "С фиш" },
              { id: "no_slip", label: "Без фиш" },
            ].map(f => (
              <button key={f.id} onClick={() => setWeeksFilter(f.id)} className={`px-3 py-1 rounded-full text-[10px] border transition-colors ${weeksFilter === f.id ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground"}`}>{f.label}</button>
            ))}
          </div>
          {loadingWeeks ? <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          : filteredWeeks.length === 0 ? <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">Няма данни за избрания филтър</div>
          : <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="weeks-table">
              <Table>
                <TableHeader><TableRow>
                  <TableHead className="text-[10px]">Сед. №</TableHead>
                  <TableHead className="text-[10px]">Период</TableHead>
                  <TableHead className="text-[10px]">Човек</TableHead>
                  <TableHead className="text-[10px]">Обект</TableHead>
                  <TableHead className="text-[10px] text-center">Дни</TableHead>
                  <TableHead className="text-[10px] text-center">Часове</TableHead>
                  <TableHead className="text-[10px] text-center">Изработено</TableHead>
                  <TableHead className="text-[10px] text-center">Корекции</TableHead>
                  <TableHead className="text-[10px] text-center">Платено</TableHead>
                  <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
                  <TableHead className="text-[10px]">Статус</TableHead>
                  <TableHead className="text-[10px]">Фиш</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {filteredWeeks.map((w, i) => {
                    const isPaid = w.run_status === "paid";
                    const hasRemaining = w.remaining_after_payment > 0;
                    const adjTotal = w.bonuses_amount - w.deductions_amount;
                    return (
                      <TableRow key={`${w.pay_run_id}-${w.employee_id}-${i}`} className={`hover:bg-muted/10 ${isPaid ? "bg-emerald-500/3" : hasRemaining ? "bg-amber-500/3" : ""}`}>
                        <TableCell className="text-xs font-mono font-bold">{w.week_number || "—"}</TableCell>
                        <TableCell className="text-xs font-mono">{w.period_start} → {w.period_end}</TableCell>
                        <TableCell>
                          <button onClick={() => navigate(`/employees/${w.employee_id}?tab=payroll-weeks`)} className="text-xs font-medium hover:text-primary">{w.first_name} {w.last_name}</button>
                          <p className="text-[9px] text-muted-foreground">{w.position || w.pay_type || "—"}</p>
                        </TableCell>
                        <TableCell>{w.sites?.length > 0 ? w.sites.map((s, si) => <span key={si} className="text-[9px] text-primary">{si > 0 ? ", " : ""}{s}</span>) : <span className="text-[10px] text-muted-foreground">—</span>}</TableCell>
                        <TableCell className="text-center text-xs font-mono">{w.approved_days}</TableCell>
                        <TableCell className="text-center text-xs font-mono font-bold">{w.approved_hours}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-primary">{w.earned_amount?.toFixed(0)}</TableCell>
                        <TableCell className="text-center text-[10px] font-mono">{adjTotal !== 0 ? <span className={adjTotal > 0 ? "text-emerald-400" : "text-red-400"}>{adjTotal > 0 ? "+" : ""}{adjTotal}</span> : "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-emerald-400">{w.paid_now_amount?.toFixed(0)}</TableCell>
                        <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${w.remaining_after_payment > 0 ? "text-amber-400" : w.remaining_after_payment < 0 ? "text-red-400" : "text-emerald-400"}`}>{w.remaining_after_payment?.toFixed(0)}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className={`text-[9px] ${isPaid ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : "bg-violet-500/15 text-violet-400 border-violet-500/30"}`}>
                            {isPaid ? "Платен" : "Потвърден"}
                          </Badge>
                        </TableCell>
                        <TableCell>{w.slip_number ? <Badge variant="outline" className="text-[9px] cursor-pointer hover:bg-muted" onClick={() => { if (w.slip_id) { API.get(`/payment-slips/${w.slip_id}`).then(r => setDetailSlip(r.data)).catch(() => {}); } }}>{w.slip_number}</Badge> : <span className="text-[10px] text-muted-foreground">—</span>}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          }
        </>
        );
      })()}

      {/* ═══ SLIPS ═══ */}
      {tab === "slips" && (
        loadingSlips ? <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
        : slips.length === 0 ? <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">Няма фишове</div>
        : <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="slips-table">
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-[10px]">Фиш №</TableHead>
                <TableHead className="text-[10px]">Служител</TableHead>
                <TableHead className="text-[10px]">Период</TableHead>
                <TableHead className="text-[10px] text-center">Часове</TableHead>
                <TableHead className="text-[10px] text-center">Изработено</TableHead>
                <TableHead className="text-[10px] text-center">Удръжки</TableHead>
                <TableHead className="text-[10px] text-center">Платено</TableHead>
                <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
                <TableHead className="text-[10px]">Статус</TableHead>
                <TableHead className="text-[10px] w-[40px]" />
              </TableRow></TableHeader>
              <TableBody>
                {slips.map(s => (
                  <TableRow key={s.id} className="hover:bg-muted/10" data-testid={`slip-${s.id}`}>
                    <TableCell className="text-xs font-mono font-bold">{s.slip_number}</TableCell>
                    <TableCell className="text-xs cursor-pointer hover:text-primary" onClick={() => navigate(`/employees/${s.employee_id}?tab=payroll-weeks`)}>{s.first_name} {s.last_name}</TableCell>
                    <TableCell className="text-xs font-mono">{s.period_start} → {s.period_end}</TableCell>
                    <TableCell className="text-center text-xs font-mono">{s.approved_hours}</TableCell>
                    <TableCell className="text-center text-xs font-mono text-primary">{s.earned_amount?.toFixed(0)}</TableCell>
                    <TableCell className="text-center text-xs font-mono text-red-400">{s.deductions_amount > 0 ? `-${s.deductions_amount.toFixed(0)}` : "—"}</TableCell>
                    <TableCell className="text-center text-xs font-mono text-emerald-400">{s.paid_now_amount?.toFixed(0)}</TableCell>
                    <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${s.remaining_after_payment > 0 ? "text-amber-400" : s.remaining_after_payment < 0 ? "text-red-400" : "text-emerald-400"}`}>{s.remaining_after_payment?.toFixed(0)}</TableCell>
                    <TableCell><Badge variant="outline" className={`text-[9px] ${(STATUS_CFG[s.status] || {}).cls || ""}`}>{(STATUS_CFG[s.status] || {}).label || s.status}</Badge></TableCell>
                    <TableCell><Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setDetailSlip(s)}><Eye className="w-3.5 h-3.5" /></Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
      )}

      {/* Adjustment Dialog */}
      <Dialog open={!!adjDialog} onOpenChange={() => setAdjDialog(null)}>
        <DialogContent className="max-w-sm" data-testid="adj-dialog">
          <DialogHeader><DialogTitle>Корекция: {adjDialog?.first_name} {adjDialog?.last_name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Select value={adjType} onValueChange={setAdjType}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>{ADJ_TYPES.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
            </Select>
            <Input value={adjTitle} onChange={e => setAdjTitle(e.target.value)} placeholder="Заглавие (опц.)" className="h-9" />
            <Input type="number" value={adjAmount} onChange={e => setAdjAmount(e.target.value)} placeholder="Сума EUR" className="h-9" />
            <Input value={adjNote} onChange={e => setAdjNote(e.target.value)} placeholder="Бележка..." className="h-9" />
            <Button onClick={addAdj} disabled={!adjAmount} className="w-full">Добави</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Pay Run Detail */}
      <Dialog open={!!detailRun} onOpenChange={() => setDetailRun(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto" data-testid="payrun-detail-modal">
          <DialogHeader><DialogTitle>Pay Run {detailRun?.number}</DialogTitle></DialogHeader>
          {detailRun && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{detailRun.period_start} → {detailRun.period_end} | Сед. {detailRun.week_number}</span>
                <Badge variant="outline" className={(STATUS_CFG[detailRun.status] || {}).cls}>{(STATUS_CFG[detailRun.status] || {}).label}</Badge>
              </div>
              <div className="rounded-lg border border-border overflow-hidden">
                <Table>
                  <TableHeader><TableRow>
                    <TableHead className="text-[10px]">Човек</TableHead>
                    <TableHead className="text-[10px] text-center">Часове</TableHead>
                    <TableHead className="text-[10px] text-center">Изработено</TableHead>
                    <TableHead className="text-[10px] text-center">Корекции</TableHead>
                    <TableHead className="text-[10px] text-center">Платено</TableHead>
                    <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {detailRun.employee_rows?.map(r => (
                      <TableRow key={r.employee_id}>
                        <TableCell className="text-xs font-medium">{r.first_name} {r.last_name}</TableCell>
                        <TableCell className="text-center text-xs font-mono">{r.approved_hours}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-primary">{r.earned_amount?.toFixed(0)}</TableCell>
                        <TableCell className="text-center">
                          {r.adjustments?.length > 0 ? r.adjustments.map((a, i) => (
                            <div key={i} className={`text-[9px] ${a.type === "bonus" ? "text-emerald-400" : "text-red-400"}`}>{a.type === "bonus" ? "+" : "-"}{a.amount} {a.title}</div>
                          )) : <span className="text-[10px] text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell className="text-center text-xs font-mono text-emerald-400">{r.paid_now_amount?.toFixed(0)}</TableCell>
                        <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${r.remaining_after_payment > 0 ? "text-amber-400" : r.remaining_after_payment < 0 ? "text-red-400" : "text-emerald-400"}`}>{r.remaining_after_payment?.toFixed(0)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {detailRun.status === "confirmed" && (
                <div className="flex justify-end">
                  <Button onClick={() => handleMarkPaid(detailRun.id)} className="gap-1.5 bg-emerald-600 hover:bg-emerald-700" data-testid="mark-paid-btn"><Check className="w-4 h-4" /> Маркирай платен</Button>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Slip Detail */}
      <Dialog open={!!detailSlip} onOpenChange={() => setDetailSlip(null)}>
        <DialogContent className="max-w-lg" data-testid="slip-detail-modal">
          <DialogHeader><DialogTitle>Фиш {detailSlip?.slip_number}</DialogTitle></DialogHeader>
          {detailSlip && (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 rounded-lg bg-muted/30">
                <div>
                  <p className="font-semibold">{detailSlip.first_name} {detailSlip.last_name}</p>
                  <p className="text-xs text-muted-foreground">{detailSlip.position || "—"} | {detailSlip.pay_type} | {detailSlip.payment_schedule || "—"}</p>
                </div>
                <div className="text-right">
                  <Badge variant="outline" className={(STATUS_CFG[detailSlip.status] || {}).cls}>{(STATUS_CFG[detailSlip.status] || {}).label}</Badge>
                  <p className="text-[10px] text-muted-foreground mt-1">{detailSlip.period_start} → {detailSlip.period_end}</p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <SumCard label="Дни" value={detailSlip.approved_days} />
                <SumCard label="Часове" value={`${detailSlip.approved_hours}ч`} />
                <SumCard label="Ставка" value={`${detailSlip.frozen_hourly_rate} EUR/ч`} />
              </div>
              {detailSlip.adjustments?.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] text-muted-foreground font-semibold uppercase">Корекции</p>
                  {detailSlip.adjustments.map((a, i) => (
                    <div key={i} className="flex justify-between text-xs px-2">
                      <span className={a.type === "bonus" ? "text-emerald-400" : "text-red-400"}>{a.title || a.type} {a.note && `(${a.note})`}</span>
                      <span className="font-mono">{a.type === "bonus" ? "+" : "-"}{a.amount} EUR</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-1 text-xs">
                <div className="flex justify-between"><span>Изработено</span><span className="font-mono">{detailSlip.earned_amount?.toFixed(2)} EUR</span></div>
                {detailSlip.bonuses_amount > 0 && <div className="flex justify-between text-emerald-400"><span>+ Бонуси</span><span className="font-mono">+{detailSlip.bonuses_amount?.toFixed(2)} EUR</span></div>}
                {detailSlip.deductions_amount > 0 && <div className="flex justify-between text-red-400"><span>- Удръжки</span><span className="font-mono">-{detailSlip.deductions_amount?.toFixed(2)} EUR</span></div>}
                {detailSlip.previously_paid > 0 && <div className="flex justify-between text-muted-foreground"><span>- Вече платено</span><span className="font-mono">-{detailSlip.previously_paid?.toFixed(2)} EUR</span></div>}
                <div className="flex justify-between font-bold text-sm pt-1 border-t border-border"><span>Платено сега</span><span className="font-mono text-primary">{detailSlip.paid_now_amount?.toFixed(2)} EUR</span></div>
                <div className="flex justify-between"><span>Остатък</span><span className={`font-mono font-bold ${detailSlip.remaining_after_payment > 0 ? "text-amber-400" : "text-emerald-400"}`}>{detailSlip.remaining_after_payment?.toFixed(2)} EUR</span></div>
              </div>
              {detailSlip.paid_at && <p className="text-xs text-emerald-400 flex items-center gap-1"><Check className="w-3 h-3" /> Платено на {detailSlip.paid_at?.slice(0, 10)}</p>}
              {detailSlip.remaining_after_payment < 0 && <p className="text-xs text-red-400 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> Внимание: Надплащане ({detailSlip.remaining_after_payment?.toFixed(2)} EUR)</p>}
              <div className="flex items-center gap-2 mt-2">
                <span className="text-[9px] text-muted-foreground">Формула: Остатък = Изработено + Бонуси - Удръжки - Вече платено - Платено сега</span>
              </div>
              <Button variant="outline" size="sm" className="w-full mt-2 gap-1.5" onClick={() => window.open(`${process.env.REACT_APP_BACKEND_URL}/api/payment-slips/${detailSlip.id}/pdf`, "_blank")} data-testid="slip-pdf-btn">
                <FileText className="w-3.5 h-3.5" /> PDF / Печат
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SumCard({ label, value, color = "", border = "border-border", bg = "bg-card" }) {
  return (
    <div className={`rounded-lg ${bg} border ${border} p-3 text-center`}>
      <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
      <p className="text-[10px] text-muted-foreground">{label}</p>
    </div>
  );
}
