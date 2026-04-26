import React, { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { DatePicker } from "@/components/ui/date-picker";
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
import { Textarea } from "@/components/ui/textarea";
import { Plus, Search, FolderKanban, Users, Loader2, Eye, ChevronDown, ChevronRight } from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Active: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Paused: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  Completed: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Cancelled: "bg-red-500/20 text-red-400 border-red-500/30",
  Stopped: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  Overhead: "bg-violet-500/20 text-violet-400 border-violet-500/30",
  Archived: "bg-gray-500/20 text-gray-300 border-gray-500/30",
};

const STATUS_TRANSITIONS = {
  Draft: ["Active", "Cancelled"],
  Active: ["Paused", "Stopped", "Completed"],
  Paused: ["Active", "Stopped", "Cancelled"],
  Stopped: ["Active", "Cancelled"],
  Completed: ["Archived"],
  Cancelled: ["Archived"],
  Overhead: ["Active", "Archived"],
  Archived: [],
};

const STATUS_BG = {
  Draft: "Чернова", Active: "Активен", Paused: "Спрян", Stopped: "Спрян",
  Completed: "Приключен", Cancelled: "Отменен", Overhead: "Режиен", Archived: "Архивиран",
};

const TYPE_COLORS = {
  Billable: "bg-primary/20 text-primary border-primary/30",
  Overhead: "bg-violet-500/20 text-violet-400 border-violet-500/30",
  Warranty: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
};

const EMPTY_FORM = {
  code: "", name: "", status: "Draft", type: "Billable",
  start_date: "", end_date: "", planned_days: "",
  budget_planned: "", default_site_manager_id: "", tags: "", notes: "",
  address_text: "", owner_type: "", owner_id: "", parent_project_id: "",
};

export default function ProjectsListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [projects, setProjects] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [filterStatus, setFilterStatus] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [search, setSearch] = useState("");
  const [expandedParents, setExpandedParents] = useState({});

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (filterStatus !== "all") params.append("status", filterStatus);
      if (filterType !== "all") params.append("type", filterType);
      if (search) params.append("search", search);
      const [projRes, usersRes] = await Promise.all([
        API.get(`/projects?${params.toString()}`),
        API.get("/users"),
      ]);
      setProjects(projRes.data);
      setUsers(usersRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterType, search]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Tree structure: parents + children grouped
  const parents = projects.filter(p => !p.parent_project_id);
  const childrenMap = {};
  projects.filter(p => p.parent_project_id).forEach(p => {
    if (!childrenMap[p.parent_project_id]) childrenMap[p.parent_project_id] = [];
    childrenMap[p.parent_project_id].push(p);
  });
  // Sort children by code
  Object.values(childrenMap).forEach(arr => arr.sort((a, b) => (a.code || "").localeCompare(b.code || "")));

  // Default expand all parents with children
  useEffect(() => {
    const exp = {};
    projects.filter(p => !p.parent_project_id).forEach(p => {
      if (childrenMap[p.id]?.length) exp[p.id] = true;
    });
    setExpandedParents(exp);
  }, [projects.length]); // eslint-disable-line

  const toggleParent = (id) => setExpandedParents(prev => ({ ...prev, [id]: !prev[id] }));

  // Auto-open create dialog for sub-project
  useEffect(() => {
    const childOf = searchParams.get("createChild");
    const parentName = searchParams.get("parentName");
    if (childOf) {
      setForm({ ...EMPTY_FORM, parent_project_id: childOf, name: parentName ? `${parentName} — ` : "" });
      setDialogOpen(true);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const managers = users.filter((u) => ["Admin", "Owner", "SiteManager"].includes(u.role));

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  };

  const openEdit = (p) => {
    setEditing(p);
    setForm({
      code: p.code, name: p.name, status: p.status, type: p.type,
      start_date: p.start_date || "", end_date: p.end_date || "",
      planned_days: p.planned_days?.toString() || "",
      budget_planned: p.budget_planned?.toString() || "",
      default_site_manager_id: p.default_site_manager_id || "",
      tags: (p.tags || []).join(", "),
      notes: p.notes || "",
      address_text: p.address_text || "",
      owner_type: p.owner_type || "",
      owner_id: p.owner_id || "",
      _origStatus: p.status,
      _clientName: "",
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        ...form,
        planned_days: form.planned_days ? parseInt(form.planned_days) : null,
        budget_planned: form.budget_planned ? parseFloat(form.budget_planned) : null,
        tags: form.tags ? form.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        default_site_manager_id: form.default_site_manager_id === "none" ? null : form.default_site_manager_id || null,
        address_text: form.address_text || null,
        owner_type: form.owner_type || null,
        owner_id: form.owner_id || null,
      };
      if (editing) {
        const { code, ...updatePayload } = payload;
        await API.put(`/projects/${editing.id}`, updatePayload);
      } else {
        await API.post("/projects", payload);
      }
      setDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const getStatusKey = (status) => status?.toLowerCase() || 'draft';
  const getTypeKey = (type) => type?.toLowerCase() || 'billable';

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1400px]" data-testid="projects-list-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("projects.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("projects.projectsCount", { count: projects.length })}</p>
        </div>
        <Button onClick={openCreate} data-testid="create-project-button">
          <Plus className="w-4 h-4 mr-2" /> {t("projects.newProject")}
        </Button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6" data-testid="project-filters">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder={t("projects.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-card border-border"
            data-testid="project-search-input"
          />
        </div>
        <Select value={filterStatus} onValueChange={setFilterStatus}>
          <SelectTrigger className="w-[150px] bg-card" data-testid="project-status-filter">
            <SelectValue placeholder={t("common.status")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allStatuses")}</SelectItem>
            {["Draft", "Active", "Paused", "Completed", "Cancelled"].map((s) => (
              <SelectItem key={s} value={s}>{t(`projects.status.${getStatusKey(s)}`)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="w-[150px] bg-card" data-testid="project-type-filter">
            <SelectValue placeholder={t("common.type")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allTypes")}</SelectItem>
            {["Billable", "Overhead", "Warranty"].map((tp) => (
              <SelectItem key={tp} value={tp}>{t(`projects.type.${getTypeKey(tp)}`)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="projects-table">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("projects.projectCode")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.name")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.status")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.type")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("projects.siteManager")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("projects.period")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("projects.team")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {projects.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center py-16">
                  <FolderKanban className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
                  <p className="text-muted-foreground">{t("projects.noProjects")}</p>
                </TableCell>
              </TableRow>
            ) : (
              parents.map((p) => {
                const children = childrenMap[p.id] || [];
                const hasChildren = children.length > 0;
                const isExpanded = expandedParents[p.id];
                return (
                  <React.Fragment key={p.id}>
                    {/* Parent row */}
                    <TableRow className="table-row-hover cursor-pointer" data-testid={`project-row-${p.id}`}>
                      <TableCell className="font-mono text-sm text-primary font-semibold">
                        <div className="flex items-center gap-1">
                          {hasChildren && (
                            <button onClick={(e) => { e.stopPropagation(); toggleParent(p.id); }} className="p-0.5 hover:bg-muted rounded">
                              {isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />}
                            </button>
                          )}
                          {p.code}
                        </div>
                      </TableCell>
                      <TableCell className="font-medium text-foreground">
                        {p.name}
                        {hasChildren && <Badge variant="outline" className="ml-2 text-[9px] bg-violet-500/15 text-violet-300 border-violet-500/30">{children.length} под-обекта</Badge>}
                      </TableCell>
                      <TableCell><Badge variant="outline" className={`text-xs ${STATUS_COLORS[p.status] || ""}`}>{t(`projects.status.${getStatusKey(p.status)}`)}</Badge></TableCell>
                      <TableCell><Badge variant="outline" className={`text-xs ${TYPE_COLORS[p.type] || ""}`}>{t(`projects.type.${getTypeKey(p.type)}`)}</Badge></TableCell>
                      <TableCell className="text-sm text-muted-foreground">{p.site_manager_name || "-"}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{p.start_date ? formatDate(p.start_date) : "?"} - {p.end_date ? formatDate(p.end_date) : "?"}</TableCell>
                      <TableCell><div className="flex items-center gap-1 text-sm text-muted-foreground"><Users className="w-3.5 h-3.5" /> {p.team_count}</div></TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => navigate(`/projects/${p.id}`)}><Eye className="w-3.5 h-3.5" /></Button>
                          <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); openEdit(p); }}>{t("common.edit")}</Button>
                        </div>
                      </TableCell>
                    </TableRow>
                    {/* Children rows (indented, with letter badge) */}
                    {isExpanded && children.map((child) => {
                      const letter = child.code?.split("-").pop() || "";
                      return (
                        <TableRow key={child.id} className="table-row-hover cursor-pointer border-l-2 border-l-violet-500/30" data-testid={`project-row-${child.id}`}>
                          <TableCell className="font-mono text-sm text-muted-foreground pl-10">{child.code}</TableCell>
                          <TableCell className="pl-10">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-violet-500/20 text-violet-300 text-xs font-bold flex-shrink-0">{letter}</span>
                              <span className="font-medium text-foreground">{child.name}</span>
                            </div>
                          </TableCell>
                          <TableCell><Badge variant="outline" className={`text-xs ${STATUS_COLORS[child.status] || ""}`}>{t(`projects.status.${getStatusKey(child.status)}`)}</Badge></TableCell>
                          <TableCell><Badge variant="outline" className={`text-xs ${TYPE_COLORS[child.type] || ""}`}>{t(`projects.type.${getTypeKey(child.type)}`)}</Badge></TableCell>
                          <TableCell className="text-sm text-muted-foreground">{child.site_manager_name || "-"}</TableCell>
                          <TableCell className="text-sm text-muted-foreground">{child.start_date ? formatDate(child.start_date) : "?"} - {child.end_date ? formatDate(child.end_date) : "?"}</TableCell>
                          <TableCell><div className="flex items-center gap-1 text-sm text-muted-foreground"><Users className="w-3.5 h-3.5" /> {child.team_count}</div></TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button variant="ghost" size="sm" onClick={() => navigate(`/projects/${child.id}`)}><Eye className="w-3.5 h-3.5" /></Button>
                              <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); openEdit(child); }}>{t("common.edit")}</Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </React.Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {/* Create/Edit Wizard */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[600px] bg-card border-border max-h-[90vh] overflow-y-auto" data-testid="project-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? t("projects.editProject") : t("projects.createProject")}</DialogTitle>
          </DialogHeader>
          <ProjectWizard form={form} setForm={setForm} editing={editing} managers={managers} saving={saving} onSave={handleSave} statusTransitions={editing ? (STATUS_TRANSITIONS[form._origStatus] || []) : null} />
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProjectWizard({ form, setForm, editing, managers, saving, onSave, statusTransitions }) {
  const { t } = useTranslation();
  const [step, setStep] = useState(0);
  const [clients, setClients] = useState([]);
  const [clientSearch, setClientSearch] = useState("");
  const [showNewClient, setShowNewClient] = useState(false);
  const [newClient, setNewClient] = useState({ type: "company", companyName: "", fullName: "", eik: "", phone: "", email: "" });

  useEffect(() => {
    API.get("/clients?limit=100").then(r => setClients(r.data?.items || r.data || [])).catch(() => {});
  }, []);

  const filteredClients = clients.filter(c => {
    if (!clientSearch) return true;
    const q = clientSearch.toLowerCase();
    return (c.companyName || c.fullName || c.name || "").toLowerCase().includes(q);
  });

  const handleCreateClient = async () => {
    try {
      const body = newClient.type === "company"
        ? { type: "company", companyName: newClient.companyName, eik: newClient.eik, phone: newClient.phone, email: newClient.email }
        : { type: "person", fullName: newClient.fullName, phone: newClient.phone, email: newClient.email };
      const res = await API.post("/clients", body);
      const created = res.data;
      setClients(prev => [created, ...prev]);
      setForm(f => ({ ...f, owner_id: created.id, owner_type: newClient.type, _clientName: newClient.type === "company" ? newClient.companyName : newClient.fullName }));
      setShowNewClient(false);
      setNewClient({ type: "company", companyName: "", fullName: "", eik: "", phone: "", email: "" });
    } catch { }
  };

  const STEPS = [
    { id: "basic", label: "1. Основни" },
    { id: "client", label: "2. Клиент" },
    { id: "details", label: "3. Детайли" },
    { id: "budget", label: "4. Бюджет" },
  ];

  return (
    <div className="space-y-4 pt-2">
      {/* Step tabs */}
      <div className="flex items-center gap-1">
        {STEPS.map((s, i) => (
          <button key={s.id} onClick={() => setStep(i)} className={`px-3 py-1.5 rounded-lg text-[10px] font-medium transition-colors ${step === i ? "bg-primary/15 text-primary border border-primary/30" : "text-muted-foreground border border-transparent hover:text-foreground"}`}>{s.label}</button>
        ))}
      </div>

      {/* Step 1: Basic */}
      {step === 0 && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div><Label className="text-muted-foreground text-xs">Код *</Label><Input value={form.code} onChange={e => setForm({...form, code: e.target.value.toUpperCase()})} placeholder="APT-001" className="bg-background font-mono" disabled={!!editing} /></div>
            <div><Label className="text-muted-foreground text-xs">Име *</Label><Input value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="Апартамент - Редута" className="bg-background" /></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-muted-foreground text-xs">Статус</Label>
              <Select value={form.status} onValueChange={v => setForm({...form, status: v})}>
                <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {editing && statusTransitions ? (
                    <>
                      <SelectItem value={form._origStatus || form.status}>{STATUS_BG[form._origStatus || form.status] || form.status} (текущ)</SelectItem>
                      {statusTransitions.map(s => <SelectItem key={s} value={s}>{STATUS_BG[s] || s}</SelectItem>)}
                    </>
                  ) : (
                    ["Draft", "Active", "Overhead"].map(s => <SelectItem key={s} value={s}>{STATUS_BG[s]}</SelectItem>)
                  )}
                </SelectContent>
              </Select>
              {form.status === "Completed" && <p className="text-[9px] text-amber-400 mt-1">Приключен: блокира нови разходи и отчети</p>}
            </div>
            <div>
              <Label className="text-muted-foreground text-xs">Тип</Label>
              <Select value={form.type} onValueChange={v => setForm({...form, type: v})}>
                <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["Billable", "Overhead", "Warranty"].map(t => <SelectItem key={t} value={t}>{t === "Billable" ? "Фактурируем" : t === "Overhead" ? "Режиен" : "Гаранционен"}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      )}

      {/* Step 2: Client */}
      {step === 1 && (
        <div className="space-y-3">
          {form.owner_id && form._clientName && (
            <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/30 p-3 flex items-center justify-between">
              <div><p className="text-xs font-medium text-emerald-400">{form._clientName}</p><p className="text-[9px] text-muted-foreground">{form.owner_type === "company" ? "Фирма" : "Частно лице"}</p></div>
              <Button variant="ghost" size="sm" className="text-xs" onClick={() => setForm({...form, owner_id: "", owner_type: "", _clientName: ""})}>Промени</Button>
            </div>
          )}
          {!form.owner_id && !showNewClient && (
            <>
              <Input value={clientSearch} onChange={e => setClientSearch(e.target.value)} placeholder="Търси клиент..." className="bg-background h-9" />
              <div className="max-h-[200px] overflow-y-auto space-y-1">
                {filteredClients.slice(0, 10).map(c => (
                  <button key={c.id} onClick={() => setForm({...form, owner_id: c.id, owner_type: c.type || "company", _clientName: c.companyName || c.fullName || c.name})} className="w-full text-left px-3 py-2 rounded-lg hover:bg-muted/30 text-xs border border-transparent hover:border-border">
                    <span className="font-medium">{c.companyName || c.fullName || c.name}</span>
                    <Badge variant="outline" className="ml-2 text-[8px]">{c.type === "person" ? "Лице" : "Фирма"}</Badge>
                  </button>
                ))}
              </div>
              <Button variant="outline" size="sm" className="w-full text-xs" onClick={() => setShowNewClient(true)}>+ Нов клиент</Button>
            </>
          )}
          {showNewClient && (
            <div className="space-y-2 p-3 rounded-lg border border-border">
              <p className="text-xs font-medium">Нов клиент</p>
              <div className="flex gap-2">
                <Button variant={newClient.type === "company" ? "default" : "outline"} size="sm" className="text-xs" onClick={() => setNewClient({...newClient, type: "company"})}>Фирма</Button>
                <Button variant={newClient.type === "person" ? "default" : "outline"} size="sm" className="text-xs" onClick={() => setNewClient({...newClient, type: "person"})}>Частно лице</Button>
              </div>
              {newClient.type === "company" ? (
                <>
                  <Input value={newClient.companyName} onChange={e => setNewClient({...newClient, companyName: e.target.value})} placeholder="Име на фирма *" className="bg-background h-9 text-xs" />
                  <Input value={newClient.eik} onChange={e => setNewClient({...newClient, eik: e.target.value})} placeholder="ЕИК (9 или 13 цифри)" className="bg-background h-9 text-xs" />
                </>
              ) : (
                <Input value={newClient.fullName} onChange={e => setNewClient({...newClient, fullName: e.target.value})} placeholder="Име и фамилия *" className="bg-background h-9 text-xs" />
              )}
              <Input value={newClient.phone} onChange={e => setNewClient({...newClient, phone: e.target.value})} placeholder="Телефон" className="bg-background h-9 text-xs" />
              <Input value={newClient.email} onChange={e => setNewClient({...newClient, email: e.target.value})} placeholder="Email" className="bg-background h-9 text-xs" />
              <p className="text-[8px] text-muted-foreground">Клиентът ще бъде записан в базата и свързан с обекта</p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" className="text-xs flex-1" onClick={() => setShowNewClient(false)}>Отказ</Button>
                <Button size="sm" className="text-xs flex-1" onClick={handleCreateClient} disabled={newClient.type === "company" ? !newClient.companyName : !newClient.fullName}>Запиши в базата</Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Step 3: Details */}
      {step === 2 && (
        <div className="space-y-3">
          <div><Label className="text-muted-foreground text-xs">Адрес</Label><Input value={form.address_text || ""} onChange={e => setForm({...form, address_text: e.target.value})} placeholder="ул. Витоша 15, София" className="bg-background" /></div>
          <div>
            <Label className="text-muted-foreground text-xs">Отговорник</Label>
            <Select value={form.default_site_manager_id || "none"} onValueChange={v => setForm({...form, default_site_manager_id: v === "none" ? "" : v})}>
              <SelectTrigger className="bg-background"><SelectValue placeholder="Изберете" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Без</SelectItem>
                {managers.map(m => <SelectItem key={m.id} value={m.id}>{m.first_name} {m.last_name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div><Label className="text-muted-foreground text-xs">Тагове (през запетая)</Label><Input value={form.tags} onChange={e => setForm({...form, tags: e.target.value})} placeholder="ремонт, софия, апартамент" className="bg-background" /></div>
          <div><Label className="text-muted-foreground text-xs">Бележки</Label><Textarea value={form.notes} onChange={e => setForm({...form, notes: e.target.value})} className="bg-background min-h-[60px]" /></div>
        </div>
      )}

      {/* Step 4: Budget */}
      {step === 3 && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div><Label className="text-muted-foreground text-xs">Начална дата</Label><DatePicker value={form.start_date} onChange={d => setForm({...form, start_date: d})} placeholder="Избери" /></div>
            <div><Label className="text-muted-foreground text-xs">Крайна дата</Label><DatePicker value={form.end_date} onChange={d => setForm({...form, end_date: d})} placeholder="Избери" /></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label className="text-muted-foreground text-xs">Планирани дни</Label><Input type="number" value={form.planned_days} onChange={e => setForm({...form, planned_days: e.target.value})} className="bg-background" /></div>
            <div><Label className="text-muted-foreground text-xs">Бюджет (EUR)</Label><Input type="number" step="0.01" value={form.budget_planned} onChange={e => setForm({...form, budget_planned: e.target.value})} className="bg-background" /></div>
          </div>
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-2 border-t border-border">
        <Button variant="ghost" size="sm" disabled={step === 0} onClick={() => setStep(s => s - 1)} className="text-xs">← Назад</Button>
        <div className="flex gap-2">
          {step < 3 && <Button variant="outline" size="sm" onClick={() => setStep(s => s + 1)} className="text-xs">Напред →</Button>}
          <Button onClick={onSave} disabled={saving || !form.code || !form.name} className="text-xs" data-testid="project-save-button">
            {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
            {editing ? "Запази" : "Създай обект"}
          </Button>
        </div>
      </div>
    </div>
  );
}
