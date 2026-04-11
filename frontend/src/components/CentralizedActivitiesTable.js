/**
 * CentralizedActivitiesTable — Main management table for SMR per project.
 * Reads from centralized reports activities projection.
 * Shows: planned/draft/approved/total hours, clean/loaded labor, subcontractor, risk.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Clock, Loader2, AlertTriangle, Eye, ChevronDown, ChevronRight,
} from "lucide-react";
import ActivityReportsList from "@/components/ActivityReportsList";

const STATUS_DOT = { green: "bg-emerald-500", yellow: "bg-amber-500", red: "bg-red-500" };
function fmt(n) { return n == null || n === 0 ? "—" : n.toLocaleString("bg-BG", { maximumFractionDigits: 0 }); }

export default function CentralizedActivitiesTable({ projectId }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [drillSmr, setDrillSmr] = useState(null);
  const [showDetails, setShowDetails] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/centralized-reports/activities`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  const activities = data?.activities || [];
  if (!activities.length) return <p className="text-center text-muted-foreground py-6 text-sm">{t("actTable.noData")}</p>;

  // Summary
  const totalPlanned = activities.reduce((s, a) => s + (a.planned_hours || 0), 0);
  const totalDraft = activities.reduce((s, a) => s + (a.draft_hours || 0), 0);
  const totalApproved = activities.reduce((s, a) => s + (a.approved_hours || 0), 0);
  const totalReported = activities.reduce((s, a) => s + (a.total_reported_hours || 0), 0);
  const totalClean = activities.reduce((s, a) => s + (a.clean_labor_cost || 0), 0);
  const totalLoaded = activities.reduce((s, a) => s + (a.labor_cost_with_overhead || 0), 0);
  const redCount = activities.filter(a => a.risk_status === "red").length;
  const yellowCount = activities.filter(a => a.risk_status === "yellow").length;
  const extraCount = activities.filter(a => a.is_extra).length;

  return (
    <div className="space-y-3" data-testid="centralized-activities-table">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-cyan-400" />
          <span className="font-semibold text-sm">{t("actTable.title")}</span>
          <Badge variant="outline" className="text-[10px]">{activities.length}</Badge>
        </div>
        <div className="flex gap-2 text-[10px]">
          {redCount > 0 && <Badge className="bg-red-500/20 text-red-400 text-[9px]">{redCount} {t("actTable.overBudget")}</Badge>}
          {yellowCount > 0 && <Badge className="bg-amber-500/20 text-amber-400 text-[9px]">{yellowCount} {t("actTable.warning")}</Badge>}
          {extraCount > 0 && <Badge className="bg-blue-500/20 text-blue-400 text-[9px]">{extraCount} {t("actTable.extra")}</Badge>}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 md:grid-cols-7 gap-2 text-center text-[10px]">
        <div className="rounded border border-border p-1.5"><p className="font-mono font-bold text-sm">{fmt(totalPlanned)}</p><p className="text-muted-foreground">{t("actTable.planned")}</p></div>
        <div className="rounded border border-border p-1.5"><p className="font-mono font-bold text-sm text-blue-400">{fmt(totalDraft)}</p><p className="text-muted-foreground">{t("actTable.draft")}</p></div>
        <div className="rounded border border-border p-1.5"><p className="font-mono font-bold text-sm text-emerald-400">{fmt(totalApproved)}</p><p className="text-muted-foreground">{t("actTable.approved")}</p></div>
        <div className="rounded border border-border p-1.5"><p className="font-mono font-bold text-sm">{fmt(totalReported)}</p><p className="text-muted-foreground">{t("actTable.total")}</p></div>
        <div className="rounded border border-border p-1.5"><p className="font-mono font-bold text-sm">{fmt(totalClean)}</p><p className="text-muted-foreground">{t("actTable.clean")}</p></div>
        <div className="rounded border border-border p-1.5"><p className="font-mono font-bold text-sm">{fmt(totalLoaded)}</p><p className="text-muted-foreground">{t("actTable.loaded")}</p></div>
        <div className="rounded border border-border p-1.5">
          <p className={`font-mono font-bold text-sm ${totalPlanned > 0 ? (totalReported / totalPlanned > 1 ? "text-red-400" : totalReported / totalPlanned > 0.8 ? "text-amber-400" : "text-emerald-400") : ""}`}>
            {totalPlanned > 0 ? `${Math.round(totalReported / totalPlanned * 100)}%` : "—"}
          </p>
          <p className="text-muted-foreground">{t("actTable.burn")}</p>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto border border-border rounded-lg">
        <Table>
          <TableHeader>
            <TableRow className="text-[9px]">
              <TableHead className="w-6"></TableHead>
              <TableHead>{t("actTable.section")}</TableHead>
              <TableHead>{t("actTable.activity")}</TableHead>
              <TableHead className="text-right">{t("actTable.planned")}</TableHead>
              <TableHead className="text-right">{t("actTable.draft")}</TableHead>
              <TableHead className="text-right">{t("actTable.approved")}</TableHead>
              <TableHead className="text-right">{t("actTable.total")}</TableHead>
              <TableHead className="text-right">{t("actTable.clean")}</TableHead>
              <TableHead className="text-right">{t("actTable.loaded")}</TableHead>
              <TableHead className="text-right">{t("actTable.sub")}</TableHead>
              <TableHead className="text-right">%</TableHead>
              <TableHead>{t("actTable.label")}</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {activities.map((a, i) => {
              const dot = STATUS_DOT[a.risk_status] || STATUS_DOT.green;
              const burnColor = a.risk_status === "red" ? "text-red-400" : a.risk_status === "yellow" ? "text-amber-400" : "text-emerald-400";
              // Variance vs subcontractor
              const subPrice = a.subcontractor_price || 0;
              const variance = subPrice > 0 ? round2(a.labor_cost_with_overhead - subPrice) : null;
              return (
                <TableRow key={i} className="text-xs" data-testid={`act-row-${i}`}>
                  <TableCell><span className={`w-2.5 h-2.5 rounded-full inline-block ${dot}`} /></TableCell>
                  <TableCell className="text-muted-foreground max-w-[80px] truncate">{a.category}</TableCell>
                  <TableCell className="font-medium max-w-[150px] truncate">{a.activity_name}</TableCell>
                  <TableCell className="text-right font-mono">{a.planned_hours > 0 ? a.planned_hours.toFixed(0) : "—"}</TableCell>
                  <TableCell className="text-right font-mono text-blue-400">{a.draft_hours > 0 ? a.draft_hours.toFixed(0) : "—"}</TableCell>
                  <TableCell className="text-right font-mono text-emerald-400">{a.approved_hours > 0 ? a.approved_hours.toFixed(0) : "—"}</TableCell>
                  <TableCell className="text-right font-mono font-bold">
                    {a.total_reported_hours > 0 ? (
                      <button onClick={() => setDrillSmr(a.activity_name)} className={`${burnColor} hover:underline`}>
                        {a.total_reported_hours.toFixed(0)} ч.
                      </button>
                    ) : "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono">{fmt(a.clean_labor_cost)}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(a.labor_cost_with_overhead)}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {subPrice > 0 ? fmt(subPrice) : "—"}
                    {variance !== null && (
                      <span className={`block text-[8px] ${variance > 0 ? "text-red-400" : "text-emerald-400"}`}>
                        {variance > 0 ? "+" : ""}{fmt(variance)}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right"><span className={`font-mono font-bold ${burnColor}`}>{a.burn_pct_total > 0 ? `${a.burn_pct_total.toFixed(0)}%` : "—"}</span></TableCell>
                  <TableCell>
                    {a.is_extra && <Badge variant="outline" className="text-[8px] bg-amber-500/10 text-amber-400">{t("actTable.extraLabel")}</Badge>}
                    {!a.planned_hours && !a.is_extra && <Badge variant="outline" className="text-[8px] text-muted-foreground">{t("actTable.noBudget")}</Badge>}
                  </TableCell>
                  <TableCell>
                    {a.total_reported_hours > 0 && (
                      <Button variant="ghost" size="sm" className="h-5 text-[9px] px-1" onClick={() => setDrillSmr(a.activity_name)}>
                        <Eye className="w-3 h-3" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Drill-down */}
      <ActivityReportsList projectId={projectId} smrType={drillSmr} open={!!drillSmr} onClose={() => setDrillSmr(null)} />
    </div>
  );
}

function round2(n) { return Math.round(n * 100) / 100; }
