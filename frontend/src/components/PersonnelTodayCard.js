import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Users, Briefcase, FileText, FileX, HeartPulse, Palmtree,
  AlertTriangle, HelpCircle, ArrowUpRight, Clock, MapPin,
} from "lucide-react";

const STATUS_CONFIG = {
  working:  { color: "text-emerald-400", bg: "bg-emerald-500/15 border-emerald-500/30", icon: Briefcase },
  sick:     { color: "text-rose-400",    bg: "bg-rose-500/15 border-rose-500/30",    icon: HeartPulse },
  leave:    { color: "text-sky-400",     bg: "bg-sky-500/15 border-sky-500/30",     icon: Palmtree },
  absent:   { color: "text-red-400",     bg: "bg-red-500/15 border-red-500/30",     icon: AlertTriangle },
  unknown:  { color: "text-gray-400",    bg: "bg-gray-500/15 border-gray-500/30",   icon: HelpCircle },
};

export default function PersonnelTodayCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    API.get("/dashboard/personnel-today")
      .then(r => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="rounded-xl border border-border bg-card p-5 mb-6 animate-pulse">
      <div className="h-4 w-40 bg-muted rounded mb-4" />
      <div className="grid grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => <div key={i} className="h-16 bg-muted rounded-lg" />)}
      </div>
    </div>
  );

  if (!data) return null;

  const { counters: c, personnel } = data;

  const counters = [
    { label: t("personnel.total"),      value: c.total,       color: "text-foreground",    Icon: Users },
    { label: t("personnel.working"),    value: c.working,     color: "text-emerald-400",   Icon: Briefcase },
    { label: t("personnel.withReport"), value: c.with_report, color: "text-primary",       Icon: FileText },
    { label: t("personnel.noReport"),   value: c.no_report,   color: "text-amber-400",     Icon: FileX },
    { label: t("personnel.sick"),       value: c.sick,        color: "text-rose-400",      Icon: HeartPulse },
    { label: t("personnel.leave"),      value: c.leave,       color: "text-sky-400",       Icon: Palmtree },
    { label: t("personnel.absent"),     value: c.absent,      color: "text-red-400",       Icon: AlertTriangle },
  ];

  // Only show alerts if there are issues
  const alerts = [];
  if (c.no_report > 0)  alerts.push({ text: t("personnel.alertNoReport", { count: c.no_report }), color: "text-amber-400 bg-amber-500/10 border-amber-500/30" });
  if (c.absent > 0)     alerts.push({ text: t("personnel.alertAbsent", { count: c.absent }),       color: "text-red-400 bg-red-500/10 border-red-500/30" });
  if (c.unknown > 0)    alerts.push({ text: t("personnel.alertUnknown", { count: c.unknown }),     color: "text-gray-400 bg-gray-500/10 border-gray-500/30" });

  return (
    <div className="rounded-xl border border-border bg-card p-5 mb-6" data-testid="personnel-today-card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Users className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold">{t("personnel.todayTitle")}</h2>
          <Badge variant="outline" className="text-[10px]">{c.total}</Badge>
        </div>
        <button onClick={() => navigate("/employees")} className="text-xs text-primary hover:underline flex items-center gap-1" data-testid="personnel-view-all">
          {t("common.viewAll")} <ArrowUpRight className="w-3 h-3" />
        </button>
      </div>

      {/* Counters */}
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-7 gap-2 mb-4" data-testid="personnel-counters">
        {counters.map(({ label, value, color, Icon }) => (
          <div key={label} className="rounded-lg bg-muted/30 p-2 text-center">
            <div className="flex items-center justify-center gap-1 mb-0.5">
              <Icon className={`w-3 h-3 ${color}`} />
              <span className={`text-lg font-bold font-mono ${color}`}>{value}</span>
            </div>
            <p className="text-[9px] text-muted-foreground leading-tight">{label}</p>
          </div>
        ))}
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4" data-testid="personnel-alerts">
          {alerts.map((a, i) => (
            <Badge key={i} variant="outline" className={`text-[10px] ${a.color}`}>{a.text}</Badge>
          ))}
        </div>
      )}

      {/* Personnel List */}
      <div className="space-y-1 max-h-[360px] overflow-y-auto" data-testid="personnel-list">
        {personnel.map(p => {
          const cfg = STATUS_CONFIG[p.day_status] || STATUS_CONFIG.unknown;
          const StatusIcon = cfg.icon;
          const isWorkingNoReport = p.day_status === "working" && !p.has_report;

          return (
            <div
              key={p.id}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-colors hover:bg-muted/20 ${isWorkingNoReport ? "border-amber-500/30 bg-amber-500/5" : "border-transparent"}`}
              data-testid={`personnel-row-${p.id}`}
            >
              {/* Avatar */}
              {p.avatar_url ? (
                <img src={`${process.env.REACT_APP_BACKEND_URL}${p.avatar_url}`} className="w-8 h-8 rounded-full object-cover flex-shrink-0" alt="" />
              ) : (
                <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-[10px] font-bold text-primary flex-shrink-0">
                  {(p.first_name?.[0] || "")}{(p.last_name?.[0] || "")}
                </div>
              )}

              {/* Name + Position */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{p.first_name} {p.last_name}</p>
                <p className="text-[10px] text-muted-foreground truncate">{p.position || p.role || "—"}</p>
              </div>

              {/* Status badge */}
              <Badge variant="outline" className={`text-[9px] gap-1 flex-shrink-0 ${cfg.bg} ${cfg.color}`}>
                <StatusIcon className="w-2.5 h-2.5" />
                {t(`personnel.status_${p.day_status}`)}
              </Badge>

              {/* Site */}
              {p.day_status === "working" && p.site_name && (
                <button
                  onClick={() => p.site_id && navigate(`/projects/${p.site_id}`)}
                  className="text-[10px] text-primary hover:underline flex items-center gap-0.5 flex-shrink-0 max-w-[120px] truncate"
                >
                  <MapPin className="w-2.5 h-2.5 flex-shrink-0" />{p.site_name}
                </button>
              )}

              {/* Report + hours */}
              {p.day_status === "working" && (
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {p.has_report ? (
                    <>
                      <FileText className="w-3 h-3 text-emerald-400" />
                      <span className="text-xs font-mono text-emerald-400">{p.hours}ч</span>
                    </>
                  ) : (
                    <Badge variant="outline" className="text-[9px] text-amber-400 bg-amber-500/10 border-amber-500/30 gap-0.5">
                      <FileX className="w-2.5 h-2.5" />{t("personnel.noReportShort")}
                    </Badge>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
