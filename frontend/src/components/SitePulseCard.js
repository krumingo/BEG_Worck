/**
 * SitePulseCard — Compact daily pulse card per site.
 * Used in DashboardPage and ProjectDetailPage.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Building2, Users, Clock, DollarSign, Package, AlertTriangle,
  ChevronDown, ChevronRight, FileText,
} from "lucide-react";

const SEVERITY_COLORS = {
  info: "text-blue-400",
  warning: "text-amber-400",
  critical: "text-red-400",
};

export function SitePulseCard({ pulse }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  if (!pulse) return null;
  const bs = pulse.budget_snapshot || {};
  const statusColor = bs.status === "over_budget" ? "text-red-400" : bs.status === "warning" ? "text-amber-400" : "text-emerald-400";

  return (
    <div className="rounded-lg border border-border bg-card p-3 hover:border-primary/30 transition-colors" data-testid={`pulse-card-${pulse.site_id}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Building2 className="w-4 h-4 text-primary flex-shrink-0" />
          <span className="font-medium text-sm truncate">{pulse.site_name || pulse.site_code}</span>
        </div>
        <span className="text-[10px] text-muted-foreground flex-shrink-0">{pulse.date}</span>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-4 gap-2 text-xs mb-2">
        <div className="flex items-center gap-1">
          <Users className="w-3 h-3 text-cyan-400" />
          <span className="font-mono">{pulse.total_workers}</span>
        </div>
        <div className="flex items-center gap-1">
          <Clock className="w-3 h-3 text-amber-400" />
          <span className="font-mono">{pulse.total_hours?.toFixed(1)}ч</span>
        </div>
        <div className="flex items-center gap-1">
          <DollarSign className="w-3 h-3 text-emerald-400" />
          <span className="font-mono">{(pulse.total_labor_cost || 0).toFixed(0)}</span>
        </div>
        <div className="flex items-center gap-1">
          <Package className="w-3 h-3 text-purple-400" />
          <span className="font-mono">{(pulse.total_material_cost || 0).toFixed(0)}</span>
        </div>
      </div>

      {/* Budget bar */}
      {bs.total_budget > 0 && (
        <div className="mb-2">
          <div className="flex justify-between text-[10px] mb-0.5">
            <span className="text-muted-foreground">{t("pulse.budget")}</span>
            <span className={statusColor}>{bs.burn_pct}%</span>
          </div>
          <Progress value={Math.min(bs.burn_pct, 100)} className="h-1" />
        </div>
      )}

      {/* Alerts */}
      {pulse.alerts?.length > 0 && (
        <div className="space-y-0.5 mb-1">
          {pulse.alerts.slice(0, 2).map((a, i) => (
            <div key={i} className={`flex items-center gap-1 text-[10px] ${SEVERITY_COLORS[a.severity] || "text-muted-foreground"}`}>
              <AlertTriangle className="w-2.5 h-2.5 flex-shrink-0" />
              <span className="truncate">{a.message}</span>
            </div>
          ))}
          {pulse.alerts.length > 2 && (
            <span className="text-[9px] text-muted-foreground">+{pulse.alerts.length - 2} {t("pulse.more")}</span>
          )}
        </div>
      )}

      {/* Expand toggle */}
      <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground w-full mt-1">
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {t("pulse.details")}
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 text-[10px]">
          {/* Workers */}
          {pulse.workers?.length > 0 && (
            <div>
              <p className="text-muted-foreground mb-1">{t("pulse.workers")}</p>
              {pulse.workers.map(w => (
                <div key={w.worker_id} className="flex justify-between p-1 bg-muted/10 rounded">
                  <span>{w.worker_name}</span>
                  <span className="font-mono">{w.hours?.toFixed(1)}ч | {w.labor_cost?.toFixed(0)}лв</span>
                </div>
              ))}
            </div>
          )}
          {/* Calendar */}
          {pulse.calendar_summary && (
            <div className="flex gap-3">
              <span className="text-emerald-400">{pulse.calendar_summary.working} работят</span>
              {pulse.calendar_summary.sick > 0 && <span className="text-red-400">{pulse.calendar_summary.sick} болни</span>}
              {pulse.calendar_summary.vacation > 0 && <span className="text-amber-400">{pulse.calendar_summary.vacation} отпуск</span>}
            </div>
          )}
          {/* Report status */}
          <div className="flex items-center gap-1">
            <FileText className="w-3 h-3" />
            <span>{pulse.daily_report_submitted ? t("pulse.reportSubmitted") : t("pulse.reportMissing")}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default SitePulseCard;
