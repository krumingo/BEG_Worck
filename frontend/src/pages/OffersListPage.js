import { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
  FileText,
  Plus,
  Search,
  ArrowRight,
  Filter,
  Upload,
  Download,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Sent: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Accepted: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Rejected: "bg-red-500/20 text-red-400 border-red-500/30",
  Archived: "bg-violet-500/20 text-violet-400 border-violet-500/30",
};

export default function OffersListPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectIdParam = searchParams.get("projectId") || "";

  const [offers, setOffers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState(projectIdParam);
  const [typeFilter, setTypeFilter] = useState("");

  const canCreate = ["Admin", "Owner", "SiteManager"].includes(user?.role);

  // New offer dialog
  const [newOfferOpen, setNewOfferOpen] = useState(false);
  const [newOfferType, setNewOfferType] = useState("main");
  const [newOfferNotes, setNewOfferNotes] = useState("");

  // Import state
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importPreview, setImportPreview] = useState(null);
  const [importProject, setImportProject] = useState("");
  const [importTitle, setImportTitle] = useState("");
  const [importSaving, setImportSaving] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [offersRes, projectsRes] = await Promise.all([
        API.get(`/offers${projectFilter ? `?project_id=${projectFilter}` : ""}${statusFilter ? `${projectFilter ? "&" : "?"}status=${statusFilter}` : ""}`),
        API.get("/projects"),
      ]);
      setOffers(offersRes.data);
      setProjects(projectsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [projectFilter, statusFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filteredOffers = offers.filter(o => {
    if (search && !(
      o.offer_no?.toLowerCase().includes(search.toLowerCase()) ||
      o.title?.toLowerCase().includes(search.toLowerCase()) ||
      o.project_code?.toLowerCase().includes(search.toLowerCase())
    )) return false;
    if (typeFilter === "main" && o.offer_type === "extra") return false;
    if (typeFilter === "extra" && o.offer_type !== "extra") return false;
    return true;
  });

  const mainCount = offers.filter(o => o.offer_type !== "extra").length;
  const extraCount = offers.filter(o => o.offer_type === "extra").length;

  const formatCurrency = (amount, currency = "EUR") => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount || 0);
  };

  // Import handlers
  const handleImportFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportFile(file);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await API.post("/offers/import-preview", formData, { headers: { "Content-Type": "multipart/form-data" } });
      setImportPreview(res.data);
      setImportTitle(`Импорт: ${file.name}`);
    } catch (err) { alert(err.response?.data?.detail || "Грешка при парсиране"); }
  };

  const handleImportConfirm = async () => {
    if (!importPreview || !importProject) { alert("Изберете проект"); return; }
    setImportSaving(true);
    try {
      const res = await API.post("/offers/import-confirm", {
        project_id: importProject, title: importTitle, lines: importPreview.lines,
        file_name: importFile?.name, offer_type: "main", currency: "EUR", vat_percent: 20,
      });
      setImportOpen(false); setImportPreview(null); setImportFile(null);
      navigate(`/offers/${res.data.id}`);
    } catch (err) { alert(err.response?.data?.detail || "Грешка при импорт"); }
    finally { setImportSaving(false); }
  };

  return (
    <div className="p-8 max-w-[1400px]" data-testid="offers-list-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("offers.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("offers.subtitle")}</p>
        </div>
        {canCreate && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={async () => {
              const res = await API.get("/offer-import-template", { responseType: 'blob' });
              const url = window.URL.createObjectURL(new Blob([res.data]));
              const a = document.createElement('a'); a.href = url; a.download = 'BEG_Work_Offer_Import_Template.xlsx';
              document.body.appendChild(a); a.click(); a.remove();
            }} data-testid="download-template-btn" className="text-xs">
              <Download className="w-4 h-4 mr-1" /> Шаблон
            </Button>
            <Button variant="outline" onClick={() => setImportOpen(true)} data-testid="import-offer-btn">
              <Upload className="w-4 h-4 mr-1" /> Импорт
            </Button>
            <Button onClick={() => { setNewOfferType("main"); setNewOfferNotes(""); setNewOfferOpen(true); }} data-testid="create-offer-btn">
              <Plus className="w-4 h-4 mr-2" /> {t("offers.newOffer")}
            </Button>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6 flex-wrap" data-testid="offers-filters">
        <div className="relative flex-1 min-w-[200px] max-w-[300px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder={t("offers.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-card"
            data-testid="search-input"
          />
        </div>
        <Select value={projectFilter} onValueChange={(v) => {
          setProjectFilter(v === "all" ? "" : v);
          if (v === "all") searchParams.delete("projectId");
          else searchParams.set("projectId", v);
          setSearchParams(searchParams);
        }}>
          <SelectTrigger className="w-[200px] bg-card" data-testid="project-filter">
            <Filter className="w-4 h-4 mr-2 text-muted-foreground" />
            <SelectValue placeholder={t("common.allProjects")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allProjects")}</SelectItem>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[150px] bg-card" data-testid="status-filter">
            <SelectValue placeholder={t("common.allStatuses")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allStatuses")}</SelectItem>
            <SelectItem value="Draft">{t("offers.status.draft")}</SelectItem>
            <SelectItem value="Sent">{t("offers.status.sent")}</SelectItem>
            <SelectItem value="Accepted">{t("offers.status.accepted")}</SelectItem>
            <SelectItem value="Rejected">{t("offers.status.rejected")}</SelectItem>
          </SelectContent>
        </Select>
        <div className="flex rounded-lg border border-border overflow-hidden" data-testid="type-filter">
          <button onClick={() => setTypeFilter("")} className={`px-3 py-1.5 text-xs transition-colors ${!typeFilter ? "bg-primary text-primary-foreground" : "bg-card text-muted-foreground hover:text-foreground"}`}>Всички</button>
          <button onClick={() => setTypeFilter("main")} className={`px-3 py-1.5 text-xs border-l border-border transition-colors ${typeFilter === "main" ? "bg-primary text-primary-foreground" : "bg-card text-muted-foreground hover:text-foreground"}`}>Основни ({mainCount})</button>
          <button onClick={() => setTypeFilter("extra")} className={`px-3 py-1.5 text-xs border-l border-border transition-colors ${typeFilter === "extra" ? "bg-amber-500 text-black" : "bg-card text-muted-foreground hover:text-foreground"}`}>Допълнителни ({extraCount})</button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="offers-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("offers.offer")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("offers.project")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.status")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("offers.version")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("offers.lines")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.total")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredOffers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    <FileText className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>{t("offers.noOffers")}</p>
                    {canCreate && (
                      <Button variant="outline" className="mt-4" onClick={() => navigate("/offers/new")}>
                        {t("offers.createFirstOffer")}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                filteredOffers.map((offer) => (
                  <TableRow 
                    key={offer.id} 
                    className={`table-row-hover cursor-pointer ${offer.offer_type === "extra" ? "border-l-2 border-l-amber-500/50" : ""}`}
                    onClick={() => navigate(`/offers/${offer.id}`)}
                    data-testid={`offer-row-${offer.id}`}
                  >
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <p className="font-mono text-sm text-primary">{offer.offer_no}</p>
                        <Badge variant="outline" className={`text-[9px] ${offer.offer_type === "extra" ? "bg-amber-500/15 text-amber-400 border-amber-500/30" : "bg-blue-500/10 text-blue-400 border-blue-500/30"}`}>
                          {offer.offer_type === "extra" ? "Допълнителна" : "Основна"}
                        </Badge>
                      </div>
                      <p className="text-sm text-foreground truncate max-w-[250px]">{offer.title}</p>
                    </TableCell>
                    <TableCell>
                      <p className="font-mono text-xs text-primary">{offer.project_code}</p>
                      <p className="text-xs text-muted-foreground truncate max-w-[150px]">{offer.project_name}</p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs ${STATUS_COLORS[offer.status] || ""}`}>
                        {t(`offers.status.${offer.status.toLowerCase()}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">v{offer.version}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{offer.line_count}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-foreground">
                      {formatCurrency(offer.total, offer.currency)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/offers/${offer.id}`); }}>
                        <ArrowRight className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Import Dialog */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="sm:max-w-[700px] bg-card border-border max-h-[85vh] overflow-y-auto" data-testid="import-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Upload className="w-5 h-5 text-primary" /> Импорт на оферта от Excel</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            {!importPreview ? (
              <div className="border-2 border-dashed border-border rounded-lg p-8 text-center">
                <Upload className="w-10 h-10 mx-auto mb-3 text-muted-foreground opacity-40" />
                <p className="text-sm text-muted-foreground mb-3">Качете .xlsx файл с оферта</p>
                <input type="file" accept=".xlsx,.xls" onChange={handleImportFile} className="hidden" id="import-file" />
                <label htmlFor="import-file" className="cursor-pointer inline-flex items-center px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90">
                  <Upload className="w-4 h-4 mr-2" /> Избери файл
                </label>
              </div>
            ) : (
              <>
                <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-sm">
                  <p className="text-emerald-400 font-medium">Файл: {importPreview.file_name}</p>
                  <p className="text-emerald-300/70">Разпознати: {importPreview.parsed_lines} реда от {importPreview.total_rows} общо</p>
                </div>
                {importPreview.warnings?.length > 0 && (
                  <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-xs space-y-1">
                    {importPreview.warnings.map((w, i) => <p key={i} className="text-amber-400">{w}</p>)}
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label>Проект *</Label>
                    <select value={importProject} onChange={e => setImportProject(e.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
                      <option value="">Изберете проект</option>
                      {projects.map(p => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <Label>Заглавие</Label>
                    <Input value={importTitle} onChange={e => setImportTitle(e.target.value)} className="bg-background" />
                  </div>
                </div>
                {/* Preview table */}
                <div className="overflow-x-auto max-h-[300px] overflow-y-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 sticky top-0"><tr>
                      <th className="p-2 text-left">Описание</th>
                      <th className="p-2">Мярка</th>
                      <th className="p-2 text-right">К-во</th>
                      <th className="p-2 text-right">Мат.</th>
                      <th className="p-2 text-right">Труд</th>
                      <th className="p-2 text-right">Общо</th>
                    </tr></thead>
                    <tbody className="divide-y divide-border">
                      {importPreview.lines.map((l, i) => (
                        <tr key={i} className="hover:bg-muted/20">
                          <td className="p-2 text-foreground">{l.description}{l.note && <span className="text-muted-foreground ml-1">({l.note})</span>}</td>
                          <td className="p-2 text-center text-muted-foreground">{l.unit}</td>
                          <td className="p-2 text-right font-mono">{l.qty}</td>
                          <td className="p-2 text-right font-mono">{l.material_price.toFixed(2)}</td>
                          <td className="p-2 text-right font-mono">{l.labor_price.toFixed(2)}</td>
                          <td className="p-2 text-right font-mono font-medium">{((l.material_price + l.labor_price) * l.qty).toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="text-right text-sm font-mono">
                  Общо: <span className="font-bold text-primary">{importPreview.lines.reduce((s, l) => s + (l.material_price + l.labor_price) * l.qty, 0).toFixed(2)} лв</span>
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setImportOpen(false); setImportPreview(null); setImportFile(null); }}>Затвори</Button>
            {importPreview && (
              <Button onClick={handleImportConfirm} disabled={importSaving || !importProject} data-testid="confirm-import-btn">
                {importSaving ? <span className="animate-spin mr-1">...</span> : <Plus className="w-4 h-4 mr-1" />}
                Създай оферта ({importPreview.parsed_lines} реда)
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Offer Type Dialog */}
      <Dialog open={newOfferOpen} onOpenChange={setNewOfferOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border">
          <DialogHeader><DialogTitle>Нова оферта</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-xs">Тип оферта</Label>
              <div className="grid grid-cols-2 gap-2">
                <button onClick={() => setNewOfferType("main")} className={`p-3 rounded-xl border text-center text-sm ${newOfferType === "main" ? "border-blue-500 bg-blue-500/10 text-blue-400" : "border-border text-muted-foreground hover:text-foreground"}`}>
                  <FileText className="w-5 h-5 mx-auto mb-1" />Основна
                </button>
                <button onClick={() => setNewOfferType("extra")} className={`p-3 rounded-xl border text-center text-sm ${newOfferType === "extra" ? "border-amber-500 bg-amber-500/10 text-amber-400" : "border-border text-muted-foreground hover:text-foreground"}`}>
                  <Plus className="w-5 h-5 mx-auto mb-1" />Допълнителна
                </button>
              </div>
            </div>
            {newOfferType === "extra" && (
              <div className="space-y-1">
                <Label className="text-xs">Причина / описание</Label>
                <Input value={newOfferNotes} onChange={e => setNewOfferNotes(e.target.value)} placeholder="Допълнителни дейности по..." className="bg-background" />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewOfferOpen(false)}>Отказ</Button>
            <Button onClick={() => {
              const params = new URLSearchParams({ offer_type: newOfferType });
              if (newOfferType === "extra" && newOfferNotes) params.set("notes", newOfferNotes);
              navigate(`/offers/new?${params.toString()}`);
              setNewOfferOpen(false);
            }}>Продължи</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
