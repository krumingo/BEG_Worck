import { useEffect, useState, useCallback } from "react";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  CheckCircle2,
  XCircle,
  Clock,
  ThermometerSun,
  Palmtree,
  CalendarDays,
} from "lucide-react";

const STATUS_ICONS = {
  Present: CheckCircle2,
  Absent: XCircle,
  Late: Clock,
  SickLeave: ThermometerSun,
  Vacation: Palmtree,
};

const STATUS_COLORS = {
  Present: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Absent: "bg-red-500/20 text-red-400 border-red-500/30",
  Late: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  SickLeave: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  Vacation: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
};

export default function AttendanceHistoryPage() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await API.get("/attendance/my-range");
      setEntries(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // Generate last 14 days
  const days = [];
  for (let i = 0; i < 14; i++) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    days.push(d.toISOString().split("T")[0]);
  }

  const entryMap = {};
  entries.forEach((e) => { entryMap[e.date] = e; });

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
        <h1 className="text-xl font-bold text-foreground">Attendance History</h1>
      </div>
      <p className="text-sm text-muted-foreground mb-6">Last 14 days</p>

      <div className="space-y-2" data-testid="history-list">
        {days.map((dateStr) => {
          const entry = entryMap[dateStr];
          const d = new Date(dateStr + "T12:00:00");
          const dayName = d.toLocaleDateString("en-US", { weekday: "short" });
          const dayNum = d.getDate();
          const month = d.toLocaleDateString("en-US", { month: "short" });
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
              {/* Date */}
              <div className="w-14 text-center flex-shrink-0">
                <p className="text-xs text-muted-foreground">{dayName}</p>
                <p className="text-lg font-bold text-foreground">{dayNum}</p>
                <p className="text-[10px] text-muted-foreground">{month}</p>
              </div>

              {/* Status */}
              <div className="flex-1 min-w-0">
                {entry ? (
                  <div className="flex items-center gap-2">
                    <Icon className={`w-4 h-4 ${STATUS_COLORS[entry.status]?.split(" ")[1] || "text-muted-foreground"}`} />
                    <Badge variant="outline" className={`text-xs ${STATUS_COLORS[entry.status] || ""}`}>{entry.status}</Badge>
                    {entry.note && (
                      <span className="text-xs text-muted-foreground truncate">- {entry.note}</span>
                    )}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    {isWeekend ? "Weekend" : isToday ? "Not marked yet" : "No record"}
                  </span>
                )}
              </div>

              {/* Time */}
              {entry && (
                <span className="text-[11px] text-muted-foreground flex-shrink-0">
                  {new Date(entry.marked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}

              {isToday && (
                <Badge variant="default" className="text-[10px] px-1.5 py-0 flex-shrink-0">Today</Badge>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
