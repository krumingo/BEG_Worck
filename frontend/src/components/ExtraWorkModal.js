import { useState } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Loader2, Sparkles, CheckCircle2, Package, Wrench, Hammer, ChevronDown, ChevronRight, Plus,
} from "lucide-react";

const UNITS = ["m2", "m", "pcs", "hours", "lot", "kg", "l"];
const UNIT_LABELS = { m2: "м2", m: "м", pcs: "бр", hours: "часа", lot: "к-т", kg: "кг", l: "л" };

export default function ExtraWorkModal({ projectId, open, onOpenChange, onCreated }) {
  const [form, setForm] = useState({
    title: "", unit: "m2", qty: 1,
    location_floor: "", location_room: "", location_zone: "", location_notes: "",
    notes: "", work_date: new Date().toISOString().split("T")[0],
  });
  const [saving, setSaving] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [proposal, setProposal] = useState(null);
  const [showMaterials, setShowMaterials] = useState(false);
  const [city, setCity] = useState("София");

  const resetForm = () => {
    setForm({ title: "", unit: "m2", qty: 1, location_floor: "", location_room: "", location_zone: "", location_notes: "", notes: "", work_date: new Date().toISOString().split("T")[0] });
    setProposal(null);
    setShowMaterials(false);
  };

  const handleAI = async () => {
    if (!form.title.trim()) return;
    setAiLoading(true);
    try {
      const res = await API.post("/extra-works/ai-proposal", {
        title: form.title, unit: form.unit, qty: parseFloat(form.qty) || 1, city: city || null,
      });
      setProposal(res.data);
    } catch (err) {
      console.error(err);
    } finally { setAiLoading(false); }
  };

  const handleSaveDraft = async (applyAi = false) => {
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      const res = await API.post("/extra-works", { project_id: projectId, ...form, qty: parseFloat(form.qty) || 1 });
      const draftId = res.data.id;
      if (applyAi && proposal) {
        await API.post(`/extra-works/${draftId}/apply-ai?city=${encodeURIComponent(city || "")}`);
      }
      resetForm();
      onOpenChange(false);
      onCreated?.();
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка");
    } finally { setSaving(false); }
  };

  const primaryMats = proposal?.materials?.filter(m => m.category === "primary") || [];
  const secondaryMats = proposal?.materials?.filter(m => m.category === "secondary") || [];
  const consumables = proposal?.materials?.filter(m => m.category === "consumable") || [];

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) resetForm(); onOpenChange(v); }}>
      <DialogContent className="sm:max-w-[700px] bg-card border-border max-h-[90vh] overflow-y-auto" data-testid="extra-work-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Hammer className="w-5 h-5 text-amber-500" />
            Ново допълнително СМР
          </DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 py-2">
          {/* Left: Form */}
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>Дата</Label>
              <Input type="date" value={form.work_date} onChange={e => setForm({...form, work_date: e.target.value})} className="bg-background" data-testid="ew-date" />
            </div>
            <div className="space-y-1">
              <Label>Описание на СМР *</Label>
              <Textarea value={form.title} onChange={e => setForm({...form, title: e.target.value})} placeholder="Напр. Направа на мазилка по стена" className="bg-background min-h-[60px]" data-testid="ew-title" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Мярка</Label>
                <Select value={form.unit} onValueChange={v => setForm({...form, unit: v})}>
                  <SelectTrigger className="bg-background" data-testid="ew-unit"><SelectValue /></SelectTrigger>
                  <SelectContent>{UNITS.map(u => <SelectItem key={u} value={u}>{UNIT_LABELS[u] || u}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Количество</Label>
                <Input type="number" min="0.01" step="0.01" value={form.qty} onChange={e => setForm({...form, qty: e.target.value})} className="bg-background font-mono" data-testid="ew-qty" />
              </div>
            </div>

            {/* Location */}
            <div className="p-3 rounded-lg bg-muted/30 border border-border space-y-2">
              <Label className="text-xs text-muted-foreground font-medium">Местоположение</Label>
              <div className="grid grid-cols-3 gap-2">
                <Input value={form.location_floor} onChange={e => setForm({...form, location_floor: e.target.value})} placeholder="Етаж" className="bg-background text-sm" data-testid="ew-floor" />
                <Input value={form.location_room} onChange={e => setForm({...form, location_room: e.target.value})} placeholder="Помещение" className="bg-background text-sm" data-testid="ew-room" />
                <Input value={form.location_zone} onChange={e => setForm({...form, location_zone: e.target.value})} placeholder="Зона" className="bg-background text-sm" data-testid="ew-zone" />
              </div>
              <Input value={form.location_notes} onChange={e => setForm({...form, location_notes: e.target.value})} placeholder="Доп. бележка за локация" className="bg-background text-sm" data-testid="ew-loc-notes" />
            </div>

            <div className="space-y-1">
              <Label>Бележки</Label>
              <Textarea value={form.notes} onChange={e => setForm({...form, notes: e.target.value})} placeholder="Допълнителни бележки" className="bg-background min-h-[40px] text-sm" />
            </div>

            <div className="space-y-1">
              <Label>Град (за ценови ориентир)</Label>
              <Input value={city} onChange={e => setCity(e.target.value)} placeholder="София" className="bg-background text-sm" data-testid="ew-city" />
            </div>

            <Button onClick={handleAI} disabled={aiLoading || !form.title.trim()} className="w-full bg-violet-600 hover:bg-violet-700" data-testid="ew-ai-btn">
              {aiLoading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Sparkles className="w-4 h-4 mr-2" />}
              AI предложение
            </Button>
          </div>

          {/* Right: AI Proposal */}
          <div className="space-y-3">
            {!proposal ? (
              <div className="h-full flex items-center justify-center text-muted-foreground text-sm p-6 rounded-lg border border-dashed border-border">
                <div className="text-center">
                  <Sparkles className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p>Натиснете "AI предложение" за автоматичен анализ</p>
                </div>
              </div>
            ) : (
              <>
                {/* Recognition */}
                <div className="p-3 rounded-lg bg-violet-500/10 border border-violet-500/30">
                  <div className="flex items-center gap-2 mb-2">
                    <Sparkles className="w-4 h-4 text-violet-400" />
                    <span className="text-xs font-medium text-violet-300">Разпознаване</span>
                    <Badge variant="outline" className="text-[10px] ml-auto">{Math.round(proposal.confidence * 100)}%</Badge>
                    <Badge variant="outline" className={`text-[10px] ${proposal.provider === "llm" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" : "bg-gray-500/10 text-gray-400 border-gray-500/30"}`}>
                      {proposal.provider === "llm" ? "AI (LLM)" : "Rule-based"}
                    </Badge>
                  </div>
                  <p className="text-sm text-foreground">{proposal.recognized.activity_type} / {proposal.recognized.activity_subtype}</p>
                  <p className="text-xs text-muted-foreground">Препоръчана мярка: {UNIT_LABELS[proposal.recognized.suggested_unit] || proposal.recognized.suggested_unit}</p>
                  {proposal.explanation && <p className="text-[10px] text-muted-foreground/70 mt-1 italic">{proposal.explanation}</p>}
                  {proposal.fallback_reason && <p className="text-[10px] text-amber-400 mt-1">{proposal.fallback_reason}</p>}
                </div>

                {/* Pricing */}
                <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
                  <p className="text-xs font-medium text-emerald-300 mb-2">Ценообразуване</p>
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between"><span className="text-muted-foreground">Материал/ед:</span><span className="font-mono">{proposal.pricing.material_price_per_unit.toFixed(2)} лв</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground">Труд/ед:</span><span className="font-mono">{proposal.pricing.labor_price_per_unit.toFixed(2)} лв</span></div>
                    <div className="flex justify-between border-t border-border pt-1"><span className="text-muted-foreground font-medium">Общо/ед:</span><span className="font-mono font-medium text-emerald-400">{proposal.pricing.total_price_per_unit.toFixed(2)} лв</span></div>
                    {proposal.pricing.small_qty_adjustment_percent > 0 && (
                      <div className="text-xs mt-1">
                        <Badge variant="outline" className="text-[10px] bg-amber-500/10 border-amber-500/30 text-amber-400">+{proposal.pricing.small_qty_adjustment_percent}%</Badge>
                        <span className="text-amber-400 ml-1">{proposal.pricing.small_qty_explanation || "корекция за малко количество"}</span>
                      </div>
                    )}
                    {proposal.pricing.city && proposal.pricing.city_factor && (
                      <div className="text-[10px] text-muted-foreground mt-1">
                        Град: {proposal.pricing.city} (коеф. {proposal.pricing.city_factor.toFixed(2)})
                      </div>
                    )}
                    <div className="flex justify-between pt-1"><span className="text-muted-foreground">Прогноза общо:</span><span className="font-mono font-bold text-primary">{proposal.pricing.total_estimated.toFixed(2)} лв</span></div>
                  </div>
                </div>

                {/* Related SMR */}
                <div className="p-3 rounded-lg bg-muted/30 border border-border">
                  <p className="text-xs font-medium text-muted-foreground mb-2">Свързани СМР</p>
                  <div className="flex flex-wrap gap-1">
                    {proposal.related_smr.map((r, i) => <Badge key={i} variant="outline" className="text-[10px]">{r}</Badge>)}
                  </div>
                </div>

                {/* Materials Checklist */}
                <div className="p-3 rounded-lg bg-muted/30 border border-border">
                  <button onClick={() => setShowMaterials(!showMaterials)} className="flex items-center gap-2 w-full text-left">
                    <Package className="w-4 h-4 text-primary" />
                    <span className="text-xs font-medium">Материали ({proposal.materials.length})</span>
                    {showMaterials ? <ChevronDown className="w-3 h-3 ml-auto" /> : <ChevronRight className="w-3 h-3 ml-auto" />}
                  </button>
                  {showMaterials && (
                    <div className="mt-2 space-y-2">
                      {primaryMats.length > 0 && (<div><p className="text-[10px] text-emerald-400 font-medium mb-1">Основни</p>{primaryMats.map((m,i) => <div key={i} className="flex justify-between text-xs text-foreground"><span>{m.name}</span><span className="font-mono text-muted-foreground">{m.estimated_qty} {m.unit}</span></div>)}</div>)}
                      {secondaryMats.length > 0 && (<div><p className="text-[10px] text-amber-400 font-medium mb-1 mt-2">Спомагателни</p>{secondaryMats.map((m,i) => <div key={i} className="flex justify-between text-xs text-foreground"><span>{m.name}</span><span className="font-mono text-muted-foreground">{m.estimated_qty} {m.unit}</span></div>)}</div>)}
                      {consumables.length > 0 && (<div><p className="text-[10px] text-gray-400 font-medium mb-1 mt-2">Консумативи</p>{consumables.map((m,i) => <div key={i} className="flex justify-between text-xs text-foreground"><span>{m.name}</span><span className="font-mono text-muted-foreground">{m.estimated_qty} {m.unit}</span></div>)}</div>)}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button variant="outline" onClick={() => { resetForm(); onOpenChange(false); }}>Затвори</Button>
          <Button variant="outline" onClick={() => handleSaveDraft(false)} disabled={saving || !form.title.trim()} data-testid="ew-save-draft-btn">
            <Plus className="w-4 h-4 mr-1" /> Добави в Draft
          </Button>
          {proposal && (
            <Button onClick={() => handleSaveDraft(true)} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700" data-testid="ew-accept-ai-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <CheckCircle2 className="w-4 h-4 mr-1" />}
              Приеми и добави
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
