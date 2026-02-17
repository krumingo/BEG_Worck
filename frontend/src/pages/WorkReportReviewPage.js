import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDate } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  CheckCircle2,
  XCircle,
  FileText,
  Clock,
  Loader2,
  Eye,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Submitted: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Approved: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Rejected: "bg-red-500/20 text-red-400 border-red-500/30",
};

export default function WorkReportReviewPage() {
  const { t } = useTranslation();
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState("all");
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split("T")[0]);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);

  // Detail dialog
  const [detailReport, setDetailReport] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);

  // Reject dialog
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectTarget, setRejectTarget] = useState(null);
  const [rejectReason, setRejectReason] = useState("");
  const [acting, setActing] = useState(false);

  const fetchProjects = useCallback(async () => {
    try {
      const res = await API.get("/projects?status=Active");
      setProjects(res.data);
    } catch (err) { console.error(err); }
  }, []);

  const fetchReports = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ date: selectedDate });
      if (selectedProject !== "all") params.append("project_id", selectedProject);
      const res = await API.get(`/work-reports/project-day?${params.toString()}`);
      setReports(res.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [selectedProject, selectedDate]);

  useEffect(() => { fetchProjects(); }, [fetchProjects]);
  useEffect(() => { fetchReports(); }, [fetchReports]);

  const handleApprove = async (reportId) => {
    setActing(true);
    try {
      await API.post(`/work-reports/${reportId}/approve`);
      await fetchReports();
    } catch (err) { alert(err.response?.data?.detail || t("toast.errorOccurred")); }
    finally { setActing(false); }
  };

  const openReject = (report) => {
    setRejectTarget(report);
    setRejectReason("");
    setRejectOpen(true);
  };

  const handleReject = async () => {
    if (!rejectTarget || !rejectReason) return;
    setActing(true);
    try {
      await API.post(`/work-reports/${rejectTarget.id}/reject`, { reason: rejectReason });
      setRejectOpen(false);
      await fetchReports();
    } catch (err) { alert(err.response?.data?.detail || t("toast.errorOccurred")); }
    finally { setActing(false); }
  };

  const openDetail = (report) => {
    setDetailReport(report);
    setDetailOpen(true);
  };

  const submitted = reports.filter((r) => r.status === "Submitted").length;
  const approved = reports.filter((r) => r.status === "Approved").length;

  return (
    <div className="p-8 max-w-[1200px]" data-testid="report-review-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Review Reports</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {reports.length} reports &middot; {submitted} pending &middot; {approved} approved
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6" data-testid="report-filters">
        <Input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="w-[180px] bg-card"
          data-testid="report-date-filter"
        />
        <Select value={selectedProject} onValueChange={setSelectedProject}>
          <SelectTrigger className="w-[280px] bg-card" data-testid="report-project-filter">
            <SelectValue placeholder="Filter project..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Projects</SelectItem>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="reports-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">User</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Project</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Lines</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Hours</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {reports.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-16">
                    <FileText className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
                    <p className="text-muted-foreground">No reports for this date</p>
                  </TableCell>
                </TableRow>
              ) : (
                reports.map((r) => (
                  <TableRow key={r.id} className="table-row-hover" data-testid={`report-row-${r.id}`}>
                    <TableCell>
                      <div>
                        <p className="font-medium text-foreground">{r.user_name}</p>
                        <p className="text-xs text-muted-foreground">{r.user_email}</p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="font-mono text-xs text-primary">{r.project_code}</span>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs ${STATUS_COLORS[r.status] || ""}`}>{r.status}</Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{r.lines?.length || 0}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Clock className="w-3 h-3 text-muted-foreground" />
                        <span className={`text-sm font-semibold ${r.total_hours > 8 ? "text-amber-400" : "text-foreground"}`}>{r.total_hours}h</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => openDetail(r)} data-testid={`view-report-${r.id}`}>
                          <Eye className="w-3.5 h-3.5" />
                        </Button>
                        {r.status === "Submitted" && (
                          <>
                            <Button size="sm" onClick={() => handleApprove(r.id)} disabled={acting} className="bg-emerald-600 hover:bg-emerald-700 h-8" data-testid={`approve-report-${r.id}`}>
                              <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Approve
                            </Button>
                            <Button size="sm" variant="destructive" onClick={() => openReject(r)} disabled={acting} className="h-8" data-testid={`reject-report-${r.id}`}>
                              <XCircle className="w-3.5 h-3.5 mr-1" /> Reject
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border max-h-[80vh] overflow-y-auto" data-testid="report-detail-dialog">
          <DialogHeader>
            <DialogTitle>Work Report — {detailReport?.user_name}</DialogTitle>
          </DialogHeader>
          {detailReport && (
            <div className="space-y-4 pt-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{detailReport.date} &middot; {detailReport.project_code}</span>
                <Badge variant="outline" className={`text-xs ${STATUS_COLORS[detailReport.status] || ""}`}>{detailReport.status}</Badge>
              </div>
              {detailReport.summary_note && (
                <div className="p-3 rounded-lg bg-background border border-border">
                  <p className="text-xs text-muted-foreground mb-1">Summary</p>
                  <p className="text-sm text-foreground">{detailReport.summary_note}</p>
                </div>
              )}
              <div>
                <p className="text-xs text-muted-foreground mb-2">Activities ({detailReport.lines?.length || 0})</p>
                {(detailReport.lines || []).map((line, i) => (
                  <div key={i} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                    <div className="flex-1">
                      <p className="text-sm text-foreground">{line.activity_name}</p>
                      {line.note && <p className="text-xs text-muted-foreground">{line.note}</p>}
                    </div>
                    <span className="text-sm font-semibold text-foreground ml-4">{line.hours}h</span>
                  </div>
                ))}
                <div className="flex items-center justify-between pt-3 mt-2 border-t border-border">
                  <span className="text-sm font-medium text-muted-foreground">Total</span>
                  <span className="text-lg font-bold text-foreground">{detailReport.total_hours}h</span>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Reject Dialog */}
      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="reject-dialog">
          <DialogHeader>
            <DialogTitle>Reject Report</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <p className="text-sm text-muted-foreground">Rejecting report for {rejectTarget?.user_name}</p>
            <div className="space-y-2">
              <label className="text-sm text-muted-foreground">Reason *</label>
              <Input value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="Enter reason for rejection..." className="bg-background" data-testid="reject-reason-input" />
            </div>
            <Button onClick={handleReject} disabled={acting || !rejectReason} variant="destructive" className="w-full" data-testid="reject-confirm-button">
              {acting && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              Reject Report
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
