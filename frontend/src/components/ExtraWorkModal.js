import { useState, useCallback } from "react";
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
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Loader2, Sparkles, CheckCircle2, Package, Hammer, ChevronDown, ChevronRight,
  Plus, Trash2, Copy, Clock, AlertTriangle,
} from "lucide-react";

const UNITS = ["m2", "m", "pcs", "hours", "lot", "kg", "l"];
const UL = { m2: "м2", m: "м", pcs: "бр", hours: "часа", lot: "к-т", kg: "кг", l: "л" };

const emptyLine = () => ({
  id: Date.now().toString() + Math.random().toString(36).substr(2, 4),
  title: "", unit: "m2", qty: 1,
  location_floor: "", location_room: "", location_zone: "", location_notes: "",
});

export default function ExtraWorkModal({ projectId, open, onOpenChange, onCreated }) {
  const [lines, setLines] = useState([emptyLine()]);
  const [city, setCity] = useState("София");
  const [workDate, setWorkDate] = useState(new Date().toISOString().split("T")[0]);
  const [aiLoading, setAiLoading] = useState(false);
  const [batchResult, setBatchResult] = useState(null);
  const [saving, setSaving] = useState(false);
  // Editable proposals per line
  const [editedProposals, setEditedProposals] = useState({});
  // Related SMR selections
  const [selectedRelated, setSelectedRelated] = useState({});
  // Expanded sections
  const [expandedMats, setExpandedMats] = useState({});
  // Two-stage status
  const [stageStatus, setStageStatus] = useState("idle"); // idle | fast_ready | refining | refined | refine_failed
  const [userEditedFields, setUserEditedFields] = useState({}); // {lineIdx: Set of field names}
  const [refineDelta, setRefineDelta] = useState({}); // {lineIdx: {field: newValue}} - pending refinement suggestions

  const reset = () => {
    setLines([emptyLine()]);
    setBatchResult(null);
    setEditedProposals({});
    setSelectedRelated({});
    setExpandedMats({});
    setStageStatus("idle");
    setUserEditedFields({});
    setRefineDelta({});
  };

  // Line management
  const addLine = () => setLines([...lines, emptyLine()]);
  const removeLine = (i) => { if (lines.length > 1) setLines(lines.filter((_, idx) => idx !== i)); };
  const dupLine = (i) => {
    const copy = { ...lines[i], id: Date.now().toString() + Math.random().toString(36).substr(2, 4) };
    const n = [...lines]; n.splice(i + 1, 0, copy); setLines(n);
  };
  const updateLine = (i, f, v) => { const n = [...lines]; n[i] = { ...n[i], [f]: v }; setLines(n); };

  // Two-Stage AI
  const initProposals = (results) => {
    const ep = {};
    results.forEach((r, i) => {
      ep[i] = {
        title: r._input.title,
        activity_type: r.recognized.activity_type,
        activity_subtype: r.recognized.activity_subtype,
        unit: r._input.unit,
        qty: r._input.qty,
        material_price: r.pricing.material_price_per_unit,
        labor_price: r.pricing.labor_price_per_unit,
        total_price: r.pricing.total_price_per_unit,
        original_total_price: r.pricing.total_price_per_unit,
        small_qty_adj: r.pricing.small_qty_adjustment_percent,
        provider: r.provider,
        confidence: r.confidence,
        explanation: r.explanation,
        materials: r.materials || [],
        related_smr: r.related_smr || [],
        hourly_info: r.hourly_info || null,
        location_floor: r._input.location_floor,
        location_room: r._input.location_room,
        location_zone: r._input.location_zone,
        stage: r.stage || "fast",
      };
    });
    return ep;
  };

  const handleBatchAI = async () => {
    const valid = lines.filter(l => l.title.trim());
    if (!valid.length) return;
    const payload = {
      lines: valid.map(l => ({ title: l.title, unit: l.unit, qty: parseFloat(l.qty) || 1,
        location_floor: l.location_floor, location_room: l.location_room, location_zone: l.location_zone })),
      city: city || null, project_id: projectId,
    };

    // Stage A: Fast (rule-based, instant)
    setAiLoading(true);
    try {
      const fastRes = await API.post("/extra-works/ai-fast", payload);
      setBatchResult(fastRes.data);
      setEditedProposals(initProposals(fastRes.data.results));
      const sr = {};
      fastRes.data.results.forEach((_, i) => { sr[i] = {}; });
      setSelectedRelated(sr);
      setStageStatus("fast_ready");
      setAiLoading(false);

      // Stage B: Refine (LLM, async non-blocking)
      setStageStatus("refining");
      try {
        const refineRes = await API.post("/extra-works/ai-refine", payload);
        // Smart merge: only update fields user hasn't edited
        const delta = {};
        refineRes.data.results.forEach((r, i) => {
          const edited = userEditedFields[i] || new Set();
          const updates = {};
          if (!edited.has("material_price") && r.pricing.material_price_per_unit !== editedProposals[i]?.material_price)
            updates.material_price = r.pricing.material_price_per_unit;
          if (!edited.has("labor_price") && r.pricing.labor_price_per_unit !== editedProposals[i]?.labor_price)
            updates.labor_price = r.pricing.labor_price_per_unit;
          if (!edited.has("activity_type") && r.recognized.activity_type !== editedProposals[i]?.activity_type)
            updates.activity_type = r.recognized.activity_type;
          if (!edited.has("activity_subtype") && r.recognized.activity_subtype !== editedProposals[i]?.activity_subtype)
            updates.activity_subtype = r.recognized.activity_subtype;
          // Always update if not edited: explanation, confidence, related, materials
          if (!edited.has("explanation")) updates.explanation = r.explanation;
          updates.confidence = r.confidence;
          updates.provider = r.provider;
          updates.stage = "refined";
          if (!edited.has("related_smr") && r.related_smr?.length > (editedProposals[i]?.related_smr?.length || 0))
            updates.related_smr = r.related_smr;
          if (!edited.has("materials") && r.materials?.length > (editedProposals[i]?.materials?.length || 0))
            updates.materials = r.materials;
          delta[i] = updates;
        });
        setRefineDelta(delta);
        setBatchResult(prev => ({ ...prev, combined_materials: refineRes.data.combined_materials, grand_total: refineRes.data.grand_total }));
        setStageStatus("refined");
      } catch (e) {
        console.warn("Refinement failed:", e);
        setStageStatus("refine_failed");
      }
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при AI");
      setAiLoading(false);
    }
  };

  // Apply refinement delta for a specific line
  const applyRefinement = (lineIdx) => {
    const d = refineDelta[lineIdx];
    if (!d) return;
    setEditedProposals(prev => {
      const updated = { ...prev[lineIdx], ...d };
      if (d.material_price !== undefined || d.labor_price !== undefined) {
        const mp = d.material_price ?? prev[lineIdx].material_price;
        const lp = d.labor_price ?? prev[lineIdx].labor_price;
        updated.total_price = round2(parseFloat(mp) + parseFloat(lp));
      }
      return { ...prev, [lineIdx]: updated };
    });
    setRefineDelta(prev => { const n = { ...prev }; delete n[lineIdx]; return n; });
  };

  // Apply all refinements
  const applyAllRefinements = () => {
    Object.keys(refineDelta).forEach(i => applyRefinement(parseInt(i)));
  };

  // Edit proposal field (tracks user edits for merge protection)
  const editProp = (i, f, v) => {
    setUserEditedFields(prev => {
      const set = new Set(prev[i] || []);
      set.add(f);
      return { ...prev, [i]: set };
    });
    setEditedProposals(prev => {
      const updated = { ...prev[i], [f]: v };
      if (f === "material_price" || f === "labor_price") {
        updated.total_price = round2(parseFloat(updated.material_price || 0) + parseFloat(updated.labor_price || 0));
      }
      return { ...prev, [i]: updated };
    });
  };

  // Toggle related SMR
  const toggleRelated = (lineIdx, smrText) => {
    setSelectedRelated(prev => {
      const current = prev[lineIdx] || {};
      return { ...prev, [lineIdx]: { ...current, [smrText]: !current[smrText] } };
    });
  };

  // Edit material in proposal
  const editMaterial = (lineIdx, matIdx, field, value) => {
    setEditedProposals(prev => {
      const mats = [...(prev[lineIdx]?.materials || [])];
      mats[matIdx] = { ...mats[matIdx], [field]: value };
      return { ...prev, [lineIdx]: { ...prev[lineIdx], materials: mats } };
    });
  };
  const removeMaterial = (lineIdx, matIdx) => {
    setEditedProposals(prev => {
      const mats = (prev[lineIdx]?.materials || []).filter((_, i) => i !== matIdx);
      return { ...prev, [lineIdx]: { ...prev[lineIdx], materials: mats } };
    });
  };
  const addMaterial = (lineIdx) => {
    setEditedProposals(prev => {
      const mats = [...(prev[lineIdx]?.materials || []), { name: "", unit: "", estimated_qty: null, category: "primary", reason: "" }];
      return { ...prev, [lineIdx]: { ...prev[lineIdx], materials: mats } };
    });
  };

  // Save all accepted lines
  const handleSaveAll = async () => {
    if (!batchResult) return;
    setSaving(true);
    try {
      const linesToSave = [];
      // Main lines
      Object.values(editedProposals).forEach(p => {
        linesToSave.push(p);
      });
      // Selected related SMR
      Object.entries(selectedRelated).forEach(([lineIdx, selected]) => {
        const parentProp = editedProposals[lineIdx];
        Object.entries(selected).forEach(([smrText, isSelected]) => {
          if (isSelected) {
            linesToSave.push({
              title: smrText,
              activity_type: parentProp?.activity_type || "Общо",
              activity_subtype: "",
              unit: parentProp?.unit || "m2",
              qty: parentProp?.qty || 1,
              material_price: 0, labor_price: 0, total_price: 0,
              provider: "related_suggestion",
              confidence: 0.5,
              explanation: `Свързано с: ${parentProp?.title}`,
              materials: [],
              related_smr: [],
              location_floor: parentProp?.location_floor,
              location_room: parentProp?.location_room,
              location_zone: parentProp?.location_zone,
            });
          }
        });
      });

      await API.post("/extra-works/batch-save", {
        project_id: projectId,
        work_date: workDate,
        lines: linesToSave,
      });

      // Record calibration events
      for (const p of Object.values(editedProposals)) {
        if (p.provider && p.total_price > 0) {
          try {
            await API.post("/ai-calibration/record-edit", {
              ai_provider_used: p.provider, ai_confidence: p.confidence,
              ai_material_price_per_unit: p.material_price, ai_labor_price_per_unit: p.labor_price,
              ai_total_price_per_unit: p.original_total_price || p.total_price,
              final_material_price_per_unit: p.material_price, final_labor_price_per_unit: p.labor_price,
              final_total_price_per_unit: p.total_price,
              city: city, project_id: projectId, source_type: "extra_work",
              normalized_activity_type: p.activity_type, normalized_activity_subtype: p.activity_subtype,
              unit: p.unit, qty: p.qty, small_qty_flag: (p.qty || 1) <= 5,
            });
          } catch { /* silent */ }
        }
      }

      reset();
      onOpenChange(false);
      onCreated?.();
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка");
    } finally { setSaving(false); }
  };

  const round2 = (n) => Math.round(n * 100) / 100;
  const grandTotal = batchResult ? Object.values(editedProposals).reduce((s, p) =>
    s + (parseFloat(p.total_price) || 0) * (parseFloat(p.qty) || 1), 0) : 0;

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
      <DialogContent className="sm:max-w-[900px] bg-card border-border max-h-[92vh] overflow-y-auto" data-testid="extra-work-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Hammer className="w-5 h-5 text-amber-500" />
            Ново допълнително СМР {lines.length > 1 && `(${lines.length} реда)`}
          </DialogTitle>
        </DialogHeader>

        {/* Phase 1: Entry */}
        {!batchResult && (
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Дата</Label>
                <Input type="date" value={workDate} onChange={e => setWorkDate(e.target.value)} className="bg-background" />
              </div>
              <div className="space-y-1">
                <Label>Град</Label>
                <Input value={city} onChange={e => setCity(e.target.value)} placeholder="София" className="bg-background" data-testid="ew-city" />
              </div>
            </div>

            {/* Multi-line entry */}
            <div className="space-y-2">
              {lines.map((line, i) => (
                <div key={line.id} className="p-3 rounded-lg bg-muted/20 border border-border space-y-2" data-testid={`entry-line-${i}`}>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground font-mono w-5">{i + 1}</span>
                    <Input value={line.title} onChange={e => updateLine(i, "title", e.target.value)}
                      placeholder="Описание на СМР" className="flex-1 bg-background text-sm" data-testid={`ew-title-${i}`} />
                    <Select value={line.unit} onValueChange={v => updateLine(i, "unit", v)}>
                      <SelectTrigger className="w-20 bg-background text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>{UNITS.map(u => <SelectItem key={u} value={u}>{UL[u]}</SelectItem>)}</SelectContent>
                    </Select>
                    <Input type="number" min="0.01" step="0.01" value={line.qty} onChange={e => updateLine(i, "qty", e.target.value)}
                      className="w-16 bg-background text-sm font-mono" />
                    <Button variant="ghost" size="sm" onClick={() => dupLine(i)} className="h-7 w-7 p-0 text-muted-foreground"><Copy className="w-3 h-3" /></Button>
                    {lines.length > 1 && <Button variant="ghost" size="sm" onClick={() => removeLine(i)} className="h-7 w-7 p-0 text-destructive"><Trash2 className="w-3 h-3" /></Button>}
                  </div>
                  <div className="grid grid-cols-4 gap-2">
                    <Input value={line.location_floor} onChange={e => updateLine(i, "location_floor", e.target.value)} placeholder="Етаж" className="bg-background text-xs" />
                    <Input value={line.location_room} onChange={e => updateLine(i, "location_room", e.target.value)} placeholder="Помещение" className="bg-background text-xs" />
                    <Input value={line.location_zone} onChange={e => updateLine(i, "location_zone", e.target.value)} placeholder="Зона" className="bg-background text-xs" />
                    <Input value={line.location_notes} onChange={e => updateLine(i, "location_notes", e.target.value)} placeholder="Бележка" className="bg-background text-xs" />
                  </div>
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={addLine}><Plus className="w-3 h-3 mr-1" /> Добави ред</Button>
            </div>

            <Button onClick={handleBatchAI} disabled={aiLoading || !lines.some(l => l.title.trim())} className="w-full bg-violet-600 hover:bg-violet-700" data-testid="batch-ai-btn">
              {aiLoading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Sparkles className="w-4 h-4 mr-2" />}
              Сметни с AI ({lines.filter(l => l.title.trim()).length} {lines.filter(l => l.title.trim()).length === 1 ? "ред" : "реда"})
            </Button>
          </div>
        )}

        {/* Phase 2: Editable AI Results */}
        {batchResult && (
          <div className="space-y-3 py-2">
            {/* Summary bar with stage status */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-violet-500/10 border border-violet-500/30">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-violet-400" />
                <span className="text-sm font-medium text-violet-300">{batchResult.line_count} реда анализирани</span>
                {stageStatus === "fast_ready" && <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-400 border-amber-500/30">Бърз анализ</Badge>}
                {stageStatus === "refining" && <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/30 animate-pulse"><Loader2 className="w-2.5 h-2.5 animate-spin mr-0.5 inline" />LLM уточняване...</Badge>}
                {stageStatus === "refined" && <Badge variant="outline" className="text-[10px] bg-emerald-500/10 text-emerald-400 border-emerald-500/30"><CheckCircle2 className="w-2.5 h-2.5 mr-0.5 inline" />LLM уточнено</Badge>}
                {stageStatus === "refine_failed" && <Badge variant="outline" className="text-[10px] bg-gray-500/10 text-gray-400 border-gray-500/30"><AlertTriangle className="w-2.5 h-2.5 mr-0.5 inline" />LLM недостъпен</Badge>}
              </div>
              <div className="flex items-center gap-3">
                {stageStatus === "refined" && Object.keys(refineDelta).length > 0 && (
                  <Button size="sm" variant="outline" onClick={applyAllRefinements} className="text-[10px] h-6 border-emerald-500/30 text-emerald-400" data-testid="apply-all-refine-btn">
                    <CheckCircle2 className="w-3 h-3 mr-1" /> Приеми LLM подобрения ({Object.keys(refineDelta).length})
                  </Button>
                )}
                <div className="font-mono text-lg font-bold text-primary">{round2(grandTotal).toFixed(2)} лв</div>
              </div>
            </div>

            {/* Per-line editable results */}
            {batchResult.results.map((result, i) => {
              const p = editedProposals[i];
              if (!p) return null;
              const lineTotal = round2((parseFloat(p.total_price) || 0) * (parseFloat(p.qty) || 1));
              const hasRefine = refineDelta[i] && Object.keys(refineDelta[i]).length > 0;
              return (
                <div key={i} className={`rounded-lg border overflow-hidden ${hasRefine ? "border-blue-500/30" : "border-border"}`} data-testid={`result-line-${i}`}>
                  {/* Header */}
                  <div className="p-3 bg-muted/30 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-muted-foreground">{i + 1}</span>
                      <span className="text-sm font-medium text-foreground">{p.title}</span>
                      <Badge variant="outline" className={`text-[10px] ${p.provider === "llm" ? "bg-emerald-500/10 text-emerald-400" : "bg-gray-500/10 text-gray-400"}`}>
                        {p.provider === "llm" ? "LLM" : "Rule"}
                      </Badge>
                      <Badge variant="outline" className="text-[10px]">{Math.round(p.confidence * 100)}%</Badge>
                      {p.stage === "fast" && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400">Бърз</Badge>}
                      {p.stage === "refined" && <Badge variant="outline" className="text-[9px] bg-emerald-500/10 text-emerald-400">LLM</Badge>}
                    </div>
                    <div className="flex items-center gap-2">
                      {hasRefine && (
                        <Button size="sm" variant="ghost" onClick={() => applyRefinement(i)} className="text-[10px] h-5 text-blue-400" data-testid={`apply-refine-${i}`}>
                          Приеми LLM
                        </Button>
                      )}
                      <span className="font-mono font-bold text-primary">{lineTotal.toFixed(2)} лв</span>
                    </div>
                  </div>

                  <div className="p-3 space-y-2">
                    {/* Editable pricing */}
                    <div className="grid grid-cols-6 gap-2">
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Тип</label>
                        <Input value={p.activity_type} onChange={e => editProp(i, "activity_type", e.target.value)} className="bg-background h-7 text-xs" />
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Подтип</label>
                        <Input value={p.activity_subtype} onChange={e => editProp(i, "activity_subtype", e.target.value)} className="bg-background h-7 text-xs" />
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Мат. лв/ед</label>
                        <Input type="number" step="0.01" value={p.material_price} onChange={e => editProp(i, "material_price", parseFloat(e.target.value) || 0)} className="bg-background h-7 text-xs font-mono" />
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Труд лв/ед</label>
                        <Input type="number" step="0.01" value={p.labor_price} onChange={e => editProp(i, "labor_price", parseFloat(e.target.value) || 0)} className="bg-background h-7 text-xs font-mono" />
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">Общо/ед</label>
                        <div className="h-7 px-2 flex items-center bg-muted/30 rounded text-xs font-mono font-bold text-primary">{(parseFloat(p.total_price) || 0).toFixed(2)}</div>
                      </div>
                      <div className="space-y-0.5">
                        <label className="text-[10px] text-muted-foreground">К-во</label>
                        <Input type="number" step="0.01" value={p.qty} onChange={e => editProp(i, "qty", parseFloat(e.target.value) || 1)} className="bg-background h-7 text-xs font-mono" />
                      </div>
                    </div>

                    {/* Hourly info + small qty */}
                    <div className="flex flex-wrap gap-2 text-[10px]">
                      {p.small_qty_adj > 0 && <Badge variant="outline" className="bg-amber-500/10 text-amber-400 border-amber-500/30">+{p.small_qty_adj}% малко к-во</Badge>}
                      {p.hourly_info && <Badge variant="outline" className="bg-blue-500/10 text-blue-400 border-blue-500/30">
                        <Clock className="w-2.5 h-2.5 mr-0.5" />{p.hourly_info.worker_type} {p.hourly_info.hourly_rate}лв/ч
                        {p.hourly_info.min_applied && " (мин.)"}
                      </Badge>}
                      {p.explanation && <span className="text-muted-foreground/70 italic">{p.explanation.slice(0, 80)}</span>}
                    </div>

                    {/* Related SMR */}
                    {p.related_smr?.length > 0 && (
                      <div className="pt-1">
                        <label className="text-[10px] text-muted-foreground font-medium">Свързани СМР (избери за добавяне)</label>
                        <div className="flex flex-wrap gap-1.5 mt-1">
                          {p.related_smr.map((smr, si) => {
                            const sel = selectedRelated[i]?.[smr];
                            return (
                              <button key={si} onClick={() => toggleRelated(i, smr)}
                                className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${sel ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-400" : "bg-muted/20 border-border text-muted-foreground hover:border-primary/30"}`}>
                                {sel && <CheckCircle2 className="w-2.5 h-2.5 inline mr-0.5" />}{smr}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Editable Materials */}
                    <div className="pt-1">
                      <button onClick={() => setExpandedMats(prev => ({ ...prev, [i]: !prev[i] }))} className="flex items-center gap-1 text-[10px] text-muted-foreground font-medium">
                        {expandedMats[i] ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                        <Package className="w-3 h-3" /> Материали ({p.materials?.length || 0})
                      </button>
                      {expandedMats[i] && (
                        <div className="mt-1 space-y-1">
                          {(p.materials || []).map((mat, mi) => (
                            <div key={mi} className="flex items-center gap-1">
                              <Badge variant="outline" className={`text-[8px] w-10 justify-center ${mat.category === "primary" ? "text-emerald-400" : mat.category === "secondary" ? "text-amber-400" : "text-gray-400"}`}>
                                {mat.category === "primary" ? "Осн" : mat.category === "secondary" ? "Спом" : "Конс"}
                              </Badge>
                              <Input value={mat.name} onChange={e => editMaterial(i, mi, "name", e.target.value)} className="flex-1 bg-background h-6 text-[10px]" />
                              <Input value={mat.estimated_qty || ""} onChange={e => editMaterial(i, mi, "estimated_qty", e.target.value)} className="w-12 bg-background h-6 text-[10px] font-mono" placeholder="к-во" />
                              <Input value={mat.unit} onChange={e => editMaterial(i, mi, "unit", e.target.value)} className="w-10 bg-background h-6 text-[10px]" />
                              <Button variant="ghost" size="sm" onClick={() => removeMaterial(i, mi)} className="h-6 w-6 p-0 text-destructive"><Trash2 className="w-2.5 h-2.5" /></Button>
                            </div>
                          ))}
                          <Button variant="ghost" size="sm" onClick={() => addMaterial(i)} className="text-[10px] h-5"><Plus className="w-2.5 h-2.5 mr-0.5" /> Добави материал</Button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}

            {/* Combined materials summary */}
            {batchResult.combined_materials?.length > 0 && (
              <div className="p-3 rounded-lg bg-muted/20 border border-border">
                <p className="text-xs font-medium text-muted-foreground mb-1">Общ материален списък ({batchResult.combined_materials.length} позиции)</p>
                <div className="flex flex-wrap gap-1">
                  {batchResult.combined_materials.slice(0, 15).map((m, i) => (
                    <Badge key={i} variant="outline" className={`text-[9px] ${m.category === "primary" ? "text-emerald-400" : m.category === "secondary" ? "text-amber-400" : "text-gray-400"}`}>
                      {m.name}{m.estimated_qty ? ` (${m.estimated_qty} ${m.unit})` : ""}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button variant="outline" onClick={() => { reset(); onOpenChange(false); }}>Затвори</Button>
          {batchResult && (
            <>
              <Button variant="outline" onClick={() => setBatchResult(null)}>Обратно към входа</Button>
              <Button onClick={handleSaveAll} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700" data-testid="save-all-btn">
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <CheckCircle2 className="w-4 h-4 mr-1" />}
                Приеми всички ({Object.keys(editedProposals).length + Object.values(selectedRelated).reduce((s, o) => s + Object.values(o).filter(Boolean).length, 0)} реда)
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
