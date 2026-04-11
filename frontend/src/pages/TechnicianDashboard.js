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
  const [availablePeople, setAvailablePeople] = useState([]);
  const [showAddPeople, setShowAddPeople] = useState(false);
  const [selectedToAdd, setSelectedToAdd] = useState([]);

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
      const [tasksRes, detailRes, draftsRes] = await Promise.all([
        API.get(`/technician/site/${site.project_id}/tasks`),
        API.get(`/technician/site/${site.project_id}/detail`),
        API.get(`/technician/site/${site.project_id}/my-drafts`),
      ]);
      setAvailableTasks(tasksRes.data.tasks || []);
      setSiteDetail(detailRes.data);
      setExistingDrafts(draftsRes.data.items || []);
    } catch { setAvailableTasks([]); setSiteDetail(null); setExistingDrafts([]); }
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
      // Pre-fill entries from roster
      setEntries(roster.map(w => ({ id: Date.now() + Math.random(), worker_id: w.worker_id, worker_name: w.worker_name, lines: [{ smr: "", hours: "8", notes: "" }] })));
      setGroupWorkers([]);
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
  const openPeople = async () => {
    setScreen("people");
    setShowAddPeople(false);
    try {
      const [enrichedRes, availRes] = await Promise.all([
        API.get(`/technician/site/${selectedSite.project_id}/roster/enriched`),
        API.get(`/technician/site/${selectedSite.project_id}/roster/available`),
      ]);
      setEnrichedRoster(enrichedRes.data.workers || []);
      setAvailablePeople(availRes.data.available || []);
    } catch { setEnrichedRoster([]); setAvailablePeople([]); }
  };

  const removeWorker = async (workerId) => {
    try {
      await API.post(`/technician/site/${selectedSite.project_id}/roster/remove-worker`, { worker_id: workerId });
      setEnrichedRoster(prev => prev.filter(w => w.worker_id !== workerId));
      toast.success(t("technician.workerRemoved"));
      // Refresh available
      const avRes = await API.get(`/technician/site/${selectedSite.project_id}/roster/available`);
      setAvailablePeople(avRes.data.available || []);
    } catch (err) { toast.error(err.response?.data?.detail || "Error"); }
  };

  const addSelectedWorkers = async () => {
    if (!selectedToAdd.length) return;
    const toAdd = selectedToAdd.map(wid => {
      const p = availablePeople.find(a => a.worker_id === wid);
      return { worker_id: wid, worker_name: p?.worker_name || "" };
    });
    try {
      await API.post(`/technician/site/${selectedSite.project_id}/roster/add-workers`, { workers: toAdd });
      toast.success(`${toAdd.length} ${t("technician.workersAdded")}`);
      setSelectedToAdd([]);
      setShowAddPeople(false);
      openPeople();
    } catch (err) { toast.error(err.response?.data?.detail || "Error"); }
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
      </div>
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">{t("technician.mySites")}</h2>
      {sites.length === 0 ? <p className="text-center py-8 text-muted-foreground">{t("technician.noSites")}</p> : sites.map(s => (
        <button key={s.project_id} onClick={() => openObject(s)} className="w-full rounded-2xl border border-border bg-card p-5 text-left hover:border-primary/40 active:scale-[0.98] transition-all" data-testid={`site-${s.project_id}`}>
          <div className="flex items-start justify-between mb-2">
            <h3 className="font-bold text-base">{s.name}</h3>
            {s.has_report_today ? <Badge className="bg-emerald-500/20 text-emerald-400 text-[10px]"><Check className="w-3 h-3 mr-1" />{t("technician.reported")}</Badge> : <Badge className="bg-amber-500/20 text-amber-400 text-[10px]"><AlertTriangle className="w-3 h-3 mr-1" />{t("technician.noReport")}</Badge>}
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
  // OBJECT SCREEN
  // ════════════════════════════════════════════════════════════
  if (screen === "object" && selectedSite) {
    const d = siteDetail;
    const co = d?.contact_owner || {};
    const cr = d?.contact_responsible || {};
    const od = d?.object_details || {};
    const ct = d?.counters || {};
    const addr = d?.address || {};
    const fullAddr = d?.address_text || [addr.city && `гр. ${addr.city}`, addr.district, addr.street, addr.block && `бл. ${addr.block}`, addr.floor && `ет. ${addr.floor}`].filter(Boolean).join(", ");

    return (
      <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-object">
        <Button variant="ghost" size="sm" onClick={() => { setScreen("myDay"); setSelectedSite(null); }}><ArrowLeft className="w-4 h-4 mr-1" /> {t("technician.back")}</Button>

        {/* Object Info Card */}
        <div className="rounded-2xl border border-border bg-card p-5 space-y-3">
          <h2 className="text-lg font-bold">{selectedSite.name}</h2>
          {fullAddr && <p className="text-sm text-muted-foreground flex items-start gap-2"><MapPin className="w-4 h-4 mt-0.5 flex-shrink-0 text-blue-400" />{fullAddr}</p>}
          {od.access_notes && <p className="text-xs text-muted-foreground bg-muted/20 rounded-lg p-2">{od.access_notes}</p>}

          {/* Contacts */}
          <div className="flex gap-3">
            {(co.name || co.phone) && (
              <div className="flex-1 text-xs">
                <p className="text-muted-foreground mb-0.5">{t("technician.owner")}</p>
                <p className="font-medium">{co.name}</p>
                {co.phone && <a href={`tel:${co.phone}`} className="flex items-center gap-1 text-primary hover:underline mt-0.5"><Phone className="w-3 h-3" />{co.phone}</a>}
              </div>
            )}
            {(cr.name || cr.phone) && (
              <div className="flex-1 text-xs">
                <p className="text-muted-foreground mb-0.5">{t("technician.responsible")}</p>
                <p className="font-medium">{cr.name}</p>
                {cr.phone && <a href={`tel:${cr.phone}`} className="flex items-center gap-1 text-primary hover:underline mt-0.5"><Phone className="w-3 h-3" />{cr.phone}</a>}
              </div>
            )}
          </div>

          {/* Object badges */}
          <div className="flex gap-2 flex-wrap">
            {d?.object_type && <Badge variant="outline" className="text-[10px]">{d.object_type}</Badge>}
            {od.is_inhabited && <Badge variant="outline" className="text-[10px] text-amber-400">Обитаем</Badge>}
            {od.parking_available && <Badge variant="outline" className="text-[10px]">Паркинг</Badge>}
            {od.elevator_available && <Badge variant="outline" className="text-[10px]">Асансьор</Badge>}
          </div>
        </div>

        {/* Guidance Photos */}
        {d?.guidance_photos?.length > 0 && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {d.guidance_photos.map(p => <img key={p.id} src={`${process.env.REACT_APP_BACKEND_URL}${p.url}`} alt="" className="w-20 h-20 rounded-xl object-cover border border-border flex-shrink-0" />)}
          </div>
        )}

        {/* Counters */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-border bg-card p-3 text-center">
            <Users className="w-5 h-5 mx-auto mb-1 text-cyan-400" />
            <p className="text-xl font-bold">{ct.roster_count || 0}</p>
            <p className="text-[10px] text-muted-foreground">{t("technician.onSite")}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-3 text-center">
            <FileText className="w-5 h-5 mx-auto mb-1 text-emerald-400" />
            <p className="text-xl font-bold">{ct.reported_workers || 0}</p>
            <p className="text-[10px] text-muted-foreground">{t("technician.reported")}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-3 text-center">
            <Clock className="w-5 h-5 mx-auto mb-1 text-primary" />
            <p className="text-xl font-bold">{ct.reported_hours || 0}</p>
            <p className="text-[10px] text-muted-foreground">{t("technician.hoursToday")}</p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="grid grid-cols-2 gap-3">
          <Button onClick={openRoster} className="h-20 rounded-2xl flex-col text-sm font-semibold"><FileText className="w-6 h-6 mb-1" />{t("technician.dailyReport")}</Button>
          <Button variant="outline" onClick={openPeople} className="h-20 rounded-2xl flex-col text-sm"><Users className="w-6 h-6 mb-1 text-cyan-400" />{t("technician.people")}</Button>
          <Button variant="outline" onClick={() => { setQSmr(""); setQuickScreen("quickSmr"); }} className="h-20 rounded-2xl flex-col text-sm"><AlertTriangle className="w-6 h-6 mb-1 text-orange-400" />{t("technician.newSMR")}</Button>
          <Button variant="outline" onClick={() => setQuickScreen("photoInvoice")} className="h-20 rounded-2xl flex-col text-sm"><Camera className="w-6 h-6 mb-1 text-blue-400" />{t("technician.photoInvoice")}</Button>
        </div>

        {/* Existing Drafts */}
        {existingDrafts.length > 0 && (
          <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
            <p className="text-xs font-semibold text-amber-400 mb-2">{t("technician.existingDrafts")} ({existingDrafts.length})</p>
            {existingDrafts.slice(0, 5).map(dd => <p key={dd.id} className="text-xs text-muted-foreground">{dd.worker_name} — {dd.smr_type} — {dd.hours}ч</p>)}
          </div>
        )}
      </div>
    );
  }

  // ════════════════════════════════════════════════════════════
  // PEOPLE MANAGEMENT
  // ════════════════════════════════════════════════════════════
  if (screen === "people") return (
    <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-people">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => setScreen("object")}><ArrowLeft className="w-4 h-4" /></Button>
        <div className="flex-1"><h2 className="font-bold">{t("technician.people")}</h2><p className="text-xs text-muted-foreground">{selectedSite?.name} — {t("technician.todayRoster")}</p></div>
        <Button size="sm" onClick={() => { setSelectedToAdd([]); setShowAddPeople(true); }}><Plus className="w-4 h-4 mr-1" />{t("technician.add")}</Button>
      </div>

      {/* Current roster */}
      {enrichedRoster.length === 0 ? (
        <p className="text-center py-8 text-muted-foreground text-sm">{t("technician.noPeopleYet")}</p>
      ) : enrichedRoster.map(w => (
        <div key={w.worker_id} className="flex items-center gap-3 p-3 rounded-2xl border border-border bg-card">
          {w.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${w.avatar_url}`} className="w-11 h-11 rounded-full object-cover" alt="" /> : (
            <div className="w-11 h-11 rounded-full bg-primary/20 flex items-center justify-center text-sm font-bold text-primary">{(w.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}</div>
          )}
          <div className="flex-1 min-w-0">
            <p className="font-medium text-sm truncate">{w.worker_name}</p>
            <p className="text-[10px] text-muted-foreground">{w.position || "Работник"}</p>
            {w.total_hours > 0 && <p className="text-[10px] font-mono">{w.normal_hours}ч{w.has_overtime && <span className="text-orange-400 ml-1">+{w.overtime_hours}ч OT</span>}</p>}
          </div>
          {w.has_overtime && <Badge className="bg-orange-500/20 text-orange-400 text-[9px]">{t("technician.overtime")}</Badge>}
          <Button variant="ghost" size="sm" onClick={() => removeWorker(w.worker_id)}><Trash2 className="w-4 h-4 text-red-400" /></Button>
        </div>
      ))}

      {/* Add People Modal */}
      {showAddPeople && (
        <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-end justify-center">
          <div className="w-full max-w-lg bg-card border-t border-border rounded-t-2xl p-4 max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-bold">{t("technician.addPeople")}</h3>
              <Button variant="ghost" size="sm" onClick={() => setShowAddPeople(false)}>✕</Button>
            </div>
            {availablePeople.length === 0 ? <p className="text-center py-4 text-muted-foreground text-sm">{t("technician.allOnSite")}</p> : (
              <div className="space-y-2">
                {availablePeople.map(p => (
                  <label key={p.worker_id} className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer ${selectedToAdd.includes(p.worker_id) ? "border-primary bg-primary/5" : "border-border"}`}>
                    <Checkbox checked={selectedToAdd.includes(p.worker_id)} onCheckedChange={c => setSelectedToAdd(prev => c ? [...prev, p.worker_id] : prev.filter(id => id !== p.worker_id))} />
                    {p.avatar_url ? <img src={`${process.env.REACT_APP_BACKEND_URL}${p.avatar_url}`} className="w-9 h-9 rounded-full object-cover" alt="" /> : (
                      <div className="w-9 h-9 rounded-full bg-muted flex items-center justify-center text-xs font-bold">{(p.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}</div>
                    )}
                    <div className="flex-1"><p className="text-sm font-medium">{p.worker_name}</p><p className="text-[10px] text-muted-foreground">{p.position || "—"}</p></div>
                  </label>
                ))}
              </div>
            )}
            {selectedToAdd.length > 0 && (
              <Button onClick={addSelectedWorkers} className="w-full h-14 text-lg rounded-2xl mt-3"><Plus className="w-5 h-5 mr-2" />{t("technician.addSelected")} ({selectedToAdd.length})</Button>
            )}
          </div>
        </div>
      )}
    </div>
  );

  // ════════════════════════════════════════════════════════════
  // ROSTER
  // ════════════════════════════════════════════════════════════
  if (screen === "roster") return (
    <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-roster">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => setScreen("object")}><ArrowLeft className="w-4 h-4" /></Button>
        <div className="flex-1"><h2 className="font-bold">{t("technician.step1Roster")}</h2><p className="text-xs text-muted-foreground">{selectedSite?.name}</p></div>
        <Button size="sm" variant="outline" onClick={copyYesterday}><Copy className="w-3.5 h-3.5 mr-1" />{t("technician.copyYesterday")}</Button>
      </div>
      {roster.length > 0 && <div className="space-y-1"><p className="text-xs text-muted-foreground">{t("technician.selected")} ({roster.length})</p>{roster.map(w => <div key={w.worker_id} className="flex items-center justify-between p-3 rounded-xl border border-primary/30 bg-primary/5"><span className="font-medium">{w.worker_name}</span><Button variant="ghost" size="sm" onClick={() => toggleWorker(w)}><Trash2 className="w-4 h-4 text-red-400" /></Button></div>)}</div>}
      <div className="flex items-center justify-between"><p className="text-xs text-muted-foreground">{showAll ? t("technician.allEmployees") : t("technician.recentWorkers")}</p><Button variant="ghost" size="sm" className="text-xs" onClick={() => setShowAll(!showAll)}><UserPlus className="w-3 h-3 mr-1" />{showAll ? t("technician.showRecent") : t("technician.showAll")}</Button></div>
      {allSugg.length === 0 ? <p className="text-xs text-muted-foreground py-2">{t("technician.noSuggestions")}</p> : allSugg.map(w => (
        <button key={w.worker_id} onClick={() => toggleWorker(w)} className={`w-full flex items-center justify-between p-3 rounded-xl border text-left ${isInRoster(w.worker_id) ? "border-primary/30 bg-primary/5" : "border-border hover:bg-muted/20"}`}>
          <span>{w.worker_name}</span>
          <div className="flex items-center gap-2">{w.source === "recent" && <Badge variant="outline" className="text-[9px]">{t("technician.recent")}</Badge>}{isInRoster(w.worker_id) && <Check className="w-4 h-4 text-primary" />}</div>
        </button>
      ))}
      <Button onClick={saveRosterAndContinue} disabled={rosterSaving || !roster.length} className="w-full h-14 text-lg rounded-2xl" data-testid="save-roster-btn">
        {rosterSaving ? <Loader2 className="w-5 h-5 mr-2 animate-spin" /> : <Users className="w-5 h-5 mr-2" />}{t("technician.saveAndContinue")} ({roster.length})
      </Button>
    </div>
  );

  // ════════════════════════════════════════════════════════════
  // REPORT
  // ════════════════════════════════════════════════════════════
  if (screen === "report") return (
    <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-report">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => setScreen("roster")}><ArrowLeft className="w-4 h-4" /></Button>
        <div className="flex-1"><h2 className="font-bold">{t("technician.step2Report")}</h2><p className="text-xs text-muted-foreground">{selectedSite?.name}</p></div>
      </div>
      {/* Mode toggle */}
      <div className="flex gap-2">
        <Button variant={reportMode === "person" ? "default" : "outline"} size="sm" onClick={() => setReportMode("person")} className="flex-1 rounded-xl">{t("technician.byPerson")}</Button>
        <Button variant={reportMode === "group" ? "default" : "outline"} size="sm" onClick={() => setReportMode("group")} className="flex-1 rounded-xl">{t("technician.byGroup")}</Button>
      </div>

      {/* MODE A: Per person */}
      {reportMode === "person" && entries.map(e => (
        <div key={e.id} className="rounded-2xl border border-border bg-card p-4 space-y-3">
          <p className="font-semibold text-sm">{e.worker_name}</p>
          {e.lines.map((ln, li) => (
            <div key={li} className="space-y-2 pl-3 border-l-2 border-primary/20">
              {availableTasks.length > 0 ? (
                <Select value={ln.smr || "none"} onValueChange={v => setLine(e.id, li, "smr", v === "none" ? "" : v)}>
                  <SelectTrigger className="h-11"><SelectValue placeholder={t("technician.selectSmr")} /></SelectTrigger>
                  <SelectContent><SelectItem value="none" disabled>{t("technician.selectSmr")}</SelectItem>{availableTasks.map((tk, ti) => <SelectItem key={ti} value={tk.smr_type}>{tk.smr_type}</SelectItem>)}<SelectItem value="__other">{t("technician.otherSmr")}</SelectItem></SelectContent>
                </Select>
              ) : <Input value={ln.smr} onChange={ev => setLine(e.id, li, "smr", ev.target.value)} placeholder={t("technician.smrType")} className="h-11" />}
              {ln.smr === "__other" && <Input value="" onChange={ev => setLine(e.id, li, "smr", ev.target.value)} placeholder={t("technician.smrType")} className="h-11" autoFocus />}
              <div className="flex gap-2">
                <Input type="number" value={ln.hours} onChange={ev => setLine(e.id, li, "hours", ev.target.value)} placeholder={t("technician.hours")} className="h-11 flex-1" min="0" max="24" step="0.5" />
                <Input value={ln.notes} onChange={ev => setLine(e.id, li, "notes", ev.target.value)} placeholder={t("technician.notes")} className="h-11 flex-1" />
                {e.lines.length > 1 && <Button variant="ghost" size="sm" onClick={() => removeLine(e.id, li)} className="h-11"><Trash2 className="w-4 h-4 text-red-400" /></Button>}
              </div>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={() => addLine(e.id)} className="w-full rounded-xl"><Plus className="w-4 h-4 mr-1" />{t("technician.addActivity")}</Button>
        </div>
      ))}

      {/* MODE B: Group */}
      {reportMode === "group" && (
        <div className="rounded-2xl border border-border bg-card p-4 space-y-3">
          {availableTasks.length > 0 ? (
            <Select value={groupSmr || "none"} onValueChange={v => setGroupSmr(v === "none" ? "" : v)}>
              <SelectTrigger className="h-11"><SelectValue placeholder={t("technician.selectSmr")} /></SelectTrigger>
              <SelectContent><SelectItem value="none" disabled>{t("technician.selectSmr")}</SelectItem>{availableTasks.map((tk, ti) => <SelectItem key={ti} value={tk.smr_type}>{tk.smr_type}</SelectItem>)}</SelectContent>
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

      <Textarea value={generalNotes} onChange={e => setGeneralNotes(e.target.value)} placeholder={t("technician.generalNotes")} className="min-h-[60px]" />
      <Button onClick={() => setScreen("review")} className="w-full h-14 text-lg rounded-2xl"><Eye className="w-5 h-5 mr-2" />{t("technician.reviewReport")}</Button>
    </div>
  );

  // ════════════════════════════════════════════════════════════
  // REVIEW
  // ════════════════════════════════════════════════════════════
  if (screen === "review") return (
    <div className="p-4 max-w-lg mx-auto space-y-4" data-testid="tech-review">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => setScreen("report")}><ArrowLeft className="w-4 h-4" /></Button>
        <h2 className="font-bold">{t("technician.step3Review")}</h2>
      </div>
      <div className="rounded-2xl border border-border bg-card p-4 space-y-2">
        <p className="text-xs text-muted-foreground">{selectedSite?.name} | {payload.length} {t("technician.entries")}</p>
        {payload.map((p, i) => (
          <div key={i} className="flex items-center justify-between text-sm py-1 border-b border-border/50 last:border-0">
            <span>{p.worker_name}</span>
            <span className="font-mono">{p.smr_type} — {p.hours}ч</span>
          </div>
        ))}
        <div className="flex justify-between font-bold pt-2 border-t border-border">
          <span>{t("technician.totalHours")}</span>
          <span className="font-mono">{payload.reduce((s, p) => s + p.hours, 0)}ч</span>
        </div>
      </div>
      <div className="flex gap-3">
        <Button variant="outline" onClick={() => setScreen("report")} className="flex-1 h-14 rounded-2xl">{t("technician.back")}</Button>
        <Button onClick={handleSubmit} disabled={submitting} className="flex-1 h-14 rounded-2xl text-lg">
          {submitting ? <Loader2 className="w-5 h-5 mr-2 animate-spin" /> : <Send className="w-5 h-5 mr-2" />}{t("technician.submit")}
        </Button>
      </div>
    </div>
  );

  return null;
}
