import { useEffect, useState, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Loader2, Plus, Trash2, Check, Users, Hammer, Save,
} from "lucide-react";

export default function ObjectDailyReportTab({ projectId }) {
  const [mode, setMode] = useState("by-person"); // by-person | by-smr
  const [date, setDate] = useState(new Date().toISOString().split("T")[0]);
  const [employees, setEmployees] = useState([]);
  const [smrList, setSmrList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // By-person rows: [{ employee_id, entries: [{ smr_id, hours, desc, note }] }]
  const [personRows, setPersonRows] = useState([]);
  // By-smr rows: [{ smr_id, smr_name, people: [{ employee_id, hours, note }] }]
  const [smrRows, setSmrRows] = useState([]);

  // Existing data
  const [existing, setExisting] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [empRes, smrRes, existRes] = await Promise.all([
        API.get("/employees"),
        API.get(`/daily-reports/available-smr/${projectId}`),
        API.get(`/daily-reports/project-entries/${projectId}?date=${date}`),
      ]);
      setEmployees(empRes.data);
      setSmrList(smrRes.data.smr || []);
      setExisting(existRes.data);

      // Populate from existing
      if (existRes.data.by_employee?.length > 0) {
        setPersonRows(existRes.data.by_employee.map(e => ({
          employee_id: e.employee_id,
          entries: e.entries.map(en => ({
            smr_id: en.smr_id || "", hours: en.hours_worked, desc: en.work_description, note: en.note || "",
          })),
        })));
        // Also populate smr view
        setSmrRows((existRes.data.by_smr || []).map(s => ({
          smr_id: s.smr_id || "", smr_name: s.work_description || "",
          people: s.employees.map(p => ({ employee_id: p.employee_id, hours: p.hours_worked, note: p.note || "" })),
        })));
      }
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [projectId, date]);

  useEffect(() => { setLoading(true); fetchData(); }, [fetchData]);

  // ── By Person helpers ──
  const addPersonRow = () => setPersonRows([...personRows, { employee_id: "", entries: [{ smr_id: "", hours: 0, desc: "", note: "" }] }]);
  const removePersonRow = (i) => setPersonRows(personRows.filter((_, idx) => idx !== i));
  const updatePerson = (i, field, val) => { const r = [...personRows]; r[i] = { ...r[i], [field]: val }; setPersonRows(r); };
  const addPersonEntry = (i) => { const r = [...personRows]; r[i].entries = [...r[i].entries, { smr_id: "", hours: 0, desc: "", note: "" }]; setPersonRows(r); };
  const removePersonEntry = (pi, ei) => { const r = [...personRows]; r[pi].entries = r[pi].entries.filter((_, idx) => idx !== ei); setPersonRows(r); };
  const updatePersonEntry = (pi, ei, f, v) => { const r = [...personRows]; r[pi].entries = [...r[pi].entries]; r[pi].entries[ei] = { ...r[pi].entries[ei], [f]: v }; setPersonRows(r); };

  // ── By SMR helpers ──
  const addSmrRow = () => setSmrRows([...smrRows, { smr_id: "", smr_name: "", people: [{ employee_id: "", hours: 0, note: "" }] }]);
  const removeSmrRow = (i) => setSmrRows(smrRows.filter((_, idx) => idx !== i));
  const updateSmr = (i, f, v) => { const r = [...smrRows]; r[i] = { ...r[i], [f]: v }; setSmrRows(r); };
  const addSmrPerson = (i) => { const r = [...smrRows]; r[i].people = [...r[i].people, { employee_id: "", hours: 0, note: "" }]; setSmrRows(r); };
  const removeSmrPerson = (si, pi) => { const r = [...smrRows]; r[si].people = r[si].people.filter((_, idx) => idx !== pi); setSmrRows(r); };
  const updateSmrPerson = (si, pi, f, v) => { const r = [...smrRows]; r[si].people = [...r[si].people]; r[si].people[pi] = { ...r[si].people[pi], [f]: v }; setSmrRows(r); };

  // ── Save ──
  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      let entries = [];
      if (mode === "by-person") {
        for (const pr of personRows) {
          if (!pr.employee_id) continue;
          for (const e of pr.entries) {
            if (e.hours <= 0 && !e.desc) continue;
            entries.push({ employee_id: pr.employee_id, smr_id: e.smr_id || null, work_description: e.desc, hours_worked: parseFloat(e.hours) || 0, note: e.note });
          }
        }
      } else {
        for (const sr of smrRows) {
          for (const p of sr.people) {
            if (!p.employee_id || p.hours <= 0) continue;
            entries.push({ employee_id: p.employee_id, smr_id: sr.smr_id || null, work_description: sr.smr_name || "", hours_worked: parseFloat(p.hours) || 0, note: p.note });
          }
        }
      }

      await API.post("/daily-reports/batch-save", { project_id: projectId, report_date: date, entries });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  const empName = (id) => { const e = employees.find(x => x.id === id); return e ? `${e.first_name || ""} ${e.last_name || ""}`.trim() : ""; };
  const smrName = (id) => smrList.find(s => s.id === id)?.name || "";

  if (loading) return <div className="p-4 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></div>;

  return (
    <div className="space-y-4" data-testid="daily-report-tab">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Input type="date" value={date} onChange={e => setDate(e.target.value)} className="w-40 bg-card h-8 text-sm" />
          <div className="flex rounded-lg border border-border overflow-hidden" data-testid="mode-toggle">
            <button onClick={() => setMode("by-person")} className={`px-3 py-1.5 text-xs flex items-center gap-1 transition-colors ${mode === "by-person" ? "bg-primary text-primary-foreground" : "bg-card text-muted-foreground"}`}>
              <Users className="w-3 h-3" /> По хора
            </button>
            <button onClick={() => setMode("by-smr")} className={`px-3 py-1.5 text-xs flex items-center gap-1 border-l border-border transition-colors ${mode === "by-smr" ? "bg-primary text-primary-foreground" : "bg-card text-muted-foreground"}`}>
              <Hammer className="w-3 h-3" /> По СМР
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {saved && <Badge variant="outline" className="text-[10px] bg-emerald-500/15 text-emerald-400">Запазено!</Badge>}
          <Button size="sm" onClick={handleSave} disabled={saving} data-testid="save-daily-btn">
            {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />} Запази
          </Button>
        </div>
      </div>

      {/* ═══ BY PERSON ═══ */}
      {mode === "by-person" && (
        <div className="space-y-3">
          {personRows.map((pr, pi) => (
            <div key={pi} className="rounded-lg border border-border bg-card p-3" data-testid={`person-row-${pi}`}>
              <div className="flex items-center gap-2 mb-2">
                <Select value={pr.employee_id || ""} onValueChange={v => updatePerson(pi, "employee_id", v)}>
                  <SelectTrigger className="bg-background text-sm h-8 flex-1"><SelectValue placeholder="Служител" /></SelectTrigger>
                  <SelectContent>{employees.map(e => <SelectItem key={e.id} value={e.id}>{e.first_name} {e.last_name}</SelectItem>)}</SelectContent>
                </Select>
                <Button size="sm" variant="outline" className="h-8 text-[10px]" onClick={() => addPersonEntry(pi)}><Plus className="w-3 h-3 mr-0.5" /> СМР</Button>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-destructive" onClick={() => removePersonRow(pi)}><Trash2 className="w-3.5 h-3.5" /></Button>
              </div>
              {pr.entries.map((en, ei) => (
                <div key={ei} className="flex items-center gap-2 ml-4 mb-1">
                  <Select value={en.smr_id || "none"} onValueChange={v => updatePersonEntry(pi, ei, "smr_id", v === "none" ? "" : v)}>
                    <SelectTrigger className="bg-background text-xs h-7 flex-1"><SelectValue placeholder="СМР" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">— общо —</SelectItem>
                      {smrList.map(s => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Input type="number" min="0" max="24" step="0.5" value={en.hours} onChange={e => updatePersonEntry(pi, ei, "hours", e.target.value)} className="w-14 bg-background h-7 text-xs font-mono" placeholder="ч" />
                  <Input value={en.desc} onChange={e => updatePersonEntry(pi, ei, "desc", e.target.value)} placeholder="Описание" className="w-32 bg-background h-7 text-xs" />
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive" onClick={() => removePersonEntry(pi, ei)}><Trash2 className="w-3 h-3" /></Button>
                </div>
              ))}
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addPersonRow}><Plus className="w-3 h-3 mr-1" /> Добави човек</Button>
        </div>
      )}

      {/* ═══ BY SMR ═══ */}
      {mode === "by-smr" && (
        <div className="space-y-3">
          {smrRows.map((sr, si) => (
            <div key={si} className="rounded-lg border border-border bg-card p-3" data-testid={`smr-row-${si}`}>
              <div className="flex items-center gap-2 mb-2">
                <Select value={sr.smr_id || "none"} onValueChange={v => { updateSmr(si, "smr_id", v === "none" ? "" : v); updateSmr(si, "smr_name", smrName(v)); }}>
                  <SelectTrigger className="bg-background text-sm h-8 flex-1"><SelectValue placeholder="СМР" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">— общо —</SelectItem>
                    {smrList.map(s => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button size="sm" variant="outline" className="h-8 text-[10px]" onClick={() => addSmrPerson(si)}><Plus className="w-3 h-3 mr-0.5" /> Човек</Button>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-destructive" onClick={() => removeSmrRow(si)}><Trash2 className="w-3.5 h-3.5" /></Button>
              </div>
              {sr.people.map((p, pi) => (
                <div key={pi} className="flex items-center gap-2 ml-4 mb-1">
                  <Select value={p.employee_id || ""} onValueChange={v => updateSmrPerson(si, pi, "employee_id", v)}>
                    <SelectTrigger className="bg-background text-xs h-7 flex-1"><SelectValue placeholder="Служител" /></SelectTrigger>
                    <SelectContent>{employees.map(e => <SelectItem key={e.id} value={e.id}>{e.first_name} {e.last_name}</SelectItem>)}</SelectContent>
                  </Select>
                  <Input type="number" min="0" max="24" step="0.5" value={p.hours} onChange={e => updateSmrPerson(si, pi, "hours", e.target.value)} className="w-14 bg-background h-7 text-xs font-mono" placeholder="ч" />
                  <Input value={p.note} onChange={e => updateSmrPerson(si, pi, "note", e.target.value)} placeholder="Бележка" className="w-32 bg-background h-7 text-xs" />
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive" onClick={() => removeSmrPerson(si, pi)}><Trash2 className="w-3 h-3" /></Button>
                </div>
              ))}
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addSmrRow}><Plus className="w-3 h-3 mr-1" /> Добави СМР</Button>
        </div>
      )}
    </div>
  );
}
