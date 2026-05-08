import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
  Package, AlertTriangle, Loader2, Search, Warehouse, TrendingUp, ArrowRight, ArrowDown, RotateCcw, MapPin,
} from "lucide-react";

export default function InventoryDashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showLowOnly, setShowLowOnly] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const res = await API.get("/inventory/dashboard");
      setData(res.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  if (!data) return <div className="p-6 text-center text-muted-foreground">Няма данни</div>;

  const { overview, stock, top_moved, project_remainders } = data;

  const filteredStock = stock.filter(s => {
    if (showLowOnly && !s.is_low_stock) return false;
    if (search) {
      return s.material_name.toLowerCase().includes(search.toLowerCase());
    }
    return true;
  });

  return (
    <div className="p-6 max-w-[1400px]" data-testid="inventory-dashboard">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
          <Warehouse className="w-6 h-6 text-teal-500" /> Наличности
        </h1>
        <p className="text-sm text-muted-foreground mt-1">Складов dashboard с наличности, алерти и движения</p>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
        <div className="rounded-xl border border-border bg-card p-4" data-testid="card-total-materials">
          <p className="text-xs text-muted-foreground">Материали</p>
          <p className="text-2xl font-bold text-foreground mt-1">{overview.total_materials}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4" data-testid="card-total-value">
          <p className="text-xs text-muted-foreground">Стойност</p>
          <p className="text-xl font-bold text-foreground mt-1">{formatCurrency(overview.total_value, "BGN")}</p>
        </div>
        <div className={`rounded-xl border p-4 ${overview.low_stock_count > 0 ? "border-red-500/30 bg-red-500/5" : "border-border bg-card"}`} data-testid="card-low-stock">
          <p className="text-xs text-muted-foreground">Ниски наличности</p>
          <p className={`text-2xl font-bold mt-1 ${overview.low_stock_count > 0 ? "text-red-400" : "text-foreground"}`}>{overview.low_stock_count}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4" data-testid="card-on-projects">
          <p className="text-xs text-muted-foreground">По обекти</p>
          <p className="text-2xl font-bold text-amber-400 mt-1">{overview.on_projects_count}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground flex items-center gap-1"><ArrowDown className="w-3 h-3 text-emerald-400" /> Входящи (30д)</p>
          <p className="text-xl font-bold text-emerald-400 mt-1">{overview.recent_intakes}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground flex items-center gap-1"><ArrowRight className="w-3 h-3 text-blue-400" /> Отпуснати (30д)</p>
          <p className="text-xl font-bold text-blue-400 mt-1">{overview.recent_issues}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground flex items-center gap-1"><RotateCcw className="w-3 h-3 text-violet-400" /> Върнати (30д)</p>
          <p className="text-xl font-bold text-violet-400 mt-1">{overview.recent_returns}</p>
        </div>
      </div>

      <Tabs defaultValue="stock">
        <TabsList className="mb-4">
          <TabsTrigger value="stock" data-testid="tab-stock"><Package className="w-4 h-4 mr-1" /> Наличности ({stock.length})</TabsTrigger>
          <TabsTrigger value="movements" data-testid="tab-movements"><TrendingUp className="w-4 h-4 mr-1" /> Движения</TabsTrigger>
          <TabsTrigger value="projects" data-testid="tab-projects"><MapPin className="w-4 h-4 mr-1" /> По обекти ({project_remainders.length})</TabsTrigger>
        </TabsList>

        {/* Stock Tab */}
        <TabsContent value="stock">
          <div className="flex items-center gap-3 mb-4">
            <div className="relative flex-1 max-w-[300px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input placeholder="Търсене по материал..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9 bg-card" data-testid="stock-search" />
            </div>
            <Button variant={showLowOnly ? "default" : "outline"} size="sm" onClick={() => setShowLowOnly(!showLowOnly)} className={showLowOnly ? "bg-red-600" : ""} data-testid="low-stock-filter">
              <AlertTriangle className="w-4 h-4 mr-1" /> Ниски ({overview.low_stock_count})
            </Button>
          </div>
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="stock-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Материал</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Мярка</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Налично</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Стойност</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Праг</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {filteredStock.length === 0 ? (
                  <TableRow><TableCell colSpan={6} className="text-center py-12 text-muted-foreground"><Package className="w-10 h-10 mx-auto mb-3 opacity-30" /><p>Няма материали</p></TableCell></TableRow>
                ) : filteredStock.map((s, i) => (
                  <TableRow key={i} className={s.is_low_stock ? "bg-red-500/5" : ""} data-testid={`stock-row-${i}`}>
                    <TableCell className="text-sm font-medium text-foreground">{s.material_name}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{s.unit}</TableCell>
                    <TableCell className={`text-right font-mono text-sm font-bold ${s.is_low_stock ? "text-red-400" : "text-foreground"}`}>{s.qty}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-muted-foreground">{s.value > 0 ? formatCurrency(s.value, "BGN") : "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-muted-foreground">{s.low_stock_threshold}</TableCell>
                    <TableCell>
                      {s.is_low_stock ? (
                        <Badge variant="outline" className="text-[10px] bg-red-500/20 text-red-400 border-red-500/30"><AlertTriangle className="w-3 h-3 mr-0.5" /> Ниско</Badge>
                      ) : (
                        <Badge variant="outline" className="text-[10px] bg-emerald-500/20 text-emerald-400 border-emerald-500/30">OK</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* Movements Tab */}
        <TabsContent value="movements">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="movements-table">
            <div className="p-4 border-b border-border">
              <h3 className="text-sm font-semibold text-foreground">Топ движения (последни 30 дни)</h3>
            </div>
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Материал</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Движения</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Входящи</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Отпуснати</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Върнати</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {top_moved.length === 0 ? (
                  <TableRow><TableCell colSpan={5} className="text-center py-12 text-muted-foreground">Няма движения за последните 30 дни</TableCell></TableRow>
                ) : top_moved.map((m, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-sm font-medium text-foreground">{m.material_name}</TableCell>
                    <TableCell className="text-right font-mono text-sm font-bold text-foreground">{m.moves}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-emerald-400">{m.intake_qty || "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-blue-400">{m.issue_qty || "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-violet-400">{m.return_qty || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* Projects Tab */}
        <TabsContent value="projects">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="projects-table">
            <div className="p-4 border-b border-border">
              <h3 className="text-sm font-semibold text-foreground">Остатъци по обекти</h3>
            </div>
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Обект</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Материал</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Мярка</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Отпуснато</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Вложено</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Върнато</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Остатък</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {project_remainders.length === 0 ? (
                  <TableRow><TableCell colSpan={7} className="text-center py-12 text-muted-foreground">Няма материали по обекти</TableCell></TableRow>
                ) : project_remainders.map((r, i) => (
                  <TableRow key={i} className="cursor-pointer hover:bg-muted/30" onClick={() => navigate(`/projects/${r.project_id}`)}>
                    <TableCell className="text-sm"><span className="font-mono text-primary">{r.project_code}</span> <span className="text-muted-foreground">{r.project_name}</span></TableCell>
                    <TableCell className="text-sm text-foreground">{r.material_name}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{r.unit}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-cyan-400">{r.issued}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-amber-400">{r.consumed}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-violet-400">{r.returned}</TableCell>
                    <TableCell className="text-right font-mono text-sm font-bold text-emerald-400">
                      {r.remaining}
                      {r.remaining > r.issued * 0.3 && <Badge variant="outline" className="ml-1 text-[8px] bg-amber-500/10 text-amber-400 border-amber-500/30">Висок</Badge>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
