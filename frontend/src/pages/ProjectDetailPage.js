import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useActiveProject } from "@/contexts/ProjectContext";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
  ArrowLeft, Users, CalendarDays, Building2, User, Phone, Mail, Hash,
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

  const { project, client, progress, team, invoices, offers, materials, balance } = dashboard;

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="project-detail-page">
      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => navigate("/projects")} className="text-gray-400 hover:text-white">
          <ArrowLeft className="w-4 h-4 mr-2" /> Проекти
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold text-white truncate">{project.name}</h1>
          <p className="text-gray-400 text-sm">{project.code}</p>
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
          <TabsTrigger value="locations" data-testid="tab-locations">{t("projectDetail.tabs.locations")}</TabsTrigger>
          <TabsTrigger value="finance" data-testid="tab-finance">{t("projectDetail.tabs.finance")}</TabsTrigger>
          <TabsTrigger value="info" data-testid="tab-info">{t("projectDetail.tabs.info")}</TabsTrigger>
          <TabsTrigger value="team" data-testid="tab-team">{t("projectDetail.tabs.team")}</TabsTrigger>
        </TabsList>

        {/* ════ TAB: OVERVIEW ════ */}
        <TabsContent value="overview" className="space-y-4 mt-4">
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
              <p className="text-2xl font-bold text-white">{team.count} <span className="text-sm font-normal text-gray-400">човека</span></p>
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
        </TabsContent>

        {/* ════ TAB: SMR ════ */}
        <TabsContent value="smr" className="space-y-4 mt-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><ProjectSMRTab projectId={projectId} /></div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><SMRGroupsPanel projectId={projectId} /></div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><SMRLocationMap projectId={projectId} /></div>
          <ExtraWorksDraftPanel projectId={projectId} refreshKey={extraWorkRefresh} />
        </TabsContent>

        {/* ════ TAB: LOCATIONS ════ */}
        <TabsContent value="locations" className="space-y-4 mt-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4"><LocationTreePanel projectId={projectId} /></div>
        </TabsContent>

        {/* ════ TAB: FINANCE ════ */}
        <TabsContent value="finance" className="space-y-4 mt-4">
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
