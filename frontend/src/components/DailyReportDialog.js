import { useEffect, useState, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Loader2, Plus, Trash2, Check, Clock, User, FileText, AlertTriangle,
  X, ThumbsUp, ThumbsDown, List,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { formatDate } from "@/lib/i18nUtils";

const STATUS_LABELS = { WORKING: "На работа", LEAVE: "Отпуск", ABSENT_UNEXCUSED: "Самоотлъчка" };
const STATUS_COLORS = { WORKING: "bg-emerald-500/15 text-emerald-400", LEAVE: "bg-blue-500/15 text-blue-400", ABSENT_UNEXCUSED: "bg-red-500/15 text-red-400" };
const APPROVAL_LABELS = { DRAFT: "Чернова", SUBMITTED: "Изпратен", APPROVED: "Одобрен", REJECTED: "Отхвърлен" };
const APPROVAL_COLORS = { DRAFT: "bg-gray-500/15 text-gray-400", SUBMITTED: "bg-blue-500/15 text-blue-400", APPROVED: "bg-emerald-500/15 text-emerald-400", REJECTED: "bg-red-500/15 text-red-400" };

export default function DailyReportDialog({ open, onOpenChange, employeeId, employeeName, reportDate, existingReportId, onSaved }) {
  const { user } = useAuth();
  const canApprove = ["Admin", "Owner", "SiteManager"].includes(user?.role);
  const [projects, setProjects] = useState([]);
  const [smrByProject, setSmrByProject] = useState({});
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // New SMR inline form
  const [newSmrOpen, setNewSmrOpen] = useState(null); // index of entry
  const [newSmrTitle, setNewSmrTitle] = useState("");
  const [newSmrSaving, setNewSmrSaving] = useState(false);

  // Approval
  const [approvalStatus, setApprovalStatus] = useState("DRAFT");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  // Form
  const [selEmployee, setSelEmployee] = useState(employeeId || "");
  const [date, setDate] = useState(reportDate || new Date().toISOString().split("T")[0]);
  const [dayStatus, setDayStatus] = useState("WORKING");
  const [leaveFrom, setLeaveFrom] = useState("");
  const [leaveTo, setLeaveTo] = useState("");
  const [notes, setNotes] = useState("");
  const [entries, setEntries] = useState([]);
  const [reportId, setReportId] = useState(existingReportId || null);

  const fetchData = useCallback(async () => {
    try {
      const [projRes, empRes] = await Promise.all([
        API.get("/projects"),
        API.get("/employees"),
      ]);
      setProjects(projRes.data);
      setEmployees(empRes.data);

      // Load existing report if editing
      if (existingReportId) {
        const repRes = await API.get(`/daily-reports/${existingReportId}`);
        const r = repRes.data;
        setSelEmployee(r.employee_id);
        setDate(r.report_date);
        setDayStatus(r.day_status);
        setLeaveFrom(r.leave_from || "");
        setLeaveTo(r.leave_to || "");
        setNotes(r.notes || "");
        setEntries(r.day_entries || []);
        setReportId(r.id);
        setApprovalStatus(r.approval_status || "DRAFT");
        // Load SMR for each project in entries
        const pids = [...new Set(r.day_entries.map(e => e.project_id))];
        for (const pid of pids) {
          const smrRes = await API.get(`/daily-reports/available-smr/${pid}`);
          setSmrByProject(prev => ({ ...prev, [pid]: smrRes.data.smr }));
        }
      }
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [existingReportId]);

  useEffect(() => { if (open) { setLoading(true); fetchData(); } }, [open, fetchData]);
  useEffect(() => { setSelEmployee(employeeId || ""); }, [employeeId]);
  useEffect(() => { setDate(reportDate || new Date().toISOString().split("T")[0]); }, [reportDate]);

  // Load SMR when project selected
  const loadSmr = async (projectId) => {
    if (smrByProject[projectId]) return;
    try {
      const res = await API.get(`/daily-reports/available-smr/${projectId}`);
      setSmrByProject(prev => ({ ...prev, [projectId]: res.data.smr }));
    } catch { /* */ }
  };

  // Entry management
  const addEntry = () => setEntries([...entries, { id: Date.now().toString(), project_id: "", smr_id: "", work_description: "", hours_worked: 0, note: "" }]);
  const removeEntry = (i) => setEntries(entries.filter((_, idx) => idx !== i));
  const updateEntry = (i, f, v) => { const n = [...entries]; n[i] = { ...n[i], [f]: v }; setEntries(n); };

  const totalHours = entries.reduce((s, e) => s + (parseFloat(e.hours_worked) || 0), 0);

  // Create new extra work SMR for a project
  const handleNewSmr = async (entryIndex) => {
    if (!newSmrTitle.trim()) return;
    const projectId = entries[entryIndex]?.project_id;
    if (!projectId) return;
    setNewSmrSaving(true);
    try {
      const res = await API.post("/extra-works", {
        project_id: projectId, title: newSmrTitle, unit: "m2", qty: 1,
      });
      const newId = res.data.id;
      // Refresh SMR list for this project
      const smrRes = await API.get(`/daily-reports/available-smr/${projectId}`);
      setSmrByProject(prev => ({ ...prev, [projectId]: smrRes.data.smr }));
      // Auto-select in entry
      updateEntry(entryIndex, "smr_id", newId);
      updateEntry(entryIndex, "extra_work_id", newId);
      setNewSmrOpen(null);
      setNewSmrTitle("");
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setNewSmrSaving(false); }
  };

  // Approve/reject
  const handleApprove = async () => {
    if (!reportId) return;
    setSaving(true);
    try {
      await API.post(`/daily-reports/${reportId}/approve`);
      setApprovalStatus("APPROVED");
      onSaved?.();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  const handleReject = async () => {
    if (!reportId) return;
    setSaving(true);
    try {
      await API.post(`/daily-reports/${reportId}/reject`, { reason: rejectReason });
      setApprovalStatus("REJECTED");
      setRejectOpen(false);
      onSaved?.();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  // Save
  const handleSave = async (andSubmit = false) => {
    if (!selEmployee) { alert("Изберете служител"); return; }
    setSaving(true);
    try {
      let rid = reportId;
      const payload = {
        employee_id: selEmployee,
        report_date: date,
        day_status: dayStatus,
        leave_from: dayStatus === "LEAVE" ? leaveFrom : null,
        leave_to: dayStatus === "LEAVE" ? leaveTo : null,
        notes: notes || null,
        day_entries: dayStatus === "WORKING" ? entries.map(e => ({
          project_id: e.project_id, smr_id: e.smr_id || null,
          extra_work_id: e.extra_work_id || null,
          work_description: e.work_description,
          hours_worked: parseFloat(e.hours_worked) || 0, note: e.note || null,
        })) : [],
      };

      if (rid) {
        await API.put(`/daily-reports/${rid}`, payload);
      } else {
        const res = await API.post("/daily-reports", payload);
        rid = res.data.id;
        setReportId(rid);
      }

      if (andSubmit && rid) {
        await API.post(`/daily-reports/${rid}/submit`);
      }

      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка");
    } finally { setSaving(false); }
  };

  if (!open) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[700px] bg-card border-border max-h-[90vh] overflow-y-auto" data-testid="daily-report-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Clock className="w-5 h-5 text-primary" /> Дневен отчет</DialogTitle>
        </DialogHeader>

        {loading ? <div className="py-8 text-center"><Loader2 className="w-6 h-6 animate-spin mx-auto" /></div> : (
          <div className="space-y-4 py-2">
            {/* Header fields */}
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Служител *</Label>
                <Select value={selEmployee} onValueChange={setSelEmployee} disabled={!!employeeId}>
                  <SelectTrigger className="bg-background"><SelectValue placeholder="Избери" /></SelectTrigger>
                  <SelectContent>
                    {employees.map(e => <SelectItem key={e.id} value={e.id}>{e.first_name} {e.last_name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Дата</Label>
                <Input type="date" value={date} onChange={e => setDate(e.target.value)} className="bg-background" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Статус</Label>
                <Select value={dayStatus} onValueChange={setDayStatus}>
                  <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="WORKING">На работа</SelectItem>
                    <SelectItem value="LEAVE">Отпуск</SelectItem>
                    <SelectItem value="ABSENT_UNEXCUSED">Самоотлъчка</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Leave fields */}
            {dayStatus === "LEAVE" && (
              <div className="grid grid-cols-2 gap-3 p-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
                <div className="space-y-1"><Label className="text-xs">От дата</Label><Input type="date" value={leaveFrom} onChange={e => setLeaveFrom(e.target.value)} className="bg-background" /></div>
                <div className="space-y-1"><Label className="text-xs">До дата</Label><Input type="date" value={leaveTo} onChange={e => setLeaveTo(e.target.value)} className="bg-background" /></div>
              </div>
            )}

            {dayStatus === "ABSENT_UNEXCUSED" && (
              <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/20 text-sm text-red-400">Самоотлъчка</div>
            )}

            {/* Work entries */}
            {dayStatus === "WORKING" && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium">Работни записи ({entries.length}) • {totalHours.toFixed(1)}ч</Label>
                  <Button size="sm" variant="outline" onClick={addEntry}><Plus className="w-3 h-3 mr-1" /> Добави запис</Button>
                </div>
                {entries.map((entry, i) => (
                  <div key={entry.id || i} className="p-3 rounded-lg border border-border space-y-2" data-testid={`entry-${i}`}>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-muted-foreground w-4">{i + 1}</span>
                      <div className="flex-1">
                        <Select value={entry.project_id || ""} onValueChange={v => { updateEntry(i, "project_id", v); loadSmr(v); }}>
                          <SelectTrigger className="bg-background text-sm h-8"><SelectValue placeholder="Обект" /></SelectTrigger>
                          <SelectContent>{projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code} — {p.name}</SelectItem>)}</SelectContent>
                        </Select>
                      </div>
                      <Input type="number" min="0" max="24" step="0.5" value={entry.hours_worked}
                        onChange={e => updateEntry(i, "hours_worked", e.target.value)}
                        className="w-16 bg-background h-8 text-sm font-mono" placeholder="ч" />
                      <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-destructive" onClick={() => removeEntry(i)}><Trash2 className="w-3.5 h-3.5" /></Button>
                    </div>
                    {entry.project_id && (
                      <>
                      <div className="flex items-center gap-2 ml-6">
                        <Select value={entry.smr_id || "none"} onValueChange={v => updateEntry(i, "smr_id", v === "none" ? "" : v)}>
                          <SelectTrigger className="bg-background text-xs h-7 flex-1"><SelectValue placeholder="СМР" /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">— Без конкретно СМР —</SelectItem>
                            {(smrByProject[entry.project_id] || []).map(s => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                          </SelectContent>
                        </Select>
                        <Button variant="ghost" size="sm" className="h-7 text-[10px] px-1.5 text-primary" onClick={() => { setNewSmrOpen(i); setNewSmrTitle(""); }} data-testid={`new-smr-btn-${i}`}>
                          <Plus className="w-3 h-3" />
                        </Button>
                        <Input value={entry.work_description} onChange={e => updateEntry(i, "work_description", e.target.value)} placeholder="Описание" className="bg-background text-xs h-7 flex-1" />
                      </div>
                      {newSmrOpen === i && (
                        <div className="flex items-center gap-2 ml-6 mt-1 p-2 rounded bg-primary/5 border border-primary/20">
                          <Input value={newSmrTitle} onChange={e => setNewSmrTitle(e.target.value)} placeholder="Ново СМР описание..." className="bg-background text-xs h-7 flex-1" data-testid="new-smr-input" />
                          <Button size="sm" className="h-7 text-[10px] bg-emerald-600" onClick={() => handleNewSmr(i)} disabled={newSmrSaving || !newSmrTitle.trim()} data-testid="save-new-smr-btn">
                            {newSmrSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                          </Button>
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setNewSmrOpen(null)}><X className="w-3 h-3" /></Button>
                        </div>
                      )}
                      </>
                    )}
                  </div>
                ))}
                {entries.length === 0 && <p className="text-sm text-muted-foreground text-center py-4">Добавете работни записи</p>}
              </div>
            )}

            {/* Notes */}
            <div className="space-y-1">
              <Label className="text-xs">Бележки</Label>
              <Textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Допълнителни бележки..." className="bg-background min-h-[40px] text-sm" />
            </div>
          </div>
        )}

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Затвори</Button>
          {approvalStatus === "SUBMITTED" && canApprove && (
            <>
              <Button variant="outline" className="border-red-500/30 text-red-400" onClick={() => setRejectOpen(true)} data-testid="reject-btn">
                <ThumbsDown className="w-4 h-4 mr-1" /> Отхвърли
              </Button>
              <Button className="bg-emerald-600 hover:bg-emerald-700" onClick={handleApprove} disabled={saving} data-testid="approve-btn">
                <ThumbsUp className="w-4 h-4 mr-1" /> Одобри
              </Button>
            </>
          )}
          {(approvalStatus === "DRAFT" || approvalStatus === "REJECTED") && (
            <>
              <Button variant="outline" onClick={() => handleSave(false)} disabled={saving} data-testid="save-draft-btn">
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <FileText className="w-4 h-4 mr-1" />} Запази чернова
              </Button>
              <Button onClick={() => handleSave(true)} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700" data-testid="save-submit-btn">
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />} Запази и изпрати
              </Button>
            </>
          )}
          {approvalStatus === "APPROVED" && <Badge variant="outline" className="bg-emerald-500/15 text-emerald-400 text-sm">Одобрен</Badge>}
        </DialogFooter>

        {/* Reject reason dialog */}
        {rejectOpen && (
          <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
            <DialogContent className="sm:max-w-[350px] bg-card border-border">
              <DialogHeader><DialogTitle>Причина за отхвърляне</DialogTitle></DialogHeader>
              <Textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)} placeholder="Причина..." className="bg-background min-h-[60px]" />
              <DialogFooter>
                <Button variant="outline" onClick={() => setRejectOpen(false)}>Отказ</Button>
                <Button className="bg-red-600 hover:bg-red-700" onClick={handleReject} disabled={saving}><ThumbsDown className="w-4 h-4 mr-1" /> Отхвърли</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ── Personnel Card (for Project Detail) ─────────────────────────
export function ProjectPersonnelCard({ projectId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reportOpen, setReportOpen] = useState(false);
  const [selectedEmp, setSelectedEmp] = useState(null);
  const [selectedReportId, setSelectedReportId] = useState(null);
  // Reports list
  const [reportsListOpen, setReportsListOpen] = useState(false);
  const [reportsListEmp, setReportsListEmp] = useState(null);
  const [reportsList, setReportsList] = useState([]);

  const fetchData = useCallback(async () => {
    try {
      const res = await API.get(`/daily-reports/project-day-status/${projectId}`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <div className="p-4 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></div>;
  if (!data || data.employees.length === 0) return null;

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="personnel-card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-white flex items-center gap-2"><User className="w-4 h-4 text-primary" /> Персонал днес ({data.employees.length})</h3>
        <Button size="sm" variant="outline" onClick={() => { setSelectedEmp(null); setSelectedReportId(null); setReportOpen(true); }}><Plus className="w-3 h-3 mr-1" /> Отчет</Button>
      </div>
      <div className="space-y-2">
        {data.employees.map((emp, i) => (
          <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-muted/10 hover:bg-muted/20 transition-colors" data-testid={`personnel-row-${i}`}>
            <div className="flex items-center gap-3">
              {emp.avatar_url ? (
                <img src={`${process.env.REACT_APP_BACKEND_URL}${emp.avatar_url}`} alt="" className="w-8 h-8 rounded-full object-cover" onError={e => { e.target.style.display = 'none'; }} />
              ) : (
                <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-xs font-bold text-primary">
                  {(emp.first_name?.[0] || "")}{(emp.last_name?.[0] || "")}
                </div>
              )}
              <div>
                <p className="text-sm text-white">{emp.first_name} {emp.last_name}</p>
                {emp.has_report && <p className="text-[10px] text-muted-foreground">{emp.hours_on_project}ч на обекта</p>}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {emp.has_report ? (
                <>
                  <Badge variant="outline" className={`text-[9px] ${STATUS_COLORS[emp.day_status] || ""}`}>{STATUS_LABELS[emp.day_status] || emp.day_status}</Badge>
                  <Badge variant="outline" className={`text-[9px] ${APPROVAL_COLORS[emp.approval_status] || ""}`}>{APPROVAL_LABELS[emp.approval_status] || emp.approval_status}</Badge>
                </>
              ) : (
                <Badge variant="outline" className="text-[9px] bg-gray-500/10 text-gray-500">Без отчет</Badge>
              )}
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0" title="Всички отчети" onClick={async () => {
                setReportsListEmp(emp);
                try {
                  const res = await API.get(`/daily-reports?employee_id=${emp.employee_id}&project_id=${projectId}`);
                  setReportsList(res.data);
                } catch { setReportsList([]); }
                setReportsListOpen(true);
              }} data-testid={`all-reports-btn-${i}`}>
                <List className="w-3.5 h-3.5 text-muted-foreground" />
              </Button>
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => { setSelectedEmp(emp.employee_id); setSelectedReportId(emp.report_id); setReportOpen(true); }}>
                <FileText className="w-3.5 h-3.5 text-primary" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      <DailyReportDialog
        open={reportOpen}
        onOpenChange={setReportOpen}
        employeeId={selectedEmp}
        employeeName=""
        reportDate={data.date}
        existingReportId={selectedReportId}
        onSaved={fetchData}
      />

      {/* All reports list dialog */}
      <Dialog open={reportsListOpen} onOpenChange={setReportsListOpen}>
        <DialogContent className="sm:max-w-[550px] bg-card border-border max-h-[80vh] overflow-y-auto" data-testid="all-reports-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <List className="w-5 h-5 text-primary" />
              Отчети: {reportsListEmp?.first_name} {reportsListEmp?.last_name}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-2 py-2">
            {reportsList.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">Няма отчети</p>
            ) : reportsList.map((r, i) => (
              <div key={i} className="flex items-center justify-between p-2 rounded-lg border border-border hover:bg-muted/20 cursor-pointer" onClick={() => {
                setReportsListOpen(false);
                setSelectedEmp(r.employee_id);
                setSelectedReportId(r.id);
                setReportOpen(true);
              }} data-testid={`report-item-${i}`}>
                <div className="flex items-center gap-3">
                  <span className="text-sm font-mono">{r.report_date}</span>
                  <Badge variant="outline" className={`text-[9px] ${STATUS_COLORS[r.day_status] || ""}`}>{STATUS_LABELS[r.day_status] || r.day_status}</Badge>
                  <Badge variant="outline" className={`text-[9px] ${APPROVAL_COLORS[r.approval_status] || ""}`}>{APPROVAL_LABELS[r.approval_status]}</Badge>
                </div>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="font-mono">{r.total_hours}ч</span>
                  <span>{r.day_entries?.length || 0} СМР</span>
                </div>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
