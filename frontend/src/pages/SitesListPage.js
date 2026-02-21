import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import DashboardLayout from "@/components/DashboardLayout";
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
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  Plus,
  Search,
  Building2,
  User,
  MapPin,
  Phone,
  Hash,
  Pencil,
  Trash2,
  Loader2,
  CheckCircle,
  AlertCircle,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

// Status config with colors
const STATUS_CONFIG = {
  Active: { label: "Активен", color: "bg-green-500/20 text-green-400 border-green-500/30" },
  Paused: { label: "Пауза", color: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" },
  Finished: { label: "Завършен", color: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
  Archived: { label: "Архив", color: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
};

export default function SitesListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [sites, setSites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [editingSite, setEditingSite] = useState(null);
  const [saving, setSaving] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    name: "",
    address_text: "",
    owner_type: "person",
    owner_id: "",
    status: "Active",
    notes: "",
  });

  // Owner lookup state
  const [ownerSearch, setOwnerSearch] = useState("");
  const [ownerSearching, setOwnerSearching] = useState(false);
  const [selectedOwner, setSelectedOwner] = useState(null);
  const [showCreateOwner, setShowCreateOwner] = useState(false);
  const [newOwnerData, setNewOwnerData] = useState({
    // Person fields
    phone: "",
    first_name: "",
    last_name: "",
    // Company fields
    eik: "",
    company_name: "",
  });

  const token = localStorage.getItem("bw_token");

  // Fetch sites
  const fetchSites = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.append("status", statusFilter);
      if (searchQuery) params.append("q", searchQuery);

      const res = await fetch(`${API}/api/sites?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to fetch sites");
      const data = await res.json();
      setSites(data);
    } catch (err) {
      toast.error("Грешка при зареждане на обекти");
    } finally {
      setLoading(false);
    }
  }, [token, statusFilter, searchQuery]);

  useEffect(() => {
    fetchSites();
  }, [fetchSites]);

  // Owner lookup
  const lookupOwner = async () => {
    if (!ownerSearch.trim()) return;

    setOwnerSearching(true);
    setSelectedOwner(null);
    setShowCreateOwner(false);

    try {
      const endpoint =
        formData.owner_type === "person"
          ? `${API}/api/persons/find-by-phone?phone=${encodeURIComponent(ownerSearch)}`
          : `${API}/api/companies/find-by-eik?eik=${encodeURIComponent(ownerSearch)}`;

      const res = await fetch(endpoint, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();

      if (data.found) {
        const owner = data.person || data.company;
        setSelectedOwner(owner);
        setFormData((prev) => ({ ...prev, owner_id: owner.id }));
        toast.success(
          formData.owner_type === "person"
            ? `Намерено: ${owner.first_name} ${owner.last_name}`
            : `Намерено: ${owner.name}`
        );
      } else {
        setShowCreateOwner(true);
        setNewOwnerData((prev) => ({
          ...prev,
          phone: formData.owner_type === "person" ? ownerSearch : "",
          eik: formData.owner_type === "company" ? ownerSearch : "",
        }));
        toast.info("Не е намерен. Можете да създадете нов.");
      }
    } catch (err) {
      toast.error("Грешка при търсене");
    } finally {
      setOwnerSearching(false);
    }
  };

  // Create new owner
  const createOwner = async () => {
    setSaving(true);
    try {
      let endpoint, body;
      if (formData.owner_type === "person") {
        endpoint = `${API}/api/persons`;
        body = {
          phone: newOwnerData.phone,
          first_name: newOwnerData.first_name,
          last_name: newOwnerData.last_name,
        };
      } else {
        endpoint = `${API}/api/companies`;
        body = {
          eik: newOwnerData.eik,
          name: newOwnerData.company_name,
        };
      }

      const res = await fetch(endpoint, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to create owner");
      }

      const owner = await res.json();
      setSelectedOwner(owner);
      setFormData((prev) => ({ ...prev, owner_id: owner.id }));
      setShowCreateOwner(false);
      toast.success("Собственикът е създаден");
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  // Save site
  const saveSite = async () => {
    if (!formData.name.trim()) {
      toast.error("Името е задължително");
      return;
    }
    if (!formData.address_text.trim()) {
      toast.error("Адресът е задължителен");
      return;
    }
    if (!formData.owner_id) {
      toast.error("Изберете собственик");
      return;
    }

    setSaving(true);
    try {
      const method = editingSite ? "PUT" : "POST";
      const url = editingSite
        ? `${API}/api/sites/${editingSite.id}`
        : `${API}/api/sites`;

      const res = await fetch(url, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(formData),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to save site");
      }

      toast.success(editingSite ? "Обектът е обновен" : "Обектът е създаден");
      setShowModal(false);
      resetForm();
      fetchSites();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  // Delete site
  const deleteSite = async (site) => {
    if (!window.confirm(`Сигурни ли сте, че искате да изтриете "${site.name}"?`)) {
      return;
    }

    try {
      const res = await fetch(`${API}/api/sites/${site.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to delete");
      }

      toast.success("Обектът е изтрит");
      fetchSites();
    } catch (err) {
      toast.error(err.message);
    }
  };

  // Reset form
  const resetForm = () => {
    setFormData({
      name: "",
      address_text: "",
      owner_type: "person",
      owner_id: "",
      status: "Active",
      notes: "",
    });
    setOwnerSearch("");
    setSelectedOwner(null);
    setShowCreateOwner(false);
    setNewOwnerData({
      phone: "",
      first_name: "",
      last_name: "",
      eik: "",
      company_name: "",
    });
    setEditingSite(null);
  };

  // Open edit modal
  const openEditModal = (site) => {
    setEditingSite(site);
    setFormData({
      name: site.name,
      address_text: site.address_text,
      owner_type: site.owner_type,
      owner_id: site.owner_id,
      status: site.status,
      notes: site.notes || "",
    });
    setSelectedOwner({
      id: site.owner_id,
      name: site.owner_name,
      identifier: site.owner_identifier,
    });
    setOwnerSearch(site.owner_identifier);
    setShowModal(true);
  };

  // Status counts for quick filters
  const statusCounts = sites.reduce((acc, site) => {
    acc[site.status] = (acc[site.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <DashboardLayout>
      <div className="p-4 md:p-6 space-y-6" data-testid="sites-list-page">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Обекти</h1>
            <p className="text-gray-400 text-sm mt-1">
              {sites.length} обекта общо
            </p>
          </div>
          <Button
            onClick={() => {
              resetForm();
              setShowModal(true);
            }}
            className="bg-yellow-500 hover:bg-yellow-600 text-black"
            data-testid="create-site-btn"
          >
            <Plus className="w-4 h-4 mr-2" />
            Нов обект
          </Button>
        </div>

        {/* Search and Filters */}
        <div className="flex flex-col md:flex-row gap-4">
          {/* Search */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <Input
              placeholder="Търсене по име, адрес, телефон, ЕИК..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 bg-gray-800 border-gray-700 text-white"
              data-testid="sites-search-input"
            />
          </div>

          {/* Quick status filters */}
          <div className="flex flex-wrap gap-2">
            <Button
              variant={statusFilter === "" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("")}
              className={statusFilter === "" ? "bg-yellow-500 text-black" : "border-gray-600 text-gray-300"}
            >
              Всички ({sites.length})
            </Button>
            {Object.entries(STATUS_CONFIG).map(([status, config]) => (
              <Button
                key={status}
                variant={statusFilter === status ? "default" : "outline"}
                size="sm"
                onClick={() => setStatusFilter(statusFilter === status ? "" : status)}
                className={statusFilter === status ? "bg-yellow-500 text-black" : "border-gray-600 text-gray-300"}
                data-testid={`filter-${status.toLowerCase()}-btn`}
              >
                {config.label} ({statusCounts[status] || 0})
              </Button>
            ))}
          </div>
        </div>

        {/* Sites List */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-yellow-500" />
          </div>
        ) : sites.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <Building2 className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>Няма намерени обекти</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {sites.map((site) => (
              <div
                key={site.id}
                className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 hover:border-yellow-500/30 transition-colors cursor-pointer"
                data-testid={`site-card-${site.id}`}
                onClick={() => navigate(`/sites/${site.id}`)}
              >
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-lg font-semibold text-white truncate">
                        {site.name}
                      </h3>
                      <Badge className={STATUS_CONFIG[site.status]?.color || ""}>
                        {STATUS_CONFIG[site.status]?.label || site.status}
                      </Badge>
                    </div>

                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-400">
                      <span className="flex items-center gap-1">
                        <MapPin className="w-4 h-4" />
                        {site.address_text?.length > 40
                          ? site.address_text.substring(0, 40) + "..."
                          : site.address_text}
                      </span>
                      <span className="flex items-center gap-1">
                        {site.owner_type === "person" ? (
                          <User className="w-4 h-4" />
                        ) : (
                          <Building2 className="w-4 h-4" />
                        )}
                        {site.owner_name}
                      </span>
                      <span className="flex items-center gap-1">
                        {site.owner_type === "person" ? (
                          <Phone className="w-4 h-4" />
                        ) : (
                          <Hash className="w-4 h-4" />
                        )}
                        {site.owner_identifier}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditModal(site)}
                      className="text-gray-400 hover:text-white"
                    >
                      <Pencil className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => deleteSite(site)}
                      className="text-gray-400 hover:text-red-400"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Create/Edit Modal */}
        <Dialog open={showModal} onOpenChange={setShowModal}>
          <DialogContent className="bg-gray-900 border-gray-700 text-white max-w-lg max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>
                {editingSite ? "Редактиране на обект" : "Нов обект"}
              </DialogTitle>
            </DialogHeader>

            <div className="space-y-4 py-4">
              {/* Name */}
              <div className="space-y-2">
                <Label>Име на обекта *</Label>
                <Input
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Напр. Апартамент ул. Витоша"
                  className="bg-gray-800 border-gray-700"
                  data-testid="site-name-input"
                />
              </div>

              {/* Address */}
              <div className="space-y-2">
                <Label>Адрес *</Label>
                <Textarea
                  value={formData.address_text}
                  onChange={(e) => setFormData({ ...formData, address_text: e.target.value })}
                  placeholder="Пълен адрес на обекта"
                  className="bg-gray-800 border-gray-700"
                  rows={2}
                  data-testid="site-address-input"
                />
              </div>

              {/* Owner Type */}
              <div className="space-y-2">
                <Label>Тип собственик</Label>
                <Select
                  value={formData.owner_type}
                  onValueChange={(val) => {
                    setFormData({ ...formData, owner_type: val, owner_id: "" });
                    setSelectedOwner(null);
                    setOwnerSearch("");
                    setShowCreateOwner(false);
                  }}
                >
                  <SelectTrigger className="bg-gray-800 border-gray-700">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700">
                    <SelectItem value="person">
                      <span className="flex items-center gap-2">
                        <User className="w-4 h-4" /> Частно лице
                      </span>
                    </SelectItem>
                    <SelectItem value="company">
                      <span className="flex items-center gap-2">
                        <Building2 className="w-4 h-4" /> Фирма
                      </span>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Owner Lookup */}
              <div className="space-y-2">
                <Label>
                  {formData.owner_type === "person" ? "Телефон на собственика" : "ЕИК на фирмата"}
                </Label>
                <div className="flex gap-2">
                  <Input
                    value={ownerSearch}
                    onChange={(e) => setOwnerSearch(e.target.value)}
                    placeholder={formData.owner_type === "person" ? "0888123456" : "123456789"}
                    className="bg-gray-800 border-gray-700 flex-1"
                    data-testid="owner-search-input"
                  />
                  <Button
                    type="button"
                    onClick={lookupOwner}
                    disabled={ownerSearching || !ownerSearch.trim()}
                    className="bg-yellow-500 hover:bg-yellow-600 text-black"
                    data-testid="find-owner-btn"
                  >
                    {ownerSearching ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      "Намери"
                    )}
                  </Button>
                </div>
              </div>

              {/* Selected Owner Display */}
              {selectedOwner && (
                <div className="flex items-center gap-2 p-3 bg-green-900/20 border border-green-700/30 rounded-lg">
                  <CheckCircle className="w-5 h-5 text-green-400" />
                  <span className="text-green-300">
                    Избран:{" "}
                    {selectedOwner.first_name
                      ? `${selectedOwner.first_name} ${selectedOwner.last_name}`
                      : selectedOwner.name || selectedOwner.identifier}
                  </span>
                </div>
              )}

              {/* Create Owner Form */}
              {showCreateOwner && (
                <div className="p-4 bg-gray-800/50 border border-gray-700 rounded-lg space-y-3">
                  <div className="flex items-center gap-2 text-yellow-400 mb-2">
                    <AlertCircle className="w-4 h-4" />
                    <span className="text-sm">Създай нов собственик</span>
                  </div>

                  {formData.owner_type === "person" ? (
                    <>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1">
                          <Label className="text-xs">Име *</Label>
                          <Input
                            value={newOwnerData.first_name}
                            onChange={(e) =>
                              setNewOwnerData({ ...newOwnerData, first_name: e.target.value })
                            }
                            placeholder="Име"
                            className="bg-gray-700 border-gray-600"
                            data-testid="new-person-first-name"
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Фамилия *</Label>
                          <Input
                            value={newOwnerData.last_name}
                            onChange={(e) =>
                              setNewOwnerData({ ...newOwnerData, last_name: e.target.value })
                            }
                            placeholder="Фамилия"
                            className="bg-gray-700 border-gray-600"
                            data-testid="new-person-last-name"
                          />
                        </div>
                      </div>
                      <p className="text-xs text-gray-400">
                        Телефон: {newOwnerData.phone}
                      </p>
                    </>
                  ) : (
                    <>
                      <div className="space-y-1">
                        <Label className="text-xs">Име на фирмата *</Label>
                        <Input
                          value={newOwnerData.company_name}
                          onChange={(e) =>
                            setNewOwnerData({ ...newOwnerData, company_name: e.target.value })
                          }
                          placeholder="Фирма ЕООД"
                          className="bg-gray-700 border-gray-600"
                          data-testid="new-company-name"
                        />
                      </div>
                      <p className="text-xs text-gray-400">ЕИК: {newOwnerData.eik}</p>
                    </>
                  )}

                  <Button
                    type="button"
                    onClick={createOwner}
                    disabled={
                      saving ||
                      (formData.owner_type === "person"
                        ? !newOwnerData.first_name || !newOwnerData.last_name
                        : !newOwnerData.company_name)
                    }
                    className="w-full bg-green-600 hover:bg-green-700"
                    data-testid="create-owner-btn"
                  >
                    {saving ? (
                      <Loader2 className="w-4 h-4 animate-spin mr-2" />
                    ) : null}
                    Създай собственик
                  </Button>
                </div>
              )}

              {/* Status */}
              <div className="space-y-2">
                <Label>Статус</Label>
                <Select
                  value={formData.status}
                  onValueChange={(val) => setFormData({ ...formData, status: val })}
                >
                  <SelectTrigger className="bg-gray-800 border-gray-700">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700">
                    {Object.entries(STATUS_CONFIG).map(([status, config]) => (
                      <SelectItem key={status} value={status}>
                        {config.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Notes */}
              <div className="space-y-2">
                <Label>Бележки</Label>
                <Textarea
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  placeholder="Допълнителна информация..."
                  className="bg-gray-800 border-gray-700"
                  rows={2}
                />
              </div>
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowModal(false)}
                className="border-gray-600"
              >
                Отказ
              </Button>
              <Button
                onClick={saveSite}
                disabled={saving}
                className="bg-yellow-500 hover:bg-yellow-600 text-black"
                data-testid="save-site-btn"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
                {editingSite ? "Запази" : "Създай"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </DashboardLayout>
  );
}
