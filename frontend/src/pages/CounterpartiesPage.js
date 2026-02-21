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
import { Plus, Pencil, Trash2, Users, Building2, BarChart3, Link, UserPlus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

const COUNTERPARTY_TYPES = ["supplier", "client", "both", "person"];

export default function CounterpartiesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const columns = [
    { key: "name", label: t("data.name"), sortable: true, filterable: true, filterType: "contains" },
    {
      key: "type",
      label: t("data.type"),
      sortable: true,
      filterable: true,
      filterType: "in",
      options: COUNTERPARTY_TYPES.map((t) => ({ value: t, label: t })),
      width: "120px",
      render: (value) => (
        <Badge variant={value === "supplier" ? "default" : value === "client" ? "secondary" : "outline"}>
          {value}
        </Badge>
      ),
    },
    { key: "eik", label: t("data.eik"), sortable: true, filterable: true, filterType: "contains", width: "130px" },
    { key: "vat_number", label: t("data.vatNumber"), filterable: true, filterType: "contains", width: "140px" },
    { key: "phone", label: t("data.phone"), filterable: true, filterType: "contains", width: "130px" },
    { key: "email", label: t("common.email"), filterable: true, filterType: "contains" },
    {
      key: "invoice_count",
      label: t("data.invoiceCount"),
      sortable: true,
      width: "100px",
      render: (value) => (
        <Badge variant="outline">{value || 0}</Badge>
      ),
    },
    {
      key: "active",
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
    queryParams.append("active_only", "false");

    const response = await API.get(`/counterparties?${queryParams.toString()}`);
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

  const handleViewTurnover = (row) => {
    // Navigate to turnover page with counterparty filter
    const type = row.type === "client" ? "sales" : "purchases";
    navigate(`/data/turnover?type=${type}&counterparty_id=${row.id}`);
  };

  const confirmDelete = async () => {
    try {
      await API.delete(`/counterparties/${editingItem.id}`);
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
        await API.put(`/counterparties/${editingItem.id}`, data);
        toast.success(t("data.updateSuccess"));
      } else {
        await API.post("/counterparties", data);
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
            <Building2 className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold" data-testid="counterparties-page-title">
              {t("data.counterparties")}
            </h1>
            <p className="text-sm text-muted-foreground">{t("data.counterpartiesDesc")}</p>
          </div>
        </div>
        <Button onClick={handleCreate} data-testid="create-counterparty-btn">
          <Plus className="w-4 h-4 mr-2" />
          {t("common.create")}
        </Button>
      </div>

      {/* Data Table */}
      <DataTable
        columns={columns}
        fetchData={fetchData}
        refreshKey={refreshKey}
        exportFilename="counterparties.csv"
        actions={(row) => (
          <div className="flex items-center gap-1">
            <Button 
              variant="ghost" 
              size="icon" 
              onClick={() => handleViewTurnover(row)}
              title={t("data.turnover")}
              data-testid={`turnover-btn-${row.id}`}
            >
              <BarChart3 className="w-4 h-4 text-primary" />
            </Button>
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
      <CounterpartyModal
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
              {t("data.deleteCounterpartyConfirm", { name: editingItem?.name })}
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

function CounterpartyModal({ open, onOpenChange, item, onSave }) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    name: "",
    type: "supplier",
    eik: "",
    vat_number: "",
    address: "",
    phone: "",
    email: "",
    contact_person: "",
    payment_terms_days: 30,
    notes: "",
    active: true,
  });

  // Reset form when modal opens
  useState(() => {
    if (open) {
      if (item) {
        setForm({
          name: item.name || "",
          type: item.type || "supplier",
          eik: item.eik || "",
          vat_number: item.vat_number || "",
          address: item.address || "",
          phone: item.phone || "",
          email: item.email || "",
          contact_person: item.contact_person || "",
          payment_terms_days: item.payment_terms_days || 30,
          notes: item.notes || "",
          active: item.active !== false,
        });
      } else {
        setForm({
          name: "",
          type: "supplier",
          eik: "",
          vat_number: "",
          address: "",
          phone: "",
          email: "",
          contact_person: "",
          payment_terms_days: 30,
          notes: "",
          active: true,
        });
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
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {item ? t("data.editCounterparty") : t("data.createCounterparty")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {item ? t("data.editCounterparty") : t("data.createCounterparty")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2 col-span-2">
              <Label htmlFor="name">{t("data.name")} *</Label>
              <Input
                id="name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                data-testid="counterparty-name-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="type">{t("data.type")} *</Label>
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                <SelectTrigger data-testid="counterparty-type-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {COUNTERPARTY_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="payment_terms_days">{t("data.paymentTerms")}</Label>
              <Input
                id="payment_terms_days"
                type="number"
                value={form.payment_terms_days}
                onChange={(e) => setForm({ ...form, payment_terms_days: parseInt(e.target.value) || 0 })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="eik">{t("data.eik")}</Label>
              <Input
                id="eik"
                value={form.eik}
                onChange={(e) => setForm({ ...form, eik: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="vat_number">{t("data.vatNumber")}</Label>
              <Input
                id="vat_number"
                value={form.vat_number}
                onChange={(e) => setForm({ ...form, vat_number: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="phone">{t("data.phone")}</Label>
              <Input
                id="phone"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">{t("common.email")}</Label>
              <Input
                id="email"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div className="space-y-2 col-span-2">
              <Label htmlFor="address">{t("data.address")}</Label>
              <Input
                id="address"
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
              />
            </div>
            <div className="space-y-2 col-span-2">
              <Label htmlFor="contact_person">{t("data.contactPerson")}</Label>
              <Input
                id="contact_person"
                value={form.contact_person}
                onChange={(e) => setForm({ ...form, contact_person: e.target.value })}
              />
            </div>
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
            <Button type="submit" disabled={loading} data-testid="counterparty-save-btn">
              {loading ? t("common.loading") : t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
