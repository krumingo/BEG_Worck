/**
 * SMRAnalysisListPage — Списък с всички ценови анализи на СМР.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Calculator, Plus, Loader2, Search, Eye, FileSpreadsheet } from "lucide-react";
import { toast } from "sonner";
import ExcelImportV2Modal from "@/components/ExcelImportV2Modal";

const STATUS_CFG = {
  draft: { label: "Чернова", color: "bg-slate-100 text-slate-700" },
  approved: { label: "Одобрен", color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  locked: { label: "Заключен", color: "bg-zinc-100 text-zinc-500" },
};

export default function SMRAnalysisListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fProject, setFProject] = useState("");
  const [fStatus, setFStatus] = useState("");

  // Create dialog
  const [showCreate, setShowCreate] = useState(false);
  const [createProjectId, setCreateProjectId] = useState("");
  const [createName, setCreateName] = useState("");
  const [saving, setSaving] = useState(false);

  // Import V2 modal
  const [showImport, setShowImport] = useState(false);
  const [importProjectId, setImportProjectId] = useState("");

  useEffect(() => {
    API.get("/projects").then(r => setProjects(r.data.items || r.data || [])).catch(() => {});
  }, []);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (fProject) p.append("project_id", fProject);
      if (fStatus) p.append("status", fStatus);
      const res = await API.get(`/smr-analyses?${p}`);
      setItems(res.data.items || []);
    } catch { toast.error(t("common.error")); }
    finally { setLoading(false); }
  }, [fProject, fStatus, t]);

  useEffect(() => { loadItems(); }, [loadItems]);

  const handleCreate = async () => {
    if (!createProjectId || !createName.trim()) {
      toast.error(t("smrAnalysis.fillRequired"));
      return;
    }
    setSaving(true);
    try {
      const res = await API.post("/smr-analyses", { project_id: createProjectId, name: createName.trim() });
      toast.success(t("smrAnalysis.created"));
      setShowCreate(false);
      navigate(`/projects/${createProjectId}/smr-analysis/${res.data.id}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    } finally { setSaving(false); }
  };

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-5xl mx-auto" data-testid="smr-analysis-list-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
            <Calculator className="w-5 h-5 text-cyan-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold">{t("smrAnalysis.listTitle")}</h1>
            <p className="text-sm text-muted-foreground">{t("smrAnalysis.listSubtitle")}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { setImportProjectId(""); setShowImport(true); }} data-testid="import-excel-btn">
            <FileSpreadsheet className="w-4 h-4 mr-2" /> {t("excelImportV2.title")}
          </Button>
          <Button onClick={() => { setCreateName(""); setCreateProjectId(""); setShowCreate(true); }} data-testid="new-analysis-btn">
            <Plus className="w-4 h-4 mr-2" /> {t("smrAnalysis.newAnalysis")}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex gap-4">
            <div className="flex-1">
              <Label className="text-xs mb-1 block">{t("smrAnalysis.project")}</Label>
              <Select value={fProject || "all"} onValueChange={v => setFProject(v === "all" ? "" : v)}>
                <SelectTrigger data-testid="filter-project"><SelectValue placeholder={t("common.all")} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code || p.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <Label className="text-xs mb-1 block">{t("common.status")}</Label>
              <Select value={fStatus || "all"} onValueChange={v => setFStatus(v === "all" ? "" : v)}>
                <SelectTrigger data-testid="filter-status"><SelectValue placeholder={t("common.all")} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {Object.entries(STATUS_CFG).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center py-16 text-muted-foreground gap-2">
              <Search className="w-8 h-8 opacity-40" />
              <p className="text-sm">{t("smrAnalysis.noItems")}</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("smrAnalysis.name")}</TableHead>
                  <TableHead>{t("smrAnalysis.project")}</TableHead>
                  <TableHead className="text-center">v</TableHead>
                  <TableHead>{t("common.status")}</TableHead>
                  <TableHead className="text-right">{t("smrAnalysis.grandTotal")}</TableHead>
                  <TableHead className="text-right">{t("common.date")}</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map(a => {
                  const st = STATUS_CFG[a.status] || STATUS_CFG.draft;
                  return (
                    <TableRow key={a.id} className="cursor-pointer hover:bg-muted/40" onClick={() => navigate(`/projects/${a.project_id}/smr-analysis/${a.id}`)} data-testid={`analysis-row-${a.id}`}>
                      <TableCell className="font-medium">{a.name}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{a.project_name}</TableCell>
                      <TableCell className="text-center"><Badge variant="outline" className="text-[10px]">v{a.version}</Badge></TableCell>
                      <TableCell><Badge className={`text-xs ${st.color}`} variant="outline">{st.label}</Badge></TableCell>
                      <TableCell className="text-right font-mono font-bold">{(a.totals?.grand_total || 0).toFixed(2)} EUR</TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">{new Date(a.created_at).toLocaleDateString("bg-BG")}</TableCell>
                      <TableCell><Eye className="w-4 h-4 text-muted-foreground" /></TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("smrAnalysis.newAnalysis")}</DialogTitle>
            <DialogDescription>{t("smrAnalysis.newAnalysisDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>{t("smrAnalysis.project")} *</Label>
              <Select value={createProjectId || "none"} onValueChange={v => setCreateProjectId(v === "none" ? "" : v)}>
                <SelectTrigger data-testid="create-project-select"><SelectValue placeholder={t("smrAnalysis.selectProject")} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("smrAnalysis.selectProject")}</SelectItem>
                  {projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code ? `${p.code} - ${p.name}` : p.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>{t("smrAnalysis.name")} *</Label>
              <Input value={createName} onChange={e => setCreateName(e.target.value)} placeholder={t("smrAnalysis.namePlaceholder")} data-testid="create-name-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleCreate} disabled={saving} data-testid="create-analysis-submit">
              {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}
              {t("common.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Excel Import V2 Modal */}
      <ExcelImportV2Modal
        open={showImport}
        onOpenChange={setShowImport}
        projectId={importProjectId || fProject || (projects[0]?.id)}
        onImported={(result) => {
          loadItems();
          if (result?.analysis_id) {
            const pid = importProjectId || fProject || projects[0]?.id;
            navigate(`/projects/${pid}/smr-analysis/${result.analysis_id}`);
          }
        }}
      />
    </div>
  );
}
