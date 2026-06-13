import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Camera, Sparkles, Loader2, Check, MapPin, ArrowLeft, Plus, X, Package } from "lucide-react";

const LOC_TYPES = [
  { key: "warehouse", label: "Склад", endpoint: "/warehouses?page_size=100&active_only=false" },
  { key: "project", label: "Обект", endpoint: "/projects?page_size=100" },
  { key: "employee", label: "Човек", endpoint: "/employees?page_size=200" },
];

export default function AssetsBatchIntakePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState("location"); // location | scan
  const [locType, setLocType] = useState("warehouse");
  const [locOptions, setLocOptions] = useState([]);
  const [locId, setLocId] = useState("");
  const [locName, setLocName] = useState("");
  const [savedCount, setSavedCount] = useState(0);

  // current item being scanned
  const [images, setImages] = useState([]); // [{b64, preview}]
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { suggestion, matched_item }
  const [saving, setSaving] = useState(false);

  const loadLocations = useCallback((type) => {
    const cfg = LOC_TYPES.find((l) => l.key === type);
    API.get(cfg.endpoint).then((r) => {
      const items = r.data?.items || r.data || [];
      setLocOptions(items.map((x) => ({ id: x.id, name: x.name || `${x.first_name || ""} ${x.last_name || ""}`.trim() || x.id })));
    }).catch(() => setLocOptions([]));
  }, []);

  useEffect(() => { loadLocations(locType); setLocId(""); }, [locType, loadLocations]);

  const fileToB64 = (file) => new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",")[1]);
    r.onerror = rej;
    r.readAsDataURL(file);
  });

  const addImage = async (e) => {
    const files = Array.from(e.target.files || []);
    for (const f of files.slice(0, 4 - images.length)) {
      const b64 = await fileToB64(f);
      setImages((prev) => [...prev, { b64, preview: URL.createObjectURL(f) }]);
    }
    e.target.value = "";
  };

  const removeImage = (i) => setImages((prev) => prev.filter((_, idx) => idx !== i));

  const recognize = async () => {
    if (!images.length) { toast.error("Добави поне една снимка"); return; }
    setBusy(true);
    try {
      const res = await API.post("/assets/batch-intake/recognize", { images_base64: images.map((i) => i.b64) });
      setResult(res.data);
      if ((res.data.suggestion?.confidence ?? 0) < 50) toast.warning("AI не е сигурен — провери внимателно");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Разпознаването не успя");
    } finally {
      setBusy(false);
    }
  };

  const editField = (field, value) => setResult((r) => ({ ...r, suggestion: { ...r.suggestion, [field]: value } }));

  const saveAndNext = async () => {
    const s = result.suggestion;
    if (!s.name?.trim()) { toast.error("Името е празно"); return; }
    setSaving(true);
    try {
      // 1) ако типът е нов — създай го
      let typeKey = s.type_key;
      if (!typeKey && s.type_label) {
        const tr = await API.post("/assets/item-types", { label_bg: s.type_label });
        typeKey = tr.data.key;
      }
      if (!typeKey) typeKey = "tool";

      // 2) артикул — съществуващ (групиране) или нов
      let itemId = result.matched_item?.id;
      if (!itemId) {
        const ir = await API.post("/assets/items", {
          name: s.name.trim(), type: typeKey, group: s.group || null,
          brand: s.brand || null, model: s.model || null,
          purchase_price: s.estimated_price_eur ?? null, purchase_currency: "EUR",
          purchase_date: new Date().toISOString().split("T")[0],
          warranty_months: s.warranty_months ?? null, activities: s.activities || [],
        });
        itemId = ir.data.id;
      }

      // 3) актив (бройка) с локация = "къде съм" — QR се генерира от бекенда
      await API.post("/assets/units", {
        item_id: itemId, serial_no: s.serial_no || null,
        location_type: locType, location_id: locId,
      });

      setSavedCount((c) => c + 1);
      toast.success(result.matched_item ? `Добавен към „${s.name}"` : `Създаден „${s.name}"`);
      setImages([]); setResult(null);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Записът не успя");
    } finally {
      setSaving(false);
    }
  };

  // ── STEP 1: избор на локация ──
  if (step === "location") {
    return (
      <div className="p-4 max-w-md mx-auto space-y-4">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/assets/items")} className="w-9 h-9 rounded-xl border border-border bg-card flex items-center justify-center"><ArrowLeft className="w-4 h-4" /></button>
          <h1 className="text-lg font-bold">Прием на партида</h1>
        </div>
        <p className="text-sm text-muted-foreground">Кажи къде се намираш — всичко, което снимаш сега, ще се запише там.</p>
        <div className="flex gap-2">
          {LOC_TYPES.map((l) => (
            <button key={l.key} onClick={() => setLocType(l.key)} className={`flex-1 py-2 rounded-lg text-sm border ${locType === l.key ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground"}`}>{l.label}</button>
          ))}
        </div>
        <div>
          <Label>Избери {LOC_TYPES.find((l) => l.key === locType)?.label.toLowerCase()}</Label>
          <select value={locId} onChange={(e) => { setLocId(e.target.value); setLocName(e.target.options[e.target.selectedIndex].text); }} className="mt-1 w-full h-10 rounded-lg border border-border bg-card px-3 text-sm" data-testid="batch-loc-select">
            <option value="">— избери —</option>
            {locOptions.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </div>
        <Button disabled={!locId} onClick={() => setStep("scan")} className="w-full h-11" data-testid="batch-start">
          <Camera className="w-4 h-4 mr-2" />Почни снимане
        </Button>
      </div>
    );
  }

  // ── STEP 2: серийно снимане ──
  const s = result?.suggestion;
  return (
    <div className="p-4 max-w-md mx-auto space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={() => setStep("location")} className="w-9 h-9 rounded-xl border border-border bg-card flex items-center justify-center"><ArrowLeft className="w-4 h-4" /></button>
        <div className="flex-1">
          <h1 className="text-base font-bold">Снимане</h1>
          <p className="text-xs text-muted-foreground flex items-center gap-1"><MapPin className="w-3 h-3" />{locName} · записани: {savedCount}</p>
        </div>
      </div>

      {!result ? (
        <>
          <div className="grid grid-cols-4 gap-2">
            {images.map((img, i) => (
              <div key={i} className="relative h-20 rounded-lg overflow-hidden border border-border">
                <img src={img.preview} alt="" className="w-full h-full object-cover" />
                <button onClick={() => removeImage(i)} className="absolute top-0.5 right-0.5 w-5 h-5 rounded-full bg-black/60 flex items-center justify-center"><X className="w-3 h-3 text-white" /></button>
              </div>
            ))}
            {images.length < 4 && (
              <label className="h-20 rounded-lg border border-dashed border-border flex flex-col items-center justify-center cursor-pointer bg-muted/30">
                <Camera className="w-5 h-5 text-muted-foreground" />
                <span className="text-[10px] text-muted-foreground mt-0.5">снимка</span>
                <input type="file" accept="image/*" capture="environment" multiple className="hidden" onChange={addImage} data-testid="batch-photo-input" />
              </label>
            )}
          </div>
          <p className="text-xs text-muted-foreground">Няколко кадъра на същата вещ помагат на разпознаването (макс. 4).</p>
          <Button disabled={busy || !images.length} onClick={recognize} className="w-full h-11" data-testid="batch-recognize">
            {busy ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Разпознава…</> : <><Sparkles className="w-4 h-4 mr-2" />Разпознай</>}
          </Button>
        </>
      ) : (
        <div className="space-y-3">
          {result.matched_item ? (
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-2.5 text-xs flex items-center gap-2">
              <Package className="w-4 h-4 text-emerald-400" /><span>Към съществуващ артикул „{result.matched_item.name}" — нова бройка</span>
            </div>
          ) : (
            <div className="rounded-lg border border-blue-500/40 bg-blue-500/10 p-2.5 text-xs">Нов артикул</div>
          )}
          {s.type_is_new && (
            <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-2.5 text-xs text-amber-300">
              <Sparkles className="w-3.5 h-3.5 inline mr-1" />Нов тип „{s.type_label}" — ще се създаде при запис.
            </div>
          )}
          <div>
            <Label className="text-xs">Име</Label>
            <Input value={s.name} onChange={(e) => editField("name", e.target.value)} className="h-9" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div><Label className="text-xs">Марка</Label><Input value={s.brand || ""} onChange={(e) => editField("brand", e.target.value)} className="h-9" /></div>
            <div><Label className="text-xs">Модел</Label><Input value={s.model || ""} onChange={(e) => editField("model", e.target.value)} className="h-9" /></div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div><Label className="text-xs">Тип</Label><Input value={s.type_label || ""} onChange={(e) => editField("type_label", e.target.value)} className="h-9" /></div>
            <div><Label className="text-xs">Сериен №</Label><Input value={s.serial_no || ""} onChange={(e) => editField("serial_no", e.target.value)} className="h-9" /></div>
          </div>
          {s.estimated_price_eur != null && (
            <p className="text-[11px] text-amber-400">Примерна цена: {s.estimated_price_eur} EUR (AI оценка — замени с реалната после).</p>
          )}
          {s.activities?.length > 0 && (
            <div className="flex flex-wrap gap-1">{s.activities.map((a) => <Badge key={a} variant="outline" className="text-[10px]">{a}</Badge>)}</div>
          )}
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => { setResult(null); }} className="flex-1 h-10">Отмени</Button>
            <Button disabled={saving} onClick={saveAndNext} className="flex-1 h-10 bg-emerald-600 hover:bg-emerald-700" data-testid="batch-save-next">
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Check className="w-4 h-4 mr-1" />Запиши + следваща</>}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
