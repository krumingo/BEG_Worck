/**
 * MissingSMRPage - Липсващи / Допълнителни СМР
 *
 * Features:
 * - Table of all missing/additional SMR records
 * - Filters: project, status, date, floor, room
 * - Create new record via modal
 * - Status transitions, bridge to analysis/offer
 * - Attachment upload via media API
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
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
  AlertTriangle,
  Plus,
  Loader2,
  Search,
  FileText,
  FlaskConical,
  FileOutput,
  Trash2,
  ImagePlus,
  X,
  ChevronRight,
  ArrowRightLeft,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CONFIG = {
  draft: { label: "Чернова", variant: "secondary", color: "bg-slate-100 text-slate-700" },
  reported: { label: "Докладвано", variant: "outline", color: "bg-blue-50 text-blue-700 border-blue-200" },
  reviewed: { label: "Прегледано", variant: "outline", color: "bg-amber-50 text-amber-700 border-amber-200" },
  executed: { label: "Извършено", variant: "outline", color: "bg-orange-50 text-orange-700 border-orange-200" },
  approved_by_client: { label: "Одобрено", variant: "outline", color: "bg-green-50 text-green-700 border-green-200" },
  rejected_by_client: { label: "Отказано", variant: "outline", color: "bg-red-50 text-red-700 border-red-200" },
  analyzed: { label: "Анализирано", variant: "outline", color: "bg-purple-50 text-purple-700 border-purple-200" },
  offered: { label: "Оферирано", variant: "outline", color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  closed: { label: "Затворено", variant: "secondary", color: "bg-zinc-100 text-zinc-500" },
};

const SOURCE_LABELS = {
  web: "Уеб",
  mobile: "Мобилно",
  daily_report: "Дневен отчет",
  change_order: "Промяна СМР",
};

const EMPTY_FORM = {
  project_id: "",
  floor: "",
  room: "",
  zone: "",
  notes: "",
  smr_type: "",
  activity_type: "",
  activity_subtype: "",
  qty: "1",
  unit: "m2",
  labor_hours_est: "",
  material_notes: "",
  source: "web",
  urgency_type: "planned",
  emergency_reason: "",
  executed_date: "",
  executed_by: "",
};

export default function MissingSMRPage() {
  const { t } = useTranslation();
  const { user } = useAuth();

  // Data
  const [items, setItems] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(false);

  // Filters
  const [fProject, setFProject] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fFloor, setFFloor] = useState("");
  const [fRoom, setFRoom] = useState("");
  const [fDateFrom, setFDateFrom] = useState("");
  const [fDateTo, setFDateTo] = useState("");
  const [fUrgency, setFUrgency] = useState("");

  // Create modal
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);

  // Detail modal
  const [selected, setSelected] = useState(null);
  const [showDetail, setShowDetail] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // Upload state
  const [uploading, setUploading] = useState(false);

  const canEdit = ["Admin", "Owner", "SiteManager"].includes(user?.role);

  // Load projects once
  useEffect(() => {
    API.get("/projects").then((r) => setProjects(r.data.items || r.data || [])).catch(() => {});
  }, []);

  // Load items
  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (fProject) params.append("project_id", fProject);
      if (fStatus) params.append("status", fStatus);
      if (fFloor) params.append("floor", fFloor);
      if (fRoom) params.append("room", fRoom);
      if (fDateFrom) params.append("date_from", fDateFrom);
      if (fDateTo) params.append("date_to", fDateTo);
      if (fUrgency) params.append("urgency_type", fUrgency);
      const res = await API.get(`/missing-smr?${params.toString()}`);
      setItems(res.data.items || []);
    } catch {
      toast.error(t("missingSMR.loadError"));
    } finally {
      setLoading(false);
    }
  }, [fProject, fStatus, fFloor, fRoom, fDateFrom, fDateTo, fUrgency, t]);

  useEffect(() => { loadItems(); }, [loadItems]);

  // Create
  const handleCreate = async () => {
    if (!form.project_id) { toast.error(t("missingSMR.selectProject")); return; }
    if (!form.smr_type && !form.activity_type) { toast.error(t("missingSMR.enterType")); return; }
    setSaving(true);
    try {
      const payload = {
        ...form,
        qty: parseFloat(form.qty) || 1,
        labor_hours_est: form.labor_hours_est ? parseFloat(form.labor_hours_est) : null,
      };
      await API.post("/missing-smr", payload);
      toast.success(t("missingSMR.created"));
      setShowCreate(false);
      setForm({ ...EMPTY_FORM });
      loadItems();
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    } finally {
      setSaving(false);
    }
  };

  // Status change
  const handleStatus = async (id, newStatus) => {
    setActionLoading(true);
    try {
      const res = await API.put(`/missing-smr/${id}/status`, { status: newStatus });
      setSelected(res.data);
      toast.success(t("missingSMR.statusUpdated"));
      loadItems();
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    } finally {
      setActionLoading(false);
    }
  };

  // Bridge to analysis
  const handleToAnalysis = async (id) => {
    setActionLoading(true);
    try {
      const res = await API.post(`/missing-smr/${id}/to-analysis`);
      setSelected(res.data.missing_smr);
      toast.success(t("missingSMR.sentToAnalysis"));
      loadItems();
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    } finally {
      setActionLoading(false);
    }
  };

  // Bridge to offer
  const handleToOffer = async (id) => {
    setActionLoading(true);
    try {
      const res = await API.post(`/missing-smr/${id}/to-offer`);
      setSelected(res.data.missing_smr);
      toast.success(`${t("missingSMR.offerCreated")}: ${res.data.offer_no}`);
      loadItems();
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    } finally {
      setActionLoading(false);
    }
  };

  // Delete
  const handleDelete = async (id) => {
    if (!window.confirm(t("missingSMR.confirmDelete"))) return;
    try {
      await API.delete(`/missing-smr/${id}`);
      toast.success(t("missingSMR.deleted"));
      setShowDetail(false);
      setSelected(null);
      loadItems();
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    }
  };

  // Upload attachment
  const handleUpload = async (e) => {
    if (!selected) return;
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("context_type", "project");
      fd.append("context_id", selected.project_id);
      const uploadRes = await API.post("/media/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const { id: media_id, url, filename } = uploadRes.data;
      const res = await API.post(`/missing-smr/${selected.id}/attachments`, {
        media_id, url, filename: filename || file.name,
      });
      setSelected(res.data);
      toast.success(t("missingSMR.photoAdded"));
    } catch (err) {
      toast.error(err.response?.data?.detail || t("missingSMR.uploadError"));
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  // Remove attachment
  const handleRemoveAttachment = async (mediaId) => {
    if (!selected) return;
    try {
      const res = await API.delete(`/missing-smr/${selected.id}/attachments/${mediaId}`);
      setSelected(res.data);
    } catch (err) {
      toast.error(t("common.error"));
    }
  };

  const openDetail = (item) => { setSelected(item); setShowDetail(true); };

  // New flow handlers
  const handleExecute = async (id) => {
    setActionLoading(true);
    try {
      const res = await API.put(`/missing-smr/${id}/execute`, { executed_date: new Date().toISOString().slice(0, 10) });
      setSelected(res.data);
      toast.success(t("missingSMR.executed"));
      loadItems();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleRequestApproval = async (id) => {
    const name = prompt(t("missingSMR.clientName"));
    if (!name) return;
    setActionLoading(true);
    try {
      const res = await API.post(`/missing-smr/${id}/request-approval`, { client_name: name });
      setSelected(res.data);
      toast.success(t("missingSMR.requestApproval"));
      loadItems();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleClientApprove = async (id) => {
    setActionLoading(true);
    try {
      const res = await API.put(`/missing-smr/${id}/client-approve`, {});
      setSelected(res.data);
      toast.success(t("missingSMR.approvedByClient"));
      loadItems();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleClientReject = async (id) => {
    const notes = prompt(t("missingSMR.clientReject"));
    setActionLoading(true);
    try {
      const res = await API.put(`/missing-smr/${id}/client-reject`, { client_notes: notes || "" });
      setSelected(res.data);
      toast.success(t("missingSMR.rejectedByClient"));
      loadItems();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleAIEstimate = async (id) => {
    setActionLoading(true);
    try {
      const res = await API.post(`/missing-smr/${id}/ai-estimate`);
      setSelected(res.data.item);
      toast.success(`${t("missingSMR.aiEstimated")}: ${res.data.estimated_price} лв`);
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const setField = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-6xl mx-auto" data-testid="missing-smr-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-orange-500/10 flex items-center justify-center">
            <AlertTriangle className="w-5 h-5 text-orange-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold" data-testid="page-title">
              {t("missingSMR.title")}
            </h1>
            <p className="text-sm text-muted-foreground">{t("missingSMR.subtitle")}</p>
          </div>
        </div>
        {canEdit && (
          <Button onClick={() => setShowCreate(true)} data-testid="new-record-btn">
            <Plus className="w-4 h-4 mr-2" />
            {t("missingSMR.newRecord")}
          </Button>
        )}
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <div>
              <Label className="text-xs mb-1 block">{t("missingSMR.project")}</Label>
              <Select value={fProject || "all"} onValueChange={(v) => setFProject(v === "all" ? "" : v)}>
                <SelectTrigger data-testid="filter-project">
                  <SelectValue placeholder={t("common.all")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.code || p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs mb-1 block">{t("common.status")}</Label>
              <Select value={fStatus || "all"} onValueChange={(v) => setFStatus(v === "all" ? "" : v)}>
                <SelectTrigger data-testid="filter-status">
                  <SelectValue placeholder={t("common.all")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs mb-1 block">{t("missingSMR.floor")}</Label>
              <Input
                value={fFloor}
                onChange={(e) => setFFloor(e.target.value)}
                placeholder="1, 2..."
                data-testid="filter-floor"
              />
            </div>
            <div>
              <Label className="text-xs mb-1 block">{t("missingSMR.room")}</Label>
              <Input
                value={fRoom}
                onChange={(e) => setFRoom(e.target.value)}
                placeholder={t("missingSMR.roomPlaceholder")}
                data-testid="filter-room"
              />
            </div>
            <div>
              <Label className="text-xs mb-1 block">{t("missingSMR.dateFrom")}</Label>
              <Input type="date" value={fDateFrom} onChange={(e) => setFDateFrom(e.target.value)} data-testid="filter-date-from" />
            </div>
            <div>
              <Label className="text-xs mb-1 block">{t("missingSMR.dateTo")}</Label>
              <Input type="date" value={fDateTo} onChange={(e) => setFDateTo(e.target.value)} data-testid="filter-date-to" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin" />
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
              <Search className="w-8 h-8 opacity-40" />
              <p className="text-sm">{t("missingSMR.noItems")}</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("missingSMR.project")}</TableHead>
                    <TableHead>{t("missingSMR.type")}</TableHead>
                    <TableHead>{t("missingSMR.location")}</TableHead>
                    <TableHead className="text-center">{t("missingSMR.qty")}</TableHead>
                    <TableHead>{t("common.status")}</TableHead>
                    <TableHead>{t("missingSMR.source")}</TableHead>
                    <TableHead>{t("common.date")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => {
                    const st = STATUS_CONFIG[item.status] || STATUS_CONFIG.draft;
                    const loc = [item.floor && `Ет.${item.floor}`, item.room, item.zone].filter(Boolean).join(", ");
                    return (
                      <TableRow
                        key={item.id}
                        className="cursor-pointer hover:bg-muted/40"
                        onClick={() => openDetail(item)}
                        data-testid={`smr-row-${item.id}`}
                      >
                        <TableCell className="font-medium text-sm">{item.project_name || item.project_id?.slice(0, 8)}</TableCell>
                        <TableCell className="text-sm">{item.smr_type || item.activity_type || "-"}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">{loc || "-"}</TableCell>
                        <TableCell className="text-center text-sm">{item.qty} {item.unit}</TableCell>
                        <TableCell>
                          <Badge className={`text-xs ${st.color}`} variant={st.variant}>
                            {st.label}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{SOURCE_LABELS[item.source] || item.source}</TableCell>
                        <TableCell className="text-xs">
                          {item.urgency_type === "emergency" ? (
                            <Badge variant="outline" className="text-[9px] bg-red-50 text-red-600 border-red-200">{t("missingSMR.emergency")}</Badge>
                          ) : (
                            <Badge variant="outline" className="text-[9px] bg-blue-50 text-blue-600 border-blue-200">{t("missingSMR.planned")}</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(item.created_at).toLocaleDateString("bg-BG")}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ─── Create Modal ───────────────────────────────────────── */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("missingSMR.newRecord")}</DialogTitle>
            <DialogDescription>{t("missingSMR.newRecordDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {/* Project */}
            <div className="space-y-1">
              <Label>{t("missingSMR.project")} *</Label>
              <Select value={form.project_id || "none"} onValueChange={(v) => setField("project_id", v === "none" ? "" : v)}>
                <SelectTrigger data-testid="create-project-select">
                  <SelectValue placeholder={t("missingSMR.selectProject")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("missingSMR.selectProject")}</SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.code ? `${p.code} - ${p.name}` : p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* SMR Type / Activity */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>{t("missingSMR.smrType")} *</Label>
                <Input value={form.smr_type} onChange={(e) => setField("smr_type", e.target.value)} placeholder={t("missingSMR.smrTypePlaceholder")} data-testid="create-smr-type" />
              </div>
              <div className="space-y-1">
                <Label>{t("missingSMR.activityType")}</Label>
                <Input value={form.activity_type} onChange={(e) => setField("activity_type", e.target.value)} placeholder={t("missingSMR.activityTypePlaceholder")} />
              </div>
            </div>
            <div className="space-y-1">
              <Label>{t("missingSMR.activitySubtype")}</Label>
              <Input value={form.activity_subtype} onChange={(e) => setField("activity_subtype", e.target.value)} placeholder={t("missingSMR.activitySubtypePlaceholder")} />
            </div>

            {/* Location */}
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label>{t("missingSMR.floor")}</Label>
                <Input value={form.floor} onChange={(e) => setField("floor", e.target.value)} placeholder="1" data-testid="create-floor" />
              </div>
              <div className="space-y-1">
                <Label>{t("missingSMR.room")}</Label>
                <Input value={form.room} onChange={(e) => setField("room", e.target.value)} placeholder={t("missingSMR.roomPlaceholder")} data-testid="create-room" />
              </div>
              <div className="space-y-1">
                <Label>{t("missingSMR.zone")}</Label>
                <Input value={form.zone} onChange={(e) => setField("zone", e.target.value)} placeholder={t("missingSMR.zonePlaceholder")} />
              </div>
            </div>

            {/* Qty + Unit */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>{t("missingSMR.qty")}</Label>
                <Input type="number" value={form.qty} onChange={(e) => setField("qty", e.target.value)} min="0" step="0.01" data-testid="create-qty" />
              </div>
              <div className="space-y-1">
                <Label>{t("missingSMR.unit")}</Label>
                <Input value={form.unit} onChange={(e) => setField("unit", e.target.value)} placeholder="m2, бр., м.л." data-testid="create-unit" />
              </div>
            </div>

            {/* Labor + Material notes */}
            <div className="space-y-1">
              <Label>{t("missingSMR.laborHoursEst")}</Label>
              <Input type="number" value={form.labor_hours_est} onChange={(e) => setField("labor_hours_est", e.target.value)} placeholder="0" min="0" step="0.5" />
            </div>
            <div className="space-y-1">
              <Label>{t("missingSMR.materialNotes")}</Label>
              <Textarea value={form.material_notes} onChange={(e) => setField("material_notes", e.target.value)} placeholder={t("missingSMR.materialNotesPlaceholder")} rows={2} />
            </div>

            {/* Notes */}
            <div className="space-y-1">
              <Label>{t("missingSMR.notes")}</Label>
              <Textarea value={form.notes} onChange={(e) => setField("notes", e.target.value)} placeholder={t("missingSMR.notesPlaceholder")} rows={3} data-testid="create-notes" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleCreate} disabled={saving} data-testid="create-submit-btn">
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Plus className="w-4 h-4 mr-2" />}
              {t("common.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Detail Modal ───────────────────────────────────────── */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="w-5 h-5" />
              {t("missingSMR.detailTitle")}
            </DialogTitle>
            <DialogDescription>
              {selected?.project_name || selected?.project_id?.slice(0, 8)}
            </DialogDescription>
          </DialogHeader>

          {selected && (
            <div className="space-y-4">
              {/* Status badge */}
              <div className="flex items-center justify-between">
                <Badge className={`${STATUS_CONFIG[selected.status]?.color || ""}`} variant={STATUS_CONFIG[selected.status]?.variant}>
                  {STATUS_CONFIG[selected.status]?.label || selected.status}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {SOURCE_LABELS[selected.source] || selected.source} | {new Date(selected.created_at).toLocaleString("bg-BG")}
                </span>
              </div>

              {/* Info grid */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-muted-foreground">{t("missingSMR.smrType")}</p>
                  <p className="font-medium">{selected.smr_type || "-"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("missingSMR.activityType")}</p>
                  <p className="font-medium">{selected.activity_type || "-"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("missingSMR.location")}</p>
                  <p className="font-medium">
                    {[selected.floor && `Ет.${selected.floor}`, selected.room, selected.zone].filter(Boolean).join(", ") || "-"}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("missingSMR.qty")}</p>
                  <p className="font-medium">{selected.qty} {selected.unit}</p>
                </div>
                {selected.labor_hours_est != null && (
                  <div>
                    <p className="text-muted-foreground">{t("missingSMR.laborHoursEst")}</p>
                    <p className="font-medium">{selected.labor_hours_est}ч</p>
                  </div>
                )}
                <div>
                  <p className="text-muted-foreground">{t("missingSMR.createdBy")}</p>
                  <p className="font-medium">{selected.created_by_name || "-"}</p>
                </div>
              </div>

              {/* Notes */}
              {selected.notes && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">{t("missingSMR.notes")}</p>
                  <p className="text-sm bg-muted/50 p-3 rounded">{selected.notes}</p>
                </div>
              )}
              {selected.material_notes && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">{t("missingSMR.materialNotes")}</p>
                  <p className="text-sm bg-muted/50 p-3 rounded">{selected.material_notes}</p>
                </div>
              )}

              {/* Attachments */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-muted-foreground">{t("missingSMR.attachments")} ({selected.attachments?.length || 0})</p>
                  {canEdit && ["draft", "reported", "reviewed"].includes(selected.status) && (
                    <label className="cursor-pointer">
                      <input type="file" accept="image/*" className="hidden" onChange={handleUpload} data-testid="upload-input" />
                      <Button variant="outline" size="sm" asChild disabled={uploading}>
                        <span>
                          {uploading ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <ImagePlus className="w-3 h-3 mr-1" />}
                          {t("missingSMR.addPhoto")}
                        </span>
                      </Button>
                    </label>
                  )}
                </div>
                {selected.attachments?.length > 0 && (
                  <div className="grid grid-cols-3 gap-2">
                    {selected.attachments.map((att) => (
                      <div key={att.media_id} className="relative group rounded-lg overflow-hidden border">
                        <img
                          src={`${process.env.REACT_APP_BACKEND_URL}${att.url}`}
                          alt={att.filename}
                          className="w-full h-20 object-cover"
                        />
                        {canEdit && ["draft", "reported"].includes(selected.status) && (
                          <button
                            className="absolute top-1 right-1 bg-black/60 text-white rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                            onClick={(e) => { e.stopPropagation(); handleRemoveAttachment(att.media_id); }}
                          >
                            <X className="w-3 h-3" />
                          </button>
                        )}
                        <p className="text-[10px] truncate px-1 py-0.5">{att.filename}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Linked refs */}
              {selected.linked_extra_work_id && (
                <div className="text-xs text-purple-600 flex items-center gap-1">
                  <ArrowRightLeft className="w-3 h-3" />
                  {t("missingSMR.linkedAnalysis")}: {selected.linked_extra_work_id.slice(0, 8)}...
                </div>
              )}
              {selected.linked_offer_id && (
                <div className="text-xs text-emerald-600 flex items-center gap-1">
                  <ArrowRightLeft className="w-3 h-3" />
                  {t("missingSMR.linkedOffer")}: {selected.linked_offer_id.slice(0, 8)}...
                </div>
              )}
            </div>
          )}

          <DialogFooter className="flex-col sm:flex-row gap-2 pt-2">
            {selected && canEdit && (
              <>
                {/* Delete (only draft) */}
                {selected.status === "draft" && (
                  <Button variant="destructive" size="sm" onClick={() => handleDelete(selected.id)} data-testid="detail-delete-btn">
                    <Trash2 className="w-4 h-4 mr-1" /> {t("common.delete")}
                  </Button>
                )}

                {/* Common: Draft → Reported */}
                {selected.status === "draft" && (
                  <Button variant="outline" size="sm" disabled={actionLoading} onClick={() => handleStatus(selected.id, "reported")} data-testid="status-reported-btn">
                    <ChevronRight className="w-4 h-4 mr-1" /> {t("missingSMR.markReported")}
                  </Button>
                )}

                {/* EMERGENCY flow */}
                {selected.urgency_type === "emergency" && selected.status === "reported" && (
                  <Button size="sm" variant="outline" disabled={actionLoading} onClick={() => handleExecute(selected.id)} data-testid="execute-btn">
                    <ChevronRight className="w-4 h-4 mr-1" /> {t("missingSMR.markExecuted")}
                  </Button>
                )}

                {/* PLANNED flow */}
                {(selected.urgency_type || "planned") === "planned" && selected.status === "reported" && (
                  <Button variant="outline" size="sm" disabled={actionLoading} onClick={() => handleStatus(selected.id, "reviewed")} data-testid="status-reviewed-btn">
                    <ChevronRight className="w-4 h-4 mr-1" /> {t("missingSMR.markReviewed")}
                  </Button>
                )}
                {(selected.urgency_type || "planned") === "planned" && selected.status === "reviewed" && !selected.client_approval && (
                  <Button size="sm" variant="outline" disabled={actionLoading} onClick={() => handleRequestApproval(selected.id)} data-testid="request-approval-btn">
                    {t("missingSMR.requestApproval")}
                  </Button>
                )}
                {selected.status === "reviewed" && selected.client_approval?.status === "pending" && (
                  <>
                    <Button size="sm" disabled={actionLoading} onClick={() => handleClientApprove(selected.id)} data-testid="client-approve-btn">
                      {t("missingSMR.clientApprove")}
                    </Button>
                    <Button size="sm" variant="destructive" disabled={actionLoading} onClick={() => handleClientReject(selected.id)} data-testid="client-reject-btn">
                      {t("missingSMR.clientReject")}
                    </Button>
                  </>
                )}

                {/* AI Estimate (any status before offered) */}
                {!["offered", "closed"].includes(selected.status) && (
                  <Button size="sm" variant="outline" disabled={actionLoading} onClick={() => handleAIEstimate(selected.id)} data-testid="ai-estimate-btn">
                    {t("missingSMR.aiEstimate")}
                  </Button>
                )}

                {/* Bridge: To Analysis */}
                {["reported", "reviewed", "executed", "approved_by_client"].includes(selected.status) && (
                  <Button size="sm" variant="outline" disabled={actionLoading} onClick={() => handleToAnalysis(selected.id)} data-testid="to-analysis-btn">
                    <FlaskConical className="w-4 h-4 mr-1" /> {t("missingSMR.toAnalysis")}
                  </Button>
                )}
                {/* Bridge: To Offer */}
                {["reviewed", "analyzed", "executed", "approved_by_client"].includes(selected.status) && (
                  <Button size="sm" disabled={actionLoading} onClick={() => handleToOffer(selected.id)} data-testid="to-offer-btn">
                    <FileOutput className="w-4 h-4 mr-1" /> {t("missingSMR.toOffer")}
                  </Button>
                )}

                {/* Close */}
                {!["closed", "rejected_by_client"].includes(selected.status) && (
                  <Button variant="ghost" size="sm" disabled={actionLoading} onClick={() => handleStatus(selected.id, "closed")} data-testid="status-close-btn">
                    <X className="w-4 h-4 mr-1" /> {t("missingSMR.close")}
                  </Button>
                )}
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
