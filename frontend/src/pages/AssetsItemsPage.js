import { useState, useCallback } from "react";
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
import { Plus, Pencil, Trash2, Wrench } from "lucide-react";
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
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [deleteItem, setDeleteItem] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

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

  const openCreate = () => { setEditingId(null); setForm(EMPTY); setModalOpen(true); };

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
        <Button onClick={openCreate} data-testid="create-asset-item-btn">
          <Plus className="w-4 h-4 mr-2" /> Нов артикул
        </Button>
      </div>

      <DataTable
        columns={columns}
        fetchData={fetchData}
        refreshKey={refreshKey}
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
          <DialogFooter>
            <Button variant="outline" onClick={() => setModalOpen(false)}>Отказ</Button>
            <Button onClick={handleSave} disabled={saving} data-testid="ai-save">{saving ? "Запазва…" : "Запази"}</Button>
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
    </div>
  );
}
