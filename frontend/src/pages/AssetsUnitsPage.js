import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
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
import { Plus, Search, Loader2, Trash2, MapPin, Calendar, User, History, LayoutGrid, List, ShieldCheck, Pencil, X, Wrench, CheckCircle2 } from "lucide-react";
import { warrantyStatus } from "@/lib/warranty";
import UnitQrBlock from "@/components/UnitQrBlock";
import { toast } from "sonner";

const STATUS = {
  available: { label: "наличен", color: "#16a34a" },
  in_use: { label: "зает", color: "#d97706" },
  repair: { label: "в ремонт", color: "#2563eb" },
  written_off: { label: "бракуван", color: "#9ca3af" },
};

const EMPTY = {
  item_id: "", serial_no: "", inventory_no: "", status: "available",
  location_id: "", notes: "",
  purchase_date: "", warranty_months: "", purchase_price: "",
};

export default function AssetsUnitsPage() {
  const { t } = useTranslation();
  const [units, setUnits] = useState([]);
  const [items, setItems] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fType, setFType] = useState("");
  const [fLoc, setFLoc] = useState("");
  const [fWho, setFWho] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editingName, setEditingName] = useState("");
  const [editingQr, setEditingQr] = useState("");
  const [view, setView] = useState("table"); // table | board
  const [moveHist, setMoveHist] = useState(null);
  const [repairSend, setRepairSend] = useState(null);   // { unit } | null
  const [repairReturn, setRepairReturn] = useState(null); // { unit } | null
  const [rForm, setRForm] = useState({ sent_by_name: "", service: "", issue: "", returned_by_name: "", cost: "", work_done: "", is_warranty: false });
  const [rSaving, setRSaving] = useState(false);
  const [employees, setEmployees] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const emp = await API.get("/employees");
      setEmployees(Array.isArray(emp.data) ? emp.data : (emp.data?.items || []));
    } catch { /* списъкът със служители е по желание */ }
    try {
      const [u, it, wh] = await Promise.all([
        API.get("/assets/units?page_size=300"),
        API.get("/assets/items?page_size=100"),
        API.get("/warehouses?page_size=100&active_only=false"),
      ]);
      setUnits(u.data.items || []);
      setItems(it.data.items || []);
      setWarehouses(wh.data.items || []);
    } catch (e) {
      toast.error("Грешка при зареждане");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const counts = units.reduce((a, u) => { a[u.status] = (a[u.status] || 0) + 1; return a; }, {});

  const q = search.trim().toLowerCase();
  const filtered = units.filter((u) => {
    if (q && !(
      (u.item_name || "").toLowerCase().includes(q) ||
      (u.qr_id || "").toLowerCase().includes(q) ||
      (u.serial_no || "").toLowerCase().includes(q) ||
      (u.inventory_no || "").toLowerCase().includes(q)
    )) return false;
    if (fStatus && u.status !== fStatus) return false;
    if (fType && (u.item_type || "") !== fType) return false;
    if (fLoc && (u.location_name || "Без място") !== fLoc) return false;
    if (fWho && (u.created_by_name || "") !== fWho) return false;
    return true;
  });

  // опции за филтрите — само реално срещаните стойности
  const locOptions = [...new Set(units.map((u) => u.location_name || "Без място"))].sort();
  const whoOptions = [...new Set(units.map((u) => u.created_by_name).filter(Boolean))].sort();
  const activeFilters = [
    fStatus && { key: "status", label: `Статус: ${(STATUS[fStatus] || {}).label || fStatus}`, clear: () => setFStatus("") },
    fType && { key: "type", label: `Тип: ${fType === "machine" ? "Машина" : "Инструмент"}`, clear: () => setFType("") },
    fLoc && { key: "loc", label: `Къде: ${fLoc}`, clear: () => setFLoc("") },
    fWho && { key: "who", label: `Кой: ${fWho}`, clear: () => setFWho("") },
  ].filter(Boolean);
  const clearAll = () => { setFStatus(""); setFType(""); setFLoc(""); setFWho(""); };

  const groups = {};
  filtered.forEach((u) => {
    const key = u.status === "repair" ? "Ремонт" : (u.location_name || "Без място");
    (groups[key] = groups[key] || []).push(u);
  });
  const groupKeys = Object.keys(groups).sort((a, b) =>
    a === "Ремонт" ? 1 : b === "Ремонт" ? -1 : a.localeCompare(b, "bg"));

  const openCreate = () => { setEditingId(null); setEditingName(""); setEditingQr(""); setForm(EMPTY); setModalOpen(true); };

  const openEdit = (u) => {
    setEditingId(u.id);
    setEditingName(u.item_name || "");
    setEditingQr(u.qr_id || "");
    setForm({
      item_id: u.item_id || "",
      serial_no: u.serial_no || "",
      inventory_no: u.inventory_no || "",
      status: u.status || "available",
      location_id: u.location_type === "warehouse" ? (u.location_id || "") : "",
      notes: u.notes || "",
      purchase_date: u.purchase_date || "",
      warranty_months: u.warranty_months ?? "",
      purchase_price: u.purchase_price ?? "",
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!editingId && !form.item_id) { toast.error("Изберете артикул"); return; }
    setSaving(true);
    try {
      const base = {
        serial_no: form.serial_no.trim() || null,
        inventory_no: form.inventory_no.trim() || null,
        status: form.status,
        location_type: form.location_id ? "warehouse" : null,
        location_id: form.location_id || null,
        notes: form.notes.trim() || null,
        purchase_date: form.purchase_date || null,
        warranty_months: form.warranty_months === "" ? null : Number(form.warranty_months),
        purchase_price: form.purchase_price === "" ? null : Number(form.purchase_price),
      };
      if (editingId) {
        await API.put(`/assets/units/${editingId}`, base);
        toast.success("Записано");
      } else {
        await API.post("/assets/units", { item_id: form.item_id, ...base });
        toast.success("Активът е създаден (с QR)");
      }
      setModalOpen(false);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!editingId) return;
    try {
      await API.delete(`/assets/units/${editingId}`);
      toast.success("Изтрито");
      setModalOpen(false);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    }
  };

  const ACTION_LABELS = { take: "Взет", handover: "Предаден", drop: "Оставен", repair: "В ремонт", return: "Върнат", intake: "Заприходен" };
  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("bg-BG") : "—";
  const daysSince = (iso) => {
    if (!iso) return "";
    const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    return d <= 0 ? " · днес" : ` · преди ${d} ${d === 1 ? "ден" : "дни"}`;
  };
  const openHistory = async (unit) => {
    setMoveHist({ unit, items: null, repairs: null, totalPaid: 0 });
    try {
      const r = await API.get(`/assets/units/${unit.id}/movements`);
      setMoveHist((prev) => ({ ...prev, unit, items: r.data?.items || [] }));
    } catch { setMoveHist((prev) => ({ ...prev, unit, items: [] })); }
    try {
      const rp = await API.get(`/assets/units/${unit.id}/repairs`);
      setMoveHist((prev) => ({ ...prev, repairs: rp.data?.items || [], totalPaid: rp.data?.total_paid || 0 }));
    } catch { setMoveHist((prev) => ({ ...prev, repairs: [] })); }
  };

  const openRepairSend = (unit) => {
    setRForm({ sent_by_name: "", service: "", issue: "", returned_by_name: "", cost: "", work_done: "", is_warranty: false });
    setRepairSend({ unit });
  };
  const openRepairReturn = async (unit) => {
    const w = warrantyStatus(unit.purchase_date, unit.warranty_months);
    setRForm({ sent_by_name: "", service: "", issue: "", returned_by_name: "", cost: "", work_done: "", is_warranty: w.inWarranty });
    setRepairReturn({ unit, open: null });
    try {
      const r = await API.get(`/assets/units/${unit.id}/repairs`);
      setRepairReturn({ unit, open: r.data?.open || null });
    } catch { /* данните от изпращането са по желание */ }
  };
  const submitRepairSend = async () => {
    if (!repairSend) return;
    setRSaving(true);
    try {
      await API.post(`/assets/units/${repairSend.unit.id}/repair/send`, {
        sent_by_name: rForm.sent_by_name || null,
        service: rForm.service || null,
        issue: rForm.issue || null,
      });
      setRepairSend(null);
      load();
    } catch (e) {
      alert(e?.response?.data?.detail || "Грешка при изпращане на ремонт");
    } finally { setRSaving(false); }
  };
  const submitRepairReturn = async () => {
    if (!repairReturn) return;
    setRSaving(true);
    try {
      await API.post(`/assets/units/${repairReturn.unit.id}/repair/return`, {
        returned_by_name: rForm.returned_by_name || null,
        cost: rForm.cost === "" ? null : Number(rForm.cost),
        work_done: rForm.work_done || null,
        is_warranty: rForm.is_warranty,
      });
      setRepairReturn(null);
      load();
    } catch (e) {
      alert(e?.response?.data?.detail || "Грешка при връщане от ремонт");
    } finally { setRSaving(false); }
  };

  const Dot = ({ status }) => (
    <span style={{ color: (STATUS[status] || {}).color || "#9ca3af" }}>●</span>
  );

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" data-testid="asset-units-title">Активи</h1>
          <p className="text-sm text-muted-foreground">Инструменти и машини с QR — къде е всичко</p>
        </div>
        <Button onClick={openCreate} data-testid="create-asset-unit-btn">
          <Plus className="w-4 h-4 mr-2" /> Нов актив
        </Button>
      </div>

      {/* status summary */}
      <div className="flex flex-wrap gap-2">
        <span className="text-xs px-3 py-1.5 rounded-full bg-muted"><b>{units.length}</b> общо</span>
        {Object.entries(STATUS).map(([k, s]) => (
          <span key={k} className="text-xs px-3 py-1.5 rounded-full bg-muted">
            <Dot status={k} /> <b>{counts[k] || 0}</b> {s.label}
          </span>
        ))}
      </div>

      {/* search */}
      <div className="relative max-w-md">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input className="pl-9" placeholder="Търси по QR код, сериен номер или име…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {/* филтри */}
      <div className="flex flex-wrap gap-2 items-center">
        <Select value={fStatus || "all"} onValueChange={(v) => setFStatus(v === "all" ? "" : v)}>
          <SelectTrigger className="w-auto h-9 text-sm" data-testid="filter-status"><SelectValue placeholder="Статус" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Статус: всички</SelectItem>
            {Object.entries(STATUS).map(([k, st]) => <SelectItem key={k} value={k}>{st.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={fType || "all"} onValueChange={(v) => setFType(v === "all" ? "" : v)}>
          <SelectTrigger className="w-auto h-9 text-sm" data-testid="filter-type"><SelectValue placeholder="Тип" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Тип: всички</SelectItem>
            <SelectItem value="machine">Машина</SelectItem>
            <SelectItem value="tool">Инструмент</SelectItem>
          </SelectContent>
        </Select>
        <Select value={fLoc || "all"} onValueChange={(v) => setFLoc(v === "all" ? "" : v)}>
          <SelectTrigger className="w-auto h-9 text-sm" data-testid="filter-loc"><SelectValue placeholder="Къде" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Къде: всички</SelectItem>
            {locOptions.map((l) => <SelectItem key={l} value={l}>{l}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={fWho || "all"} onValueChange={(v) => setFWho(v === "all" ? "" : v)}>
          <SelectTrigger className="w-auto h-9 text-sm" data-testid="filter-who"><SelectValue placeholder="Кой" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Кой: всички</SelectItem>
            {whoOptions.map((w) => <SelectItem key={w} value={w}>{w}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {/* активни филтри */}
      {activeFilters.length > 0 && (
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-xs text-muted-foreground">Активни:</span>
          {activeFilters.map((f) => (
            <span key={f.key} className="text-xs bg-primary/10 text-primary px-2.5 py-1 rounded-md inline-flex items-center gap-1.5">
              {f.label}
              <button onClick={f.clear} data-testid={`clear-${f.key}`}><X className="w-3 h-3" /></button>
            </span>
          ))}
          <button onClick={clearAll} className="text-xs text-amber-500 px-2" data-testid="clear-all-filters">Изчисти всички</button>
        </div>
      )}

      {/* board */}
      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Зареждане…</div>
      ) : units.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          Още няма активи. Натисни „Нов актив", за да добавиш първата бройка (получава QR автоматично).
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 mb-3">
            <button onClick={() => setView("table")} className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border transition-colors ${view === "table" ? "border-primary bg-primary/10" : "border-border text-muted-foreground"}`} data-testid="view-table"><List className="w-4 h-4" />Таблица</button>
            <button onClick={() => setView("board")} className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border transition-colors ${view === "board" ? "border-primary bg-primary/10" : "border-border text-muted-foreground"}`} data-testid="view-board"><LayoutGrid className="w-4 h-4" />По локация</button>
          </div>

          {view === "table" ? (
            <div className="rounded-xl border border-border overflow-hidden">
              <div className="grid grid-cols-[1.9fr_1.4fr_1.1fr_1fr_0.8fr] gap-3 px-4 py-2.5 border-b border-border text-xs text-muted-foreground">
                <span>Артикул</span><span>Къде</span><span>Въведен</span><span>Кой</span><span className="text-right">Действия</span>
              </div>
              {filtered.map((u) => (
                <div key={u.id} className="grid grid-cols-[1.9fr_1.4fr_1.1fr_1fr_0.8fr] gap-3 px-4 py-3 border-b border-border last:border-0 items-center hover:bg-muted/40" data-testid={`unit-row-${u.id}`}>
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                      {u.photo_url ? <img src={u.photo_url} alt="" className="w-full h-full object-cover rounded-lg" /> : <Dot status={u.status} />}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate flex items-center gap-1.5">
                        {u.item_name || "—"}
                        {warrantyStatus(u.purchase_date, u.warranty_months).inWarranty && (
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" title="В гаранция" />
                        )}
                      </p>
                      <p className="text-[10px] font-mono text-muted-foreground">{u.qr_id || u.serial_no || "—"}</p>
                    </div>
                  </div>
                  <span className="text-sm inline-flex items-center gap-1 min-w-0"><MapPin className="w-3.5 h-3.5 text-primary shrink-0" /><span className="truncate">{u.location_name || "—"}</span></span>
                  <span className="text-sm text-muted-foreground">{fmtDate(u.created_at)}</span>
                  <span className="text-sm text-muted-foreground truncate">{u.created_by_name || "—"}</span>
                  <div className="flex items-center justify-end gap-1">
                    {u.status === "repair" ? (
                      <Button variant="ghost" size="icon" onClick={() => openRepairReturn(u)} data-testid={`repair-return-${u.id}`} title="Върни от ремонт"><CheckCircle2 className="w-4 h-4 text-emerald-500" /></Button>
                    ) : (
                      <Button variant="ghost" size="icon" onClick={() => openRepairSend(u)} data-testid={`repair-send-${u.id}`} title="На ремонт"><Wrench className="w-4 h-4 text-amber-500" /></Button>
                    )}
                    <Button variant="ghost" size="icon" onClick={() => openHistory(u)} data-testid={`hist-${u.id}`}><History className="w-4 h-4" /></Button>
                    <Button variant="ghost" size="icon" onClick={() => openEdit(u)} data-testid={`edit-${u.id}`}><Pencil className="w-4 h-4" /></Button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {groupKeys.map((key) => (
            <div key={key} className="min-w-[200px] flex-shrink-0">
              <div className="flex justify-between items-center text-sm font-semibold mb-2 px-1">
                <span className="truncate">{key}</span>
                <span className="text-muted-foreground">{groups[key].length}</span>
              </div>
              <div className="flex flex-col gap-2">
                {groups[key].map((u) => (
                  <button
                    key={u.id}
                    onClick={() => openEdit(u)}
                    className="text-left p-2.5 rounded-lg bg-muted hover:bg-muted/70 transition-colors"
                    data-testid={`unit-${u.id}`}
                  >
                    <div className="text-sm font-medium flex items-center gap-1.5">
                      <Dot status={u.status} /> {u.item_name || "—"}
                    </div>
                    <div className="text-[10px] font-mono text-muted-foreground mt-0.5">{u.qr_id}</div>
                    {(u.brand || u.model) && (
                      <div className="text-[10px] text-muted-foreground">{[u.brand, u.model].filter(Boolean).join(" · ")}</div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
          )}
        </>
      )}

      {/* Create / Edit */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-md max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingId ? `Актив · ${editingName}` : "Нов актив"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {editingId && editingQr && (
              <div className="flex justify-center pb-1">
                <UnitQrBlock qrId={editingQr} serialNo={form.serial_no} />
              </div>
            )}
            {!editingId && (
              <div>
                <Label>Артикул *</Label>
                <Select value={form.item_id} onValueChange={(v) => setForm({ ...form, item_id: v })}>
                  <SelectTrigger><SelectValue placeholder="Избери артикул" /></SelectTrigger>
                  <SelectContent>
                    {items.map((it) => (
                      <SelectItem key={it.id} value={it.id}>
                        {it.name}{it.brand ? ` · ${it.brand}` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Сериен №</Label><Input value={form.serial_no} onChange={(e) => setForm({ ...form, serial_no: e.target.value })} /></div>
              <div><Label>Инвентарен №</Label><Input value={form.inventory_no} onChange={(e) => setForm({ ...form, inventory_no: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Статус</Label>
                <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(STATUS).map(([k, s]) => <SelectItem key={k} value={k}>{s.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Склад (място)</Label>
                <Select value={form.location_id || "none"} onValueChange={(v) => setForm({ ...form, location_id: v === "none" ? "" : v })}>
                  <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">—</SelectItem>
                    {warehouses.map((w) => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Дата на покупка</Label><Input type="date" value={form.purchase_date} onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} data-testid="unit-purchase-date" /></div>
              <div><Label>Гаранция (мес.)</Label><Input type="number" min="0" value={form.warranty_months} onChange={(e) => setForm({ ...form, warranty_months: e.target.value })} data-testid="unit-warranty" /></div>
            </div>
            <div>
              <Label>Цена (€)</Label>
              <Input type="number" min="0" step="0.01" value={form.purchase_price} onChange={(e) => setForm({ ...form, purchase_price: e.target.value })} data-testid="unit-price" />
            </div>
            <div>
              <Label>Бележки</Label>
              <Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
          </div>
          <DialogFooter className="flex justify-between sm:justify-between">
            {editingId ? (
              <Button variant="ghost" onClick={handleDelete} className="text-destructive">
                <Trash2 className="w-4 h-4 mr-1" /> Изтрий
              </Button>
            ) : <span />}
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setModalOpen(false)}>Отказ</Button>
              <Button onClick={handleSave} disabled={saving} data-testid="unit-save">{saving ? "Запазва…" : "Запази"}</Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* История на движенията */}
      <Dialog open={!!moveHist} onOpenChange={(o) => !o && setMoveHist(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><History className="w-5 h-5" />История · {moveHist?.unit?.item_name}</DialogTitle>
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
                  <p className="text-xs text-muted-foreground mt-1">{m.from_name ? `от ${m.from_name} ` : ""}{m.to_name ? `→ ${m.to_name}` : ""}</p>
                  <p className="text-xs text-muted-foreground">{m.by_name}</p>
                  {m.note && <p className="text-xs mt-1">{m.note}</p>}
                </div>
              ))}
            </div>
          )}

          {moveHist?.repairs && moveHist.repairs.length > 0 && (
            <div className="mt-4 pt-4 border-t border-border">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-medium flex items-center gap-1.5"><Wrench className="w-4 h-4 text-amber-500" />Ремонти</p>
                <span className="text-xs text-muted-foreground">Похарчено общо: <b className="text-amber-400">{(moveHist.totalPaid || 0).toLocaleString("bg-BG")} €</b></span>
              </div>
              <div className="space-y-2">
                {moveHist.repairs.map((rp, i) => (
                  <div key={i} className="rounded-lg border border-border p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">{fmtDate(rp.sent_at)}{rp.returned_at ? ` → ${fmtDate(rp.returned_at)}` : " · в ремонт"}</span>
                      <div className="flex items-center gap-1.5">
                        {rp.is_warranty && <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded">гаранция</span>}
                        {rp.cost != null && rp.cost > 0 && <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded">{rp.cost} €</span>}
                      </div>
                    </div>
                    {rp.work_done && <p className="text-xs mt-1">{rp.work_done}</p>}
                    {rp.issue && !rp.work_done && <p className="text-xs mt-1 text-muted-foreground">Повреда: {rp.issue}</p>}
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {rp.service ? `${rp.service} · ` : ""}{rp.sent_by_name ? `закара: ${rp.sent_by_name}` : ""}{rp.returned_by_name ? ` · взе: ${rp.returned_by_name}` : ""}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Изпрати на ремонт */}
      <Dialog open={!!repairSend} onOpenChange={(o) => !o && setRepairSend(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Wrench className="w-5 h-5 text-amber-500" />Изпрати на ремонт</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg bg-muted/40 p-2.5 text-sm">
              {repairSend?.unit?.item_name} <span className="text-[10px] font-mono text-muted-foreground">{repairSend?.unit?.qr_id}</span>
            </div>
            <div>
              <Label>Кой го закара</Label>
              <Select value={rForm.sent_by_name || "none"} onValueChange={(v) => setRForm({ ...rForm, sent_by_name: v === "none" ? "" : v })}>
                <SelectTrigger data-testid="repair-sent-by"><SelectValue placeholder="Избери служител" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">—</SelectItem>
                  {employees.map((e) => <SelectItem key={e.id} value={e.name || e.email}>{e.name || e.email}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div><Label>Сервиз / при кого</Label><Input value={rForm.service} onChange={(e) => setRForm({ ...rForm, service: e.target.value })} data-testid="repair-service" /></div>
            <div><Label>Повреда</Label><Input value={rForm.issue} onChange={(e) => setRForm({ ...rForm, issue: e.target.value })} data-testid="repair-issue" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRepairSend(null)}>Отказ</Button>
            <Button onClick={submitRepairSend} disabled={rSaving} data-testid="repair-send-submit">{rSaving ? "Изпраща…" : "Изпрати на ремонт"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Върни от ремонт */}
      <Dialog open={!!repairReturn} onOpenChange={(o) => !o && setRepairReturn(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><CheckCircle2 className="w-5 h-5 text-emerald-500" />Върни от ремонт</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg bg-muted/40 p-2.5 text-sm">
              <p className="font-medium">{repairReturn?.unit?.item_name} <span className="text-[10px] font-mono text-muted-foreground">{repairReturn?.unit?.qr_id}</span></p>
              {repairReturn?.open && (
                <div className="mt-1.5 flex flex-col gap-0.5 text-xs text-muted-foreground">
                  <span>Изпратен: <b className="text-foreground">{fmtDate(repairReturn.open.sent_at)}</b>{daysSince(repairReturn.open.sent_at)}</span>
                  {repairReturn.open.service && <span>Сервиз: <b className="text-foreground">{repairReturn.open.service}</b></span>}
                  {repairReturn.open.sent_by_name && <span>Закара: <b className="text-foreground">{repairReturn.open.sent_by_name}</b></span>}
                  {repairReturn.open.issue && <span>Повреда: <b className="text-foreground">{repairReturn.open.issue}</b></span>}
                </div>
              )}
            </div>
            {repairReturn && warrantyStatus(repairReturn.unit.purchase_date, repairReturn.unit.warranty_months).inWarranty && (
              <div className="flex items-center gap-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 px-3 py-2">
                <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                <span className="text-xs text-emerald-300">В гаранция до {warrantyStatus(repairReturn.unit.purchase_date, repairReturn.unit.warranty_months).untilLabel} · но диагностика/транспорт може да се плащат</span>
              </div>
            )}
            <div>
              <Label>Кой го взе</Label>
              <Select value={rForm.returned_by_name || "none"} onValueChange={(v) => setRForm({ ...rForm, returned_by_name: v === "none" ? "" : v })}>
                <SelectTrigger data-testid="repair-returned-by"><SelectValue placeholder="Избери служител" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">—</SelectItem>
                  {employees.map((e) => <SelectItem key={e.id} value={e.name || e.email}>{e.name || e.email}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={rForm.is_warranty} onChange={(e) => setRForm({ ...rForm, is_warranty: e.target.checked })} data-testid="repair-is-warranty" />
              Покрито от гаранция
            </label>
            <div><Label>Цена (€){rForm.is_warranty ? " · диагностика/транспорт може да се плащат" : ""}</Label><Input type="number" min="0" step="0.01" placeholder="0" value={rForm.cost} onChange={(e) => setRForm({ ...rForm, cost: e.target.value })} data-testid="repair-cost" /></div>
            <div><Label>Какво е направено</Label><Input value={rForm.work_done} onChange={(e) => setRForm({ ...rForm, work_done: e.target.value })} data-testid="repair-work-done" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRepairReturn(null)}>Отказ</Button>
            <Button onClick={submitRepairReturn} disabled={rSaving} data-testid="repair-return-submit">{rSaving ? "Връща…" : "Готов · върни в наличност"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}


