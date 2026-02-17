import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
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
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  ArrowLeft,
  Plus,
  Trash2,
  Send,
  Save,
  Loader2,
  Copy,
  Check,
  X,
  FileText,
  Calculator,
  Printer,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Sent: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Accepted: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Rejected: "bg-red-500/20 text-red-400 border-red-500/30",
};

const UNITS = ["m2", "m", "pcs", "hours", "lot", "kg", "l"];

export default function OfferEditorPage() {
  const { t } = useTranslation();
  const { offerId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const projectIdParam = searchParams.get("projectId") || "";

  const isNew = !offerId || offerId === "new";
  const canManage = ["Admin", "Owner", "SiteManager"].includes(user?.role);
  const canAcceptReject = ["Admin", "Owner"].includes(user?.role);

  const [offer, setOffer] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Form state
  const [projectId, setProjectId] = useState(projectIdParam);
  const [title, setTitle] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [vatPercent, setVatPercent] = useState(20);
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState([]);

  // Dialogs
  const [activityDialogOpen, setActivityDialogOpen] = useState(false);
  const [selectedLineIndex, setSelectedLineIndex] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const projectsRes = await API.get("/projects");
      setProjects(projectsRes.data);

      if (!isNew) {
        const offerRes = await API.get(`/offers/${offerId}`);
        setOffer(offerRes.data);
        setProjectId(offerRes.data.project_id);
        setTitle(offerRes.data.title);
        setCurrency(offerRes.data.currency);
        setVatPercent(offerRes.data.vat_percent);
        setNotes(offerRes.data.notes || "");
        setLines(offerRes.data.lines || []);

        // Load activities for the project
        const activitiesRes = await API.get(`/activity-catalog?project_id=${offerRes.data.project_id}`);
        setActivities(activitiesRes.data);
      } else if (projectIdParam) {
        const activitiesRes = await API.get(`/activity-catalog?project_id=${projectIdParam}`);
        setActivities(activitiesRes.data);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [offerId, isNew, projectIdParam]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Load activities when project changes
  useEffect(() => {
    if (projectId && isNew) {
      API.get(`/activity-catalog?project_id=${projectId}`)
        .then(res => setActivities(res.data))
        .catch(() => setActivities([]));
    }
  }, [projectId, isNew]);

  const computeLineTotals = (line) => {
    const qty = parseFloat(line.qty) || 0;
    const material = parseFloat(line.material_unit_cost) || 0;
    const labor = parseFloat(line.labor_unit_cost) || 0;
    const lineMaterial = qty * material;
    const lineLabor = qty * labor;
    return {
      ...line,
      line_material_cost: lineMaterial,
      line_labor_cost: lineLabor,
      line_total: lineMaterial + lineLabor,
    };
  };

  const computedLines = lines.map(computeLineTotals);
  const subtotal = computedLines.reduce((sum, l) => sum + (l.line_total || 0), 0);
  const vatAmount = subtotal * (vatPercent / 100);
  const total = subtotal + vatAmount;

  const addLine = () => {
    setLines([...lines, {
      id: Date.now().toString(),
      activity_code: "",
      activity_name: "",
      unit: "pcs",
      qty: 1,
      material_unit_cost: 0,
      labor_unit_cost: 0,
      labor_hours_per_unit: null,
      note: "",
      sort_order: lines.length,
    }]);
  };

  const removeLine = (idx) => {
    setLines(lines.filter((_, i) => i !== idx));
  };

  const updateLine = (idx, field, value) => {
    const updated = [...lines];
    updated[idx] = { ...updated[idx], [field]: value };
    setLines(updated);
  };

  const openActivityPicker = (idx) => {
    setSelectedLineIndex(idx);
    setActivityDialogOpen(true);
  };

  const selectActivity = (activity) => {
    if (selectedLineIndex !== null) {
      const updated = [...lines];
      updated[selectedLineIndex] = {
        ...updated[selectedLineIndex],
        activity_code: activity.code || "",
        activity_name: activity.name,
        unit: activity.default_unit,
        material_unit_cost: activity.default_material_unit_cost,
        labor_unit_cost: activity.default_labor_unit_cost,
        labor_hours_per_unit: activity.default_labor_hours_per_unit,
      };
      setLines(updated);
    }
    setActivityDialogOpen(false);
  };

  const handleSave = async () => {
    if (!projectId || !title) {
      alert(t("offers.projectTitleRequired"));
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const res = await API.post("/offers", {
          project_id: projectId,
          title,
          currency,
          vat_percent: vatPercent,
          notes,
          lines: lines.map((l, i) => ({
            activity_code: l.activity_code || null,
            activity_name: l.activity_name,
            unit: l.unit,
            qty: parseFloat(l.qty) || 0,
            material_unit_cost: parseFloat(l.material_unit_cost) || 0,
            labor_unit_cost: parseFloat(l.labor_unit_cost) || 0,
            labor_hours_per_unit: l.labor_hours_per_unit ? parseFloat(l.labor_hours_per_unit) : null,
            note: l.note || "",
            sort_order: i,
          })),
        });
        navigate(`/offers/${res.data.id}`, { replace: true });
      } else {
        await API.put(`/offers/${offerId}`, { title, currency, vat_percent: vatPercent, notes });
        await API.put(`/offers/${offerId}/lines`, {
          lines: lines.map((l, i) => ({
            activity_code: l.activity_code || null,
            activity_name: l.activity_name,
            unit: l.unit,
            qty: parseFloat(l.qty) || 0,
            material_unit_cost: parseFloat(l.material_unit_cost) || 0,
            labor_unit_cost: parseFloat(l.labor_unit_cost) || 0,
            labor_hours_per_unit: l.labor_hours_per_unit ? parseFloat(l.labor_hours_per_unit) : null,
            note: l.note || "",
            sort_order: i,
          })),
        });
        await fetchData();
      }
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleSend = async () => {
    if (lines.length === 0) {
      alert(t("offers.addLineBeforeSend"));
      return;
    }
    setSaving(true);
    try {
      await API.post(`/offers/${offerId}/send`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setSaving(false);
    }
  };

  const handleAccept = async () => {
    setSaving(true);
    try {
      await API.post(`/offers/${offerId}/accept`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setSaving(false);
    }
  };

  const handleReject = async () => {
    const reason = prompt(t("offers.rejectionReasonPrompt"));
    setSaving(true);
    try {
      await API.post(`/offers/${offerId}/reject`, { reason });
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setSaving(false);
    }
  };

  const handleNewVersion = async () => {
    setSaving(true);
    try {
      const res = await API.post(`/offers/${offerId}/new-version`);
      navigate(`/offers/${res.data.id}`, { replace: true });
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setSaving(false);
    }
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "EUR" }).format(amount || 0);
  };

  const isDraft = !offer || offer.status === "Draft";
  const canEdit = isDraft && canManage;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px]" data-testid="offer-editor-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/offers")} data-testid="back-btn">
            <ArrowLeft className="w-4 h-4 mr-1" /> {t("common.back")}
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-foreground">
                {isNew ? t("offers.newOffer") : `${offer?.offer_no}`}
              </h1>
              {offer && (
                <>
                  <Badge variant="outline" className={`text-xs ${STATUS_COLORS[offer.status] || ""}`}>
                    {t(`offers.status.${offer.status.toLowerCase()}`)}
                  </Badge>
                  <span className="text-sm text-muted-foreground">v{offer.version}</span>
                </>
              )}
            </div>
            {offer && <p className="text-sm text-muted-foreground">{offer.project_code} - {offer.project_name}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canEdit && (
            <>
              <Button variant="outline" onClick={handleSave} disabled={saving} data-testid="save-btn">
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />}
                {t("common.save")}
              </Button>
              {!isNew && (
                <Button onClick={handleSend} disabled={saving || lines.length === 0} data-testid="send-btn">
                  <Send className="w-4 h-4 mr-1" /> {t("common.send")}
                </Button>
              )}
            </>
          )}
          {offer?.status === "Sent" && canAcceptReject && (
            <>
              <Button variant="outline" className="text-emerald-400 border-emerald-500/30" onClick={handleAccept} disabled={saving} data-testid="accept-btn">
                <Check className="w-4 h-4 mr-1" /> {t("common.accept")}
              </Button>
              <Button variant="outline" className="text-red-400 border-red-500/30" onClick={handleReject} disabled={saving} data-testid="reject-btn">
                <X className="w-4 h-4 mr-1" /> {t("common.reject")}
              </Button>
            </>
          )}
          {offer && offer.status !== "Draft" && canManage && (
            <Button variant="outline" onClick={handleNewVersion} disabled={saving} data-testid="new-version-btn">
              <Copy className="w-4 h-4 mr-1" /> {t("offers.newVersion")}
            </Button>
          )}
          {offer && (
            <Button variant="ghost" size="sm" onClick={() => window.print()} data-testid="print-btn">
              <Printer className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-3 space-y-6">
          {/* Basic Info */}
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" /> {t("offers.offerDetails")}
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("offers.project")} *</Label>
                <Select value={projectId} onValueChange={setProjectId} disabled={!isNew}>
                  <SelectTrigger className="bg-background" data-testid="project-select">
                    <SelectValue placeholder={t("workReports.selectProject")} />
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("offers.offerTitle")} *</Label>
                <Input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={t("offers.offerTitle")}
                  disabled={!canEdit}
                  className="bg-background"
                  data-testid="title-input"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("offers.currency")}</Label>
                <Select value={currency} onValueChange={setCurrency} disabled={!canEdit}>
                  <SelectTrigger className="bg-background" data-testid="currency-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="EUR">EUR</SelectItem>
                    <SelectItem value="USD">USD</SelectItem>
                    <SelectItem value="BGN">BGN</SelectItem>
                    <SelectItem value="GBP">GBP</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("offers.vatPercent")}</Label>
                <Input
                  type="number"
                  value={vatPercent}
                  onChange={(e) => setVatPercent(parseFloat(e.target.value) || 0)}
                  disabled={!canEdit}
                  className="bg-background"
                  data-testid="vat-input"
                />
              </div>
            </div>
          </div>

          {/* Lines Table */}
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <div className="p-4 border-b border-border flex items-center justify-between">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Calculator className="w-4 h-4 text-primary" /> {t("offers.boqLines")} ({lines.length})
              </h2>
              {canEdit && (
                <Button size="sm" onClick={addLine} data-testid="add-line-btn">
                  <Plus className="w-4 h-4 mr-1" /> {t("offers.addLine")}
                </Button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="lines-table">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium">{t("offers.activity")}</th>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium w-[80px]">{t("offers.unit")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[80px]">{t("offers.qty")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">{t("offers.matPerUnit")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">{t("offers.labPerUnit")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">{t("offers.material")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">{t("offers.labor")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[110px]">{t("common.total")}</th>
                    {canEdit && <th className="w-[50px]"></th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {computedLines.length === 0 ? (
                    <tr>
                      <td colSpan={canEdit ? 9 : 8} className="text-center py-8 text-muted-foreground">
                        {t("offers.noLinesYet")}
                      </td>
                    </tr>
                  ) : (
                    computedLines.map((line, idx) => (
                      <tr key={line.id || idx} className="hover:bg-muted/30" data-testid={`line-row-${idx}`}>
                        <td className="p-2">
                          <div className="flex items-center gap-2">
                            {canEdit && activities.length > 0 && (
                              <Button 
                                variant="ghost" 
                                size="sm" 
                                className="h-7 px-2 text-xs"
                                onClick={() => openActivityPicker(idx)}
                                data-testid={`pick-activity-btn-${idx}`}
                              >
                                Pick
                              </Button>
                            )}
                            <Input
                              value={line.activity_name}
                              onChange={(e) => updateLine(idx, "activity_name", e.target.value)}
                              placeholder="Activity name"
                              disabled={!canEdit}
                              className="bg-background h-8 text-sm"
                            />
                          </div>
                        </td>
                        <td className="p-2">
                          <Select value={line.unit} onValueChange={(v) => updateLine(idx, "unit", v)} disabled={!canEdit}>
                            <SelectTrigger className="bg-background h-8 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {UNITS.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="p-2">
                          <Input
                            type="number"
                            value={line.qty}
                            onChange={(e) => updateLine(idx, "qty", e.target.value)}
                            disabled={!canEdit}
                            className="bg-background h-8 text-sm text-right"
                          />
                        </td>
                        <td className="p-2">
                          <Input
                            type="number"
                            value={line.material_unit_cost}
                            onChange={(e) => updateLine(idx, "material_unit_cost", e.target.value)}
                            disabled={!canEdit}
                            className="bg-background h-8 text-sm text-right"
                          />
                        </td>
                        <td className="p-2">
                          <Input
                            type="number"
                            value={line.labor_unit_cost}
                            onChange={(e) => updateLine(idx, "labor_unit_cost", e.target.value)}
                            disabled={!canEdit}
                            className="bg-background h-8 text-sm text-right"
                          />
                        </td>
                        <td className="p-2 text-right font-mono text-muted-foreground">
                          {formatCurrency(line.line_material_cost)}
                        </td>
                        <td className="p-2 text-right font-mono text-muted-foreground">
                          {formatCurrency(line.line_labor_cost)}
                        </td>
                        <td className="p-2 text-right font-mono font-medium text-foreground">
                          {formatCurrency(line.line_total)}
                        </td>
                        {canEdit && (
                          <td className="p-2">
                            <Button variant="ghost" size="sm" onClick={() => removeLine(idx)} className="text-destructive hover:text-destructive">
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </td>
                        )}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Notes */}
          <div className="rounded-xl border border-border bg-card p-5">
            <Label className="mb-2 block">Notes</Label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Additional notes..."
              disabled={!canEdit}
              className="bg-background min-h-[80px]"
              data-testid="notes-textarea"
            />
          </div>
        </div>

        {/* Sidebar - Totals */}
        <div className="space-y-6">
          <div className="rounded-xl border border-border bg-card p-5 sticky top-6" data-testid="totals-card">
            <h3 className="text-sm font-semibold text-foreground mb-4">Summary</h3>
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Subtotal</span>
                <span className="font-mono text-foreground">{formatCurrency(subtotal)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">VAT ({vatPercent}%)</span>
                <span className="font-mono text-foreground">{formatCurrency(vatAmount)}</span>
              </div>
              <div className="border-t border-border pt-3 flex justify-between">
                <span className="font-semibold text-foreground">Total</span>
                <span className="font-mono text-lg font-bold text-primary">{formatCurrency(total)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Activity Picker Dialog */}
      <Dialog open={activityDialogOpen} onOpenChange={setActivityDialogOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="activity-picker-dialog">
          <DialogHeader>
            <DialogTitle>Select Activity from Catalog</DialogTitle>
          </DialogHeader>
          <div className="max-h-[300px] overflow-y-auto space-y-2">
            {activities.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No activities in catalog</p>
            ) : (
              activities.map((act) => (
                <div
                  key={act.id}
                  className="p-3 rounded-lg border border-border hover:bg-muted/50 cursor-pointer transition-colors"
                  onClick={() => selectActivity(act)}
                  data-testid={`activity-option-${act.id}`}
                >
                  <p className="font-medium text-foreground">{act.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {act.code && `${act.code} · `}
                    {act.default_unit} · Mat: {formatCurrency(act.default_material_unit_cost)} · Lab: {formatCurrency(act.default_labor_unit_cost)}
                  </p>
                </div>
              ))
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setActivityDialogOpen(false)}>Cancel</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
