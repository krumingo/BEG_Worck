import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Users, Plus, Pencil, Trash2, BarChart3, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import DataTable from "@/components/DataTable";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import API from "@/api";
import { toast } from "sonner";

export default function ClientsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // Form state
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    phone: "",
    email: "",
    address: "",
    notes: "",
    is_active: true,
  });

  const columns = [
    {
      key: "first_name",
      label: t("clients.firstName"),
      sortable: true,
      filterable: true,
      filterType: "text",
    },
    {
      key: "last_name",
      label: t("clients.lastName"),
      sortable: true,
      filterable: true,
      filterType: "text",
    },
    {
      key: "phone",
      label: t("clients.phone"),
      sortable: true,
      filterable: true,
      filterType: "text",
    },
    {
      key: "email",
      label: t("clients.email"),
      sortable: true,
      filterable: true,
      filterType: "text",
    },
    {
      key: "linked_counterparties_count",
      label: t("clients.linkedCounterparties"),
      sortable: false,
      render: (row) => (
        <span className="text-muted-foreground">
          {row.linked_counterparties_count || 0}
        </span>
      ),
    },
    {
      key: "invoice_count",
      label: t("data.invoiceCount"),
      sortable: false,
      render: (row) => (
        <span className="text-muted-foreground">{row.invoice_count || 0}</span>
      ),
    },
    {
      key: "is_active",
      label: t("common.active"),
      sortable: true,
      render: (row) => (
        <span
          className={`px-2 py-0.5 rounded-full text-xs font-medium ${
            row.is_active
              ? "bg-green-500/20 text-green-400"
              : "bg-red-500/20 text-red-400"
          }`}
        >
          {row.is_active ? t("common.yes") : t("common.no")}
        </span>
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

    const response = await API.get(`/clients?${queryParams.toString()}`);
    return response.data;
  }, []);

  const handleCreate = () => {
    setEditingItem(null);
    setForm({
      first_name: "",
      last_name: "",
      phone: "",
      email: "",
      address: "",
      notes: "",
      is_active: true,
    });
    setModalOpen(true);
  };

  const handleEdit = (row) => {
    setEditingItem(row);
    setForm({
      first_name: row.first_name || "",
      last_name: row.last_name || "",
      phone: row.phone || "",
      email: row.email || "",
      address: row.address || "",
      notes: row.notes || "",
      is_active: row.is_active !== false,
    });
    setModalOpen(true);
  };

  const handleDelete = (row) => {
    setEditingItem(row);
    setDeleteOpen(true);
  };

  const handleViewTurnover = (row) => {
    navigate(`/data/turnover?type=sales&client_id=${row.id}`);
  };

  const handleSave = async () => {
    try {
      if (editingItem) {
        await API.put(`/clients/${editingItem.id}`, form);
        toast.success(t("clients.updateSuccess"));
      } else {
        await API.post("/clients", form);
        toast.success(t("clients.createSuccess"));
      }
      setModalOpen(false);
      setRefreshKey((k) => k + 1);
    } catch (error) {
      const message = error.response?.data?.detail || t("common.error");
      toast.error(message);
    }
  };

  const handleConfirmDelete = async () => {
    try {
      await API.delete(`/clients/${editingItem.id}`);
      toast.success(t("clients.deleteSuccess"));
      setDeleteOpen(false);
      setRefreshKey((k) => k + 1);
    } catch (error) {
      toast.error(t("common.error"));
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="clients-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
            <Users className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">
              {t("clients.title")}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t("clients.subtitle")}
            </p>
          </div>
        </div>
        <Button onClick={handleCreate} data-testid="create-client-btn">
          <Plus className="w-4 h-4 mr-2" />
          {t("common.create")}
        </Button>
      </div>

      <DataTable
        columns={columns}
        fetchData={fetchData}
        refreshKey={refreshKey}
        searchPlaceholder={t("clients.searchPlaceholder")}
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
            <Button
              variant="ghost"
              size="icon"
              onClick={() => handleDelete(row)}
            >
              <Trash2 className="w-4 h-4 text-destructive" />
            </Button>
          </div>
        )}
      />

      {/* Create/Edit Modal */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {editingItem ? t("clients.edit") : t("clients.create")}
            </DialogTitle>
            <DialogDescription>
              {editingItem
                ? t("clients.editDescription")
                : t("clients.createDescription")}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="first_name">{t("clients.firstName")} *</Label>
                <Input
                  id="first_name"
                  value={form.first_name}
                  onChange={(e) =>
                    setForm({ ...form, first_name: e.target.value })
                  }
                  data-testid="client-first-name-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="last_name">{t("clients.lastName")} *</Label>
                <Input
                  id="last_name"
                  value={form.last_name}
                  onChange={(e) =>
                    setForm({ ...form, last_name: e.target.value })
                  }
                  data-testid="client-last-name-input"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="phone">{t("clients.phone")} *</Label>
              <Input
                id="phone"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="+359888123456"
                data-testid="client-phone-input"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="email">{t("clients.email")}</Label>
              <Input
                id="email"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                data-testid="client-email-input"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="address">{t("clients.address")}</Label>
              <Input
                id="address"
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
                data-testid="client-address-input"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="notes">{t("common.notes")}</Label>
              <Textarea
                id="notes"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                rows={3}
                data-testid="client-notes-input"
              />
            </div>

            <div className="flex items-center space-x-2">
              <Switch
                id="is_active"
                checked={form.is_active}
                onCheckedChange={(checked) =>
                  setForm({ ...form, is_active: checked })
                }
              />
              <Label htmlFor="is_active">{t("common.active")}</Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setModalOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              onClick={handleSave}
              disabled={!form.first_name || !form.last_name || !form.phone}
              data-testid="save-client-btn"
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("clients.deleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("clients.deleteConfirmDescription", {
                name: `${editingItem?.first_name} ${editingItem?.last_name}`,
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
