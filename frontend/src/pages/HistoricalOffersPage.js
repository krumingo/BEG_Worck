import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
  Archive, Upload, Loader2, BarChart3, Search, TrendingUp, AlertTriangle, Plus, FileText,
} from "lucide-react";
import { formatDate } from "@/lib/i18nUtils";

export default function HistoricalOffersPage() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState("");
  const [cityFilter, setCityFilter] = useState("");
  const [search, setSearch] = useState("");

  // Import state
  const [importOpen, setImportOpen] = useState(false);
  const [importPreview, setImportPreview] = useState(null);
  const [importMeta, setImportMeta] = useState({ source_project_name: "", source_date: "", city: "", source_offer_name: "" });
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const params = {};
      if (typeFilter) params.activity_type = typeFilter;
      if (cityFilter) params.city = cityFilter;
      const res = await API.get("/historical/analytics", { params });
      setData(res.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [typeFilter, cityFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Import handlers
  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await API.post("/historical/import-preview", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setImportPreview(res.data);
      setImportMeta(prev => ({ ...prev, file_name: file.name }));
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
  };

  const handleConfirmImport = async () => {
    if (!importPreview) return;
    setSaving(true);
    try {
      await API.post("/historical/import-confirm", {
        ...importMeta, lines: importPreview.lines,
      });
      setImportOpen(false);
      setImportPreview(null);
      setLoading(true);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  const filtered = data?.categories?.filter(c => {
    if (search) return c.activity_type.toLowerCase().includes(search.toLowerCase()) || c.activity_subtype.toLowerCase().includes(search.toLowerCase());
    return true;
  }) || [];

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  return (
    <div className="p-6 max-w-[1400px]" data-testid="historical-offers-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Archive className="w-6 h-6 text-violet-500" /> Историческа ценова база
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Анализ на архивни оферти за AI ценови предложения</p>
        </div>
        <Button onClick={() => { setImportPreview(null); setImportOpen(true); }} data-testid="import-historical-btn">
          <Upload className="w-4 h-4 mr-1" /> Импорт на архивна оферта
        </Button>
      </div>

      {/* Overview */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <div className="rounded-xl border border-border bg-card p-4" data-testid="card-total-rows">
            <p className="text-xs text-muted-foreground">Исторически редове</p>
            <p className="text-2xl font-bold text-foreground mt-1">{data.total_rows}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4">
            <p className="text-xs text-muted-foreground">Импорт пакети</p>
            <p className="text-2xl font-bold text-foreground mt-1">{data.total_batches}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4">
            <p className="text-xs text-muted-foreground">Категории</p>
            <p className="text-2xl font-bold text-foreground mt-1">{data.categories?.length || 0}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4">
            <p className="text-xs text-muted-foreground">Градове</p>
            <p className="text-2xl font-bold text-foreground mt-1">{data.unique_cities?.length || 0}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="relative flex-1 max-w-[300px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input placeholder="Търсене..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9 bg-card" />
        </div>
        <Select value={typeFilter || "all"} onValueChange={v => setTypeFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[180px] bg-card"><SelectValue placeholder="Всички типове" /></SelectTrigger>
          <SelectContent><SelectItem value="all">Всички типове</SelectItem>{(data?.unique_types || []).map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={cityFilter || "all"} onValueChange={v => setCityFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[160px] bg-card"><SelectValue placeholder="Всички градове" /></SelectTrigger>
          <SelectContent><SelectItem value="all">Всички градове</SelectItem>{(data?.unique_cities || []).map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      <Tabs defaultValue="analytics">
        <TabsList className="mb-4">
          <TabsTrigger value="analytics" data-testid="tab-analytics"><BarChart3 className="w-4 h-4 mr-1" /> Сравнителни таблици</TabsTrigger>
          <TabsTrigger value="batches" data-testid="tab-batches"><FileText className="w-4 h-4 mr-1" /> Импорти ({data?.total_batches || 0})</TabsTrigger>
        </TabsList>

        <TabsContent value="analytics">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="analytics-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Категория</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Подтип</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Ед.</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Случаи</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Мед. материал</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Мед. труд</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Мед. общо</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Мин.</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Макс.</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {filtered.length === 0 ? (
                  <TableRow><TableCell colSpan={9} className="text-center py-12 text-muted-foreground"><Archive className="w-10 h-10 mx-auto mb-3 opacity-30" /><p>Няма исторически данни</p><p className="text-xs mt-1">Импортирайте архивни оферти за да генерирате ценова база</p></TableCell></TableRow>
                ) : filtered.map((c, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-sm font-medium text-foreground">{c.activity_type}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{c.activity_subtype}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{c.unit}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{c.sample_count}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-blue-400">{c.median_material.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-amber-400">{c.median_labor.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-sm font-bold text-primary">{c.median_total.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-muted-foreground">{c.min_total.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-muted-foreground">{c.max_total.toFixed(2)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        <TabsContent value="batches">
          <div className="space-y-2">
            {(data?.batches || []).length === 0 ? (
              <div className="text-center py-12 text-muted-foreground"><Upload className="w-10 h-10 mx-auto mb-3 opacity-30" /><p>Няма импортирани пакети</p></div>
            ) : (data?.batches || []).map(b => (
              <div key={b.id} className="p-3 rounded-lg bg-muted/20 border border-border flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">{b.file_name || "Без име"}</p>
                  <p className="text-xs text-muted-foreground">{b.source_project_name && `${b.source_project_name} | `}{b.city && `${b.city} | `}{formatDate(b.created_at)}</p>
                </div>
                <Badge variant="outline" className="text-xs">{b.rows_imported} реда</Badge>
              </div>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      {/* Import Dialog */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="sm:max-w-[700px] bg-card border-border max-h-[85vh] overflow-y-auto" data-testid="historical-import-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Archive className="w-5 h-5 text-violet-500" /> Импорт на архивна оферта</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            {!importPreview ? (
              <div className="border-2 border-dashed border-border rounded-lg p-8 text-center">
                <Upload className="w-10 h-10 mx-auto mb-3 text-muted-foreground opacity-40" />
                <p className="text-sm text-muted-foreground mb-3">Качете .xlsx файл с архивна оферта</p>
                <input type="file" accept=".xlsx,.xls" onChange={handleFile} className="hidden" id="hist-file" />
                <label htmlFor="hist-file" className="cursor-pointer inline-flex items-center px-4 py-2 rounded-md bg-violet-600 text-white text-sm font-medium hover:bg-violet-700">
                  <Upload className="w-4 h-4 mr-2" /> Избери файл
                </label>
              </div>
            ) : (
              <>
                <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-sm">
                  <p className="text-emerald-400 font-medium">{importPreview.file_name}: {importPreview.parsed_lines} реда ({importPreview.skipped_sections} секционни пропуснати)</p>
                </div>
                {importPreview.warnings?.length > 0 && (
                  <div className="p-2 rounded bg-amber-500/10 border border-amber-500/30 text-xs space-y-0.5 max-h-[60px] overflow-y-auto">
                    {importPreview.warnings.slice(0, 5).map((w, i) => <p key={i} className="text-amber-400"><AlertTriangle className="w-3 h-3 inline mr-1" />{w}</p>)}
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1"><Label>Проект/обект</Label><Input value={importMeta.source_project_name} onChange={e => setImportMeta(p => ({...p, source_project_name: e.target.value}))} placeholder="Напр. Къща Бояна" className="bg-background text-sm" /></div>
                  <div className="space-y-1"><Label>Дата/година</Label><Input value={importMeta.source_date} onChange={e => setImportMeta(p => ({...p, source_date: e.target.value}))} placeholder="2020 или 2020-06" className="bg-background text-sm" /></div>
                  <div className="space-y-1"><Label>Град</Label><Input value={importMeta.city} onChange={e => setImportMeta(p => ({...p, city: e.target.value}))} placeholder="София" className="bg-background text-sm" /></div>
                  <div className="space-y-1"><Label>Име на оферта</Label><Input value={importMeta.source_offer_name} onChange={e => setImportMeta(p => ({...p, source_offer_name: e.target.value}))} placeholder="Оферта 2020-001" className="bg-background text-sm" /></div>
                </div>
                <div className="overflow-x-auto max-h-[250px] overflow-y-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 sticky top-0"><tr>
                      <th className="p-1.5 text-left">СМР (оригинал)</th>
                      <th className="p-1.5">Тип</th>
                      <th className="p-1.5">Подтип</th>
                      <th className="p-1.5">Ед.</th>
                      <th className="p-1.5 text-right">Мат./ед</th>
                      <th className="p-1.5 text-right">Труд/ед</th>
                      <th className="p-1.5 text-right">Общо/ед</th>
                    </tr></thead>
                    <tbody className="divide-y divide-border">
                      {importPreview.lines.slice(0, 30).map((l, i) => (
                        <tr key={i} className="hover:bg-muted/20">
                          <td className="p-1.5 text-foreground max-w-[200px] truncate">{l.raw_smr_text}</td>
                          <td className="p-1.5 text-muted-foreground">{l.normalized_activity_type}</td>
                          <td className="p-1.5 text-muted-foreground">{l.normalized_activity_subtype}</td>
                          <td className="p-1.5 text-center">{l.unit}</td>
                          <td className="p-1.5 text-right font-mono">{l.material_price_per_unit.toFixed(2)}</td>
                          <td className="p-1.5 text-right font-mono">{l.labor_price_per_unit.toFixed(2)}</td>
                          <td className="p-1.5 text-right font-mono font-medium">{l.total_price_per_unit.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setImportOpen(false); setImportPreview(null); }}>Затвори</Button>
            {importPreview && (
              <Button onClick={handleConfirmImport} disabled={saving} className="bg-violet-600 hover:bg-violet-700" data-testid="confirm-historical-import">
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Archive className="w-4 h-4 mr-1" />}
                Импортирай {importPreview.parsed_lines} реда
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
