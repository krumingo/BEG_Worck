/**
 * WorkerCalendarPage — Monthly calendar grid: workers × days with status colors.
 * Route: /worker-calendar
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Calendar, Loader2, RefreshCcw, Users, AlertTriangle, TrendingUp,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_COLORS = {
  working: "bg-emerald-500",
  sick_paid: "bg-red-500",
  sick_unpaid: "bg-red-300",
  vacation_paid: "bg-amber-500",
  vacation_unpaid: "bg-amber-300",
  absent_unauthorized: "bg-zinc-700",
  day_off: "bg-zinc-800/50",
  holiday: "bg-blue-500/50",
};
const STATUS_LABELS = {
  working: "Работи", sick_paid: "Болн. (пл.)", sick_unpaid: "Болн. (НОИ)",
  vacation_paid: "Отп. (пл.)", vacation_unpaid: "Отп. (непл.)", absent_unauthorized: "Самоотл.",
  day_off: "Почивен", holiday: "Празник",
};

export default function WorkerCalendarPage() {
  const { t } = useTranslation();
  const now = new Date();
  const [month, setMonth] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [employees, setEmployees] = useState([]);
  const [calendar, setCalendar] = useState([]);
  const [overhead, setOverhead] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [empRes, calRes, ohRes] = await Promise.all([
        API.get("/employees"),
        API.get(`/worker-calendar?month=${month}`),
        API.get(`/overhead/realtime?month=${month}`),
      ]);
      setEmployees(empRes.data || []);
      setCalendar(calRes.data.items || []);
      setOverhead(ohRes.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [month]);

  useEffect(() => { load(); }, [load]);

  // Build calendar map: worker_id → { date → entry }
  const calMap = {};
  for (const e of calendar) {
    if (!calMap[e.worker_id]) calMap[e.worker_id] = {};
    calMap[e.worker_id][e.date] = e;
  }

  // Generate days in month
  const [y, m] = month.split("-").map(Number);
  const daysInMonth = new Date(y, m, 0).getDate();
  const days = [];
  for (let d = 1; d <= daysInMonth; d++) {
    const dt = new Date(y, m - 1, d);
    const isWeekend = dt.getDay() === 0 || dt.getDay() === 6;
    days.push({ day: d, date: `${month}-${String(d).padStart(2, "0")}`, isWeekend });
  }

  const handleSetStatus = async (workerId, date, status) => {
    try {
      await API.post("/worker-calendar", { worker_id: workerId, date, status });
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  const handleSync = async () => {
    try {
      const today = new Date().toISOString().slice(0, 10);
      const res = await API.post(`/worker-calendar/sync-from-sessions?date=${today}`);
      toast.success(`${t("workerCalendar.synced")}: ${res.data.synced}`);
      load();
    } catch (err) { toast.error(t("common.error")); }
  };

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin" /></div>;

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="worker-calendar-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-indigo-500/10 flex items-center justify-center">
            <Calendar className="w-5 h-5 text-indigo-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold">{t("workerCalendar.title")}</h1>
            <p className="text-sm text-muted-foreground">{t("workerCalendar.subtitle")}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Input type="month" value={month} onChange={e => setMonth(e.target.value)} className="w-40" data-testid="month-picker" />
          <Button size="sm" variant="outline" onClick={handleSync} data-testid="sync-btn">
            <RefreshCcw className="w-4 h-4 mr-1" /> {t("workerCalendar.sync")}
          </Button>
        </div>
      </div>

      {/* Overhead summary */}
      {overhead && (
        <Card>
          <CardContent className="p-4">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-center text-xs">
              <div>
                <p className="text-muted-foreground">{t("workerCalendar.fixedTotal")}</p>
                <p className="font-mono font-bold text-lg">{overhead.fixed_total.toFixed(0)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("workerCalendar.ohPerPersonDay")}</p>
                <p className="font-mono font-bold text-lg text-primary">{overhead.overhead_per_person_day.toFixed(2)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("workerCalendar.avgWorking")}</p>
                <p className="font-mono font-bold text-lg">{overhead.avg_working_per_day.toFixed(1)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("workerCalendar.workingDays")}</p>
                <p className="font-mono font-bold text-lg">{overhead.working_days}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("workerCalendar.employees")}</p>
                <p className="font-mono font-bold text-lg">{overhead.total_employees}</p>
              </div>
            </div>
            {overhead.alerts?.length > 0 && (
              <div className="mt-2 flex items-center gap-2 text-xs text-amber-400">
                <AlertTriangle className="w-3.5 h-3.5" />
                {overhead.alerts[0]}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Calendar grid */}
      <Card>
        <CardContent className="p-2 overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead>
              <tr>
                <th className="text-left p-1 sticky left-0 bg-card z-10 min-w-[120px]">{t("workerCalendar.worker")}</th>
                {days.map(d => (
                  <th key={d.day} className={`text-center p-0.5 w-7 ${d.isWeekend ? "text-muted-foreground/50" : ""}`}>
                    {d.day}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {employees.map(emp => {
                const wid = emp.user_id || emp.id;
                const name = emp.name || `${emp.first_name || ""} ${emp.last_name || ""}`.trim();
                return (
                  <tr key={wid} className="border-t border-border/30">
                    <td className="p-1 sticky left-0 bg-card z-10 truncate max-w-[120px]">{name}</td>
                    {days.map(d => {
                      const entry = calMap[wid]?.[d.date];
                      const status = entry?.status || (d.isWeekend ? "day_off" : "");
                      const color = STATUS_COLORS[status] || "bg-zinc-900";
                      return (
                        <td key={d.day} className="p-0.5 text-center">
                          <Select value={status || "none"} onValueChange={v => { if (v !== "none") handleSetStatus(wid, d.date, v); }}>
                            <SelectTrigger className={`w-6 h-5 p-0 border-0 rounded-sm ${color}`}>
                              <span />
                            </SelectTrigger>
                            <SelectContent>
                              {Object.entries(STATUS_LABELS).map(([k, v]) => (
                                <SelectItem key={k} value={k} className="text-xs">{v}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-[10px]">
        {Object.entries(STATUS_LABELS).map(([k, v]) => (
          <div key={k} className="flex items-center gap-1">
            <span className={`w-3 h-3 rounded-sm ${STATUS_COLORS[k]}`} />
            <span>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
