import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  DollarSign,
  Hash,
  Layers,
  Plus,
  Trash2,
  Loader2,
  Tag,
  FileText,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Active: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Paused: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  Completed: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Cancelled: "bg-red-500/20 text-red-400 border-red-500/30",
};

const TEAM_ROLE_COLORS = {
  SiteManager: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Technician: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Viewer: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

export default function ProjectDetailPage() {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [team, setTeam] = useState([]);
  const [phases, setPhases] = useState([]);
  const [orgUsers, setOrgUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  // Team dialog
  const [teamDialogOpen, setTeamDialogOpen] = useState(false);
  const [teamForm, setTeamForm] = useState({ user_id: "", role_in_project: "Technician" });
  const [addingMember, setAddingMember] = useState(false);

  // Phase dialog
  const [phaseDialogOpen, setPhaseDialogOpen] = useState(false);
  const [phaseForm, setPhaseForm] = useState({ name: "", order: 0, status: "Draft", planned_start: "", planned_end: "" });
  const [editingPhase, setEditingPhase] = useState(null);
  const [savingPhase, setSavingPhase] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [projRes, teamRes, phasesRes, usersRes] = await Promise.all([
        API.get(`/projects/${projectId}`),
        API.get(`/projects/${projectId}/team`),
        API.get(`/projects/${projectId}/phases`),
        API.get("/users"),
      ]);
      setProject(projRes.data);
      setTeam(teamRes.data);
      setPhases(phasesRes.data);
      setOrgUsers(usersRes.data);
    } catch (err) {
      console.error(err);
      if (err.response?.status === 404 || err.response?.status === 403) navigate("/projects");
    } finally {
      setLoading(false);
    }
  }, [projectId, navigate]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleAddMember = async () => {
    if (!teamForm.user_id) return;
    setAddingMember(true);
    try {
      await API.post(`/projects/${projectId}/team`, teamForm);
      setTeamDialogOpen(false);
      setTeamForm({ user_id: "", role_in_project: "Technician" });
      const teamRes = await API.get(`/projects/${projectId}/team`);
      setTeam(teamRes.data);
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to add member");
    } finally {
      setAddingMember(false);
    }
  };

  const handleRemoveMember = async (memberId) => {
    if (!window.confirm("Remove this team member?")) return;
    try {
      await API.delete(`/projects/${projectId}/team/${memberId}`);
      const teamRes = await API.get(`/projects/${projectId}/team`);
      setTeam(teamRes.data);
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to remove member");
    }
  };

  const openCreatePhase = () => {
    setEditingPhase(null);
    setPhaseForm({ name: "", order: phases.length, status: "Draft", planned_start: "", planned_end: "" });
    setPhaseDialogOpen(true);
  };

  const openEditPhase = (ph) => {
    setEditingPhase(ph);
    setPhaseForm({
      name: ph.name, order: ph.order, status: ph.status,
      planned_start: ph.planned_start || "", planned_end: ph.planned_end || "",
    });
    setPhaseDialogOpen(true);
  };

  const handleSavePhase = async () => {
    setSavingPhase(true);
    try {
      const payload = {
        ...phaseForm,
        order: parseInt(phaseForm.order) || 0,
        planned_start: phaseForm.planned_start || null,
        planned_end: phaseForm.planned_end || null,
      };
      if (editingPhase) {
        await API.put(`/projects/${projectId}/phases/${editingPhase.id}`, payload);
      } else {
        await API.post(`/projects/${projectId}/phases`, payload);
      }
      setPhaseDialogOpen(false);
      const phasesRes = await API.get(`/projects/${projectId}/phases`);
      setPhases(phasesRes.data);
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to save phase");
    } finally {
      setSavingPhase(false);
    }
  };

  const handleDeletePhase = async (phaseId) => {
    if (!window.confirm("Delete this phase?")) return;
    try {
      await API.delete(`/projects/${projectId}/phases/${phaseId}`);
      const phasesRes = await API.get(`/projects/${projectId}/phases`);
      setPhases(phasesRes.data);
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to delete phase");
    }
  };

  // Users not already on the team
  const availableUsers = orgUsers.filter((u) => !team.some((m) => m.user_id === u.id));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!project) return null;

  return (
    <div className="p-8 max-w-[1200px]" data-testid="project-detail-page">
      {/* Back button + header */}
      <Button variant="ghost" size="sm" className="mb-4 text-muted-foreground" onClick={() => navigate("/projects")} data-testid="back-to-projects">
        <ArrowLeft className="w-4 h-4 mr-2" /> Back to Projects
      </Button>

      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="font-mono text-sm text-primary font-bold">{project.code}</span>
            <Badge variant="outline" className={`text-xs ${STATUS_COLORS[project.status] || ""}`}>{project.status}</Badge>
          </div>
          <h1 className="text-2xl font-bold text-foreground" data-testid="project-title">{project.name}</h1>
        </div>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6" data-testid="project-overview">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <Layers className="w-3.5 h-3.5" />
            <span className="text-xs uppercase tracking-wider">Type</span>
          </div>
          <p className="text-sm font-semibold text-foreground">{project.type}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <CalendarDays className="w-3.5 h-3.5" />
            <span className="text-xs uppercase tracking-wider">Period</span>
          </div>
          <p className="text-sm font-semibold text-foreground">
            {project.start_date || "?"} &mdash; {project.end_date || "?"}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <Hash className="w-3.5 h-3.5" />
            <span className="text-xs uppercase tracking-wider">Planned Days</span>
          </div>
          <p className="text-sm font-semibold text-foreground">{project.planned_days ?? "-"}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <DollarSign className="w-3.5 h-3.5" />
            <span className="text-xs uppercase tracking-wider">Budget</span>
          </div>
          <p className="text-sm font-semibold text-foreground">
            {project.budget_planned != null ? `${project.budget_planned.toLocaleString()} EUR` : "-"}
          </p>
        </div>
      </div>

      {/* Tags + Notes */}
      {(project.tags?.length > 0 || project.notes) && (
        <div className="rounded-lg border border-border bg-card p-4 mb-6">
          {project.tags?.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap mb-2">
              <Tag className="w-3.5 h-3.5 text-muted-foreground" />
              {project.tags.map((t) => (
                <Badge key={t} variant="secondary" className="text-xs">{t}</Badge>
              ))}
            </div>
          )}
          {project.notes && (
            <div className="flex items-start gap-2 text-sm text-muted-foreground">
              <FileText className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              <p>{project.notes}</p>
            </div>
          )}
        </div>
      )}

      {/* Tabs */}
      <Tabs defaultValue="team" className="w-full" data-testid="project-tabs">
        <TabsList className="bg-card border border-border">
          <TabsTrigger value="team" data-testid="tab-team">
            <Users className="w-4 h-4 mr-2" /> Team ({team.length})
          </TabsTrigger>
          <TabsTrigger value="phases" data-testid="tab-phases">
            <Layers className="w-4 h-4 mr-2" /> Phases ({phases.length})
          </TabsTrigger>
        </TabsList>

        {/* Team Tab */}
        <TabsContent value="team" className="mt-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-foreground">Team Members</h3>
            <Button size="sm" onClick={() => setTeamDialogOpen(true)} data-testid="add-team-member-button">
              <Plus className="w-4 h-4 mr-1" /> Add Member
            </Button>
          </div>
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="team-table">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Name</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Email</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Org Role</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Project Role</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {team.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">No team members assigned</TableCell>
                  </TableRow>
                ) : (
                  team.map((m) => (
                    <TableRow key={m.id} className="table-row-hover" data-testid={`team-member-${m.id}`}>
                      <TableCell className="font-medium text-foreground">{m.user_name}</TableCell>
                      <TableCell className="text-muted-foreground">{m.user_email}</TableCell>
                      <TableCell className="text-muted-foreground">{m.user_role}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={`text-xs ${TEAM_ROLE_COLORS[m.role_in_project] || ""}`}>
                          {m.role_in_project}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => handleRemoveMember(m.id)} className="hover:text-destructive" data-testid={`remove-member-${m.id}`}>
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* Phases Tab */}
        <TabsContent value="phases" className="mt-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-foreground">Project Phases</h3>
            <Button size="sm" onClick={openCreatePhase} data-testid="add-phase-button">
              <Plus className="w-4 h-4 mr-1" /> Add Phase
            </Button>
          </div>
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="phases-table">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground w-16">#</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Name</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Start</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">End</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {phases.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">No phases defined</TableCell>
                  </TableRow>
                ) : (
                  phases.map((ph) => (
                    <TableRow key={ph.id} className="table-row-hover" data-testid={`phase-row-${ph.id}`}>
                      <TableCell className="font-mono text-muted-foreground">{ph.order}</TableCell>
                      <TableCell className="font-medium text-foreground">{ph.name}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={`text-xs ${STATUS_COLORS[ph.status] || ""}`}>{ph.status}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{ph.planned_start || "-"}</TableCell>
                      <TableCell className="text-muted-foreground">{ph.planned_end || "-"}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => openEditPhase(ph)}>Edit</Button>
                          <Button variant="ghost" size="sm" onClick={() => handleDeletePhase(ph.id)} className="hover:text-destructive">
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>

      {/* Add Team Member Dialog */}
      <Dialog open={teamDialogOpen} onOpenChange={setTeamDialogOpen}>
        <DialogContent className="sm:max-w-[420px] bg-card border-border" data-testid="team-dialog">
          <DialogHeader>
            <DialogTitle>Add Team Member</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-2">
              <Label className="text-muted-foreground">User</Label>
              <Select value={teamForm.user_id} onValueChange={(v) => setTeamForm({ ...teamForm, user_id: v })}>
                <SelectTrigger className="bg-background" data-testid="team-user-select">
                  <SelectValue placeholder="Select a user..." />
                </SelectTrigger>
                <SelectContent>
                  {availableUsers.map((u) => (
                    <SelectItem key={u.id} value={u.id}>{u.first_name} {u.last_name} ({u.role})</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">Role in Project</Label>
              <Select value={teamForm.role_in_project} onValueChange={(v) => setTeamForm({ ...teamForm, role_in_project: v })}>
                <SelectTrigger className="bg-background" data-testid="team-role-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["SiteManager", "Technician", "Viewer"].map((r) => (
                    <SelectItem key={r} value={r}>{r}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleAddMember} disabled={addingMember || !teamForm.user_id} className="w-full" data-testid="team-add-button">
              {addingMember && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              Add to Team
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Phase Dialog */}
      <Dialog open={phaseDialogOpen} onOpenChange={setPhaseDialogOpen}>
        <DialogContent className="sm:max-w-[420px] bg-card border-border" data-testid="phase-dialog">
          <DialogHeader>
            <DialogTitle>{editingPhase ? "Edit Phase" : "Add Phase"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-2">
              <Label className="text-muted-foreground">Name *</Label>
              <Input value={phaseForm.name} onChange={(e) => setPhaseForm({ ...phaseForm, name: e.target.value })} className="bg-background" data-testid="phase-name-input" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-muted-foreground">Order</Label>
                <Input type="number" value={phaseForm.order} onChange={(e) => setPhaseForm({ ...phaseForm, order: e.target.value })} className="bg-background" data-testid="phase-order-input" />
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground">Status</Label>
                <Select value={phaseForm.status} onValueChange={(v) => setPhaseForm({ ...phaseForm, status: v })}>
                  <SelectTrigger className="bg-background" data-testid="phase-status-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["Draft", "Active", "Paused", "Completed", "Cancelled"].map((s) => (
                      <SelectItem key={s} value={s}>{s}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-muted-foreground">Start</Label>
                <Input type="date" value={phaseForm.planned_start} onChange={(e) => setPhaseForm({ ...phaseForm, planned_start: e.target.value })} className="bg-background" data-testid="phase-start-input" />
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground">End</Label>
                <Input type="date" value={phaseForm.planned_end} onChange={(e) => setPhaseForm({ ...phaseForm, planned_end: e.target.value })} className="bg-background" data-testid="phase-end-input" />
              </div>
            </div>
            <Button onClick={handleSavePhase} disabled={savingPhase || !phaseForm.name} className="w-full" data-testid="phase-save-button">
              {savingPhase && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              {editingPhase ? "Update Phase" : "Add Phase"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
