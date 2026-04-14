import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useActiveProject } from "@/contexts/ProjectContext";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  ArrowLeft, Users, CalendarDays, Building2, User, Phone, Mail, Hash, AlertTriangle, Sparkles, Pencil,
  FileText, Package, Wallet, Plus, Loader2, Eye, Shield, Clock,
  TrendingUp, Receipt, Boxes, Scale, UserPlus, BarChart3, Hammer, MapPin,
} from "lucide-react";
import ClientSelector from "@/components/ClientSelector";
import ClientPickerModal from "@/components/ClientPickerModal";
import ExtraWorkModal from "@/components/ExtraWorkModal";
import ExtraWorksDraftPanel from "@/components/ExtraWorksDraftPanel";
import ProjectMaterialLedger from "@/components/ProjectMaterialLedger";
import ProjectSMRTab from "@/components/ProjectSMRTab";
import LocationTreePanel from "@/components/LocationTreePanel";
import SMRLocationMap from "@/components/SMRLocationMap";
import ProjectInfoPanel from "@/components/ProjectInfoPanel";
import SMRGroupsPanel from "@/components/SMRGroupsPanel";
import ProjectPnLDashboard from "@/components/ProjectPnLDashboard";
import ExpectedActualPanel from "@/components/ExpectedActualPanel";
import MaterialWastePanel from "@/components/MaterialWastePanel";
import SubcontractorPerformancePanel from "@/components/SubcontractorPerformancePanel";
import ProjectActivitiesTable from "@/components/ProjectActivitiesTable";
import CentralizedActivitiesTable from "@/components/CentralizedActivitiesTable";
import { toast } from "sonner";
import CentralizedProjectView from "@/components/CentralizedProjectView";
import FinancialResultsCard from "@/components/FinancialResultsCard";
import ProjectPersonnelPanel from "@/components/ProjectPersonnelPanel";
import { ProjectPersonnelCard } from "@/components/DailyReportDialog";
import ObjectDailyReportTab from "@/components/ObjectDailyReportTab";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Active: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Paused: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  Completed: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Cancelled: "bg-red-500/20 text-red-400 border-red-500/30",
  Finished: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Archived: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

const WARRANTY_OPTIONS = [
  { value: 3, label: "3 месеца" }, { value: 6, label: "6 месеца" },
  { value: 12, label: "12 месеца" }, { value: 24, label: "24 месеца" },
];

export default function ProjectDetailPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();

  const { setActiveProject } = useActiveProject();
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState(null);
  const [showClientModal, setShowClientModal] = useState(false);
  const [showClientPicker, setShowClientPicker] = useState(false);
  const [savingWarranty, setSavingWarranty] = useState(false);
  const [showExtraWork, setShowExtraWork] = useState(false);
  const [extraWorkRefresh, setExtraWorkRefresh] = useState(0);
  const [pendingReports, setPendingReports] = useState([]);
  const [aggregate, setAggregate] = useState(null);
  const [showAddSMR, setShowAddSMR] = useState(false);
  const [showImportSMR, setShowImportSMR] = useState(false);

  // Tab from URL hash
  const hashTab = location.hash?.replace("#", "") || "overview";
  const [activeTab, setActiveTab] = useState(hashTab);

  const handleTabChange = (val) => {
    setActiveTab(val);
    window.history.replaceState(null, "", `#${val}`);
  };

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/dashboard`);
      setDashboard(res.data);
      // Set active project context
      const p = res.data.project;
      if (p) setActiveProject({ id: p.id || projectId, name: p.name, code: p.code, address_text: p.address_text });
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [projectId, setActiveProject]);

  useEffect(() => { fetchDashboard(); }, [fetchDashboard]);

  useEffect(() => {
    if (projectId) {
      API.get(`/projects/${projectId}/pending-reports`).then(r => setPendingReports(r.data?.items || [])).catch(() => {});
      API.get(`/projects/${projectId}/aggregate`).then(r => setAggregate(r.data?.has_children ? r.data : null)).catch(() => {});
    }
  }, [projectId]);

  const handleApproveReport = async (reportId) => {
    try {
      await API.post(`/daily-reports/${reportId}/approve`);
      setPendingReports(prev => prev.filter(r => r.id !== reportId));
      fetchDashboard();
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка при одобрение"); }
  };

  const handleRejectReport = async (reportId) => {
    try {
      await API.post(`/daily-reports/${reportId}/reject`, { reason: "Отхвърлен" });
      setPendingReports(prev => prev.filter(r => r.id !== reportId));
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка при отхвърляне"); }
  };

  const handleWarrantyChange = async (value) => {
    setSavingWarranty(true);
    try {
      await API.put(`/projects/${projectId}`, { warranty_months: parseInt(value) });
      setDashboard(prev => ({ ...prev, project: { ...prev.project, warranty_months: parseInt(value) } }));
    } catch { /* */ }
    finally { setSavingWarranty(false); }
  };

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin text-yellow-500" /></div>;
  if (!dashboard) return <div className="p-6 text-center text-gray-400">Проектът не е намерен</div>;

  const { project, client, progress, team, invoices, offers, materials, balance, sub_projects, parent_project } = dashboard;

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="project-detail-page">
      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => navigate(parent_project ? `/projects/${parent_project.id}` : "/projects")} className="text-gray-400 hover:text-white">
          <ArrowLeft className="w-4 h-4 mr-2" /> {parent_project ? parent_project.name : "Проекти"}
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold text-white truncate">{project.name}</h1>
          <div className="flex items-center gap-2">
            <p className="text-gray-400 text-sm">{project.code}</p>
            {parent_project && <Badge variant="outline" className="text-[9px] text-cyan-400 border-cyan-500/30">Под-обект на {parent_project.code}</Badge>}
          </div>
        </div>
        <Badge className={STATUS_COLORS[project.status] || ""}>{project.status}</Badge>
        <Button size="sm" onClick={() => navigate(`/projects/${projectId}/novo-smr`)} className="bg-amber-500 hover:bg-amber-600 text-black" data-testid="new-extra-work-btn">
          <Plus className="w-4 h-4 mr-1" /> Ново СМР
        </Button>
      </div>

      {/* Quick nav with context */}
      <div className="flex gap-2 flex-wrap">
        {[
          { to: `/site-attendance?project=${projectId}`, label: t("projectContext.attendance") },
          { to: `/daily-logs?project=${projectId}`, label: t("projectContext.reports") },
          { to: `/missing-smr?project=${projectId}`, label: t("projectContext.requests") },
        ].map(({ to, label }) => (
          <Button key={to} variant="outline" size="sm" onClick={() => navigate(to)} className="text-xs h-7">{label}</Button>
        ))}
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
        <TabsList className="w-full justify-start overflow-x-auto flex-nowrap bg-gray-800/50 border border-gray-700 h-auto p-1" data-testid="project-tabs">
          <TabsTrigger value="overview" data-testid="tab-overview">{t("projectDetail.tabs.overview")}</TabsTrigger>
          <TabsTrigger value="smr" data-testid="tab-smr">{t("projectDetail.tabs.smr")}</TabsTrigger>
          <TabsTrigger value="offers" data-testid="tab-offers">Оферти</TabsTrigger>
          <TabsTrigger value="locations" data-testid="tab-locations">{t("projectDetail.tabs.locations")}</TabsTrigger>
          <TabsTrigger value="finance" data-testid="tab-finance">{t("projectDetail.tabs.finance")}</TabsTrigger>
          <TabsTrigger value="info" data-testid="tab-info">{t("projectDetail.tabs.info")}</TabsTrigger>
          <TabsTrigger value="team" data-testid="tab-team">{t("projectDetail.tabs.team")}</TabsTrigger>
        </TabsList>

        {/* ════ TAB: OVERVIEW ════ */}
        <TabsContent value="overview" className="space-y-4 mt-4">
          {/* Pending Approval */}
          {pendingReports.length > 0 && (
            <div className="bg-amber-500/5 border border-amber-500/30 rounded-lg p-4" data-testid="pending-approval">
              <div className="flex items-center gap-2 mb-3"><AlertTriangle className="w-4 h-4 text-amber-400" /><h3 className="text-sm font-semibold text-amber-400">{pendingReports.length} отчета за одобрение</h3></div>
              <div className="space-y-2">
                {pendingReports.slice(0, 10).map(r => (
                  <div key={r.id} className="flex items-center justify-between bg-card/50 rounded-lg px-3 py-2 border border-border/50">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary">{(r.worker_name||"?").split(" ").map(n=>n[0]).join("").slice(0,2)}</div>
                      <div className="min-w-0">
                        <p className="text-xs font-medium">{r.worker_name}</p>
                        <p className="text-[9px] text-muted-foreground">{r.date} | {r.smr_type || "—"} | {r.hours}ч</p>
                      </div>
                    </div>
                    <div className="flex gap-1">
                      <Button variant="outline" size="sm" className="h-7 px-2 text-[10px] text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/10" onClick={() => handleApproveReport(r.id)}>✓</Button>
                      <Button variant="outline" size="sm" className="h-7 px-2 text-[10px] text-red-400 border-red-500/30 hover:bg-red-500/10" onClick={() => handleRejectReport(r.id)}>✗</Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* Card: Обект */}
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-project">
              <div className="flex items-center gap-2 mb-3"><Building2 className="w-5 h-5 text-yellow-500" /><h3 className="font-semibold text-white">Обект</h3></div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-gray-400">Код:</span><span className="text-white font-mono">{project.code}</span></div>
                <div className="flex justify-between"><span className="text-gray-400">Име:</span><span className="text-white">{project.name}</span></div>
                <div className="flex justify-between items-center">
                  <span className="text-gray-400">Гаранция:</span>
                  <Select value={project.warranty_months?.toString() || ""} onValueChange={handleWarrantyChange} disabled={savingWarranty}>
                    <SelectTrigger className="w-32 h-8 bg-gray-700 border-gray-600 text-sm"><SelectValue placeholder="Избери" /></SelectTrigger>
                    <SelectContent className="bg-gray-800 border-gray-700">{WARRANTY_OPTIONS.map(o => <SelectItem key={o.value} value={o.value.toString()}>{o.label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                {project.address_text && <div className="pt-2 border-t border-gray-700"><span className="text-gray-400 text-xs">Адрес:</span><p className="text-white text-sm mt-1">{project.address_text}</p></div>}
              </div>
            </div>

            {/* Card: Клиент */}
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-client">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  {client.owner_type === "company" ? <Building2 className="w-5 h-5 text-blue-500" /> : <User className="w-5 h-5 text-green-500" />}
                  <h3 className="font-semibold text-white">Клиент</h3>
                </div>
                <div className="flex items-center gap-1">
                  {client.owner_data && <Button variant="ghost" size="sm" onClick={() => setShowClientModal(true)} className="text-gray-400 hover:text-white"><Eye className="w-4 h-4" /></Button>}
                  <Button variant="ghost" size="sm" onClick={() => setShowClientPicker(true)} className="text-yellow-400 hover:text-yellow-300"><UserPlus className="w-4 h-4" /></Button>
                </div>
              </div>
              {client.owner_data ? (
                <div className="space-y-1 text-sm">
                  <Badge variant="outline" className="text-xs">{client.owner_type === "company" ? "Фирма" : "Частно лице"}</Badge>
                  <p className="text-white font-medium">{client.owner_data.name || `${client.owner_data.first_name || ""} ${client.owner_data.last_name || ""}`}</p>
                  {client.owner_data.phone && <p className="text-gray-400 text-xs flex items-center gap-1"><Phone className="w-3 h-3" />{client.owner_data.phone}</p>}
                </div>
              ) : <p className="text-gray-500 text-sm">Няма избран клиент<Button variant="ghost" size="sm" onClick={() => setShowClientPicker(true)} className="text-yellow-400 ml-2">Избери клиент</Button></p>}
            </div>

            {/* Card: Прогрес */}
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-progress">
              <div className="flex items-center gap-2 mb-3"><Clock className="w-5 h-5 text-cyan-500" /><h3 className="font-semibold text-white">Прогрес</h3></div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-gray-400">Начало:</span><span className="text-white">{progress.start_date ? formatDate(progress.start_date) : "?"}</span></div>
                <div className="flex justify-between"><span className="text-gray-400">Край (план):</span><span className="text-white">{progress.end_date ? formatDate(progress.end_date) : "?"}</span></div>
                <div className="flex justify-between"><span className="text-gray-400">Прогнозни дни:</span><span className="text-white">{progress.planned_days || "—"}</span></div>
                <div className="flex justify-between"><span className="text-gray-400 text-xs">Изминало: {progress.elapsed_days} дни</span><span className="text-gray-400 text-xs">Оставащи: {progress.remaining_days} дни</span></div>
                <Progress value={progress.progress_percent || 0} className="h-2 mt-1" />
                <p className="text-center text-xs text-gray-400">{progress.progress_percent || 0}% време изминало</p>
              </div>
            </div>

            {/* Card: Баланс */}
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-balance">
              <div className="flex items-center gap-2 mb-3"><Scale className="w-5 h-5 text-green-500" /><h3 className="font-semibold text-white">Баланс</h3></div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-gray-400">Приходи:</span><span className="text-green-400 font-mono">{formatCurrency(balance.revenue, "BGN")}</span></div>
                <div className="flex justify-between"><span className="text-gray-400">Разходи:</span><span className="text-red-400 font-mono">{formatCurrency(balance.expenses, "BGN")}</span></div>
                <div className="flex justify-between pt-2 border-t border-gray-700">
                  <span className="text-gray-400">Баланс:</span>
                  <span className={`font-bold ${balance.balance >= 0 ? "text-green-400" : "text-red-400"}`}>{formatCurrency(balance.balance, "BGN")}</span>
                </div>
              </div>
            </div>

            {/* Card: Екип (compact) */}
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-team-compact">
              <div className="flex items-center gap-2 mb-3"><Users className="w-5 h-5 text-cyan-500" /><h3 className="font-semibold text-white">Екип</h3></div>
              <div className="grid grid-cols-3 gap-2 mb-2">
                <div><p className="text-xl font-bold text-white">{team.count}</p><p className="text-[9px] text-gray-400">В екипа</p></div>
                <div><p className="text-xl font-bold text-emerald-400">{team.reported_today || 0}</p><p className="text-[9px] text-gray-400">Отчели днес</p></div>
                <div><p className="text-xl font-bold text-cyan-400">{team.approved_today || 0}</p><p className="text-[9px] text-gray-400">Одобрени</p></div>
              </div>
              {team.reported_hours > 0 && <p className="text-xs text-gray-400">{team.reported_hours}ч отчетени</p>}
              {team.pending_approval > 0 && <p className="text-xs text-amber-400">{team.pending_approval} за одобрение</p>}
              <Button variant="ghost" size="sm" className="mt-2 text-xs" onClick={() => handleTabChange("team")}>Виж детайли →</Button>
            </div>

            {/* Card: Оферти (compact) */}
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-offers-compact">
              <div className="flex items-center gap-2 mb-3"><FileText className="w-5 h-5 text-amber-500" /><h3 className="font-semibold text-white">Оферти</h3></div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-gray-400">Одобрени:</span><span className="text-white">{offers.approved_count}</span></div>
                <div className="flex justify-between"><span className="text-gray-400">С ДДС:</span><span className="text-yellow-500 font-mono">{formatCurrency(offers.total_inc_vat, "BGN")}</span></div>
              </div>
            </div>
          </div>

          {/* Sub-projects section */}
          {(sub_projects?.length > 0 || !parent_project) && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-sub-projects">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2"><Building2 className="w-5 h-5 text-violet-500" /><h3 className="font-semibold text-white">Под-обекти</h3>{sub_projects?.length > 0 && <Badge variant="outline" className="text-[10px]">{sub_projects.length}</Badge>}</div>
                <Button size="sm" variant="outline" className="text-xs gap-1" onClick={() => { navigate(`/projects?createChild=${projectId}&parentName=${encodeURIComponent(project.name)}`); }} data-testid="add-sub-project-btn">
                  <Plus className="w-3 h-3" />Под-обект
                </Button>
              </div>
              {sub_projects?.length > 0 ? (
                <div className="space-y-2">
                  {sub_projects.map(sp => (
                    <button key={sp.id} onClick={() => navigate(`/projects/${sp.id}`)} className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-gray-900/50 hover:bg-gray-700/50 text-left transition-colors">
                      <div className="min-w-0"><p className="text-sm font-medium text-white truncate">{sp.name}</p><p className="text-[10px] text-gray-400">{sp.code}</p></div>
                      <Badge className={`text-[9px] ${STATUS_COLORS[sp.status] || ""}`}>{sp.status}</Badge>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-gray-500">Няма под-обекти</p>
              )}
            </div>
          )}

          {/* Parent aggregate (only for parents with children) */}
          {aggregate && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 col-span-full" data-testid="parent-aggregate">
              <div className="flex items-center gap-2 mb-3"><Building2 className="w-5 h-5 text-violet-500" /><h3 className="font-semibold text-white">Обобщение (родител + под-обекти)</h3></div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-400 border-b border-gray-700">
                      <th className="text-left py-1 pr-4"></th>
                      <th className="text-right py-1 px-2">Собствени</th>
                      <th className="text-right py-1 px-2">Под-обекти</th>
                      <th className="text-right py-1 px-2 text-primary font-bold">Общо</th>
                    </tr>
                  </thead>
                  <tbody>
                    <AggRow label="Хора в екип" own={aggregate.team.own.count} children={aggregate.team.children.count} total={aggregate.team.total.count} />
                    <AggRow label="Отчели днес" own={aggregate.team.own.reported} children={aggregate.team.children.reported} total={aggregate.team.total.reported} />
                    <AggRow label="Часове днес" own={aggregate.team.own.hours} children={aggregate.team.children.hours} total={aggregate.team.total.hours} suffix="ч" />
                    <AggRow label="Всички отчети" own={aggregate.reports.own.count} children={aggregate.reports.children.count} total={aggregate.reports.total.count} />
                    <AggRow label="Общо часове" own={aggregate.reports.own.hours} children={aggregate.reports.children.hours} total={aggregate.reports.total.hours} suffix="ч" />
                    <AggRow label="Оферти" own={aggregate.offers.own.count} children={aggregate.offers.children.count} total={aggregate.offers.total.count} />
                    <AggRow label="Фактури" own={aggregate.invoices.own.count} children={aggregate.invoices.children.count} total={aggregate.invoices.total.count} />
                    <AggRow label="Фактурирано" own={aggregate.invoices.own.invoiced} children={aggregate.invoices.children.invoiced} total={aggregate.invoices.total.invoiced} suffix=" EUR" color="text-primary" />
                    <AggRow label="Реално платено" own={aggregate.invoices.own.paid} children={aggregate.invoices.children.paid} total={aggregate.invoices.total.paid} suffix=" EUR" color="text-emerald-400" />
                    <AggRow label="Неплатено" own={aggregate.invoices.own.unpaid} children={aggregate.invoices.children.unpaid} total={aggregate.invoices.total.unpaid} suffix=" EUR" color="text-amber-400" />
                    {(aggregate.invoices.total.overdue || 0) > 0 && <AggRow label="Просрочено" own={aggregate.invoices.own.overdue} children={aggregate.invoices.children.overdue} total={aggregate.invoices.total.overdue} suffix=" EUR" color="text-red-400" />}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Centralized View */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-centralized">
            <CentralizedProjectView projectId={projectId} />
          </div>
        </TabsContent>

        {/* ════ TAB: SMR ════ */}
        <TabsContent value="smr" className="space-y-4 mt-4">
          {/* SMR Entry Points */}
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">СМР — {project.name}</h3>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" className="text-xs gap-1" onClick={() => setShowAddSMR(!showAddSMR)} data-testid="add-smr-toggle">
                <Plus className="w-3 h-3" />{showAddSMR ? "Скрий" : "+ Ново СМР"}
              </Button>
              <Button size="sm" variant="outline" className="text-xs gap-1" onClick={() => setShowImportSMR(!showImportSMR)} data-testid="import-smr-toggle">
                <FileText className="w-3 h-3" />Импорт
              </Button>
              <Button size="sm" onClick={() => navigate(`/projects/${projectId}/novo-smr`)} className="bg-amber-500 hover:bg-amber-600 text-black text-xs gap-1">
                <Sparkles className="w-3 h-3" />Ново СМР + AI
              </Button>
            </div>
          </div>

          {/* Inline Add SMR Form */}
          {showAddSMR && (
            <InlineAddSMR projectId={projectId} onDone={() => { setShowAddSMR(false); fetchDashboard(); }} />
          )}

          {/* Import SMR */}
          {showImportSMR && (
            <InlineImportSMR projectId={projectId} onDone={() => { setShowImportSMR(false); fetchDashboard(); }} />
          )}

          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><CentralizedActivitiesTable projectId={projectId} /></div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><SMRGroupsPanel projectId={projectId} /></div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><SMRLocationMap projectId={projectId} /></div>
          {/* Aggregated SMR with to-offer flow */}
          <AggregatedSMRPanel projectId={projectId} />

          <ExtraWorksDraftPanel projectId={projectId} refreshKey={extraWorkRefresh} />
        </TabsContent>

        {/* ════ TAB: LOCATIONS ════ */}
        {/* TAB: Оферти */}
        <TabsContent value="offers" className="space-y-4 mt-4">
          <ProjectOffersTab projectId={projectId} projectName={project.name} />
        </TabsContent>

        <TabsContent value="locations" className="space-y-4 mt-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><LocationTreePanel projectId={projectId} /></div>
        </TabsContent>

        {/* ════ TAB: FINANCE ════ */}
        <TabsContent value="finance" className="space-y-4 mt-4">
          {/* Financial Results: Cash / Operating / Fully Loaded */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <FinancialResultsCard projectId={projectId} />
          </div>

          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><ProjectPnLDashboard projectId={projectId} /></div>

          {/* Expected vs Actual */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><ExpectedActualPanel projectId={projectId} /></div>

          {/* Material Waste */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><MaterialWastePanel projectId={projectId} /></div>

          {/* Subcontractor Performance */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><SubcontractorPerformancePanel projectId={projectId} /></div>

          {/* Invoices */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-invoices">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2"><Receipt className="w-5 h-5 text-pink-500" /><h3 className="font-semibold text-white">Фактури ({invoices.count})</h3></div>
              <Button size="sm" onClick={() => navigate(`/finance/invoices/new?project_id=${projectId}`)} className="bg-yellow-500 hover:bg-yellow-600 text-black"><Plus className="w-4 h-4 mr-1" />Нова фактура</Button>
            </div>
            {invoices.invoices.length > 0 ? (
              <>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader><TableRow className="border-gray-700">
                      <TableHead className="text-gray-400">№</TableHead><TableHead className="text-gray-400">Клиент</TableHead>
                      <TableHead className="text-gray-400">Дата</TableHead><TableHead className="text-gray-400">Падеж</TableHead>
                      <TableHead className="text-gray-400">Статус</TableHead><TableHead className="text-gray-400 text-right">Общо</TableHead>
                      <TableHead className="text-gray-400 text-right">Платено</TableHead><TableHead className="text-gray-400 text-right">Остатък</TableHead>
                    </TableRow></TableHeader>
                    <TableBody>
                      {invoices.invoices.map(inv => (
                        <TableRow key={inv.id} className="border-gray-700 cursor-pointer hover:bg-gray-800/50" onClick={() => navigate(`/finance/invoices/${inv.id}`)}>
                          <TableCell className="text-yellow-400 font-mono text-sm">{inv.invoice_number}</TableCell>
                          <TableCell className="text-white text-sm">{inv.counterparty_name || "—"}</TableCell>
                          <TableCell className="text-gray-400 text-sm">{formatDate(inv.issue_date)}</TableCell>
                          <TableCell className="text-gray-400 text-sm">{formatDate(inv.due_date)}</TableCell>
                          <TableCell><Badge variant="outline" className="text-xs">{inv.status}</Badge></TableCell>
                          <TableCell className="text-right text-white font-mono">{formatCurrency(inv.total, inv.currency)}</TableCell>
                          <TableCell className="text-right text-green-400 font-mono">{formatCurrency(inv.paid_amount, inv.currency)}</TableCell>
                          <TableCell className="text-right text-red-400 font-mono">{formatCurrency(inv.remaining_amount, inv.currency)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <div className="mt-4 pt-4 border-t border-gray-700 grid grid-cols-3 gap-4 text-sm">
                  <div className="text-center"><p className="text-gray-400">Общо</p><p className="text-white font-bold">{formatCurrency(invoices.totals.total, "BGN")}</p></div>
                  <div className="text-center"><p className="text-gray-400">Платено</p><p className="text-green-400 font-bold">{formatCurrency(invoices.totals.paid, "BGN")}</p></div>
                  <div className="text-center"><p className="text-gray-400">Неплатено</p><p className="text-red-400 font-bold">{formatCurrency(invoices.totals.unpaid, "BGN")}</p></div>
                </div>
              </>
            ) : <p className="text-gray-500 text-sm">Няма издадени фактури</p>}
          </div>

          <ProjectMaterialLedger projectId={projectId} />

          {/* Extra Offers */}
          {offers.extra_offers?.length > 0 && (
            <div className="bg-gray-800/50 border border-amber-500/20 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-4"><FileText className="w-5 h-5 text-amber-500" /><h3 className="font-semibold text-white">Допълнителни оферти</h3><Badge variant="outline" className="text-[10px] bg-amber-500/15 text-amber-400">{offers.extra_offers.length}</Badge></div>
              <div className="space-y-2">
                {offers.extra_offers.map(eo => (
                  <div key={eo.id} className="flex items-center justify-between p-3 rounded-lg bg-muted/15 hover:bg-muted/25 cursor-pointer border border-gray-700/50 hover:border-amber-500/30 transition-colors" onClick={() => navigate(`/offers/${eo.id}`)}>
                    <div className="min-w-0 flex-1"><span className="font-mono text-sm text-amber-400">{eo.offer_no}</span><p className="text-sm text-gray-300 truncate">{eo.title}</p></div>
                    <div className="text-right ml-4"><p className="font-mono text-sm font-bold text-white">{formatCurrency(eo.total || 0, eo.currency || "BGN")}</p></div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </TabsContent>

        {/* ════ TAB: INFO ════ */}
        <TabsContent value="info" className="space-y-4 mt-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <ProjectInfoPanel projectId={projectId} project={project} onUpdated={(p) => setDashboard(prev => ({ ...prev, project: p }))} />
          </div>
        </TabsContent>

        {/* ════ TAB: TEAM ════ */}
        <TabsContent value="team" className="space-y-4 mt-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <ProjectPersonnelPanel projectId={projectId} />
          </div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <PersonnelUnified projectId={projectId} team={team} />
          </div>
        </TabsContent>
      </Tabs>

      {/* Modals (always rendered) */}
      <Dialog open={showClientModal} onOpenChange={setShowClientModal}>
        <DialogContent className="bg-gray-900 border-gray-700 text-white max-w-md">
          <DialogHeader><DialogTitle>Данни за клиента</DialogTitle></DialogHeader>
          {client.owner_data && (
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2 pb-2 border-b border-gray-700">
                {client.owner_data.type === "company" ? <Building2 className="w-5 h-5 text-blue-500" /> : <User className="w-5 h-5 text-green-500" />}
                <Badge>{client.owner_data.type === "company" ? "Фирма" : "Частно лице"}</Badge>
              </div>
              {client.owner_data.type === "company" ? (
                <>
                  <div><span className="text-gray-400">Име:</span> <span className="text-white">{client.owner_data.name}</span></div>
                  <div><span className="text-gray-400">ЕИК:</span> <span className="text-white font-mono">{client.owner_data.eik}</span></div>
                  {client.owner_data.vat_number && <div><span className="text-gray-400">ДДС:</span> <span className="text-white font-mono">{client.owner_data.vat_number}</span></div>}
                  {client.owner_data.mol && <div><span className="text-gray-400">МОЛ:</span> <span className="text-white">{client.owner_data.mol}</span></div>}
                  {client.owner_data.address && <div><span className="text-gray-400">Адрес:</span> <span className="text-white">{client.owner_data.address}</span></div>}
                </>
              ) : (
                <div><span className="text-gray-400">Име:</span> <span className="text-white">{client.owner_data.first_name} {client.owner_data.last_name}</span></div>
              )}
              {client.owner_data.phone && <div><span className="text-gray-400">Телефон:</span> <span className="text-white">{client.owner_data.phone}</span></div>}
              {client.owner_data.email && <div><span className="text-gray-400">Имейл:</span> <span className="text-white">{client.owner_data.email}</span></div>}
            </div>
          )}
        </DialogContent>
      </Dialog>
      <ClientPickerModal projectId={projectId} open={showClientPicker} onOpenChange={setShowClientPicker} onClientSelected={fetchDashboard} />
      <ExtraWorkModal projectId={projectId} open={showExtraWork} onOpenChange={setShowExtraWork} onCreated={() => setExtraWorkRefresh(prev => prev + 1)} />
    </div>
  );
}

// ── PersonnelUnified Component ──────────────────────────────────
function PersonnelUnified({ projectId, team }) {
  const [tab, setTab] = useState("today");
  const [allPersonnel, setAllPersonnel] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const res = await API.get(`/daily-reports/project-day-status/${projectId}`);
        const fromReports = res.data.employees || [];
        const reportIds = new Set(fromReports.map(e => e.employee_id));
        const combined = [...fromReports];
        for (const m of (team.members || [])) {
          if (m.user_id && !reportIds.has(m.user_id)) {
            combined.push({ employee_id: m.user_id, first_name: m.name?.split(" ")[0] || "", last_name: m.name?.split(" ").slice(1).join(" ") || "", avatar_url: null, has_report: false, role: m.role_in_project });
          }
        }
        setAllPersonnel(combined);
      } catch { setAllPersonnel(team.members?.map(m => ({ employee_id: m.user_id, first_name: m.name || "", last_name: "", has_report: false, role: m.role_in_project })) || []); }
    };
    fetchAll();
  }, [projectId, team]);

  const count = allPersonnel.length || team.count || 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2"><Users className="w-5 h-5 text-cyan-500" /><h3 className="font-semibold text-white">Персонал</h3></div>
        <div className="flex rounded-lg border border-gray-600 overflow-hidden">
          <button onClick={() => setTab("all")} className={`px-3 py-1 text-xs ${tab === "all" ? "bg-primary text-primary-foreground" : "bg-gray-800 text-gray-400"}`}>Всички ({count})</button>
          <button onClick={() => setTab("today")} className={`px-3 py-1 text-xs border-l border-gray-600 ${tab === "today" ? "bg-primary text-primary-foreground" : "bg-gray-800 text-gray-400"}`}>Днес</button>
          <button onClick={() => setTab("report")} className={`px-3 py-1 text-xs border-l border-gray-600 ${tab === "report" ? "bg-amber-500 text-black" : "bg-gray-800 text-gray-400"}`}>Дневен отчет</button>
        </div>
      </div>
      {tab === "all" && (
        <div className="space-y-1">
          {allPersonnel.length > 0 ? allPersonnel.map((p, i) => {
            const name = `${p.first_name || ""} ${p.last_name || ""}`.trim();
            const initials = `${(p.first_name || "?")[0]}${(p.last_name || "")[0] || ""}`;
            return (
              <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/10 text-sm cursor-pointer hover:bg-muted/20" onClick={() => navigate(`/employees/${p.employee_id}`)}>
                <div className="flex items-center gap-2">
                  {p.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${p.avatar_url}`} className="w-7 h-7 rounded-full object-cover" alt="" onError={e => e.target.style.display = "none"} /> : <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[10px] font-bold text-primary">{initials}</div>}
                  <span className="text-white">{name || "—"}</span>
                </div>
                <div className="flex items-center gap-2">
                  {p.has_report && <Badge variant="outline" className="text-[9px] bg-emerald-500/15 text-emerald-400">Отчет</Badge>}
                  {p.role && <Badge variant="outline" className="text-[10px]">{p.role}</Badge>}
                </div>
              </div>
            );
          }) : <p className="text-gray-500 text-sm">Няма персонал по обекта</p>}
        </div>
      )}
      {tab === "today" && <ProjectPersonnelCard projectId={projectId} />}
      {tab === "report" && <ObjectDailyReportTab projectId={projectId} />}
    </div>
  );
}


function AggRow({ label, own, children, total, suffix = "", color = "" }) {
  return (
    <tr className="border-b border-gray-800/50">
      <td className="py-1.5 pr-4 text-gray-400">{label}</td>
      <td className="text-right py-1.5 px-2 font-mono text-gray-300">{own || 0}{suffix}</td>
      <td className="text-right py-1.5 px-2 font-mono text-gray-400">{children || 0}{suffix}</td>
      <td className={`text-right py-1.5 px-2 font-mono font-bold ${color || "text-white"}`}>{total || 0}{suffix}</td>
    </tr>
  );
}


function InlineAddSMR({ projectId, onDone }) {
  const [title, setTitle] = useState("");
  const [qty, setQty] = useState("1");
  const [unit, setUnit] = useState("m2");
  const [location, setLocation] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [rows, setRows] = useState([]);

  const UNITS = [
    { v: "m2", l: "м²" }, { v: "m", l: "м" }, { v: "pcs", l: "бр" },
    { v: "hours", l: "часа" }, { v: "lot", l: "к-т" }, { v: "kg", l: "кг" },
  ];

  const addRow = () => {
    if (!title.trim()) return;
    setRows(prev => [...prev, { title: title.trim(), qty: parseFloat(qty) || 1, unit, location, note, isExtra }]);
    setTitle(""); setQty("1"); setNote("");
  };

  const handleSave = async () => {
    const toSave = rows.length > 0 ? rows : (title.trim() ? [{ title: title.trim(), qty: parseFloat(qty) || 1, unit, location, note, isExtra }] : []);
    if (toSave.length === 0) return;
    setSaving(true);
    try {
      for (const r of toSave) {
        await API.post("/extra-works", {
          project_id: projectId,
          title: r.title,
          qty: r.qty,
          unit: r.unit,
          location_room: r.location,
          notes: r.note,
        });
      }
      toast.success(`${toSave.length} СМР добавени`);
      onDone();
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 space-y-3" data-testid="inline-add-smr">
      <p className="text-xs font-semibold text-gray-400">Бързо добавяне на СМР</p>
      <div className="grid grid-cols-12 gap-2">
        <div className="col-span-4"><Input value={title} onChange={e => setTitle(e.target.value)} placeholder="Наименование *" className="bg-background h-9 text-xs" onKeyDown={e => e.key === "Enter" && addRow()} /></div>
        <div className="col-span-1"><Input type="number" value={qty} onChange={e => setQty(e.target.value)} className="bg-background h-9 text-xs text-center" /></div>
        <div className="col-span-1">
          <select value={unit} onChange={e => setUnit(e.target.value)} className="w-full h-9 rounded-md border border-input bg-background px-2 text-xs">
            {UNITS.map(u => <option key={u.v} value={u.v}>{u.l}</option>)}
          </select>
        </div>
        <div className="col-span-2"><Input value={location} onChange={e => setLocation(e.target.value)} placeholder="Локация" className="bg-background h-9 text-xs" /></div>
        <div className="col-span-2"><Input value={note} onChange={e => setNote(e.target.value)} placeholder="Бележка" className="bg-background h-9 text-xs" /></div>
        <div className="col-span-2 flex gap-1">
          <Button size="sm" variant="outline" onClick={addRow} disabled={!title.trim()} className="h-9 text-xs">+Ред</Button>
          <Button size="sm" onClick={handleSave} disabled={saving || (!title.trim() && rows.length === 0)} className="h-9 text-xs">
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : "Запази"}
          </Button>
        </div>
      </div>
      {rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r, i) => (
            <div key={i} className="flex items-center justify-between text-xs bg-gray-900/50 rounded px-3 py-1">
              <span>{r.title} — {r.qty} {UNITS.find(u => u.v === r.unit)?.l} {r.location && `@ ${r.location}`}</span>
              <button onClick={() => setRows(prev => prev.filter((_, j) => j !== i))} className="text-red-400 text-xs">×</button>
            </div>
          ))}
          <p className="text-[9px] text-gray-500">{rows.length} реда за запис</p>
        </div>
      )}
    </div>
  );
}

function InlineImportSMR({ projectId, onDone }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);

  const handlePreview = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("project_id", projectId);
      const res = await API.post("/excel-import/preview", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setPreview(res.data);
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка при преглед"); }
    finally { setLoading(false); }
  };

  const handleImport = async () => {
    if (!preview?.rows) return;
    setImporting(true);
    try {
      let count = 0;
      for (const row of preview.rows) {
        await API.post("/extra-works", {
          project_id: projectId,
          title: row.title || row.description || row.name || `Ред ${count + 1}`,
          qty: parseFloat(row.qty || row.quantity || 1),
          unit: row.unit || "m2",
          location_room: row.location || row.room || "",
          notes: row.notes || row.note || "",
        });
        count++;
      }
      toast.success(`${count} СМР импортирани`);
      onDone();
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка при импорт"); }
    finally { setImporting(false); }
  };

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 space-y-3" data-testid="inline-import-smr">
      <p className="text-xs font-semibold text-gray-400">Импорт на СМР от Excel</p>
      <div className="flex items-center gap-3">
        <input type="file" accept=".xlsx,.xls,.csv" onChange={e => setFile(e.target.files?.[0])} className="text-xs" />
        <Button size="sm" onClick={handlePreview} disabled={!file || loading} className="text-xs">
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Преглед"}
        </Button>
      </div>
      {preview?.rows && (
        <div>
          <p className="text-xs text-gray-400 mb-1">{preview.rows.length} реда за импорт:</p>
          <div className="max-h-[200px] overflow-y-auto space-y-1">
            {preview.rows.slice(0, 20).map((r, i) => (
              <div key={i} className="text-[10px] bg-gray-900/50 rounded px-2 py-1">
                {r.title || r.description || r.name} — {r.qty || r.quantity || 1} {r.unit || "m2"} {r.location && `@ ${r.location}`}
              </div>
            ))}
            {preview.rows.length > 20 && <p className="text-[9px] text-gray-500">... и още {preview.rows.length - 20}</p>}
          </div>
          <Button size="sm" onClick={handleImport} disabled={importing} className="mt-2 text-xs bg-emerald-600 hover:bg-emerald-700">
            {importing ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
            Импортирай {preview.rows.length} реда
          </Button>
        </div>
      )}
    </div>
  );
}

function AggregatedSMRPanel({ projectId }) {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [creating, setCreating] = useState(false);
  const [result, setResult] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    API.get(`/projects/${projectId}/smr-aggregated`).then(r => setData(r.data)).catch(() => {});
  }, [projectId]);

  if (!data || data.total === 0) return null;

  const toggleItem = (ids) => {
    setSelected(prev => {
      const next = new Set(prev);
      for (const id of ids) { if (next.has(id)) next.delete(id); else next.add(id); }
      return next;
    });
  };

  const selectAll = () => {
    const ids = new Set();
    data.items.filter(i => i.status === "open").forEach(i => i.source_ids.forEach(id => ids.add(id)));
    setSelected(ids);
  };

  const handleCreateOffer = async () => {
    setCreating(true);
    try {
      const res = await API.post(`/projects/${projectId}/smr-to-offer`, { source_ids: Array.from(selected) });
      setResult(res.data);
      toast.success(`Оферта ${res.data.offer_no} създадена`);
      setSelected(new Set());
      API.get(`/projects/${projectId}/smr-aggregated`).then(r => setData(r.data)).catch(() => {});
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
    finally { setCreating(false); }
  };

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="smr-aggregated">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-white">СМР за оферта</h3>
          <Badge variant="outline" className="text-[10px]">{data.total} групи / {data.source_rows} реда</Badge>
        </div>
        <div className="flex gap-2">
          {data.items.some(i => i.status === "open") && <Button size="sm" variant="ghost" className="text-xs" onClick={selectAll}>Избери всички</Button>}
          {selected.size > 0 && (
            <Button size="sm" onClick={handleCreateOffer} disabled={creating} className="text-xs bg-amber-500 hover:bg-amber-600 text-black gap-1">
              {creating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
              Създай оферта ({selected.size} реда)
            </Button>
          )}
        </div>
      </div>
      {result && (
        <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/30 p-3 mb-3 flex items-center justify-between">
          <span className="text-xs text-emerald-400">Оферта {result.offer_no} ({result.lines_count} реда, {result.subtotal} EUR)</span>
          <Button size="sm" variant="outline" className="text-xs" onClick={() => navigate(`/offers/${result.offer_id}`)}>Отвори →</Button>
        </div>
      )}
      <div className="space-y-1 max-h-[300px] overflow-y-auto">
        {data.items.map((item, i) => {
          const isSelected = item.source_ids.some(id => selected.has(id));
          const isOpen = item.status === "open";
          return (
            <div key={i} className={`flex items-center gap-3 px-3 py-2 rounded-lg text-xs ${isOpen ? (isSelected ? "bg-amber-500/10 border border-amber-500/30" : "hover:bg-gray-700/30 border border-transparent") : "opacity-50 border border-transparent"}`}>
              {isOpen && <input type="checkbox" checked={isSelected} onChange={() => toggleItem(item.source_ids)} className="rounded" />}
              {!isOpen && <span className="w-4 text-center text-emerald-400 text-[10px]">✓</span>}
              <div className="flex-1 min-w-0">
                <span className="font-medium text-white">{item.title}</span>
                {item.location && <span className="text-gray-400 ml-2">@ {item.location}</span>}
              </div>
              <span className="font-mono text-gray-300">{item.total_qty} {item.unit}</span>
              {item.source_count > 1 && <Badge variant="outline" className="text-[8px] text-gray-400">{item.source_count} реда</Badge>}
              {item.has_offer && <Badge variant="outline" className="text-[8px] text-emerald-400 border-emerald-500/30">В оферта</Badge>}
            </div>
          );
        })}
      </div>
    </div>
  );
}


const OFFER_STATUS = {
  Draft: { label: "Чернова", cls: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
  Sent: { label: "Изпратена", cls: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
  Accepted: { label: "Одобрена", cls: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" },
  Rejected: { label: "Отхвърлена", cls: "bg-red-500/20 text-red-400 border-red-500/30" },
  NeedsRevision: { label: "За преработка", cls: "bg-amber-500/20 text-amber-400 border-amber-500/30" },
};

function ProjectOffersTab({ projectId, projectName }) {
  const [offers, setOffers] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const loadOffers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await API.get(`/offers?project_id=${projectId}`);
      setOffers(res.data?.items || res.data || []);
    } catch { setOffers([]); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { loadOffers(); }, [loadOffers]);

  const handleAction = async (offerId, action) => {
    try {
      await API.post(`/offers/${offerId}/${action}`);
      toast.success(action === "send" ? "Изпратена" : action === "accept" ? "Одобрена" : "Отхвърлена");
      loadOffers();
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
  };

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>;

  const byStatus = {};
  offers.forEach(o => { byStatus[o.status] = (byStatus[o.status] || 0) + 1; });
  const totalValue = offers.reduce((s, o) => s + (o.total || 0), 0);

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-white">Оферти — {projectName}</h3>
          <Badge variant="outline" className="text-[10px]">{offers.length}</Badge>
          {Object.entries(byStatus).map(([s, c]) => {
            const cfg = OFFER_STATUS[s] || {};
            return <Badge key={s} variant="outline" className={`text-[9px] ${cfg.cls || ""}`}>{cfg.label || s}: {c}</Badge>;
          })}
        </div>
        <span className="text-xs font-mono text-primary">{totalValue.toFixed(0)} EUR</span>
      </div>

      {offers.length === 0 ? (
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-8 text-center text-gray-500">
          Няма оферти. Създайте от таб СМР → "Създай оферта от избраните".
        </div>
      ) : (
        <div className="space-y-2">
          {offers.map(o => {
            const st = OFFER_STATUS[o.status] || { label: o.status, cls: "" };
            const linesCount = o.lines?.length || 0;
            const zeroLines = (o.lines || []).filter(ln => !ln.unit_price || ln.unit_price === 0).length;
            const isZero = (o.total || 0) === 0 && linesCount > 0;
            return (
              <div key={o.id} className={`bg-gray-800/50 border rounded-lg p-4 ${isZero && o.status === "Draft" ? "border-amber-500/50" : "border-gray-700"}`} data-testid={`offer-${o.id}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="font-mono text-sm font-bold text-primary">{o.offer_no}</span>
                    <span className="text-sm text-white truncate">{o.title || `${linesCount} позиции`}</span>
                    <Badge variant="outline" className={`text-[10px] ${st.cls}`}>{st.label}</Badge>
                  </div>
                  <span className={`text-sm font-mono font-bold ${isZero ? "text-gray-500" : "text-amber-400"}`}>{(o.total || 0).toFixed(0)} EUR</span>
                </div>

                {/* Zero-price warning */}
                {zeroLines > 0 && o.status === "Draft" && (
                  <div className="flex items-center gap-2 mb-2 px-2 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
                    <span className="text-[10px] text-amber-400">{zeroLines === linesCount ? "Всички редове са без цена" : `${zeroLines} от ${linesCount} реда без цена`} — попълнете цените преди изпращане</span>
                  </div>
                )}

                {/* Lines preview */}
                {linesCount > 0 && (
                  <div className="mb-2 space-y-0.5">
                    {o.lines.slice(0, 4).map((ln, i) => (
                      <div key={i} className="flex items-center justify-between text-[10px] text-gray-400 px-2">
                        <span className="truncate max-w-[300px]">{ln.description}</span>
                        <span className="font-mono">{ln.qty} {ln.unit} × {ln.unit_price} = {(ln.total || 0).toFixed(0)}</span>
                      </div>
                    ))}
                    {linesCount > 4 && <p className="text-[9px] text-gray-500 px-2">... и още {linesCount - 4}</p>}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2 pt-2 border-t border-gray-700/50">
                  {o.status === "Draft" && (
                    <Button size="sm" variant="outline" className="text-xs gap-1 h-7" onClick={() => navigate(`/offers/${o.id}?returnTo=/projects/${projectId}&returnTab=offers`)}>
                      <Pencil className="w-3 h-3" />Редактирай
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" className="text-xs gap-1 h-7" onClick={() => navigate(`/offers/${o.id}`)}>
                    <FileText className="w-3 h-3" />Преглед
                  </Button>

                  {o.status === "Draft" && (
                    isZero ? (
                      <Button size="sm" variant="outline" className="text-xs gap-1 h-7 text-gray-500 border-gray-600 cursor-not-allowed" disabled title="Попълнете цените преди изпращане">
                        Изпрати (0 EUR)
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" className="text-xs gap-1 h-7 text-blue-400 border-blue-500/30" onClick={() => handleAction(o.id, "send")}>
                        Изпрати
                      </Button>
                    )
                  )}

                  {o.status === "Sent" && (
                    <>
                      <Button size="sm" className="text-xs gap-1 h-7 bg-emerald-600 hover:bg-emerald-700" onClick={() => handleAction(o.id, "accept")}>
                        ✓ Одобри
                      </Button>
                      <Button size="sm" variant="outline" className="text-xs gap-1 h-7 text-red-400 border-red-500/30" onClick={() => handleAction(o.id, "reject")}>
                        ✗ Отхвърли
                      </Button>
                    </>
                  )}

                  <Button size="sm" variant="ghost" className="text-xs gap-1 h-7 ml-auto" onClick={() => window.open(`${process.env.REACT_APP_BACKEND_URL}/api/offers/${o.id}/pdf`, "_blank")}>
                    PDF
                  </Button>

                  {o.notes && <span className="text-[9px] text-gray-500 ml-2">{o.notes.slice(0, 40)}</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

