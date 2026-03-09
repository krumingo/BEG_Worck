import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
  ArrowLeft, User, Briefcase, Calendar, Clock, MapPin, CreditCard, Loader2,
  ChevronLeft, ChevronRight,
} from "lucide-react";

const STATUS_COLORS = { Present: "bg-emerald-500/20 text-emerald-400", Absent: "bg-red-500/20 text-red-400", Late: "bg-amber-500/20 text-amber-400" };
const STATUS_BG = { Present: "Присъства", Absent: "Отсъства", Late: "Закъснял" };
const DAYS_BG = ["Нд", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

export default function EmployeeDetailPage() {
  const { userId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [calMonth, setCalMonth] = useState(new Date().toISOString().slice(0, 7));
  const [calendar, setCalendar] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await API.get(`/employees/${userId}/dashboard`);
      setData(res.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [userId]);

  const fetchCalendar = useCallback(async () => {
    try {
      const res = await API.get(`/employees/${userId}/calendar?month=${calMonth}`);
      setCalendar(res.data);
    } catch (err) { console.error(err); }
  }, [userId, calMonth]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { fetchCalendar(); }, [fetchCalendar]);

  const prevMonth = () => {
    const [y, m] = calMonth.split("-").map(Number);
    setCalMonth(m === 1 ? `${y-1}-12` : `${y}-${String(m-1).padStart(2, "0")}`);
  };
  const nextMonth = () => {
    const [y, m] = calMonth.split("-").map(Number);
    setCalMonth(m === 12 ? `${y+1}-01` : `${y}-${String(m+1).padStart(2, "0")}`);
  };

  // Build calendar grid
  const buildCalGrid = () => {
    if (!calendar) return [];
    const [y, m] = calMonth.split("-").map(Number);
    const firstDay = new Date(y, m - 1, 1).getDay();
    const daysInMonth = new Date(y, m, 0).getDate();
    const dayMap = {};
    (calendar.days || []).forEach(d => { dayMap[d.date] = d; });
    
    const grid = [];
    let week = new Array(firstDay).fill(null);
    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      week.push({ day: d, date: dateStr, data: dayMap[dateStr] || null });
      if (week.length === 7) { grid.push(week); week = []; }
    }
    if (week.length > 0) { while (week.length < 7) week.push(null); grid.push(week); }
    return grid;
  };

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  if (!data) return <div className="p-6 text-muted-foreground">Служителят не е намерен</div>;

  const { employee: emp, profile: prof, attendance, project_history, hours_summary, payslips } = data;
  const calGrid = buildCalGrid();

  return (
    <div className="p-6 max-w-[1200px]" data-testid="employee-detail-page">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Button variant="ghost" size="sm" onClick={() => navigate("/employees")}><ArrowLeft className="w-4 h-4 mr-1" /> Персонал</Button>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-foreground">{emp.first_name} {emp.last_name}</h1>
          <div className="flex items-center gap-3 text-sm text-muted-foreground mt-0.5">
            <Badge variant="outline">{emp.role}</Badge>
            {emp.email && <span>{emp.email}</span>}
            {emp.phone && <span>{emp.phone}</span>}
          </div>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">Този месец</p>
          <p className="text-lg font-bold text-foreground">{hours_summary.current_month_days} дни / {hours_summary.current_month_hours}ч</p>
          <p className="text-xs text-muted-foreground">{hours_summary.total_projects} обекта</p>
        </div>
      </div>

      {/* Pay info bar */}
      {prof && (
        <div className="flex items-center gap-6 p-3 rounded-lg bg-muted/20 border border-border mb-6 text-sm">
          <div><span className="text-muted-foreground">Тип:</span> <span className="text-foreground font-medium">{prof.pay_type}</span></div>
          {prof.hourly_rate && <div><span className="text-muted-foreground">Часова:</span> <span className="font-mono">{prof.hourly_rate} лв/ч</span></div>}
          {prof.daily_rate && <div><span className="text-muted-foreground">Дневна:</span> <span className="font-mono">{prof.daily_rate} лв/ден</span></div>}
          {prof.monthly_salary && <div><span className="text-muted-foreground">Месечна:</span> <span className="font-mono">{prof.monthly_salary} лв</span></div>}
          <div><span className="text-muted-foreground">Часове/ден:</span> <span className="font-mono">{prof.standard_hours_per_day}ч</span></div>
          <Badge variant="outline" className={prof.active ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}>
            {prof.active ? "Активен" : "Неактивен"}
          </Badge>
        </div>
      )}

      <Tabs defaultValue="calendar">
        <TabsList className="mb-4">
          <TabsTrigger value="calendar" data-testid="tab-calendar"><Calendar className="w-4 h-4 mr-1" /> Календар</TabsTrigger>
          <TabsTrigger value="projects" data-testid="tab-projects"><MapPin className="w-4 h-4 mr-1" /> Обекти ({project_history.length})</TabsTrigger>
          <TabsTrigger value="attendance" data-testid="tab-attendance"><Clock className="w-4 h-4 mr-1" /> Присъствия</TabsTrigger>
          <TabsTrigger value="payroll" data-testid="tab-payroll"><CreditCard className="w-4 h-4 mr-1" /> Заплащане</TabsTrigger>
        </TabsList>

        {/* Calendar Tab */}
        <TabsContent value="calendar">
          <div className="rounded-xl border border-border bg-card p-4" data-testid="calendar-view">
            <div className="flex items-center justify-between mb-4">
              <Button variant="ghost" size="sm" onClick={prevMonth}><ChevronLeft className="w-4 h-4" /></Button>
              <h3 className="text-sm font-semibold text-foreground">{calMonth}</h3>
              <Button variant="ghost" size="sm" onClick={nextMonth}><ChevronRight className="w-4 h-4" /></Button>
            </div>
            {calendar && (
              <>
                <div className="text-xs text-muted-foreground mb-1 text-right">
                  Дни: {calendar.total_present} | Часове: {calendar.total_hours}
                </div>
                <div className="grid grid-cols-7 gap-1">
                  {DAYS_BG.map(d => <div key={d} className="text-center text-[10px] text-muted-foreground font-medium py-1">{d}</div>)}
                  {calGrid.flat().map((cell, i) => {
                    if (!cell) return <div key={i} className="h-16" />;
                    const d = cell.data;
                    const att = d?.attendance;
                    const isPresent = att?.status === "Present";
                    const isAbsent = att?.status === "Absent";
                    return (
                      <div key={i} className={`h-16 rounded-md border text-xs p-1 ${
                        isPresent ? "border-emerald-500/30 bg-emerald-500/10" :
                        isAbsent ? "border-red-500/30 bg-red-500/10" :
                        d ? "border-border bg-muted/20" : "border-transparent"
                      }`} data-testid={`cal-day-${cell.date}`}>
                        <span className={`text-[10px] font-mono ${isPresent ? "text-emerald-400" : isAbsent ? "text-red-400" : "text-muted-foreground"}`}>{cell.day}</span>
                        {att && <div className="text-[9px] text-muted-foreground truncate">{att.project_code}</div>}
                        {d?.total_hours > 0 && <div className="text-[9px] font-mono text-amber-400">{d.total_hours}ч</div>}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </TabsContent>

        {/* Projects Tab */}
        <TabsContent value="projects">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="projects-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Обект</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Роля</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Дни</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Часове</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Последно</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {project_history.length === 0 ? (
                  <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Няма данни за обекти</TableCell></TableRow>
                ) : project_history.map((ph, i) => (
                  <TableRow key={i} className="cursor-pointer hover:bg-muted/30" onClick={() => navigate(`/projects/${ph.project_id}`)}>
                    <TableCell><span className="font-mono text-primary text-sm">{ph.project_code}</span> <span className="text-muted-foreground text-sm">{ph.project_name}</span></TableCell>
                    <TableCell className="text-sm text-muted-foreground">{ph.role_in_project || "—"}</TableCell>
                    <TableCell><Badge variant="outline" className="text-[10px]">{ph.project_status}</Badge></TableCell>
                    <TableCell className="text-right font-mono text-sm">{ph.days_present}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-amber-400">{ph.total_hours || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{ph.last_attendance ? formatDate(ph.last_attendance) : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* Attendance Tab */}
        <TabsContent value="attendance">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="attendance-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Дата</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Обект</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Бележка</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {attendance.length === 0 ? (
                  <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Няма записи за присъствие</TableCell></TableRow>
                ) : attendance.map((att, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-sm font-mono">{att.date}</TableCell>
                    <TableCell><Badge variant="outline" className={`text-[10px] ${STATUS_COLORS[att.status] || ""}`}>{STATUS_BG[att.status] || att.status}</Badge></TableCell>
                    <TableCell className="text-sm text-muted-foreground">{att.project_code || "—"} {att.project_name || ""}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{att.note || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* Payroll Tab */}
        <TabsContent value="payroll">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="payroll-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Период</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Бруто</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Нето</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {payslips.length === 0 ? (
                  <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Няма фишове</TableCell></TableRow>
                ) : payslips.map((ps, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-sm">{ps.period_start} — {ps.period_end}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{formatCurrency(ps.gross_pay, "BGN")}</TableCell>
                    <TableCell className="text-right font-mono text-sm font-bold">{formatCurrency(ps.net_pay, "BGN")}</TableCell>
                    <TableCell><Badge variant="outline" className={`text-[10px] ${ps.status === "Paid" ? "bg-emerald-500/20 text-emerald-400" : ""}`}>{ps.status}</Badge></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="p-3 border-t border-border">
              <Button variant="outline" size="sm" onClick={() => navigate("/payroll")} className="text-xs">Към Заплати</Button>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
