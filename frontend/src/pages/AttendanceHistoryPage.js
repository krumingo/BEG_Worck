import { useEffect, useState, useCallback } from "react";
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
  CalendarDays,
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

const REPORT_COLORS = {
  Draft: "text-gray-400",
  Submitted: "text-blue-400",
  Approved: "text-emerald-400",
  Rejected: "text-red-400",
};

export default function AttendanceHistoryPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [entries, setEntries] = useState([]);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchHistory = useCallback(async () => {
    try {
      const [attRes, repRes] = await Promise.all([
        API.get("/attendance/my-range"),
        API.get("/work-reports/my-range"),
      ]);
      setEntries(attRes.data);
      setReports(repRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const days = [];
  for (let i = 0; i < 14; i++) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    days.push(d.toISOString().split("T")[0]);
  }

  const entryMap = {};
  entries.forEach((e) => { entryMap[e.date] = e; });

  const reportsByDate = {};
  reports.forEach((r) => {
    if (!reportsByDate[r.date]) reportsByDate[r.date] = [];
    reportsByDate[r.date].push(r);
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[580px] mx-auto" data-testid="attendance-history-page">
      <div className="flex items-center gap-2 mb-6">
        <CalendarDays className="w-5 h-5 text-primary" />
        <h1 className="text-xl font-bold text-foreground">{t("attendance.history")}</h1>
      </div>
      <p className="text-sm text-muted-foreground mb-6">{t("attendance.last14Days")}</p>

      <div className="space-y-2" data-testid="history-list">
        {days.map((dateStr) => {
          const entry = entryMap[dateStr];
          const dayReports = reportsByDate[dateStr] || [];
          const d = new Date(dateStr + "T12:00:00");
          const dayName = formatDate(d, i18n.language, { weekday: "short" });
          const dayNum = d.getDate();
          const month = formatDate(d, i18n.language, { month: "short" });
          const isToday = dateStr === new Date().toISOString().split("T")[0];
          const isWeekend = d.getDay() === 0 || d.getDay() === 6;
          const Icon = entry ? (STATUS_ICONS[entry.status] || CheckCircle2) : null;

          return (
            <div
              key={dateStr}
              className={`flex items-center gap-4 p-3 rounded-lg border transition-colors ${
                isToday ? "border-primary/40 bg-primary/5" : "border-border bg-card"
              } ${isWeekend && !entry ? "opacity-50" : ""}`}
              data-testid={`history-${dateStr}`}
            >
              <div className="w-14 text-center flex-shrink-0">
                <p className="text-xs text-muted-foreground">{dayName}</p>
                <p className="text-lg font-bold text-foreground">{dayNum}</p>
                <p className="text-[10px] text-muted-foreground">{month}</p>
              </div>

              <div className="flex-1 min-w-0">
                {entry ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    <Icon className={`w-4 h-4 ${STATUS_COLORS[entry.status]?.split(" ")[1] || "text-muted-foreground"}`} />
                    <Badge variant="outline" className={`text-xs ${STATUS_COLORS[entry.status] || ""}`}>{t(`attendance.statusLabels.${entry.status.toLowerCase()}`, entry.status)}</Badge>
                    {dayReports.map((r) => (
                      <button
                        key={r.id}
                        onClick={() => navigate(`/work-reports/${r.id}`)}
                        className="flex items-center gap-1 text-xs hover:underline"
                      >
                        <FileText className={`w-3 h-3 ${REPORT_COLORS[r.status] || ""}`} />
                        <span className={REPORT_COLORS[r.status]}>{t(`workReports.status.${r.status.toLowerCase()}`)}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    {isWeekend ? t("attendance.weekend") : isToday ? t("attendance.notMarkedYet") : t("attendance.noRecord")}
                  </span>
                )}
              </div>

              {entry && (
                <span className="text-[11px] text-muted-foreground flex-shrink-0">
                  {formatTime(entry.marked_at, i18n.language)}
                </span>
              )}

              {isToday && (
                <Badge variant="default" className="text-[10px] px-1.5 py-0 flex-shrink-0">{t("common.today")}</Badge>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
