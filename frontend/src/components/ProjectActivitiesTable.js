/**
 * ProjectActivitiesTable — "Дейности по проект" с всички колони.
 * Визуалното сърце: бюджет, прогноза ч.ч., отчет ч.ч., %, статус.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Loader2, Clock, AlertTriangle } from "lucide-react";
import ActivityReportsList from "@/components/ActivityReportsList";

const STATUS_DOT = {
  green: "bg-emerald-500",
  yellow: "bg-amber-500",
  red: "bg-red-500",
};

function fmt(n) {
  if (n == null || n === 0) return "—";
  return n.toLocaleString("bg-BG", { maximumFractionDigits: 0 });
}

export default function ProjectActivitiesTable({ projectId }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [drillSmr, setDrillSmr] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/activities-overview`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data || !data.activities?.length) return <p className="text-sm text-muted-foreground text-center py-6">{t("activitiesTable.noData")}</p>;

  const { activities, totals } = data;

  return (
    <div data-testid="project-activities-table">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-cyan-400" />
          <span className="font-semibold text-sm">{t("activitiesTable.title")}</span>
          <Badge variant="outline" className="text-[10px]">{totals.activities_count}</Badge>
        </div>
        <div className="flex gap-2 text-[10px]">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500" />{totals.green_count}</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500" />{totals.yellow_count}</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" />{totals.red_count}</span>
        </div>
      </div>

      <div className="overflow-x-auto border border-border rounded-lg">
        <Table>
          <TableHeader>
            <TableRow className="text-[10px]">
              <TableHead className="w-8"></TableHead>
              <TableHead>{t("activitiesTable.section")}</TableHead>
              <TableHead>{t("activitiesTable.activity")}</TableHead>
              <TableHead className="text-center">{t("activitiesTable.unit")}</TableHead>
              <TableHead className="text-right">{t("activitiesTable.material")}</TableHead>
              <TableHead className="text-right">{t("activitiesTable.labor")}</TableHead>
              <TableHead className="text-right">{t("activitiesTable.total")}</TableHead>
              <TableHead className="text-right">{t("activitiesTable.forecastHH")}</TableHead>
              <TableHead className="text-right">{t("activitiesTable.reportHH")}</TableHead>
              <TableHead className="text-right">%</TableHead>
              <TableHead>{t("activitiesTable.label")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {activities.map((a, i) => {
              const dot = STATUS_DOT[a.status] || STATUS_DOT.green;
              const burnColor = a.status === "red" ? "text-red-400" : a.status === "yellow" ? "text-amber-400" : "text-emerald-400";
              return (
                <TableRow key={a.budget_id || `extra-${i}`} className="text-xs" data-testid={`activity-row-${i}`}>
                  <TableCell><span className={`w-2.5 h-2.5 rounded-full inline-block ${dot}`} /></TableCell>
                  <TableCell className="text-muted-foreground">{a.category}</TableCell>
                  <TableCell className="font-medium max-w-[180px] truncate">{a.activity_name}</TableCell>
                  <TableCell className="text-center text-muted-foreground">{a.unit}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(a.material_budget)}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(a.labor_budget)}</TableCell>
                  <TableCell className="text-right font-mono font-bold">{fmt(a.total_budget)}</TableCell>
                  <TableCell className="text-right font-mono">{a.planned_man_hours > 0 ? a.planned_man_hours.toFixed(0) : "—"}</TableCell>
                  <TableCell className="text-right">
                    {a.actual_hours > 0 ? (
                      <button
                        onClick={() => setDrillSmr(a.activity_name)}
                        className={`font-mono font-bold px-1.5 py-0.5 rounded ${burnColor} hover:underline`}
                        data-testid={`actual-hours-${i}`}
                      >
                        {a.actual_hours.toFixed(0)} ч.
                      </button>
                    ) : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    {a.burn_pct > 0 ? <span className={`font-mono font-bold ${burnColor}`}>{a.burn_pct.toFixed(0)}%</span> : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell>
                    {a.is_extra && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/30">{t("activitiesTable.extraWork")}</Badge>}
                  </TableCell>
                </TableRow>
              );
            })}
            {/* Summary row */}
            <TableRow className="text-xs font-bold border-t-2 border-border">
              <TableCell></TableCell>
              <TableCell></TableCell>
              <TableCell>{t("activitiesTable.totalRow")}</TableCell>
              <TableCell></TableCell>
              <TableCell></TableCell>
              <TableCell className="text-right font-mono">{fmt(totals.total_labor_budget)}</TableCell>
              <TableCell></TableCell>
              <TableCell className="text-right font-mono">{totals.total_planned_hours.toFixed(0)}</TableCell>
              <TableCell className="text-right font-mono text-primary">{totals.total_actual_hours.toFixed(0)} ч.</TableCell>
              <TableCell className="text-right">
                <span className={`font-mono ${totals.total_burn_pct > 100 ? "text-red-400" : totals.total_burn_pct > 80 ? "text-amber-400" : "text-emerald-400"}`}>
                  {totals.total_burn_pct.toFixed(0)}%
                </span>
              </TableCell>
              <TableCell></TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      {/* Level 2 Drill-down */}
      <ActivityReportsList
        projectId={projectId}
        smrType={drillSmr}
        open={!!drillSmr}
        onClose={() => setDrillSmr(null)}
      />
    </div>
  );
}
