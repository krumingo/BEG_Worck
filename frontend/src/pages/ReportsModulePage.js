import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
  Loader2, Calendar, List, ChevronLeft, ChevronRight,
} from "lucide-react";
import DailyReportDialog from "@/components/DailyReportDialog";

const DS_LABELS = { WORKING: "На работа", LEAVE: "Отпуск", ABSENT_UNEXCUSED: "Самоотлъчка", SICK: "Болен" };
const DS_COLORS = { WORKING: "bg-emerald-500/15 text-emerald-400", LEAVE: "bg-blue-500/15 text-blue-400", ABSENT_UNEXCUSED: "bg-red-500/15 text-red-400", SICK: "bg-orange-500/15 text-orange-400" };
const AS_LABELS = { DRAFT: "Чернова", SUBMITTED: "Изпратен", APPROVED: "Одобрен", REJECTED: "Отхвърлен" };
const AS_COLORS = { DRAFT: "bg-gray-500/15 text-gray-400", SUBMITTED: "bg-blue-500/15 text-blue-400", APPROVED: "bg-emerald-500/15 text-emerald-400", REJECTED: "bg-red-500/15 text-red-400" };
const PT_LABELS = { Monthly: "Месечно", Akord: "Акорд", Hourly: "Почасово", Daily: "Дневно" };
const DAYS_BG = ["Нд", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

export default function ReportsModulePage() {
  const { user } = useAuth();
  const [tab, setTab] = useState("table");
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState([]);
  const [employees, setEmployees] = useState([]);

  // Table state
  const [rows, setRows] = useState([]);
  const [filters, setFilters] = useState({
    date_from: new Date(Date.now() - 30 * 86400000).toISOString().split("T")[0],
    date_to: new Date().toISOString().split("T")[0],
    project_id: "", employee_id: "", approval_status: "", day_status: "",
  });

  // Calendar state
  const [calMonth, setCalMonth] = useState(new Date().toISOString().slice(0, 7));
  const [calDays, setCalDays] = useState([]);
  const [calFilters, setCalFilters] = useState({ project_id: "", employee_id: "" });

  // Report detail dialog
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailId, setDetailId] = useState(null);

  const fetchTable = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (filters.date_from) params.date_from = filters.date_from;
      if (filters.date_to) params.date_to = filters.date_to;
      if (filters.project_id) params.project_id = filters.project_id;
      if (filters.employee_id) params.employee_id = filters.employee_id;
      if (filters.approval_status) params.approval_status = filters.approval_status;
      if (filters.day_status) params.day_status = filters.day_status;
      const res = await API.get("/daily-reports/reports-table", { params });
      setRows(res.data.rows || []);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [filters]);

  const fetchCalendar = useCallback(async () => {
    try {
      const params = { month: calMonth };
      if (calFilters.project_id) params.project_id = calFilters.project_id;
      if (calFilters.employee_id) params.employee_id = calFilters.employee_id;
      const res = await API.get("/daily-reports/reports-calendar", { params });
      setCalDays(res.data.days || []);
    } catch { /* */ }
  }, [calMonth, calFilters]);

  useEffect(() => {
    Promise.all([
      API.get("/projects").then(r => setProjects(r.data)),
      API.get("/employees").then(r => setEmployees(r.data)),
    ]).catch(() => {});
  }, []);

  useEffect(() => { if (tab === "table") fetchTable(); }, [tab, fetchTable]);
  useEffect(() => { if (tab === "calendar") fetchCalendar(); }, [tab, fetchCalendar]);

  const updateFilter = (k, v) => setFilters(prev => ({ ...prev, [k]: v }));
  const prevMonth = () => { const [y, m] = calMonth.split("-").map(Number); setCalMonth(m === 1 ? `${y-1}-12` : `${y}-${String(m-1).padStart(2, "0")}`); };
  const nextMonth = () => { const [y, m] = calMonth.split("-").map(Number); setCalMonth(m === 12 ? `${y+1}-01` : `${y}-${String(m+1).padStart(2, "0")}`); };

  // Calendar grid
  const calGrid = (() => {
    const [y, m] = calMonth.split("-").map(Number);
    const firstDay = new Date(y, m - 1, 1).getDay();
    const daysInMonth = new Date(y, m, 0).getDate();
    const dayMap = {};
    calDays.forEach(d => { dayMap[d.date] = d; });
    const grid = [];
    let week = new Array(firstDay).fill(null);
    for (let d = 1; d <= daysInMonth; d++) {
      const ds = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      week.push({ day: d, date: ds, data: dayMap[ds] || null });
      if (week.length === 7) { grid.push(week); week = []; }
    }
    if (week.length > 0) { while (week.length < 7) week.push(null); grid.push(week); }
    return grid;
  })();

  const totalCost = rows.reduce((s, r) => s + (r.cost_estimate || 0), 0);
  const totalHours = rows.reduce((s, r) => s + (r.total_hours || 0), 0);

  return (
    <div className="p-6 max-w-[1400px]" data-testid="reports-module-page">
      <h1 className="text-2xl font-bold text-foreground mb-6">Отчети</h1>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="table"><List className="w-4 h-4 mr-1" /> Таблица</TabsTrigger>
          <TabsTrigger value="calendar"><Calendar className="w-4 h-4 mr-1" /> Календар</TabsTrigger>
        </TabsList>

        {/* ═══ TABLE ═══ */}
        <TabsContent value="table">
          {/* Filters */}
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            <Input type="date" value={filters.date_from} onChange={e => updateFilter("date_from", e.target.value)} className="w-36 bg-card h-8 text-xs" />
            <span className="text-xs text-muted-foreground">—</span>
            <Input type="date" value={filters.date_to} onChange={e => updateFilter("date_to", e.target.value)} className="w-36 bg-card h-8 text-xs" />
            <Select value={filters.project_id || "all"} onValueChange={v => updateFilter("project_id", v === "all" ? "" : v)}>
              <SelectTrigger className="w-40 bg-card h-8 text-xs"><SelectValue placeholder="Проект" /></SelectTrigger>
              <SelectContent><SelectItem value="all">Всички проекти</SelectItem>{projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={filters.employee_id || "all"} onValueChange={v => updateFilter("employee_id", v === "all" ? "" : v)}>
              <SelectTrigger className="w-40 bg-card h-8 text-xs"><SelectValue placeholder="Служител" /></SelectTrigger>
              <SelectContent><SelectItem value="all">Всички</SelectItem>{employees.map(e => <SelectItem key={e.id} value={e.id}>{e.first_name} {e.last_name}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={filters.approval_status || "all"} onValueChange={v => updateFilter("approval_status", v === "all" ? "" : v)}>
              <SelectTrigger className="w-32 bg-card h-8 text-xs"><SelectValue placeholder="Статус" /></SelectTrigger>
              <SelectContent><SelectItem value="all">Всички</SelectItem>{Object.entries(AS_LABELS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={filters.day_status || "all"} onValueChange={v => updateFilter("day_status", v === "all" ? "" : v)}>
              <SelectTrigger className="w-32 bg-card h-8 text-xs"><SelectValue placeholder="Ден" /></SelectTrigger>
              <SelectContent><SelectItem value="all">Всички</SelectItem>{Object.entries(DS_LABELS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent>
            </Select>
          </div>

          {/* Summary */}
          <div className="flex items-center gap-6 mb-3 text-sm text-muted-foreground">
            <span>Отчети: <span className="text-foreground font-bold">{rows.length}</span></span>
            <span>Часове: <span className="font-mono text-foreground">{totalHours.toFixed(1)}</span></span>
            <span>Сума: <span className="font-mono text-primary font-bold">{totalCost.toFixed(2)} EUR</span></span>
          </div>

          {/* Table */}
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="reports-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-[10px] uppercase text-muted-foreground">Статус</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Дата</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Служител</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Проект</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Тип</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Часове</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Сума EUR</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow><TableCell colSpan={7} className="text-center py-8"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></TableCell></TableRow>
                ) : rows.length === 0 ? (
                  <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">Няма отчети</TableCell></TableRow>
                ) : rows.map((r, i) => (
                  <TableRow key={i} className="cursor-pointer hover:bg-muted/30" onClick={() => { setDetailId(r.id); setDetailOpen(true); }} data-testid={`report-row-${i}`}>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Badge variant="outline" className={`text-[9px] ${AS_COLORS[r.approval_status]}`}>{AS_LABELS[r.approval_status]}</Badge>
                        <Badge variant="outline" className={`text-[9px] ${DS_COLORS[r.day_status]}`}>{DS_LABELS[r.day_status]}</Badge>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-sm">{r.report_date}</TableCell>
                    <TableCell className="text-sm">{r.employee_name}</TableCell>
                    <TableCell className="font-mono text-sm text-primary">{r.project_codes?.join(", ") || "—"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{PT_LABELS[r.pay_type] || r.pay_type}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{r.total_hours}</TableCell>
                    <TableCell className={`text-right font-mono text-sm ${r.cost_estimate ? "text-foreground" : "text-muted-foreground"}`}>
                      {r.cost_estimate != null ? r.cost_estimate.toFixed(2) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <p className="text-[10px] text-muted-foreground mt-2">Сума = часове × часова ставка (от профила на служителя). Месечна заплата / работни дни / часове на ден = часова ставка.</p>
        </TabsContent>

        {/* ═══ CALENDAR ═══ */}
        <TabsContent value="calendar">
          <div className="flex items-center gap-3 mb-4">
            <Button variant="ghost" size="sm" onClick={prevMonth}><ChevronLeft className="w-4 h-4" /></Button>
            <span className="text-sm font-semibold w-20 text-center">{calMonth}</span>
            <Button variant="ghost" size="sm" onClick={nextMonth}><ChevronRight className="w-4 h-4" /></Button>
            <Select value={calFilters.project_id || "all"} onValueChange={v => setCalFilters(prev => ({ ...prev, project_id: v === "all" ? "" : v }))}>
              <SelectTrigger className="w-40 bg-card h-8 text-xs"><SelectValue placeholder="Проект" /></SelectTrigger>
              <SelectContent><SelectItem value="all">Всички</SelectItem>{projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={calFilters.employee_id || "all"} onValueChange={v => setCalFilters(prev => ({ ...prev, employee_id: v === "all" ? "" : v }))}>
              <SelectTrigger className="w-40 bg-card h-8 text-xs"><SelectValue placeholder="Служител" /></SelectTrigger>
              <SelectContent><SelectItem value="all">Всички</SelectItem>{employees.map(e => <SelectItem key={e.id} value={e.id}>{e.first_name} {e.last_name}</SelectItem>)}</SelectContent>
            </Select>
          </div>

          <div className="rounded-xl border border-border bg-card p-4" data-testid="reports-calendar">
            <div className="grid grid-cols-7 gap-1">
              {DAYS_BG.map(d => <div key={d} className="text-center text-[10px] text-muted-foreground font-medium py-1">{d}</div>)}
              {calGrid.flat().map((cell, i) => {
                if (!cell) return <div key={i} className="h-20" />;
                const dd = cell.data;
                const hasData = dd && (dd.working + dd.leave + dd.absent + dd.sick) > 0;
                return (
                  <div key={i} className={`h-20 rounded-md border text-xs p-1 overflow-hidden ${hasData ? "border-border bg-muted/20" : "border-transparent"}`} data-testid={`cal-cell-${cell.date}`}>
                    <span className="text-[10px] font-mono text-muted-foreground">{cell.day}</span>
                    {dd && (
                      <div className="mt-0.5 space-y-0.5">
                        {dd.working > 0 && <div className="flex items-center gap-0.5"><div className="w-1.5 h-1.5 rounded-full bg-emerald-500" /><span className="text-[9px] text-emerald-400">{dd.working}</span></div>}
                        {dd.leave > 0 && <div className="flex items-center gap-0.5"><div className="w-1.5 h-1.5 rounded-full bg-blue-500" /><span className="text-[9px] text-blue-400">{dd.leave}</span></div>}
                        {dd.sick > 0 && <div className="flex items-center gap-0.5"><div className="w-1.5 h-1.5 rounded-full bg-orange-500" /><span className="text-[9px] text-orange-400">{dd.sick}</span></div>}
                        {dd.absent > 0 && <div className="flex items-center gap-0.5"><div className="w-1.5 h-1.5 rounded-full bg-red-500" /><span className="text-[9px] text-red-400">{dd.absent}</span></div>}
                        {dd.people?.length <= 2 && dd.people.map((p, pi) => (
                          <div key={pi} className="text-[8px] text-muted-foreground truncate">{p.name?.split(" ")[0]} {p.hours}ч</div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="flex items-center gap-4 mt-3 text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-emerald-500" /> На работа</span>
              <span className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-blue-500" /> Отпуск</span>
              <span className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-orange-500" /> Болен</span>
              <span className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-red-500" /> Самоотлъчка</span>
            </div>
          </div>
        </TabsContent>
      </Tabs>

      {/* Report detail */}
      <DailyReportDialog
        open={detailOpen}
        onOpenChange={setDetailOpen}
        existingReportId={detailId}
        onSaved={() => { fetchTable(); fetchCalendar(); }}
      />
    </div>
  );
}
