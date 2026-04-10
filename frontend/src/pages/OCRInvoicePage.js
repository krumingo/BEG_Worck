/**
 * OCRInvoicePage — OCR invoice intake: upload, review, approve.
 * Route: /ocr-invoices
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  ScanLine, Upload, Loader2, Search, Eye, Check, X, FileText, ChevronDown,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CFG = {
  uploaded: { label: "Качен", color: "bg-slate-100 text-slate-700" },
  processed: { label: "Обработен", color: "bg-blue-50 text-blue-700" },
  reviewed: { label: "Прегледан", color: "bg-amber-50 text-amber-700" },
  approved: { label: "Одобрен", color: "bg-emerald-50 text-emerald-700" },
  rejected: { label: "Отказан", color: "bg-red-50 text-red-700" },
  failed: { label: "Грешка", color: "bg-zinc-100 text-zinc-500" },
};

export default function OCRInvoicePage() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fStatus, setFStatus] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProject, setUploadProject] = useState("");

  // Detail/review
  const [selected, setSelected] = useState(null);
  const [showDetail, setShowDetail] = useState(false);
  const [reviewForm, setReviewForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    API.get("/projects").then(r => setProjects(r.data.items || r.data || [])).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (fStatus) p.append("status", fStatus);
      const res = await API.get(`/ocr-invoice?${p}`);
      setItems(res.data.items || []);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [fStatus]);

  useEffect(() => { load(); }, [load]);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (uploadProject) fd.append("project_id", uploadProject);
      const res = await API.post("/ocr-invoice/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(t("ocrInvoice.uploaded"));
      load();
      openDetail(res.data);
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setUploading(false); e.target.value = ""; }
  };

  const openDetail = (item) => {
    setSelected(item);
    const d = item.reviewed_data || item.detected_data || {};
    setReviewForm({
      supplier_name: d.supplier_name || "",
      invoice_number: d.invoice_number || "",
      invoice_date: d.invoice_date || "",
      total_amount: d.total_amount || "",
      vat_amount: d.vat_amount || "",
      currency: d.currency || "BGN",
      notes: d.notes || "",
    });
    setShowDetail(true);
    setShowRaw(false);
  };

  const handleReview = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const res = await API.put(`/ocr-invoice/${selected.id}/review`, {
        ...reviewForm,
        total_amount: parseFloat(reviewForm.total_amount) || null,
        vat_amount: parseFloat(reviewForm.vat_amount) || null,
      });
      setSelected(res.data);
      toast.success(t("ocrInvoice.reviewed"));
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setSaving(false); }
  };

  const handleApprove = async () => {
    if (!selected) return;
    try {
      const res = await API.put(`/ocr-invoice/${selected.id}/approve`);
      setSelected(res.data);
      toast.success(t("ocrInvoice.approved"));
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  const handleReject = async () => {
    if (!selected) return;
    try {
      await API.put(`/ocr-invoice/${selected.id}/reject`, { reason: "Отказано от потребител" });
      setShowDetail(false);
      toast.success(t("ocrInvoice.rejected"));
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-5xl mx-auto" data-testid="ocr-invoice-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-violet-500/10 flex items-center justify-center"><ScanLine className="w-5 h-5 text-violet-500" /></div>
          <div><h1 className="text-xl font-bold">{t("ocrInvoice.title")}</h1><p className="text-sm text-muted-foreground">{t("ocrInvoice.subtitle")}</p></div>
        </div>
        <div className="flex items-center gap-2">
          <Select value={uploadProject || "none"} onValueChange={v => setUploadProject(v === "none" ? "" : v)}>
            <SelectTrigger className="w-40"><SelectValue placeholder={t("ocrInvoice.project")} /></SelectTrigger>
            <SelectContent><SelectItem value="none">—</SelectItem>{projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code || p.name}</SelectItem>)}</SelectContent>
          </Select>
          <label className="cursor-pointer">
            <input type="file" accept=".pdf,.jpg,.jpeg,.png,.txt,.csv" className="hidden" onChange={handleUpload} data-testid="ocr-upload-input" />
            <Button asChild disabled={uploading}><span>{uploading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Upload className="w-4 h-4 mr-2" />}{t("ocrInvoice.upload")}</span></Button>
          </label>
        </div>
      </div>

      <Card><CardContent className="p-4"><div className="flex gap-3">
        <Select value={fStatus || "all"} onValueChange={v => setFStatus(v === "all" ? "" : v)}>
          <SelectTrigger className="w-40"><SelectValue placeholder={t("common.all")} /></SelectTrigger>
          <SelectContent><SelectItem value="all">{t("common.all")}</SelectItem>{Object.entries(STATUS_CFG).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}</SelectContent>
        </Select>
      </div></CardContent></Card>

      <Card><CardContent className="p-0">
        {loading ? <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div> : items.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground"><Search className="w-8 h-8 mx-auto mb-2 opacity-40" /><p className="text-sm">{t("ocrInvoice.noItems")}</p></div>
        ) : (
          <Table><TableHeader><TableRow>
            <TableHead>{t("ocrInvoice.file")}</TableHead><TableHead>{t("ocrInvoice.supplier")}</TableHead>
            <TableHead className="text-right">{t("ocrInvoice.amount")}</TableHead>
            <TableHead>{t("ocrInvoice.confidence")}</TableHead><TableHead>{t("common.status")}</TableHead>
            <TableHead>{t("common.date")}</TableHead>
          </TableRow></TableHeader><TableBody>
            {items.map(it => {
              const st = STATUS_CFG[it.status] || STATUS_CFG.uploaded;
              const d = it.reviewed_data || it.detected_data || {};
              return (
                <TableRow key={it.id} className="cursor-pointer hover:bg-muted/30" onClick={() => openDetail(it)}>
                  <TableCell className="text-sm">{it.file_name || "—"}</TableCell>
                  <TableCell className="text-sm">{d.supplier_name || "—"}</TableCell>
                  <TableCell className="text-right font-mono">{d.total_amount?.toFixed(2) || "—"}</TableCell>
                  <TableCell><Badge variant="outline" className="text-[10px]">{Math.round((it.confidence_score || 0) * 100)}%</Badge></TableCell>
                  <TableCell><Badge className={`text-xs ${st.color}`} variant="outline">{st.label}</Badge></TableCell>
                  <TableCell className="text-xs text-muted-foreground">{new Date(it.created_at).toLocaleDateString("bg-BG")}</TableCell>
                </TableRow>
              );
            })}
          </TableBody></Table>
        )}
      </CardContent></Card>

      {/* Detail / Review Dialog */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><FileText className="w-5 h-5" />{t("ocrInvoice.review")}</DialogTitle>
            <DialogDescription>{selected?.file_name} | {Math.round((selected?.confidence_score || 0) * 100)}% {t("ocrInvoice.confidence")}</DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-4">
              {selected.warnings?.length > 0 && (
                <div className="space-y-1">{selected.warnings.map((w, i) => <p key={i} className="text-xs text-amber-400">{w}</p>)}</div>
              )}
              <Badge className={`${STATUS_CFG[selected.status]?.color || ""}`} variant="outline">{STATUS_CFG[selected.status]?.label}</Badge>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label className="text-xs">{t("ocrInvoice.supplierName")}</Label><Input value={reviewForm.supplier_name} onChange={e => setReviewForm(f => ({ ...f, supplier_name: e.target.value }))} /></div>
                <div className="space-y-1"><Label className="text-xs">{t("ocrInvoice.invoiceNumber")}</Label><Input value={reviewForm.invoice_number} onChange={e => setReviewForm(f => ({ ...f, invoice_number: e.target.value }))} /></div>
                <div className="space-y-1"><Label className="text-xs">{t("ocrInvoice.invoiceDate")}</Label><Input value={reviewForm.invoice_date} onChange={e => setReviewForm(f => ({ ...f, invoice_date: e.target.value }))} /></div>
                <div className="space-y-1"><Label className="text-xs">{t("ocrInvoice.totalAmount")}</Label><Input type="number" value={reviewForm.total_amount} onChange={e => setReviewForm(f => ({ ...f, total_amount: e.target.value }))} /></div>
                <div className="space-y-1"><Label className="text-xs">{t("ocrInvoice.vatAmount")}</Label><Input type="number" value={reviewForm.vat_amount} onChange={e => setReviewForm(f => ({ ...f, vat_amount: e.target.value }))} /></div>
                <div className="space-y-1"><Label className="text-xs">{t("ocrInvoice.currency")}</Label><Input value={reviewForm.currency} onChange={e => setReviewForm(f => ({ ...f, currency: e.target.value }))} /></div>
              </div>
              <div className="space-y-1"><Label className="text-xs">{t("ocrInvoice.notes")}</Label><Input value={reviewForm.notes} onChange={e => setReviewForm(f => ({ ...f, notes: e.target.value }))} /></div>

              <button onClick={() => setShowRaw(!showRaw)} className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1">
                <ChevronDown className="w-3 h-3" /> {t("ocrInvoice.rawText")}
              </button>
              {showRaw && <pre className="text-[10px] bg-muted/10 p-2 rounded max-h-[150px] overflow-auto whitespace-pre-wrap">{(selected.detected_data || {}).raw_text || "—"}</pre>}
            </div>
          )}
          <DialogFooter className="gap-2">
            {selected?.status !== "approved" && selected?.status !== "rejected" && (
              <>
                <Button variant="destructive" size="sm" onClick={handleReject}><X className="w-4 h-4 mr-1" />{t("ocrInvoice.reject")}</Button>
                <Button variant="outline" size="sm" onClick={handleReview} disabled={saving}>{saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}{t("ocrInvoice.saveReview")}</Button>
                {selected?.status === "reviewed" && (
                  <Button size="sm" onClick={handleApprove}><Check className="w-4 h-4 mr-1" />{t("ocrInvoice.approve")}</Button>
                )}
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
