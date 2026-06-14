import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import DataTable from "@/components/DataTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Plus, Pencil, Trash2, Wrench, Camera, Sparkles, Loader2, MapPin, Calendar, User, History, Package } from "lucide-react";
import { toast } from "sonner";

const TYPE_OPTIONS = [
  { value: "machine", label: "Машина" },
  { value: "tool", label: "Инструмент" },
];

const EMPTY = {
  name: "", type: "tool", group: "", brand: "", model: "", article_no: "",
  unit: "бр", purchase_price: "", purchase_currency: "EUR", purchase_date: "",
  warranty_months: "", activities: "",
};

export default function AssetsItemsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [unitsItem, setUnitsItem] = useState(null);
  const [units, setUnits] = useState([]);
  const [unitsLoading, setUnitsLoading] = useState(false);
  const [moveHist, setMoveHist] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [deleteItem, setDeleteItem] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiImage, setAiImage] = useState(null);        // { b64, preview }
  const [aiPlate, setAiPlate] = useState(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiConsumables, setAiConsumables] = useState([]); // само показване (Пакет 2 ги записва)
  const [aiPriceIsEstimate, setAiPriceIsEstimate] = useState(false);

  const fileToB64 = (file) => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1]);
    r.onerror = reject;
    r.readAsDataURL(file);
  });

  const pickImage = async (e, setter) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const b64 = await fileToB64(f);
    setter({ b64, preview: URL.createObjectURL(f) });
  };

  const runRecognition = async () => {
    if (!aiImage) { toast.error("Първо снимай или качи снимка"); return; }
    setAiBusy(true);
    try {
      const res = await API.post("/assets/ai-intake", {
        image_base64: aiImage.b64,
        plate_image_base64: aiPlate?.b64 || null,
      });
      const d = res.data;
      const today = new Date().toISOString().split("T")[0];
      setForm({
        name: d.name || "", type: d.type || "tool", group: d.group || "",
        brand: d.brand || "", model: d.model || "", article_no: d.serial_no || "",
        unit: "бр",
        purchase_price: d.estimated_price_eur ?? "",
        purchase_currency: "EUR", purchase_date: today,
        warranty_months: d.warranty_months ?? "",
        activities: (d.activities || []).join(", "),
      });
      setAiPriceIsEstimate(d.estimated_price_eur != null);
      setAiConsumables(d.consumables || []);
      setEditingId(null);
      setAiOpen(false);
      setModalOpen(true);
      if ((d.confidence ?? 0) < 50) toast.warning("AI не е сигурен — провери полетата внимателно");
      else toast.success("Разпознато — провери и запиши");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Разпознаването не успя, опитай пак");
    } finally {
      setAiBusy(false);
    }
  };

  const fetchData = useCallback(async (params) => {
    const q = new URLSearchParams();
    q.append("page", params.page);
    q.append("page_size", params.page_size);
    if (params.sort_by) q.append("sort_by", params.sort_by);
    if (params.sort_dir) q.append("sort_dir", params.sort_dir);
    if (params.search) q.append("search", params.search);
    if (params.filters) q.append("filters", params.filters);
    const res = await API.get(`/assets/items?${q.toString()}`);
    return res.data;
  }, []);

  const openCreate = () => { setEditingId(null); setForm(EMPTY); setAiConsumables([]); setAiPriceIsEstimate(false); setModalOpen(true); };

  const openEdit = (row) => {
    setEditingId(row.id);
    setForm({
      name: row.name || "", type: row.type || "tool", group: row.group || "",
      brand: row.brand || "", model: row.model || "", article_no: row.article_no || "",
      unit: row.unit || "бр", purchase_price: row.purchase_price ?? "",
      purchase_currency: row.purchase_currency || "EUR", purchase_date: row.purchase_date || "",
      warranty_months: row.warranty_months ?? "", activities: (row.activities || []).join(", "),
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) { toast.error("Въведете наименование"); return; }
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        type: form.type,
        group: form.group.trim() || null,
        brand: form.brand.trim() || null,
        model: form.model.trim() || null,
        article_no: form.article_no.trim() || null,
        unit: form.unit.trim() || "бр",
        purchase_price: form.purchase_price === "" ? null : Number(form.purchase_price),
        purchase_currency: form.purchase_currency,
        purchase_date: form.purchase_date || null,
        warranty_months: form.warranty_months === "" ? null : Number(form.warranty_months),
        activities: form.activities.split(",").map((s) => s.trim()).filter(Boolean),
      };
      if (editingId) {
        await API.put(`/assets/items/${editingId}`, payload);
        toast.success("Артикулът е обновен");
      } else {
        await API.post("/assets/items", payload);
        toast.success("Артикулът е създаден");
      }
      setModalOpen(false);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    try {
      await API.delete(`/assets/items/${deleteItem.id}`);
      toast.success("Изтрито");
      setDeleteItem(null);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    }
  };

  const openUnits = async (item) => {
    setUnitsItem(item); setUnits([]); setUnitsLoading(true);
    try {
      const r = await API.get(`/assets/units?item_id=${item.id}&page_size=200`);
      setUnits(r.data?.items || []);
    } catch { setUnits([]); }
    finally { setUnitsLoading(false); }
  };

  const openHistory = async (unit) => {
    setMoveHist({ unit, items: null });
    try {
      const r = await API.get(`/assets/units/${unit.id}/movements`);
      setMoveHist({ unit, items: r.data?.items || [] });
    } catch { setMoveHist({ unit, items: [] }); }
  };

  const ACTION_LABELS = { take: "Взет", handover: "Предаден", drop: "Оставен", repair: "В ремонт", return: "Върнат", intake: "Заприходен" };
  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("bg-BG") : "—";

  const columns = [

    {
      key: "photo_url", label: "", width: "56px", sortable: false,
      render: (v) => (
        <div className="w-9 h-9 rounded bg-muted flex items-center justify-center text-muted-foreground overflow-hidden">
          {v ? <img src={v} alt="" className="w-full h-full object-cover" /> : <Wrench className="w-4 h-4" />}
        </div>
      ),
    },
    {
      key: "name", label: "Наименование", sortable: true, filterable: true, filterType: "contains",
      render: (v, row) => (
        <div>
          <div className="font-medium">{v}</div>
          {(row.brand || row.model) && (
            <div className="text-xs text-muted-foreground">
              {[row.brand, row.model].filter(Boolean).join(" · ")}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "type", label: "Тип", width: "110px", sortable: true, filterable: true, filterType: "in",
      options: TYPE_OPTIONS,
      render: (v) => <Badge variant="outline">{v === "machine" ? "Машина" : "Инструмент"}</Badge>,
    },
    { key: "group", label: "Група", filterable: true, filterType: "contains" },
    { key: "unit", label: "Ед.", width: "70px", sortable: false },
    {
      key: "asset_count", label: "Активи", width: "90px", sortable: false,
      render: (v) => <Badge variant="secondary">{v || 0}</Badge>,
    },
  ];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" data-testid="asset-items-title">Артикули</h1>
          <p className="text-sm text-muted-foreground">Обща номенклатура</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate("/assets/batch-intake")} data-testid="batch-intake-btn">
            <Camera className="w-4 h-4 mr-2" /> Прием на партида
          </Button>
          <Button variant="outline" onClick={() => { setAiImage(null); setAiPlate(null); setAiOpen(true); }} data-testid="ai-intake-btn">
            <Camera className="w-4 h-4 mr-2" /> Със снимка
          </Button>
          <Button onClick={openCreate} data-testid="create-asset-item-btn">
            <Plus className="w-4 h-4 mr-2" /> Нов артикул
          </Button>
        </div>
      </div>

      <DataTable
        columns={columns}
        fetchData={fetchData}
        refreshKey={refreshKey}
        onRowClick={openUnits}
        exportFilename="asset-items.csv"
        actions={(row) => (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={() => openEdit(row)} data-testid={`edit-${row.id}`}>
              <Pencil className="w-4 h-4" />
            </Button>
            <Button variant="ghost" size="icon" onClick={() => setDeleteItem(row)} data-testid={`delete-${row.id}`}>
              <Trash2 className="w-4 h-4 text-destructive" />
            </Button>
          </div>
        )}
      />

      {/* Create / Edit */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingId ? "Редактирай артикул" : "Нов артикул"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Наименование *</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="ai-name" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Тип *</Label>
                <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {TYPE_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Мерна единица</Label>
                <Input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Група</Label><Input value={form.group} onChange={(e) => setForm({ ...form, group: e.target.value })} /></div>
              <div><Label>Артикулен №</Label><Input value={form.article_no} onChange={(e) => setForm({ ...form, article_no: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Марка</Label><Input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} /></div>
              <div><Label>Модел</Label><Input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Покупна цена</Label>
                <div className="flex gap-2">
                  <Input type="number" step="0.01" value={form.purchase_price} onChange={(e) => setForm({ ...form, purchase_price: e.target.value })} />
                  <Select value={form.purchase_currency} onValueChange={(v) => setForm({ ...form, purchase_currency: v })}>
                    <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="EUR">EUR</SelectItem>
                      <SelectItem value="BGN">BGN</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div><Label>Дата на закупуване</Label><Input type="date" value={form.purchase_date} onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Гаранция (месеци)</Label><Input type="number" value={form.warranty_months} onChange={(e) => setForm({ ...form, warranty_months: e.target.value })} /></div>
            </div>
            <div>
              <Label>Дейности (със запетая)</Label>
              <Input value={form.activities} onChange={(e) => setForm({ ...form, activities: e.target.value })} placeholder="Замазка, Бетон, Боя" />
            </div>
          </div>
          {aiPriceIsEstimate && form.purchase_price !== "" && (
            <p className="text-[11px] text-amber-400 -mt-1">Цената е примерна (AI оценка за нова) — замени я с реалната при покупка.</p>
          )}
          {aiConsumables.length > 0 && (
            <div className="rounded-lg border border-border bg-muted/40 p-3 mt-1">
              <p className="text-xs font-semibold mb-1.5 flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-amber-400" />Препоръчани консумативи</p>
              <div className="flex flex-wrap gap-1.5">
                {aiConsumables.map((c) => <Badge key={c} variant="outline" className="text-[11px]">{c}</Badge>)}
              </div>
              <p className="text-[10px] text-muted-foreground mt-1.5">Записването им в склада идва с Пакет 2.</p>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setModalOpen(false)}>Отказ</Button>
            <Button onClick={handleSave} disabled={saving} data-testid="ai-save">{saving ? "Запазва…" : "Запази"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* AI прием със снимка */}
      <Dialog open={aiOpen} onOpenChange={setAiOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Добави със снимка</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Снимка на машината *</Label>
              <label className="mt-1 flex flex-col items-center justify-center gap-2 border border-dashed border-border rounded-xl h-36 cursor-pointer overflow-hidden bg-muted/30">
                {aiImage ? <img src={aiImage.preview} alt="" className="w-full h-full object-contain" /> : (<><Camera className="w-7 h-7 text-muted-foreground" /><span className="text-xs text-muted-foreground">Снимай или избери файл</span></>)}
                <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => pickImage(e, setAiImage)} data-testid="ai-photo-input" />
              </label>
            </div>
            <div>
              <Label>Табелка със серийния номер (по желание)</Label>
              <label className="mt-1 flex flex-col items-center justify-center gap-2 border border-dashed border-border rounded-xl h-24 cursor-pointer overflow-hidden bg-muted/30">
                {aiPlate ? <img src={aiPlate.preview} alt="" className="w-full h-full object-contain" /> : (<><Camera className="w-5 h-5 text-muted-foreground" /><span className="text-xs text-muted-foreground">Снимай табелката</span></>)}
                <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => pickImage(e, setAiPlate)} data-testid="ai-plate-input" />
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAiOpen(false)}>Отказ</Button>
            <Button onClick={runRecognition} disabled={aiBusy || !aiImage} data-testid="ai-recognize-btn">
              {aiBusy ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Разпознава…</> : <><Sparkles className="w-4 h-4 mr-2" />Разпознай</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete */}
      <AlertDialog open={!!deleteItem} onOpenChange={(o) => !o && setDeleteItem(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Изтриване</AlertDialogTitle>
            <AlertDialogDescription>Да изтрия ли „{deleteItem?.name}"?</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отказ</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} className="bg-destructive text-destructive-foreground">Изтрий</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Бройки на артикула — къде, кога, кой */}
      <Dialog open={!!unitsItem} onOpenChange={(o) => !o && setUnitsItem(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Package className="w-5 h-5" />{unitsItem?.name} — бройки</DialogTitle>
          </DialogHeader>
          {unitsLoading ? (
            <div className="flex justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>
          ) : units.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">Няма заведени бройки.</p>
          ) : (
            <div className="space-y-2">
              {units.map((u) => (
                <div key={u.id} className="rounded-lg border border-border p-3 flex items-center gap-3 flex-wrap" data-testid={`unit-${u.id}`}>
                  <span className="font-mono text-xs text-muted-foreground">{u.qr_id || u.serial_no || "—"}</span>
                  <span className="inline-flex items-center gap-1 text-sm"><MapPin className="w-4 h-4 text-primary" />{u.location_name || "—"}</span>
                  <span className="inline-flex items-center gap-1 text-sm text-muted-foreground"><Calendar className="w-4 h-4" />{fmtDate(u.created_at)}</span>
                  <span className="inline-flex items-center gap-1 text-sm text-muted-foreground"><User className="w-4 h-4" />{u.created_by_name || "—"}</span>
                  <Button variant="outline" size="sm" className="ml-auto" onClick={() => openHistory(u)} data-testid={`hist-${u.id}`}>
                    <History className="w-4 h-4 mr-1" />История
                  </Button>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* История на движенията */}
      <Dialog open={!!moveHist} onOpenChange={(o) => !o && setMoveHist(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><History className="w-5 h-5" />История на движенията</DialogTitle>
          </DialogHeader>
          {moveHist?.items === null ? (
            <div className="flex justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>
          ) : (moveHist?.items || []).length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">Няма движения.</p>
          ) : (
            <div className="space-y-2">
              {moveHist.items.map((m, i) => (
                <div key={i} className="rounded-lg border border-border p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <Badge variant="outline">{ACTION_LABELS[m.action] || m.action}</Badge>
                    <span className="text-xs text-muted-foreground">{fmtDate(m.at)}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {m.from_name ? `от ${m.from_name} ` : ""}{m.to_name ? `→ ${m.to_name}` : ""}
                  </p>
                  <p className="text-xs text-muted-foreground">{m.by_name}</p>
                  {m.note && <p className="text-xs mt-1">{m.note}</p>}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
