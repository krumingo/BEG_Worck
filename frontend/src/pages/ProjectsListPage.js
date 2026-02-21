import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
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
import { Plus, Search, FolderKanban, Users, Loader2, Eye } from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Active: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Paused: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  Completed: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Cancelled: "bg-red-500/20 text-red-400 border-red-500/30",
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
};

export default function ProjectsListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
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

  const getStatusKey = (status) => status.toLowerCase();
  const getTypeKey = (type) => type.toLowerCase();

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
              projects.map((p) => (
                <TableRow key={p.id} className="table-row-hover cursor-pointer" data-testid={`project-row-${p.id}`}>
                  <TableCell className="font-mono text-sm text-primary font-semibold">{p.code}</TableCell>
                  <TableCell className="font-medium text-foreground">{p.name}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-xs ${STATUS_COLORS[p.status] || ""}`}>
                      {t(`projects.status.${getStatusKey(p.status)}`)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-xs ${TYPE_COLORS[p.type] || ""}`}>
                      {t(`projects.type.${getTypeKey(p.type)}`)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{p.site_manager_name || "-"}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {p.start_date ? formatDate(p.start_date) : "?"} - {p.end_date ? formatDate(p.end_date) : "?"}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1 text-sm text-muted-foreground">
                      <Users className="w-3.5 h-3.5" /> {p.team_count}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => navigate(`/projects/${p.id}`)} data-testid={`view-project-${p.id}`}>
                        <Eye className="w-3.5 h-3.5" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); openEdit(p); }} data-testid={`edit-project-${p.id}`}>
                        {t("common.edit")}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[560px] bg-card border-border max-h-[90vh] overflow-y-auto" data-testid="project-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? t("projects.editProject") : t("projects.createProject")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("projects.projectCode")} *</Label>
                <Input
                  value={form.code}
                  onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                  placeholder="PRJ-001"
                  className="bg-background font-mono"
                  disabled={!!editing}
                  data-testid="project-code-input"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("projects.projectName")} *</Label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder={t("projects.projectName")}
                  className="bg-background"
                  data-testid="project-name-input"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("common.status")}</Label>
                <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                  <SelectTrigger className="bg-background" data-testid="project-status-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["Draft", "Active", "Paused", "Completed", "Cancelled"].map((s) => (
                      <SelectItem key={s} value={s}>{t(`projects.status.${getStatusKey(s)}`)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("common.type")}</Label>
                <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                  <SelectTrigger className="bg-background" data-testid="project-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["Billable", "Overhead", "Warranty"].map((tp) => (
                      <SelectItem key={tp} value={tp}>{t(`projects.type.${getTypeKey(tp)}`)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("projects.startDate")}</Label>
                <Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} className="bg-background" data-testid="project-start-date" />
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("projects.endDate")}</Label>
                <Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} className="bg-background" data-testid="project-end-date" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("projects.plannedDays")}</Label>
                <Input type="number" value={form.planned_days} onChange={(e) => setForm({ ...form, planned_days: e.target.value })} className="bg-background" data-testid="project-planned-days" />
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("projects.budgetEur")}</Label>
                <Input type="number" step="0.01" value={form.budget_planned} onChange={(e) => setForm({ ...form, budget_planned: e.target.value })} className="bg-background" data-testid="project-budget" />
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("projects.siteManager")}</Label>
              <Select value={form.default_site_manager_id || "none"} onValueChange={(v) => setForm({ ...form, default_site_manager_id: v })}>
                <SelectTrigger className="bg-background" data-testid="project-manager-select">
                  <SelectValue placeholder={t("projects.selectManager")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("common.none")}</SelectItem>
                  {managers.map((m) => (
                    <SelectItem key={m.id} value={m.id}>{m.first_name} {m.last_name} ({t(`users.roles.${m.role.toLowerCase()}`)})</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("projects.tags")} ({t("projects.tagsHint")})</Label>
              <Input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder={t("projects.tagsPlaceholder")} className="bg-background" data-testid="project-tags" />
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("common.notes")}</Label>
              <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="bg-background min-h-[80px]" data-testid="project-notes" />
            </div>
            <Button onClick={handleSave} disabled={saving || !form.code || !form.name} className="w-full" data-testid="project-save-button">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              {editing ? t("projects.updateProject") : t("projects.createProject")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
