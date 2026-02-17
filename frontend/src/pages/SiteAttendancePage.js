import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDate, formatTime } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
  CalendarCheck,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  ThermometerSun,
  Palmtree,
  Loader2,
  UserX,
} from "lucide-react";

const STATUS_COLORS = {
  Present: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Absent: "bg-red-500/20 text-red-400 border-red-500/30",
  Late: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  SickLeave: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  Vacation: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
};

const STATUS_ICONS = {
  Present: CheckCircle2, Absent: XCircle, Late: Clock,
  SickLeave: ThermometerSun, Vacation: Palmtree,
};

export default function SiteAttendancePage() {
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState("all");
  const [siteData, setSiteData] = useState(null);
  const [loading, setLoading] = useState(true);

  // Mark dialog
  const [markDialogOpen, setMarkDialogOpen] = useState(false);
  const [markTarget, setMarkTarget] = useState(null);
  const [markStatus, setMarkStatus] = useState("Present");
  const [markNote, setMarkNote] = useState("");
  const [marking, setMarking] = useState(false);

  const fetchProjects = useCallback(async () => {
    try {
      const res = await API.get("/projects?status=Active");
      setProjects(res.data);
    } catch (err) {
      console.error(err);
    }
  }, []);

  const fetchSiteData = useCallback(async () => {
    setLoading(true);
    try {
      const params = selectedProject !== "all" ? `?project_id=${selectedProject}` : "";
      const res = await API.get(`/attendance/site-today${params}`);
      setSiteData(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [selectedProject]);

  useEffect(() => { fetchProjects(); }, [fetchProjects]);
  useEffect(() => { fetchSiteData(); }, [fetchSiteData]);

  const openMarkDialog = (user) => {
    setMarkTarget(user);
    setMarkStatus("Present");
    setMarkNote("");
    setMarkDialogOpen(true);
  };

  const handleMark = async () => {
    if (!markTarget) return;
    setMarking(true);
    try {
      await API.post("/attendance/mark-for-user", {
        user_id: markTarget.user_id,
        project_id: selectedProject !== "all" ? selectedProject : null,
        status: markStatus,
        note: markNote,
        source: "Web",
      });
      setMarkDialogOpen(false);
      await fetchSiteData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to mark attendance");
    } finally {
      setMarking(false);
    }
  };

  return (
    <div className="p-8 max-w-[1200px]" data-testid="site-attendance-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Site Attendance</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
          </p>
        </div>
        {siteData && (
          <div className="flex items-center gap-4">
            {siteData.missing_count > 0 && (
              <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30" data-testid="missing-badge">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span className="text-sm font-semibold text-amber-400">{siteData.missing_count} Missing</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Project Filter */}
      <div className="flex items-center gap-3 mb-6">
        <Select value={selectedProject} onValueChange={setSelectedProject}>
          <SelectTrigger className="w-[300px] bg-card" data-testid="site-project-filter">
            <SelectValue placeholder="Filter by project..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Active Projects</SelectItem>
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
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="site-attendance-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">User</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Role</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Marked At</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Note</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!siteData?.users?.length ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-16">
                    <UserX className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
                    <p className="text-muted-foreground">No team members in active projects</p>
                  </TableCell>
                </TableRow>
              ) : (
                siteData.users.map((row) => {
                  const entry = row.attendance;
                  const StatusIcon = entry ? (STATUS_ICONS[entry.status] || CheckCircle2) : null;
                  return (
                    <TableRow key={row.user_id} className="table-row-hover" data-testid={`site-row-${row.user_id}`}>
                      <TableCell>
                        <div>
                          <p className="font-medium text-foreground">{row.user_name}</p>
                          <p className="text-xs text-muted-foreground">{row.user_email}</p>
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">{row.user_role}</TableCell>
                      <TableCell>
                        {entry ? (
                          <div className="flex items-center gap-2">
                            <StatusIcon className={`w-4 h-4 ${STATUS_COLORS[entry.status]?.split(" ")[1] || ""}`} />
                            <Badge variant="outline" className={`text-xs ${STATUS_COLORS[entry.status] || ""}`}>
                              {entry.status}
                            </Badge>
                          </div>
                        ) : (
                          <Badge variant="outline" className="text-xs bg-gray-500/10 text-gray-400 border-gray-500/30">
                            Not Marked
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {entry ? new Date(entry.marked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "-"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground max-w-[150px] truncate">
                        {entry?.note || "-"}
                      </TableCell>
                      <TableCell className="text-right">
                        {!row.marked && (
                          <Button size="sm" onClick={() => openMarkDialog(row)} data-testid={`mark-for-${row.user_id}`}>
                            <CalendarCheck className="w-3.5 h-3.5 mr-1" /> Mark
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Mark Dialog */}
      <Dialog open={markDialogOpen} onOpenChange={setMarkDialogOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="mark-dialog">
          <DialogHeader>
            <DialogTitle>Mark Attendance for {markTarget?.user_name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-2">
              <label className="text-sm text-muted-foreground">Status</label>
              <Select value={markStatus} onValueChange={setMarkStatus}>
                <SelectTrigger className="bg-background" data-testid="mark-status-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["Present", "Absent", "Late", "SickLeave", "Vacation"].map((s) => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-muted-foreground">Note</label>
              <Input value={markNote} onChange={(e) => setMarkNote(e.target.value)} placeholder="Optional note..." className="bg-background" data-testid="mark-note-input" />
            </div>
            <Button onClick={handleMark} disabled={marking} className="w-full" data-testid="mark-confirm-button">
              {marking && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              Confirm
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
