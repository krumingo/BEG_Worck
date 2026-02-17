import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  ArrowLeft,
  Plus,
  Trash2,
  Send,
  Save,
  Loader2,
  Clock,
  AlertTriangle,
  FileText,
  MinusCircle,
  PlusCircle,
  Layers,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Submitted: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Approved: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Rejected: "bg-red-500/20 text-red-400 border-red-500/30",
};

export default function WorkReportFormPage() {
  const { reportId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const projectIdParam = searchParams.get("projectId");

  const [report, setReport] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activities, setActivities] = useState([]);
  const [selectedProject, setSelectedProject] = useState(projectIdParam || "");
  const [summaryNote, setSummaryNote] = useState("");
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const fetchReport = useCallback(async () => {
    try {
      if (reportId && reportId !== "new") {
        const res = await API.get(`/work-reports/${reportId}`);
        setReport(res.data);
        setSummaryNote(res.data.summary_note || "");
        setLines(res.data.lines || []);
        setSelectedProject(res.data.project_id);
        // Load activities for the project
        try {
          const actRes = await API.get(`/activity-catalog?project_id=${res.data.project_id}`);
          setActivities(actRes.data || []);
        } catch { setActivities([]); }
      } else {
        // Load projects for selection
        const todayRes = await API.get("/attendance/my-today");
        setProjects(todayRes.data.active_projects || []);
        if (projectIdParam) {
          setSelectedProject(projectIdParam);
          // Load activities for selected project
          try {
            const actRes = await API.get(`/activity-catalog?project_id=${projectIdParam}`);
            setActivities(actRes.data || []);
          } catch { setActivities([]); }
        }
        else if (todayRes.data.active_projects?.length === 1) {
          setSelectedProject(todayRes.data.active_projects[0].id);
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [reportId, projectIdParam]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const createDraft = async () => {
    if (!selectedProject) return;
    setSaving(true);
    try {
      const res = await API.post("/work-reports/draft", { project_id: selectedProject });
      setReport(res.data);
      setSummaryNote(res.data.summary_note || "");
      setLines(res.data.lines || []);
      navigate(`/work-reports/${res.data.id}`, { replace: true });
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to create draft");
    } finally {
      setSaving(false);
    }
  };

  const addLine = () => {
    setLines([...lines, { id: Date.now().toString(), activity_name: "", hours: 1, note: "" }]);
  };

  const removeLine = (idx) => {
    setLines(lines.filter((_, i) => i !== idx));
  };

  const updateLine = (idx, field, value) => {
    const updated = [...lines];
    updated[idx] = { ...updated[idx], [field]: value };
    setLines(updated);
  };

  const adjustHours = (idx, delta) => {
    const updated = [...lines];
    const newVal = Math.max(0.25, Math.round((updated[idx].hours + delta) * 4) / 4);
    updated[idx] = { ...updated[idx], hours: newVal };
    setLines(updated);
  };

  const totalHours = lines.reduce((sum, l) => sum + (l.hours || 0), 0);

  const handleSave = async () => {
    if (!report) return;
    setSaving(true);
    try {
      const res = await API.put(`/work-reports/${report.id}`, {
        summary_note: summaryNote,
        lines: lines.map((l) => ({ activity_name: l.activity_name, hours: l.hours, note: l.note })),
      });
      setReport(res.data);
      setLines(res.data.lines || []);
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = async () => {
    if (!report) return;
    // Save first, then submit
    setSubmitting(true);
    try {
      await API.put(`/work-reports/${report.id}`, {
        summary_note: summaryNote,
        lines: lines.map((l) => ({ activity_name: l.activity_name, hours: l.hours, note: l.note })),
      });
      const res = await API.post(`/work-reports/${report.id}/submit`);
      setReport(res.data);
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to submit");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // If no report yet, show project selection to create draft
  if (!report) {
    return (
      <div className="p-6 max-w-[480px] mx-auto" data-testid="work-report-create">
        <Button variant="ghost" size="sm" className="mb-4 text-muted-foreground" onClick={() => navigate("/my-day")} data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-2" /> Back
        </Button>
        <h1 className="text-xl font-bold text-foreground mb-2">New Work Report</h1>
        <p className="text-sm text-muted-foreground mb-6">Select a project to start your daily report</p>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label className="text-muted-foreground">Project</Label>
            <Select value={selectedProject} onValueChange={setSelectedProject}>
              <SelectTrigger className="bg-card h-12" data-testid="report-project-select">
                <SelectValue placeholder="Select project..." />
              </SelectTrigger>
              <SelectContent>
                {projects.map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button onClick={createDraft} disabled={!selectedProject || saving} className="w-full h-12" data-testid="create-draft-button">
            {saving && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
            <FileText className="w-4 h-4 mr-2" /> Start Report
          </Button>
        </div>
      </div>
    );
  }

  const isEditable = report.status === "Draft" || report.status === "Rejected";
  const isSubmitted = report.status === "Submitted" || report.status === "Approved";

  return (
    <div className="p-6 max-w-[540px] mx-auto" data-testid="work-report-form">
      <Button variant="ghost" size="sm" className="mb-4 text-muted-foreground" onClick={() => navigate("/my-day")} data-testid="back-button">
        <ArrowLeft className="w-4 h-4 mr-2" /> Back
      </Button>

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-foreground">Daily Report</h1>
          <p className="text-sm text-muted-foreground">{report.date} &middot; {report.project_code}</p>
        </div>
        <Badge variant="outline" className={`${STATUS_COLORS[report.status] || ""}`}>{report.status}</Badge>
      </div>

      {/* Reject reason */}
      {report.status === "Rejected" && report.reject_reason && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-red-500/10 border border-red-500/30 mb-6" data-testid="reject-reason">
          <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-400">Rejected</p>
            <p className="text-sm text-muted-foreground">{report.reject_reason}</p>
          </div>
        </div>
      )}

      {/* Summary */}
      <div className="rounded-xl border border-border bg-card p-4 mb-4">
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-2 block">Summary Note</Label>
        <Textarea
          value={summaryNote}
          onChange={(e) => setSummaryNote(e.target.value)}
          placeholder="Brief summary of today's work..."
          className="bg-background min-h-[60px]"
          disabled={!isEditable}
          data-testid="summary-note"
        />
      </div>

      {/* Activity Lines */}
      <div className="rounded-xl border border-border bg-card p-4 mb-4" data-testid="lines-section">
        <div className="flex items-center justify-between mb-3">
          <Label className="text-xs text-muted-foreground uppercase tracking-wider">Activities</Label>
          {isEditable && (
            <Button variant="ghost" size="sm" onClick={addLine} data-testid="add-line-button">
              <Plus className="w-4 h-4 mr-1" /> Add
            </Button>
          )}
        </div>

        {lines.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">No activities yet. Add your first one.</p>
        ) : (
          <div className="space-y-3">
            {lines.map((line, idx) => (
              <div key={line.id || idx} className="p-3 rounded-lg bg-background border border-border" data-testid={`line-${idx}`}>
                <div className="flex items-start gap-2 mb-2">
                  {activities.length > 0 && isEditable && (
                    <Select
                      value=""
                      onValueChange={(actId) => {
                        const act = activities.find(a => a.id === actId);
                        if (act) updateLine(idx, "activity_name", act.name);
                      }}
                    >
                      <SelectTrigger className="w-[100px] bg-card h-9 text-xs" data-testid={`pick-activity-${idx}`}>
                        <Layers className="w-3 h-3 mr-1" />
                        <span>Pick</span>
                      </SelectTrigger>
                      <SelectContent>
                        {activities.map((act) => (
                          <SelectItem key={act.id} value={act.id}>{act.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                  <Input
                    value={line.activity_name}
                    onChange={(e) => updateLine(idx, "activity_name", e.target.value)}
                    placeholder="Activity name..."
                    className="flex-1 bg-card text-sm h-9"
                    disabled={!isEditable}
                    data-testid={`line-activity-${idx}`}
                  />
                  {isEditable && (
                    <Button variant="ghost" size="sm" onClick={() => removeLine(idx)} className="hover:text-destructive h-9 w-9 p-0" data-testid={`remove-line-${idx}`}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    <Button variant="ghost" size="sm" onClick={() => adjustHours(idx, -0.25)} disabled={!isEditable || line.hours <= 0.25} className="h-8 w-8 p-0" data-testid={`hours-minus-${idx}`}>
                      <MinusCircle className="w-4 h-4" />
                    </Button>
                    <div className="flex items-center gap-1 px-2">
                      <Clock className="w-3 h-3 text-muted-foreground" />
                      <span className="text-sm font-bold text-foreground min-w-[2.5rem] text-center" data-testid={`hours-display-${idx}`}>{line.hours}h</span>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => adjustHours(idx, 0.25)} disabled={!isEditable} className="h-8 w-8 p-0" data-testid={`hours-plus-${idx}`}>
                      <PlusCircle className="w-4 h-4" />
                    </Button>
                  </div>
                  <Input
                    value={line.note}
                    onChange={(e) => updateLine(idx, "note", e.target.value)}
                    placeholder="Note..."
                    className="flex-1 bg-card text-xs h-8"
                    disabled={!isEditable}
                    data-testid={`line-note-${idx}`}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Total */}
        <div className="flex items-center justify-between mt-4 pt-3 border-t border-border">
          <span className="text-sm font-medium text-muted-foreground">Total Hours</span>
          <span className={`text-lg font-bold ${totalHours > 8 ? "text-amber-400" : "text-foreground"}`} data-testid="total-hours">
            {totalHours}h
          </span>
        </div>
        {totalHours > 8 && (
          <p className="text-xs text-amber-400 mt-1 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Over 8 hours — will require manager approval
          </p>
        )}
      </div>

      {/* Actions */}
      {isEditable && (
        <div className="flex gap-3">
          <Button variant="outline" onClick={handleSave} disabled={saving} className="flex-1" data-testid="save-draft-button">
            {saving && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
            <Save className="w-4 h-4 mr-2" /> Save Draft
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting || lines.length === 0 || lines.some((l) => !l.activity_name)}
            className="flex-1 bg-emerald-600 hover:bg-emerald-700"
            data-testid="submit-report-button"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
            <Send className="w-4 h-4 mr-2" /> Submit
          </Button>
        </div>
      )}

      {isSubmitted && (
        <div className="text-center text-sm text-muted-foreground">
          {report.status === "Approved" ? "This report has been approved." : "Waiting for manager review."}
        </div>
      )}
    </div>
  );
}
