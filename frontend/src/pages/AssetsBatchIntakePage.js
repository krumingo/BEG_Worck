import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Camera, Sparkles, Loader2, Check, MapPin, ArrowLeft, X, Package, Printer, Warehouse, Building2, User, AlertCircle, Tag, Coins, CameraIcon } from "lucide-react";

const LOC_TYPES = [
  { key: "warehouse", label: "Склад", icon: Warehouse },
  { key: "project", label: "Обект", icon: Building2 },
  { key: "employee", label: "Човек", icon: User },
];

// Свиване на снимка през canvas. plate=true → по-висока резолюция за серийния номер.
function compressImage(file, plate) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const maxDim = plate ? 1600 : 1024;       // табелката — по-голяма за четим сериен №
      const quality = plate ? 0.85 : 0.7;
      let { width, height } = img;
      if (width > height && width > maxDim) { height = Math.round(height * maxDim / width); width = maxDim; }
      else if (height > maxDim) { width = Math.round(width * maxDim / height); height = maxDim; }
      const canvas = document.createElement("canvas");
      canvas.width = width; canvas.height = height;
      canvas.getContext("2d").drawImage(img, 0, 0, width, height);
      URL.revokeObjectURL(url);
      const dataUrl = canvas.toDataURL("image/jpeg", quality);
      resolve({ b64: dataUrl.split(",")[1], preview: dataUrl });
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("bad image")); };
    img.src = url;
  });
}

export default function AssetsBatchIntakePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState("location");
  const [locType, setLocType] = useState("warehouse");
  const [locOptions, setLocOptions] = useState([]);
  const [locId, setLocId] = useState("");
  const [locName, setLocName] = useState("");
  const [savedCount, setSavedCount] = useState(0);

  const [images, setImages] = useState([]);     // нормални кадри
  const [plateImg, setPlateImg] = useState(null); // кадър на табелката (висока резолюция)
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState("");
  const [result, setResult] = useState(null);
  const [saving, setSaving] = useState(false);
  const [lastUnit, setLastUnit] = useState(null);
  const [qrSvg, setQrSvg] = useState("");

  const loadLocations = useCallback((type) => {
    API.get(`/assets/intake/locations?type=${type}`).then((r) => {
      const items = r.data?.items || [];
      const roleLabels = { Admin: "Админ", Owner: "Собственик", SiteManager: "Site Manager", Accountant: "Счетоводител", Technician: "Техник", Worker: "Работник", Warehousekeeper: "Складар", Driver: "Шофьор" };
      const mapped = items.map((x) => ({
        id: x.id,
        name: x.name || x.id,
        avatar: x.avatar_url || null,
        role: roleLabels[x.role] || x.role || "",
      }));
      setLocOptions(type === "employee" ? [{ id: "__guest__", name: "Гост (външен)", role: "външен" }, ...mapped] : mapped);
    }).catch(() => setLocOptions([]));
  }, []);

  useEffect(() => { loadLocations(locType); setLocId(""); setLocName(""); }, [locType, loadLocations]);

  const addImages = async (e, isPlate) => {
    const files = Array.from(e.target.files || []);
    try {
      if (isPlate) {
        if (files[0]) setPlateImg(await compressImage(files[0], true));
      } else {
        for (const f of files.slice(0, 4 - images.length)) {
          const c = await compressImage(f, false);
          setImages((prev) => [...prev, c]);
        }
      }
    } catch { toast.error("Проблем със снимката, опитай пак"); }
    e.target.value = "";
  };

  const recognize = async () => {
    const all = [...images.map((i) => i.b64), ...(plateImg ? [plateImg.b64] : [])];
    if (!all.length) { toast.error("Добави поне една снимка"); return; }
    setBusy(true); setErrMsg("");
    // таймаут предпазител — да не виси безкрайно
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60000);
    try {
      const res = await API.post("/assets/batch-intake/recognize", { images_base64: all }, { signal: controller.signal });
      setResult(res.data);
      if ((res.data.suggestion?.confidence ?? 0) < 50) toast.warning("AI не е сигурен — провери внимателно");
    } catch (err) {
      const msg = err.name === "CanceledError" || err.name === "AbortError"
        ? "AI се забави над минута — опитай с по-малко или по-малки снимки"
        : (err.response?.data?.detail || err.message || "Разпознаването не успя");
      setErrMsg(msg);
      toast.error(msg);
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  };

  const editField = (field, value) => setResult((r) => ({ ...r, suggestion: { ...r.suggestion, [field]: value } }));

  const saveAndNext = async () => {
    const s = result.suggestion;
    if (!s.name?.trim()) { toast.error("Името е празно"); return; }
    setSaving(true);
    try {
      // Заскладяването НЕ влиза директно в склада — подава се за одобрение
      await API.post("/assets/intake/submit", {
        location_type: locType,
        location_id: locId === "__guest__" ? null : locId,
        location_name: locName,
        suggestion: {
          name: s.name.trim(), type_label: s.type_label || null, type_key: s.type_key || null,
          group: s.group || null, brand: s.brand || null, model: s.model || null,
          article_no: s.article_no || null,
          serial_no: s.serial_no || null, estimated_price_eur: s.estimated_price_eur ?? null,
          warranty_months: s.warranty_months ?? null, activities: s.activities || [],
        },
        matched_item_id: result.matched_item?.id || null,
        photo_b64: images[0]?.b64 || plateImg?.b64 || null,
      });
      setSavedCount((c) => c + 1);
      toast.success("Изпратено за одобрение");
      setImages([]); setPlateImg(null); setResult(null);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Записът не успя");
    } finally {
      setSaving(false);
    }
  };

  // ── STEP 1: локация ──
  if (step === "location") {
    const cfg = LOC_TYPES.find((l) => l.key === locType);
    return (
      <div className="p-4 max-w-md mx-auto space-y-5">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="w-10 h-10 rounded-xl border border-border bg-card flex items-center justify-center"><ArrowLeft className="w-5 h-5" /></button>
          <h1 className="text-xl font-bold">Заскладяване</h1>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">Кажи къде се намираш. Всичко, което снимаш сега, ще се запише на това място.</p>
        <div className="grid grid-cols-3 gap-2">
          {LOC_TYPES.map((l) => (
            <button key={l.key} onClick={() => setLocType(l.key)} className={`py-3 rounded-xl text-sm border flex flex-col items-center gap-1.5 transition-all ${locType === l.key ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground"}`}>
              <l.icon className="w-5 h-5" />{l.label}
            </button>
          ))}
        </div>
        <div>
          <Label className="text-sm">Избери {cfg?.label.toLowerCase()}</Label>
          {locType === "employee" ? (
            <div className="mt-1.5 max-h-72 overflow-y-auto rounded-xl border border-border divide-y divide-border" data-testid="batch-people-list">
              {locOptions.map((o) => (
                <button key={o.id} onClick={() => { setLocId(o.id); setLocName(o.name); }} className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors ${locId === o.id ? "bg-primary/10" : "hover:bg-muted/40"}`}>
                  {o.avatar ? <img src={o.avatar} alt="" className="w-9 h-9 rounded-full object-cover shrink-0" /> : <div className="w-9 h-9 rounded-full bg-muted flex items-center justify-center text-xs font-medium shrink-0">{o.name.slice(0, 2).toUpperCase()}</div>}
                  <div className="flex-1 min-w-0"><p className="text-sm font-medium truncate">{o.name}</p>{o.role && <p className="text-[11px] text-muted-foreground">{o.role}</p>}</div>
                  {locId === o.id && <Check className="w-4 h-4 text-primary shrink-0" />}
                </button>
              ))}
            </div>
          ) : (
            <select value={locId} onChange={(e) => { setLocId(e.target.value); setLocName(e.target.options[e.target.selectedIndex].text); }} className="mt-1.5 w-full h-12 rounded-xl border border-border bg-card px-3 text-base" data-testid="batch-loc-select">
              <option value="">— избери —</option>
              {locOptions.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
        </div>
        <Button disabled={!locId} onClick={() => setStep("scan")} className="w-full h-12 text-base" data-testid="batch-start">
          <Camera className="w-5 h-5 mr-2" />Почни снимане
        </Button>
      </div>
    );
  }

  // ── STEP 2: снимане ──
  const s = result?.suggestion;
  const locCfg = LOC_TYPES.find((l) => l.key === locType);
  return (
    <div className="max-w-md mx-auto">
      <style>{`@media print { body * { visibility: hidden; } #qr-print, #qr-print * { visibility: visible !important; } #qr-print { position: absolute; left: 0; top: 0; width: 100%; } .qr-svg svg { width: 100%; height: 100%; } }`}</style>

      {/* Голяма, четима лента с локацията */}
      <div className="sticky top-0 z-10 bg-background border-b border-border px-4 py-3 flex items-center gap-3">
        <button onClick={() => setStep("location")} className="w-10 h-10 rounded-xl border border-border bg-card flex items-center justify-center shrink-0"><ArrowLeft className="w-5 h-5" /></button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 text-primary">
            <MapPin className="w-4 h-4 shrink-0" />
            <span className="font-bold text-base truncate">{locName}</span>
          </div>
          <p className="text-xs text-muted-foreground">{locCfg?.label} · записани: {savedCount}</p>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {!result ? (
          <>
            <div>
              <p className="text-base font-semibold">Снимки на вещта</p>
              <p className="text-sm text-muted-foreground mb-3">Няколко кадъра помагат на разпознаването (макс. 4).</p>
              <div className="grid grid-cols-4 gap-2">
                {images.map((img, i) => (
                  <div key={i} className="relative aspect-square rounded-lg overflow-hidden border border-border">
                    <img src={img.preview} alt="" className="w-full h-full object-cover" />
                    <button onClick={() => setImages((p) => p.filter((_, idx) => idx !== i))} className="absolute top-1 right-1 w-6 h-6 rounded-full bg-black/60 flex items-center justify-center"><X className="w-3.5 h-3.5 text-white" /></button>
                  </div>
                ))}
                {images.length < 4 && (
                  <label className="aspect-square rounded-lg border border-dashed border-muted-foreground/40 flex flex-col items-center justify-center cursor-pointer bg-muted/30 gap-1">
                    <Camera className="w-6 h-6 text-primary" />
                    <span className="text-[10px] text-muted-foreground">снимка</span>
                    <input type="file" accept="image/*" capture="environment" multiple className="hidden" onChange={(e) => addImages(e, false)} data-testid="batch-photo-input" />
                  </label>
                )}
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-1">
                <Tag className="w-4 h-4 text-primary" />
                <p className="text-base font-semibold">Табелка със серийния номер</p>
              </div>
              <p className="text-sm text-muted-foreground mb-2 pl-6">По желание — снима се в по-високо качество за четим номер.</p>
              <label className="flex items-center justify-center gap-2 h-24 rounded-lg border border-dashed border-muted-foreground/40 cursor-pointer bg-muted/30 overflow-hidden">
                {plateImg ? <img src={plateImg.preview} alt="" className="h-full object-contain" /> : <><Camera className="w-5 h-5 text-primary" /><span className="text-sm text-muted-foreground">снимай табелка</span></>}
                <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => addImages(e, true)} data-testid="batch-plate-input" />
              </label>
            </div>

            {errMsg && (
              <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-3 flex items-start gap-2 text-xs text-red-300">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /><span>{errMsg}</span>
              </div>
            )}

            <Button disabled={busy || (!images.length && !plateImg)} onClick={recognize} className="w-full h-14 text-lg" data-testid="batch-recognize">
              {busy ? <><Loader2 className="w-5 h-5 mr-2 animate-spin" />Разпознава…</> : <><Sparkles className="w-5 h-5 mr-2" />Разпознай</>}
            </Button>
          </>
        ) : (
          <div className="space-y-3">
            {result.matched_item ? (
              <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm flex items-center gap-2">
                <Package className="w-4 h-4 text-emerald-400" /><span>Към съществуващ „{result.matched_item.name}" — нова бройка</span>
              </div>
            ) : (
              <div className="rounded-xl border border-blue-500/40 bg-blue-500/10 p-3 text-sm">Нов артикул</div>
            )}
            {s.type_is_new && (
              <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-300">
                <Sparkles className="w-4 h-4 inline mr-1" />Нов тип „{s.type_label}" — ще се създаде при запис.
              </div>
            )}
            <div><Label className="text-sm text-muted-foreground">Име</Label><Input value={s.name} onChange={(e) => editField("name", e.target.value)} className="h-12 text-base mt-1" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label className="text-sm text-muted-foreground">Марка</Label><Input value={s.brand || ""} onChange={(e) => editField("brand", e.target.value)} className="h-12 text-base mt-1" /></div>
              <div><Label className="text-sm text-muted-foreground">Модел</Label><Input value={s.model || ""} onChange={(e) => editField("model", e.target.value)} className="h-12 text-base mt-1" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label className="text-sm text-muted-foreground">Артикулен №</Label><Input value={s.article_no || ""} onChange={(e) => editField("article_no", e.target.value)} className="h-12 text-base mt-1" /></div>
              <div><Label className="text-sm text-muted-foreground">Сериен №</Label><Input value={s.serial_no || ""} onChange={(e) => editField("serial_no", e.target.value)} className="h-12 text-base mt-1" /></div>
            </div>
            <div><Label className="text-sm text-muted-foreground">Тип</Label><Input value={s.type_label || ""} onChange={(e) => editField("type_label", e.target.value)} className="h-12 text-base mt-1" /></div>
            {s.estimated_price_eur != null && (
              <div className="flex items-center gap-2 rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2.5">
                <Coins className="w-5 h-5 text-amber-400 shrink-0" />
                <span className="text-sm text-amber-300">Примерна цена: <b>{s.estimated_price_eur} EUR</b> · замени с реалната</span>
              </div>
            )}
            {s.activities?.length > 0 && (
              <div>
                <Label className="text-sm text-muted-foreground">Дейности</Label>
                <div className="flex flex-wrap gap-2 mt-1.5">{s.activities.map((a) => <Badge key={a} variant="outline" className="text-xs py-1 px-2.5">{a}</Badge>)}</div>
              </div>
            )}
            <div className="flex gap-3 pt-2">
              <Button variant="outline" onClick={() => setResult(null)} className="flex-1 h-12 text-base">Отмени</Button>
              <Button disabled={saving} onClick={saveAndNext} className="flex-1 h-12 text-base bg-emerald-600 hover:bg-emerald-700" data-testid="batch-save-next">
                {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <><Check className="w-5 h-5 mr-1.5" />Запиши</>}
              </Button>
            </div>
          </div>
        )}

        {savedCount > 0 && !result && (
          <div className="rounded-xl border border-blue-500/40 bg-blue-500/5 p-3 text-sm text-blue-300" data-testid="submitted-info">
            Изпратени за одобрение: {savedCount}. Админ ще ги прегледа преди да влязат в склада.
          </div>
        )}
      </div>
    </div>
  );
}
