import React, { useEffect, useState, useCallback, useMemo } from "react";
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
  Tags,
  PiggyBank,
  Layers,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  ToggleLeft,
  ToggleRight,
  ChevronsUpDown,
  Sparkles,
  Link2,
  ExternalLink,
  Package,
} from "lucide-react";
import ActivityTypeSelect, { ACTIVITY_TYPES } from "@/components/ActivityTypeSelect";
import ActivityBudgetsPanel from "@/components/ActivityBudgetsPanel";
import OfferVersionsPanel from "@/components/OfferVersionsPanel";
import { Switch } from "@/components/ui/switch";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

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
  
  // AI Assist - multi-line with editable proposals
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [aiLines, setAiLines] = useState([{ id: "1", text: "", unit: "m2", qty: 1 }]);
  const [aiResults, setAiResults] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiEdits, setAiEdits] = useState({});
  
  // Grouping state
  const [groupingEnabled, setGroupingEnabled] = useState(() => {
    const saved = localStorage.getItem("offer_grouping_enabled");
    return saved === "true";
  });
  const [collapsedGroups, setCollapsedGroups] = useState({});
  const [budgetSummary, setBudgetSummary] = useState(null);

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
  
  // Load budget summary when project changes
  useEffect(() => {
    if (projectId) {
      API.get(`/projects/${projectId}/activity-budget-summary`)
        .then(res => setBudgetSummary(res.data))
        .catch(() => setBudgetSummary(null));
    }
  }, [projectId]);
  
  // Persist grouping preference
  useEffect(() => {
    localStorage.setItem("offer_grouping_enabled", groupingEnabled.toString());
  }, [groupingEnabled]);

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
  
  // Group lines by type/subtype (must be after computedLines)
  const groupedLines = useMemo(() => {
    if (!groupingEnabled) return null;
    
    const groups = {};
    computedLines.forEach((line, originalIndex) => {
      const type = line.activity_type || "Общо";
      const subtype = line.activity_subtype || "";
      const key = `${type}||${subtype}`;
      
      if (!groups[key]) {
        groups[key] = {
          key,
          type,
          subtype,
          lines: [],
          totals: { material: 0, labor: 0, total: 0 },
        };
      }
      
      groups[key].lines.push({ ...line, originalIndex });
      groups[key].totals.material += line.line_material_cost || 0;
      groups[key].totals.labor += line.line_labor_cost || 0;
      groups[key].totals.total += line.line_total || 0;
    });
    
    // Add budget info to each group
    if (budgetSummary?.items) {
      Object.values(groups).forEach(group => {
        const budgetItem = budgetSummary.items.find(
          b => b.type === group.type && (b.subtype || "") === group.subtype
        );
        if (budgetItem) {
          group.budget = budgetItem;
        }
      });
    }
    
    // Sort groups by type then subtype
    return Object.values(groups).sort((a, b) => {
      if (a.type !== b.type) return a.type.localeCompare(b.type, "bg");
      return (a.subtype || "").localeCompare(b.subtype || "", "bg");
    });
  }, [computedLines, groupingEnabled, budgetSummary]);
  
  // Toggle group collapse
  const toggleGroupCollapse = (key) => {
    setCollapsedGroups(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
  };
  
  // Expand/collapse all
  const expandAllGroups = () => setCollapsedGroups({});
  const collapseAllGroups = () => {
    if (groupedLines) {
      const collapsed = {};
      groupedLines.forEach(g => { collapsed[g.key] = true; });
      setCollapsedGroups(collapsed);
    }
  };

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
      activity_type: "Общо",
      activity_subtype: "",
    }]);
  };

  const removeLine = (idx) => {
    setLines(lines.filter((_, i) => i !== idx));
  };

  // AI Assist handlers
  const addAiLine = () => setAiLines([...aiLines, { id: Date.now().toString(), text: "", unit: "m2", qty: 1 }]);
  const removeAiLine = (i) => { if (aiLines.length > 1) setAiLines(aiLines.filter((_, idx) => idx !== i)); };
  const updateAiLine = (i, f, v) => { const n = [...aiLines]; n[i] = { ...n[i], [f]: v }; setAiLines(n); };

  const handleAiAssist = async () => {
    const valid = aiLines.filter(l => l.text.trim());
    if (!valid.length) return;
    setAiLoading(true);
    setAiResults(null);
    setAiEdits({});
    try {
      const res = await API.post("/extra-works/ai-fast", {
        lines: valid.map(l => ({ title: l.text, unit: l.unit, qty: parseFloat(l.qty) || 1 })),
        city: null,
      });
      setAiResults(res.data);
      // Init editable state
      const edits = {};
      res.data.results.forEach((r, i) => {
        edits[i] = {
          text: r._input.title,
          unit: r.recognized.suggested_unit || r._input.unit,
          qty: r._input.qty,
          material: r.pricing.material_price_per_unit,
          labor: r.pricing.labor_price_per_unit,
          type: r.recognized.activity_type,
          subtype: r.recognized.activity_subtype,
          note: r.pricing.small_qty_adjustment_percent > 0 ? `AI: +${r.pricing.small_qty_adjustment_percent}% малко к-во` : "",
          confidence: r.confidence,
          provider: r.provider,
          explanation: r.explanation || "",
          hint: r.internal_price_hint || null,
          hourly: r.hourly_info || null,
        };
      });
      setAiEdits(edits);
      // Start LLM refinement in background
      API.post("/extra-works/ai-refine", {
        lines: valid.map(l => ({ title: l.text, unit: l.unit, qty: parseFloat(l.qty) || 1 })),
        city: null,
      }).then(refRes => {
        setAiResults(prev => prev ? { ...prev, stage: "refined", combined_materials: refRes.data.combined_materials } : prev);
        // Merge refined pricing where user hasn't edited
        setAiEdits(prev => {
          const updated = { ...prev };
          refRes.data.results.forEach((r, i) => {
            if (updated[i] && updated[i].material === prev[i]?.material && updated[i].labor === prev[i]?.labor) {
              updated[i] = { ...updated[i], material: r.pricing.material_price_per_unit, labor: r.pricing.labor_price_per_unit,
                confidence: r.confidence, provider: r.provider, explanation: r.explanation || updated[i].explanation,
                hint: r.internal_price_hint || updated[i].hint };
            }
          });
          return updated;
        });
      }).catch(() => {});
    } catch (err) { console.error(err); }
    finally { setAiLoading(false); }
  };

  const editAiProp = (i, f, v) => setAiEdits(prev => ({ ...prev, [i]: { ...prev[i], [f]: v } }));

  const addAiLinesToOffer = () => {
    if (!aiEdits || !Object.keys(aiEdits).length) return;
    const newLines = Object.values(aiEdits).map((e, i) => ({
      id: Date.now().toString() + i,
      activity_code: "",
      activity_name: e.text,
      unit: e.unit,
      qty: parseFloat(e.qty) || 1,
      material_unit_cost: parseFloat(e.material) || 0,
      labor_unit_cost: parseFloat(e.labor) || 0,
      labor_hours_per_unit: null,
      note: e.note,
      sort_order: lines.length + i,
      activity_type: e.type || "Общо",
      activity_subtype: e.subtype || "",
    }));
    setLines([...lines, ...newLines]);
    setAiDialogOpen(false);
    setAiResults(null);
    setAiEdits({});
    setAiLines([{ id: "1", text: "", unit: "m2", qty: 1 }]);
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

  // Review link state
  const [reviewUrl, setReviewUrl] = useState(null);
  const [linkCopied, setLinkCopied] = useState(false);

  const handleSend = async () => {
    if (lines.length === 0) {
      alert(t("offers.addLineBeforeSend"));
      return;
    }
    setSaving(true);
    try {
      const res = await API.post(`/offers/${offerId}/send`);
      if (res.data.review_url) {
        setReviewUrl(window.location.origin + res.data.review_url);
      }
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setSaving(false);
    }
  };

  const copyReviewLink = () => {
    const url = reviewUrl || (offer?.review_token ? `${window.location.origin}/offers/review/${offer.review_token}` : null);
    if (url) {
      navigator.clipboard.writeText(url);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
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
                  <Badge variant="outline" className={`text-[10px] ${offer.offer_type === "extra" ? "bg-amber-500/15 text-amber-400 border-amber-500/30" : "bg-blue-500/10 text-blue-400 border-blue-500/30"}`}>
                    {offer.offer_type === "extra" ? "Допълнителна" : "Основна"}
                  </Badge>
                  <Badge variant="outline" className={`text-xs ${STATUS_COLORS[offer.status] || ""}`}>
                    {t(`offers.status.${offer.status.toLowerCase()}`)}
                  </Badge>
                  <span className="text-sm text-muted-foreground">v{offer.version}</span>
                </>
              )}
            </div>
            {offer && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>{offer.project_code} - {offer.project_name}</span>
                {offer.offer_type === "extra" && offer.notes && (
                  <span className="text-xs text-amber-400/70">• {offer.notes}</span>
                )}
              </div>
            )}
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
          {offer?.review_token && (
            <Button variant="outline" onClick={copyReviewLink} className="border-violet-500/30 text-violet-400 hover:bg-violet-500/10" data-testid="copy-link-btn">
              <Link2 className="w-4 h-4 mr-1" /> {linkCopied ? "Копирано!" : "Копирай линк"}
            </Button>
          )}
          {offer?.review_token && (
            <Button variant="ghost" size="sm" onClick={() => window.open(`/offers/review/${offer.review_token}`, '_blank')} data-testid="open-review-btn">
              <ExternalLink className="w-4 h-4" />
            </Button>
          )}
          {offer && (
            <>
              <Button variant="outline" size="sm" onClick={async () => {
                try {
                  const res = await API.get(`/offers/${offerId}/pdf`, { responseType: 'blob' });
                  const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
                  const a = document.createElement('a'); a.href = url; a.download = `offer_${offer.offer_no}.pdf`;
                  document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url);
                } catch (err) { alert("Грешка при PDF"); }
              }} data-testid="export-pdf-btn" className="text-xs">
                <Printer className="w-4 h-4 mr-1" /> PDF
              </Button>
              <Button variant="outline" size="sm" onClick={async () => {
                try {
                  const res = await API.get(`/offers/${offerId}/xlsx`, { responseType: 'blob' });
                  const url = window.URL.createObjectURL(new Blob([res.data]));
                  const a = document.createElement('a'); a.href = url; a.download = `offer_${offer.offer_no}.xlsx`;
                  document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url);
                } catch (err) { alert("Грешка при Excel"); }
              }} data-testid="export-xlsx-btn" className="text-xs">
                <FileText className="w-4 h-4 mr-1" /> Excel
              </Button>
            </>
          )}
          {offer && ["Accepted", "Sent"].includes(offer.status) && (
            <Button variant="outline" size="sm" onClick={async () => {
              try {
                const res = await API.post(`/material-requests/from-offer/${offer.id}`, { stage_name: offer.title });
                navigate(`/procurement?tab=requests`);
              } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
            }} className="border-amber-500/30 text-amber-400 hover:bg-amber-500/10" data-testid="create-mr-btn">
              <Package className="w-4 h-4 mr-1" /> Заявка материали
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
            <div className="p-4 border-b border-border flex items-center justify-between flex-wrap gap-3">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Calculator className="w-4 h-4 text-primary" /> {t("offers.boqLines")} ({lines.length})
              </h2>
              <div className="flex items-center gap-4">
                {/* Grouping Toggle */}
                <div className="flex items-center gap-2 text-sm">
                  <Switch
                    id="grouping-toggle"
                    checked={groupingEnabled}
                    onCheckedChange={setGroupingEnabled}
                    data-testid="grouping-toggle"
                  />
                  <Label htmlFor="grouping-toggle" className="text-xs text-muted-foreground cursor-pointer flex items-center gap-1">
                    <Layers className="w-3 h-3" />
                    Групирай по Тип/Подтип
                  </Label>
                </div>
                
                {/* Expand/Collapse All */}
                {groupingEnabled && groupedLines && groupedLines.length > 0 && (
                  <div className="flex items-center gap-1">
                    <Button variant="ghost" size="sm" onClick={expandAllGroups} className="h-7 px-2 text-xs">
                      Разгъни
                    </Button>
                    <span className="text-muted-foreground">/</span>
                    <Button variant="ghost" size="sm" onClick={collapseAllGroups} className="h-7 px-2 text-xs">
                      Сгъни
                    </Button>
                  </div>
                )}
                
                {canEdit && (
                  <>
                  <Button size="sm" onClick={addLine} data-testid="add-line-btn">
                    <Plus className="w-4 h-4 mr-1" /> {t("offers.addLine")}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => { setAiLines([{ id: "1", text: "", unit: "m2", qty: 1 }]); setAiResults(null); setAiEdits({}); setAiDialogOpen(true); }} className="border-violet-500/30 text-violet-400 hover:bg-violet-500/10" data-testid="ai-assist-btn">
                    <Sparkles className="w-4 h-4 mr-1" /> AI помощ
                  </Button>
                  </>
                )}
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="lines-table">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium">{t("offers.activity")}</th>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">Тип</th>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium w-[65px]">{t("offers.unit")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[65px]">{t("offers.qty")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[85px]">{t("offers.matPerUnit")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[85px]">{t("offers.labPerUnit")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[90px]">{t("offers.material")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[90px]">{t("offers.labor")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[95px]">{t("common.total")}</th>
                    {canEdit && <th className="w-[50px]"></th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {computedLines.length === 0 ? (
                    <tr>
                      <td colSpan={canEdit ? 10 : 9} className="text-center py-8 text-muted-foreground">
                        {t("offers.noLinesYet")}
                      </td>
                    </tr>
                  ) : groupingEnabled && groupedLines ? (
                    /* Grouped View */
                    groupedLines.map((group) => {
                      const isCollapsed = collapsedGroups[group.key];
                      const hasNegativeRemaining = group.budget && (group.budget.labor_remaining < 0 || group.budget.materials_remaining < 0);
                      const hasOverBudget = group.budget && (group.budget.percent_labor_used > 100 || group.budget.percent_materials_used > 100);
                      
                      return (
                        <React.Fragment key={group.key}>
                          {/* Group Header */}
                          <tr 
                            className={`bg-muted/70 cursor-pointer hover:bg-muted ${hasNegativeRemaining ? "border-l-2 border-l-red-500" : ""}`}
                            onClick={() => toggleGroupCollapse(group.key)}
                            data-testid={`group-header-${group.key}`}
                          >
                            <td colSpan={3} className="p-3">
                              <div className="flex items-center gap-2">
                                {isCollapsed ? (
                                  <ChevronRight className="w-4 h-4 text-muted-foreground" />
                                ) : (
                                  <ChevronDown className="w-4 h-4 text-muted-foreground" />
                                )}
                                <Tags className="w-4 h-4 text-primary" />
                                <span className="font-semibold text-foreground">
                                  {group.type}
                                  {group.subtype && <span className="text-muted-foreground font-normal"> / {group.subtype}</span>}
                                </span>
                                <Badge variant="secondary" className="text-xs">
                                  {group.lines.length} {group.lines.length === 1 ? "ред" : "реда"}
                                </Badge>
                                {hasOverBudget && (
                                  <Badge variant="destructive" className="text-xs">
                                    <AlertTriangle className="w-3 h-3 mr-1" />
                                    Над бюджет
                                  </Badge>
                                )}
                              </div>
                            </td>
                            <td className="p-3 text-right text-xs text-muted-foreground" colSpan={2}>
                              {group.budget && (
                                <div className="flex flex-col items-end gap-0.5">
                                  <span>Бюджет: {formatCurrency(group.budget.labor_budget + group.budget.materials_budget)}</span>
                                  <span className={group.budget.labor_remaining + group.budget.materials_remaining < 0 ? "text-red-500" : "text-green-500"}>
                                    Остатък: {formatCurrency(group.budget.labor_remaining + group.budget.materials_remaining)}
                                  </span>
                                </div>
                              )}
                            </td>
                            <td className="p-3 text-right font-mono text-muted-foreground">
                              {formatCurrency(group.totals.material)}
                            </td>
                            <td className="p-3 text-right font-mono text-muted-foreground">
                              {formatCurrency(group.totals.labor)}
                            </td>
                            <td className="p-3 text-right font-mono font-semibold text-primary">
                              {formatCurrency(group.totals.total)}
                            </td>
                            {canEdit && <td></td>}
                          </tr>
                          
                          {/* Group Lines (collapsible) */}
                          {!isCollapsed && group.lines.map((line) => (
                            <tr key={line.id || line.originalIndex} className="hover:bg-muted/30 bg-card" data-testid={`line-row-${line.originalIndex}`}>
                              <td className="p-2 pl-8">
                                <div className="flex items-center gap-2">
                                  {canEdit && activities.length > 0 && (
                                    <Button 
                                      variant="ghost" 
                                      size="sm" 
                                      className="h-7 px-2 text-xs"
                                      onClick={() => openActivityPicker(line.originalIndex)}
                                    >
                                      Pick
                                    </Button>
                                  )}
                                  <Input
                                    value={line.activity_name}
                                    onChange={(e) => updateLine(line.originalIndex, "activity_name", e.target.value)}
                                    placeholder="Описание на СМР"
                                    disabled={!canEdit}
                                    className="bg-background h-8 text-sm"
                                  />
                                  {line.note && (
                                    <p className="text-[10px] text-muted-foreground/70 mt-0.5 truncate" title={line.note}>{line.note}</p>
                                  )}
                                </div>
                              </td>
                              <td className="p-2">
                                <ActivityTypeSelect
                                  value={line.activity_type || "Общо"}
                                  subtype={line.activity_subtype || ""}
                                  onChange={(type, subtype) => {
                                    const updated = [...lines];
                                    updated[line.originalIndex] = { ...updated[line.originalIndex], activity_type: type, activity_subtype: subtype };
                                    setLines(updated);
                                  }}
                                  compact
                                />
                              </td>
                              <td className="p-2">
                                <Select value={line.unit} onValueChange={(v) => updateLine(line.originalIndex, "unit", v)} disabled={!canEdit}>
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
                                  onChange={(e) => updateLine(line.originalIndex, "qty", e.target.value)}
                                  disabled={!canEdit}
                                  className="bg-background h-8 text-sm text-right"
                                />
                              </td>
                              <td className="p-2">
                                <Input
                                  type="number"
                                  value={line.material_unit_cost}
                                  onChange={(e) => updateLine(line.originalIndex, "material_unit_cost", e.target.value)}
                                  disabled={!canEdit}
                                  className="bg-background h-8 text-sm text-right"
                                />
                              </td>
                              <td className="p-2">
                                <Input
                                  type="number"
                                  value={line.labor_unit_cost}
                                  onChange={(e) => updateLine(line.originalIndex, "labor_unit_cost", e.target.value)}
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
                                  <Button variant="ghost" size="sm" onClick={() => removeLine(line.originalIndex)} className="text-destructive hover:text-destructive">
                                    <Trash2 className="w-4 h-4" />
                                  </Button>
                                </td>
                              )}
                            </tr>
                          ))}
                        </React.Fragment>
                      );
                    })
                  ) : (
                    /* Flat View (default) */
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
                          <ActivityTypeSelect
                            value={line.activity_type || "Общо"}
                            subtype={line.activity_subtype || ""}
                            onChange={(type, subtype) => {
                              const updated = [...lines];
                              updated[idx] = { ...updated[idx], activity_type: type, activity_subtype: subtype };
                              setLines(updated);
                            }}
                            compact
                          />
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
            <Label className="mb-2 block">{t("common.notes")}</Label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t("offers.notesPlaceholder")}
              disabled={!canEdit}
              className="bg-background min-h-[80px]"
              data-testid="notes-textarea"
            />
          </div>
          
          {/* Activity Budgets Panel */}
          {projectId && (
            <ActivityBudgetsPanel projectId={projectId} />
          )}
        </div>

        {/* Sidebar - Totals + Versions */}
        <div className="space-y-6">
          <div className="rounded-xl border border-border bg-card p-5 sticky top-6" data-testid="totals-card">
            <h3 className="text-sm font-semibold text-foreground mb-4">{t("offers.summary")}</h3>
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">{t("offers.subtotal")}</span>
                <span className="font-mono text-foreground">{formatCurrency(subtotal)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">{t("offers.vat")} ({vatPercent}%)</span>
                <span className="font-mono text-foreground">{formatCurrency(vatAmount)}</span>
              </div>
              <div className="border-t border-border pt-3 flex justify-between">
                <span className="font-semibold text-foreground">{t("common.total")}</span>
                <span className="font-mono text-lg font-bold text-primary">{formatCurrency(total)}</span>
              </div>
            </div>
          </div>
          
          {/* Offer Versions Panel */}
          {!isNew && offerId && (
            <OfferVersionsPanel 
              offerId={offerId} 
              onRestore={(restoredOffer) => {
                // Update local state with restored offer data
                if (restoredOffer) {
                  setTitle(restoredOffer.title || "");
                  setCurrency(restoredOffer.currency || "EUR");
                  setVatPercent(restoredOffer.vat_percent || 0);
                  setNotes(restoredOffer.notes || "");
                  setLines(restoredOffer.lines || []);
                  setOffer(restoredOffer);
                }
              }}
            />
          )}
        </div>
      </div>

      {/* Activity Picker Dialog */}
      <Dialog open={activityDialogOpen} onOpenChange={setActivityDialogOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="activity-picker-dialog">
          <DialogHeader>
            <DialogTitle>{t("offers.selectActivityFromCatalog")}</DialogTitle>
          </DialogHeader>
          <div className="max-h-[300px] overflow-y-auto space-y-2">
            {activities.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">{t("activities.noActivities")}</p>
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
                    {act.default_unit} · {t("offers.mat")}: {formatCurrency(act.default_material_unit_cost)} · {t("offers.lab")}: {formatCurrency(act.default_labor_unit_cost)}
                  </p>
                </div>
              ))
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setActivityDialogOpen(false)}>{t("common.cancel")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {/* AI Assist Dialog - Multi-line with editable proposals */}
      <Dialog open={aiDialogOpen} onOpenChange={setAiDialogOpen}>
        <DialogContent className="sm:max-w-[800px] bg-card border-border max-h-[90vh] overflow-y-auto" data-testid="ai-assist-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-violet-500" /> AI помощ за оферта
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {/* Input phase */}
            {!aiResults && (
              <>
                {aiLines.map((al, i) => (
                  <div key={al.id} className="flex items-center gap-2" data-testid={`ai-input-${i}`}>
                    <span className="text-xs text-muted-foreground font-mono w-4">{i+1}</span>
                    <Input value={al.text} onChange={e => updateAiLine(i, "text", e.target.value)}
                      placeholder="Описание на СМР" className="flex-1 bg-background text-sm" data-testid={`ai-text-${i}`} />
                    <select value={al.unit} onChange={e => updateAiLine(i, "unit", e.target.value)}
                      className="w-16 rounded-md border border-border bg-background px-2 py-1.5 text-xs">
                      {UNITS.map(u => <option key={u} value={u}>{u}</option>)}
                    </select>
                    <Input type="number" min="0.01" step="0.01" value={al.qty}
                      onChange={e => updateAiLine(i, "qty", e.target.value)}
                      className="w-16 bg-background text-sm font-mono" />
                    {aiLines.length > 1 && (
                      <Button variant="ghost" size="sm" onClick={() => removeAiLine(i)} className="h-7 w-7 p-0 text-destructive">
                        <X className="w-3 h-3" />
                      </Button>
                    )}
                  </div>
                ))}
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={addAiLine} className="text-xs">
                    <Plus className="w-3 h-3 mr-1" /> Добави ред
                  </Button>
                </div>
                <Button onClick={handleAiAssist} disabled={aiLoading || !aiLines.some(l => l.text.trim())}
                  className="w-full bg-violet-600 hover:bg-violet-700" data-testid="ai-get-proposal-btn">
                  {aiLoading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Sparkles className="w-4 h-4 mr-2" />}
                  Анализирай с AI ({aiLines.filter(l => l.text.trim()).length} {aiLines.filter(l => l.text.trim()).length === 1 ? "ред" : "реда"})
                </Button>
              </>
            )}

            {/* Results phase - editable proposals */}
            {aiResults && (
              <>
                <div className="flex items-center justify-between p-2 rounded-lg bg-violet-500/10 border border-violet-500/30">
                  <span className="text-xs text-violet-300">{aiResults.line_count} реда</span>
                  <span className="font-mono text-sm font-bold text-primary">
                    {Object.values(aiEdits).reduce((s, e) => s + (parseFloat(e.material) + parseFloat(e.labor)) * parseFloat(e.qty), 0).toFixed(2)} лв
                  </span>
                </div>

                {Object.entries(aiEdits).map(([i, e]) => {
                  const total = ((parseFloat(e.material) || 0) + (parseFloat(e.labor) || 0));
                  const lineTotal = total * (parseFloat(e.qty) || 1);
                  return (
                    <div key={i} className="rounded-lg border border-border p-3 space-y-2" data-testid={`ai-result-${i}`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono text-muted-foreground">{parseInt(i)+1}</span>
                          <span className="text-sm font-medium text-foreground">{e.text}</span>
                          <Badge variant="outline" className={`text-[9px] ${e.provider === "llm" ? "bg-emerald-500/10 text-emerald-400" : "bg-gray-500/10 text-gray-400"}`}>
                            {e.provider === "llm" ? "LLM" : "Rule"} {Math.round(e.confidence * 100)}%
                          </Badge>
                        </div>
                        <span className="font-mono text-sm font-bold text-primary">{lineTotal.toFixed(2)}</span>
                      </div>

                      {/* Editable pricing row */}
                      <div className="grid grid-cols-7 gap-2 items-end">
                        <div className="col-span-2 space-y-0.5">
                          <label className="text-[10px] text-muted-foreground">Описание</label>
                          <Input value={e.text} onChange={ev => editAiProp(i, "text", ev.target.value)} className="bg-background h-7 text-xs" />
                        </div>
                        <div className="space-y-0.5">
                          <label className="text-[10px] text-muted-foreground">Мярка</label>
                          <select value={e.unit} onChange={ev => editAiProp(i, "unit", ev.target.value)}
                            className="w-full h-7 rounded border border-border bg-background px-1 text-xs">
                            {UNITS.map(u => <option key={u} value={u}>{u}</option>)}
                          </select>
                        </div>
                        <div className="space-y-0.5">
                          <label className="text-[10px] text-muted-foreground">К-во</label>
                          <Input type="number" step="0.01" value={e.qty} onChange={ev => editAiProp(i, "qty", parseFloat(ev.target.value) || 1)} className="bg-background h-7 text-xs font-mono" />
                        </div>
                        <div className="space-y-0.5">
                          <label className="text-[10px] text-muted-foreground">Мат. лв/ед</label>
                          <Input type="number" step="0.01" value={e.material} onChange={ev => editAiProp(i, "material", parseFloat(ev.target.value) || 0)} className="bg-background h-7 text-xs font-mono" />
                        </div>
                        <div className="space-y-0.5">
                          <label className="text-[10px] text-muted-foreground">Труд лв/ед</label>
                          <Input type="number" step="0.01" value={e.labor} onChange={ev => editAiProp(i, "labor", parseFloat(ev.target.value) || 0)} className="bg-background h-7 text-xs font-mono" />
                        </div>
                        <div className="space-y-0.5">
                          <label className="text-[10px] text-muted-foreground">Общо/ед</label>
                          <div className="h-7 px-2 flex items-center bg-muted/30 rounded text-xs font-mono font-bold text-primary">{total.toFixed(2)}</div>
                        </div>
                      </div>

                      {/* Info badges */}
                      <div className="flex flex-wrap gap-1.5 text-[10px]">
                        <span className="text-muted-foreground">{e.type}/{e.subtype}</span>
                        {e.hourly && <Badge variant="outline" className="text-[9px] bg-blue-500/10 text-blue-400">{e.hourly.worker_type} {e.hourly.hourly_rate}лв/ч{e.hourly.min_applied ? " мин." : ""}</Badge>}
                        {e.hint?.available && <Badge variant="outline" className="text-[9px] bg-violet-500/10 text-violet-400">Вътр. {e.hint.range_label} ({e.hint.sample_count}x)</Badge>}
                        {e.explanation && <span className="text-muted-foreground/60 italic">{e.explanation.slice(0, 60)}</span>}
                      </div>
                    </div>
                  );
                })}

                {/* Recalculate button */}
                <Button variant="outline" onClick={() => { setAiResults(null); }} className="w-full text-xs" data-testid="ai-back-btn">
                  Обратно към входа (редактирай и пресметни отново)
                </Button>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAiDialogOpen(false)}>Затвори</Button>
            {aiResults && (
              <Button onClick={addAiLinesToOffer} className="bg-emerald-600 hover:bg-emerald-700" data-testid="ai-add-line-btn">
                <Plus className="w-4 h-4 mr-1" /> Добави {Object.keys(aiEdits).length} {Object.keys(aiEdits).length === 1 ? "ред" : "реда"} в офертата
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
