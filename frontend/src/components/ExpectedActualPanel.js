/**
 * ExpectedActualPanel — Planned vs Real comparison by activity/group/location.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  BarChart3, Loader2, ChevronDown, ChevronRight,
  TrendingUp, Clock, DollarSign,
} from "lucide-react";

const STATUS_CFG = {
  on_track: { color: "text-emerald-400", bg: "bg-emerald-500", label: "OK" },
  warning: { color: "text-amber-400", bg: "bg-amber-500", label: "!" },
  over: { color: "text-red-400", bg: "bg-red-500", label: "!!" },
};

function ComparisonRow({ item }) {
  const st = STATUS_CFG[item.status] || STATUS_CFG.on_track;
  const pct = item.planned_cost > 0 ? Math.min(Math.round(item.actual_cost / item.planned_cost * 100), 200) : 0;
  return (
    <div className="flex items-center gap-3 py-1.5 text-xs">
      <span className={`w-2 h-2 rounded-full ${st.bg} flex-shrink-0`} />
      <span className="flex-1 truncate min-w-0">{item.name}</span>
      <span className="font-mono w-14 text-right text-muted-foreground">{item.planned_hours?.toFixed(0) || 0}ч</span>
      <span className="font-mono w-14 text-right">{item.actual_hours?.toFixed(0) || 0}ч</span>
      <span className={`font-mono w-16 text-right font-bold ${st.color}`}>
        {item.variance_cost > 0 ? "+" : ""}{item.variance_cost?.toFixed(0) || 0}
      </span>
      <div className="w-20"><Progress value={Math.min(pct, 100)} className="h-1.5" /></div>
    </div>
  );
}

export default function ExpectedActualPanel({ projectId }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("activities");
  const [expanded, setExpanded] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/expected-actual`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const { summary, activities, groups, locations } = data;
  const st = STATUS_CFG[summary.overall_status] || STATUS_CFG.on_track;
  const items = tab === "activities" ? activities : tab === "groups" ? groups : locations;

  return (
    <div className="space-y-3" data-testid="expected-actual-panel">
      <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-2 w-full">
        {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        <BarChart3 className="w-4 h-4 text-cyan-400" />
        <span className="font-semibold text-sm">{t("expectedActual.title")}</span>
        <Badge variant="outline" className={`text-[10px] ${st.color}`}>{st.label}</Badge>
        {summary.over_count > 0 && <Badge className="bg-red-500/20 text-red-400 text-[9px]">{summary.over_count} {t("expectedActual.overBudget")}</Badge>}
      </button>

      {expanded && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div><Clock className="w-3.5 h-3.5 mx-auto mb-0.5 text-muted-foreground" /><p className="font-mono">{summary.total_planned_hours}</p><p className="text-[9px] text-muted-foreground">{t("expectedActual.plannedHours")}</p></div>
            <div><Clock className="w-3.5 h-3.5 mx-auto mb-0.5 text-primary" /><p className="font-mono">{summary.total_actual_hours}</p><p className="text-[9px] text-muted-foreground">{t("expectedActual.actualHours")}</p></div>
            <div><DollarSign className="w-3.5 h-3.5 mx-auto mb-0.5 text-muted-foreground" /><p className="font-mono">{summary.total_planned_cost?.toFixed(0)}</p><p className="text-[9px] text-muted-foreground">{t("expectedActual.plannedCost")}</p></div>
            <div><DollarSign className="w-3.5 h-3.5 mx-auto mb-0.5 text-primary" /><p className={`font-mono ${st.color}`}>{summary.total_actual_cost?.toFixed(0)}</p><p className="text-[9px] text-muted-foreground">{t("expectedActual.actualCost")}</p></div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-border pb-1">
            {[
              { key: "activities", label: t("expectedActual.byActivity"), count: activities.length },
              { key: "groups", label: t("expectedActual.byGroup"), count: groups.length },
              { key: "locations", label: t("expectedActual.byLocation"), count: locations.length },
            ].map(tb => (
              <button key={tb.key} onClick={() => setTab(tb.key)}
                className={`px-2 py-1 text-[10px] rounded-t ${tab === tb.key ? "bg-muted text-foreground font-bold" : "text-muted-foreground hover:text-foreground"}`}>
                {tb.label} ({tb.count})
              </button>
            ))}
          </div>

          {/* Header row */}
          <div className="flex items-center gap-3 text-[9px] text-muted-foreground px-1">
            <span className="w-2" />
            <span className="flex-1">{t("common.name")}</span>
            <span className="w-14 text-right">{t("expectedActual.plan")}</span>
            <span className="w-14 text-right">{t("expectedActual.actual")}</span>
            <span className="w-16 text-right">{t("expectedActual.variance")}</span>
            <span className="w-20" />
          </div>

          {/* Rows */}
          <div className="max-h-[200px] overflow-y-auto">
            {items.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-4">{t("expectedActual.noData")}</p>
            ) : items.map((item, i) => <ComparisonRow key={i} item={item} />)}
          </div>
        </>
      )}
    </div>
  );
}
