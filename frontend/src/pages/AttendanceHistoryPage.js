import { useEffect, useState, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDate, formatTime } from "@/lib/i18nUtils";
import { Badge } from "@/components/ui/badge";
import {
  CheckCircle2,
  XCircle,
  Clock,
  ThermometerSun,
  Palmtree,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FileText,
} from "lucide-react";

const STATUS_ICONS = {
  Present: CheckCircle2, Absent: XCircle, Late: Clock,
  SickLeave: ThermometerSun, Vacation: Palmtree,
};

const STATUS_COLORS = {
  Present: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Absent: "bg-red-500/20 text-red-400 border-red-500/30",
  Late: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  SickLeave: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  Vacation: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
};

const DOT_COLORS = {
  Present: "bg-emerald-400",
  Absent: "bg-red-400",
  Late: "bg-amber-400",
  SickLeave: "bg-orange-400",
  Vacation: "bg-cyan-400",
};

const REPORT_COLORS = {
  Draft: "text-gray-400",
  Submitted: "text-blue-400",
  Approved: "text-emerald-400",
  Rejected: "text-red-400",
};

const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"];

const toDateStr = (d) => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
};

export default function AttendanceHistoryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const today = new Date();
  const [monthDate, setMonthDate] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
  const [entries, setEntries] = useState([]);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState(toDateStr(today));

  const fetchMonth = useCallback(async () => {
    setLoading(true);
    try {
      const from = toDateStr(new Date(monthDate.getFullYear(), monthDate.getMonth(), 1));
      const to = toDateStr(new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0));
      const [attRes, repRes] = await Promise.all([
        API.get(`/attendance/my-range?from_date=${from}&to_date=${to}`),
        API.get(`/work-reports/my-range?from_date=${from}&to_date=${to}`),
      ]);
      setEntries(attRes.data || []);
      setReports(repRes.data || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [monthDate]);

  useEffect(() => { fetchMonth(); }, [fetchMonth]);

  const entryMap = useMemo(() => {
    const m = {};
    entries.forEach((e) => { m[e.date] = e; });
    return m;
  }, [entries]);

  const reportsByDate = useMemo(() => {
    const m = {};
    reports.forEach((r) => {
      if (!m[r.date]) m[r.date] = [];
      m[r.date].push(r);
    });
    return m;
  }, [reports]);

  const presentCount = entries.filter((e) => e.status === "Present" || e.status === "Late").length;
  const totalHours = reports.reduce((sum, r) => sum + (r.total_hours || 0), 0);

  const changeMonth = (delta) => {
    const next = new Date(monthDate.getFullYear(), monthDate.getMonth() + delta, 1);
    setMonthDate(next);
    setSelectedDate(null);
  };

  // Календарна мрежа: седмицата започва от понеделник
  const daysInMonth = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0).getDate();
  const leadingBlanks = (new Date(monthDate.getFullYear(), monthDate.getMonth(), 1).getDay() + 6) % 7;
  const todayStr = toDateStr(today);
  const monthLabel = formatDate(monthDate, { month: "long", year: "numeric" });

  const selEntry = selectedDate ? entryMap[selectedDate] : null;
  const selReports = selectedDate ? (reportsByDate[selectedDate] || []) : [];
  const SelIcon = selEntry ? (STATUS_ICONS[selEntry.status] || CheckCircle2) : null;

  return (
    <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="attendance-history-page">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="w-9 h-9 rounded-xl border border-border bg-card flex items-center justify-center active:scale-95 transition-all" data-testid="history-back">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="text-lg font-bold text-foreground">{t("attendance.history")}</h1>
      </div>

      <div className="rounded-2xl border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-1">
          <button onClick={() => changeMonth(-1)} className="w-8 h-8 rounded-lg border border-border flex items-center justify-center active:scale-95 transition-all" data-testid="month-prev">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="font-semibold capitalize">{monthLabel}</span>
          <button onClick={() => changeMonth(1)} className="w-8 h-8 rounded-lg border border-border flex items-center justify-center active:scale-95 transition-all" data-testid="month-next">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
        <p className="text-center text-[11px] text-muted-foreground mb-3">{presentCount} присъствия · {totalHours}ч · {reports.length} отчета</p>

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-7 gap-1 mb-1">
              {WEEKDAYS.map((w) => (
                <span key={w} className="text-center text-[10px] text-muted-foreground">{w}</span>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-1" data-testid="calendar-grid">
              {Array.from({ length: leadingBlanks }).map((_, i) => (
                <div key={`b${i}`} className="h-10" />
              ))}
              {Array.from({ length: daysInMonth }).map((_, i) => {
                const dayNum = i + 1;
                const dateStr = toDateStr(new Date(monthDate.getFullYear(), monthDate.getMonth(), dayNum));
                const entry = entryMap[dateStr];
                const hasReports = (reportsByDate[dateStr] || []).length > 0;
                const isToday = dateStr === todayStr;
                const isSelected = dateStr === selectedDate;
                const isFuture = dateStr > todayStr;
                const dot = entry ? DOT_COLORS[entry.status] : (hasReports ? "bg-blue-400" : null);
                return (
                  <button
                    key={dateStr}
                    onClick={() => setSelectedDate(dateStr)}
                    className={`h-10 rounded-lg border flex flex-col items-center justify-center gap-0.5 transition-all active:scale-95 ${
                      isSelected ? "border-primary bg-primary/10" : isToday ? "border-amber-500/60 bg-amber-500/10" : "border-border"
                    } ${isFuture || (!entry && !hasReports && !isToday) ? "opacity-40" : ""}`}
                    data-testid={`cal-${dateStr}`}
                  >
                    <span className={`text-xs leading-none ${isToday ? "font-bold" : ""}`}>{dayNum}</span>
                    {dot ? <span className={`w-1.5 h-1.5 rounded-full ${dot}`} /> : isToday ? <span className="text-[8px] text-amber-400 leading-none">днес</span> : null}
                  </button>
                );
              })}
            </div>
            <div className="flex justify-center gap-3 mt-3 text-[10px] text-muted-foreground flex-wrap">
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />присъства</span>
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" />закъснял</span>
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-400" />отсъства</span>
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-400" />отчет</span>
            </div>
          </>
        )}
      </div>

      {selectedDate && !loading && (
        <div className="rounded-2xl border border-border bg-card p-4" data-testid="day-detail">
          <p className="font-semibold text-sm capitalize mb-2">{formatDate(new Date(selectedDate + "T12:00:00"), { weekday: "long", day: "numeric", month: "long" })}</p>
          {selEntry ? (
            <div className="flex items-center gap-2 flex-wrap mb-2">
              <SelIcon className={`w-4 h-4 ${STATUS_COLORS[selEntry.status]?.split(" ")[1] || "text-muted-foreground"}`} />
              <Badge variant="outline" className={`text-xs ${STATUS_COLORS[selEntry.status] || ""}`}>{t(`attendance.statusLabels.${selEntry.status.toLowerCase()}`, selEntry.status)}</Badge>
              {selEntry.marked_at && <span className="text-[11px] text-muted-foreground">{formatTime(selEntry.marked_at)}</span>}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground mb-2">{selectedDate === todayStr ? t("attendance.notMarkedYet") : t("attendance.noRecord")}</p>
          )}
          {selReports.map((r) => (
            <button
              key={r.id}
              onClick={() => navigate(`/work-reports/${r.id}`)}
              className="flex items-center gap-2 text-xs hover:underline py-0.5"
            >
              <FileText className={`w-3.5 h-3.5 ${REPORT_COLORS[r.status] || ""}`} />
              <span className={REPORT_COLORS[r.status]}>{t(`workReports.status.${r.status.toLowerCase()}`)}</span>
              {r.total_hours ? <span className="text-muted-foreground">· {r.total_hours}ч</span> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
