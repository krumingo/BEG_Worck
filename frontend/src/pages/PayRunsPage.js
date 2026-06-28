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
  DollarSign, Loader2, Check, FileText, Eye, Plus, X, Receipt, Calendar, MapPin, AlertTriangle, Clock, Printer, Lock, X as XIcon,
} from "lucide-react";
import { toast } from "sonner";
import { openGroupPrint, openIndividualPrint, openSelectedPrint } from "@/components/PayRunPrintView";

const STATUS_CFG = {
  draft:     { label: "Чернова",   cls: "bg-gray-500/15 text-gray-400 border-gray-500/30" },
  confirmed: { label: "Потвърден", cls: "bg-violet-500/15 text-violet-400 border-violet-500/30" },
  paid:      { label: "Платен",    cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
  reopened:  { label: "Отворен",   cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
  cancelled: { label: "Отменен",   cls: "bg-red-500/15 text-red-400 border-red-500/30" },
};

// P0-2A: Payroll status colors for calendar cells.
// Mirrors PAYROLL_BADGE from AllReportsPage.js — same semantics, same colors.
const PAYROLL_CELL_CFG = {
  none:           { cls: "bg-blue-500/15  text-blue-300   border-blue-500/30",    label: "Избираем" },
  eligible:       { cls: "bg-blue-500/15  text-blue-300   border-blue-500/30",    label: "Избираем" },
  batched:        { cls: "bg-violet-500/15 text-violet-300 border-violet-500/30", label: "В pay-run" },
  paid:           { cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30", label: "Платен" },
  partially_paid: { cls: "bg-amber-500/15 text-amber-300  border-amber-500/30",   label: "Частично" },
};
const PAYROLL_CELL_REJECTED = { cls: "bg-gray-500/15 text-gray-400 border-gray-500/30", label: "Отхвърлен" };

// Day-of-week names for column headers (index matches JS Date.getDay(): 0=Sun..6=Sat)
const BG_D = ["Нд", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

const ADJ_TYPES = [
  { value: "bonus", label: "Бонус", color: "text-emerald-400" },
  { value: "advance", label: "Аванс", color: "text-blue-400" },
  { value: "loan_repayment", label: "Погасяване заем", color: "text-red-400" },
  { value: "deduction", label: "Удръжка", color: "text-red-400" },
  { value: "manual_correction", label: "Ръчна корекция", color: "text-amber-400" },
];

// P0-2A: compute payroll week range based on first_day setting.
// first_day: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat (JS Date.getDay() convention).
// Returns [start_date, end_date] as YYYY-MM-DD strings, 7-day span.
// For BEG default (first_day=6, Saturday): today=Wed 28.05 → start=Sat 23.05, end=Fri 29.05.
function computePayrollWeek(firstDay = 6, today = new Date()) {
  const d = new Date(today);
  d.setHours(0, 0, 0, 0);
  const todayDow = d.getDay();
  // Find the most recent occurrence of firstDay (today or earlier).
  // Example: today=Wed (3), firstDay=Sat (6) → diff = (3 - 6 + 7) % 7 = 4 → go back 4 days to Saturday.
  const diff = (todayDow - firstDay + 7) % 7;
  const start = new Date(d);
  start.setDate(start.getDate() - diff);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const fmt = (dt) => dt.toISOString().slice(0, 10);
  return [fmt(start), fmt(end)];
}

export default function PayRunsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("generate");

  // P0-2A: payroll week setting (loaded from /settings/payroll-week, default Saturday=6)
  const [payrollWeekFirstDay, setPayrollWeekFirstDay] = useState(6);

  const [periodStart, setPeriodStart] = useState(() => {
    const [start] = computePayrollWeek(6);
    return start;
  });
  const [periodEnd, setPeriodEnd] = useState(() => {
    const [, end] = computePayrollWeek(6);
    return end;
  });

  const [preview, setPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [overrides, setOverrides] = useState({});
  const [creating, setCreating] = useState(false);

  const [selectedEmps, setSelectedEmps] = useState(new Set());
  const [selectedDays, setSelectedDays] = useState({});

  // Step: "grid" | "adjustments" | "payment"
  const [step, setStep] = useState("grid");
  // Day overrides: { `${eid}_${date}`: { hours, value, reason } }
  const [dayOverrides, setDayOverrides] = useState({});
  // Adjustment rows per employee
  const [adjustments, setAdjustments] = useState({});
  // Step 3: actual payment amounts
  const [paidAmounts, setPaidAmounts] = useState({}); // { eid: number }
  const [paySelected, setPaySelected] = useState(new Set()); // which employees are in payment batch
  // Day edit dialog
  const [dayEditDialog, setDayEditDialog] = useState(null);
  const [dayEditHours, setDayEditHours] = useState("");
  const [dayEditValue, setDayEditValue] = useState("");
  const [dayEditReason, setDayEditReason] = useState("");

  // P0-2A.2: per-report selection popup state.
  // reportPopup = { eid, date, row, dc } when open, null when closed.
  // selectedReportIds = { [eid]: Set<report_id> } — explicit per-report selection per employee.
  // When empty for an eid, backend falls back to day-level (P0-2A.1) behavior.
  const [reportPopup, setReportPopup] = useState(null);
  const [selectedReportIds, setSelectedReportIds] = useState({});

  const toggleReportSelection = (eid, reportId) => {
    setSelectedReportIds(prev => {
      const ids = new Set(prev[eid] || []);
      if (ids.has(reportId)) ids.delete(reportId); else ids.add(reportId);
      return { ...prev, [eid]: ids };
    });
  };

  // Audit check
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditData, setAuditData] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const runAudit = async () => {
    setAuditLoading(true); setAuditOpen(true); setAuditData(null);
    try {
      const res = await API.get("/pay-runs/audit-check");
      setAuditData(res.data);
    } catch { toast.error("Грешка при одит проверка"); }
    finally { setAuditLoading(false); }
  };

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

  // Monthly calendar
  const [monthYear, setMonthYear] = useState(() => new Date().toISOString().slice(0, 7));
  const [monthData, setMonthData] = useState(null);
  const [loadingMonth, setLoadingMonth] = useState(false);
  const [monthDetail, setMonthDetail] = useState(null); // employee detail

  const loadPreview = useCallback(async () => {
    setLoadingPreview(true);
    try {
      // P0-2A: review_mode=true so paid/batched reports also appear in the calendar (locked).
      // Real pay-run creation still uses generate without review_mode → only unpaid reports.
      const res = await API.get(`/pay-runs/generate?period_start=${periodStart}&period_end=${periodEnd}&review_mode=true`);
      setPreview(res.data);
      setOverrides({});
      setDayOverrides({});
      setPaidAmounts({});
      setPaySelected(new Set());
      setSelectedReportIds({});  // P0-2A.2: clear per-report selections on reload
      setStep("grid");
      // Auto-select all employees with data and all their days
      const emps = new Set();
      const days = {};
      const autoAdj = {};
      for (const r of (res.data.rows || [])) {
        if (r.earned_amount > 0) {
          emps.add(r.employee_id);
          // P0-2A.1 FIX 2: auto-select unpaid/eligible AND partially_paid cells.
          // partially_paid means some reports are paid, but some unpaid approved reports remain.
          // Backend (FIX 1 in pay-run filter) automatically skips already-paid reports,
          // so selecting a partially_paid cell only adds the still-unpaid reports.
          // Locked cells (paid/batched) stay visible but are not pre-selected.
          days[r.employee_id] = new Set(
            (r.day_cells || [])
              .filter(d => {
                const st = d.payroll_status || "none";
                return st === "none" || st === "eligible" || st === "partially_paid";
              })
              .map(d => d.date)
          );
          // 3a: auto-suggest advance deductions, capped at available salary (rest carries to next run)
          const _avail = Math.max(0, (r.earned_amount || 0) - (r.previously_paid || 0));
          let _cap = _avail;
          const _advList = [];
          for (const adv of (r.open_advances || [])) {
            if (_cap <= 0) break;
            const _amt = Math.min(adv.remaining_amount || 0, _cap);
            if (_amt > 0) {
              _advList.push({ type: "advance", title: "Аванс (авто)", amount: Math.round(_amt * 100) / 100, note: "", ref_id: adv.id });
              _cap = Math.round((_cap - _amt) * 100) / 100;
            }
          }
          if (_advList.length) autoAdj[r.employee_id] = _advList;
        }
      }
      setAdjustments(autoAdj);
      setSelectedEmps(emps);
      setSelectedDays(days);
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

  const loadMonth = useCallback(async () => {
    setLoadingMonth(true);
    try {
      const res = await API.get(`/payroll-weeks?month=${monthYear}`);
      setMonthData(res.data.items || []);
    } catch { setMonthData(null); }
    finally { setLoadingMonth(false); }
  }, [monthYear]);

  useEffect(() => { if (tab === "generate") loadPreview(); }, [tab, loadPreview]);
  useEffect(() => { if (tab === "history") loadRuns(); }, [tab, loadRuns]);
  useEffect(() => { if (tab === "slips") loadSlips(); }, [tab, loadSlips]);
  useEffect(() => { if (tab === "weeks") loadWeeks(); }, [tab, loadWeeks]);
  useEffect(() => { if (tab === "monthly") loadMonth(); }, [tab, loadMonth, monthYear]);

  // P0-2A: load payroll-week settings on mount, recompute default period.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await API.get("/settings/payroll-week");
        if (cancelled) return;
        const fd = (typeof res.data?.first_day === "number") ? res.data.first_day : 6;
        setPayrollWeekFirstDay(fd);
        // Recompute period using loaded setting (only if user hasn't changed it manually)
        const [start, end] = computePayrollWeek(fd);
        setPeriodStart(start);
        setPeriodEnd(end);
      } catch (e) {
        // Settings not available — keep default (Saturday). Silent.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // P0-2A: update payroll week setting from dropdown.
  const updatePayrollWeekFirstDay = async (newFirstDay) => {
    const fd = parseInt(newFirstDay, 10);
    setPayrollWeekFirstDay(fd);
    // Recompute period
    const [start, end] = computePayrollWeek(fd);
    setPeriodStart(start);
    setPeriodEnd(end);
    try {
      await API.put("/settings/payroll-week", { first_day: fd });
      toast.success("Настройка запазена");
    } catch (e) {
      toast.error("Грешка при запазване");
    }
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

  const buildRows = () => {
    if (!preview) return [];
    const usePayment = step === "payment";
    const filterSet = usePayment ? paySelected : selectedEmps;
    return preview.rows.filter(r => filterSet.has(r.employee_id)).map(r => {
      const empDays = selectedDays[r.employee_id] || new Set();
      const empAdj = getEmpAdj(r.employee_id);
      const paidNow = usePayment ? (paidAmounts[r.employee_id] ?? getEmpNet(r)) : getEmpNet(r);
      // P0-2A.2: include explicit selected_report_ids if any were chosen via popup.
      // Empty list → backend uses day-level fallback (P0-2A.1 behavior).
      const reportIds = Array.from(selectedReportIds[r.employee_id] || []);
      return {
        employee_id: r.employee_id,
        paid_now_amount: Math.round(paidNow * 100) / 100,
        adjustments: empAdj.map(a => ({ type: a.type, title: a.title, amount: a.amount, note: a.note, ref_id: a.ref_id || null })),
        notes: "",
        selected_report_ids: reportIds,
      };
    });
  };

  const toggleEmp = (eid) => {
    const row = (preview?.rows || []).find(r => r.employee_id === eid);
    if (row && (row.previously_paid || 0) > 0 && (row.remaining_after_payment || 0) <= 0) return;
    setSelectedEmps(prev => {
      const next = new Set(prev);
      if (next.has(eid)) next.delete(eid); else next.add(eid);
      return next;
    });
  };

  const toggleDay = (eid, date) => {
    setSelectedDays(prev => {
      const empDays = new Set(prev[eid] || []);
      if (empDays.has(date)) empDays.delete(date); else empDays.add(date);
      return { ...prev, [eid]: empDays };
    });
  };

  const selectAllEmps = () => {
    const emps = new Set();
    const days = {};
    for (const r of (preview?.rows || [])) {
      const isFullyPaid = (r.previously_paid || 0) > 0 && (r.remaining_after_payment || 0) <= 0;
      if (r.earned_amount > 0 && !isFullyPaid) {
        emps.add(r.employee_id);
        // P0-2A.1 FIX 2: include unpaid/eligible AND partially_paid cells.
        // Skip locked (paid/batched). Backend filters paid reports automatically.
        days[r.employee_id] = new Set(
          (r.day_cells || [])
            .filter(d => {
              const st = d.payroll_status || "none";
              return st === "none" || st === "eligible" || st === "partially_paid";
            })
            .map(d => d.date)
        );
      }
    }
    setSelectedEmps(emps);
    setSelectedDays(days);
  };

  // P0-2A.1 FIX 3: Clear button should only clear selected days, NOT remove employees.
  // Old behavior removed employees from selectedEmps, which made isSelected=false → cell onClick
  // was blocked by `if (!isLocked && isSelected) toggleDay(...)`. Now we keep all employees
  // visible and selectable, but with no days picked — user can manually click cells to select.
  const clearAllEmps = () => {
    const allEmps = new Set(
      (preview?.rows || [])
        .filter(r => r.earned_amount > 0)
        .map(r => r.employee_id)
    );
    setSelectedEmps(allEmps);  // keep employees selectable
    setSelectedDays({});        // clear all day selections
  };

  const selectAllDaysForEmp = (eid, dayCells) => {
    // P0-2A.1 FIX 2: include unpaid/eligible AND partially_paid cells.
    setSelectedDays(prev => ({
      ...prev,
      [eid]: new Set(
        (dayCells || [])
          .filter(d => {
            const st = d.payroll_status || "none";
            return st === "none" || st === "eligible" || st === "partially_paid";
          })
          .map(d => d.date)
      ),
    }));
    setSelectedEmps(prev => new Set([...prev, eid]));
  };

  const clearAllDaysForEmp = (eid) => {
    setSelectedDays(prev => ({ ...prev, [eid]: new Set() }));
  };

  // P0-2A.3: helper to compute effective day value considering per-report selection.
  // Priority order:
  //   1. dayOverrides (manual edit) — takes precedence over everything.
  //   2. selectedReportIds for this employee (popup picked specific reports) — sum only those.
  //   3. dc.selectable_value (backend-provided unpaid-only sum) — for partially paid cells.
  //   4. dc.value (legacy) — full day total.
  const getDayValue = (eid, dc) => {
    const key = `${eid}_${dc.date}`;
    const ovr = dayOverrides[key];
    if (ovr) return ovr.value;
    // P0-2A.3: if user picked specific reports for this employee, use only those that fall in this day.
    const empReportIds = selectedReportIds[eid];
    if (empReportIds && empReportIds.size > 0 && Array.isArray(dc.reports)) {
      const picked = dc.reports.filter(r => empReportIds.has(r.report_id));
      if (picked.length > 0) {
        return picked.reduce((s, r) => s + (r.value || 0), 0);
      }
      // If no picks for this day but employee has popup picks elsewhere → 0 for this day.
      return 0;
    }
    // Fallback: prefer selectable_value (unpaid-only) when backend provides it.
    if (typeof dc.selectable_value === "number" && dc.selectable_value > 0) {
      return dc.selectable_value;
    }
    return dc.value;
  };

  const getDayHours = (eid, dc) => {
    const key = `${eid}_${dc.date}`;
    const ovr = dayOverrides[key];
    if (ovr) return ovr.hours;
    // P0-2A.3: per-report selection for this employee.
    const empReportIds = selectedReportIds[eid];
    if (empReportIds && empReportIds.size > 0 && Array.isArray(dc.reports)) {
      const picked = dc.reports.filter(r => empReportIds.has(r.report_id));
      if (picked.length > 0) {
        return Math.round(picked.reduce((s, r) => s + (r.hours || 0), 0) * 10) / 10;
      }
      return 0;
    }
    if (typeof dc.selectable_hours === "number" && dc.selectable_hours > 0) {
      return dc.selectable_hours;
    }
    return dc.hours;
  };

  const getEmpPayAmount = (row) => {
    const empDays = selectedDays[row.employee_id] || new Set();
    return (row.day_cells || []).filter(d => empDays.has(d.date)).reduce((s, d) => s + getDayValue(row.employee_id, d), 0);
  };

  const getEmpAdj = (eid) => adjustments[eid] || [];
  const getEmpBonuses = (eid) => getEmpAdj(eid).filter(a => a.type === "bonus").reduce((s, a) => s + a.amount, 0);
  const getEmpDeductions = (eid) => getEmpAdj(eid).filter(a => a.type !== "bonus").reduce((s, a) => s + a.amount, 0);
  const getEmpNet = (row) => {
    const gross = getEmpPayAmount(row);
    const bonuses = getEmpBonuses(row.employee_id);
    const deductions = getEmpDeductions(row.employee_id);
    return Math.round((gross + bonuses - deductions) * 100) / 100;
  };

  const totalSelectedPay = (preview?.rows || [])
    .filter(r => selectedEmps.has(r.employee_id))
    .reduce((s, r) => s + getEmpNet(r), 0);

  const totalSelectedEmps = selectedEmps.size;
  const totalSelectedDays = Object.values(selectedDays).reduce((s, ds) => s + ds.size, 0);

  // Step 3 helpers
  const getActualPaid = (eid) => paidAmounts[eid] ?? null; // null = not set yet
  const getRemaining = (row) => {
    const net = getEmpNet(row);
    const paid = getActualPaid(row.employee_id);
    return paid !== null ? Math.round((net - paid) * 100) / 100 : 0;
  };

  const initPaymentStep = () => {
    // Pre-fill paid amounts = net for all selected employees
    const amounts = {};
    const selected = new Set();
    for (const r of (preview?.rows || [])) {
      if (selectedEmps.has(r.employee_id) && getEmpPayAmount(r) > 0) {
        amounts[r.employee_id] = getEmpNet(r);
        selected.add(r.employee_id);
      }
    }
    setPaidAmounts(amounts);
    setPaySelected(selected);
    setStep("payment");
  };

  const fillAllPaidEqNet = () => {
    const amounts = { ...paidAmounts };
    for (const r of (preview?.rows || [])) {
      if (paySelected.has(r.employee_id)) {
        amounts[r.employee_id] = getEmpNet(r);
      }
    }
    setPaidAmounts(amounts);
  };

  const clearAllPaid = () => {
    const amounts = { ...paidAmounts };
    for (const eid of paySelected) amounts[eid] = 0;
    setPaidAmounts(amounts);
  };

  const payTotals = (() => {
    const rows = (preview?.rows || []).filter(r => paySelected.has(r.employee_id));
    const net = rows.reduce((s, r) => s + getEmpNet(r), 0);
    const paid = rows.reduce((s, r) => s + (paidAmounts[r.employee_id] ?? 0), 0);
    return { count: rows.length, net: Math.round(net * 100) / 100, paid: Math.round(paid * 100) / 100, carry: Math.round((net - paid) * 100) / 100 };
  })();

  const handleSaveDraft = async () => {
    if (!preview) return;
    setCreating(true);
    try {
      await API.post("/pay-runs", { run_type: "weekly", period_start: periodStart, period_end: periodEnd, rows: buildRows(), status: "draft" });
      toast.success("Чернова записана");
      setTab("history");
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
    finally { setCreating(false); }
  };

  const handleCreate = async () => {
    if (!preview) return;
    setCreating(true);
    try {
      await API.post("/pay-runs", { run_type: "weekly", period_start: periodStart, period_end: periodEnd, rows: buildRows(), status: "confirmed" });
      toast.success("Pay Run потвърден");
      setTab("history");
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
    finally { setCreating(false); }
  };

  // Day edit
  const openDayEdit = (eid, dc, row) => {
    const key = `${eid}_${dc.date}`;
    const ovr = dayOverrides[key];
    setDayEditHours(String(ovr?.hours ?? dc.hours));
    setDayEditValue(String(ovr?.value ?? dc.value));
    setDayEditReason(ovr?.reason || "");
    setDayEditDialog({ eid, date: dc.date, cell: dc, row });
  };

  const saveDayEdit = () => {
    if (!dayEditDialog) return;
    const key = `${dayEditDialog.eid}_${dayEditDialog.date}`;
    setDayOverrides(prev => ({
      ...prev,
      [key]: {
        hours: parseFloat(dayEditHours) || 0,
        value: parseFloat(dayEditValue) || 0,
        reason: dayEditReason,
        source_hours: dayEditDialog.cell.hours,
        source_value: dayEditDialog.cell.value,
      },
    }));
    setDayEditDialog(null);
  };

  // Adjustments
  const addAdj = (eid) => {
    if (!adjAmount) return;
    setAdjustments(prev => ({
      ...prev,
      [eid]: [...(prev[eid] || []), { type: adjType, title: adjTitle || ADJ_TYPES.find(t => t.value === adjType)?.label, amount: parseFloat(adjAmount) || 0, note: adjNote }],
    }));
    setAdjDialog(null); setAdjTitle(""); setAdjAmount(""); setAdjNote("");
  };

  const removeAdj = (eid, idx) => {
    setAdjustments(prev => ({ ...prev, [eid]: (prev[eid] || []).filter((_, i) => i !== idx) }));
  };

  const [payDialog, setPayDialog] = useState(null); // run_id
  const [payMethod, setPayMethod] = useState("cash");
  const [payRef, setPayRef] = useState("");
  const [payNote, setPayNote] = useState("");

  const handleMarkPaid = async (runId) => {
    try {
      await API.post(`/pay-runs/${runId}/mark-paid`, {
        payment_method: payMethod,
        payment_reference: payRef,
        payment_note: payNote,
      });
      toast.success("Маркиран като платен");
      setPayDialog(null); setPayMethod("cash"); setPayRef(""); setPayNote("");
      loadRuns(); setDetailRun(null);
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
  };

  const handleReopen = async (runId, employeeIds = [], reason = "") => {
    try {
      await API.post(`/pay-runs/${runId}/reopen`, { employee_ids: employeeIds, reason });
      toast.success(employeeIds.length > 0 ? `Отворени ${employeeIds.length} реда` : "Batch отворен за редакция");
      loadRuns(); setDetailRun(null);
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
  };

  const [historyData, setHistoryData] = useState(null);
  const [allocData, setAllocData] = useState(null);
  const [printSelected, setPrintSelected] = useState(new Set());
  const loadHistory = async (runId) => {
    try { const res = await API.get(`/pay-runs/${runId}/history`); setHistoryData(res.data); }
    catch { setHistoryData(null); }
  };

  const loadAlloc = async (runId) => {
    try { const res = await API.get(`/pay-runs/${runId}/allocations`); setAllocData(res.data); }
    catch { setAllocData(null); }
  };

  const loadDetail = async (runId) => {
    try { const res = await API.get(`/pay-runs/${runId}`); setDetailRun(res.data); } catch {}
    loadAlloc(runId);
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
          { id: "monthly", icon: Calendar, label: "Месечен" },
          { id: "weeks", icon: Calendar, label: "Седмици" },
          { id: "history", icon: FileText, label: "История" },
          { id: "slips", icon: Receipt, label: "Фишове" },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${tab === t.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`} data-testid={`tab-${t.id}`}>
            <t.icon className="w-3.5 h-3.5" />{t.label}
          </button>
        ))}
        <div className="ml-auto">
          <Button variant="outline" size="sm" onClick={runAudit} className="text-xs gap-1" data-testid="audit-btn">
            <AlertTriangle className="w-3.5 h-3.5" />Одит проверка
          </Button>
        </div>
      </div>

      {/* ═══ GENERATE — Weekly Grid ═══ */}
      {tab === "generate" && (
        <>
          <div className="flex items-center gap-3 mb-4 flex-wrap" data-testid="period-picker">
            <div><label className="text-[10px] text-muted-foreground">От</label><Input type="date" value={periodStart} onChange={e => setPeriodStart(e.target.value)} className="h-9 text-xs w-[140px]" /></div>
            <div><label className="text-[10px] text-muted-foreground">До</label><Input type="date" value={periodEnd} onChange={e => setPeriodEnd(e.target.value)} className="h-9 text-xs w-[140px]" /></div>
            <Button variant="outline" size="sm" onClick={loadPreview} className="mt-4">Зареди</Button>
            {/* P0-2A: Payroll week first-day setting, per organization. */}
            <div className="ml-auto flex items-center gap-2 mt-4 px-3 py-1.5 rounded-md bg-amber-500/10 border border-amber-500/20">
              <label className="text-[11px] text-amber-400 whitespace-nowrap">Седмица започва от:</label>
              <Select value={String(payrollWeekFirstDay)} onValueChange={updatePayrollWeekFirstDay}>
                <SelectTrigger className="h-7 w-[120px] text-xs border-amber-500/30 bg-transparent">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">Неделя</SelectItem>
                  <SelectItem value="1">Понеделник</SelectItem>
                  <SelectItem value="2">Вторник</SelectItem>
                  <SelectItem value="3">Сряда</SelectItem>
                  <SelectItem value="4">Четвъртък</SelectItem>
                  <SelectItem value="5">Петък</SelectItem>
                  <SelectItem value="6">Събота</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {loadingPreview ? <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          : !preview?.rows?.length ? <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">Няма одобрени отчети за периода</div>
          : (() => {
            // P0-2A.1 FIX 1: Sort dates correctly based on period length.
            // - For 7 days or fewer: use custom day-of-week order (Sat→Fri for BEG)
            //   This makes a payroll week start on the configured first_day.
            // - For more than 7 days: sort chronologically by date.
            //   Sorting by day-of-week with multiple weeks would group all Mondays
            //   together, then all Tuesdays etc. — that breaks readability.
            const rawDates = preview.dates || [];
            const fd = payrollWeekFirstDay;
            const isLongPeriod = rawDates.length > 7;
            let dates;
            if (isLongPeriod) {
              // Chronological sort by date string (YYYY-MM-DD sorts naturally)
              dates = [...rawDates].sort();
            } else {
              // Single-week: order by configured first_day → first_day+6
              const customOrder = [0,1,2,3,4,5,6].map(i => (fd + i) % 7);
              dates = [...rawDates].sort((a, b) => {
                const da = new Date(a + "T12:00:00").getDay();
                const db = new Date(b + "T12:00:00").getDay();
                return customOrder.indexOf(da) - customOrder.indexOf(db);
              });
            }
            const BG_D = ["Нд","Пон","Вт","Ср","Чет","Пет","Съб"];
            return (
            <>
              {/* Warnings */}
              {preview.warnings?.length > 0 && (
                <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg border border-amber-500/30 bg-amber-500/5 text-xs text-amber-400">
                  <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                  {preview.warnings.join(" | ")}
                </div>
              )}

              {/* Step tabs */}
              <div className="flex items-center gap-2 mb-3">
                <button onClick={() => setStep("grid")} className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${step === "grid" ? "bg-primary/15 text-primary border border-primary/30" : "text-muted-foreground hover:text-foreground border border-transparent"}`}>1. Дни</button>
                <span className="text-muted-foreground text-xs">→</span>
                <button onClick={() => setStep("adjustments")} className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${step === "adjustments" ? "bg-primary/15 text-primary border border-primary/30" : "text-muted-foreground hover:text-foreground border border-transparent"}`}>2. Корекции</button>
                <span className="text-muted-foreground text-xs">→</span>
                <button onClick={() => initPaymentStep()} className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${step === "payment" ? "bg-primary/15 text-primary border border-primary/30" : "text-muted-foreground hover:text-foreground border border-transparent"}`}>3. Плащане</button>
              </div>

              {/* Header */}
              <div className="flex items-center justify-between mb-3 px-1">
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span>Избрани: <strong className="text-foreground">{totalSelectedEmps}</strong> хора</span>
                  <span>Дни: <strong className="text-foreground">{totalSelectedDays}</strong></span>
                  <span>Нетно: <strong className="text-primary font-mono text-sm">{totalSelectedPay.toFixed(0)} €</strong></span>
                </div>
                {step === "grid" && <div className="flex gap-1">
                  <Button variant="ghost" size="sm" className="h-7 text-[10px]" onClick={selectAllEmps}>Избери всички</Button>
                  <Button variant="ghost" size="sm" className="h-7 text-[10px]" onClick={clearAllEmps}>Изчисти</Button>
                </div>}
              </div>

              {/* Weekly grid — Step 1 */}
              {step === "grid" && (
              <div className="rounded-xl border border-border bg-card overflow-hidden mb-4" data-testid="weekly-grid">
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-[10px] w-[30px] text-center"><input type="checkbox" checked={totalSelectedEmps === preview.rows.filter(r => r.earned_amount > 0).length} onChange={e => e.target.checked ? selectAllEmps() : clearAllEmps()} className="rounded" /></TableHead>
                        <TableHead className="text-[10px] min-w-[140px] sticky left-0 bg-card z-10">Служител</TableHead>
                        {dates.map(d => {
                          const dt = new Date(d + "T12:00:00");
                          const wd = dt.getDay();
                          const isWeekend = wd === 0 || wd === 6;
                          return (
                            <TableHead key={d} className={`text-[10px] text-center min-w-[68px] ${isWeekend ? "bg-muted/20" : ""}`}>
                              <div>{BG_D[wd]}</div>
                              <div className="text-[8px] text-muted-foreground font-normal">{dt.getDate()}.{String(dt.getMonth()+1).padStart(2,"0")}</div>
                            </TableHead>
                          );
                        })}
                        <TableHead className="text-[10px] text-center bg-primary/10 min-w-[75px]">За плащане</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {preview.rows.filter(r => r.earned_amount > 0).map(row => {
                        const eid = row.employee_id;
                        const isSelected = selectedEmps.has(eid);
                        const empDays = selectedDays[eid] || new Set();
                        const payAmount = getEmpPayAmount(row);
                        const isFullyPaid = (row.previously_paid || 0) > 0 && (row.remaining_after_payment || 0) <= 0;
                        const dayCellMap = {};
                        (row.day_cells || []).forEach(dc => { dayCellMap[dc.date] = dc; });

                        return (
                          <TableRow key={eid} className={`${isSelected ? "" : "opacity-40"} ${isFullyPaid ? "opacity-60" : ""}`} data-testid={`grid-row-${eid}`}>
                            <TableCell className="text-center"><input type="checkbox" checked={isSelected} disabled={isFullyPaid} onChange={() => toggleEmp(eid)} className="rounded" /></TableCell>
                            <TableCell className="sticky left-0 bg-card z-10">
                              <div className="flex items-center gap-2">
                                {row.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${row.avatar_url}`} className="w-8 h-8 rounded-full object-cover" alt="" /> : <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-[10px] font-bold text-primary">{(row.first_name?.[0] || "")}{(row.last_name?.[0] || "")}</div>}
                                <div className="min-w-0">
                                  <div className="flex items-center gap-1.5">
                                    <p className="text-xs font-medium truncate max-w-[100px]">{row.first_name} {row.last_name}</p>
                                    {row.previously_paid > 0 && row.remaining_after_payment <= 0 && (
                                      <Badge variant="outline" className="text-[7px] bg-emerald-500/15 text-emerald-400 border-emerald-500/30 px-1 py-0 h-3.5">Платено</Badge>
                                    )}
                                    {row.previously_paid > 0 && row.remaining_after_payment > 0 && (
                                      <Badge variant="outline" className="text-[7px] bg-amber-500/15 text-amber-400 border-amber-500/30 px-1 py-0 h-3.5">Частично</Badge>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-1">
                                    <p className="text-[8px] text-muted-foreground">{row.position || row.pay_type || "—"}</p>
                                    <button onClick={() => isSelected ? clearAllDaysForEmp(eid) : selectAllDaysForEmp(eid, row.day_cells || [])} className="text-[7px] text-primary hover:underline">{empDays.size > 0 ? "×" : "✓"}</button>
                                  </div>
                                </div>
                              </div>
                            </TableCell>

                            {dates.map(d => {
                              const dc = dayCellMap[d];
                              const dt = new Date(d + "T12:00:00");
                              const isWeekend = dt.getDay() === 0 || dt.getDay() === 6;
                              const isDaySelected = empDays.has(d);

                              if (!dc) {
                                return <TableCell key={d} className={`text-center p-1 ${isWeekend ? "bg-muted/10" : ""}`}><span className="text-[10px] text-muted-foreground/20">—</span></TableCell>;
                              }

                              // P0-2A.2: split-cell visualization (Вариант 5).
                              // Cell can have up to 3 sections shown stacked:
                              //   1. Paid/batched reports (green/violet, locked, with lock icon + PR number)
                              //   2. Selectable approved unpaid reports (blue, selectable)
                              //   3. Rejected reports (red, for reference only) — only if any
                              // For backwards compat: if backend didn't send reports[], fall back to legacy single-cell render.
                              const reports = dc.reports || [];
                              const hasReports = reports.length > 0;

                              if (!hasReports) {
                                // Legacy fallback: single-color cell using payroll_status (P0-2A behavior).
                                const cellPayrollStatus = dc.payroll_status || "none";
                                const cellReportStatus = dc.report_status || "";
                                let cellCfg;
                                if (cellReportStatus === "REJECTED" || cellReportStatus === "rejected") {
                                  cellCfg = PAYROLL_CELL_REJECTED;
                                } else {
                                  cellCfg = PAYROLL_CELL_CFG[cellPayrollStatus] || PAYROLL_CELL_CFG.none;
                                }
                                const isLockedLegacy = (cellPayrollStatus === "paid" || cellPayrollStatus === "batched");
                                return (
                                  <TableCell key={d} className={`text-center p-1 ${isWeekend ? "bg-muted/10" : ""} ${isLockedLegacy ? cellCfg.cls + " cursor-not-allowed opacity-90" : (isDaySelected && isSelected ? "bg-primary/15 border border-primary/30 cursor-pointer" : "hover:bg-muted/20 cursor-pointer")}`}
                                    onClick={() => { if (!isLockedLegacy) { if (!isSelected) setSelectedEmps(prev => new Set([...prev, eid])); toggleDay(eid, d); } }}>
                                    <span className="text-[11px] font-mono font-bold">{getDayHours(eid, dc)}ч</span>
                                  </TableCell>
                                );
                              }

                              // Group reports by section
                              const paidReports = reports.filter(r => r.payroll_status === "paid" || r.payroll_status === "batched");
                              const selectableReports = reports.filter(r => r.selectable);
                              const rejectedReports = reports.filter(r => (r.report_status || "").toUpperCase() === "REJECTED");

                              const totalReports = reports.length;
                              const hasOnlyPaid = paidReports.length === totalReports;
                              const hasOnlySelectable = selectableReports.length === totalReports;
                              const isCellLocked = hasOnlyPaid;
                              const isCellSelectable = selectableReports.length > 0;
                              const paidHours = paidReports.reduce((s, r) => s + r.hours, 0);
                              const paidValue = paidReports.reduce((s, r) => s + r.value, 0);
                              const selectableHours = selectableReports.reduce((s, r) => s + r.hours, 0);
                              const selectableValue = selectableReports.reduce((s, r) => s + r.value, 0);
                              const rejectedHours = rejectedReports.reduce((s, r) => s + r.hours, 0);
                              const rejectedValue = rejectedReports.reduce((s, r) => s + r.value, 0);
                              const firstPaidBatchId = paidReports[0]?.payroll_batch_id || null;
                              const hasMultipleReports = totalReports > 1;

                              // Click behavior:
                              // - Multi-report cell with any selectable: open popup for per-report selection
                              // - Single selectable report: toggle day directly (old behavior, fastest)
                              // - Fully locked (only paid): no action
                              const handleClick = () => {
                                if (isCellLocked) return;
                                if (hasMultipleReports && isCellSelectable && (paidReports.length > 0 || rejectedReports.length > 0)) {
                                  // Mixed cell → open popup
                                  // P0-2A.3: pre-check all selectable reports if user hasn't picked yet.
                                  // This way the popup opens already showing "what would be paid by default",
                                  // and the user can uncheck specific reports to exclude them.
                                  setSelectedReportIds(prev => {
                                    const existing = prev[eid] || new Set();
                                    // If user already has picks for these reports → don't override.
                                    const hasAnyPick = selectableReports.some(r => existing.has(r.report_id));
                                    if (hasAnyPick) return prev;
                                    const next = new Set(existing);
                                    selectableReports.forEach(r => next.add(r.report_id));
                                    return { ...prev, [eid]: next };
                                  });
                                  setReportPopup({ eid, date: d, row, dc });
                                  return;
                                }
                                // Simple cell → toggle day
                                if (!isSelected) {
                                  setSelectedEmps(prev => new Set([...prev, eid]));
                                }
                                toggleDay(eid, d);
                              };

                              return (
                                <TableCell key={d} className={`p-0 ${isWeekend ? "bg-muted/10" : ""} ${dayOverrides[`${eid}_${d}`] ? "ring-1 ring-amber-500/40" : ""}`}
                                  onDoubleClick={(e) => { e.stopPropagation(); if (!isCellLocked) openDayEdit(eid, dc, row); }}
                                  title={hasMultipleReports ? `${totalReports} отчета · клик за детайл` : (reports[0]?.locked_reason || "1 отчет")}>
                                  <div className={`flex flex-col ${isCellLocked ? "cursor-not-allowed" : "cursor-pointer"} ${isDaySelected && isSelected ? "ring-1 ring-primary" : ""}`}
                                    onClick={handleClick}>
                                    {paidReports.length > 0 && (
                                      <div className="px-1 py-0.5 bg-emerald-500/15 border-b border-emerald-500/30 text-center">
                                        <div className="flex items-center justify-center gap-0.5 text-[8px] text-emerald-400 font-medium">
                                          <Lock className="w-2 h-2" />
                                          <span>{paidReports.length === 1 ? "Платено" : `${paidReports.length} платени`}</span>
                                        </div>
                                        <div className="text-[10px] font-mono font-bold text-emerald-300">{paidHours.toFixed(1)}ч · {paidValue.toFixed(0)}</div>
                                        {firstPaidBatchId && <div className="text-[7px] text-emerald-400/70">{firstPaidBatchId}</div>}
                                      </div>
                                    )}
                                    {selectableReports.length > 0 && (() => {
                                      // P0-2A.3: visual indicator if user picked subset via popup.
                                      const empPicks = selectedReportIds[eid] || new Set();
                                      const pickedHere = selectableReports.filter(r => empPicks.has(r.report_id));
                                      const hasPartialPick = pickedHere.length > 0 && pickedHere.length < selectableReports.length;
                                      const pickedHours = pickedHere.reduce((s, r) => s + r.hours, 0);
                                      const pickedValue = pickedHere.reduce((s, r) => s + r.value, 0);
                                      return (
                                        <div className={`px-1 py-0.5 text-center ${isDaySelected && isSelected ? "bg-blue-500/30 border-b border-blue-500/60" : "bg-blue-500/15 border-b border-blue-500/30"}`}>
                                          <div className="text-[8px] text-blue-400 font-medium">
                                            {hasPartialPick
                                              ? `${pickedHere.length}/${selectableReports.length} избрани`
                                              : (selectableReports.length === 1 ? "За плащане" : `${selectableReports.length} избираеми`)}
                                          </div>
                                          <div className="text-[10px] font-mono font-bold text-blue-300">
                                            {hasPartialPick
                                              ? `${pickedHours.toFixed(1)}ч · ${pickedValue.toFixed(0)}`
                                              : `${selectableHours.toFixed(1)}ч · ${selectableValue.toFixed(0)}`}
                                          </div>
                                        </div>
                                      );
                                    })()}
                                    {rejectedReports.length > 0 && (
                                      <div className="px-1 py-0.5 bg-red-500/15 text-center">
                                        <div className="flex items-center justify-center gap-0.5 text-[8px] text-red-400 font-medium">
                                          <XIcon className="w-2 h-2" />
                                          <span>{rejectedReports.length === 1 ? "Отхвърлен" : `${rejectedReports.length} отказани`}</span>
                                        </div>
                                        <div className="text-[10px] font-mono text-red-300/80 line-through">{rejectedHours.toFixed(1)}ч · {rejectedValue.toFixed(0)}</div>
                                      </div>
                                    )}
                                  </div>
                                </TableCell>
                              );
                            })}

                            <TableCell className={`text-center bg-primary/5 ${isSelected && payAmount > 0 ? "" : "opacity-30"}`}>
                              <span className="text-sm font-mono font-bold text-primary">{payAmount > 0 ? payAmount.toFixed(0) : "—"}</span>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>
              )}

              {/* Step 2: Adjustments */}
              {step === "adjustments" && (
              <div className="rounded-xl border border-border bg-card overflow-hidden mb-4" data-testid="adjustments-table">
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader><TableRow>
                      <TableHead className="text-[10px] min-w-[140px]">Служител</TableHead>
                      <TableHead className="text-[10px] text-center">Брутно</TableHead>
                      <TableHead className="text-[10px] text-center min-w-[55px]">Аванс</TableHead>
                      <TableHead className="text-[10px] text-center min-w-[55px]">Заем</TableHead>
                      <TableHead className="text-[10px] text-center min-w-[55px]">Удръжки</TableHead>
                      <TableHead className="text-[10px] text-center min-w-[55px]">Бонус</TableHead>
                      <TableHead className="text-[10px] text-center min-w-[55px]">Други</TableHead>
                      <TableHead className="text-[10px] text-center bg-primary/5 min-w-[70px]">Нетно</TableHead>
                    </TableRow></TableHeader>
                    <TableBody>
                      {preview.rows.filter(r => selectedEmps.has(r.employee_id) && getEmpPayAmount(r) > 0).map(row => {
                        const eid = row.employee_id;
                        const gross = getEmpPayAmount(row);
                        const adjs = getEmpAdj(eid);
                        const net = getEmpNet(row);
                        const byType = (t) => adjs.filter(a => a.type === t).reduce((s, a) => s + a.amount, 0);
                        return (
                          <TableRow key={eid}>
                            <TableCell>
                              <div className="flex items-center gap-2">
                                {row.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${row.avatar_url}`} className="w-7 h-7 rounded-full object-cover" alt="" /> : <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary">{(row.first_name?.[0] || "")}{(row.last_name?.[0] || "")}</div>}
                                <div><p className="text-xs font-medium">{row.first_name} {row.last_name}</p><p className="text-[8px] text-muted-foreground">{row.position || "—"}</p></div>
                              </div>
                            </TableCell>
                            <TableCell className="text-center text-xs font-mono text-primary font-bold">{gross.toFixed(0)}</TableCell>
                            {["advance","loan_repayment","deduction","bonus","manual_correction"].map(t => {
                              const v = byType(t);
                              const isPos = t === "bonus";
                              return <TableCell key={t} className="text-center p-1 cursor-pointer hover:bg-muted/20" onClick={() => { setAdjDialog(row); setAdjType(t); setAdjTitle(""); setAdjAmount(""); setAdjNote(""); }}>
                                {v > 0 ? <span className={`text-xs font-mono ${isPos ? "text-emerald-400" : "text-red-400"}`}>{isPos ? "+" : "-"}{v}</span> : <span className="text-[10px] text-muted-foreground/30">+</span>}
                              </TableCell>;
                            })}
                            <TableCell className={`text-center text-sm font-mono font-bold bg-primary/5 ${net < 0 ? "text-red-400" : "text-primary"}`}>{net.toFixed(0)}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
                <div className="p-2 border-t border-border text-[9px] text-muted-foreground">
                  Нетно = Брутно + Бонуси - Удръжки - Аванс - Заем ± Ръчна корекция
                </div>
              </div>
              )}

              {/* Step 3: Payment */}
              {step === "payment" && (
              <div className="rounded-xl border border-border bg-card overflow-hidden mb-4" data-testid="payment-table">
                <div className="flex items-center justify-between p-3 border-b border-border">
                  <div className="flex items-center gap-4 text-xs">
                    <span>Избрани: <strong className="text-foreground">{payTotals.count}</strong></span>
                    <span>Нетно: <strong className="text-primary font-mono">{payTotals.net.toFixed(0)}</strong></span>
                    <span>Платено: <strong className="text-emerald-400 font-mono">{payTotals.paid.toFixed(0)}</strong></span>
                    <span className={payTotals.carry > 0 ? "text-amber-400" : "text-emerald-400"}>Остатък: <strong className="font-mono">{payTotals.carry.toFixed(0)}</strong></span>
                  </div>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="sm" className="h-7 text-[10px]" onClick={fillAllPaidEqNet}>Платено = Нетно</Button>
                    <Button variant="ghost" size="sm" className="h-7 text-[10px]" onClick={clearAllPaid}>Нулирай</Button>
                  </div>
                </div>
                <Table>
                  <TableHeader><TableRow>
                    <TableHead className="text-[10px] w-[30px]"><input type="checkbox" checked={payTotals.count === (preview?.rows || []).filter(r => selectedEmps.has(r.employee_id) && getEmpPayAmount(r) > 0).length} onChange={e => { const sel = new Set(); if (e.target.checked) (preview?.rows || []).filter(r => selectedEmps.has(r.employee_id) && getEmpPayAmount(r) > 0).forEach(r => sel.add(r.employee_id)); setPaySelected(sel); }} className="rounded" /></TableHead>
                    <TableHead className="text-[10px] min-w-[140px]">Служител</TableHead>
                    <TableHead className="text-[10px] text-center">Нетно</TableHead>
                    <TableHead className="text-[10px] text-center min-w-[100px]">Реално платено</TableHead>
                    <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {(preview?.rows || []).filter(r => selectedEmps.has(r.employee_id) && getEmpPayAmount(r) > 0).map(row => {
                      const eid = row.employee_id;
                      const net = getEmpNet(row);
                      const isPay = paySelected.has(eid);
                      const paid = paidAmounts[eid] ?? net;
                      const remain = Math.round((net - paid) * 100) / 100;
                      return (
                        <TableRow key={eid} className={isPay ? "" : "opacity-40"}>
                          <TableCell><input type="checkbox" checked={isPay} onChange={() => { const s = new Set(paySelected); if (s.has(eid)) s.delete(eid); else s.add(eid); setPaySelected(s); }} className="rounded" /></TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              {row.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${row.avatar_url}`} className="w-8 h-8 rounded-full object-cover" alt="" /> : <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-[10px] font-bold text-primary">{(row.first_name?.[0] || "")}{(row.last_name?.[0] || "")}</div>}
                              <div><p className="text-xs font-medium">{row.first_name} {row.last_name}</p><p className="text-[8px] text-muted-foreground">{row.position || "—"}</p></div>
                            </div>
                          </TableCell>
                          <TableCell className="text-center text-sm font-mono font-bold text-primary">{net.toFixed(0)}</TableCell>
                          <TableCell className="text-center">
                            <Input type="number" value={paid} onChange={e => setPaidAmounts(prev => ({ ...prev, [eid]: parseFloat(e.target.value) || 0 }))} className="h-8 w-24 text-sm font-mono text-center mx-auto font-bold text-emerald-400" disabled={!isPay} />
                          </TableCell>
                          <TableCell className={`text-center text-sm font-mono font-bold bg-primary/5 ${remain > 0 ? "text-amber-400" : remain < 0 ? "text-red-400" : "text-emerald-400"}`}>
                            {remain.toFixed(0)}
                            {remain < 0 && <span className="text-[8px] block text-red-400">надплащане</span>}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              )}

              {/* Actions */}
              <div className="flex items-center justify-between gap-2">
                <div>
                  {step === "adjustments" && <Button variant="ghost" size="sm" onClick={() => setStep("grid")} className="text-xs">← Назад</Button>}
                  {step === "payment" && <Button variant="ghost" size="sm" onClick={() => setStep("adjustments")} className="text-xs">← Корекции</Button>}
                </div>
                <div className="flex gap-2">
                  {step === "grid" && <Button variant="outline" onClick={() => setStep("adjustments")} disabled={totalSelectedPay === 0} className="gap-1.5">Напред →</Button>}
                  {step === "adjustments" && <Button variant="outline" onClick={initPaymentStep} disabled={totalSelectedPay === 0} className="gap-1.5">Напред → Плащане</Button>}
                  <Button variant="outline" onClick={handleSaveDraft} disabled={creating || totalSelectedPay === 0} className="gap-1.5" data-testid="save-draft-btn">
                    {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
                    Чернова
                  </Button>
                  {step === "payment" && (
                    <Button onClick={handleCreate} disabled={creating || payTotals.count === 0} className="gap-1.5 bg-emerald-600 hover:bg-emerald-700" data-testid="create-payrun-btn">
                      {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                      Потвърди плащане ({payTotals.paid.toFixed(0)} €)
                    </Button>
                  )}
                </div>
              </div>
            </>
            );
          })()}
        </>
      )}

      {/* ═══ MONTHLY ═══ */}
      {tab === "monthly" && (() => {
        if (loadingMonth) return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>;
        const items = monthData || [];

        // Deduplicate: keep only the LATEST pay_run row per employee per week
        // (Multiple pay runs may cover the same period — use last created)
        const deduped = {};
        items.forEach(w => {
          const key = `${w.employee_id}_${w.week_number}`;
          const existing = deduped[key];
          if (!existing || (w.pay_run_number || "") > (existing.pay_run_number || "")) {
            deduped[key] = w;
          }
        });
        const uniqueItems = Object.values(deduped);

        // Group by employee → by week_number
        const empMap = {};
        const weekNums = new Set();
        uniqueItems.forEach(w => {
          const eid = w.employee_id;
          const wn = w.week_number || 0;
          weekNums.add(wn);
          if (!empMap[eid]) empMap[eid] = { ...w, weeks: {}, totalPaid: 0, totalEarned: 0, totalBonuses: 0, totalDeductions: 0, totalDays: 0, lastRemaining: 0 };
          empMap[eid].weeks[wn] = w;
          empMap[eid].totalPaid += w.paid_now_amount || 0;
          empMap[eid].totalEarned += w.earned_amount || 0;
          empMap[eid].totalBonuses += w.bonuses_amount || 0;
          empMap[eid].totalDeductions += w.deductions_amount || 0;
          empMap[eid].totalDays += w.approved_days || 0;
        });
        // Remaining = sum of remaining across latest weeks
        for (const emp of Object.values(empMap)) {
          emp.lastRemaining = Object.values(emp.weeks).reduce((s, w) => s + (w.remaining_after_payment || 0), 0);
        }
        const employees = Object.values(empMap).sort((a, b) => (b.totalPaid - a.totalPaid) || a.last_name?.localeCompare(b.last_name || ""));
        const sortedWeeks = [...weekNums].sort((a, b) => a - b);
        const grandPaid = employees.reduce((s, e) => s + e.totalPaid, 0);
        const grandEarned = employees.reduce((s, e) => s + e.totalEarned, 0);
        const grandBonuses = employees.reduce((s, e) => s + e.totalBonuses, 0);
        const grandDeductions = employees.reduce((s, e) => s + e.totalDeductions, 0);
        const grandRemaining = employees.reduce((s, e) => s + e.lastRemaining, 0);

        return (
        <>
          {/* Month picker */}
          <div className="flex items-center gap-3 mb-4">
            <Input type="month" value={monthYear} onChange={e => setMonthYear(e.target.value)} className="h-9 text-xs w-[160px]" />
            <span className="text-xs text-muted-foreground">{employees.length} служители | {sortedWeeks.length} седмици</span>
          </div>

          {/* Summary bar */}
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 mb-4" data-testid="monthly-summary">
            <div className="rounded-lg bg-card border border-border p-2 text-center">
              <p className="text-lg font-bold font-mono">{employees.length}</p>
              <p className="text-[8px] text-muted-foreground">Хора</p>
            </div>
            <div className="rounded-lg bg-card border border-border p-2 text-center">
              <p className="text-lg font-bold font-mono text-primary">{grandEarned.toFixed(0)}<span className="text-xs text-muted-foreground"> €</span></p>
              <p className="text-[8px] text-muted-foreground">Изработено</p>
            </div>
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-2 text-center">
              <p className="text-lg font-bold font-mono text-emerald-400">{grandPaid.toFixed(0)}<span className="text-xs text-emerald-400/60"> €</span></p>
              <p className="text-[8px] text-emerald-400/70">Платено</p>
            </div>
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-2 text-center">
              <p className="text-lg font-bold font-mono text-emerald-400">{grandBonuses.toFixed(0)}<span className="text-xs text-muted-foreground"> €</span></p>
              <p className="text-[8px] text-muted-foreground">Бонуси</p>
            </div>
            <div className={`rounded-lg p-2 text-center ${grandDeductions > 0 ? "bg-red-500/5 border border-red-500/20" : "bg-card border border-border"}`}>
              <p className={`text-lg font-bold font-mono ${grandDeductions > 0 ? "text-red-400" : "text-muted-foreground"}`}>{grandDeductions.toFixed(0)}<span className="text-xs text-muted-foreground"> €</span></p>
              <p className="text-[8px] text-muted-foreground">Удръжки</p>
            </div>
            <div className={`rounded-lg p-2 text-center ${grandRemaining > 0 ? "bg-amber-500/5 border border-amber-500/20" : grandRemaining < 0 ? "bg-red-500/5 border border-red-500/20" : "bg-card border border-border"}`}>
              <p className={`text-lg font-bold font-mono ${grandRemaining > 0 ? "text-amber-400" : grandRemaining < 0 ? "text-red-400" : "text-emerald-400"}`}>{grandRemaining.toFixed(0)}<span className="text-xs text-muted-foreground"> €</span></p>
              <p className="text-[8px] text-muted-foreground">Остатък</p>
            </div>
          </div>

          {employees.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">Няма данни за {monthYear}</div>
          ) : (
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="monthly-table">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow>
                  <TableHead className="text-[10px] min-w-[140px] sticky left-0 bg-card z-10">Служител</TableHead>
                  {sortedWeeks.map(wn => <TableHead key={wn} className="text-[10px] text-center min-w-[70px]">Сед. {wn}</TableHead>)}
                  <TableHead className="text-[10px] text-center bg-muted/20 min-w-[60px]">Общо</TableHead>
                  <TableHead className="text-[10px] text-center bg-muted/20 min-w-[40px]">Дни</TableHead>
                  <TableHead className="text-[10px] text-center min-w-[50px]">Бонус</TableHead>
                  <TableHead className="text-[10px] text-center min-w-[50px]">Удръж.</TableHead>
                  <TableHead className="text-[10px] text-center bg-primary/5 min-w-[60px]">Остатък</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {employees.map(emp => (
                    <TableRow key={emp.employee_id} className="hover:bg-muted/10">
                      <TableCell className="sticky left-0 bg-card z-10">
                        <div className="flex items-center gap-2 cursor-pointer" onClick={() => setMonthDetail(emp)}>
                          <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary">{(emp.first_name?.[0] || "")}{(emp.last_name?.[0] || "")}</div>
                          <div><p className="text-xs font-medium hover:text-primary">{emp.first_name} {emp.last_name}</p><p className="text-[8px] text-muted-foreground">{emp.position || "—"}</p></div>
                        </div>
                      </TableCell>
                      {sortedWeeks.map(wn => {
                        const w = emp.weeks[wn];
                        if (!w) return <TableCell key={wn} className="text-center text-[10px] text-muted-foreground/30">—</TableCell>;
                        const isPaid = w.run_status === "paid";
                        const hasRemain = w.remaining_after_payment > 0;
                        return (
                          <TableCell key={wn} className={`text-center p-1 cursor-pointer transition-colors ${isPaid ? "bg-emerald-500/5" : hasRemain ? "bg-amber-500/5" : ""}`} onClick={() => w.pay_run_id && loadDetail(w.pay_run_id)}>
                            <span className="text-xs font-mono font-bold">{w.paid_now_amount?.toFixed(0)}</span>
                            <div className="mt-0.5">
                              {isPaid ? <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400" /> : hasRemain ? <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" /> : <span className="inline-block w-1.5 h-1.5 rounded-full bg-violet-400" />}
                            </div>
                          </TableCell>
                        );
                      })}
                      <TableCell className="text-center text-xs font-mono font-bold bg-muted/10 text-emerald-400">{emp.totalPaid.toFixed(0)}</TableCell>
                      <TableCell className="text-center text-xs font-mono bg-muted/10">{emp.totalDays}</TableCell>
                      <TableCell className="text-center text-xs font-mono text-emerald-400">{emp.totalBonuses > 0 ? emp.totalBonuses.toFixed(0) : "—"}</TableCell>
                      <TableCell className="text-center text-xs font-mono text-red-400">{emp.totalDeductions > 0 ? emp.totalDeductions.toFixed(0) : "—"}</TableCell>
                      <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${emp.lastRemaining > 0 ? "text-amber-400" : emp.lastRemaining < 0 ? "text-red-400" : "text-emerald-400"}`}>{emp.lastRemaining.toFixed(0)}</TableCell>
                    </TableRow>
                  ))}
                  {/* Totals */}
                  <TableRow className="border-t-2 border-border font-bold bg-muted/10">
                    <TableCell className="sticky left-0 bg-muted/10 z-10 text-xs">ОБЩО</TableCell>
                    {sortedWeeks.map(wn => {
                      const weekTotal = employees.reduce((s, e) => s + (e.weeks[wn]?.paid_now_amount || 0), 0);
                      return <TableCell key={wn} className="text-center text-xs font-mono">{weekTotal > 0 ? weekTotal.toFixed(0) : "—"}</TableCell>;
                    })}
                    <TableCell className="text-center text-xs font-mono text-emerald-400">{grandPaid.toFixed(0)}</TableCell>
                    <TableCell className="text-center text-xs font-mono">{employees.reduce((s, e) => s + e.totalDays, 0)}</TableCell>
                    <TableCell className="text-center text-xs font-mono text-emerald-400">{grandBonuses > 0 ? grandBonuses.toFixed(0) : "—"}</TableCell>
                    <TableCell className="text-center text-xs font-mono text-red-400">{grandDeductions > 0 ? grandDeductions.toFixed(0) : "—"}</TableCell>
                    <TableCell className="text-center text-xs font-mono font-bold text-primary">{grandRemaining.toFixed(0)}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          </div>
          )}

          {/* Definitions */}
          <p className="text-[8px] text-muted-foreground mt-2">
            Общо = сбор реално платено по седмици | Остатък = сбор остатъци от последните потвърдени плащания | Само последният pay run за всяка седмица
          </p>

          {/* Employee month detail modal */}
          {monthDetail && (
            <Dialog open={!!monthDetail} onOpenChange={() => setMonthDetail(null)}>
              <DialogContent className="max-w-lg" data-testid="month-detail-modal">
                <DialogHeader><DialogTitle>{monthDetail.first_name} {monthDetail.last_name} — {monthYear}</DialogTitle></DialogHeader>
                <div className="space-y-3">
                  <div className="grid grid-cols-3 gap-2">
                    <div className="rounded-lg bg-muted/30 p-2 text-center"><p className="text-sm font-bold font-mono text-primary">{monthDetail.totalEarned.toFixed(0)}</p><p className="text-[8px] text-muted-foreground">Изработено</p></div>
                    <div className="rounded-lg bg-emerald-500/10 p-2 text-center"><p className="text-sm font-bold font-mono text-emerald-400">{monthDetail.totalPaid.toFixed(0)}</p><p className="text-[8px] text-emerald-400/70">Платено</p></div>
                    <div className={`rounded-lg p-2 text-center ${monthDetail.lastRemaining > 0 ? "bg-amber-500/10" : monthDetail.lastRemaining < 0 ? "bg-red-500/10" : "bg-muted/30"}`}><p className={`text-sm font-bold font-mono ${monthDetail.lastRemaining > 0 ? "text-amber-400" : monthDetail.lastRemaining < 0 ? "text-red-400" : "text-emerald-400"}`}>{monthDetail.lastRemaining.toFixed(0)}</p><p className="text-[8px] text-muted-foreground">Остатък</p></div>
                  </div>
                  {/* Validation: cards must match table */}
                  {(() => {
                    const tblPaid = Object.values(monthDetail.weeks).reduce((s, w) => s + (w.paid_now_amount || 0), 0);
                    const tblEarned = Object.values(monthDetail.weeks).reduce((s, w) => s + (w.earned_amount || 0), 0);
                    const match = Math.abs(tblPaid - monthDetail.totalPaid) < 0.01 && Math.abs(tblEarned - monthDetail.totalEarned) < 0.01;
                    return match ? <p className="text-[7px] text-emerald-400/60 text-center">✓ Сборовете съвпадат</p> : <p className="text-[7px] text-red-400 text-center">✗ Разминаване: картите ({monthDetail.totalPaid.toFixed(2)}) ≠ таблица ({tblPaid.toFixed(2)})</p>;
                  })()}
                  <Table>
                    <TableHeader><TableRow>
                      <TableHead className="text-[10px]">Седмица</TableHead>
                      <TableHead className="text-[10px]">Период</TableHead>
                      <TableHead className="text-[10px] text-center">Дни</TableHead>
                      <TableHead className="text-[10px] text-center">Платено</TableHead>
                      <TableHead className="text-[10px] text-center">Остатък</TableHead>
                      <TableHead className="text-[10px]">Статус</TableHead>
                      <TableHead className="text-[10px]">Фиш</TableHead>
                    </TableRow></TableHeader>
                    <TableBody>
                      {sortedWeeks.filter(wn => monthDetail.weeks[wn]).map(wn => {
                        const w = monthDetail.weeks[wn];
                        return (
                          <TableRow key={wn} className="hover:bg-muted/10">
                            <TableCell className="text-xs font-mono font-bold">{wn}</TableCell>
                            <TableCell className="text-xs font-mono">{w.period_start}→{w.period_end}</TableCell>
                            <TableCell className="text-center text-xs font-mono">{w.approved_days}</TableCell>
                            <TableCell className="text-center text-xs font-mono text-emerald-400">{w.paid_now_amount?.toFixed(0)}</TableCell>
                            <TableCell className={`text-center text-xs font-mono ${w.remaining_after_payment > 0 ? "text-amber-400" : "text-emerald-400"}`}>{w.remaining_after_payment?.toFixed(0)}</TableCell>
                            <TableCell><Badge variant="outline" className={`text-[8px] ${w.run_status === "paid" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : "bg-violet-500/15 text-violet-400 border-violet-500/30"}`}>{w.run_status === "paid" ? "Платен" : "Потвърден"}</Badge></TableCell>
                            <TableCell>{w.slip_number ? <Badge variant="outline" className="text-[8px] cursor-pointer" onClick={() => { if (w.slip_id) API.get(`/payment-slips/${w.slip_id}`).then(r => setDetailSlip(r.data)).catch(()=>{}); }}>{w.slip_number}</Badge> : "—"}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                  <div className="flex gap-2 justify-end">
                    <Button variant="outline" size="sm" className="text-xs" onClick={() => { setMonthDetail(null); navigate(`/employees/${monthDetail.employee_id}?tab=payroll-weeks`); }}>Досие</Button>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          )}
        </>
        );
      })()}

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
            <Input type="number" value={adjAmount} onChange={e => setAdjAmount(e.target.value)} placeholder="Сума €" className="h-9" />
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
                    <TableHead className="text-[10px] w-[25px]"><input type="checkbox" checked={printSelected.size === (detailRun.employee_rows || []).length} onChange={e => { if (e.target.checked) setPrintSelected(new Set((detailRun.employee_rows || []).map(r => r.employee_id))); else setPrintSelected(new Set()); }} className="rounded" /></TableHead>
                    <TableHead className="text-[10px]">Човек</TableHead>
                    <TableHead className="text-[10px] text-center">Часове</TableHead>
                    <TableHead className="text-[10px] text-center">Изработено</TableHead>
                    <TableHead className="text-[10px] text-center">Корекции</TableHead>
                    <TableHead className="text-[10px] text-center">Платено</TableHead>
                    <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
                    <TableHead className="text-[10px]">Статус</TableHead>
                    <TableHead className="text-[10px] w-[30px]" />
                  </TableRow></TableHeader>
                  <TableBody>
                    {detailRun.employee_rows?.map(r => {
                      const isPaid = r.paid_now_amount > 0 && r.remaining_after_payment <= 0;
                      const isPartial = r.paid_now_amount > 0 && r.remaining_after_payment > 0;
                      return (
                      <TableRow key={r.employee_id}>
                        <TableCell><input type="checkbox" checked={printSelected.has(r.employee_id)} onChange={() => { const s = new Set(printSelected); if (s.has(r.employee_id)) s.delete(r.employee_id); else s.add(r.employee_id); setPrintSelected(s); }} className="rounded" /></TableCell>
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
                        <TableCell>
                          {isPaid ? <Badge variant="outline" className="text-[8px] bg-emerald-500/15 text-emerald-400 border-emerald-500/30">Платен</Badge>
                          : isPartial ? <Badge variant="outline" className="text-[8px] bg-amber-500/15 text-amber-400 border-amber-500/30">Частичен</Badge>
                          : r.paid_now_amount === 0 ? <Badge variant="outline" className="text-[8px] bg-gray-500/15 text-gray-400 border-gray-500/30">Неплатен</Badge>
                          : null}
                        </TableCell>
                        <TableCell>
                          <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => openIndividualPrint(detailRun, r, (allocData?.employees || []).find(e => e.employee_id === r.employee_id))}>
                            <Printer className="w-3 h-3" />
                          </Button>
                        </TableCell>
                      </TableRow>);
                    })}
                  </TableBody>
                </Table>
              </div>
              {/* Actions */}
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex gap-2 flex-wrap">
                  {(detailRun.status === "confirmed" || detailRun.status === "draft") && (
                    <Button variant="outline" size="sm" onClick={() => handleReopen(detailRun.id)} className="gap-1 text-xs" data-testid="reopen-all-btn">Отвори за редакция</Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => loadHistory(detailRun.id)} className="gap-1 text-xs" data-testid="view-history-btn"><Clock className="w-3 h-3" /> История</Button>
                  <Button variant="outline" size="sm" onClick={() => openGroupPrint(detailRun, detailRun.employee_rows, allocData)} className="gap-1 text-xs" data-testid="print-all-btn"><Printer className="w-3 h-3" /> Групов лист</Button>
                  {printSelected.size > 0 && (
                    <Button variant="outline" size="sm" onClick={() => openSelectedPrint(detailRun, detailRun.employee_rows.filter(r => printSelected.has(r.employee_id)), allocData)} className="gap-1 text-xs"><Printer className="w-3 h-3" /> Печат избрани ({printSelected.size})</Button>
                  )}
                </div>
                <div className="flex gap-2">
                  {detailRun.status === "confirmed" && (
                    <Button onClick={() => setPayDialog(detailRun.id)} className="gap-1.5 bg-emerald-600 hover:bg-emerald-700" data-testid="mark-paid-btn"><Check className="w-4 h-4" /> Маркирай платен</Button>
                  )}
                </div>
              </div>

              {/* Payment info */}
              {detailRun.payment_method && (
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span>Метод: <strong className="text-foreground">{detailRun.payment_method === "cash" ? "В брой" : detailRun.payment_method === "bank_transfer" ? "Банков превод" : detailRun.payment_method === "card" ? "Карта" : detailRun.payment_method}</strong></span>
                  {detailRun.payment_reference && <span>Реф: <strong className="text-foreground">{detailRun.payment_reference}</strong></span>}
                  {detailRun.payment_note && <span>Бележка: {detailRun.payment_note}</span>}
                </div>
              )}

              {/* Version badge */}
              {detailRun.version > 1 && (
                <p className="text-[9px] text-muted-foreground">Версия {detailRun.version}</p>
              )}

              {/* Allocation breakdown */}
              {allocData && allocData.employees?.length > 0 && (
                <div className="space-y-3 border-t border-border pt-3">
                  <p className="text-[10px] text-muted-foreground font-semibold uppercase">Разнасяне по обекти</p>
                  {/* Site summary */}
                  {allocData.site_summary?.length > 0 && (
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2" data-testid="alloc-site-summary">
                      {allocData.site_summary.map((s, i) => (
                        <div key={i} className="rounded-lg border border-border p-2">
                          <p className="text-xs font-medium truncate">{s.site_name}</p>
                          <div className="flex items-center gap-2 text-[10px] mt-1">
                            <span className="text-muted-foreground">{s.hours}ч</span>
                            <span className="text-emerald-400 font-mono">{s.paid} €</span>
                            {s.remaining > 0 && <span className="text-amber-400 font-mono">+{s.remaining}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Per-employee allocation */}
                  {allocData.employees.map(emp => {
                    const v = emp.validation || {};
                    return (
                    <div key={emp.employee_id} className="rounded-lg border border-border/50 p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div>
                          <span className="text-xs font-medium">{emp.first_name} {emp.last_name}</span>
                          <span className="text-[8px] text-muted-foreground ml-2">метод: {emp.allocation_method_day === "proportional_value" ? "пропорционално" : "равно (fallback)"}</span>
                        </div>
                        <div className="flex gap-2 text-[10px]">
                          <span className="text-emerald-400 font-mono">Платено: {emp.paid_now_amount}</span>
                          {emp.remaining_carry_forward !== 0 && <span className={`font-mono ${emp.remaining_carry_forward > 0 ? "text-amber-400" : "text-red-400"}`}>Остатък: {emp.remaining_carry_forward}</span>}
                          {v.match === true && <span className="text-[7px] text-emerald-400">✓ OK</span>}
                          {v.match === false && <span className="text-[7px] text-red-400">✗ Разминаване</span>}
                        </div>
                      </div>
                      <div className="space-y-1">
                        {emp.day_allocations?.map((da, di) => (
                          <div key={di} className="rounded bg-muted/10 px-2 py-1">
                            <div className="flex items-center justify-between text-[9px]">
                              <span className="font-mono text-muted-foreground w-[75px]">{da.date}</span>
                              <span className="w-[70px]">{da.hours}ч / {da.source_value}</span>
                              <span className="text-emerald-400 font-mono w-[55px] text-right">→ {da.allocated_paid}</span>
                              <span className={`font-mono w-[55px] text-right ${da.allocated_remaining > 0 ? "text-amber-400" : da.allocated_remaining < 0 ? "text-red-400" : "text-muted-foreground"}`}>{da.allocated_remaining !== 0 ? da.allocated_remaining : "0"}</span>
                              <span className="text-[7px] text-muted-foreground/60 w-[60px] text-right">{da.allocation_method === "proportional_value" ? "пропорц." : "равно"}</span>
                            </div>
                            {da.sites?.length > 1 && (
                              <div className="ml-[75px] mt-0.5 space-y-0.5">
                                {da.sites.map((sa, si) => (
                                  <div key={si} className="flex items-center gap-2 text-[8px] text-muted-foreground">
                                    <span className="text-primary">{sa.site_name}</span>
                                    <span>{sa.hours}ч</span>
                                    <span className="text-emerald-400 font-mono">{sa.paid}</span>
                                    {sa.remaining !== 0 && <span className="text-amber-400 font-mono">{sa.remaining > 0 ? "+" : ""}{sa.remaining}</span>}
                                    <span className="text-[6px]">{sa.method?.includes("remainder") ? "(закр.)" : ""}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {da.sites?.length === 1 && (
                              <div className="text-[8px] text-muted-foreground ml-[75px]">{da.sites[0]?.site_name}</div>
                            )}
                          </div>
                        ))}
                      </div>
                      {emp.rounding_adjustment !== 0 && (
                        <p className="text-[7px] text-muted-foreground mt-1">Закръгляне: {emp.rounding_adjustment} € (последен ред поема остатъка)</p>
                      )}
                    </div>
                    );
                  })}
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
                <SumCard label="Ставка" value={`${detailSlip.frozen_hourly_rate} €/ч`} />
              </div>
              {detailSlip.adjustments?.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] text-muted-foreground font-semibold uppercase">Корекции</p>
                  {detailSlip.adjustments.map((a, i) => (
                    <div key={i} className="flex justify-between text-xs px-2">
                      <span className={a.type === "bonus" ? "text-emerald-400" : "text-red-400"}>{a.title || a.type} {a.note && `(${a.note})`}</span>
                      <span className="font-mono">{a.type === "bonus" ? "+" : "-"}{a.amount} €</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-1 text-xs">
                <div className="flex justify-between"><span>Изработено</span><span className="font-mono">{detailSlip.earned_amount?.toFixed(2)} €</span></div>
                {detailSlip.bonuses_amount > 0 && <div className="flex justify-between text-emerald-400"><span>+ Бонуси</span><span className="font-mono">+{detailSlip.bonuses_amount?.toFixed(2)} €</span></div>}
                {detailSlip.deductions_amount > 0 && <div className="flex justify-between text-red-400"><span>- Удръжки</span><span className="font-mono">-{detailSlip.deductions_amount?.toFixed(2)} €</span></div>}
                {detailSlip.previously_paid > 0 && <div className="flex justify-between text-muted-foreground"><span>- Вече платено</span><span className="font-mono">-{detailSlip.previously_paid?.toFixed(2)} €</span></div>}
                <div className="flex justify-between font-bold text-sm pt-1 border-t border-border"><span>Платено сега</span><span className="font-mono text-primary">{detailSlip.paid_now_amount?.toFixed(2)} €</span></div>
                <div className="flex justify-between"><span>Остатък</span><span className={`font-mono font-bold ${detailSlip.remaining_after_payment > 0 ? "text-amber-400" : "text-emerald-400"}`}>{detailSlip.remaining_after_payment?.toFixed(2)} €</span></div>
              </div>
              {detailSlip.paid_at && <p className="text-xs text-emerald-400 flex items-center gap-1"><Check className="w-3 h-3" /> Платено на {detailSlip.paid_at?.slice(0, 10)}</p>}
              {detailSlip.remaining_after_payment < 0 && <p className="text-xs text-red-400 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> Внимание: Надплащане ({detailSlip.remaining_after_payment?.toFixed(2)} €)</p>}
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

      {/* Payment Dialog */}
      <Dialog open={!!payDialog} onOpenChange={() => setPayDialog(null)}>
        <DialogContent className="max-w-sm" data-testid="pay-dialog">
          <DialogHeader><DialogTitle>Потвърди плащане</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-[10px] text-muted-foreground">Метод на плащане</label>
              <Select value={payMethod} onValueChange={setPayMethod}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="cash">В брой</SelectItem>
                  <SelectItem value="bank_transfer">Банков превод</SelectItem>
                  <SelectItem value="card">Карта</SelectItem>
                  <SelectItem value="other">Друго</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">Референция (опц.)</label>
              <Input value={payRef} onChange={e => setPayRef(e.target.value)} placeholder="Номер на превод..." className="h-9" />
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">Бележка (опц.)</label>
              <Input value={payNote} onChange={e => setPayNote(e.target.value)} placeholder="Бележка..." className="h-9" />
            </div>
            <Button onClick={() => handleMarkPaid(payDialog)} className="w-full gap-1.5 bg-emerald-600 hover:bg-emerald-700">
              <Check className="w-4 h-4" /> Потвърди плащане
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Day Edit Dialog */}
      <Dialog open={!!dayEditDialog} onOpenChange={() => setDayEditDialog(null)}>
        <DialogContent className="max-w-sm" data-testid="day-edit-dialog">
          <DialogHeader><DialogTitle>Редакция на ден</DialogTitle></DialogHeader>
          {dayEditDialog && (
            <div className="space-y-3">
              <div className="text-xs text-muted-foreground">
                <strong>{dayEditDialog.row?.first_name} {dayEditDialog.row?.last_name}</strong> — {dayEditDialog.date}
                {dayEditDialog.cell?.sites?.length > 0 && <span className="text-primary"> | {dayEditDialog.cell.sites.join(", ")}</span>}
              </div>
              <div className="rounded-lg bg-muted/20 p-2 text-[10px] text-muted-foreground">
                Оригинал: {dayEditDialog.cell?.hours}ч / {dayEditDialog.cell?.value?.toFixed(2)} €
              </div>
              <div><label className="text-[10px] text-muted-foreground">Часове</label><Input type="number" value={dayEditHours} onChange={e => setDayEditHours(e.target.value)} className="h-9" /></div>
              <div><label className="text-[10px] text-muted-foreground">Сума €</label><Input type="number" value={dayEditValue} onChange={e => setDayEditValue(e.target.value)} className="h-9" /></div>
              <div><label className="text-[10px] text-muted-foreground">Причина</label><Input value={dayEditReason} onChange={e => setDayEditReason(e.target.value)} placeholder="Причина за промяната..." className="h-9" /></div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setDayEditDialog(null)} className="flex-1">Откажи</Button>
                <Button onClick={saveDayEdit} className="flex-1">Запази</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* P0-2A.2: Per-report selection popup (Вариант 4 — стек на отчети) */}
      <Dialog open={!!reportPopup} onOpenChange={() => setReportPopup(null)}>
        <DialogContent className="max-w-lg" data-testid="report-popup">
          <DialogHeader>
            <DialogTitle>
              {reportPopup?.row?.first_name} {reportPopup?.row?.last_name} — {reportPopup?.date}
            </DialogTitle>
          </DialogHeader>
          {reportPopup && (() => {
            const dc = reportPopup.dc;
            const eid = reportPopup.eid;
            const reports = dc.reports || [];
            const empSelectedIds = selectedReportIds[eid] || new Set();
            const paidR = reports.filter(r => r.payroll_status === "paid" || r.payroll_status === "batched");
            const selectableR = reports.filter(r => r.selectable);
            const rejectedR = reports.filter(r => (r.report_status || "").toUpperCase() === "REJECTED");
            const selectedHere = selectableR.filter(r => empSelectedIds.has(r.report_id));
            const totalSelectedValue = selectedHere.reduce((s, r) => s + r.value, 0);
            const totalSelectedHours = selectedHere.reduce((s, r) => s + r.hours, 0);

            return (
              <div className="space-y-3">
                <div className="text-[11px] text-muted-foreground">{reports.length} отчет(а) в този ден</div>

                {/* Paid/batched reports — locked */}
                {paidR.map(r => (
                  <div key={r.report_id} className="flex items-center gap-3 p-2.5 rounded-md bg-emerald-500/15 border border-emerald-500/30">
                    <Lock className="w-4 h-4 text-emerald-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] text-emerald-300 font-medium truncate">{r.project_name || "—"} · {r.hours}ч</div>
                      <div className="text-[10px] text-emerald-400/80">{r.locked_reason}</div>
                    </div>
                    <div className="text-[13px] font-mono font-bold text-emerald-300">{r.value.toFixed(0)}€</div>
                  </div>
                ))}

                {/* Selectable approved unpaid reports — with checkbox */}
                {selectableR.map(r => {
                  const isChecked = empSelectedIds.has(r.report_id);
                  return (
                    <div key={r.report_id} className={`flex items-center gap-3 p-2.5 rounded-md border cursor-pointer ${isChecked ? "bg-blue-500/25 border-blue-500/60" : "bg-blue-500/10 border-blue-500/30"}`}
                      onClick={() => {
                        toggleReportSelection(eid, r.report_id);
                        if (!selectedEmps.has(eid)) setSelectedEmps(prev => new Set([...prev, eid]));
                      }}>
                      <input type="checkbox" checked={isChecked} onChange={() => {}} className="w-4 h-4 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] text-blue-300 font-medium truncate">{r.project_name || "—"} · {r.hours}ч</div>
                        <div className="text-[10px] text-blue-400/80">Одобрен · готов за плащане</div>
                      </div>
                      <div className="text-[13px] font-mono font-bold text-blue-300">{r.value.toFixed(0)}€</div>
                    </div>
                  );
                })}

                {/* Rejected reports — for reference only */}
                {rejectedR.map(r => (
                  <div key={r.report_id} className="flex items-center gap-3 p-2.5 rounded-md bg-red-500/15 border border-red-500/30 opacity-75">
                    <XIcon className="w-4 h-4 text-red-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] text-red-300 font-medium truncate line-through">{r.project_name || "—"} · {r.hours}ч</div>
                      <div className="text-[10px] text-red-400/80">Отхвърлен · само за справка</div>
                    </div>
                    <div className="text-[13px] font-mono text-red-300/80 line-through">{r.value.toFixed(0)}€</div>
                  </div>
                ))}

                {/* Footer */}
                <div className="flex items-center justify-between pt-3 border-t border-border mt-3">
                  <div>
                    <div className="text-[10px] text-muted-foreground">Избрано за плащане</div>
                    <div className="text-[15px] font-mono font-bold text-blue-300">{totalSelectedValue.toFixed(2)}€ · {totalSelectedHours.toFixed(1)}ч</div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => {
                      // P0-2A.3: cancel = also clear any per-report picks for this employee in this day.
                      // So if user opened popup then cancelled, nothing changes in main state.
                      setReportPopup(null);
                    }}>Откажи</Button>
                    <Button size="sm" onClick={() => {
                      // P0-2A.3: commit popup selection to main state.
                      // - If any selectable report is picked → add this day to selectedDays + ensure employee in selectedEmps.
                      // - If user unchecked everything → remove this day from selectedDays (sum becomes 0 for it).
                      const hasPicks = selectedHere.length > 0;
                      setSelectedEmps(prev => {
                        if (!hasPicks) return prev;
                        const n = new Set(prev);
                        n.add(eid);
                        return n;
                      });
                      setSelectedDays(prev => {
                        const empDays = new Set(prev[eid] || []);
                        if (hasPicks) {
                          empDays.add(reportPopup.date);
                        } else {
                          empDays.delete(reportPopup.date);
                        }
                        return { ...prev, [eid]: empDays };
                      });
                      setReportPopup(null);
                    }}>Потвърди</Button>
                  </div>
                </div>
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>

      {/* Adjustment Dialog */}
      <Dialog open={!!adjDialog} onOpenChange={() => setAdjDialog(null)}>
        <DialogContent className="max-w-sm" data-testid="adj-dialog">
          <DialogHeader><DialogTitle>{ADJ_TYPES.find(t => t.value === adjType)?.label || adjType}: {adjDialog?.first_name} {adjDialog?.last_name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {/* Show existing adjustments for this type */}
            {adjDialog && (getEmpAdj(adjDialog.employee_id) || []).filter(a => a.type === adjType).length > 0 && (
              <div className="rounded-lg bg-muted/20 p-2 space-y-1">
                <p className="text-[9px] text-muted-foreground uppercase">Съществуващи:</p>
                {getEmpAdj(adjDialog.employee_id).filter(a => a.type === adjType).map((a, i) => (
                  <div key={i} className="flex justify-between text-xs">
                    <span>{a.title} {a.note && `(${a.note})`}</span>
                    <div className="flex items-center gap-1">
                      <span className="font-mono">{a.amount} €</span>
                      <button onClick={() => { const idx = getEmpAdj(adjDialog.employee_id).indexOf(a); removeAdj(adjDialog.employee_id, idx); }} className="text-red-400 text-[9px]">×</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <Select value={adjType} onValueChange={setAdjType}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>{ADJ_TYPES.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
            </Select>
            <Input value={adjTitle} onChange={e => setAdjTitle(e.target.value)} placeholder="Заглавие" className="h-9" />
            <Input type="number" value={adjAmount} onChange={e => setAdjAmount(e.target.value)} placeholder="Сума €" className="h-9" />
            <Input value={adjNote} onChange={e => setAdjNote(e.target.value)} placeholder="Бележка..." className="h-9" />
            <Button onClick={() => adjDialog && addAdj(adjDialog.employee_id)} disabled={!adjAmount} className="w-full">Добави</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* History Dialog */}
      <Dialog open={!!historyData} onOpenChange={() => setHistoryData(null)}>
        <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto" data-testid="history-dialog">
          <DialogHeader><DialogTitle>История: {historyData?.number}</DialogTitle></DialogHeader>
          {historyData && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Текуща версия: <strong className="text-foreground">{historyData.version}</strong></span>
                <Badge variant="outline" className={(STATUS_CFG[historyData.status] || {}).cls}>{(STATUS_CFG[historyData.status] || {}).label}</Badge>
              </div>
              {(historyData.history || []).slice().reverse().map((h, i) => (
                <div key={i} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between mb-1">
                    <Badge variant="outline" className="text-[9px]">v{h.version}</Badge>
                    <span className="text-[10px] text-muted-foreground">{h.changed_at?.slice(0, 19)}</span>
                  </div>
                  <p className="text-xs font-medium">{h.action === "created" ? "Създаден (чернова)" : h.action === "created_confirmed" ? "Създаден и потвърден" : h.action === "updated" ? "Обновен" : h.action === "reopened_all" ? "Отворен за редакция" : h.action === "reopened_rows" ? "Отворени редове" : h.action}</p>
                  {h.reason && <p className="text-[10px] text-muted-foreground">Причина: {h.reason}</p>}
                  {h.totals_snapshot && (
                    <div className="flex gap-3 mt-1 text-[10px] text-muted-foreground">
                      <span>Earned: {h.totals_snapshot.earned}</span>
                      <span>Paid: {h.totals_snapshot.paid}</span>
                      <span>Remain: {h.totals_snapshot.remaining}</span>
                    </div>
                  )}
                  {h.reopened_employees && <p className="text-[9px] text-amber-400 mt-1">Отворени: {h.reopened_employees.join(", ")}</p>}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Audit Check Modal */}
      <Dialog open={auditOpen} onOpenChange={setAuditOpen}>
        <DialogContent className="max-w-lg max-h-[70vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5" />Payroll одит проверка
            </DialogTitle>
          </DialogHeader>
          {auditLoading ? (
            <div className="flex items-center justify-center py-8"><Loader2 className="w-6 h-6 animate-spin" /></div>
          ) : auditData ? (
            <div className="space-y-3">
              {auditData.status === "pass" ? (
                <div className="flex items-center gap-3 p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                  <Check className="w-6 h-6 text-emerald-400" />
                  <div>
                    <p className="font-semibold text-emerald-400">Всичко е наред</p>
                    <p className="text-xs text-muted-foreground">Няма открити проблеми</p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex gap-3">
                    {auditData.critical > 0 && <Badge className="bg-red-500/20 text-red-400 border-red-500/30">{auditData.critical} критични</Badge>}
                    {auditData.warnings > 0 && <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30">{auditData.warnings} предупреждения</Badge>}
                  </div>
                  <div className="space-y-2">
                    {auditData.issues.map((issue, i) => (
                      <div key={i} className={`flex items-start gap-2 p-2.5 rounded-lg text-xs ${issue.severity === "critical" ? "bg-red-500/10 border border-red-500/20" : "bg-amber-500/10 border border-amber-500/20"}`}>
                        <AlertTriangle className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${issue.severity === "critical" ? "text-red-400" : "text-amber-400"}`} />
                        <div>
                          <Badge variant="outline" className={`text-[8px] mb-1 ${issue.severity === "critical" ? "text-red-400 border-red-500/30" : "text-amber-400 border-amber-500/30"}`}>{issue.type}</Badge>
                          <p>{issue.message}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          ) : null}
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
