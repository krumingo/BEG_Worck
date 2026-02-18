import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import { useNavigate, useSearchParams } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Calculator, Plus, Pencil, Trash2, Loader2, Calendar, Filter, Play,
  BarChart3, TrendingUp, Users, Clock, Building2, Layers, Eye
} from "lucide-react";

const FREQUENCIES = ["OneTime", "Monthly", "Weekly"];
const ALLOCATION_TYPES = ["CompanyWide", "PerPerson", "PerAssetAmortized"];

export default function OverheadPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") || "dashboard";

  // Data states
  const [categories, setCategories] = useState([]);
  const [costs, setCosts] = useState([]);
  const [assets, setAssets] = useState([]);
  const [snapshots, setSnapshots] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);

  // Filters
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
  });
  const [dateTo, setDateTo] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);
  });
  const [categoryFilter, setCategoryFilter] = useState("");

  // Dialog states
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false);
  const [costDialogOpen, setCostDialogOpen] = useState(false);
  const [assetDialogOpen, setAssetDialogOpen] = useState(false);
  const [snapshotDialogOpen, setSnapshotDialogOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [saving, setSaving] = useState(false);
  const [computing, setComputing] = useState(false);

  // Form states - Category
  const [formCatName, setFormCatName] = useState("");
  const [formCatActive, setFormCatActive] = useState(true);

  // Form states - Cost
  const [formCostCategoryId, setFormCostCategoryId] = useState("");
  const [formCostName, setFormCostName] = useState("");
  const [formCostAmount, setFormCostAmount] = useState("");
  const [formCostVat, setFormCostVat] = useState("20");
  const [formCostDate, setFormCostDate] = useState(new Date().toISOString().slice(0, 10));
  const [formCostFrequency, setFormCostFrequency] = useState("OneTime");
  const [formCostAllocType, setFormCostAllocType] = useState("CompanyWide");
  const [formCostNote, setFormCostNote] = useState("");

  // Form states - Asset
  const [formAssetName, setFormAssetName] = useState("");
  const [formAssetCost, setFormAssetCost] = useState("");
  const [formAssetDate, setFormAssetDate] = useState(new Date().toISOString().slice(0, 10));
  const [formAssetLife, setFormAssetLife] = useState("60");
  const [formAssetAssigned, setFormAssetAssigned] = useState("");
  const [formAssetActive, setFormAssetActive] = useState(true);
  const [formAssetNote, setFormAssetNote] = useState("");

  // Form states - Snapshot
  const [formSnapMethod, setFormSnapMethod] = useState("PersonDays");
  const [formSnapNotes, setFormSnapNotes] = useState("");

  const canWrite = ["Admin", "Owner", "Accountant"].includes(user?.role);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [catRes, costRes, assetRes, snapRes, empRes] = await Promise.all([
        API.get("/overhead/categories"),
        API.get(`/overhead/costs?date_from=${dateFrom}&date_to=${dateTo}${categoryFilter ? `&category_id=${categoryFilter}` : ""}`),
        API.get("/overhead/assets?active_only=false"),
        API.get("/overhead/snapshots"),
        API.get("/employees"),
      ]);
      setCategories(catRes.data);
      setCosts(costRes.data);
      setAssets(assetRes.data);
      setSnapshots(snapRes.data);
      setEmployees(empRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, categoryFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(amount || 0);
  };

  // Category handlers
  const openCategoryCreate = () => {
    setEditingItem(null);
    setFormCatName("");
    setFormCatActive(true);
    setCategoryDialogOpen(true);
  };

  const openCategoryEdit = (cat) => {
    setEditingItem(cat);
    setFormCatName(cat.name);
    setFormCatActive(cat.active);
    setCategoryDialogOpen(true);
  };

  const handleSaveCategory = async () => {
    if (!formCatName) return;
    setSaving(true);
    try {
      if (editingItem) {
        await API.put(`/overhead/categories/${editingItem.id}`, { name: formCatName, active: formCatActive });
      } else {
        await API.post("/overhead/categories", { name: formCatName, active: formCatActive });
      }
      setCategoryDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteCategory = async (cat) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await API.delete(`/overhead/categories/${cat.id}`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.deleteFailed"));
    }
  };

  // Cost handlers
  const openCostCreate = () => {
    setEditingItem(null);
    setFormCostCategoryId(categories[0]?.id || "");
    setFormCostName("");
    setFormCostAmount("");
    setFormCostVat("20");
    setFormCostDate(new Date().toISOString().slice(0, 10));
    setFormCostFrequency("OneTime");
    setFormCostAllocType("CompanyWide");
    setFormCostNote("");
    setCostDialogOpen(true);
  };

  const openCostEdit = (cost) => {
    setEditingItem(cost);
    setFormCostCategoryId(cost.category_id || "");
    setFormCostName(cost.name);
    setFormCostAmount(String(cost.amount));
    setFormCostVat(String(cost.vat_percent));
    setFormCostDate(cost.date_incurred);
    setFormCostFrequency(cost.frequency);
    setFormCostAllocType(cost.allocation_type);
    setFormCostNote(cost.note || "");
    setCostDialogOpen(true);
  };

  const handleSaveCost = async () => {
    if (!formCostCategoryId || !formCostName || !formCostAmount) return;
    setSaving(true);
    try {
      const data = {
        category_id: formCostCategoryId,
        name: formCostName,
        amount: parseFloat(formCostAmount),
        vat_percent: parseFloat(formCostVat),
        date_incurred: formCostDate,
        frequency: formCostFrequency,
        allocation_type: formCostAllocType,
        note: formCostNote || null,
      };
      if (editingItem) {
        await API.put(`/overhead/costs/${editingItem.id}`, data);
      } else {
        await API.post("/overhead/costs", data);
      }
      setCostDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteCost = async (cost) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await API.delete(`/overhead/costs/${cost.id}`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.deleteFailed"));
    }
  };

  // Asset handlers
  const openAssetCreate = () => {
    setEditingItem(null);
    setFormAssetName("");
    setFormAssetCost("");
    setFormAssetDate(new Date().toISOString().slice(0, 10));
    setFormAssetLife("60");
    setFormAssetAssigned("");
    setFormAssetActive(true);
    setFormAssetNote("");
    setAssetDialogOpen(true);
  };

  const openAssetEdit = (asset) => {
    setEditingItem(asset);
    setFormAssetName(asset.name);
    setFormAssetCost(String(asset.purchase_cost));
    setFormAssetDate(asset.purchase_date);
    setFormAssetLife(String(asset.useful_life_months));
    setFormAssetAssigned(asset.assigned_to_user_id || "");
    setFormAssetActive(asset.active);
    setFormAssetNote(asset.note || "");
    setAssetDialogOpen(true);
  };

  const handleSaveAsset = async () => {
    if (!formAssetName || !formAssetCost) return;
    setSaving(true);
    try {
      const data = {
        name: formAssetName,
        purchase_cost: parseFloat(formAssetCost),
        purchase_date: formAssetDate,
        useful_life_months: parseInt(formAssetLife),
        assigned_to_user_id: formAssetAssigned || null,
        active: formAssetActive,
        note: formAssetNote || null,
      };
      if (editingItem) {
        await API.put(`/overhead/assets/${editingItem.id}`, data);
      } else {
        await API.post("/overhead/assets", data);
      }
      setAssetDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAsset = async (asset) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await API.delete(`/overhead/assets/${asset.id}`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.deleteFailed"));
    }
  };

  // Snapshot handlers
  const openSnapshotCompute = () => {
    setFormSnapMethod("PersonDays");
    setFormSnapNotes("");
    setSnapshotDialogOpen(true);
  };

  const handleComputeSnapshot = async () => {
    setComputing(true);
    try {
      await API.post("/overhead/snapshots/compute", {
        period_start: dateFrom,
        period_end: dateTo,
        method: formSnapMethod,
        notes: formSnapNotes || null,
      });
      setSnapshotDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setComputing(false);
    }
  };

  // Compute summary for dashboard
  const totalCostsInPeriod = costs.reduce((sum, c) => sum + (c.amount || 0), 0);
  const activeAssets = assets.filter(a => a.active);
  const periodDays = Math.ceil((new Date(dateTo) - new Date(dateFrom)) / (1000 * 60 * 60 * 24)) + 1;
  const totalAmortInPeriod = activeAssets.reduce((sum, a) => {
    const dailyAmort = a.purchase_cost / (a.useful_life_months * 30.4375);
    return sum + (dailyAmort * periodDays);
  }, 0);
  const totalOverheadInPeriod = totalCostsInPeriod + totalAmortInPeriod;

  const latestSnapshot = snapshots[0];

  const setTab = (tab) => {
    searchParams.set("tab", tab);
    setSearchParams(searchParams);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px]" data-testid="overhead-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("overhead.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("overhead.subtitle")}</p>
        </div>
      </div>

      {/* Period Filter - Global */}
      <div className="flex items-center gap-4 mb-6 p-4 rounded-lg bg-card border border-border" data-testid="period-filter">
        <Calendar className="w-5 h-5 text-muted-foreground" />
        <div className="flex items-center gap-2">
          <Label className="text-sm">{t("overhead.periodStart")}</Label>
          <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="w-[150px] bg-background" data-testid="date-from" />
        </div>
        <div className="flex items-center gap-2">
          <Label className="text-sm">{t("overhead.periodEnd")}</Label>
          <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="w-[150px] bg-background" data-testid="date-to" />
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setTab} className="space-y-6">
        <TabsList className="grid grid-cols-4 w-[500px]">
          <TabsTrigger value="dashboard" data-testid="tab-dashboard">
            <BarChart3 className="w-4 h-4 mr-2" /> {t("overhead.dashboard")}
          </TabsTrigger>
          <TabsTrigger value="costs" data-testid="tab-costs">
            <TrendingUp className="w-4 h-4 mr-2" /> {t("overhead.costs")}
          </TabsTrigger>
          <TabsTrigger value="assets" data-testid="tab-assets">
            <Building2 className="w-4 h-4 mr-2" /> {t("overhead.assets")}
          </TabsTrigger>
          <TabsTrigger value="snapshots" data-testid="tab-snapshots">
            <Layers className="w-4 h-4 mr-2" /> {t("overhead.snapshots")}
          </TabsTrigger>
        </TabsList>

        {/* DASHBOARD TAB */}
        <TabsContent value="dashboard" className="space-y-6">
          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm text-muted-foreground mb-1">{t("overhead.totalOverhead")}</p>
              <p className="text-2xl font-bold text-primary">{formatCurrency(totalOverheadInPeriod)}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm text-muted-foreground mb-1">{t("overhead.totalCosts")}</p>
              <p className="text-2xl font-bold text-foreground">{formatCurrency(totalCostsInPeriod)}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm text-muted-foreground mb-1">{t("overhead.totalAmortization")}</p>
              <p className="text-2xl font-bold text-amber-400">{formatCurrency(totalAmortInPeriod)}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm text-muted-foreground mb-1">{t("overhead.assets")}</p>
              <p className="text-2xl font-bold text-emerald-400">{activeAssets.length}</p>
            </div>
          </div>

          {/* Latest Snapshot */}
          {latestSnapshot && (
            <div className="rounded-xl border border-border bg-card p-6">
              <h3 className="text-lg font-semibold text-foreground mb-4">{t("overhead.snapshotDetail")}</h3>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">{t("common.period")}</p>
                  <p className="text-sm font-medium">{latestSnapshot.period_start} - {latestSnapshot.period_end}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t("overhead.personDays")}</p>
                  <p className="text-sm font-medium">{latestSnapshot.total_person_days}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t("overhead.hours")}</p>
                  <p className="text-sm font-medium">{latestSnapshot.total_hours}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t("overhead.ratePerPersonDay")}</p>
                  <p className="text-sm font-bold text-primary">{formatCurrency(latestSnapshot.overhead_rate_per_person_day)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t("overhead.ratePerHour")}</p>
                  <p className="text-sm font-bold text-primary">{formatCurrency(latestSnapshot.overhead_rate_per_hour)}</p>
                </div>
              </div>
            </div>
          )}

          {/* Compute Button */}
          {canWrite && (
            <div className="flex justify-end">
              <Button onClick={openSnapshotCompute} data-testid="compute-snapshot-btn">
                <Calculator className="w-4 h-4 mr-2" /> {t("overhead.computeSnapshot")}
              </Button>
            </div>
          )}
        </TabsContent>

        {/* COSTS TAB */}
        <TabsContent value="costs" className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Select value={categoryFilter} onValueChange={(v) => setCategoryFilter(v === "all" ? "" : v)}>
                <SelectTrigger className="w-[200px] bg-card" data-testid="category-filter">
                  <Filter className="w-4 h-4 mr-2" />
                  <SelectValue placeholder={t("overhead.categories")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {categories.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {canWrite && (
                <Button variant="outline" size="sm" onClick={openCategoryCreate} data-testid="manage-categories-btn">
                  <Plus className="w-4 h-4 mr-1" /> {t("overhead.categories")}
                </Button>
              )}
            </div>
            {canWrite && (
              <Button onClick={openCostCreate} data-testid="new-cost-btn">
                <Plus className="w-4 h-4 mr-2" /> {t("overhead.newCost")}
              </Button>
            )}
          </div>

          {/* Categories List */}
          {categories.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-4">
              {categories.map((c) => (
                <Badge key={c.id} variant={c.active ? "default" : "outline"} className="cursor-pointer" onClick={() => canWrite && openCategoryEdit(c)}>
                  {c.name} {canWrite && <Pencil className="w-3 h-3 ml-1" />}
                </Badge>
              ))}
            </div>
          )}

          {/* Costs Table */}
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="costs-table">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("overhead.categories")}</TableHead>
                  <TableHead>{t("common.name")}</TableHead>
                  <TableHead>{t("overhead.dateIncurred")}</TableHead>
                  <TableHead className="text-right">{t("common.amount")}</TableHead>
                  <TableHead>{t("overhead.frequency")}</TableHead>
                  <TableHead>{t("overhead.allocationType")}</TableHead>
                  {canWrite && <TableHead className="text-right">{t("common.actions")}</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {costs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={canWrite ? 7 : 6} className="text-center py-12 text-muted-foreground">
                      <TrendingUp className="w-10 h-10 mx-auto mb-3 opacity-30" />
                      <p>{t("overhead.noCosts")}</p>
                      {canWrite && (
                        <Button variant="outline" className="mt-4" onClick={openCostCreate}>
                          {t("overhead.createFirstCost")}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ) : (
                  costs.map((cost) => (
                    <TableRow key={cost.id} data-testid={`cost-row-${cost.id}`}>
                      <TableCell className="text-sm">{cost.category_name || "-"}</TableCell>
                      <TableCell className="font-medium">{cost.name}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{cost.date_incurred}</TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(cost.amount)}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {t(`overhead.frequencies.${cost.frequency.charAt(0).toLowerCase() + cost.frequency.slice(1)}`)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">{cost.allocation_type}</TableCell>
                      {canWrite && (
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            <Button variant="ghost" size="sm" onClick={() => openCostEdit(cost)}>
                              <Pencil className="w-4 h-4" />
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => handleDeleteCost(cost)} className="text-destructive">
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </div>
                        </TableCell>
                      )}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* ASSETS TAB */}
        <TabsContent value="assets" className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">{t("overhead.assetsSubtitle")}</p>
            {canWrite && (
              <Button onClick={openAssetCreate} data-testid="new-asset-btn">
                <Plus className="w-4 h-4 mr-2" /> {t("overhead.newAsset")}
              </Button>
            )}
          </div>

          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="assets-table">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("common.name")}</TableHead>
                  <TableHead>{t("overhead.purchaseDate")}</TableHead>
                  <TableHead className="text-right">{t("overhead.purchaseCost")}</TableHead>
                  <TableHead className="text-right">{t("overhead.usefulLifeMonths")}</TableHead>
                  <TableHead className="text-right">{t("overhead.dailyAmortization")}</TableHead>
                  <TableHead>{t("overhead.assignedTo")}</TableHead>
                  <TableHead>{t("common.status")}</TableHead>
                  {canWrite && <TableHead className="text-right">{t("common.actions")}</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {assets.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={canWrite ? 8 : 7} className="text-center py-12 text-muted-foreground">
                      <Building2 className="w-10 h-10 mx-auto mb-3 opacity-30" />
                      <p>{t("overhead.noAssets")}</p>
                      {canWrite && (
                        <Button variant="outline" className="mt-4" onClick={openAssetCreate}>
                          {t("overhead.createFirstAsset")}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ) : (
                  assets.map((asset) => (
                    <TableRow key={asset.id} data-testid={`asset-row-${asset.id}`}>
                      <TableCell className="font-medium">{asset.name}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{asset.purchase_date}</TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(asset.purchase_cost)}</TableCell>
                      <TableCell className="text-right">{asset.useful_life_months}</TableCell>
                      <TableCell className="text-right font-mono text-amber-400">{formatCurrency(asset.daily_amortization)}</TableCell>
                      <TableCell className="text-sm">
                        {employees.find(e => e.id === asset.assigned_to_user_id)?.name || "-"}
                      </TableCell>
                      <TableCell>
                        <Badge variant={asset.active ? "default" : "outline"}>
                          {asset.active ? t("common.active") : t("common.inactive")}
                        </Badge>
                      </TableCell>
                      {canWrite && (
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            <Button variant="ghost" size="sm" onClick={() => openAssetEdit(asset)}>
                              <Pencil className="w-4 h-4" />
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => handleDeleteAsset(asset)} className="text-destructive">
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </div>
                        </TableCell>
                      )}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* SNAPSHOTS TAB */}
        <TabsContent value="snapshots" className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">{t("overhead.snapshotsSubtitle")}</p>
            {canWrite && (
              <Button onClick={openSnapshotCompute} data-testid="compute-snapshot-btn-2">
                <Calculator className="w-4 h-4 mr-2" /> {t("overhead.computeSnapshot")}
              </Button>
            )}
          </div>

          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="snapshots-table">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("common.period")}</TableHead>
                  <TableHead>{t("overhead.method")}</TableHead>
                  <TableHead className="text-right">{t("overhead.totalOverhead")}</TableHead>
                  <TableHead className="text-right">{t("overhead.personDays")}</TableHead>
                  <TableHead className="text-right">{t("overhead.hours")}</TableHead>
                  <TableHead className="text-right">{t("overhead.ratePerPersonDay")}</TableHead>
                  <TableHead className="text-right">{t("overhead.ratePerHour")}</TableHead>
                  <TableHead>{t("overhead.computedAt")}</TableHead>
                  <TableHead className="text-right">{t("common.actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {snapshots.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center py-12 text-muted-foreground">
                      <Layers className="w-10 h-10 mx-auto mb-3 opacity-30" />
                      <p>{t("overhead.noSnapshots")}</p>
                      {canWrite && (
                        <Button variant="outline" className="mt-4" onClick={openSnapshotCompute}>
                          {t("overhead.computeFirstSnapshot")}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ) : (
                  snapshots.map((snap) => (
                    <TableRow key={snap.id} data-testid={`snapshot-row-${snap.id}`}>
                      <TableCell className="font-medium">{snap.period_start} - {snap.period_end}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{t(`overhead.methods.${snap.method === "PersonDays" ? "personDays" : "hours"}`)}</Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono font-bold text-primary">{formatCurrency(snap.total_overhead)}</TableCell>
                      <TableCell className="text-right">{snap.total_person_days}</TableCell>
                      <TableCell className="text-right">{snap.total_hours}</TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(snap.overhead_rate_per_person_day)}</TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(snap.overhead_rate_per_hour)}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{new Date(snap.computed_at).toLocaleString()}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => navigate(`/overhead/snapshots/${snap.id}`)}>
                          <Eye className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>

      {/* Category Dialog */}
      <Dialog open={categoryDialogOpen} onOpenChange={setCategoryDialogOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card" data-testid="category-dialog">
          <DialogHeader>
            <DialogTitle>{editingItem ? t("overhead.editCategory") : t("overhead.newCategory")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>{t("common.name")} *</Label>
              <Input value={formCatName} onChange={(e) => setFormCatName(e.target.value)} className="bg-background" data-testid="cat-name-input" />
            </div>
            <div className="flex items-center gap-3">
              <Switch checked={formCatActive} onCheckedChange={setFormCatActive} data-testid="cat-active-switch" />
              <Label>{t("common.active")}</Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCategoryDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleSaveCategory} disabled={saving} data-testid="cat-save-btn">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cost Dialog */}
      <Dialog open={costDialogOpen} onOpenChange={setCostDialogOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card" data-testid="cost-dialog">
          <DialogHeader>
            <DialogTitle>{editingItem ? t("overhead.editCost") : t("overhead.newCost")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>{t("overhead.categories")} *</Label>
              <Select value={formCostCategoryId} onValueChange={setFormCostCategoryId}>
                <SelectTrigger className="bg-background" data-testid="cost-category-select">
                  <SelectValue placeholder={t("overhead.categories")} />
                </SelectTrigger>
                <SelectContent>
                  {categories.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("common.name")} *</Label>
              <Input value={formCostName} onChange={(e) => setFormCostName(e.target.value)} className="bg-background" data-testid="cost-name-input" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("common.amount")} (€) *</Label>
                <Input type="number" value={formCostAmount} onChange={(e) => setFormCostAmount(e.target.value)} className="bg-background" data-testid="cost-amount-input" />
              </div>
              <div className="space-y-2">
                <Label>VAT %</Label>
                <Input type="number" value={formCostVat} onChange={(e) => setFormCostVat(e.target.value)} className="bg-background" data-testid="cost-vat-input" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("overhead.dateIncurred")}</Label>
                <Input type="date" value={formCostDate} onChange={(e) => setFormCostDate(e.target.value)} className="bg-background" data-testid="cost-date-input" />
              </div>
              <div className="space-y-2">
                <Label>{t("overhead.frequency")}</Label>
                <Select value={formCostFrequency} onValueChange={setFormCostFrequency}>
                  <SelectTrigger className="bg-background" data-testid="cost-frequency-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FREQUENCIES.map((f) => (
                      <SelectItem key={f} value={f}>{t(`overhead.frequencies.${f.charAt(0).toLowerCase() + f.slice(1)}`)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("overhead.allocationType")}</Label>
              <Select value={formCostAllocType} onValueChange={setFormCostAllocType}>
                <SelectTrigger className="bg-background" data-testid="cost-alloctype-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ALLOCATION_TYPES.map((a) => (
                    <SelectItem key={a} value={a}>{a}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("common.note")}</Label>
              <Textarea value={formCostNote} onChange={(e) => setFormCostNote(e.target.value)} className="bg-background" data-testid="cost-note-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCostDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleSaveCost} disabled={saving} data-testid="cost-save-btn">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Asset Dialog */}
      <Dialog open={assetDialogOpen} onOpenChange={setAssetDialogOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card" data-testid="asset-dialog">
          <DialogHeader>
            <DialogTitle>{editingItem ? t("overhead.editAsset") : t("overhead.newAsset")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>{t("common.name")} *</Label>
              <Input value={formAssetName} onChange={(e) => setFormAssetName(e.target.value)} className="bg-background" data-testid="asset-name-input" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("overhead.purchaseCost")} (€) *</Label>
                <Input type="number" value={formAssetCost} onChange={(e) => setFormAssetCost(e.target.value)} className="bg-background" data-testid="asset-cost-input" />
              </div>
              <div className="space-y-2">
                <Label>{t("overhead.purchaseDate")}</Label>
                <Input type="date" value={formAssetDate} onChange={(e) => setFormAssetDate(e.target.value)} className="bg-background" data-testid="asset-date-input" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("overhead.usefulLifeMonths")}</Label>
                <Input type="number" value={formAssetLife} onChange={(e) => setFormAssetLife(e.target.value)} className="bg-background" data-testid="asset-life-input" />
              </div>
              <div className="space-y-2">
                <Label>{t("overhead.assignedTo")}</Label>
                <Select value={formAssetAssigned} onValueChange={setFormAssetAssigned}>
                  <SelectTrigger className="bg-background" data-testid="asset-assigned-select">
                    <SelectValue placeholder="-" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">-</SelectItem>
                    {employees.map((e) => (
                      <SelectItem key={e.id} value={e.id}>{e.name || e.email}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Switch checked={formAssetActive} onCheckedChange={setFormAssetActive} data-testid="asset-active-switch" />
              <Label>{t("common.active")}</Label>
            </div>
            <div className="space-y-2">
              <Label>{t("common.note")}</Label>
              <Textarea value={formAssetNote} onChange={(e) => setFormAssetNote(e.target.value)} className="bg-background" data-testid="asset-note-input" />
            </div>
            {/* Daily amortization preview */}
            {formAssetCost && formAssetLife && (
              <div className="p-3 rounded-lg bg-muted/50">
                <p className="text-sm text-muted-foreground">{t("overhead.dailyAmortization")}:</p>
                <p className="text-lg font-bold text-amber-400">
                  {formatCurrency(parseFloat(formAssetCost) / (parseInt(formAssetLife) * 30.4375))}
                </p>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssetDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleSaveAsset} disabled={saving} data-testid="asset-save-btn">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Compute Snapshot Dialog */}
      <Dialog open={snapshotDialogOpen} onOpenChange={setSnapshotDialogOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card" data-testid="snapshot-dialog">
          <DialogHeader>
            <DialogTitle>{t("overhead.computeSnapshot")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="p-3 rounded-lg bg-muted/50">
              <p className="text-sm text-muted-foreground">{t("common.period")}:</p>
              <p className="font-medium">{dateFrom} - {dateTo}</p>
            </div>
            <div className="space-y-2">
              <Label>{t("overhead.method")}</Label>
              <Select value={formSnapMethod} onValueChange={setFormSnapMethod}>
                <SelectTrigger className="bg-background" data-testid="snap-method-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="PersonDays">{t("overhead.methods.personDays")}</SelectItem>
                  <SelectItem value="Hours">{t("overhead.methods.hours")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("common.note")}</Label>
              <Textarea value={formSnapNotes} onChange={(e) => setFormSnapNotes(e.target.value)} className="bg-background" data-testid="snap-notes-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSnapshotDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleComputeSnapshot} disabled={computing} data-testid="snap-compute-btn">
              {computing && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              <Play className="w-4 h-4 mr-1" /> {t("overhead.computeSnapshot")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
