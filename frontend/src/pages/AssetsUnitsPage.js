import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { Plus, Search, Loader2, Trash2 } from "lucide-react";
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
};

export default function AssetsUnitsPage() {
  const { t } = useTranslation();
  const [units, setUnits] = useState([]);
  const [items, setItems] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editingName, setEditingName] = useState("");
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [u, it, wh] = await Promise.all([
        API.get("/assets/units?page_size=300"),
        API.get("/assets/items?page_size=200"),
        API.get("/warehouses?page_size=200&active_only=false"),
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
  const filtered = q
    ? units.filter((u) =>
        (u.item_name || "").toLowerCase().includes(q) ||
        (u.qr_id || "").toLowerCase().includes(q) ||
        (u.serial_no || "").toLowerCase().includes(q) ||
        (u.inventory_no || "").toLowerCase().includes(q))
    : units;

  const groups = {};
  filtered.forEach((u) => {
    const key = u.status === "repair" ? "Ремонт" : (u.location_name || "Без място");
    (groups[key] = groups[key] || []).push(u);
  });
  const groupKeys = Object.keys(groups).sort((a, b) =>
    a === "Ремонт" ? 1 : b === "Ремонт" ? -1 : a.localeCompare(b, "bg"));

  const openCreate = () => { setEditingId(null); setEditingName(""); setForm(EMPTY); setModalOpen(true); };

  const openEdit = (u) => {
    setEditingId(u.id);
    setEditingName(u.item_name || "");
    setForm({
      item_id: u.item_id || "",
      serial_no: u.serial_no || "",
      inventory_no: u.inventory_no || "",
      status: u.status || "available",
      location_id: u.location_type === "warehouse" ? (u.location_id || "") : "",
      notes: u.notes || "",
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

      {/* board */}
      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Зареждане…</div>
      ) : units.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          Още няма активи. Натисни „Нов актив", за да добавиш първата бройка (получава QR автоматично).
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

      {/* Create / Edit */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-md max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingId ? `Актив · ${editingName}` : "Нов актив"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
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
    </div>
  );
}
