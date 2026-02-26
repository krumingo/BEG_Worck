/**
 * ChangeOrdersPage - Промени/Допълнения СМР (Mobile-first)
 * 
 * Features:
 * - Create new change orders (new/modify/cancel)
 * - Save as draft, submit for approval
 * - Admin/SiteManager can approve/reject
 * - List view with status filter
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  FilePlus2,
  Loader2,
  Plus,
  Building2,
  FileText,
  Save,
  Send,
  ChevronLeft,
  ChevronRight,
  Check,
  X,
  Clock,
  AlertCircle,
  CheckCircle,
  XCircle,
  FileWarning,
  DollarSign,
  Hammer,
  Package,
} from "lucide-react";
import { toast } from "sonner";

const KIND_OPTIONS = [
  { value: "new", label: "Ново", icon: Plus, color: "text-green-500" },
  { value: "modify", label: "Промяна", icon: FileWarning, color: "text-amber-500" },
  { value: "cancel", label: "Отмяна", icon: X, color: "text-red-500" },
];

const STATUS_OPTIONS = [
  { value: "", label: "Всички" },
  { value: "draft", label: "Чернова" },
  { value: "pending_approval", label: "Чака одобрение" },
  { value: "approved", label: "Одобрена" },
  { value: "rejected", label: "Отхвърлена" },
  { value: "invoiced", label: "Фактурирана" },
  { value: "paid", label: "Платена" },
];

const STATUS_BADGES = {
  draft: { label: "Чернова", variant: "secondary" },
  pending_approval: { label: "Чака одобрение", variant: "warning" },
  approved: { label: "Одобрена", variant: "success" },
  rejected: { label: "Отхвърлена", variant: "destructive" },
  invoiced: { label: "Фактурирана", variant: "default" },
  paid: { label: "Платена", variant: "success" },
};

export default function ChangeOrdersPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState("list");
  
  // Form state
  const [sites, setSites] = useState([]);
  const [workTypes, setWorkTypes] = useState([]);
  
  const [selectedSite, setSelectedSite] = useState("");
  const [selectedWorkType, setSelectedWorkType] = useState("");
  const [kind, setKind] = useState("new");
  const [deltaQty, setDeltaQty] = useState("");
  const [unit, setUnit] = useState("");
  const [laborDelta, setLaborDelta] = useState("");
  const [materialDelta, setMaterialDelta] = useState("");
  const [description, setDescription] = useState("");
  const [neededByDate, setNeededByDate] = useState("");
  
  // List state
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  
  // Detail dialog
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [showDetail, setShowDetail] = useState(false);
  
  // Check if user can approve
  const canApprove = user?.role === "Admin" || user?.role === "SiteManager";
  
  // Load initial data
  useEffect(() => {
    const loadData = async () => {
      try {
        const [sitesRes, workTypesRes] = await Promise.all([
          API.get("/my-sites"),
          API.get("/work-types"),
        ]);
        setSites(sitesRes.data.items || []);
        setWorkTypes(workTypesRes.data.items || []);
      } catch (err) {
        console.error("Failed to load initial data:", err);
      }
    };
    loadData();
  }, []);
  
  // Load orders
  const loadOrders = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, page_size: 10 });
      if (siteFilter) params.append("site_id", siteFilter);
      if (statusFilter) params.append("status", statusFilter);
      
      const res = await API.get(`/change-orders?${params.toString()}`);
      setOrders(res.data.items || []);
      setTotalPages(res.data.total_pages || 1);
    } catch (err) {
      console.error("Failed to load orders:", err);
    } finally {
      setLoading(false);
    }
  }, [page, siteFilter, statusFilter]);
  
  useEffect(() => {
    loadOrders();
  }, [loadOrders]);
  
  // Reset form
  const resetForm = () => {
    setSelectedSite("");
    setSelectedWorkType("");
    setKind("new");
    setDeltaQty("");
    setUnit("");
    setLaborDelta("");
    setMaterialDelta("");
    setDescription("");
    setNeededByDate("");
  };
  
  // Save as draft
  const handleSaveDraft = async () => {
    if (!selectedSite) {
      toast.error("Изберете обект");
      return;
    }
    if (!description.trim()) {
      toast.error("Въведете описание");
      return;
    }
    
    try {
      await API.post("/change-orders", {
        site_id: selectedSite,
        work_type_id: selectedWorkType || null,
        kind,
        delta_qty: deltaQty ? parseFloat(deltaQty) : null,
        unit: unit || null,
        labor_delta: parseFloat(laborDelta) || 0,
        material_delta: parseFloat(materialDelta) || 0,
        description,
        needed_by_date: neededByDate || null,
        attachments: [],
      });
      
      toast.success("Черновата е записана");
      resetForm();
      loadOrders();
      setActiveTab("list");
    } catch (err) {
      console.error("Failed to save draft:", err);
      toast.error(err.response?.data?.detail || "Грешка при записване");
    }
  };
  
  // Save and submit
  const handleSaveAndSubmit = async () => {
    if (!selectedSite) {
      toast.error("Изберете обект");
      return;
    }
    if (!description.trim()) {
      toast.error("Въведете описание");
      return;
    }
    
    try {
      const res = await API.post("/change-orders", {
        site_id: selectedSite,
        work_type_id: selectedWorkType || null,
        kind,
        delta_qty: deltaQty ? parseFloat(deltaQty) : null,
        unit: unit || null,
        labor_delta: parseFloat(laborDelta) || 0,
        material_delta: parseFloat(materialDelta) || 0,
        description,
        needed_by_date: neededByDate || null,
        attachments: [],
      });
      
      // Submit for approval
      await API.post(`/change-orders/${res.data.id}/submit`);
      
      toast.success("Изпратено за одобрение");
      resetForm();
      loadOrders();
      setActiveTab("list");
    } catch (err) {
      console.error("Failed to submit:", err);
      toast.error(err.response?.data?.detail || "Грешка при изпращане");
    }
  };
  
  // Submit existing draft
  const handleSubmit = async (orderId) => {
    try {
      await API.post(`/change-orders/${orderId}/submit`);
      toast.success("Изпратено за одобрение");
      loadOrders();
      setShowDetail(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    }
  };
  
  // Approve
  const handleApprove = async (orderId) => {
    try {
      await API.post(`/change-orders/${orderId}/approve`);
      toast.success("Промяната е одобрена");
      loadOrders();
      setShowDetail(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    }
  };
  
  // Reject
  const handleReject = async (orderId) => {
    const reason = prompt("Причина за отхвърляне (optional):");
    try {
      await API.post(`/change-orders/${orderId}/reject?reason=${encodeURIComponent(reason || "")}`);
      toast.success("Промяната е отхвърлена");
      loadOrders();
      setShowDetail(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    }
  };
  
  // Open detail
  const openDetail = (order) => {
    setSelectedOrder(order);
    setShowDetail(true);
  };
  
  // Calculate total
  const totalDelta = (parseFloat(laborDelta) || 0) + (parseFloat(materialDelta) || 0);
  
  return (
    <div className="p-4 md:p-6 space-y-4 max-w-4xl mx-auto" data-testid="change-orders-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center">
            <FilePlus2 className="w-5 h-5 text-amber-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold">Промени / СМР</h1>
            <p className="text-sm text-muted-foreground">Допълнения и промени по проекти</p>
          </div>
        </div>
      </div>
      
      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="list" data-testid="tab-list">
            <FileText className="w-4 h-4 mr-2" />
            Списък
          </TabsTrigger>
          <TabsTrigger value="new" data-testid="tab-new">
            <Plus className="w-4 h-4 mr-2" />
            Нова промяна
          </TabsTrigger>
        </TabsList>
        
        {/* New Change Order Form */}
        <TabsContent value="new" className="space-y-4 mt-4">
          <Card>
            <CardContent className="p-4 space-y-4">
              {/* Site Select */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <Building2 className="w-4 h-4" />
                  Обект *
                </Label>
                <Select value={selectedSite} onValueChange={setSelectedSite}>
                  <SelectTrigger data-testid="site-select">
                    <SelectValue placeholder="Изберете обект..." />
                  </SelectTrigger>
                  <SelectContent>
                    {sites.map(site => (
                      <SelectItem key={site.id} value={site.id}>
                        {site.code} - {site.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              
              {/* Kind */}
              <div className="space-y-2">
                <Label>Тип промяна *</Label>
                <div className="grid grid-cols-3 gap-2">
                  {KIND_OPTIONS.map(opt => (
                    <Button
                      key={opt.value}
                      variant={kind === opt.value ? "default" : "outline"}
                      className="flex flex-col h-auto py-3"
                      onClick={() => setKind(opt.value)}
                      data-testid={`kind-${opt.value}`}
                    >
                      <opt.icon className={`w-5 h-5 mb-1 ${kind === opt.value ? "" : opt.color}`} />
                      <span className="text-xs">{opt.label}</span>
                    </Button>
                  ))}
                </div>
              </div>
              
              {/* Work Type (optional) */}
              <div className="space-y-2">
                <Label>Вид работа (optional)</Label>
                <Select value={selectedWorkType} onValueChange={setSelectedWorkType}>
                  <SelectTrigger>
                    <SelectValue placeholder="Изберете..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">Без</SelectItem>
                    {workTypes.map(wt => (
                      <SelectItem key={wt.id} value={wt.id}>
                        {wt.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              
              {/* Quantity */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Количество (delta)</Label>
                  <Input
                    type="number"
                    value={deltaQty}
                    onChange={(e) => setDeltaQty(e.target.value)}
                    placeholder="напр. 10"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Мерна единица</Label>
                  <Input
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                    placeholder="напр. м², бр."
                  />
                </div>
              </div>
              
              {/* Deltas */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Hammer className="w-4 h-4" />
                    Труд (лв.)
                  </Label>
                  <Input
                    type="number"
                    value={laborDelta}
                    onChange={(e) => setLaborDelta(e.target.value)}
                    placeholder="0.00"
                    data-testid="labor-input"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Package className="w-4 h-4" />
                    Материали (лв.)
                  </Label>
                  <Input
                    type="number"
                    value={materialDelta}
                    onChange={(e) => setMaterialDelta(e.target.value)}
                    placeholder="0.00"
                    data-testid="material-input"
                  />
                </div>
              </div>
              
              {/* Total */}
              {totalDelta > 0 && (
                <div className="bg-muted/50 rounded-lg p-3 flex items-center justify-between">
                  <span className="text-sm">Общо:</span>
                  <span className="font-bold text-lg">{totalDelta.toFixed(2)} лв.</span>
                </div>
              )}
              
              {/* Description */}
              <div className="space-y-2">
                <Label>Описание *</Label>
                <Textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Опишете промяната..."
                  rows={4}
                  data-testid="description-input"
                />
              </div>
              
              {/* Needed by date */}
              <div className="space-y-2">
                <Label>Необходимо до (optional)</Label>
                <Input
                  type="date"
                  value={neededByDate}
                  onChange={(e) => setNeededByDate(e.target.value)}
                />
              </div>
              
              {/* Action Buttons */}
              <div className="grid grid-cols-2 gap-3 pt-2">
                <Button variant="outline" onClick={handleSaveDraft} data-testid="save-draft-btn">
                  <Save className="w-4 h-4 mr-2" />
                  Запази чернова
                </Button>
                <Button onClick={handleSaveAndSubmit} data-testid="submit-btn">
                  <Send className="w-4 h-4 mr-2" />
                  Изпрати за одобрение
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        
        {/* List View */}
        <TabsContent value="list" className="space-y-4 mt-4">
          {/* Filters */}
          <Card>
            <CardContent className="p-4">
              <div className="flex flex-col md:flex-row gap-4">
                <div className="flex-1">
                  <Label className="text-xs mb-1 block">Обект</Label>
                  <Select value={siteFilter || "all"} onValueChange={(v) => { setSiteFilter(v === "all" ? "" : v); setPage(1); }}>
                    <SelectTrigger>
                      <SelectValue placeholder="Всички обекти" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Всички обекти</SelectItem>
                      {sites.map(site => (
                        <SelectItem key={site.id} value={site.id}>
                          {site.code} - {site.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex-1">
                  <Label className="text-xs mb-1 block">Статус</Label>
                  <Select value={statusFilter || "all"} onValueChange={(v) => { setStatusFilter(v === "all" ? "" : v); setPage(1); }}>
                    <SelectTrigger>
                      <SelectValue placeholder="Всички статуси" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Всички</SelectItem>
                      <SelectItem value="draft">Чернова</SelectItem>
                      <SelectItem value="pending_approval">Чака одобрение</SelectItem>
                      <SelectItem value="approved">Одобрена</SelectItem>
                      <SelectItem value="rejected">Отхвърлена</SelectItem>
                      <SelectItem value="invoiced">Фактурирана</SelectItem>
                      <SelectItem value="paid">Платена</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardContent>
          </Card>
          
          {/* Orders List */}
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-6 h-6 animate-spin" />
                </div>
              ) : orders.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  Няма промени
                </div>
              ) : (
                <div className="divide-y">
                  {orders.map(order => {
                    const kindOpt = KIND_OPTIONS.find(k => k.value === order.kind);
                    const statusBadge = STATUS_BADGES[order.status] || { label: order.status, variant: "secondary" };
                    
                    return (
                      <div
                        key={order.id}
                        className="p-4 hover:bg-muted/30 cursor-pointer"
                        onClick={() => openDetail(order)}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              {kindOpt && <kindOpt.icon className={`w-4 h-4 ${kindOpt.color}`} />}
                              <span className="font-medium text-sm">{order.site_code}</span>
                              <Badge variant={statusBadge.variant === "warning" ? "outline" : statusBadge.variant} 
                                     className={statusBadge.variant === "warning" ? "border-amber-500 text-amber-500" : ""}>
                                {statusBadge.label}
                              </Badge>
                            </div>
                            <p className="text-sm text-muted-foreground truncate">{order.description}</p>
                            <p className="text-xs text-muted-foreground mt-1">
                              {order.site_name} • {new Date(order.requested_at).toLocaleDateString("bg-BG")}
                            </p>
                          </div>
                          <div className="text-right">
                            <p className="font-bold text-sm">{order.total_delta?.toFixed(2) || "0.00"} лв.</p>
                            <p className="text-xs text-muted-foreground">{order.created_by_name}</p>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
          
          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="text-sm">Страница {page} от {totalPages}</span>
              <Button variant="outline" size="sm" disabled={page === totalPages} onClick={() => setPage(p => p + 1)}>
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          )}
        </TabsContent>
      </Tabs>
      
      {/* Detail Dialog */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {selectedOrder && KIND_OPTIONS.find(k => k.value === selectedOrder.kind)?.icon && (
                (() => {
                  const KindIcon = KIND_OPTIONS.find(k => k.value === selectedOrder.kind).icon;
                  return <KindIcon className="w-5 h-5" />;
                })()
              )}
              Детайли на промяната
            </DialogTitle>
            <DialogDescription>
              {selectedOrder?.site_code} - {selectedOrder?.site_name}
            </DialogDescription>
          </DialogHeader>
          
          {selectedOrder && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-muted-foreground">Тип</p>
                  <p className="font-medium">{KIND_OPTIONS.find(k => k.value === selectedOrder.kind)?.label}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Статус</p>
                  <Badge variant={STATUS_BADGES[selectedOrder.status]?.variant || "secondary"}>
                    {STATUS_BADGES[selectedOrder.status]?.label || selectedOrder.status}
                  </Badge>
                </div>
                <div>
                  <p className="text-muted-foreground">Труд</p>
                  <p className="font-medium">{selectedOrder.labor_delta?.toFixed(2)} лв.</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Материали</p>
                  <p className="font-medium">{selectedOrder.material_delta?.toFixed(2)} лв.</p>
                </div>
                <div className="col-span-2">
                  <p className="text-muted-foreground">Общо</p>
                  <p className="font-bold text-lg">{selectedOrder.total_delta?.toFixed(2)} лв.</p>
                </div>
              </div>
              
              <div>
                <p className="text-muted-foreground text-sm mb-1">Описание</p>
                <p className="text-sm bg-muted/50 p-3 rounded">{selectedOrder.description}</p>
              </div>
              
              <div className="text-xs text-muted-foreground">
                Създадено от: {selectedOrder.created_by_name} на {new Date(selectedOrder.requested_at).toLocaleString("bg-BG")}
              </div>
              
              {selectedOrder.approved_by_name && (
                <div className="text-xs text-green-500">
                  Одобрено от: {selectedOrder.approved_by_name} на {new Date(selectedOrder.approved_at).toLocaleString("bg-BG")}
                </div>
              )}
              
              {selectedOrder.rejection_reason && (
                <div className="text-xs text-red-500">
                  Причина за отхвърляне: {selectedOrder.rejection_reason}
                </div>
              )}
            </div>
          )}
          
          <DialogFooter className="flex-col sm:flex-row gap-2">
            {selectedOrder?.status === "draft" && (
              <Button onClick={() => handleSubmit(selectedOrder.id)} className="w-full sm:w-auto">
                <Send className="w-4 h-4 mr-2" />
                Изпрати за одобрение
              </Button>
            )}
            
            {selectedOrder?.status === "pending_approval" && canApprove && (
              <>
                <Button variant="outline" onClick={() => handleReject(selectedOrder.id)} className="w-full sm:w-auto">
                  <XCircle className="w-4 h-4 mr-2" />
                  Отхвърли
                </Button>
                <Button onClick={() => handleApprove(selectedOrder.id)} className="w-full sm:w-auto">
                  <CheckCircle className="w-4 h-4 mr-2" />
                  Одобри
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
