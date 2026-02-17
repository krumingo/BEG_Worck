import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatTime } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertTriangle,
  CalendarCheck,
  FileText,
  Send,
  Shield,
  Loader2,
  Bell,
} from "lucide-react";

const LOG_STATUS_COLORS = {
  Open: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Reminded: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  Resolved: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Excused: "bg-blue-500/20 text-blue-400 border-blue-500/30",
};

export default function RemindersPage() {
  const { t } = useTranslation();
  const [date, setDate] = useState(new Date().toISOString().split("T")[0]);
  const [missingAtt, setMissingAtt] = useState([]);
  const [missingRep, setMissingRep] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  // Excuse dialog
  const [excuseOpen, setExcuseOpen] = useState(false);
  const [excuseTarget, setExcuseTarget] = useState(null);
  const [excuseReason, setExcuseReason] = useState("");
  const [excuseType, setExcuseType] = useState("");
  const [excusing, setExcusing] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [attRes, repRes, logsRes] = await Promise.all([
        API.get(`/reminders/missing-attendance?date=${date}`),
        API.get(`/reminders/missing-work-reports?date=${date}`),
        API.get(`/reminders/logs?date=${date}`),
      ]);
      setMissingAtt(attRes.data);
      setMissingRep(repRes.data);
      setLogs(logsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSendReminders = async (type, userIds, projectId) => {
    setSending(true);
    try {
      const res = await API.post("/reminders/send", {
        type,
        date,
        user_ids: userIds,
        project_id: projectId || null,
      });
      alert(`Sent ${res.data.sent} of ${res.data.total} reminders`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed");
    } finally {
      setSending(false);
    }
  };

  const openExcuse = (userId, type, projectId) => {
    setExcuseTarget(userId);
    setExcuseType(type);
    setExcuseReason("");
    setExcuseOpen(true);
  };

  const handleExcuse = async () => {
    if (!excuseReason) return;
    setExcusing(true);
    try {
      await API.post("/reminders/excuse", {
        type: excuseType,
        date,
        user_id: excuseTarget,
        reason: excuseReason,
      });
      setExcuseOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed");
    } finally {
      setExcusing(false);
    }
  };

  return (
    <div className="p-8 max-w-[1200px]" data-testid="reminders-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Reminders & Alerts</h1>
          <p className="text-sm text-muted-foreground mt-1">Monitor attendance and report compliance</p>
        </div>
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-[180px] bg-card" data-testid="reminders-date" />
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6" data-testid="reminder-cards">
        <div className="stat-card animate-in" data-testid="missing-att-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Missing Attendance</span>
            <CalendarCheck className="w-4 h-4 text-amber-400" />
          </div>
          <p className="text-2xl font-bold text-amber-400">{loading ? "..." : missingAtt.length}</p>
        </div>
        <div className="stat-card animate-in" style={{ animationDelay: "80ms" }} data-testid="missing-rep-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Missing Reports</span>
            <FileText className="w-4 h-4 text-blue-400" />
          </div>
          <p className="text-2xl font-bold text-blue-400">{loading ? "..." : missingRep.length}</p>
        </div>
        <div className="stat-card animate-in" style={{ animationDelay: "160ms" }} data-testid="reminders-sent-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Reminders Sent</span>
            <Bell className="w-4 h-4 text-violet-400" />
          </div>
          <p className="text-2xl font-bold text-violet-400">{loading ? "..." : logs.filter((l) => l.status === "Reminded").length}</p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <Tabs defaultValue="attendance" className="w-full" data-testid="reminder-tabs">
          <TabsList className="bg-card border border-border">
            <TabsTrigger value="attendance" data-testid="tab-missing-att">
              <CalendarCheck className="w-4 h-4 mr-2" /> Missing Attendance ({missingAtt.length})
            </TabsTrigger>
            <TabsTrigger value="reports" data-testid="tab-missing-rep">
              <FileText className="w-4 h-4 mr-2" /> Missing Reports ({missingRep.length})
            </TabsTrigger>
            <TabsTrigger value="logs" data-testid="tab-logs">
              <Bell className="w-4 h-4 mr-2" /> Reminder Log ({logs.length})
            </TabsTrigger>
          </TabsList>

          {/* Missing Attendance */}
          <TabsContent value="attendance" className="mt-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-foreground">Users with no attendance today</h3>
              {missingAtt.length > 0 && (
                <Button size="sm" onClick={() => handleSendReminders("MissingAttendance", missingAtt.map((m) => m.user_id))} disabled={sending} data-testid="send-att-reminders">
                  {sending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Send className="w-4 h-4 mr-1" />}
                  Remind All ({missingAtt.length})
                </Button>
              )}
            </div>
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">User</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Role</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {missingAtt.length === 0 ? (
                    <TableRow><TableCell colSpan={3} className="text-center py-8 text-muted-foreground">Everyone has checked in</TableCell></TableRow>
                  ) : (
                    missingAtt.map((m) => (
                      <TableRow key={m.user_id} className="table-row-hover" data-testid={`missing-att-${m.user_id}`}>
                        <TableCell>
                          <p className="font-medium text-foreground">{m.user_name}</p>
                          <p className="text-xs text-muted-foreground">{m.user_email}</p>
                        </TableCell>
                        <TableCell className="text-muted-foreground">{m.user_role}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button size="sm" variant="outline" onClick={() => handleSendReminders("MissingAttendance", [m.user_id])} disabled={sending}>
                              <Send className="w-3.5 h-3.5 mr-1" /> Remind
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => openExcuse(m.user_id, "MissingAttendance")}>
                              <Shield className="w-3.5 h-3.5 mr-1" /> Excuse
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

          {/* Missing Reports */}
          <TabsContent value="reports" className="mt-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-foreground">Users with no submitted report</h3>
              {missingRep.length > 0 && (
                <Button size="sm" onClick={() => handleSendReminders("MissingWorkReport", missingRep.map((m) => m.user_id), missingRep[0]?.project_id)} disabled={sending} data-testid="send-rep-reminders">
                  {sending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Send className="w-4 h-4 mr-1" />}
                  Remind All ({missingRep.length})
                </Button>
              )}
            </div>
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">User</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Project</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {missingRep.length === 0 ? (
                    <TableRow><TableCell colSpan={3} className="text-center py-8 text-muted-foreground">All reports submitted</TableCell></TableRow>
                  ) : (
                    missingRep.map((m, i) => (
                      <TableRow key={`${m.user_id}-${m.project_id}-${i}`} className="table-row-hover" data-testid={`missing-rep-${m.user_id}`}>
                        <TableCell>
                          <p className="font-medium text-foreground">{m.user_name}</p>
                          <p className="text-xs text-muted-foreground">{m.user_email}</p>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-primary">{m.project_code}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button size="sm" variant="outline" onClick={() => handleSendReminders("MissingWorkReport", [m.user_id], m.project_id)} disabled={sending}>
                              <Send className="w-3.5 h-3.5 mr-1" /> Remind
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => openExcuse(m.user_id, "MissingWorkReport", m.project_id)}>
                              <Shield className="w-3.5 h-3.5 mr-1" /> Excuse
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

          {/* Reminder Logs */}
          <TabsContent value="logs" className="mt-4">
            <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="reminder-logs-table">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">User</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Type</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Project</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Sent</TableHead>
                    <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Last</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.length === 0 ? (
                    <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">No reminder logs</TableCell></TableRow>
                  ) : (
                    logs.map((l) => (
                      <TableRow key={l.id} className="table-row-hover" data-testid={`log-${l.id}`}>
                        <TableCell>
                          <p className="font-medium text-foreground text-sm">{l.user_name}</p>
                          <p className="text-xs text-muted-foreground">{l.user_email}</p>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={`text-xs ${l.type === "MissingAttendance" ? "text-amber-400 border-amber-500/30" : "text-blue-400 border-blue-500/30"}`}>
                            {l.type === "MissingAttendance" ? "Attendance" : "Report"}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-primary">{l.project_code || "-"}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className={`text-xs ${LOG_STATUS_COLORS[l.status] || ""}`}>{l.status}</Badge>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">{l.reminder_count}x</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {l.last_reminded_at ? new Date(l.last_reminded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "-"}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        </Tabs>
      )}

      {/* Excuse Dialog */}
      <Dialog open={excuseOpen} onOpenChange={setExcuseOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="excuse-dialog">
          <DialogHeader>
            <DialogTitle>Excuse User</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-2">
              <label className="text-sm text-muted-foreground">Reason *</label>
              <Input value={excuseReason} onChange={(e) => setExcuseReason(e.target.value)} placeholder="e.g., Sick leave, approved absence..." className="bg-background" data-testid="excuse-reason-input" />
            </div>
            <Button onClick={handleExcuse} disabled={excusing || !excuseReason} className="w-full" data-testid="excuse-confirm-button">
              {excusing && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              Excuse
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
