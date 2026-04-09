/**
 * SMRAnalysisPage — Detailed SMR cost analysis editor with inline-editable table.
 */
import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  ArrowLeft, Plus, Loader2, Calculator, Sparkles, Check, Lock,
  Copy, FileOutput, Trash2, RefreshCcw, Download,
} from "lucide-react";
import { toast } from "sonner";
import PricingPanel from "@/components/PricingPanel";

const STATUS_CFG = {
  draft: { label: "Чернова", color: "bg-slate-100 text-slate-700" },
  approved: { label: "Одобрен", color: "bg-emerald-50 text-emerald-700" },
  locked: { label: "Заключен", color: "bg-zinc-100 text-zinc-500" },
};

// Inline editable number cell
function EditCell({ value, onChange, disabled, suffix, className = "" }) {
  const [editing, setEditing] = useState(false);
  const [temp, setTemp] = useState(String(value ?? ""));

  const commit = () => {
    const num = parseFloat(temp);
    if (!isNaN(num) && num !== value) onChange(num);
    setEditing(false);
  };

  if (disabled || !onChange) {
    return <span className={className}>{typeof value === "number" ? value.toFixed(2) : value}{suffix || ""}</span>;
  }

  if (editing) {
    return (
      <Input
        value={temp}
        onChange={e => setTemp(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
        className="h-7 w-20 text-xs px-1"
        autoFocus
        type="number"
        step="any"
      />
    );
  }

  return (
    <button onClick={() => { setTemp(String(value ?? "")); setEditing(true); }} className={`hover:bg-muted/30 px-1 rounded cursor-text ${className}`}>
      {typeof value === "number" ? value.toFixed(2) : value}{suffix || ""}
    </button>
  );
}

// Frontend-side recalculation (mirrors backend calc_line)
function calcLine(ln) {
  const materials = ln.materials || [];
  const qty = ln.qty || 1;
  const logPct = ln.logistics_pct ?? 10;
  const markupPct = ln.markup_pct ?? 15;
  const riskPct = ln.risk_pct ?? 5;
  const labor = ln.labor_price_per_unit || 0;

  let matRaw = 0;
  for (const m of materials) {
    const up = m.unit_price || 0;
    const qpu = m.qty_per_unit || 0;
    const waste = m.waste_pct || 0;
    matRaw += up * qpu * (1 + waste / 100);
  }
  matRaw = Math.round(matRaw * 100) / 100;
  const matLogistics = matRaw * (1 + logPct / 100);
  const totalCost = matLogistics + labor;
  const finalPrice = Math.round(totalCost * (1 + markupPct / 100) * (1 + riskPct / 100) * 100) / 100;
  const finalTotal = Math.round(finalPrice * qty * 100) / 100;

  return { ...ln, material_cost_per_unit: matRaw, total_cost_per_unit: Math.round(totalCost * 100) / 100, final_price_per_unit: finalPrice, final_total: finalTotal };
}

function calcTotals(lines) {
  let mat = 0, lab = 0, log = 0, cost = 0, mu = 0, ri = 0, grand = 0;
  for (const ln of lines) {
    const q = ln.qty || 1;
    const mr = ln.material_cost_per_unit || 0;
    const lp = ln.labor_price_per_unit || 0;
    const lPct = ln.logistics_pct ?? 10;
    const mPct = ln.markup_pct ?? 15;
    const rPct = ln.risk_pct ?? 5;
    mat += mr * q;
    lab += lp * q;
    log += mr * (lPct / 100) * q;
    const c = (mr * (1 + lPct / 100) + lp) * q;
    cost += c;
    const cm = c * (1 + mPct / 100);
    mu += cm - c;
    const cf = cm * (1 + rPct / 100);
    ri += cf - cm;
    grand += cf;
  }
  return { material_total: r2(mat), labor_total: r2(lab), logistics_total: r2(log), cost_total: r2(cost), markup_total: r2(mu), risk_total: r2(ri), grand_total: r2(grand) };
}
function r2(n) { return Math.round(n * 100) / 100; }

export default function SMRAnalysisPage() {
  const { projectId, analysisId } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  // Add line modal
  const [showAdd, setShowAdd] = useState(false);
  const [addType, setAddType] = useState("");
  const [addUnit, setAddUnit] = useState("m2");
  const [addQty, setAddQty] = useState("1");

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/smr-analyses/${analysisId}`);
      setAnalysis(res.data);
    } catch { toast.error(t("common.error")); }
    finally { setLoading(false); }
  }, [analysisId, t]);

  useEffect(() => { load(); }, [load]);

  const isLocked = analysis?.status === "locked";
  const isDraft = analysis?.status === "draft";

  // Update a line field locally + send to server
  const updateLineField = async (lineId, field, value) => {
    if (!analysis || isLocked) return;
    // Optimistic local update
    const newLines = analysis.lines.map(ln => {
      if (ln.line_id !== lineId) return ln;
      const updated = { ...ln, [field]: value };
      return calcLine(updated);
    });
    const newTotals = calcTotals(newLines);
    setAnalysis(prev => ({ ...prev, lines: newLines, totals: newTotals }));

    // Server sync
    try {
      await API.put(`/smr-analyses/${analysisId}/lines/${lineId}`, { [field]: value });
    } catch { /* will be corrected on next load */ }
  };

  const handleAddLine = async () => {
    if (!addType.trim()) { toast.error(t("smrAnalysis.enterSMRType")); return; }
    setActionLoading(true);
    try {
      const res = await API.post(`/smr-analyses/${analysisId}/lines`, {
        smr_type: addType.trim(),
        unit: addUnit,
        qty: parseFloat(addQty) || 1,
      });
      setAnalysis(res.data);
      setShowAdd(false);
      setAddType("");
      toast.success(t("smrAnalysis.lineAdded"));
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleDeleteLine = async (lineId) => {
    if (!window.confirm(t("smrAnalysis.confirmDeleteLine"))) return;
    try {
      const res = await API.delete(`/smr-analyses/${analysisId}/lines/${lineId}`);
      setAnalysis(res.data);
      toast.success(t("smrAnalysis.lineDeleted"));
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  const handleAISuggest = async (lineId) => {
    setActionLoading(true);
    try {
      const res = await API.post(`/smr-analyses/${analysisId}/ai-suggest`, { line_id: lineId });
      setAnalysis(res.data.analysis);
      toast.success(t("smrAnalysis.aiApplied"));
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleRecalculate = async () => {
    setActionLoading(true);
    try {
      const res = await API.post(`/smr-analyses/${analysisId}/recalculate`);
      setAnalysis(res.data);
      toast.success(t("smrAnalysis.recalculated"));
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleApprove = async () => {
    setActionLoading(true);
    try {
      const res = await API.post(`/smr-analyses/${analysisId}/approve`);
      setAnalysis(res.data);
      toast.success(t("smrAnalysis.approved"));
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleLock = async () => {
    setActionLoading(true);
    try {
      const res = await API.post(`/smr-analyses/${analysisId}/lock`);
      setAnalysis(res.data);
      toast.success(t("smrAnalysis.locked"));
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleSnapshot = async () => {
    setActionLoading(true);
    try {
      const res = await API.post(`/smr-analyses/${analysisId}/snapshot`);
      toast.success(`${t("smrAnalysis.snapshotCreated")} v${res.data.version}`);
      navigate(`/projects/${projectId}/smr-analysis/${res.data.id}`);
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  const handleToOffer = async () => {
    setActionLoading(true);
    try {
      const res = await API.post(`/smr-analyses/${analysisId}/to-offer`);
      toast.success(`${t("smrAnalysis.offerCreated")}: ${res.data.offer_no}`);
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setActionLoading(false); }
  };

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin text-cyan-500" /></div>;
  if (!analysis) return <div className="p-6 text-center text-muted-foreground">{t("smrAnalysis.notFound")}</div>;

  const { lines = [], totals = {} } = analysis;
  const st = STATUS_CFG[analysis.status] || STATUS_CFG.draft;

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-[1400px] mx-auto" data-testid="smr-analysis-page">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => navigate(`/smr-analyses`)} data-testid="back-btn">
          <ArrowLeft className="w-4 h-4 mr-1" /> {t("smrAnalysis.listTitle")}
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-bold truncate" data-testid="analysis-name">{analysis.name}</h1>
          <p className="text-xs text-muted-foreground">{analysis.project_name} | v{analysis.version}</p>
        </div>
        <Badge className={st.color} variant="outline" data-testid="analysis-status">{st.label}</Badge>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        {!isLocked && (
          <Button size="sm" variant="outline" onClick={() => setShowAdd(true)} data-testid="add-line-btn">
            <Plus className="w-4 h-4 mr-1" /> {t("smrAnalysis.addLine")}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={handleRecalculate} disabled={actionLoading} data-testid="recalculate-btn">
          <RefreshCcw className="w-4 h-4 mr-1" /> {t("smrAnalysis.recalculate")}
        </Button>
        {isDraft && (
          <Button size="sm" variant="outline" onClick={handleApprove} disabled={actionLoading} data-testid="approve-btn">
            <Check className="w-4 h-4 mr-1" /> {t("smrAnalysis.approve")}
          </Button>
        )}
        {!isLocked && (
          <Button size="sm" variant="outline" onClick={handleLock} disabled={actionLoading} data-testid="lock-btn">
            <Lock className="w-4 h-4 mr-1" /> {t("smrAnalysis.lock")}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={handleSnapshot} disabled={actionLoading} data-testid="snapshot-btn">
          <Copy className="w-4 h-4 mr-1" /> {t("smrAnalysis.snapshot")}
        </Button>
        <Button size="sm" onClick={handleToOffer} disabled={actionLoading} data-testid="to-offer-btn">
          <FileOutput className="w-4 h-4 mr-1" /> {t("smrAnalysis.toOffer")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => {
          window.open(`${process.env.REACT_APP_BACKEND_URL}/api/smr-analyses/${analysisId}/export-excel`, "_blank");
        }} data-testid="export-excel-btn">
          <Download className="w-4 h-4 mr-1" /> Excel
        </Button>
      </div>

      {/* Lines Table */}
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="text-[11px]">
                <TableHead className="w-8">#</TableHead>
                <TableHead>{t("smrAnalysis.smrType")}</TableHead>
                <TableHead className="text-center">{t("smrAnalysis.qty")}</TableHead>
                <TableHead className="text-center">{t("smrAnalysis.unit")}</TableHead>
                <TableHead className="text-right">{t("smrAnalysis.matPerUnit")}</TableHead>
                <TableHead className="text-right">{t("smrAnalysis.logPct")}</TableHead>
                <TableHead className="text-right">{t("smrAnalysis.laborPerUnit")}</TableHead>
                <TableHead className="text-right">{t("smrAnalysis.costPerUnit")}</TableHead>
                <TableHead className="text-right">{t("smrAnalysis.markupPct")}</TableHead>
                <TableHead className="text-right">{t("smrAnalysis.riskPct")}</TableHead>
                <TableHead className="text-right">{t("smrAnalysis.finalPriceUnit")}</TableHead>
                <TableHead className="text-right">{t("smrAnalysis.totalEUR")}</TableHead>
                <TableHead className="w-16"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.length === 0 ? (
                <TableRow><TableCell colSpan={13} className="text-center text-muted-foreground py-8">{t("smrAnalysis.noLines")}</TableCell></TableRow>
              ) : lines.map((ln, i) => (
                <TableRow key={ln.line_id} data-testid={`line-row-${ln.line_id}`} className="text-xs">
                  <TableCell className="text-muted-foreground">{i + 1}</TableCell>
                  <TableCell className="font-medium max-w-[180px] truncate">{ln.smr_type}</TableCell>
                  <TableCell className="text-center">
                    <EditCell value={ln.qty} onChange={v => updateLineField(ln.line_id, "qty", v)} disabled={isLocked} />
                  </TableCell>
                  <TableCell className="text-center text-muted-foreground">{ln.unit}</TableCell>
                  <TableCell className="text-right">{(ln.material_cost_per_unit || 0).toFixed(2)}</TableCell>
                  <TableCell className="text-right">
                    <EditCell value={ln.logistics_pct} onChange={v => updateLineField(ln.line_id, "logistics_pct", v)} disabled={isLocked} suffix="%" />
                  </TableCell>
                  <TableCell className="text-right">
                    <EditCell value={ln.labor_price_per_unit} onChange={v => updateLineField(ln.line_id, "labor_price_per_unit", v)} disabled={isLocked} />
                  </TableCell>
                  <TableCell className="text-right font-mono">{(ln.total_cost_per_unit || 0).toFixed(2)}</TableCell>
                  <TableCell className="text-right">
                    <EditCell value={ln.markup_pct} onChange={v => updateLineField(ln.line_id, "markup_pct", v)} disabled={isLocked} suffix="%" />
                  </TableCell>
                  <TableCell className="text-right">
                    <EditCell value={ln.risk_pct} onChange={v => updateLineField(ln.line_id, "risk_pct", v)} disabled={isLocked} suffix="%" />
                  </TableCell>
                  <TableCell className="text-right font-mono font-bold">{(ln.final_price_per_unit || 0).toFixed(2)}</TableCell>
                  <TableCell className="text-right font-mono font-bold text-primary">{(ln.final_total || 0).toFixed(2)}</TableCell>
                  <TableCell>
                    <div className="flex gap-0.5">
                      {!isLocked && (
                        <button onClick={() => handleAISuggest(ln.line_id)} className="p-1 hover:text-amber-400" title="AI"><Sparkles className="w-3.5 h-3.5" /></button>
                      )}
                      {!isLocked && (
                        <button onClick={() => handleDeleteLine(ln.line_id)} className="p-1 hover:text-red-400" title={t("common.delete")}><Trash2 className="w-3.5 h-3.5" /></button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Summary */}
      <Card>
        <CardContent className="p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 text-center">
            {[
              { label: t("smrAnalysis.sumMaterials"), val: totals.material_total, color: "text-blue-400" },
              { label: t("smrAnalysis.sumLabor"), val: totals.labor_total, color: "text-emerald-400" },
              { label: t("smrAnalysis.sumLogistics"), val: totals.logistics_total, color: "text-amber-400" },
              { label: t("smrAnalysis.sumCost"), val: totals.cost_total, color: "text-white" },
              { label: t("smrAnalysis.sumMarkup"), val: totals.markup_total, color: "text-purple-400" },
              { label: t("smrAnalysis.sumRisk"), val: totals.risk_total, color: "text-orange-400" },
              { label: t("smrAnalysis.grandTotal"), val: totals.grand_total, color: "text-primary font-bold text-lg" },
            ].map(({ label, val, color }) => (
              <div key={label}>
                <p className="text-[10px] text-muted-foreground mb-1">{label}</p>
                <p className={`font-mono ${color}`}>{(val || 0).toFixed(2)}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Pricing Panels for lines with materials */}
      {lines.filter(ln => ln.materials?.length > 0).map(ln => (
        <Card key={`pricing-${ln.line_id}`}>
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground mb-2">{ln.smr_type}</p>
            <PricingPanel
              analysisId={analysisId}
              lineId={ln.line_id}
              materials={ln.materials}
              onUpdated={setAnalysis}
              disabled={isLocked}
            />
          </CardContent>
        </Card>
      ))}

      {/* Add Line Dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("smrAnalysis.addLine")}</DialogTitle>
            <DialogDescription>{t("smrAnalysis.addLineDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>{t("smrAnalysis.smrType")} *</Label>
              <Input value={addType} onChange={e => setAddType(e.target.value)} placeholder={t("smrAnalysis.smrTypePlaceholder")} data-testid="add-line-type" autoFocus />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>{t("smrAnalysis.qty")}</Label>
                <Input type="number" value={addQty} onChange={e => setAddQty(e.target.value)} min="0.01" step="0.01" data-testid="add-line-qty" />
              </div>
              <div className="space-y-1">
                <Label>{t("smrAnalysis.unit")}</Label>
                <Input value={addUnit} onChange={e => setAddUnit(e.target.value)} data-testid="add-line-unit" />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAdd(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleAddLine} disabled={actionLoading} data-testid="add-line-submit">
              {actionLoading && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}
              {t("common.add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
