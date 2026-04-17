/**
 * TechnicianDashboard — Mobile-first wizard portal.
 * Flow: My Day → Object → Roster → Report (per-worker multi-line OR group) → Review → Submit
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Building2, Clock, Users, Plus, Loader2, Check, Camera, Package,
  FileText, ArrowLeft, Send, AlertTriangle, Trash2, Copy, UserPlus,
  MapPin, Phone, Pencil, Eye,
} from "lucide-react";
import { toast } from "sonner";

export default function TechnicianDashboard() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = ["Admin", "Owner", "SiteManager"].includes(user?.role);

  // Navigation state
  const [screen, setScreen] = useState("myDay"); // myDay | object | people | roster | report | review
  const [sites, setSites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSite, setSelectedSite] = useState(null);

  // Roster
  const [roster, setRoster] = useState([]);
  const [suggestions, setSuggestions] = useState({ recent: [], all: [] });
  const [showAll, setShowAll] = useState(false);
  const [rosterSaving, setRosterSaving] = useState(false);

  // People screen
  const [enrichedRoster, setEnrichedRoster] = useState([]);
  const [savedRosterState, setSavedRosterState] = useState([]); // snapshot of last saved state
  const [availablePeople, setAvailablePeople] = useState([]);
  const [showAddPeople, setShowAddPeople] = useState(false);
  const [selectedToAdd, setSelectedToAdd] = useState([]);
  const [pickerSearch, setPickerSearch] = useState("");
  const [pickerFilter, setPickerFilter] = useState("all");

  // Report
  const [reportMode, setReportMode] = useState("person"); // person | group
  const [entries, setEntries] = useState([]); // [{id, worker_id, worker_name, lines: [{smr, hours, notes}]}]
  const [availableTasks, setAvailableTasks] = useState([]);
  const [generalNotes, setGeneralNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Group mode
  const [groupSmr, setGroupSmr] = useState("");
  const [groupHours, setGroupHours] = useState("8");
  const [groupWorkers, setGroupWorkers] = useState([]);

  // Draft editing
  const [existingDrafts, setExistingDrafts] = useState([]);
  const [workerDayHours, setWorkerDayHours] = useState({}); // {worker_id: {total_hours, projects_count}}

  // Object detail
  const [siteDetail, setSiteDetail] = useState(null);

  // Quick actions
  const [quickScreen, setQuickScreen] = useState(null); // quickSmr | photoInvoice

  const loadSites = useCallback(async () => {
    try {
      const res = await API.get("/technician/my-sites");
      setSites(res.data.sites || []);
    } catch { /* */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadSites(); }, [loadSites]);

  // ── Open Object ─────────────────────────────────────────────
  const openObject = async (site) => {
    setSelectedSite(site);
    setScreen("object");
    setSiteDetail(null);
    try {
      const [tasksRes, detailRes, draftsRes, rosterRes] = await Promise.all([
        API.get(`/technician/site/${site.project_id}/tasks`),
        API.get(`/technician/site/${site.project_id}/detail`),
        API.get(`/technician/site/${site.project_id}/my-drafts`),
        API.get(`/technician/site/${site.project_id}/roster/enriched`),
      ]);
      setAvailableTasks(tasksRes.data.tasks || []);
      setSiteDetail(detailRes.data);
      setExistingDrafts(draftsRes.data.items || []);
      setEnrichedRoster(rosterRes.data.workers || []);
    } catch { setAvailableTasks([]); setSiteDetail(null); setExistingDrafts([]); setEnrichedRoster([]); }
  };

  // ── Open Roster ─────────────────────────────────────────────
  const openRoster = async () => {
    setScreen("roster");
    const today = new Date().toISOString().slice(0, 10);
    try {
      const [rosterRes, suggestRes, draftsRes] = await Promise.all([
        API.get(`/technician/site/${selectedSite.project_id}/roster?date=${today}`),
        API.get(`/technician/site/${selectedSite.project_id}/roster/suggestions`),
        API.get(`/technician/site/${selectedSite.project_id}/my-drafts`),
      ]);
      setRoster(rosterRes.data.workers || []);
      setSuggestions(suggestRes.data || { recent: [], all: [] });
      setExistingDrafts(draftsRes.data.items || []);
    } catch {
      setRoster([]); setSuggestions({ recent: [], all: [] }); setExistingDrafts([]);
    }
  };

  const toggleWorker = (w) => setRoster(prev => prev.find(r => r.worker_id === w.worker_id) ? prev.filter(r => r.worker_id !== w.worker_id) : [...prev, { worker_id: w.worker_id, worker_name: w.worker_name }]);
  const isInRoster = (wid) => roster.some(r => r.worker_id === wid);

  const saveRosterAndContinue = async () => {
    if (!roster.length) { toast.error(t("technician.addWorkersFirst")); return; }
    setRosterSaving(true);
    try {
      await API.post(`/technician/site/${selectedSite.project_id}/roster`, { workers: roster });
      setEntries(roster.map(w => ({ id: Date.now() + Math.random(), worker_id: w.worker_id, worker_name: w.worker_name, lines: [{ smr: "", hours: "8", notes: "" }] })));
      setGroupWorkers([]);
      // Fetch day hours for all workers
      try {
        const ids = roster.map(w => w.worker_id).join(",");
        const hRes = await API.get(`/technician/worker-day-hours?worker_ids=${ids}`);
        setWorkerDayHours(hRes.data.workers || {});
      } catch { setWorkerDayHours({}); }
      setScreen("report");
    } catch (err) { toast.error(err.response?.data?.detail || "Error"); }
    finally { setRosterSaving(false); }
  };

  const copyYesterday = async () => {
    try {
      const res = await API.post(`/technician/site/${selectedSite.project_id}/roster/copy-yesterday`);
      setRoster(res.data.workers || []);
      toast.success(t("technician.copiedYesterday"));
    } catch { toast.error(t("technician.noPreviousRoster")); }
  };

  // ── People Management ───────────────────────────────────────
  const [siteWorkers, setSiteWorkers] = useState([]);

  const openPeople = async () => {
    setScreen("people");
    setShowAddPeople(false);
    try {
      const [enrichedRes, shortlistRes, availRes] = await Promise.all([
        API.get(`/technician/site/${selectedSite.project_id}/roster/enriched`),
        API.get(`/projects/${selectedSite.project_id}/site-workers`),
        API.get(`/technician/site/${selectedSite.project_id}/roster/available`),
      ]);
      const workers = enrichedRes.data.workers || [];
      setEnrichedRoster(workers);
      setSavedRosterState(workers.map(w => ({ worker_id: w.worker_id, status: w.status || "Present" })));
      setSiteWorkers(shortlistRes.data.workers || []);
      setAvailablePeople(availRes.data.available || []);
    } catch { setEnrichedRoster([]); setSavedRosterState([]); setSiteWorkers([]); setAvailablePeople([]); }
  };

  // ── Report helpers ──────────────────────────────────────────
  const addLine = (entryId) => setEntries(prev => prev.map(e => e.id === entryId ? { ...e, lines: [...e.lines, { smr: "", hours: "", notes: "" }] } : e));
  const removeLine = (entryId, lineIdx) => setEntries(prev => prev.map(e => e.id === entryId ? { ...e, lines: e.lines.filter((_, i) => i !== lineIdx) } : e));
  const setLine = (entryId, lineIdx, field, val) => setEntries(prev => prev.map(e => e.id === entryId ? { ...e, lines: e.lines.map((l, i) => i === lineIdx ? { ...l, [field]: val } : l) } : e));

  // ── Submit ──────────────────────────────────────────────────
  const buildPayload = () => {
    const allEntries = [];
    if (reportMode === "person") {
      for (const e of entries) {
        for (const ln of e.lines) {
          if (ln.smr && ln.hours) {
            allEntries.push({ worker_id: e.worker_id, worker_name: e.worker_name, smr_type: ln.smr, hours: parseFloat(ln.hours) || 0, notes: ln.notes || undefined });
          }
        }
      }
    } else {
      // Group mode
      for (const wid of groupWorkers) {
        const w = roster.find(r => r.worker_id === wid);
        if (w && groupSmr && groupHours) {
          allEntries.push({ worker_id: wid, worker_name: w.worker_name, smr_type: groupSmr, hours: parseFloat(groupHours) || 0 });
        }
      }
    }
    return allEntries;
  };

  const handleSubmit = async () => {
    const payload = buildPayload();
    if (!payload.length) { toast.error(t("technician.fillEntries")); return; }
    setSubmitting(true);
    try {
      const res = await API.post("/technician/daily-report", { project_id: selectedSite.project_id, entries: payload, general_notes: generalNotes || undefined });

      // Check for hours warnings per worker
      const warnings = res.data?.hours_warnings || [];
      if (warnings.length > 0) {
        for (const w of warnings) {
          if (w.level === "critical") {
            toast.error(`${w.worker_name}: ${w.total_hours}ч за деня! Проверете.`, { duration: 8000 });
          } else if (w.level === "warning") {
            toast.warning(`${w.worker_name}: ${w.total_hours}ч за деня. Извънреден труд?`, { duration: 6000 });
          }
        }
      }

      toast.success(`${t("technician.reportSubmitted")}: ${res.data.total_hours}ч`);
      setScreen("myDay");
      setSelectedSite(null);
      loadSites();
    } catch (err) { toast.error(err.response?.data?.detail || "Error"); }
    finally { setSubmitting(false); }
  };

  // ── Quick SMR ───────────────────────────────────────────────
  const [qSmr, setQSmr] = useState(""); const [qQty, setQQty] = useState("1"); const [qDesc, setQDesc] = useState("");
  const submitQuickSmr = async () => {
    if (!qSmr.trim()) return;
    try { await API.post("/technician/quick-smr", { project_id: selectedSite.project_id, smr_type: qSmr, description: qDesc, qty: parseFloat(qQty) || 1 }); toast.success(t("technician.smrCreated")); setQuickScreen(null); } catch (err) { toast.error("Error"); }
  };

  const submitPhoto = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    try { const fd = new FormData(); fd.append("file", file); fd.append("project_id", selectedSite.project_id); fd.append("description", "Фактура от терена"); await API.post("/technician/photo-invoice", fd, { headers: { "Content-Type": "multipart/form-data" } }); toast.success(t("technician.invoiceUploaded")); setQuickScreen(null); } catch { toast.error("Error"); }
    e.target.value = "";
  };

  if (loading) return <div className="flex items-center justify-center h-screen"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  const allSugg = showAll ? [...suggestions.recent, ...suggestions.all.filter(a => !suggestions.recent.find(r => r.worker_id === a.worker_id))] : suggestions.recent;
  const payload = screen === "review" ? buildPayload() : [];

  // ════════════════════════════════════════════════════════════
  // QUICK SCREENS (overlay)
  // ════════════════════════════════════════════════════════════
  if (quickScreen === "quickSmr") return (
    <div className="p-4 max-w-lg mx-auto space-y-4">
      <div className="flex items-center gap-3"><Button variant="ghost" size="sm" onClick={() => setQuickScreen(null)}><ArrowLeft className="w-4 h-4" /></Button><h1 className="text-lg font-bold">{t("technician.newSMR")}</h1></div>
      <Input value={qSmr} onChange={e => setQSmr(e.target.value)} placeholder={t("technician.smrType")} className="h-12 text-base" />
      <Input type="number" value={qQty} onChange={e => setQQty(e.target.value)} placeholder={t("technician.qty")} className="h-12" />
      <Textarea value={qDesc} onChange={e => setQDesc(e.target.value)} placeholder={t("technician.description")} />
      <Button onClick={submitQuickSmr} className="w-full h-14 text-lg rounded-xl">{t("common.save")}</Button>
    </div>
  );

  if (quickScreen === "photoInvoice") return (
    <div className="p-4 max-w-lg mx-auto space-y-4">
      <div className="flex items-center gap-3"><Button variant="ghost" size="sm" onClick={() => setQuickScreen(null)}><ArrowLeft className="w-4 h-4" /></Button><h1 className="text-lg font-bold">{t("technician.photoInvoice")}</h1></div>
      <div className="border-2 border-dashed border-border rounded-xl p-12 text-center"><Camera className="w-12 h-12 mx-auto mb-3 text-muted-foreground" /><input type="file" accept="image/*" capture="environment" onChange={submitPhoto} className="block mx-auto" /></div>
    </div>
  );

  // ════════════════════════════════════════════════════════════
  // MY DAY
  // ════════════════════════════════════════════════════════════
  if (screen === "myDay") return (
    <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-my-day">
      <div className="text-center mb-4">
        <div className="w-16 h-16 rounded-full bg-primary/20 flex items-center justify-center text-xl font-bold text-primary mx-auto mb-2">{user?.first_name?.[0]}{user?.last_name?.[0]}</div>
        <h1 className="text-xl font-bold">{user?.first_name} {user?.last_name}</h1>
        <p className="text-sm text-muted-foreground">{new Date().toLocaleDateString("bg-BG", { weekday: "long", day: "numeric", month: "long" })}</p>
        {isAdmin && <Badge className="mt-2 bg-violet-500/20 text-violet-400 border-violet-500/30">{t("technician.adminMode")}</Badge>}
      </div>
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">{t("technician.mySites")}</h2>
      {sites.length === 0 ? <p className="text-center py-8 text-muted-foreground">{t("technician.noSites")}</p> : sites.map(s => (
        <button key={s.project_id} onClick={() => openObject(s)} className="w-full rounded-2xl border border-border bg-card p-5 text-left hover:border-primary/40 active:scale-[0.98] transition-all" data-testid={`site-${s.project_id}`}>
          <div className="flex items-start justify-between mb-2">
            <h3 className="font-bold text-base">{s.name}</h3>
            {s.reported_workers > 0 ? (
              s.roster_count > 0 ? <Badge className={`text-[10px] ${s.reported_workers >= s.roster_count ? "bg-emerald-500/20 text-emerald-400" : "bg-amber-500/20 text-amber-400"}`}><Check className="w-3 h-3 mr-1" />{s.reported_workers}/{s.roster_count} отчета</Badge>
              : <Badge className="bg-emerald-500/20 text-emerald-400 text-[10px]"><Check className="w-3 h-3 mr-1" />{s.reported_workers} отчета</Badge>
            ) : <Badge className="bg-amber-500/20 text-amber-400 text-[10px]"><AlertTriangle className="w-3 h-3 mr-1" />{t("technician.noReport")}</Badge>}
          </div>
          <p className="text-xs text-muted-foreground">{s.address_text || s.code}</p>
          <div className="flex gap-4 mt-2 text-xs text-muted-foreground">
            <span className="flex items-center gap-1"><Users className="w-3 h-3" />{s.today_workers}</span>
            <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{s.today_hours}ч</span>
          </div>
        </button>
      ))}
    </div>
  );

  // ════════════════════════════════════════════════════════════
  // OBJECT SCREEN — Централен дневен operational екран
  // ════════════════════════════════════════════════════════════
  if (screen === "object" && selectedSite) {
    const d = siteDetail;
    const ct = d?.counters || {};
    const fullAddr = d?.address_text || "";

    // Enriched roster data for "Хора днес" inline display
    const rosterWorkers = enrichedRoster.length > 0 ? enrichedRoster : [];
    const hasRoster = rosterWorkers.length > 0 || (ct.roster_count || 0) > 0;

    // Start report flow: skip Step 1 if roster exists
    const startReport = () => {
      if (!hasRoster) {
        toast.error("Първо запишете кои хора са на обекта днес.");
        openPeople();
        return;
      }
      // Skip Step 1 — go directly to Step 2
      const rosterForReport = rosterWorkers.length > 0
        ? rosterWorkers.filter(w => w.status === "Present" || w.status === "Late")
        : roster;
      if (rosterForReport.length === 0) {
        toast.error("Няма потвърдени присъстващи. Маркирайте хора в секция Хора.");
        openPeople();
        return;
      }
      // Set roster + entries from enriched data, then go to report
      setRoster(rosterForReport.map(w => ({ worker_id: w.worker_id, worker_name: w.worker_name })));
      setEntries(rosterForReport.map(w => ({ id: Date.now() + Math.random(), worker_id: w.worker_id, worker_name: w.worker_name, lines: [{ smr: "", hours: "8", notes: "" }] })));
      setGroupWorkers([]);
      // Fetch day hours
      const ids = rosterForReport.map(w => w.worker_id).join(",");
      API.get(`/technician/worker-day-hours?worker_ids=${ids}`).then(r => setWorkerDayHours(r.data.workers || {})).catch(() => setWorkerDayHours({}));
      // Fetch tasks
      API.get(`/technician/site/${selectedSite.project_id}/tasks`).then(r => setAvailableTasks(r.data.tasks || [])).catch(() => setAvailableTasks([]));
      setScreen("report");
    };

    return (
      <div className="p-4 max-w-lg mx-auto space-y-3" data-testid="tech-object">
        {/* Header — compact */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => { setScreen("myDay"); setSelectedSite(null); }}><ArrowLeft className="w-4 h-4" /></Button>
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-bold truncate">{selectedSite.name}</h2>
            {fullAddr && <p className="text-[10px] text-muted-foreground truncate">{fullAddr}</p>}
          </div>
        </div>

        {/* KPI Counters */}
        <div className="grid grid-cols-3 gap-2">
          <div className="rounded-xl border border-border bg-card p-2.5 text-center">
            <p className="text-xl font-bold text-cyan-400">{ct.roster_count || 0}</p>
            <p className="text-[9px] text-muted-foreground">На обекта</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-2.5 text-center">
            <p className="text-xl font-bold text-emerald-400">{ct.reported_workers || 0}</p>
            <p className="text-[9px] text-muted-foreground">Отчетено</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-2.5 text-center">
            <p className="text-xl font-bold text-primary">{ct.reported_hours || 0}<span className="text-sm">ч</span></p>
            <p className="text-[9px] text-muted-foreground">Часове днес</p>
          </div>
        </div>

        {/* ══ ХОРА ДНЕС — постоянен контролен блок ══ */}
        <div className="rounded-2xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-2.5 bg-muted/20 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4 text-cyan-400" />
              <span className="text-sm font-semibold">Хора днес</span>
              {rosterWorkers.length > 0 && <Badge variant="outline" className="text-[9px]">{rosterWorkers.length}</Badge>}
            </div>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={openPeople}>Редактирай</Button>
          </div>
          <div className="p-3 space-y-1.5">
            {rosterWorkers.length === 0 ? (
              <div className="text-center py-4">
                <p className="text-sm text-muted-foreground mb-2">Няма записани хора за днес</p>
                <Button size="sm" onClick={openPeople}><Plus className="w-4 h-4 mr-1" />Добави хора</Button>
              </div>
            ) : rosterWorkers.map(w => {
              const isPresent = w.status === "Present" || w.status === "Late";
              const isAdmin = w.status === "SickLeave" || w.status === "Leave" || w.status === "Vacation";
              const dayH = w.total_hours || 0;
              const hCls = dayH > 12 ? "text-red-400" : dayH > 8 ? "text-amber-400" : dayH > 0 ? "text-emerald-400" : "text-muted-foreground";
              const hasReport = dayH > 0;
              return (
                <div key={w.worker_id} className="flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-muted/10">
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isPresent ? "bg-emerald-500" : isAdmin ? "bg-red-500" : "bg-gray-500"}`} />
                  <span className="text-sm flex-1 truncate">{w.worker_name}</span>
                  {isAdmin && <Badge className="text-[8px] bg-red-500/15 text-red-400">{{ SickLeave: "Болен", Leave: "Отпуск", Vacation: "Отпуск" }[w.status]}</Badge>}
                  {hasReport && <span className={`text-[10px] font-mono ${hCls}`}>{dayH}ч</span>}
                  {!hasReport && isPresent && <span className="text-[9px] text-muted-foreground">—</span>}
                  {hasReport ? <Check className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" /> : isPresent ? <Clock className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" /> : null}
                </div>
              );
            })}
          </div>
        </div>

        {/* Action Buttons — 3 columns (Отчет, СМР, Фактура) */}
        <div className="grid grid-cols-3 gap-3">
          <Button onClick={startReport} className="h-16 rounded-2xl flex-col text-xs font-semibold"><FileText className="w-5 h-5 mb-1" />Отчет за деня</Button>
          <Button variant="outline" onClick={() => { setQSmr(""); setQuickScreen("quickSmr"); }} className="h-16 rounded-2xl flex-col text-xs"><AlertTriangle className="w-5 h-5 mb-1 text-orange-400" />Ново СМР</Button>
          <Button variant="outline" onClick={() => setQuickScreen("photoInvoice")} className="h-16 rounded-2xl flex-col text-xs"><Camera className="w-5 h-5 mb-1 text-blue-400" />Снимай фактура</Button>
        </div>

        {/* Чернови за днес — with delete */}
        {existingDrafts.length > 0 && (
          <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-3">
            <p className="text-xs font-semibold text-amber-400 mb-2">Чернови за днес ({existingDrafts.length})</p>
            {existingDrafts.slice(0, 10).map(dd => (
              <div key={dd.id} className="flex items-center justify-between py-1">
                <p className="text-xs text-muted-foreground">{dd.worker_name} — {dd.smr_type} — {dd.hours}ч</p>
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={async () => {
                  if (!window.confirm(`Изтрий чернова: ${dd.worker_name} — ${dd.smr_type} — ${dd.hours}ч?`)) return;
                  try {
                    await API.delete(`/technician/draft/${dd.id}`);
                    toast.success("Черновата е изтрита");
                    const [draftsRes, detailRes] = await Promise.all([
                      API.get(`/technician/site/${selectedSite.project_id}/my-drafts`),
                      API.get(`/technician/site/${selectedSite.project_id}/detail`),
                    ]);
                    setExistingDrafts(draftsRes.data.items || []);
                    setSiteDetail(detailRes.data);
                  } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
                }}><Trash2 className="w-3 h-3 text-red-400" /></Button>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ════════════════════════════════════════════════════════════
  // PEOPLE — ЕДИНСТВЕН ДНЕВЕН СПИСЪК
  // Save е единствената точка на commit. Всичко преди Save е local staging.
  // ════════════════════════════════════════════════════════════
  if (screen === "people") {
    // === Change detection ===
    const savedMap = Object.fromEntries(savedRosterState.map(w => [w.worker_id, w.status]));
    const savedIds = new Set(savedRosterState.map(w => w.worker_id));
    const currentIds = new Set(enrichedRoster.map(w => w.worker_id));
    const removedFromSaved = savedRosterState.filter(w => !currentIds.has(w.worker_id));

    const getState = (w) => {
      if (!savedIds.has(w.worker_id)) return "new";
      if (w.status !== savedMap[w.worker_id]) return "changed";
      return "saved";
    };
    const hasChanges = enrichedRoster.some(w => getState(w) !== "saved") || removedFromSaved.length > 0;

    // === Local-only actions (NO backend calls) ===
    const localRemove = (workerId) => {
      setEnrichedRoster(prev => prev.filter(r => r.worker_id !== workerId));
    };

    const localAddFromShortlist = (w) => {
      if (enrichedRoster.some(r => r.worker_id === w.worker_id)) return;
      setEnrichedRoster(prev => [...prev, {
        worker_id: w.worker_id, worker_name: w.worker_name,
        avatar_url: w.avatar_url || null, position: w.position || "",
        status: "Present",
      }]);
    };

    const localAddFromPicker = () => {
      if (!selectedToAdd.length) return;
      const existing = new Set(enrichedRoster.map(r => r.worker_id));
      const toAdd = selectedToAdd.filter(wid => !existing.has(wid)).map(wid => {
        const p = availablePeople.find(a => a.worker_id === wid);
        return {
          worker_id: wid, worker_name: p?.worker_name || "",
          avatar_url: p?.avatar_url || null, position: p?.position || "",
          status: "Present",
        };
      });
      setEnrichedRoster(prev => [...prev, ...toAdd]);
      setSelectedToAdd([]);
      setShowAddPeople(false);
    };

    // === SAVE — единствен commit point ===
    const handleSave = async () => {
      // Check for conflicts with removed workers that have reports
      for (const removed of removedFromSaved) {
        try {
          const check = await API.post(`/technician/site/${selectedSite.project_id}/check-remove-worker`, { worker_id: removed.worker_id });
          const d = check.data;
          if (d.submitted_count > 0 || d.approved_count > 0) {
            toast.error(`Не може да махнете работник с подаден/одобрен отчет. Първо коригирайте отчета.`);
            return;
          }
          if (d.draft_count > 0) {
            const ok = window.confirm(`Работникът има ${d.draft_count} чернови за днес.\nПри запис те ще бъдат изтрити. Продължи?`);
            if (!ok) return;
          }
        } catch { /* continue if check fails */ }
      }

      try {
        // Commit attendance (creates/updates/removes attendance_entries + roster)
        const workers = enrichedRoster.map(w => ({
          worker_id: w.worker_id, worker_name: w.worker_name, status: w.status || "Present",
        }));
        const res = await API.post(`/technician/site/${selectedSite.project_id}/attendance`, { workers });

        // Delete drafts for removed workers
        for (const removed of removedFromSaved) {
          try {
            await API.post(`/technician/site/${selectedSite.project_id}/remove-worker-with-drafts`, { worker_id: removed.worker_id });
          } catch { /* might not have drafts */ }
        }

        toast.success(`Записано: ${res.data.present} на работа от ${res.data.total}`);
        setSavedRosterState(enrichedRoster.map(w => ({ worker_id: w.worker_id, status: w.status || "Present" })));

        // Refresh counters + drafts
        try {
          const [detailRes, draftsRes] = await Promise.all([
            API.get(`/technician/site/${selectedSite.project_id}/detail`),
            API.get(`/technician/site/${selectedSite.project_id}/my-drafts`),
          ]);
          setSiteDetail(detailRes.data);
          setExistingDrafts(draftsRes.data.items || []);
        } catch {}
      } catch (err) { toast.error(err.response?.data?.detail || "Грешка при запис"); }
    };

    const handleBack = () => {
      if (hasChanges && !window.confirm("Има незапазени промени. Излизате?")) return;
      setScreen("object");
    };

    // === Counters ===
    const presentCount = enrichedRoster.filter(w => w.status === "Present" || w.status === "Late").length;
    const todayStr = new Date().toLocaleDateString("bg-BG", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

    // === Shortlist: filter out anyone already in the daily list ===
    const dailyIds = new Set(enrichedRoster.map(w => w.worker_id));
    const shortlistFiltered = siteWorkers.filter(w => w.is_active && !dailyIds.has(w.worker_id));

    // === Available for + Добави: filter out daily list AND shortlist shown ===
    const allShownIds = new Set([...dailyIds, ...shortlistFiltered.map(w => w.worker_id)]);

    const STATE_BADGE = {
      saved: { label: "Потвърден", cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
      changed: { label: "Променено", cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
      new: { label: "Нов за днес", cls: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
    };

    return (
      <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-people">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={handleBack}><ArrowLeft className="w-4 h-4" /></Button>
          <div className="flex-1">
            <h2 className="font-bold">Хора на обекта днес</h2>
            <p className="text-xs text-muted-foreground">{selectedSite?.name}</p>
          </div>
          <Button size="sm" onClick={() => { setSelectedToAdd([]); setPickerSearch(""); setPickerFilter("all"); setShowAddPeople(true); }}><Plus className="w-4 h-4 mr-1" />{t("technician.add")}</Button>
        </div>

        {/* Stats bar */}
        <div className="rounded-xl border border-border bg-card/50 p-3">
          <p className="text-xs font-semibold text-white mb-1">{todayStr}</p>
          <div className="flex items-center gap-4">
            <div className="text-center"><p className="text-lg font-bold text-emerald-400">{presentCount}</p><p className="text-[9px] text-muted-foreground">На работа</p></div>
            <div className="text-center"><p className="text-lg font-bold">{enrichedRoster.length}</p><p className="text-[9px] text-muted-foreground">В списъка</p></div>
            <div className="text-center"><p className="text-lg font-bold text-cyan-400">{savedRosterState.length}</p><p className="text-[9px] text-muted-foreground">Записани</p></div>
          </div>
        </div>

        {/* === ДНЕВЕН СПИСЪК === */}
        {enrichedRoster.length === 0 ? (
          <p className="text-center py-8 text-muted-foreground text-sm">Няма хора в дневния списък. Добавете от бутон „+ Добави" или от списъка отдолу.</p>
        ) : (
          <div className="space-y-2">
            {enrichedRoster.map(w => {
              const state = getState(w);
              const badge = STATE_BADGE[state];
              const isAdmin = w.status === "SickLeave" || w.status === "Leave" || w.status === "Vacation";
              const isPresent = w.status === "Present" || w.status === "Late";
              const border = isAdmin ? "border-red-500/30 bg-red-500/5" : isPresent ? "border-emerald-500/40" : "border-dashed border-gray-600";

              return (
                <div key={w.worker_id} className={`flex items-center gap-3 p-3 rounded-2xl border-2 bg-card ${border}`}>
                  {w.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${w.avatar_url}`} className="w-10 h-10 rounded-full object-cover" alt="" onError={e => e.target.style.display = "none"} /> : (
                    <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center text-xs font-bold text-primary">{(w.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}</div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <p className="font-medium text-sm truncate">{w.worker_name}</p>
                      {!isAdmin && <Badge variant="outline" className={`text-[8px] ${badge.cls}`}>{badge.label}</Badge>}
                    </div>
                    <p className="text-[10px] text-muted-foreground">{w.position || "Работник"}</p>
                  </div>
                  {isAdmin ? (
                    <Badge className="text-[10px] bg-red-500/20 text-red-400 border-red-500/30">{{ SickLeave: "Болен", Leave: "Отпуск", Vacation: "Отпуск" }[w.status]}</Badge>
                  ) : (
                    <button
                      onClick={() => setEnrichedRoster(prev => prev.map(r => r.worker_id === w.worker_id ? { ...r, status: isPresent ? "" : "Present" } : r))}
                      className={`h-9 px-4 rounded-xl text-xs font-semibold ${isPresent ? "bg-emerald-500 text-white" : "bg-gray-700 text-gray-400 border border-gray-600"}`}
                    >{isPresent ? "На работа" : "Потвърди"}</button>
                  )}
                  {!isAdmin && <Button variant="ghost" size="sm" onClick={() => localRemove(w.worker_id)}><Trash2 className="w-4 h-4 text-red-400" /></Button>}
                </div>
              );
            })}
          </div>
        )}

        {/* === ЕДИНСТВЕН БУТОН ЗАПАЗИ === */}
        {enrichedRoster.length > 0 && (
          <Button
            onClick={handleSave}
            disabled={!hasChanges}
            className={`w-full h-12 rounded-xl text-base ${hasChanges ? "bg-amber-500 hover:bg-amber-600 text-black" : "bg-emerald-600/50 cursor-default"}`}
          >{hasChanges ? "Запази промените" : "Записано"}</Button>
        )}

        {/* === SHORTLIST: Работили преди === */}
        {shortlistFiltered.length > 0 && (
          <div className="mt-6 pt-4 border-t border-border/50 space-y-2">
            <p className="text-xs text-muted-foreground font-semibold">Работили преди на обекта ({shortlistFiltered.length})</p>
            {shortlistFiltered.slice(0, 8).map(w => (
              <div key={w.worker_id} className="flex items-center gap-3 p-2.5 rounded-xl border border-dashed border-border bg-card/30">
                {w.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${w.avatar_url}`} className="w-8 h-8 rounded-full object-cover" alt="" onError={e => e.target.style.display = "none"} /> : (
                  <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center text-[10px] font-bold">{(w.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}</div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">{w.worker_name}</p>
                  <p className="text-[9px] text-muted-foreground">{w.position || "—"} · {w.days_count}д</p>
                </div>
                <Button size="sm" variant="outline" className="h-7 text-[10px]" onClick={() => localAddFromShortlist(w)}>+ Днес</Button>
              </div>
            ))}
          </div>
        )}

        {/* === + ДОБАВИ МОДАЛ (само останалите) === */}
        {showAddPeople && (() => {
          const pickerList = availablePeople.filter(p => !allShownIds.has(p.worker_id));
          const filtered = pickerList.filter(p => {
            if (pickerSearch) {
              const q = pickerSearch.toLowerCase();
              if (!((p.worker_name || "").toLowerCase().includes(q) || (p.position || "").toLowerCase().includes(q))) return false;
            }
            if (pickerFilter && pickerFilter !== "all") {
              if ((p.position || "").toLowerCase() !== pickerFilter.toLowerCase()) return false;
            }
            return true;
          });
          const positions = [...new Set(pickerList.map(p => p.position).filter(Boolean))].sort();

          return (
            <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-end justify-center">
              <div className="w-full max-w-lg bg-card border-t border-border rounded-t-2xl p-4 max-h-[85vh] flex flex-col">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-bold">Добави от Персонал</h3>
                  <Button variant="ghost" size="sm" onClick={() => setShowAddPeople(false)}>✕</Button>
                </div>
                <Input value={pickerSearch} onChange={e => setPickerSearch(e.target.value)} placeholder="Търси..." className="h-11 mb-2" />
                {positions.length > 0 && (
                  <div className="flex gap-1.5 overflow-x-auto pb-2 mb-2">
                    <button onClick={() => setPickerFilter("all")} className={`px-3 py-1.5 rounded-full text-xs whitespace-nowrap border ${!pickerFilter || pickerFilter === "all" ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground"}`}>Всички</button>
                    {positions.map(pos => (
                      <button key={pos} onClick={() => setPickerFilter(pos)} className={`px-3 py-1.5 rounded-full text-xs whitespace-nowrap border ${pickerFilter === pos ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground"}`}>{pos}</button>
                    ))}
                  </div>
                )}
                <div className="flex-1 overflow-y-auto space-y-2">
                  {filtered.length === 0 ? <p className="text-center py-8 text-muted-foreground text-sm">Няма повече служители за добавяне</p> : (
                    filtered.map(p => (
                      <label key={p.worker_id} className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer ${selectedToAdd.includes(p.worker_id) ? "border-primary bg-primary/5" : "border-border"}`}>
                        <Checkbox checked={selectedToAdd.includes(p.worker_id)} onCheckedChange={c => setSelectedToAdd(prev => c ? [...prev, p.worker_id] : prev.filter(id => id !== p.worker_id))} />
                        {p.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${p.avatar_url}`} className="w-10 h-10 rounded-full object-cover" alt="" /> : (
                          <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center text-xs font-bold">{(p.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}</div>
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">{p.worker_name}</p>
                          <p className="text-[10px] text-muted-foreground">{p.position || "—"}</p>
                        </div>
                      </label>
                    ))
                  )}
                </div>
                {selectedToAdd.length > 0 && (
                  <Button onClick={localAddFromPicker} className="w-full h-14 text-lg rounded-2xl mt-3"><Plus className="w-5 h-5 mr-2" />Добави ({selectedToAdd.length})</Button>
                )}
              </div>
            </div>
          );
        })()}
      </div>
    );
  } // end screen === "people"

  // ════════════════════════════════════════════════════════════
  // ROSTER
  // ════════════════════════════════════════════════════════════
  if (screen === "roster") return (
    <div className="p-4 max-w-lg mx-auto space-y-3" data-testid="tech-roster">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => setScreen("object")}><ArrowLeft className="w-4 h-4" /></Button>
        <div className="flex-1">
          <h2 className="font-bold text-base">Стъпка 1: Кой е на обекта?</h2>
          <p className="text-xs text-muted-foreground">{selectedSite?.name} — {new Date().toLocaleDateString("bg-BG", { day: "numeric", month: "long" })}</p>
        </div>
        <Button size="sm" variant="ghost" className="text-xs" onClick={copyYesterday}><Copy className="w-3.5 h-3.5 mr-1" />{t("technician.copyYesterday")}</Button>
      </div>

      {/* Selected workers — compact */}
      {roster.length > 0 && (
        <div className="space-y-1">
          {roster.map(w => (
            <div key={w.worker_id} className="flex items-center justify-between p-2.5 rounded-xl border border-emerald-500/30 bg-emerald-500/5">
              <span className="text-sm font-medium">{w.worker_name}</span>
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => toggleWorker(w)}><Trash2 className="w-3.5 h-3.5 text-red-400" /></Button>
            </div>
          ))}
        </div>
      )}

      {/* Available workers — compact toggle list */}
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{showAll ? t("technician.allEmployees") : t("technician.recentWorkers")} <button onClick={() => setShowAll(!showAll)} className="text-primary ml-1">{showAll ? "↩ Скорошни" : "Виж всички →"}</button></p>
      <div className="space-y-1">
        {allSugg.filter(w => !isInRoster(w.worker_id)).slice(0, 15).map(w => (
          <button key={w.worker_id} onClick={() => toggleWorker(w)} className="w-full flex items-center justify-between p-2.5 rounded-xl border border-border text-left hover:bg-muted/20 text-sm">
            <span>{w.worker_name}</span>
            <Plus className="w-4 h-4 text-muted-foreground" />
          </button>
        ))}
        {allSugg.filter(w => !isInRoster(w.worker_id)).length === 0 && <p className="text-xs text-muted-foreground py-2">{t("technician.noSuggestions")}</p>}
      </div>

      {/* CTA — dominant */}
      <Button onClick={saveRosterAndContinue} disabled={rosterSaving || !roster.length} className="w-full h-14 text-lg rounded-2xl bg-emerald-600 hover:bg-emerald-700" data-testid="save-roster-btn">
        {rosterSaving ? <Loader2 className="w-5 h-5 mr-2 animate-spin" /> : <Check className="w-5 h-5 mr-2" />}
        Запази и продължи ({roster.length})
      </Button>
    </div>
  );

  // ════════════════════════════════════════════════════════════
  // REPORT
  // ════════════════════════════════════════════════════════════
  if (screen === "report") return (
    <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-report">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => setScreen("object")}><ArrowLeft className="w-4 h-4" /></Button>
        <div className="flex-1">
          <h2 className="font-bold text-base">Дневен отчет</h2>
          <p className="text-xs text-muted-foreground">{selectedSite?.name} — {new Date().toLocaleDateString("bg-BG", { day: "numeric", month: "long" })}</p>
        </div>
      </div>

      {/* Mode toggle */}
      <div className="flex gap-2">
        <Button variant={reportMode === "person" ? "default" : "outline"} size="sm" onClick={() => setReportMode("person")} className="flex-1 rounded-xl">{t("technician.byPerson")}</Button>
        <Button variant={reportMode === "group" ? "default" : "outline"} size="sm" onClick={() => setReportMode("group")} className="flex-1 rounded-xl">{t("technician.byGroup")}</Button>
      </div>

      {/* MODE A: Per person — styled cards */}
      {reportMode === "person" && entries.map(e => {
        const dayH = workerDayHours[e.worker_id];
        const dayTotal = dayH ? dayH.total_hours : 0;
        const otherProjects = dayH ? dayH.projects_count : 0;
        const entryHours = e.lines.reduce((s, ln) => s + (parseFloat(ln.hours) || 0), 0);
        const projected = dayTotal + entryHours;

        // Color logic
        const isCritical = projected > 12;
        const isWarning = projected > 8;
        const accentCls = isCritical ? "border-l-red-500" : isWarning ? "border-l-amber-500" : "border-l-slate-600";
        const headerBg = isCritical ? "bg-red-500/8" : isWarning ? "bg-amber-500/8" : "bg-slate-800/60";
        const pillCls = isCritical ? "bg-red-500/20 text-red-400 border-red-500/30" : isWarning ? "bg-amber-500/20 text-amber-400 border-amber-500/30" : "bg-slate-700/50 text-slate-300 border-slate-600/50";

        return (
          <div key={e.id} className={`rounded-2xl border border-border bg-card overflow-hidden border-l-4 ${accentCls}`} style={{ marginTop: "16px" }}>
            {/* Worker header */}
            <div className={`px-4 py-3 ${headerBg} border-b border-border/50 flex items-center gap-3`}>
              <div className="w-9 h-9 rounded-full bg-primary/20 flex items-center justify-center text-[11px] font-bold text-primary flex-shrink-0">
                {(e.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-sm truncate">{e.worker_name}</p>
                {otherProjects > 1 && <p className="text-[9px] text-muted-foreground">{otherProjects} обекта днес</p>}
              </div>
              {/* Hours badge / pill */}
              <div className={`px-2.5 py-1 rounded-lg border text-right ${pillCls}`}>
                <p className="text-[11px] font-mono font-bold leading-tight">
                  {projected > 0 ? `${projected}ч` : "0ч"}
                </p>
                {dayTotal > 0 && entryHours > 0 && (
                  <p className="text-[8px] leading-tight opacity-70">
                    Тук: {entryHours}ч · Други: {dayTotal}ч
                  </p>
                )}
              </div>
            </div>

            {/* Activity lines */}
            <div className="p-4 space-y-4">
              {e.lines.map((ln, li) => (
                <div key={li} className="space-y-2">
                  {/* Activity select — subtle blue accent */}
                  {availableTasks.length > 0 ? (
                    <Select value={ln.smr || "none"} onValueChange={v => setLine(e.id, li, "smr", v === "none" ? "" : v)}>
                      <SelectTrigger className="h-11 border-blue-500/20 focus:border-blue-500/40"><SelectValue placeholder={t("technician.selectSmr")} /></SelectTrigger>
                      <SelectContent><SelectItem value="none" disabled>{t("technician.selectSmr")}</SelectItem>{availableTasks.map((tk, ti) => <SelectItem key={ti} value={tk.smr_type}>{tk.source === "offer_approved" ? "✓ " : tk.source === "extra_draft" ? "⊕ " : ""}{tk.smr_type}{tk.source_label ? ` (${tk.source_label})` : ""}</SelectItem>)}<SelectItem value="__other">{t("technician.otherSmr")}</SelectItem></SelectContent>
                    </Select>
                  ) : <Input value={ln.smr} onChange={ev => setLine(e.id, li, "smr", ev.target.value)} placeholder={t("technician.smrType")} className="h-11 border-blue-500/20 focus:border-blue-500/40" />}
                  {ln.smr === "__other" && <Input value="" onChange={ev => setLine(e.id, li, "smr", ev.target.value)} placeholder={t("technician.smrType")} className="h-11" autoFocus />}

                  {/* Hours + Notes row */}
                  <div className="flex gap-2">
                    <div className="flex-1 relative">
                      <Input type="number" value={ln.hours} onChange={ev => setLine(e.id, li, "hours", ev.target.value)} placeholder="Часове" className="h-11 border-amber-500/20 focus:border-amber-500/40 pl-8" min="0" max="24" step="0.5" />
                      <Clock className="w-3.5 h-3.5 absolute left-2.5 top-3.5 text-amber-500/40" />
                    </div>
                    <div className="flex-1">
                      <Input value={ln.notes} onChange={ev => setLine(e.id, li, "notes", ev.target.value)} placeholder="Бележки" className="h-11 border-slate-600/30" />
                    </div>
                    {e.lines.length > 1 && <Button variant="ghost" size="sm" onClick={() => removeLine(e.id, li)} className="h-11 hover:bg-red-500/10"><Trash2 className="w-4 h-4 text-red-400" /></Button>}
                  </div>
                </div>
              ))}
              {/* Add activity — secondary */}
              <Button variant="outline" size="sm" onClick={() => addLine(e.id)} className="w-full rounded-xl border-dashed border-border/50 text-muted-foreground hover:text-foreground hover:border-primary/30"><Plus className="w-4 h-4 mr-1" />{t("technician.addActivity")}</Button>
            </div>
          </div>
        );
      })}

      {/* MODE B: Group */}
      {reportMode === "group" && (
        <div className="rounded-2xl border border-border bg-card p-4 space-y-3">
          {availableTasks.length > 0 ? (
            <Select value={groupSmr || "none"} onValueChange={v => setGroupSmr(v === "none" ? "" : v)}>
              <SelectTrigger className="h-11"><SelectValue placeholder={t("technician.selectSmr")} /></SelectTrigger>
              <SelectContent><SelectItem value="none" disabled>{t("technician.selectSmr")}</SelectItem>{availableTasks.map((tk, ti) => <SelectItem key={ti} value={tk.smr_type}>{tk.source === "offer_approved" ? "✓ " : tk.source === "extra_draft" ? "⊕ " : ""}{tk.smr_type}</SelectItem>)}</SelectContent>
            </Select>
          ) : <Input value={groupSmr} onChange={e => setGroupSmr(e.target.value)} placeholder={t("technician.smrType")} className="h-11" />}
          <Input type="number" value={groupHours} onChange={e => setGroupHours(e.target.value)} placeholder={t("technician.hours")} className="h-11" />
          <p className="text-xs text-muted-foreground">{t("technician.selectWorkers")}:</p>
          {roster.map(w => (
            <label key={w.worker_id} className="flex items-center gap-3 p-3 rounded-xl border border-border cursor-pointer hover:bg-muted/20">
              <Checkbox checked={groupWorkers.includes(w.worker_id)} onCheckedChange={(checked) => setGroupWorkers(prev => checked ? [...prev, w.worker_id] : prev.filter(id => id !== w.worker_id))} />
              <span>{w.worker_name}</span>
            </label>
          ))}
        </div>
      )}

      <Textarea value={generalNotes} onChange={e => setGeneralNotes(e.target.value)} placeholder={t("technician.generalNotes")} className="min-h-[60px] border-slate-600/30" />
      <Button onClick={() => setScreen("review")} className="w-full h-14 text-lg rounded-2xl bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg"><Eye className="w-5 h-5 mr-2" />{t("technician.reviewReport")}</Button>
    </div>
  );

  // ════════════════════════════════════════════════════════════
  // REVIEW (with overtime breakdown)
  // ════════════════════════════════════════════════════════════
  if (screen === "review") {
    const NORMAL_DAY = 8;
    // Group payload by worker
    const workerMap = {};
    for (const p of payload) {
      if (!workerMap[p.worker_id]) workerMap[p.worker_id] = { name: p.worker_name, lines: [], total: 0 };
      workerMap[p.worker_id].lines.push(p);
      workerMap[p.worker_id].total += p.hours;
    }
    const workers = Object.values(workerMap);
    const totalHours = workers.reduce((s, w) => s + w.total, 0);
    const totalNormal = workers.reduce((s, w) => s + Math.min(w.total, NORMAL_DAY), 0);
    const totalOvertime = workers.reduce((s, w) => s + Math.max(0, w.total - NORMAL_DAY), 0);
    const overtimeCount = workers.filter(w => w.total > NORMAL_DAY).length;

    return (
      <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-review">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => setScreen("report")} data-testid="review-back-btn"><ArrowLeft className="w-4 h-4" /></Button>
          <h2 className="font-bold">{t("technician.step3Review")}</h2>
        </div>

        {/* Overtime Warning */}
        {overtimeCount > 0 && (
          <div className="rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 flex items-start gap-3" data-testid="overtime-warning">
            <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-sm text-amber-300">{t("technician.overtimeWarning", { count: overtimeCount })}</p>
              <p className="text-xs text-amber-400/70 mt-0.5">{t("technician.overtimeNote")}</p>
            </div>
          </div>
        )}

        {/* Day Summary */}
        <div className="rounded-2xl border border-border bg-card p-4" data-testid="day-summary">
          <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wider mb-3">{t("technician.daySummary")}</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-muted/30 p-3 text-center">
              <p className="text-2xl font-bold">{workers.length}</p>
              <p className="text-[10px] text-muted-foreground">{t("technician.totalPeople")}</p>
            </div>
            <div className="rounded-xl bg-muted/30 p-3 text-center">
              <p className="text-2xl font-bold font-mono">{totalHours}<span className="text-sm text-muted-foreground">ч</span></p>
              <p className="text-[10px] text-muted-foreground">{t("technician.totalHours")}</p>
            </div>
            <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/20 p-3 text-center">
              <p className="text-2xl font-bold font-mono text-emerald-400">{totalNormal}<span className="text-sm text-emerald-400/60">ч</span></p>
              <p className="text-[10px] text-emerald-400/70">{t("technician.normalHours")}</p>
            </div>
            <div className={`rounded-xl p-3 text-center ${totalOvertime > 0 ? "bg-amber-500/10 border border-amber-500/20" : "bg-muted/30"}`}>
              <p className={`text-2xl font-bold font-mono ${totalOvertime > 0 ? "text-amber-400" : "text-muted-foreground"}`}>{totalOvertime}<span className={`text-sm ${totalOvertime > 0 ? "text-amber-400/60" : "text-muted-foreground/60"}`}>ч</span></p>
              <p className={`text-[10px] ${totalOvertime > 0 ? "text-amber-400/70" : "text-muted-foreground"}`}>{t("technician.overtimeHours")}</p>
            </div>
          </div>
          {overtimeCount > 0 && (
            <p className="text-[10px] text-amber-400/60 text-center mt-2">{overtimeCount} {t("technician.withOvertime")}</p>
          )}
        </div>

        {/* Per-worker cards */}
        {workers.map((w, wi) => {
          const normal = Math.min(w.total, NORMAL_DAY);
          const overtime = Math.max(0, w.total - NORMAL_DAY);
          return (
            <div key={wi} className="rounded-2xl border border-border bg-card overflow-hidden" data-testid={`review-worker-${wi}`}>
              <div className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-xs font-bold text-primary flex-shrink-0">
                    {w.name.split(" ").map(n => n[0]).join("").slice(0, 2)}
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-sm truncate">{w.name}</p>
                    <p className="text-[10px] text-muted-foreground">{w.lines.length} {t("technician.workerActivities")}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className="font-mono font-bold text-sm">{w.total}ч</span>
                  {overtime > 0 && <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-[10px]">{t("technician.overtime")}</Badge>}
                </div>
              </div>
              {/* Hours bar */}
              <div className="px-4 pb-2 flex gap-3 text-[10px]">
                <span className="text-emerald-400">{t("technician.normalHours")}: {normal}ч</span>
                {overtime > 0 && <span className="text-amber-400">{t("technician.overtimeHours")}: +{overtime}ч</span>}
              </div>
              {/* Activity lines */}
              <div className="border-t border-border/50">
                {w.lines.map((ln, li) => (
                  <div key={li} className="px-4 py-2 flex items-center justify-between text-sm border-b border-border/30 last:border-0">
                    <div className="min-w-0 flex-1">
                      <span className="text-foreground">{ln.smr_type}</span>
                      {ln.notes && <p className="text-[10px] text-muted-foreground truncate">{ln.notes}</p>}
                    </div>
                    <span className={`font-mono text-xs flex-shrink-0 ml-2 ${ln.hours > NORMAL_DAY ? "text-amber-400" : ""}`}>{ln.hours}ч</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}

        {/* General notes */}
        {generalNotes && (
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-xs text-muted-foreground mb-1">{t("technician.generalNotes")}</p>
            <p className="text-sm">{generalNotes}</p>
          </div>
        )}

        <div className="flex gap-3">
          <Button variant="outline" onClick={() => setScreen("report")} className="flex-1 h-14 rounded-2xl" data-testid="review-edit-btn"><Pencil className="w-4 h-4 mr-2" />{t("technician.back")}</Button>
          <Button onClick={handleSubmit} disabled={submitting} className="flex-1 h-14 rounded-2xl text-lg" data-testid="review-submit-btn">
            {submitting ? <Loader2 className="w-5 h-5 mr-2 animate-spin" /> : <Send className="w-5 h-5 mr-2" />}{t("technician.submit")}
          </Button>
        </div>
      </div>
    );
  }

  return null;
}
