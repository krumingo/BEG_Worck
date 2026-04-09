/**
 * ExcelImportV2Modal — 3-step smart Excel import: Upload → Preview → Confirm.
 */
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Upload, Loader2, Check, AlertTriangle, FileSpreadsheet, ArrowRight,
} from "lucide-react";
import { toast } from "sonner";

export default function ExcelImportV2Modal({ open, onOpenChange, projectId, onImported }) {
  const { t } = useTranslation();
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [importing, setImporting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saveName, setSaveName] = useState("");

  useEffect(() => {
    if (open) {
      setStep(1); setFile(null); setPreview(null); setSelectedTemplate("");
      API.get("/excel-import/templates").then(r => setTemplates(r.data.items || [])).catch(() => {});
    }
  }, [open]);

  // Step 1 → Step 2: Upload & preview
  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("import_type", "kss");
      const res = await API.post("/excel-import/preview", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setPreview(res.data);
      setStep(2);
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setLoading(false); }
  };

  // Step 3: Commit import
  const handleCommit = async () => {
    if (!file || !projectId) return;
    setImporting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("project_id", projectId);
      fd.append("import_type", "kss");
      if (selectedTemplate) fd.append("template_id", selectedTemplate);
      const res = await API.post("/excel-import/commit", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`${t("excelImportV2.imported")}: ${res.data.lines_imported} ${t("excelImportV2.lines")}`);
      onImported?.(res.data);
      onOpenChange(false);
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setImporting(false); }
  };

  // Save template
  const handleSaveTemplate = async () => {
    if (!saveName.trim() || !preview?.detected_columns) return;
    try {
      await API.post("/excel-import/templates", {
        name: saveName.trim(),
        import_type: "kss",
        column_mapping: preview.detected_columns,
        detected_headers: preview.headers_raw,
      });
      toast.success(t("excelImportV2.templateSaved"));
      setSaveName("");
    } catch (err) { toast.error(t("common.error")); }
  };

  const conf = preview?.confidence || 0;
  const confColor = conf >= 0.7 ? "text-emerald-400" : conf >= 0.4 ? "text-amber-400" : "text-red-400";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-emerald-400" />
            {t("excelImportV2.title")}
          </DialogTitle>
          <DialogDescription>
            {step === 1 && t("excelImportV2.step1")}
            {step === 2 && t("excelImportV2.step2")}
            {step === 3 && t("excelImportV2.step3")}
          </DialogDescription>
        </DialogHeader>

        {/* Steps indicator */}
        <div className="flex items-center gap-2 mb-4">
          {[1, 2, 3].map(s => (
            <div key={s} className={`flex items-center gap-1 text-xs ${step >= s ? "text-primary" : "text-muted-foreground"}`}>
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${step >= s ? "bg-primary text-primary-foreground" : "bg-muted"}`}>{s}</span>
              {s < 3 && <ArrowRight className="w-3 h-3" />}
            </div>
          ))}
        </div>

        {/* Step 1: Upload */}
        {step === 1 && (
          <div className="space-y-4">
            <div className="border-2 border-dashed border-border rounded-xl p-8 text-center">
              <Upload className="w-8 h-8 mx-auto mb-3 text-muted-foreground" />
              <input type="file" accept=".xlsx,.xls" onChange={e => setFile(e.target.files?.[0] || null)} className="block mx-auto text-sm" data-testid="excel-file-input" />
              {file && <p className="mt-2 text-sm text-emerald-400">{file.name}</p>}
            </div>
            {templates.length > 0 && (
              <div className="space-y-1">
                <Label className="text-xs">{t("excelImportV2.useTemplate")}</Label>
                <Select value={selectedTemplate || "none"} onValueChange={v => setSelectedTemplate(v === "none" ? "" : v)}>
                  <SelectTrigger><SelectValue placeholder={t("excelImportV2.noTemplate")} /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t("excelImportV2.noTemplate")}</SelectItem>
                    {templates.map(t => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}
            <Button onClick={handleUpload} disabled={!file || loading} className="w-full" data-testid="preview-btn">
              {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <ArrowRight className="w-4 h-4 mr-2" />}
              {t("excelImportV2.preview")}
            </Button>
          </div>
        )}

        {/* Step 2: Preview */}
        {step === 2 && preview && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 flex-wrap">
              <Badge variant="outline" className="text-xs">{preview.total_rows} {t("excelImportV2.rows")}</Badge>
              <Badge variant="outline" className="text-xs">{preview.selected_sheet}</Badge>
              <span className={`text-xs font-mono ${confColor}`}>{t("excelImportV2.confidence")}: {Math.round(conf * 100)}%</span>
            </div>

            {preview.warnings?.length > 0 && (
              <div className="space-y-1">
                {preview.warnings.map((w, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-amber-400"><AlertTriangle className="w-3 h-3" />{w}</div>
                ))}
              </div>
            )}

            {/* Detected columns */}
            <div className="text-xs space-y-1">
              <p className="font-semibold text-muted-foreground">{t("excelImportV2.detectedColumns")}:</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(preview.detected_columns || {}).map(([field, col]) => (
                  <Badge key={field} variant="outline" className="text-[10px]">{field}: {col}</Badge>
                ))}
              </div>
            </div>

            {/* Preview table */}
            {preview.preview_rows?.length > 0 && (
              <div className="overflow-x-auto border border-border rounded-lg">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">СМР</TableHead>
                      <TableHead className="text-xs">Ед.</TableHead>
                      <TableHead className="text-xs text-right">Кол.</TableHead>
                      <TableHead className="text-xs text-right">Мат.</TableHead>
                      <TableHead className="text-xs text-right">Труд</TableHead>
                      <TableHead className="text-xs text-right">Общо</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.preview_rows.map((r, i) => (
                      <TableRow key={i} className="text-xs">
                        <TableCell className="truncate max-w-[200px]">{r.smr_type}</TableCell>
                        <TableCell>{r.unit}</TableCell>
                        <TableCell className="text-right font-mono">{r.qty}</TableCell>
                        <TableCell className="text-right font-mono">{r.material_price || "-"}</TableCell>
                        <TableCell className="text-right font-mono">{r.labor_price || "-"}</TableCell>
                        <TableCell className="text-right font-mono">{r.total_price || "-"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}

            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep(1)}>{t("common.back")}</Button>
              <Button onClick={() => setStep(3)} className="flex-1" data-testid="confirm-mapping-btn">
                <Check className="w-4 h-4 mr-2" /> {t("excelImportV2.confirmMapping")}
              </Button>
            </div>
          </div>
        )}

        {/* Step 3: Confirm & Import */}
        {step === 3 && (
          <div className="space-y-4">
            <div className="rounded-lg bg-muted/10 border border-border p-4 text-sm">
              <p><strong>{preview?.total_rows}</strong> {t("excelImportV2.rowsReady")}</p>
              {preview?.warnings?.length > 0 && <p className="text-amber-400 text-xs mt-1">{preview.warnings.length} {t("excelImportV2.warnings")}</p>}
            </div>

            {/* Save template option */}
            <div className="flex gap-2 items-end">
              <div className="flex-1 space-y-1">
                <Label className="text-xs">{t("excelImportV2.saveAsTemplate")}</Label>
                <Input value={saveName} onChange={e => setSaveName(e.target.value)} placeholder={t("excelImportV2.templateName")} />
              </div>
              <Button variant="outline" size="sm" onClick={handleSaveTemplate} disabled={!saveName.trim()}>
                {t("common.save")}
              </Button>
            </div>

            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep(2)}>{t("common.back")}</Button>
              <Button onClick={handleCommit} disabled={importing} className="flex-1" data-testid="commit-import-btn">
                {importing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <FileSpreadsheet className="w-4 h-4 mr-2" />}
                {t("excelImportV2.import")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
