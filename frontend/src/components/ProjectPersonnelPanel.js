/**
 * ProjectPersonnelPanel — Operational personnel view per project.
 * Reads from centralized reports personnel projection.
 * Shows: today status, draft/approved counts, amounts, links to reports.
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Users, Loader2, Check, Clock, FileText, AlertTriangle, Eye,
} from "lucide-react";
import ActivityReportsList from "@/components/ActivityReportsList";

function fmt(n) { return n == null || n === 0 ? "—" : n.toLocaleString("bg-BG", { maximumFractionDigits: 0 }); }

const TODAY_STATUS = {
  has_approved: { label: "Одобрен", color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30", dot: "bg-emerald-500" },
  has_draft: { label: "Чернова", color: "bg-blue-500/20 text-blue-400 border-blue-500/30", dot: "bg-blue-500" },
  present_no_report: { label: "Без отчет", color: "bg-amber-500/20 text-amber-400 border-amber-500/30", dot: "bg-amber-500" },
  not_present: { label: "Отсъства", color: "bg-zinc-500/20 text-zinc-400", dot: "bg-zinc-600" },
};

export default function ProjectPersonnelPanel({ projectId }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [drillWorker, setDrillWorker] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/centralized-reports/personnel`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  const personnel = data?.personnel || [];

  // Compute today status for each worker
  const enriched = personnel.map(p => {
    let today_status = "not_present";
    if (p.today_present) {
      if (p.approved_reports_count > 0) today_status = "has_approved";
      else if (p.draft_reports_count > 0) today_status = "has_draft";
      else today_status = "present_no_report";
    }
    return { ...p, today_status };
  });

  // Summary
  const total = enriched.length;
  const present = enriched.filter(p => p.today_present).length;
  const withDrafts = enriched.filter(p => p.draft_reports_count > 0).length;
  const withApproved = enriched.filter(p => p.approved_reports_count > 0).length;
  const totalClean = enriched.reduce((s, p) => s + (p.clean_amount || 0), 0);
  const totalLoaded = enriched.reduce((s, p) => s + (p.total_amount || 0), 0);
  const missingRateCount = enriched.filter(p => p.missing_rate).length;

  return (
    <div className="space-y-4" data-testid="project-personnel-panel">
      {/* Summary cards */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-2 text-center text-xs">
        <div className="rounded-lg border border-border p-2">
          <p className="text-lg font-bold">{total}</p>
          <p className="text-muted-foreground">{t("personnelPanel.total")}</p>
        </div>
        <div className="rounded-lg border border-border p-2">
          <p className="text-lg font-bold text-emerald-400">{present}</p>
          <p className="text-muted-foreground">{t("personnelPanel.today")}</p>
        </div>
        <button onClick={() => navigate(`/all-reports?project_id=${projectId}&report_status=DRAFT&returnTo=/projects/${projectId}&returnTab=team`)} className="rounded-lg border border-blue-500/30 p-2 hover:bg-blue-500/10 transition-colors" data-testid="link-drafts">
          <p className="text-lg font-bold text-blue-400">{withDrafts}</p>
          <p className="text-muted-foreground">{t("personnelPanel.withDrafts")}</p>
        </button>
        <button onClick={() => navigate(`/all-reports?project_id=${projectId}&report_status=APPROVED&returnTo=/projects/${projectId}&returnTab=team`)} className="rounded-lg border border-emerald-500/30 p-2 hover:bg-emerald-500/10 transition-colors" data-testid="link-approved">
          <p className="text-lg font-bold text-emerald-400">{withApproved}</p>
          <p className="text-muted-foreground">{t("personnelPanel.withApproved")}</p>
        </button>
        <button onClick={() => navigate(`/all-reports?project_id=${projectId}&returnTo=/projects/${projectId}&returnTab=team`)} className="rounded-lg border border-border p-2 hover:bg-primary/10 transition-colors" data-testid="link-clean">
          <p className="text-lg font-bold font-mono">{fmt(totalClean)}</p>
          <p className="text-muted-foreground">{t("personnelPanel.cleanLabor")}</p>
        </button>
        <div className="rounded-lg border border-border p-2">
          <p className="text-lg font-bold font-mono">{fmt(totalLoaded)}</p>
          <p className="text-muted-foreground">{t("personnelPanel.loadedLabor")}</p>
        </div>
      </div>

      {/* Warnings */}
      {missingRateCount > 0 && (
        <div className="flex items-center gap-2 text-xs text-amber-400">
          <AlertTriangle className="w-3 h-3" /> {missingRateCount} {t("personnelPanel.missingRate")}
        </div>
      )}

      {/* Personnel table */}
      {enriched.length === 0 ? (
        <p className="text-center text-muted-foreground py-6 text-sm">{t("personnelPanel.noWorkers")}</p>
      ) : (
        <div className="overflow-x-auto border border-border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow className="text-[10px]">
                <TableHead>{t("personnelPanel.worker")}</TableHead>
                <TableHead className="text-center">{t("personnelPanel.todayStatus")}</TableHead>
                <TableHead className="text-right">{t("personnelPanel.drafts")}</TableHead>
                <TableHead className="text-right">{t("personnelPanel.approved")}</TableHead>
                <TableHead className="text-right">{t("personnelPanel.hours")}</TableHead>
                <TableHead className="text-right">{t("personnelPanel.clean")}</TableHead>
                <TableHead className="text-right">{t("personnelPanel.loaded")}</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {enriched.map((p, i) => {
                const st = TODAY_STATUS[p.today_status] || TODAY_STATUS.not_present;
                return (
                  <TableRow key={i} className="text-xs">
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[10px] font-bold text-primary">
                          {(p.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}
                        </div>
                        <div>
                          <span className="font-medium">{p.worker_name}</span>
                          {p.missing_rate && <Badge variant="outline" className="ml-1 text-[7px] text-red-400 border-red-400/30">{t("personnelPanel.noRate")}</Badge>}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-center">
                      <Badge variant="outline" className={`text-[9px] ${st.color}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${st.dot} inline-block mr-1`} />
                        {st.label}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-blue-400">
                      {p.draft_reports_count > 0 ? (
                        <button onClick={() => navigate(`/all-reports?project_id=${projectId}&report_status=DRAFT&worker_id=${p.worker_id}&returnTo=/projects/${projectId}&returnTab=team`)} className="hover:underline">{p.draft_reports_count}</button>
                      ) : "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono text-emerald-400">
                      {p.approved_reports_count > 0 ? (
                        <button onClick={() => navigate(`/all-reports?project_id=${projectId}&report_status=APPROVED&worker_id=${p.worker_id}&returnTo=/projects/${projectId}&returnTab=team`)} className="hover:underline">{p.approved_reports_count}</button>
                      ) : "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono">{p.total_hours > 0 ? p.total_hours.toFixed(0) : "—"}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(p.clean_amount)}</TableCell>
                    <TableCell className="text-right font-mono font-bold">{fmt(p.total_amount)}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={() => setDrillWorker(p.worker_name)} data-testid={`view-reports-${i}`}>
                        <Eye className="w-3 h-3 mr-1" /> {t("personnelPanel.viewReports")}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Drill-down to worker reports (reuses ActivityReportsList as filter by worker name) */}
      {drillWorker && (
        <ActivityReportsList
          projectId={projectId}
          smrType={drillWorker}
          open={true}
          onClose={() => setDrillWorker(null)}
        />
      )}
    </div>
  );
}
