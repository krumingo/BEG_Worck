import { useState, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import ProjectContextBar from "@/components/ProjectContextBar";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Clock, Users, FileText, AlertTriangle, Filter, ChevronLeft,
  ChevronRight, ArrowUpDown, MapPin, User, Check, X as XIcon,
  Briefcase, Eye, CalendarDays, List,
} from "lucide-react";
import WeeklyMatrixSection from "@/components/WeeklyMatrixSection";
import EmployeeDossierSection from "@/components/EmployeeDossierSection";
import useBulkSelection from "@/hooks/useBulkSelection";
import { toast } from "sonner";
import OvertimeOverrideModal from "@/components/OvertimeOverrideModal";

const STATUS_BADGE = {
  DRAFT:     { label: "Чернова",  cls: "bg-gray-500/15 text-gray-400 border-gray-500/30" },
  SUBMITTED: { label: "Подаден",  cls: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  APPROVED:  { label: "Одобрен",  cls: "bg-green-700/30 text-green-300 border-green-600/40", icon: Check },
  REJECTED:  { label: "Отхвърлен", cls: "bg-red-500/15 text-red-400 border-red-500/30" },
};

const PAYROLL_BADGE = {
  none:           { label: "—",          cls: "text-muted-foreground" },
  eligible:       { label: "За заплата", cls: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  batched:        { label: "В пакет",    cls: "bg-violet-500/15 text-violet-400 border-violet-500/30" },
  paid:           { label: "Платен",     cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
  partially_paid: { label: "Частично",   cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
  carry_forward:  { label: "Пренесен",   cls: "bg-orange-500/15 text-orange-400 border-orange-500/30" },
};

export default function AllReportsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("all"); // all | weekly

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("date");
  const [sortDir, setSortDir] = useState("desc");
  const [detail, setDetail] = useState(null);
  const bulk = useBulkSelection();
  const [bulkLoading, setBulkLoading] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideBlocked, setOverrideBlocked] = useState([]);

  // URL params for deep-linking from PersonnelPanel
  const [searchParams] = useSearchParams();
  const urlProject = searchParams.get("project_id") || "";
  const urlStatus = searchParams.get("report_status") || "";
  const urlWorker = searchParams.get("worker_id") || "";

  // Filters
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 30);
    return d.toISOString().slice(0, 10);
  });
  const [dateTo, setDateTo] = useState(() => new Date().toISOString().slice(0, 10));
  const [fWorker, setFWorker] = useState(urlWorker);
  const [fProject, setFProject] = useState(urlProject);
  const [fSmr, setFSmr] = useState("");
  const [fStatus, setFStatus] = useState(urlStatus || "all");
  const [fOvertime, setFOvertime] = useState(false);
  const [showFilters, setShowFilters] = useState(!!(urlProject || urlStatus || urlWorker));

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        date_from: dateFrom, date_to: dateTo,
        page: String(page), page_size: "50",
        sort_by: sortBy, sort_dir: sortDir,
      });
      if (fWorker) params.set("worker_id", fWorker);
      if (fProject) params.set("project_id", fProject);
      if (fSmr) params.set("smr", fSmr);
      if (fStatus !== "all") params.set("report_status", fStatus);
      if (fOvertime) params.set("only_overtime", "true");
      const res = await API.get(`/all-reports?${params}`);
      setData(res.data);
    } catch { setData(null); }
    finally { setLoading(false); }
  }, [dateFrom, dateTo, page, sortBy, sortDir, fWorker, fProject, fSmr, fStatus, fOvertime]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortBy(col); setSortDir("desc"); }
    setPage(1);
  };

  const applyFilters = () => { setPage(1); setShowFilters(false); };
  const clearFilters = () => {
    setFWorker(""); setFProject(""); setFSmr(""); setFStatus("all"); setFOvertime(false);
    setPage(1); setShowFilters(false);
  };

  const SortHead = ({ col, children }) => (
    <TableHead
      className="text-[10px] cursor-pointer select-none hover:text-foreground whitespace-nowrap"
      onClick={() => toggleSort(col)}
    >
      <span className="flex items-center gap-1">
        {children}
        {sortBy === col && <ArrowUpDown className="w-2.5 h-2.5 text-primary" />}
      </span>
    </TableHead>
  );

  const s = data?.summary || {};
  const activeFilters = [fWorker, fProject, fSmr, fStatus !== "all" && fStatus, fOvertime].filter(Boolean).length;

  return (
    <div className="p-6 lg:p-8 max-w-[1400px]" data-testid="all-reports-page">
      <ProjectContextBar pageTitle="Отчети" />
      {/* Header + Tabs */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold">{t("allReports.pageTitle")}</h1>
          <p className="text-sm text-muted-foreground mt-0.5">{t("allReports.subtitle")}</p>
        </div>
      </div>

      {/* Internal Tabs */}
      <div className="flex items-center gap-1 mb-6 border-b border-border" data-testid="reports-tabs">
        <button
          onClick={() => setActiveTab("all")}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === "all" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          data-testid="tab-all"
        >
          <List className="w-3.5 h-3.5" />{t("allReports.tabAll")}
        </button>
        <button
          onClick={() => setActiveTab("weekly")}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === "weekly" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          data-testid="tab-weekly"
        >
          <CalendarDays className="w-3.5 h-3.5" />{t("allReports.tabWeekly")}
        </button>
        <button
          onClick={() => setActiveTab("dossier")}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === "dossier" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          data-testid="tab-dossier"
        >
          <User className="w-3.5 h-3.5" />{t("allReports.tabDossier")}
        </button>
      </div>

      {/* Weekly Matrix Tab */}
      {activeTab === "weekly" && <WeeklyMatrixSection />}

      {/* Dossier Tab */}
      {activeTab === "dossier" && <EmployeeDossierSection />}

      {/* All Reports Tab */}
      {activeTab === "all" && (
      <>
      {/* Filter button */}
      <div className="flex justify-end mb-4">
        <Button variant="outline" size="sm" onClick={() => setShowFilters(!showFilters)} className="gap-1.5" data-testid="toggle-filters-btn">
          <Filter className="w-3.5 h-3.5" />
          {t("allReports.filters")}
          {activeFilters > 0 && <Badge className="bg-primary text-primary-foreground text-[9px] px-1.5">{activeFilters}</Badge>}
        </Button>
      </div>

      {/* Filters Panel */}
      {showFilters && (
        <div className="rounded-xl border border-border bg-card p-4 mb-4 grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="filters-panel">
          <div>
            <label className="text-[10px] text-muted-foreground">{t("allReports.dateFrom")}</label>
            <Input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="h-9 text-xs" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground">{t("allReports.dateTo")}</label>
            <Input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="h-9 text-xs" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground">{t("allReports.smrFilter")}</label>
            <Input value={fSmr} onChange={e => setFSmr(e.target.value)} placeholder="Мазилка..." className="h-9 text-xs" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground">{t("allReports.statusFilter")}</label>
            <Select value={fStatus} onValueChange={setFStatus}>
              <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("allReports.allStatuses")}</SelectItem>
                <SelectItem value="DRAFT">{t("allReports.draft")}</SelectItem>
                <SelectItem value="SUBMITTED">{t("allReports.submitted")}</SelectItem>
                <SelectItem value="APPROVED">{t("allReports.approved")}</SelectItem>
                <SelectItem value="REJECTED">{t("allReports.rejected")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <label className="flex items-center gap-2 col-span-2 md:col-span-1 text-xs cursor-pointer">
            <input type="checkbox" checked={fOvertime} onChange={e => setFOvertime(e.target.checked)} className="rounded" />
            {t("allReports.onlyOvertime")}
          </label>
          <div className="col-span-2 md:col-span-3 flex items-end gap-2 justify-end">
            <Button variant="ghost" size="sm" onClick={clearFilters}>{t("allReports.clearFilters")}</Button>
            <Button size="sm" onClick={applyFilters}>{t("allReports.apply")}</Button>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4" data-testid="reports-summary">
          <div className="rounded-lg bg-card border border-border p-3 text-center">
            <p className="text-xl font-bold font-mono">{s.total_hours}<span className="text-sm text-muted-foreground">ч</span></p>
            <p className="text-[10px] text-muted-foreground">{t("allReports.totalHours")}</p>
          </div>
          <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3 text-center">
            <p className="text-xl font-bold font-mono text-emerald-400">{s.normal_hours}<span className="text-sm text-emerald-400/60">ч</span></p>
            <p className="text-[10px] text-emerald-400/70">{t("allReports.normalHours")}</p>
          </div>
          <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3 text-center">
            <p className="text-xl font-bold font-mono text-amber-400">{s.overtime_hours}<span className="text-sm text-amber-400/60">ч</span></p>
            <p className="text-[10px] text-amber-400/70">{t("allReports.overtimeHours")}</p>
          </div>
          <div className="rounded-lg bg-card border border-border p-3 text-center">
            <p className="text-xl font-bold font-mono text-primary">{s.total_value?.toFixed(0)}<span className="text-sm text-muted-foreground"> EUR</span></p>
            <p className="text-[10px] text-muted-foreground">{t("allReports.laborValue")}</p>
          </div>
        </div>
      )}

      {/* Status breakdown chips */}
      {data && s.by_status && (
        <div className="flex flex-wrap gap-2 mb-4" data-testid="status-breakdown">
          {Object.entries(s.by_status).map(([st, cnt]) => {
            const cfg = STATUS_BADGE[st] || { label: st, cls: "bg-muted text-muted-foreground" };
            return <Badge key={st} variant="outline" className={`text-[10px] gap-1 ${cfg.cls}`}>{cfg.label}: {cnt}</Badge>;
          })}
        </div>
      )}

      {/* Bulk action bar */}
      {bulk.count > 0 && (
        <div className="flex items-center gap-3 p-3 bg-primary/5 border border-primary/20 rounded-lg mb-3" data-testid="bulk-bar">
          <span className="text-sm font-medium">Маркирани: {bulk.count}</span>
          <Button size="sm" className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700" disabled={bulkLoading} onClick={async () => {
            setBulkLoading(true);
            try {
              const res = await API.post("/daily-reports/bulk-approve", { report_ids: [...bulk.selectedIds] });
              const d = res.data;
              if (d.succeeded?.length) toast.success(`${d.succeeded.length} одобрени`);
              if (d.blocked_for_override?.length) {
                setOverrideBlocked(d.blocked_for_override);
                setOverrideOpen(true);
              }
              if (d.failed?.length) toast.error(`${d.failed.length} неуспешни`);
              if (!d.blocked_for_override?.length) bulk.clear();
              fetchData();
            } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
            finally { setBulkLoading(false); }
          }}>Одобри ({bulk.count})</Button>
          <Button size="sm" variant="outline" className="h-7 text-xs text-red-400 border-red-500/30" disabled={bulkLoading} onClick={async () => {
            const reason = window.prompt("Причина за отхвърляне:");
            if (!reason) return;
            setBulkLoading(true);
            try {
              const res = await API.post("/daily-reports/bulk-reject", { report_ids: [...bulk.selectedIds], reason });
              toast.success(`${res.data.succeeded?.length || 0} отхвърлени`);
              bulk.clear(); fetchData();
            } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
            finally { setBulkLoading(false); }
          }}>Отхвърли ({bulk.count})</Button>
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={bulk.clear}>Изчисти</Button>
        </div>
      )}

      {/* Table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="reports-table">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8"><input type="checkbox" checked={bulk.count > 0 && data?.items?.length > 0 && bulk.count === data.items.length} onChange={() => bulk.toggleAll((data?.items || []).map(r => r.id))} className="rounded" /></TableHead>
                <SortHead col="date">{t("allReports.colDate")}</SortHead>
                <SortHead col="worker">{t("allReports.colWorker")}</SortHead>
                <TableHead className="text-[10px]">{t("allReports.colSite")}</TableHead>
                <TableHead className="text-[10px]">{t("allReports.colSmr")}</TableHead>
                <SortHead col="hours">{t("allReports.colHours")}</SortHead>
                <TableHead className="text-[10px]">{t("allReports.colNormal")}</TableHead>
                <TableHead className="text-[10px]">{t("allReports.colOvertime")}</TableHead>
                <TableHead className="text-[10px]">{t("allReports.colRate")}</TableHead>
                <SortHead col="value">{t("allReports.colValue")}</SortHead>
                <SortHead col="status">{t("allReports.colStatus")}</SortHead>
                <TableHead className="text-[10px]">{t("allReports.colPayroll")}</TableHead>
                <TableHead className="text-[10px] w-[50px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={12} className="text-center py-12 text-muted-foreground">{t("common.loading")}</TableCell></TableRow>
              ) : !data?.items?.length ? (
                <TableRow><TableCell colSpan={12} className="text-center py-12 text-muted-foreground">{t("allReports.noData")}</TableCell></TableRow>
              ) : data.items.map(r => {
                const stCfg = STATUS_BADGE[r.report_status] || { label: r.report_status, cls: "bg-muted text-muted-foreground" };
                const payCfg = PAYROLL_BADGE[r.payroll_status] || PAYROLL_BADGE.none;
                return (
                  <TableRow key={r.id} className={`hover:bg-muted/20 ${bulk.isSelected(r.id) ? "bg-primary/5" : ""}`} data-testid={`report-row-${r.id}`}>
                    <TableCell><input type="checkbox" checked={bulk.isSelected(r.id)} onChange={() => bulk.toggleId(r.id)} className="rounded" /></TableCell>
                    <TableCell className="text-xs font-mono whitespace-nowrap">{r.date}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 cursor-pointer" onClick={() => navigate(`/employees/${r.worker_id}?tab=reports`)}>
                        {r.worker_avatar ? (
                          <img src={`${process.env.REACT_APP_BACKEND_URL}${r.worker_avatar}`} className="w-6 h-6 rounded-full object-cover" alt="" />
                        ) : (
                          <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center text-[8px] font-bold text-primary">
                            {(r.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}
                          </div>
                        )}
                        <span className="text-xs truncate max-w-[120px] hover:text-primary transition-colors">{r.worker_name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      {r.site_name ? (
                        <button onClick={() => r.project_id && navigate(`/projects/${r.project_id}`)} className="text-[10px] text-primary hover:underline flex items-center gap-0.5 truncate max-w-[100px]">
                          <MapPin className="w-2.5 h-2.5 flex-shrink-0" />{r.site_name}
                        </button>
                      ) : <span className="text-[10px] text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="text-xs truncate max-w-[120px]">{r.smr_type || "—"}</TableCell>
                    <TableCell className="text-xs font-mono font-bold">
                      {r.hours}
                      {r.day_warning_level === "critical" && <span className="ml-1 text-red-400" title={r.day_warnings?.join("; ")}>!</span>}
                      {r.day_warning_level === "warning" && <span className="ml-1 text-amber-400" title={r.day_warnings?.join("; ")}>*</span>}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-emerald-400">{r.normal_hours}</TableCell>
                    <TableCell className={`text-xs font-mono ${r.overtime_hours > 0 ? "text-amber-400 font-bold" : "text-muted-foreground"}`}>
                      {r.overtime_hours > 0 ? `+${r.overtime_hours}` : "—"}
                      {r.day_total_hours > 0 && r.day_total_hours !== r.hours && (
                        <span className="text-[9px] text-muted-foreground ml-1">({r.day_total_hours}ч/ден)</span>
                      )}
                    </TableCell>
                    <TableCell className="text-[10px] font-mono text-muted-foreground">{r.hourly_rate > 0 ? `${r.hourly_rate}` : "—"}</TableCell>
                    <TableCell>
                      {r.labor_value > 0 ? (
                        <div>
                          <span title={r.earned_formula || ""} className="text-xs font-mono text-primary cursor-help border-b border-dotted border-muted-foreground">{r.labor_value.toFixed(0)}</span>
                          {r.earned_formula && <div className="text-[9px] text-muted-foreground mt-0.5">{r.earned_formula}</div>}
                        </div>
                      ) : <span className="text-xs text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell><Badge variant="outline" className={`text-[9px] ${stCfg.cls}`}>{stCfg.icon && <stCfg.icon className="w-2.5 h-2.5 mr-0.5" />}{stCfg.label}</Badge></TableCell>
                    <TableCell>{payCfg.label !== "—" ? <Badge variant="outline" className={`text-[9px] ${payCfg.cls}`}>{payCfg.label}</Badge> : <span className="text-[10px] text-muted-foreground">—</span>}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setDetail(r)} data-testid={`detail-btn-${r.id}`}>
                        <Eye className="w-3.5 h-3.5" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-border" data-testid="pagination">
            <span className="text-xs text-muted-foreground">{t("allReports.showing")} {((page - 1) * 50) + 1}–{Math.min(page * 50, data.total)} / {data.total}</span>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="h-7 w-7 p-0"><ChevronLeft className="w-3.5 h-3.5" /></Button>
              <span className="text-xs flex items-center px-2">{page}/{data.total_pages}</span>
              <Button variant="outline" size="sm" disabled={page >= data.total_pages} onClick={() => setPage(p => p + 1)} className="h-7 w-7 p-0"><ChevronRight className="w-3.5 h-3.5" /></Button>
            </div>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      <Dialog open={!!detail} onOpenChange={() => setDetail(null)}>
        <DialogContent className="max-w-lg" data-testid="report-detail-modal">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="w-4 h-4" />{t("allReports.detailTitle")}
            </DialogTitle>
          </DialogHeader>
          {detail && (
            <div className="space-y-4">
              {/* Worker */}
              <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/30">
                {detail.worker_avatar ? (
                  <img src={`${process.env.REACT_APP_BACKEND_URL}${detail.worker_avatar}`} className="w-10 h-10 rounded-full object-cover" alt="" />
                ) : (
                  <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center text-sm font-bold text-primary">
                    {(detail.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}
                  </div>
                )}
                <div>
                  <p className="font-semibold">{detail.worker_name}</p>
                  <p className="text-xs text-muted-foreground">{detail.position || detail.pay_type || "—"}</p>
                </div>
              </div>

              {/* Grid */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <DetailRow label={t("allReports.colDate")} value={detail.date} />
                <DetailRow label={t("allReports.colSite")} value={detail.site_name || "—"} link={detail.project_id ? `/projects/${detail.project_id}` : null} />
                <DetailRow label={t("allReports.colSmr")} value={detail.smr_type || "—"} />
                <DetailRow label={t("allReports.colHours")} value={`${detail.hours}ч`} bold />
                <DetailRow label={t("allReports.colNormal")} value={`${detail.normal_hours}ч`} color="text-emerald-400" />
                <DetailRow label={t("allReports.colOvertime")} value={detail.overtime_hours > 0 ? `+${detail.overtime_hours}ч` : "—"} color={detail.overtime_hours > 0 ? "text-amber-400" : ""} />
                {detail.day_total_hours > 0 && detail.day_total_hours !== detail.hours && (
                  <DetailRow label="Общо за деня" value={`${detail.day_total_hours}ч (${detail.day_normal_hours}ч норм. + ${detail.day_overtime_hours}ч извънр.)`} color={detail.day_warning_level === "critical" ? "text-red-400" : detail.day_warning_level === "warning" ? "text-amber-400" : ""} />
                )}
                {detail.day_warnings?.length > 0 && (
                  <div className="col-span-2 mt-1 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30">
                    {detail.day_warnings.map((w, i) => <p key={i} className="text-[11px] text-amber-400">{w}</p>)}
                  </div>
                )}
                <DetailRow label={t("allReports.colRate")} value={detail.hourly_rate > 0 ? `${detail.hourly_rate} EUR/ч` : "—"} />
                <DetailRow label={t("allReports.colValue")} value={detail.labor_value > 0 ? `${detail.labor_value.toFixed(2)} EUR` : "—"} color="text-primary" bold />
                {detail.earned_formula && (() => {
                  const payTypeLabels = {Hourly: "Часово", Daily: "Надница", Monthly: "Месечно", Akord: "Акорд", mixed: "Смесено"};
                  const payTypeLabel = payTypeLabels[detail.pay_type || detail.rate_type] || detail.pay_type || "—";
                  return (
                    <div className="col-span-2 mt-1 px-3 py-2 rounded-lg bg-primary/5 border border-primary/20">
                      <p className="text-[10px] text-muted-foreground mb-1">Как е изчислена сумата</p>
                      <p className="text-xs font-mono text-primary mb-2">{detail.earned_formula}</p>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div><span className="text-muted-foreground">Тип: </span>{payTypeLabel}</div>
                        <div><span className="text-muted-foreground">Ставка: </span>{detail.hourly_rate || detail.hourly_rate_at_date || "—"} EUR/ч</div>
                        <div><span className="text-muted-foreground">Обект: </span>{detail.site_name || detail.project_name || "—"}</div>
                        <div><span className="text-muted-foreground">Дата: </span>{detail.date || "—"}</div>
                      </div>
                    </div>
                  );
                })()}
              </div>

              {/* Status row */}
              <div className="flex items-center gap-3 flex-wrap">
                <div>
                  <p className="text-[10px] text-muted-foreground mb-0.5">{t("allReports.colStatus")}</p>
                  {(() => {
                    const cfg = STATUS_BADGE[detail.report_status] || {};
                    const Icon = cfg.icon;
                    return (
                      <Badge variant="outline" className={`text-[10px] ${cfg.cls || ""}`}>
                        {Icon && <Icon className="w-2.5 h-2.5 mr-0.5" />}
                        {cfg.label || detail.report_status}
                      </Badge>
                    );
                  })()}
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground mb-0.5">{t("allReports.colPayroll")}</p>
                  <Badge variant="outline" className={`text-[10px] ${(PAYROLL_BADGE[detail.payroll_status] || {}).cls || ""}`}>
                    {(PAYROLL_BADGE[detail.payroll_status] || PAYROLL_BADGE.none).label}
                  </Badge>
                </div>
                {detail.slip_number && (
                  <div>
                    <p className="text-[10px] text-muted-foreground mb-0.5">{t("allReports.slipNumber")}</p>
                    <span className="text-xs font-mono">#{detail.slip_number}</span>
                  </div>
                )}
              </div>

              {/* Audit */}
              <div className="grid grid-cols-2 gap-3 text-sm border-t border-border pt-3">
                <DetailRow label={t("allReports.submittedBy")} value={detail.submitted_by_name || "—"} />
                <DetailRow label={t("allReports.approvedBy")} value={detail.approved_by_name || "—"} />
                {detail.entered_by_admin && (
                  <div className="col-span-2">
                    <Badge variant="outline" className="text-[9px] bg-violet-500/15 text-violet-400 border-violet-500/30">{t("allReports.adminEntry")}</Badge>
                  </div>
                )}
              </div>

              {/* Notes */}
              {detail.notes && (
                <div className="border-t border-border pt-3">
                  <p className="text-[10px] text-muted-foreground mb-1">{t("allReports.notes")}</p>
                  <p className="text-sm">{detail.notes}</p>
                </div>
              )}

              {/* Value disclaimer */}
              <div className="rounded-lg bg-muted/30 p-3 text-[10px] text-muted-foreground">
                {t("allReports.valueDisclaimer")}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      </>
      )}

      <OvertimeOverrideModal
        open={overrideOpen}
        onOpenChange={setOverrideOpen}
        blocked={overrideBlocked}
        onSubmit={async (overrides) => {
          const ids = Object.keys(overrides);
          const res = await API.post("/daily-reports/bulk-approve", { report_ids: ids, overrides });
          const d = res.data;
          if (d.succeeded?.length) toast.success(`${d.succeeded.length} одобрени с override`);
          if (d.failed?.length) toast.error(`${d.failed.length} неуспешни: ${d.failed.map(f=>f.reason).join(", ")}`);
          setOverrideOpen(false);
          setOverrideBlocked([]);
          bulk.clear();
          fetchData();
        }}
      />
    </div>
  );
}

function DetailRow({ label, value, bold, color, link }) {
  const navigate = useNavigate();
  return (
    <div>
      <p className="text-[10px] text-muted-foreground">{label}</p>
      {link ? (
        <button onClick={() => navigate(link)} className={`text-sm text-primary hover:underline ${bold ? "font-bold" : ""}`}>{value}</button>
      ) : (
        <p className={`text-sm ${bold ? "font-bold" : ""} ${color || ""}`}>{value}</p>
      )}
    </div>
  );
}
