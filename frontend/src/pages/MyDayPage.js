import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDate, formatTime } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CheckCircle2,
  XCircle,
  Clock,
  ThermometerSun,
  Palmtree,
  AlertTriangle,
  Loader2,
  CalendarDays,
  FileText,
  ArrowRight,
} from "lucide-react";

const STATUS_CONFIG = {
  Present: { icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/20 border-emerald-500/40 hover:bg-emerald-500/30", labelKey: "myDay.imAtWork" },
  Absent: { icon: XCircle, color: "text-red-400", bg: "bg-red-500/20 border-red-500/40 hover:bg-red-500/30", labelKey: "attendance.absent" },
  Late: { icon: Clock, color: "text-amber-400", bg: "bg-amber-500/20 border-amber-500/40", labelKey: "attendance.late" },
  SickLeave: { icon: ThermometerSun, color: "text-orange-400", bg: "bg-orange-500/20 border-orange-500/40 hover:bg-orange-500/30", labelKey: "myDay.sickLeave" },
  Vacation: { icon: Palmtree, color: "text-cyan-400", bg: "bg-cyan-500/20 border-cyan-500/40 hover:bg-cyan-500/30", labelKey: "myDay.vacation" },
};

const REPORT_STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Submitted: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Approved: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Rejected: "bg-red-500/20 text-red-400 border-red-500/30",
};

export default function MyDayPage() {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [marking, setMarking] = useState(false);
  const [note, setNote] = useState("");
  const [selectedProject, setSelectedProject] = useState("");

  const fetchToday = useCallback(async () => {
    try {
      const [attRes, repRes] = await Promise.all([
        API.get("/attendance/my-today"),
        API.get("/work-reports/my-today"),
      ]);
      setData(attRes.data);
      setReports(repRes.data);
      if (attRes.data.active_projects?.length === 1) {
        setSelectedProject(attRes.data.active_projects[0].id);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchToday(); }, [fetchToday]);

  const handleMark = async (status) => {
    setMarking(true);
    try {
      await API.post("/attendance/mark", {
        project_id: selectedProject || null,
        status,
        note,
        source: "Web",
      });
      await fetchToday();
      setNote("");
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setMarking(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const alreadyMarked = data?.entry != null;
  const pastDeadline = data?.past_deadline;
  const needsReport = alreadyMarked && ["Present", "Late"].includes(data?.entry?.status);
  const activeProjects = data?.active_projects || [];

  // Reports that exist for today
  const reportMap = {};
  reports.forEach((r) => { reportMap[r.project_id] = r; });

  return (
    <div className="p-6 max-w-[480px] mx-auto" data-testid="my-day-page">
      {/* Date header */}
      <div className="text-center mb-8">
        <div className="flex items-center justify-center gap-2 mb-2">
          <CalendarDays className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-bold text-foreground">My Day</h1>
        </div>
        <p className="text-lg text-muted-foreground">{new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</p>
        <p className="text-xs text-muted-foreground mt-1">
          {user?.first_name} {user?.last_name} &middot; {user?.role}
        </p>
      </div>

      {/* Late Warning */}
      {pastDeadline && !alreadyMarked && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 mb-6" data-testid="late-warning">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-400">Past Deadline ({data?.deadline})</p>
            <p className="text-xs text-muted-foreground">Your attendance will be marked as Late</p>
          </div>
        </div>
      )}

      {/* Already Marked */}
      {alreadyMarked ? (
        <div className="rounded-xl border border-border bg-card p-6 text-center mb-6" data-testid="attendance-already-marked">
          {(() => {
            const cfg = STATUS_CONFIG[data.entry.status] || STATUS_CONFIG.Present;
            const Icon = cfg.icon;
            return (
              <>
                <div className={`w-16 h-16 rounded-full ${cfg.bg} border flex items-center justify-center mx-auto mb-4`}>
                  <Icon className={`w-8 h-8 ${cfg.color}`} />
                </div>
                <h2 className="text-lg font-bold text-foreground mb-1">Attendance Recorded</h2>
                <Badge variant="outline" className={`text-sm mb-2 ${cfg.bg} ${cfg.color}`}>{data.entry.status}</Badge>
                <p className="text-xs text-muted-foreground">
                  Marked at {new Date(data.entry.marked_at).toLocaleTimeString()}
                </p>
                {data.entry.note && (
                  <p className="text-sm text-muted-foreground mt-3 italic">"{data.entry.note}"</p>
                )}
              </>
            );
          })()}
        </div>
      ) : (
        <>
          {/* Project Selection */}
          {activeProjects.length > 0 && (
            <div className="mb-6">
              <label className="text-xs text-muted-foreground uppercase tracking-wider mb-2 block">Active Project</label>
              <Select value={selectedProject} onValueChange={setSelectedProject}>
                <SelectTrigger className="bg-card border-border h-12 text-base" data-testid="project-select">
                  <SelectValue placeholder="Select project..." />
                </SelectTrigger>
                <SelectContent>
                  {activeProjects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Main Action — Present */}
          <Button
            className="w-full h-20 text-xl font-bold rounded-2xl bg-emerald-600 hover:bg-emerald-700 text-white mb-4 transition-all duration-200 active:scale-[0.98]"
            onClick={() => handleMark("Present")}
            disabled={marking}
            data-testid="mark-present-button"
          >
            {marking ? <Loader2 className="w-6 h-6 animate-spin mr-3" /> : <CheckCircle2 className="w-7 h-7 mr-3" />}
            {pastDeadline ? "I'm at Work (Late)" : "I'm at Work"}
          </Button>

          {/* Secondary Actions */}
          <div className="grid grid-cols-3 gap-3 mb-6">
            {["Absent", "SickLeave", "Vacation"].map((s) => {
              const cfg = STATUS_CONFIG[s];
              const Icon = cfg.icon;
              return (
                <button
                  key={s}
                  className={`flex flex-col items-center gap-2 p-4 rounded-xl border ${cfg.bg} transition-all duration-200 active:scale-95 disabled:opacity-50`}
                  onClick={() => handleMark(s)}
                  disabled={marking}
                  data-testid={`mark-${s.toLowerCase()}-button`}
                >
                  <Icon className={`w-6 h-6 ${cfg.color}`} />
                  <span className="text-xs font-medium text-foreground">{cfg.label}</span>
                </button>
              );
            })}
          </div>

          {/* Note */}
          <div className="mb-4">
            <Textarea
              placeholder="Add a note (optional)..."
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="bg-card border-border min-h-[60px] text-sm"
              data-testid="attendance-note"
            />
          </div>
        </>
      )}

      {/* Work Report CTA */}
      {needsReport && (
        <div className="space-y-3" data-testid="work-report-section">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <FileText className="w-4 h-4 text-primary" /> End-of-Day Reports
          </h3>

          {activeProjects.length === 0 && reports.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-4">
              <Button
                onClick={() => navigate("/work-reports/new")}
                className="w-full h-14 text-base rounded-xl bg-primary hover:bg-primary/90"
                data-testid="fill-report-button"
              >
                <FileText className="w-5 h-5 mr-2" /> Fill End-of-Day Report
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
            </div>
          ) : (
            <>
              {activeProjects.map((proj) => {
                const rep = reportMap[proj.id];
                return (
                  <div key={proj.id} className="rounded-xl border border-border bg-card p-4 flex items-center justify-between" data-testid={`report-cta-${proj.id}`}>
                    <div>
                      <p className="text-sm font-medium text-foreground">{proj.code} - {proj.name}</p>
                      {rep ? (
                        <Badge variant="outline" className={`text-xs mt-1 ${REPORT_STATUS_COLORS[rep.status] || ""}`}>
                          {rep.status} {rep.total_hours > 0 ? `(${rep.total_hours}h)` : ""}
                        </Badge>
                      ) : (
                        <p className="text-xs text-muted-foreground mt-1">No report yet</p>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant={rep ? "outline" : "default"}
                      onClick={() => rep ? navigate(`/work-reports/${rep.id}`) : navigate(`/work-reports/new?projectId=${proj.id}`)}
                      data-testid={`report-action-${proj.id}`}
                    >
                      {rep && rep.status === "Draft" ? "Continue" : rep ? "View" : "Fill Report"}
                      <ArrowRight className="w-3.5 h-3.5 ml-1" />
                    </Button>
                  </div>
                );
              })}
              {/* For reports on projects not in active list */}
              {reports.filter((r) => !activeProjects.find((p) => p.id === r.project_id)).map((rep) => (
                <div key={rep.id} className="rounded-xl border border-border bg-card p-4 flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-foreground">{rep.project_code || "Project"}</p>
                    <Badge variant="outline" className={`text-xs mt-1 ${REPORT_STATUS_COLORS[rep.status] || ""}`}>
                      {rep.status} {rep.total_hours > 0 ? `(${rep.total_hours}h)` : ""}
                    </Badge>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => navigate(`/work-reports/${rep.id}`)}>
                    View <ArrowRight className="w-3.5 h-3.5 ml-1" />
                  </Button>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
