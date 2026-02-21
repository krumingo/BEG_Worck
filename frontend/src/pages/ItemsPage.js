import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import DataTable from "@/components/DataTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
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
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Plus, Pencil, Trash2, Package } from "lucide-react";
import { toast } from "sonner";

export default function ItemsPage() {
  const { t } = useTranslation();
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [categories, setCategories] = useState([]);

  // Fetch categories on mount
  useEffect(() => {
    API.get("/items/enums/categories")
      .then((res) => setCategories(res.data.categories || []))
      .catch(console.error);
  }, []);

  const columns = [
    { key: "sku", label: t("data.sku"), sortable: true, filterable: true, filterType: "contains", width: "120px" },
    { key: "name", label: t("data.name"), sortable: true, filterable: true, filterType: "contains" },
    { key: "unit", label: t("data.unit"), sortable: true, width: "80px" },
    {
      key: "category",
      label: t("data.category"),
      sortable: true,
      filterable: true,
      filterType: "in",
      options: categories.map((c) => ({ value: c, label: c })),
      width: "130px",
      render: (value) => <Badge variant="outline">{value}</Badge>,
    },
    { key: "brand", label: t("data.brand"), sortable: true, filterable: true, filterType: "contains", width: "120px" },
    {
      key: "default_price",
      label: t("data.defaultPrice"),
      sortable: true,
      filterable: true,
      filterType: "numberRange",
      width: "120px",
      render: (value) => value ? `${value.toFixed(2)} лв.` : "-",
    },
    {
      key: "is_active",
      label: t("common.active"),
      sortable: true,
      filterable: true,
      filterType: "bool",
      width: "80px",
      render: (value) => (
        <Badge variant={value ? "default" : "secondary"}>
          {value ? t("common.yes") : t("common.no")}
        </Badge>
      ),
    },
  ];

  const fetchData = useCallback(async (params) => {
    const queryParams = new URLSearchParams();
    queryParams.append("page", params.page);
    queryParams.append("page_size", params.page_size);
    if (params.sort_by) queryParams.append("sort_by", params.sort_by);
    if (params.sort_dir) queryParams.append("sort_dir", params.sort_dir);
    if (params.search) queryParams.append("search", params.search);
    if (params.filters) queryParams.append("filters", params.filters);

    const response = await API.get(`/items?${queryParams.toString()}`);
    return response.data;
  }, []);

  const handleCreate = () => {
    setEditingItem(null);
    setModalOpen(true);
  };

  const handleEdit = (row) => {
    setEditingItem(row);
    setModalOpen(true);
  };

  const handleDelete = (row) => {
    setEditingItem(row);
    setDeleteOpen(true);
  };

  const confirmDelete = async () => {
    try {
      await API.delete(`/items/${editingItem.id}`);
      toast.success(t("data.deleteSuccess"));
      setDeleteOpen(false);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    }
  };

  const handleSave = async (data) => {
    try {
      if (editingItem) {
        await API.put(`/items/${editingItem.id}`, data);
        toast.success(t("data.updateSuccess"));
      } else {
        await API.post("/items", data);
        toast.success(t("data.createSuccess"));
      }
      setModalOpen(false);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    }
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Package className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold" data-testid="items-page-title">
              {t("data.items")}
            </h1>
            <p className="text-sm text-muted-foreground">{t("data.itemsDesc")}</p>
          </div>
        </div>
        <Button onClick={handleCreate} data-testid="create-item-btn">
          <Plus className="w-4 h-4 mr-2" />
          {t("common.create")}
        </Button>
      </div>

      {/* Data Table */}
      <DataTable
        columns={columns}
        fetchData={fetchData}
        refreshKey={refreshKey}
        exportFilename="items.csv"
        actions={(row) => (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={() => handleEdit(row)}>
              <Pencil className="w-4 h-4" />
            </Button>
            <Button variant="ghost" size="icon" onClick={() => handleDelete(row)}>
              <Trash2 className="w-4 h-4 text-destructive" />
            </Button>
          </div>
        )}
      />

      {/* Create/Edit Modal */}
      <ItemModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        item={editingItem}
        onSave={handleSave}
        categories={categories}
      />

      {/* Delete Confirm */}
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("data.confirmDelete")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("data.deleteItemConfirm", { name: editingItem?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} className="bg-destructive text-destructive-foreground">
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function ItemModal({ open, onOpenChange, item, onSave, categories }) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    sku: "",
    name: "",
    unit: "бр.",
    category: "Materials",
    brand: "",
    description: "",
    default_price: "",
    min_stock: "",
    is_active: true,
  });

  // Reset form when modal opens
  useEffect(() => {
    if (open) {
      if (item) {
        setForm({
          sku: item.sku || "",
          name: item.name || "",
          unit: item.unit || "бр.",
          category: item.category || "Materials",
          brand: item.brand || "",
          description: item.description || "",
          default_price: item.default_price || "",
          min_stock: item.min_stock || "",
          is_active: item.is_active !== false,
        });
      } else {
        setForm({
          sku: "",
          name: "",
          unit: "бр.",
          category: "Materials",
          brand: "",
          description: "",
          default_price: "",
          min_stock: "",
          is_active: true,
        });
      }
    }
  }, [open, item]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    const data = {
      ...form,
      default_price: form.default_price ? parseFloat(form.default_price) : null,
      min_stock: form.min_stock ? parseFloat(form.min_stock) : null,
    };
    await onSave(data);
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {item ? t("data.editItem") : t("data.createItem")}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="sku">{t("data.sku")} *</Label>
              <Input
                id="sku"
                value={form.sku}
                onChange={(e) => setForm({ ...form, sku: e.target.value })}
                required
                disabled={!!item}
                placeholder="MAT-001"
                data-testid="item-sku-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="unit">{t("data.unit")} *</Label>
              <Input
                id="unit"
                value={form.unit}
                onChange={(e) => setForm({ ...form, unit: e.target.value })}
                required
                placeholder="бр."
              />
            </div>
            <div className="space-y-2 col-span-2">
              <Label htmlFor="name">{t("data.name")} *</Label>
              <Input
                id="name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                data-testid="item-name-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="category">{t("data.category")} *</Label>
              <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                <SelectTrigger data-testid="item-category-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {categories.map((c) => (
                    <SelectItem key={c} value={c}>{c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="brand">{t("data.brand")}</Label>
              <Input
                id="brand"
                value={form.brand}
                onChange={(e) => setForm({ ...form, brand: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="default_price">{t("data.defaultPrice")}</Label>
              <Input
                id="default_price"
                type="number"
                step="0.01"
                value={form.default_price}
                onChange={(e) => setForm({ ...form, default_price: e.target.value })}
                placeholder="0.00"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="min_stock">{t("data.minStock")}</Label>
              <Input
                id="min_stock"
                type="number"
                value={form.min_stock}
                onChange={(e) => setForm({ ...form, min_stock: e.target.value })}
                placeholder="0"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">{t("common.description")}</Label>
            <Textarea
              id="description"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={2}
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="is_active"
              checked={form.is_active}
              onCheckedChange={(checked) => setForm({ ...form, is_active: checked })}
            />
            <Label htmlFor="is_active">{t("common.active")}</Label>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={loading} data-testid="item-save-btn">
              {loading ? t("common.loading") : t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
