import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
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
  ArrowLeft,
  Users,
  CalendarDays,
  Building2,
  User,
  Phone,
  Mail,
  Hash,
  FileText,
  Package,
  Wallet,
  Plus,
  Loader2,
  Eye,
  Shield,
  Clock,
  TrendingUp,
  Receipt,
  Boxes,
  Scale,
  UserPlus,
  BarChart3,
} from "lucide-react";
import ClientSelector from "@/components/ClientSelector";
import ClientPickerModal from "@/components/ClientPickerModal";
import ExtraWorkModal from "@/components/ExtraWorkModal";
import ExtraWorksDraftPanel from "@/components/ExtraWorksDraftPanel";
import ProjectMaterialLedger from "@/components/ProjectMaterialLedger";

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
  { value: 3, label: "3 месеца" },
  { value: 6, label: "6 месеца" },
  { value: 12, label: "12 месеца" },
  { value: 24, label: "24 месеца" },
];

export default function ProjectDetailPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState(null);
  const [showClientModal, setShowClientModal] = useState(false);
  const [showClientPicker, setShowClientPicker] = useState(false);
  const [savingWarranty, setSavingWarranty] = useState(false);
  const [showExtraWork, setShowExtraWork] = useState(false);
  const [extraWorkRefresh, setExtraWorkRefresh] = useState(0);

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/dashboard`);
      setDashboard(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  // Scroll to anchor (e.g. #extra-works-section) after load
  useEffect(() => {
    if (!loading && window.location.hash) {
      setTimeout(() => {
        const el = document.querySelector(window.location.hash);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 300);
    }
  }, [loading]);

  const handleWarrantyChange = async (value) => {
    setSavingWarranty(true);
    try {
      await API.put(`/projects/${projectId}`, { warranty_months: parseInt(value) });
      setDashboard(prev => ({
        ...prev,
        project: { ...prev.project, warranty_months: parseInt(value) }
      }));
    } catch (err) {
      console.error(err);
    } finally {
      setSavingWarranty(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-8 h-8 animate-spin text-yellow-500" />
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="p-6 text-center text-gray-400">
        Проектът не е намерен
      </div>
    );
  }

  const { project, client, progress, team, invoices, offers, materials, balance } = dashboard;

  return (
    <div className="p-4 md:p-6 space-y-6" data-testid="project-detail-page">
        {/* Header */}
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate("/projects")}
            className="text-gray-400 hover:text-white"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Проекти
          </Button>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-white">{project.name}</h1>
            <p className="text-gray-400 text-sm">{project.code}</p>
          </div>
          <Badge className={STATUS_COLORS[project.status] || ""}>
            {project.status}
          </Badge>
          <Button size="sm" variant="outline" onClick={() => navigate(`/projects/${projectId}/financial`)} data-testid="project-financial-btn">
            <BarChart3 className="w-4 h-4 mr-1" /> Финанси
          </Button>
          <Button size="sm" onClick={() => navigate(`/projects/${projectId}/novo-smr`)} className="bg-amber-500 hover:bg-amber-600 text-black" data-testid="new-extra-work-btn">
            <Plus className="w-4 h-4 mr-1" /> Ново СМР
          </Button>
        </div>

        {/* Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          
          {/* CARD 1: Обект */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-project">
            <div className="flex items-center gap-2 mb-4">
              <Building2 className="w-5 h-5 text-yellow-500" />
              <h3 className="font-semibold text-white">Обект</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-400">Номер:</span>
                <span className="text-white font-mono">{project.code}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Име:</span>
                <span className="text-white">{project.name}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Гаранция:</span>
                <Select
                  value={project.warranty_months?.toString() || ""}
                  onValueChange={handleWarrantyChange}
                  disabled={savingWarranty}
                >
                  <SelectTrigger className="w-32 h-8 bg-gray-700 border-gray-600 text-sm">
                    <SelectValue placeholder="Избери" />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700">
                    {WARRANTY_OPTIONS.map(opt => (
                      <SelectItem key={opt.value} value={opt.value.toString()}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {project.address_text && (
                <div className="pt-2 border-t border-gray-700">
                  <span className="text-gray-400 text-xs">Адрес:</span>
                  <p className="text-white text-sm mt-1">{project.address_text}</p>
                </div>
              )}
            </div>
          </div>

          {/* CARD 2: Клиент/Контакт */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-client">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                {client.owner_type === "company" ? (
                  <Building2 className="w-5 h-5 text-blue-500" />
                ) : (
                  <User className="w-5 h-5 text-green-500" />
                )}
                <h3 className="font-semibold text-white">Клиент</h3>
              </div>
              <div className="flex items-center gap-1">
                {client.owner_data && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowClientModal(true)}
                    className="text-gray-400 hover:text-white"
                    title="Преглед"
                  >
                    <Eye className="w-4 h-4" />
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowClientPicker(true)}
                  className="text-yellow-400 hover:text-yellow-300"
                  title={client.owner_data ? "Смени клиент" : "Избери клиент"}
                >
                  <UserPlus className="w-4 h-4" />
                </Button>
              </div>
            </div>
            
            {client.owner_data ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="text-xs">
                    {client.owner_type === "company" ? "Фирма" : "Частно лице"}
                  </Badge>
                </div>
                {client.owner_data.type === "company" ? (
                  <>
                    <p className="text-white font-medium">{client.owner_data.name}</p>
                    <div className="flex items-center gap-2 text-gray-400">
                      <Hash className="w-3 h-3" />
                      <span>ЕИК: {client.owner_data.eik}</span>
                    </div>
                    {client.owner_data.vat_number && (
                      <div className="flex items-center gap-2 text-gray-400">
                        <FileText className="w-3 h-3" />
                        <span>ДДС: {client.owner_data.vat_number}</span>
                      </div>
                    )}
                    {client.owner_data.mol && (
                      <div className="flex items-center gap-2 text-gray-400">
                        <User className="w-3 h-3" />
                        <span>МОЛ: {client.owner_data.mol}</span>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <p className="text-white font-medium">
                      {client.owner_data.first_name} {client.owner_data.last_name}
                    </p>
                    {client.owner_data.egn && (
                      <div className="flex items-center gap-2 text-gray-400">
                        <Hash className="w-3 h-3" />
                        <span>ЕГН: {client.owner_data.egn?.slice(0,2)}****{client.owner_data.egn?.slice(-2)}</span>
                      </div>
                    )}
                  </>
                )}
                {client.owner_data.phone && (
                  <div className="flex items-center gap-2 text-gray-400">
                    <Phone className="w-3 h-3" />
                    <span>{client.owner_data.phone}</span>
                  </div>
                )}
                {client.owner_data.email && (
                  <div className="flex items-center gap-2 text-gray-400">
                    <Mail className="w-3 h-3" />
                    <span>{client.owner_data.email}</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-4">
                <p className="text-gray-500 text-sm mb-3">Няма избран клиент</p>
                <Button
                  size="sm"
                  onClick={() => setShowClientPicker(true)}
                  className="bg-yellow-500 hover:bg-yellow-600 text-black"
                  data-testid="select-client-btn"
                >
                  <UserPlus className="w-4 h-4 mr-2" />
                  Избери клиент
                </Button>
              </div>
            )}
          </div>

          {/* CARD 3: Прогрес/Срокове */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-progress">
            <div className="flex items-center gap-2 mb-4">
              <Clock className="w-5 h-5 text-purple-500" />
              <h3 className="font-semibold text-white">Прогрес</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-400">Начало:</span>
                <span className="text-white">{progress.start_date ? formatDate(progress.start_date) : "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Край (план):</span>
                <span className="text-white">{progress.end_date ? formatDate(progress.end_date) : "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Прогнозни дни:</span>
                <span className="text-white">{progress.planned_days || "—"}</span>
              </div>
              
              {progress.days_total > 0 && (
                <div className="pt-3 border-t border-gray-700 space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-400">Изминало: {progress.days_elapsed} дни</span>
                    <span className="text-gray-400">Оставащи: {progress.days_remaining} дни</span>
                  </div>
                  <Progress value={progress.progress_percent} className="h-2" />
                  <div className="text-center text-yellow-500 font-medium">
                    {progress.progress_percent}% време изминало
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* CARD 4: Персонал */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 md:col-span-2" data-testid="card-team">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Users className="w-5 h-5 text-cyan-500" />
                <h3 className="font-semibold text-white">Персонал ({team.count})</h3>
              </div>
              <div className="text-sm">
                <span className="text-gray-400">Платени заплати: </span>
                <span className="text-green-400 font-medium">{formatCurrency(team.total_salaries_paid, "BGN")}</span>
              </div>
            </div>
            
            {team.members.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow className="border-gray-700">
                    <TableHead className="text-gray-400">Име</TableHead>
                    <TableHead className="text-gray-400">Длъжност</TableHead>
                    <TableHead className="text-gray-400">Роля</TableHead>
                    <TableHead className="text-gray-400 text-right">Действия</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {team.members.map((member, idx) => (
                    <TableRow key={idx} className="border-gray-700">
                      <TableCell className="text-white">{member.name || "—"}</TableCell>
                      <TableCell className="text-gray-400">{member.system_role || "—"}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {member.role_in_project}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" className="text-gray-400 hover:text-white text-xs">
                          Отчет
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-gray-500 text-sm">Няма добавен персонал</p>
            )}
          </div>

          {/* CARD 6: Оферти */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-offers">
            <div className="flex items-center gap-2 mb-4">
              <FileText className="w-5 h-5 text-orange-500" />
              <h3 className="font-semibold text-white">Оферти</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-400">Одобрени:</span>
                <span className="text-white font-medium">{offers.approved_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Без ДДС:</span>
                <span className="text-white">{formatCurrency(offers.total_ex_vat, "BGN")}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">ДДС:</span>
                <span className="text-white">{formatCurrency(offers.total_vat, "BGN")}</span>
              </div>
              <div className="flex justify-between pt-2 border-t border-gray-700">
                <span className="text-gray-400">С ДДС:</span>
                <span className="text-yellow-500 font-medium">{formatCurrency(offers.total_inc_vat, "BGN")}</span>
              </div>
            </div>
          </div>

          {/* CARD 7: Материали */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-materials">
            <div className="flex items-center gap-2 mb-4">
              <Boxes className="w-5 h-5 text-amber-500" />
              <h3 className="font-semibold text-white">Материали</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-400">Без ДДС:</span>
                <span className="text-white">{formatCurrency(materials.total_ex_vat, "BGN")}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">ДДС:</span>
                <span className="text-white">{formatCurrency(materials.total_vat, "BGN")}</span>
              </div>
              <div className="flex justify-between pt-2 border-t border-gray-700">
                <span className="text-gray-400">С ДДС:</span>
                <span className="text-yellow-500 font-medium">{formatCurrency(materials.total_inc_vat, "BGN")}</span>
              </div>
            </div>
            {materials.total_ex_vat === 0 && (
              <p className="text-gray-500 text-xs mt-2">Няма регистрирани материали</p>
            )}
          </div>

          {/* CARD 8: Баланс */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-balance">
            <div className="flex items-center gap-2 mb-4">
              <Scale className="w-5 h-5 text-emerald-500" />
              <h3 className="font-semibold text-white">Баланс</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-400">Приходи:</span>
                <span className="text-green-400 font-medium">{formatCurrency(balance.income, "BGN")}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Разходи:</span>
                <span className="text-red-400 font-medium">{formatCurrency(balance.expenses, "BGN")}</span>
              </div>
              <div className="flex justify-between pt-2 border-t border-gray-700">
                <span className="text-gray-400">Баланс:</span>
                <span className={`font-bold ${balance.balance >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {formatCurrency(balance.balance, "BGN")}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* CARD 5: Фактури (Full Width) */}
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="card-invoices">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Receipt className="w-5 h-5 text-pink-500" />
              <h3 className="font-semibold text-white">Фактури ({invoices.count})</h3>
            </div>
            <Button
              size="sm"
              onClick={() => navigate(`/finance/invoices/new?project_id=${projectId}`)}
              className="bg-yellow-500 hover:bg-yellow-600 text-black"
            >
              <Plus className="w-4 h-4 mr-1" />
              Нова фактура
            </Button>
          </div>
          
          {invoices.invoices.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="border-gray-700">
                      <TableHead className="text-gray-400">№</TableHead>
                      <TableHead className="text-gray-400">Клиент</TableHead>
                      <TableHead className="text-gray-400">Дата</TableHead>
                      <TableHead className="text-gray-400">Падеж</TableHead>
                      <TableHead className="text-gray-400">Статус</TableHead>
                      <TableHead className="text-gray-400 text-right">Общо</TableHead>
                      <TableHead className="text-gray-400 text-right">Платено</TableHead>
                      <TableHead className="text-gray-400 text-right">Остатък</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {invoices.invoices.map((inv) => (
                      <TableRow key={inv.id} className="border-gray-700 hover:bg-gray-700/30 cursor-pointer"
                        onClick={() => navigate(`/finance/invoices/${inv.id}`)}
                        data-testid={`invoice-row-${inv.id}`}>
                        <TableCell className="text-white font-mono">{inv.invoice_no}</TableCell>
                        <TableCell className="text-white">{inv.client_name || "—"}</TableCell>
                        <TableCell className="text-gray-400">{inv.issue_date ? formatDate(inv.issue_date) : "—"}</TableCell>
                        <TableCell className="text-gray-400">{inv.due_date ? formatDate(inv.due_date) : "—"}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className={`text-xs ${
                            inv.status === "Paid" ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" :
                            inv.status === "PartiallyPaid" ? "bg-amber-500/20 text-amber-400 border-amber-500/30" :
                            inv.status === "Sent" ? "bg-blue-500/20 text-blue-400 border-blue-500/30" :
                            inv.status === "Overdue" ? "bg-red-500/20 text-red-400 border-red-500/30" :
                            inv.status === "Cancelled" ? "bg-gray-500/20 text-gray-400 border-gray-500/30" :
                            "bg-gray-500/20 text-gray-400 border-gray-500/30"
                          }`}>
                            {inv.status === "Draft" ? "Чернова" : inv.status === "Sent" ? "Издадена" :
                             inv.status === "PartiallyPaid" ? "Частично" : inv.status === "Paid" ? "Платена" :
                             inv.status === "Overdue" ? "Просрочена" : inv.status === "Cancelled" ? "Анулирана" : inv.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right text-white font-mono">{formatCurrency(inv.total, inv.currency)}</TableCell>
                        <TableCell className="text-right text-green-400 font-mono">{formatCurrency(inv.paid_amount, inv.currency)}</TableCell>
                        <TableCell className="text-right text-red-400 font-mono">{formatCurrency(inv.remaining_amount, inv.currency)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              
              {/* Totals */}
              <div className="mt-4 pt-4 border-t border-gray-700 grid grid-cols-3 gap-4 text-sm">
                <div className="text-center">
                  <p className="text-gray-400">Общо фактури</p>
                  <p className="text-white font-bold">{formatCurrency(invoices.totals.total, "BGN")}</p>
                </div>
                <div className="text-center">
                  <p className="text-gray-400">Платено</p>
                  <p className="text-green-400 font-bold">{formatCurrency(invoices.totals.paid, "BGN")}</p>
                </div>
                <div className="text-center">
                  <p className="text-gray-400">Неплатено</p>
                  <p className="text-red-400 font-bold">{formatCurrency(invoices.totals.unpaid, "BGN")}</p>
                </div>
              </div>
            </>
          ) : (
            <p className="text-gray-500 text-sm">Няма издадени фактури</p>
          )}
        </div>

        {/* Project Material Ledger */}
        <ProjectMaterialLedger projectId={projectId} />

        {/* Extra Offers Section */}
        {offers.extra_offers && offers.extra_offers.length > 0 && (
          <div className="bg-gray-800/50 border border-amber-500/20 rounded-lg p-4" data-testid="card-extra-offers">
            <div className="flex items-center gap-2 mb-4">
              <FileText className="w-5 h-5 text-amber-500" />
              <h3 className="font-semibold text-white">Допълнителни оферти</h3>
              <Badge variant="outline" className="text-[10px] bg-amber-500/15 text-amber-400 border-amber-500/30">{offers.extra_offers.length}</Badge>
            </div>
            <div className="space-y-2">
              {offers.extra_offers.map((eo) => {
                const sc = {
                  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30", Sent: "bg-blue-500/20 text-blue-400 border-blue-500/30",
                  Accepted: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30", Rejected: "bg-red-500/20 text-red-400 border-red-500/30",
                  NeedsRevision: "bg-amber-500/20 text-amber-400 border-amber-500/30",
                };
                const sl = {
                  Draft: "Чернова", Sent: "Изпратена", Accepted: "Одобрена",
                  Rejected: "Отказана", NeedsRevision: "Корекция",
                };
                return (
                  <div key={eo.id} className="flex items-center justify-between p-3 rounded-lg bg-muted/15 hover:bg-muted/25 cursor-pointer border border-gray-700/50 hover:border-amber-500/30 transition-colors"
                    onClick={() => navigate(`/offers/${eo.id}`)} data-testid={`extra-offer-${eo.id}`}>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="font-mono text-sm text-amber-400 font-medium">{eo.offer_no}</span>
                        <Badge variant="outline" className={`text-[10px] ${sc[eo.status] || ""}`}>{sl[eo.status] || eo.status}</Badge>
                        {eo.version > 1 && <span className="text-[10px] text-muted-foreground">v{eo.version}</span>}
                      </div>
                      <p className="text-sm text-gray-300 truncate">{eo.title}</p>
                    </div>
                    <div className="text-right flex-shrink-0 ml-4">
                      <p className="font-mono text-sm font-bold text-white">{formatCurrency(eo.total || 0, eo.currency || "BGN")}</p>
                      <p className="text-[10px] text-gray-500">{eo.sent_at ? `Изпр. ${formatDate(eo.sent_at)}` : formatDate(eo.created_at)}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Extra Works Draft Panel */}
        <ExtraWorksDraftPanel projectId={projectId} refreshKey={extraWorkRefresh} />

        {/* Client Details Modal */}
        <Dialog open={showClientModal} onOpenChange={setShowClientModal}>
          <DialogContent className="bg-gray-900 border-gray-700 text-white max-w-md">
            <DialogHeader>
              <DialogTitle>Данни за клиента</DialogTitle>
            </DialogHeader>
            {client.owner_data && (
              <div className="space-y-3 text-sm">
                <div className="flex items-center gap-2 pb-2 border-b border-gray-700">
                  {client.owner_data.type === "company" ? (
                    <Building2 className="w-5 h-5 text-blue-500" />
                  ) : (
                    <User className="w-5 h-5 text-green-500" />
                  )}
                  <Badge>{client.owner_data.type === "company" ? "Фирма" : "Частно лице"}</Badge>
                </div>
                
                {client.owner_data.type === "company" ? (
                  <>
                    <div><span className="text-gray-400">Име:</span> <span className="text-white">{client.owner_data.name}</span></div>
                    <div><span className="text-gray-400">ЕИК:</span> <span className="text-white font-mono">{client.owner_data.eik}</span></div>
                    {client.owner_data.vat_number && <div><span className="text-gray-400">ДДС номер:</span> <span className="text-white font-mono">{client.owner_data.vat_number}</span></div>}
                    {client.owner_data.mol && <div><span className="text-gray-400">МОЛ:</span> <span className="text-white">{client.owner_data.mol}</span></div>}
                    {client.owner_data.address && <div><span className="text-gray-400">Адрес:</span> <span className="text-white">{client.owner_data.address}</span></div>}
                  </>
                ) : (
                  <>
                    <div><span className="text-gray-400">Име:</span> <span className="text-white">{client.owner_data.first_name} {client.owner_data.last_name}</span></div>
                    {client.owner_data.egn && <div><span className="text-gray-400">ЕГН:</span> <span className="text-white font-mono">{client.owner_data.egn?.slice(0,2)}****{client.owner_data.egn?.slice(-2)}</span></div>}
                  </>
                )}
                
                {client.owner_data.phone && <div><span className="text-gray-400">Телефон:</span> <span className="text-white">{client.owner_data.phone}</span></div>}
                {client.owner_data.email && <div><span className="text-gray-400">Имейл:</span> <span className="text-white">{client.owner_data.email}</span></div>}
                {client.owner_data.notes && (
                  <div className="pt-2 border-t border-gray-700">
                    <span className="text-gray-400">Бележки:</span>
                    <p className="text-white mt-1">{client.owner_data.notes}</p>
                  </div>
                )}
              </div>
            )}
          </DialogContent>
        </Dialog>

        {/* Client Picker Modal */}
        <ClientPickerModal
          projectId={projectId}
          open={showClientPicker}
          onOpenChange={setShowClientPicker}
          onClientSelected={fetchDashboard}
        />

        {/* Extra Work Modal */}
        <ExtraWorkModal
          projectId={projectId}
          open={showExtraWork}
          onOpenChange={setShowExtraWork}
          onCreated={() => setExtraWorkRefresh(prev => prev + 1)}
        />
      </div>
  );
}
