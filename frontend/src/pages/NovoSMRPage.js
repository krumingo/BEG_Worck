import { useState, useCallback, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Sparkles, Plus, Trash2, Copy, Loader2, ArrowLeft, Save, Send,
  MapPin, Clock, CheckCircle2, X,
} from "lucide-react";
import LocationPicker from "@/components/LocationPicker";
import AIPricingBreakdown from "@/components/AIPricingBreakdown";

const UNITS = ["m2", "m", "pcs", "hours", "lot", "kg", "l"];
const UL = { m2: "м2", m: "м", pcs: "бр", hours: "часа", lot: "к-т", kg: "кг", l: "л" };

const emptyRow = () => ({
  id: Date.now().toString() + Math.random().toString(36).substr(2, 4),
  text: "", unit: "m2", qty: 1,
  floor: "", room: "", zone: "", note: "",
  selected: true,
});

export default function NovoSMRPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [project, setProject] = useState(null);
  const [rows, setRows] = useState([emptyRow()]);
  const [city, setCity] = useState("София");
  const [loading, setLoading] = useState(true);

  // AI state
  const [aiPhase, setAiPhase] = useState("input"); // input | results
  const [aiLoading, setAiLoading] = useState(false);
  const [proposals, setProposals] = useState({});
  const [refineStatus, setRefineStatus] = useState("idle"); // idle | refining | done | failed

  // Save state
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await API.get(`/projects/${projectId}`);
        setProject(res.data);
      } catch { /* */ }
      finally { setLoading(false); }
    })();
  }, [projectId]);

  // Row management
  const addRow = () => setRows(prev => [...prev, emptyRow()]);
  const removeRow = (i) => { if (rows.length > 1) setRows(rows.filter((_, idx) => idx !== i)); };
  const dupRow = (i) => {
    const copy = { ...rows[i], id: Date.now().toString() + Math.random().toString(36).substr(2, 4) };
    const n = [...rows]; n.splice(i + 1, 0, copy); setRows(n);
  };
  const updateRow = (i, f, v) => { const n = [...rows]; n[i] = { ...n[i], [f]: v }; setRows(n); };

  // Handle Enter key on text field — add new row
  const handleKeyDown = (e, i) => {
    if (e.key === "Enter" && rows[i].text.trim() && i === rows.length - 1) {
      e.preventDefault();
      addRow();
      setTimeout(() => {
        const next = document.querySelector(`[data-testid="smr-text-${i + 1}"]`);
        if (next) next.focus();
      }, 100);
    }
  };

  // AI Analysis
  const runAI = async () => {
    const valid = rows.filter(r => r.text.trim());
    if (!valid.length) return;
    setAiLoading(true);
    setAiPhase("results");
    setRefineStatus("idle");

    try {
      // Stage A: Fast
      const fastRes = await API.post("/extra-works/ai-fast", {
        lines: valid.map(r => ({
          title: r.text, unit: r.unit, qty: parseFloat(r.qty) || 1,
          location_floor: r.floor, location_room: r.room, location_zone: r.zone,
        })),
        city: city || null,
      });

      const props = {};
      fastRes.data.results.forEach((r, i) => {
        props[i] = {
          text: r._input.title,
          type: r.recognized.activity_type,
          subtype: r.recognized.activity_subtype,
          unit: r.recognized.suggested_unit || r._input.unit,
          qty: r._input.qty,
          material: r.pricing.material_price_per_unit,
          labor: r.pricing.labor_price_per_unit,
          confidence: r.confidence,
          provider: r.provider,
          explanation: r.explanation || "",
          hint: r.internal_price_hint || null,
          hourly: r.hourly_info || null,
          smallQty: r.pricing.small_qty_adjustment_percent || 0,
          materials: r.materials || [],
          floor: r._input.location_floor || "",
          room: r._input.location_room || "",
          zone: r._input.location_zone || "",
          selected: true,
          stage: "fast",
        };
      });
      setProposals(props);
      setAiLoading(false);

      // Stage B: LLM Refine (background)
      setRefineStatus("refining");
      API.post("/extra-works/ai-refine", {
        lines: valid.map(r => ({
          title: r.text, unit: r.unit, qty: parseFloat(r.qty) || 1,
          location_floor: r.floor, location_room: r.room, location_zone: r.zone,
        })),
        city: city || null,
      }).then(refRes => {
        setProposals(prev => {
          const updated = { ...prev };
          refRes.data.results.forEach((r, i) => {
            if (updated[i] && updated[i].material === prev[i]?.material && updated[i].labor === prev[i]?.labor) {
              updated[i] = {
                ...updated[i],
                material: r.pricing.material_price_per_unit,
                labor: r.pricing.labor_price_per_unit,
                confidence: r.confidence,
                provider: r.provider,
                explanation: r.explanation || updated[i].explanation,
                hint: r.internal_price_hint || updated[i].hint,
                stage: "refined",
              };
            }
          });
          return updated;
        });
        setRefineStatus("done");
      }).catch(() => setRefineStatus("failed"));
    } catch (err) {
      console.error(err);
      setAiLoading(false);
    }
  };

  const editProp = (i, f, v) => setProposals(prev => ({ ...prev, [i]: { ...prev[i], [f]: v } }));
  const toggleSelect = (i) => setProposals(prev => ({ ...prev, [i]: { ...prev[i], selected: !prev[i].selected } }));

  const selectedCount = Object.values(proposals).filter(p => p.selected).length;
  const grandTotal = Object.values(proposals).filter(p => p.selected).reduce(
    (s, p) => s + ((parseFloat(p.material) || 0) + (parseFloat(p.labor) || 0)) * (parseFloat(p.qty) || 1), 0);

  // Save
  const handleSave = async (status = "draft") => {
    const selected = Object.values(proposals).filter(p => p.selected);
    if (!selected.length) return;
    setSaving(true);
    try {
      await API.post("/extra-works/batch-save", {
        project_id: projectId,
        work_date: new Date().toISOString().split("T")[0],
        lines: selected.map(p => ({
          title: p.text,
          activity_type: p.type,
          activity_subtype: p.subtype,
          unit: p.unit,
          qty: parseFloat(p.qty) || 1,
          material_price: parseFloat(p.material) || 0,
          labor_price: parseFloat(p.labor) || 0,
          total_price: (parseFloat(p.material) || 0) + (parseFloat(p.labor) || 0),
          original_total_price: (parseFloat(p.material) || 0) + (parseFloat(p.labor) || 0),
          provider: p.provider,
          confidence: p.confidence,
          explanation: p.explanation,
          materials: p.materials || [],
          related_smr: [],
          location_floor: p.floor,
          location_room: p.room,
          location_zone: p.zone,
          notes: "",
        })),
      });

      // Record calibration events
      for (const p of selected) {
        try {
          await API.post("/ai-calibration/record-edit", {
            ai_provider_used: p.provider, ai_confidence: p.confidence,
            ai_material_price_per_unit: p.material, ai_labor_price_per_unit: p.labor,
            ai_total_price_per_unit: (parseFloat(p.material) || 0) + (parseFloat(p.labor) || 0),
            final_material_price_per_unit: p.material, final_labor_price_per_unit: p.labor,
            final_total_price_per_unit: (parseFloat(p.material) || 0) + (parseFloat(p.labor) || 0),
            city: city, project_id: projectId, source_type: "extra_work",
            normalized_activity_type: p.type, normalized_activity_subtype: p.subtype,
            unit: p.unit, qty: p.qty, small_qty_flag: (p.qty || 1) <= 5,
          });
        } catch { /* silent */ }
      }

      navigate(`/projects/${projectId}`);
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при запис");
    } finally { setSaving(false); }
  };

  // Back to input
  const backToInput = () => {
    // Sync edited proposals back to rows
    const newRows = Object.values(proposals).map(p => ({
      id: Date.now().toString() + Math.random().toString(36).substr(2, 4),
      text: p.text, unit: p.unit, qty: p.qty,
      floor: p.floor || "", room: p.room || "", zone: p.zone || "", note: "",
      selected: true,
    }));
    setRows(newRows.length ? newRows : [emptyRow()]);
    setAiPhase("input");
    setProposals({});
  };

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  return (
    <div className="p-6 max-w-[1100px]" data-testid="novo-smr-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate(`/projects/${projectId}`)}>
            <ArrowLeft className="w-4 h-4 mr-1" /> Обект
          </Button>
          <div>
            <h1 className="text-xl font-bold text-foreground">Ново СМР</h1>
            <p className="text-sm text-muted-foreground">{project?.code} — {project?.name}</p>
          </div>
        </div>
        {aiPhase === "results" && (
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => handleSave("draft")} disabled={saving || !selectedCount} data-testid="save-draft-btn">
              <Save className="w-4 h-4 mr-1" /> Запази чернова
            </Button>
            <Button onClick={() => handleSave("ready")} disabled={saving || !selectedCount} className="bg-emerald-600 hover:bg-emerald-700" data-testid="save-ready-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Send className="w-4 h-4 mr-1" />}
              Запази като готово ({selectedCount})
            </Button>
          </div>
        )}
      </div>

      {/* INPUT PHASE */}
      {aiPhase === "input" && (
        <div className="space-y-3">
          {/* City */}
          <div className="flex items-center gap-3 mb-2">
            <label className="text-xs text-muted-foreground">Град:</label>
            <Input value={city} onChange={e => setCity(e.target.value)} className="w-32 bg-card h-7 text-xs" />
          </div>

          {/* Rows */}
          <div className="space-y-2">
            {rows.map((row, i) => (
              <div key={row.id} className="rounded-lg border border-border bg-card p-3" data-testid={`smr-row-${i}`}>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-mono text-muted-foreground w-5">{i + 1}</span>
                  <Input value={row.text} onChange={e => updateRow(i, "text", e.target.value)}
                    onKeyDown={e => handleKeyDown(e, i)}
                    placeholder="Описание на СМР (напр. Мазилка по стени)" className="flex-1 bg-background text-sm"
                    data-testid={`smr-text-${i}`} />
                  <Select value={row.unit} onValueChange={v => updateRow(i, "unit", v)}>
                    <SelectTrigger className="w-20 bg-background text-xs h-9"><SelectValue /></SelectTrigger>
                    <SelectContent>{UNITS.map(u => <SelectItem key={u} value={u}>{UL[u]}</SelectItem>)}</SelectContent>
                  </Select>
                  <Input type="number" min="0.01" step="0.01" value={row.qty}
                    onChange={e => updateRow(i, "qty", e.target.value)}
                    className="w-16 bg-background text-sm font-mono h-9" />
                  <Button variant="ghost" size="sm" onClick={() => dupRow(i)} className="h-8 w-8 p-0 text-muted-foreground"><Copy className="w-3.5 h-3.5" /></Button>
                  {rows.length > 1 && <Button variant="ghost" size="sm" onClick={() => removeRow(i)} className="h-8 w-8 p-0 text-destructive"><Trash2 className="w-3.5 h-3.5" /></Button>}
                </div>
                {/* Location fields */}
                <div className="flex items-center gap-2 ml-7">
                  <MapPin className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                  <div className="flex-1">
                    <LocationPicker projectId={projectId} value={row.location_id} onChange={(id, node) => {
                      updateRow(i, "location_id", id);
                      if (node) {
                        if (node.type === "floor") updateRow(i, "floor", node.name);
                        else if (node.type === "room") updateRow(i, "room", node.name);
                        else if (node.type === "zone") updateRow(i, "zone", node.name);
                      }
                    }} />
                  </div>
                  <Input value={row.floor} onChange={e => updateRow(i, "floor", e.target.value)} placeholder="Етаж" className="w-14 bg-background text-xs h-7" />
                  <Input value={row.room} onChange={e => updateRow(i, "room", e.target.value)} placeholder="Пом." className="w-14 bg-background text-xs h-7" />
                </div>
              </div>
            ))}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={addRow}>
              <Plus className="w-3.5 h-3.5 mr-1" /> Добави ред
            </Button>
          </div>

          {/* AI Button — sticky at bottom */}
          <div className="sticky bottom-4 pt-3">
            <Button onClick={runAI} disabled={aiLoading || !rows.some(r => r.text.trim())}
              className="w-full bg-violet-600 hover:bg-violet-700 h-11 text-base" data-testid="analyze-btn">
              {aiLoading ? <Loader2 className="w-5 h-5 animate-spin mr-2" /> : <Sparkles className="w-5 h-5 mr-2" />}
              Анализирай с AI ({rows.filter(r => r.text.trim()).length} {rows.filter(r => r.text.trim()).length === 1 ? "ред" : "реда"})
            </Button>
          </div>
        </div>
      )}

      {/* RESULTS PHASE */}
      {aiPhase === "results" && (
        <div className="space-y-3">
          {/* Summary bar */}
          <div className="flex items-center justify-between p-3 rounded-lg bg-violet-500/10 border border-violet-500/30">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-violet-400" />
              <span className="text-sm text-violet-300">{Object.keys(proposals).length} реда</span>
              {refineStatus === "refining" && <Badge variant="outline" className="text-[9px] bg-blue-500/10 text-blue-400 animate-pulse">LLM...</Badge>}
              {refineStatus === "done" && <Badge variant="outline" className="text-[9px] bg-emerald-500/10 text-emerald-400"><CheckCircle2 className="w-2.5 h-2.5 mr-0.5 inline" />LLM</Badge>}
              {refineStatus === "failed" && <Badge variant="outline" className="text-[9px] bg-gray-500/10 text-gray-400">LLM n/a</Badge>}
            </div>
            <span className="font-mono text-lg font-bold text-primary">{grandTotal.toFixed(2)} EUR</span>
          </div>

          {/* Proposal rows */}
          {Object.entries(proposals).map(([i, p]) => {
            const total = ((parseFloat(p.material) || 0) + (parseFloat(p.labor) || 0));
            const lineTotal = total * (parseFloat(p.qty) || 1);
            return (
              <div key={i} className={`rounded-lg border p-3 transition-colors ${p.selected ? "border-border bg-card" : "border-border/50 bg-card/50 opacity-60"}`}
                data-testid={`proposal-row-${i}`}>
                {/* Header */}
                <div className="flex items-center gap-2 mb-2">
                  <Checkbox checked={p.selected} onCheckedChange={() => toggleSelect(i)} />
                  <span className="text-xs font-mono text-muted-foreground">{parseInt(i) + 1}</span>
                  <span className="text-sm font-medium text-foreground flex-1">{p.text}</span>
                  <Badge variant="outline" className={`text-[9px] ${p.provider === "llm" ? "bg-emerald-500/10 text-emerald-400" : "bg-gray-500/10 text-gray-400"}`}>
                    {p.provider === "llm" ? "LLM" : "Rule"} {Math.round(p.confidence * 100)}%
                  </Badge>
                  <span className="font-mono text-sm font-bold text-primary">{lineTotal.toFixed(2)} EUR</span>
                </div>

                {/* Editable fields */}
                {p.selected && (
                  <>
                    <div className="grid grid-cols-7 gap-2 mb-2 items-end">
                      <div className="col-span-2 space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Описание</label>
                        <Input value={p.text} onChange={e => editProp(i, "text", e.target.value)} className="bg-background h-7 text-xs" />
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Мярка</label>
                        <Select value={p.unit} onValueChange={v => editProp(i, "unit", v)}>
                          <SelectTrigger className="bg-background h-7 text-xs"><SelectValue /></SelectTrigger>
                          <SelectContent>{UNITS.map(u => <SelectItem key={u} value={u}>{UL[u]}</SelectItem>)}</SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">К-во</label>
                        <Input type="number" step="0.01" value={p.qty} onChange={e => editProp(i, "qty", parseFloat(e.target.value) || 1)} className="bg-background h-7 text-xs font-mono" />
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Мат. EUR/ед</label>
                        <Input type="number" step="0.01" value={p.material} onChange={e => editProp(i, "material", parseFloat(e.target.value) || 0)} className="bg-background h-7 text-xs font-mono" />
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Труд EUR/ед</label>
                        <Input type="number" step="0.01" value={p.labor} onChange={e => editProp(i, "labor", parseFloat(e.target.value) || 0)} className="bg-background h-7 text-xs font-mono" />
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Общо/ед</label>
                        <div className="h-7 px-2 flex items-center bg-muted/30 rounded text-xs font-mono font-bold text-primary">{total.toFixed(2)}</div>
                      </div>
                    </div>

                    {/* Pricing breakdown + Materials */}
                    <AIPricingBreakdown proposal={p} />
                    {(p.floor || p.room || p.zone) && (
                      <div className="flex items-center gap-1 text-[10px] text-muted-foreground/60 mt-0.5">
                        <MapPin className="w-2.5 h-2.5" />{[p.floor && `Ет.${p.floor}`, p.room, p.zone].filter(Boolean).join(", ")}
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })}

          {/* Bottom actions */}
          <div className="flex items-center justify-between pt-2">
            <Button variant="outline" size="sm" onClick={backToInput} data-testid="back-to-input-btn">
              <ArrowLeft className="w-3.5 h-3.5 mr-1" /> Редактирай и пресметни
            </Button>
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={() => handleSave("draft")} disabled={saving || !selectedCount} data-testid="save-draft-btn-bottom">
                <Save className="w-4 h-4 mr-1" /> Чернова
              </Button>
              <Button onClick={() => handleSave("ready")} disabled={saving || !selectedCount} className="bg-emerald-600 hover:bg-emerald-700" data-testid="save-ready-btn-bottom">
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <CheckCircle2 className="w-4 h-4 mr-1" />}
                Запази ({selectedCount} реда, {grandTotal.toFixed(2)} EUR)
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
