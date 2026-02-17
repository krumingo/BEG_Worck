import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Layers,
  Plus,
  Pencil,
  Trash2,
  Filter,
  Loader2,
} from "lucide-react";

const UNITS = ["m2", "m", "pcs", "hours", "lot", "kg", "l"];

export default function ActivityCatalogPage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectIdParam = searchParams.get("projectId") || "";

  const [activities, setActivities] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [projectFilter, setProjectFilter] = useState(projectIdParam);
  const [showInactive, setShowInactive] = useState(false);

  const canManage = ["Admin", "Owner", "SiteManager"].includes(user?.role);

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [saving, setSaving] = useState(false);

  // Form state
  const [formProjectId, setFormProjectId] = useState("");
  const [formCode, setFormCode] = useState("");
  const [formName, setFormName] = useState("");
  const [formUnit, setFormUnit] = useState("pcs");
  const [formMaterial, setFormMaterial] = useState(0);
  const [formLabor, setFormLabor] = useState(0);
  const [formHours, setFormHours] = useState("");
  const [formActive, setFormActive] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [activitiesRes, projectsRes] = await Promise.all([
        API.get(`/activity-catalog${projectFilter ? `?project_id=${projectFilter}` : ""}${showInactive ? "&active_only=false" : ""}`),
        API.get("/projects"),
      ]);
      setActivities(activitiesRes.data);
      setProjects(projectsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [projectFilter, showInactive]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openCreate = () => {
    setEditingItem(null);
    setFormProjectId(projectFilter || "");
    setFormCode("");
    setFormName("");
    setFormUnit("pcs");
    setFormMaterial(0);
    setFormLabor(0);
    setFormHours("");
    setFormActive(true);
    setDialogOpen(true);
  };

  const openEdit = (item) => {
    setEditingItem(item);
    setFormProjectId(item.project_id);
    setFormCode(item.code || "");
    setFormName(item.name);
    setFormUnit(item.default_unit);
    setFormMaterial(item.default_material_unit_cost);
    setFormLabor(item.default_labor_unit_cost);
    setFormHours(item.default_labor_hours_per_unit || "");
    setFormActive(item.active);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formProjectId || !formName) {
      alert("Project and name are required");
      return;
    }
    setSaving(true);
    try {
      const data = {
        project_id: formProjectId,
        code: formCode || null,
        name: formName,
        default_unit: formUnit,
        default_material_unit_cost: parseFloat(formMaterial) || 0,
        default_labor_unit_cost: parseFloat(formLabor) || 0,
        default_labor_hours_per_unit: formHours ? parseFloat(formHours) : null,
        active: formActive,
      };
      if (editingItem) {
        await API.put(`/activity-catalog/${editingItem.id}`, data);
      } else {
        await API.post("/activity-catalog", data);
      }
      setDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (item) => {
    if (!confirm(`Delete activity "${item.name}"?`)) return;
    try {
      await API.delete(`/activity-catalog/${item.id}`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to delete");
    }
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(amount || 0);
  };

  return (
    <div className="p-8 max-w-[1200px]" data-testid="activity-catalog-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Activity Catalog</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage reusable activities for BOQ/offers</p>
        </div>
        {canManage && (
          <Button onClick={openCreate} data-testid="create-activity-btn">
            <Plus className="w-4 h-4 mr-2" /> New Activity
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6 flex-wrap" data-testid="catalog-filters">
        <Select value={projectFilter} onValueChange={(v) => {
          setProjectFilter(v === "all" ? "" : v);
          if (v === "all") searchParams.delete("projectId");
          else searchParams.set("projectId", v);
          setSearchParams(searchParams);
        }}>
          <SelectTrigger className="w-[250px] bg-card" data-testid="project-filter">
            <Filter className="w-4 h-4 mr-2 text-muted-foreground" />
            <SelectValue placeholder="All Projects" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Projects</SelectItem>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex items-center gap-2">
          <Switch checked={showInactive} onCheckedChange={setShowInactive} data-testid="show-inactive-switch" />
          <Label className="text-sm text-muted-foreground">Show inactive</Label>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="activities-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Code</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Name</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Project</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Unit</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Material</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Labor</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                {canManage && <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {activities.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={canManage ? 8 : 7} className="text-center py-12 text-muted-foreground">
                    <Layers className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>No activities found</p>
                    {canManage && projectFilter && (
                      <Button variant="outline" className="mt-4" onClick={openCreate}>
                        Create your first activity
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                activities.map((item) => {
                  const project = projects.find(p => p.id === item.project_id);
                  return (
                    <TableRow key={item.id} className="table-row-hover" data-testid={`activity-row-${item.id}`}>
                      <TableCell className="font-mono text-xs text-primary">{item.code || "-"}</TableCell>
                      <TableCell className="font-medium text-foreground">{item.name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {project ? `${project.code}` : "-"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">{item.default_unit}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{formatCurrency(item.default_material_unit_cost)}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{formatCurrency(item.default_labor_unit_cost)}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={`text-xs ${item.active ? "text-emerald-400 border-emerald-500/30" : "text-gray-400 border-gray-500/30"}`}>
                          {item.active ? "Active" : "Inactive"}
                        </Badge>
                      </TableCell>
                      {canManage && (
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button variant="ghost" size="sm" onClick={() => openEdit(item)} data-testid={`edit-btn-${item.id}`}>
                              <Pencil className="w-4 h-4" />
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => handleDelete(item)} className="text-destructive hover:text-destructive" data-testid={`delete-btn-${item.id}`}>
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </div>
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="activity-dialog">
          <DialogHeader>
            <DialogTitle>{editingItem ? "Edit Activity" : "New Activity"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Project *</Label>
              <Select value={formProjectId} onValueChange={setFormProjectId} disabled={!!editingItem}>
                <SelectTrigger className="bg-background" data-testid="form-project-select">
                  <SelectValue placeholder="Select project" />
                </SelectTrigger>
                <SelectContent>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Code (optional)</Label>
                <Input value={formCode} onChange={(e) => setFormCode(e.target.value)} placeholder="e.g., ELEC-001" className="bg-background" data-testid="form-code-input" />
              </div>
              <div className="space-y-2">
                <Label>Unit</Label>
                <Select value={formUnit} onValueChange={setFormUnit}>
                  <SelectTrigger className="bg-background" data-testid="form-unit-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {UNITS.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>Name *</Label>
              <Input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="Activity name" className="bg-background" data-testid="form-name-input" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Material Cost / Unit</Label>
                <Input type="number" value={formMaterial} onChange={(e) => setFormMaterial(e.target.value)} className="bg-background" data-testid="form-material-input" />
              </div>
              <div className="space-y-2">
                <Label>Labor Cost / Unit</Label>
                <Input type="number" value={formLabor} onChange={(e) => setFormLabor(e.target.value)} className="bg-background" data-testid="form-labor-input" />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Labor Hours / Unit (optional)</Label>
              <Input type="number" value={formHours} onChange={(e) => setFormHours(e.target.value)} placeholder="e.g., 0.5" className="bg-background" data-testid="form-hours-input" />
            </div>
            <div className="flex items-center gap-3">
              <Switch checked={formActive} onCheckedChange={setFormActive} data-testid="form-active-switch" />
              <Label>Active</Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving} data-testid="form-save-btn">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              {editingItem ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
