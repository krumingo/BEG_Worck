/**
 * ActivityReportsList — Level 2: list of reports for a specific activity.
 * Shows worker, date, hours, cost, rate, slip, status.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Loader2, ArrowLeft, FileText } from "lucide-react";
import WorkerDayDetail from "@/components/WorkerDayDetail";

const STATUS_BADGE = {
  APPROVED: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Approved: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Draft: "bg-slate-100 text-slate-600",
  SUBMITTED: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Submitted: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  REJECTED: "bg-red-500/20 text-red-400 border-red-500/30",
};

export default function ActivityReportsList({ projectId, smrType, open, onClose }) {
  const { t } = useTranslation();
  const [reports, setReports] = useState([]);
  const [totals, setTotals] = useState({});
  const [loading, setLoading] = useState(true);
  const [fStatus, setFStatus] = useState("");
  const [fDateFrom, setFDateFrom] = useState("");
  const [fDateTo, setFDateTo] = useState("");

  // Level 3 detail
  const [detailSessionId, setDetailSessionId] = useState(null);

  const load = useCallback(async () => {
    if (!projectId || !smrType) return;
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (fStatus) p.append("status", fStatus);
      if (fDateFrom) p.append("date_from", fDateFrom);
      if (fDateTo) p.append("date_to", fDateTo);
      const res = await API.get(`/projects/${projectId}/activity-reports/${encodeURIComponent(smrType)}?${p}`);
      setReports(res.data.reports || []);
      setTotals(res.data.totals || {});
    } catch { setReports([]); }
    finally { setLoading(false); }
  }, [projectId, smrType, fStatus, fDateFrom, fDateTo]);

  useEffect(() => { if (open) load(); }, [open, load]);

  if (detailSessionId) {
    return (
      <Dialog open={true} onOpenChange={() => setDetailSessionId(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <WorkerDayDetail sessionId={detailSessionId} onBack={() => setDetailSessionId(null)} />
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-cyan-400" />
            {t("activityReports.title")}: {smrType}
          </DialogTitle>
        </DialogHeader>

        {/* Filters */}
        <div className="flex gap-2 flex-wrap mb-3">
          <Select value={fStatus || "all"} onValueChange={v => setFStatus(v === "all" ? "" : v)}>
            <SelectTrigger className="w-36 h-8 text-xs"><SelectValue placeholder={t("common.all")} /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("common.all")}</SelectItem>
              <SelectItem value="APPROVED">{t("activityReports.approved")}</SelectItem>
              <SelectItem value="Draft">{t("activityReports.draft")}</SelectItem>
              <SelectItem value="SUBMITTED">{t("activityReports.submitted")}</SelectItem>
            </SelectContent>
          </Select>
          <Input type="date" value={fDateFrom} onChange={e => setFDateFrom(e.target.value)} className="w-36 h-8 text-xs" />
          <Input type="date" value={fDateTo} onChange={e => setFDateTo(e.target.value)} className="w-36 h-8 text-xs" />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>
        ) : reports.length === 0 ? (
          <p className="text-center text-muted-foreground py-8 text-sm">{t("activityReports.noReports")}</p>
        ) : (
          <div className="overflow-x-auto border border-border rounded-lg">
            <Table>
              <TableHeader>
                <TableRow className="text-[10px]">
                  <TableHead>{t("activityReports.status")}</TableHead>
                  <TableHead>{t("activityReports.worker")}</TableHead>
                  <TableHead>{t("activityReports.date")}</TableHead>
                  <TableHead className="text-right">{t("activityReports.hours")}</TableHead>
                  <TableHead className="text-right">{t("activityReports.rate")}</TableHead>
                  <TableHead className="text-right">{t("activityReports.amount")}</TableHead>
                  <TableHead className="text-center">{t("activityReports.slip")}</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {reports.map((r, i) => (
                  <TableRow key={i} className="text-xs">
                    <TableCell><Badge variant="outline" className={`text-[9px] ${STATUS_BADGE[r.status] || ""}`}>{r.status}</Badge></TableCell>
                    <TableCell className="font-medium">{r.worker_name}</TableCell>
                    <TableCell>{r.date}</TableCell>
                    <TableCell className="text-right font-mono">{r.total_hours}</TableCell>
                    <TableCell className="text-right font-mono text-muted-foreground">{r.hourly_rate.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono font-bold">{r.total_cost.toFixed(2)}</TableCell>
                    <TableCell className="text-center">{r.slip_number || "—"}</TableCell>
                    <TableCell>
                      {r.session_ids?.length > 0 && (
                        <Button variant="ghost" size="sm" className="text-[10px] h-6" onClick={() => setDetailSessionId(r.session_ids[0])} data-testid={`detail-btn-${i}`}>
                          {t("activityReports.detail")}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {/* Summary */}
                <TableRow className="text-xs font-bold border-t-2">
                  <TableCell></TableCell>
                  <TableCell>{t("activitiesTable.totalRow")}</TableCell>
                  <TableCell>{totals.reports_count} {t("activityReports.records")}</TableCell>
                  <TableCell className="text-right font-mono">{totals.total_hours}</TableCell>
                  <TableCell></TableCell>
                  <TableCell className="text-right font-mono text-primary">{totals.total_cost?.toFixed(2)}</TableCell>
                  <TableCell></TableCell>
                  <TableCell></TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
