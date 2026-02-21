import { useState, useCallback } from "react";
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
import { Plus, Pencil, Trash2, Warehouse, Database } from "lucide-react";
import { toast } from "sonner";

const WAREHOUSE_TYPES = ["central", "project", "vehicle", "person"];

export default function WarehousesPage() {
  const { t } = useTranslation();
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const columns = [
    { key: "code", label: t("data.code"), sortable: true, filterable: true, filterType: "contains", width: "120px" },
    { key: "name", label: t("data.name"), sortable: true, filterable: true, filterType: "contains" },
    {
      key: "type",
      label: t("data.type"),
      sortable: true,
      filterable: true,
      filterType: "in",
      options: WAREHOUSE_TYPES.map((t) => ({ value: t, label: t })),
      width: "120px",
      render: (value) => <Badge variant="outline">{value}</Badge>,
    },
    { key: "address", label: t("data.address"), filterable: true, filterType: "contains" },
    {
      key: "active",
      label: t("common.active"),
      sortable: true,
      filterable: true,
      filterType: "bool",
      width: "100px",
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
    queryParams.append("active_only", "false");

    const response = await API.get(`/warehouses?${queryParams.toString()}`);
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
      await API.delete(`/warehouses/${editingItem.id}`);
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
        await API.put(`/warehouses/${editingItem.id}`, data);
        toast.success(t("data.updateSuccess"));
      } else {
        await API.post("/warehouses", data);
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
            <Warehouse className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold" data-testid="warehouses-page-title">
              {t("data.warehouses")}
            </h1>
            <p className="text-sm text-muted-foreground">{t("data.warehousesDesc")}</p>
          </div>
        </div>
        <Button onClick={handleCreate} data-testid="create-warehouse-btn">
          <Plus className="w-4 h-4 mr-2" />
          {t("common.create")}
        </Button>
      </div>

      {/* Data Table */}
      <DataTable
        columns={columns}
        fetchData={fetchData}
        refreshKey={refreshKey}
        exportFilename="warehouses.csv"
        actions={(row) => (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={() => handleEdit(row)} data-testid={`edit-${row.id}`}>
              <Pencil className="w-4 h-4" />
            </Button>
            <Button variant="ghost" size="icon" onClick={() => handleDelete(row)} data-testid={`delete-${row.id}`}>
              <Trash2 className="w-4 h-4 text-destructive" />
            </Button>
          </div>
        )}
      />

      {/* Create/Edit Modal */}
      <WarehouseModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        item={editingItem}
        onSave={handleSave}
      />

      {/* Delete Confirm */}
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("data.confirmDelete")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("data.deleteWarehouseConfirm", { name: editingItem?.name })}
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

function WarehouseModal({ open, onOpenChange, item, onSave }) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    code: "",
    name: "",
    type: "central",
    address: "",
    notes: "",
    active: true,
  });

  // Reset form when modal opens
  useState(() => {
    if (open) {
      if (item) {
        setForm({
          code: item.code || "",
          name: item.name || "",
          type: item.type || "central",
          address: item.address || "",
          notes: item.notes || "",
          active: item.active !== false,
        });
      } else {
        setForm({ code: "", name: "", type: "central", address: "", notes: "", active: true });
      }
    }
  }, [open, item]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    await onSave(form);
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {item ? t("data.editWarehouse") : t("data.createWarehouse")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {item ? t("data.editWarehouse") : t("data.createWarehouse")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="code">{t("data.code")} *</Label>
              <Input
                id="code"
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                required
                disabled={!!item}
                data-testid="warehouse-code-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="type">{t("data.type")} *</Label>
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                <SelectTrigger data-testid="warehouse-type-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WAREHOUSE_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="name">{t("data.name")} *</Label>
            <Input
              id="name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              data-testid="warehouse-name-input"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="address">{t("data.address")}</Label>
            <Input
              id="address"
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
              data-testid="warehouse-address-input"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="notes">{t("common.notes")}</Label>
            <Textarea
              id="notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              rows={2}
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="active"
              checked={form.active}
              onCheckedChange={(checked) => setForm({ ...form, active: checked })}
            />
            <Label htmlFor="active">{t("common.active")}</Label>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={loading} data-testid="warehouse-save-btn">
              {loading ? t("common.loading") : t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
