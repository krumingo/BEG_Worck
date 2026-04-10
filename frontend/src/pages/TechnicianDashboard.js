/**
 * TechnicianDashboard — Mobile-first: Sites → Roster → Daily Report (DRAFT).
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Building2, Clock, Users, Plus, Loader2, Check, Camera, Package,
  FileText, ArrowLeft, Send, AlertTriangle, Trash2, Copy, UserPlus,
} from "lucide-react";
import { toast } from "sonner";

export default function TechnicianDashboard() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [sites, setSites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSite, setSelectedSite] = useState(null);

  // Step management: "roster" | "report"
  const [step, setStep] = useState("roster");

  // Roster state
  const [roster, setRoster] = useState([]);
  const [suggestions, setSuggestions] = useState({ recent: [], all: [] });
  const [showAllWorkers, setShowAllWorkers] = useState(false);
  const [rosterSaving, setRosterSaving] = useState(false);

  // Report state
  const [entries, setEntries] = useState([]);
  const [generalNotes, setGeneralNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [availableTasks, setAvailableTasks] = useState([]);
  const [customSmrMode, setCustomSmrMode] = useState({});

  // Quick SMR
  const [showQuickSMR, setShowQuickSMR] = useState(false);
  const [quickType, setQuickType] = useState("");
  const [quickQty, setQuickQty] = useState("1");
  const [quickDesc, setQuickDesc] = useState("");

  const loadSites = useCallback(async () => {
    try {
      const res = await API.get("/technician/my-sites");
      setSites(res.data.sites || []);
    } catch { /* */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadSites(); }, [loadSites]);

  const openSite = async (site) => {
    setSelectedSite(site);
    setStep("roster");
    setRoster([]);
    setShowAllWorkers(false);
    // Load roster + suggestions + tasks in parallel
    try {
      const today = new Date().toISOString().slice(0, 10);
      const [rosterRes, suggestRes, tasksRes] = await Promise.all([
        API.get(`/technician/site/${site.project_id}/roster?date=${today}`),
        API.get(`/technician/site/${site.project_id}/roster/suggestions`),
        API.get(`/technician/site/${site.project_id}/tasks`),
      ]);
      setRoster(rosterRes.data.workers || []);
      setSuggestions(suggestRes.data || { recent: [], all: [] });
      setAvailableTasks(tasksRes.data.tasks || []);
    } catch {
      setRoster([]);
      setSuggestions({ recent: [], all: [] });
      setAvailableTasks([]);
    }
  };

  // Roster management
  const toggleWorker = (worker) => {
    setRoster(prev => {
      const exists = prev.find(w => w.worker_id === worker.worker_id);
      if (exists) return prev.filter(w => w.worker_id !== worker.worker_id);
      return [...prev, { worker_id: worker.worker_id, worker_name: worker.worker_name }];
    });
  };

  const isInRoster = (workerId) => roster.some(w => w.worker_id === workerId);

  const saveRoster = async () => {
    if (!selectedSite || roster.length === 0) { toast.error(t("technician.addWorkersFirst")); return; }
    setRosterSaving(true);
    try {
      await API.post(`/technician/site/${selectedSite.project_id}/roster`, { workers: roster });
      toast.success(t("technician.rosterSaved"));
      // Move to report step — pre-fill entries from roster
      setEntries(roster.map(w => ({
        id: Date.now() + Math.random(),
        worker_id: w.worker_id,
        worker_name: w.worker_name,
        smr_type: "",
        hours: "8",
        notes: "",
      })));
      setCustomSmrMode({});
      setGeneralNotes("");
      setStep("report");
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setRosterSaving(false); }
  };

  const copyYesterday = async () => {
    if (!selectedSite) return;
    try {
      const res = await API.post(`/technician/site/${selectedSite.project_id}/roster/copy-yesterday`);
      setRoster(res.data.workers || []);
      toast.success(t("technician.copiedYesterday"));
    } catch (err) { toast.error(err.response?.data?.detail || t("technician.noPreviousRoster")); }
  };

  // Report management
  const setEntry = (id, key, val) => setEntries(prev => prev.map(e => e.id === id ? { ...e, [key]: val } : e));
  const removeEntry = (id) => setEntries(prev => prev.filter(e => e.id !== id));

  const handleSubmitReport = async () => {
    if (!selectedSite) return;
    const valid = entries.filter(e => e.smr_type && e.hours && e.worker_id);
    if (!valid.length) { toast.error(t("technician.fillEntries")); return; }
    setSubmitting(true);
    try {
      const res = await API.post("/technician/daily-report", {
        project_id: selectedSite.project_id,
        entries: valid.map(e => ({
          worker_id: e.worker_id,
          worker_name: e.worker_name,
          smr_type: e.smr_type,
          hours: parseFloat(e.hours) || 0,
          notes: e.notes || undefined,
        })),
        general_notes: generalNotes || undefined,
      });
      toast.success(`${t("technician.reportSubmitted")}: ${res.data.total_hours}ч (${t("technician.draft")})`);
      if (res.data.missing_smr_created?.length) {
        toast.info(`${res.data.missing_smr_created.length} ${t("technician.newSMRCreated")}`);
      }
      setSelectedSite(null);
      loadSites();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setSubmitting(false); }
  };

  const handleQuickSMR = async () => {
    if (!quickType.trim() || !selectedSite) return;
    try {
      await API.post("/technician/quick-smr", {
        project_id: selectedSite.project_id,
        smr_type: quickType.trim(),
        description: quickDesc,
        qty: parseFloat(quickQty) || 1,
      });
      toast.success(t("technician.smrCreated"));
      setShowQuickSMR(false);
      setQuickType("");
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  const handlePhotoInvoice = async (e) => {
    if (!selectedSite) return;
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("project_id", selectedSite.project_id);
      fd.append("description", "Фактура от терена");
      await API.post("/technician/photo-invoice", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(t("technician.invoiceUploaded"));
    } catch { toast.error(t("common.error")); }
    e.target.value = "";
  };

  if (loading) return <div className="flex items-center justify-center h-screen"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  // ── SITE VIEW: Roster or Report step ──────────────────────────
  if (selectedSite) {
    // Merge recent + all for display
    const allSuggestions = showAllWorkers ? [...suggestions.recent, ...suggestions.all.filter(a => !suggestions.recent.find(r => r.worker_id === a.worker_id))] : suggestions.recent;

    return (
      <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-site-view">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => { if (step === "report") setStep("roster"); else setSelectedSite(null); }}>
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-bold truncate">{selectedSite.name}</h1>
            <p className="text-xs text-muted-foreground">{selectedSite.address_text || selectedSite.code}</p>
          </div>
          <Badge variant="outline" className="text-xs">{step === "roster" ? t("technician.step1") : t("technician.step2")}</Badge>
        </div>

        {/* ── STEP 1: ROSTER ────────────────────────────────── */}
        {step === "roster" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold flex items-center gap-2">
                <Users className="w-4 h-4 text-cyan-400" /> {t("technician.rosterTitle")}
              </h2>
              <Button size="sm" variant="outline" onClick={copyYesterday}>
                <Copy className="w-3.5 h-3.5 mr-1" /> {t("technician.copyYesterday")}
              </Button>
            </div>

            {/* Current roster */}
            {roster.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">{t("technician.selected")} ({roster.length})</p>
                {roster.map(w => (
                  <div key={w.worker_id} className="flex items-center justify-between p-2.5 rounded-lg border border-primary/30 bg-primary/5">
                    <span className="text-sm font-medium">{w.worker_name}</span>
                    <Button variant="ghost" size="sm" onClick={() => toggleWorker(w)}><Trash2 className="w-3.5 h-3.5 text-red-400" /></Button>
                  </div>
                ))}
              </div>
            )}

            {/* Suggestions */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  {showAllWorkers ? t("technician.allEmployees") : t("technician.recentWorkers")}
                </p>
                <Button variant="ghost" size="sm" className="text-xs" onClick={() => setShowAllWorkers(!showAllWorkers)}>
                  <UserPlus className="w-3 h-3 mr-1" /> {showAllWorkers ? t("technician.showRecent") : t("technician.showAll")}
                </Button>
              </div>
              {allSuggestions.length === 0 ? (
                <p className="text-xs text-muted-foreground py-2">{t("technician.noSuggestions")}</p>
              ) : allSuggestions.map(w => (
                <button key={w.worker_id} onClick={() => toggleWorker(w)}
                  className={`w-full flex items-center justify-between p-2.5 rounded-lg border text-left text-sm ${isInRoster(w.worker_id) ? "border-primary/30 bg-primary/5" : "border-border hover:bg-muted/20"}`}>
                  <span>{w.worker_name}</span>
                  <div className="flex items-center gap-2">
                    {w.source === "recent" && <Badge variant="outline" className="text-[9px]">{t("technician.recent")}</Badge>}
                    {isInRoster(w.worker_id) && <Check className="w-4 h-4 text-primary" />}
                  </div>
                </button>
              ))}
            </div>

            <Button onClick={saveRoster} disabled={rosterSaving || roster.length === 0} className="w-full h-14 text-lg rounded-xl" data-testid="save-roster-btn">
              {rosterSaving ? <Loader2 className="w-5 h-5 mr-2 animate-spin" /> : <Users className="w-5 h-5 mr-2" />}
              {t("technician.saveRoster")} ({roster.length})
            </Button>
          </div>
        )}

        {/* ── STEP 2: REPORT ────────────────────────────────── */}
        {step === "report" && (
          <div className="space-y-3">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" /> {t("technician.dailyReport")}
            </h2>

            {entries.map((entry) => (
              <div key={entry.id} className="rounded-xl border border-border bg-card p-3 space-y-2" data-testid={`report-entry-${entry.id}`}>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{entry.worker_name}</span>
                  {entries.length > 1 && (
                    <Button variant="ghost" size="sm" onClick={() => removeEntry(entry.id)}><Trash2 className="w-4 h-4 text-red-400" /></Button>
                  )}
                </div>

                {/* SMR Select */}
                {availableTasks.length > 0 && !customSmrMode[entry.id] ? (
                  <Select value={entry.smr_type || "none"} onValueChange={v => {
                    if (v === "__custom__") { setCustomSmrMode(prev => ({ ...prev, [entry.id]: true })); setEntry(entry.id, "smr_type", ""); }
                    else if (v !== "none") { setEntry(entry.id, "smr_type", v); }
                  }}>
                    <SelectTrigger className="h-11 text-base" data-testid="entry-smr-type"><SelectValue placeholder={t("technician.selectSmr")} /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none" disabled>{t("technician.selectSmr")}</SelectItem>
                      {availableTasks.map((task, idx) => (
                        <SelectItem key={`${task.smr_type}-${idx}`} value={task.smr_type}>
                          <span>{task.smr_type}{task.smr_subtype ? ` / ${task.smr_subtype}` : ""}</span>
                          {task.source === "budget" && <span className="ml-2 text-[10px] text-muted-foreground opacity-60">(план)</span>}
                        </SelectItem>
                      ))}
                      <SelectItem value="__custom__">{t("technician.otherSmr")}</SelectItem>
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="flex gap-2">
                    <Input value={entry.smr_type} onChange={e => setEntry(entry.id, "smr_type", e.target.value)} placeholder={t("technician.smrType")} className="h-11 text-base flex-1" data-testid="entry-smr-type" />
                    {availableTasks.length > 0 && (
                      <Button variant="outline" size="sm" className="h-11 text-xs" onClick={() => { setCustomSmrMode(prev => ({ ...prev, [entry.id]: false })); setEntry(entry.id, "smr_type", ""); }}>
                        {t("technician.pickFromList")}
                      </Button>
                    )}
                  </div>
                )}

                <div className="flex gap-2">
                  <Input type="number" value={entry.hours} onChange={e => setEntry(entry.id, "hours", e.target.value)} placeholder={t("technician.hours")} className="flex-1 h-11 text-base" min="0" max="24" step="0.5" data-testid="entry-hours" />
                  <Input value={entry.notes} onChange={e => setEntry(entry.id, "notes", e.target.value)} placeholder={t("technician.notes")} className="flex-1 h-11" />
                </div>
              </div>
            ))}

            <Textarea value={generalNotes} onChange={e => setGeneralNotes(e.target.value)} placeholder={t("technician.generalNotes")} className="min-h-[60px]" />

            <Button onClick={handleSubmitReport} disabled={submitting} className="w-full h-14 text-lg rounded-xl" data-testid="submit-report-btn">
              {submitting ? <Loader2 className="w-5 h-5 mr-2 animate-spin" /> : <Send className="w-5 h-5 mr-2" />}
              {t("technician.submitReport")}
            </Button>

            {/* Quick actions */}
            <div className="grid grid-cols-2 gap-3">
              <Button variant="outline" className="h-14 rounded-xl flex-col" onClick={() => { setQuickType(""); setShowQuickSMR(true); }}>
                <AlertTriangle className="w-5 h-5 mb-1 text-orange-400" /><span className="text-xs">{t("technician.newSMR")}</span>
              </Button>
              <label className="cursor-pointer">
                <input type="file" accept="image/*" capture="environment" className="hidden" onChange={handlePhotoInvoice} />
                <div className="h-14 rounded-xl border border-border flex flex-col items-center justify-center hover:bg-muted/20">
                  <Camera className="w-5 h-5 mb-1 text-blue-400" /><span className="text-xs">{t("technician.photoInvoice")}</span>
                </div>
              </label>
            </div>
          </div>
        )}

        {/* Quick SMR Dialog */}
        <Dialog open={showQuickSMR} onOpenChange={setShowQuickSMR}>
          <DialogContent className="max-w-sm">
            <DialogHeader>
              <DialogTitle>{t("technician.newSMR")}</DialogTitle>
              <DialogDescription>{t("technician.newSMRDesc")}</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <Input value={quickType} onChange={e => setQuickType(e.target.value)} placeholder={t("technician.smrType")} className="h-11" data-testid="quick-smr-type" />
              <Input type="number" value={quickQty} onChange={e => setQuickQty(e.target.value)} placeholder={t("technician.qty")} className="h-11" />
              <Textarea value={quickDesc} onChange={e => setQuickDesc(e.target.value)} placeholder={t("technician.description")} />
            </div>
            <DialogFooter>
              <Button onClick={handleQuickSMR} className="w-full h-12" data-testid="submit-quick-smr">{t("common.submit")}</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  // ── SITES LIST ────────────────────────────────────────────────
  return (
    <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-dashboard">
      <div className="text-center mb-6">
        <h1 className="text-xl font-bold">{t("technician.myDay")}</h1>
        <p className="text-sm text-muted-foreground">{new Date().toLocaleDateString("bg-BG", { weekday: "long", day: "numeric", month: "long" })}</p>
      </div>

      {sites.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <Building2 className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>{t("technician.noSites")}</p>
        </div>
      ) : (
        sites.map(site => (
          <button key={site.project_id} onClick={() => openSite(site)} className="w-full rounded-xl border border-border bg-card p-4 text-left hover:border-primary/40 transition-colors" data-testid={`site-card-${site.project_id}`}>
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <h3 className="font-bold text-base truncate">{site.name}</h3>
                <p className="text-xs text-muted-foreground truncate">{site.address_text || site.code}</p>
              </div>
              {site.has_report_today ? (
                <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-[10px]"><Check className="w-3 h-3 mr-1" />{t("technician.reported")}</Badge>
              ) : (
                <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-[10px]"><AlertTriangle className="w-3 h-3 mr-1" />{t("technician.noReport")}</Badge>
              )}
            </div>
            <div className="flex gap-4 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><Users className="w-3 h-3" />{site.today_workers}</span>
              <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{site.today_hours}ч</span>
              {site.pending_requests > 0 && (
                <span className="flex items-center gap-1"><Package className="w-3 h-3 text-amber-400" />{site.pending_requests}</span>
              )}
            </div>
          </button>
        ))
      )}
    </div>
  );
}
