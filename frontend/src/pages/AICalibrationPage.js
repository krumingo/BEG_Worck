import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Sparkles, TrendingUp, Check, Eye, BarChart3, Loader2, Search, Shield, X,
} from "lucide-react";

const STATUS_COLORS = {
  observation: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  suggested: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  ready: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  approved: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
};
const STATUS_LABELS = {
  observation: "Наблюдение",
  suggested: "Предложение",
  ready: "Готово за одобрение",
  approved: "Одобрено",
};

export default function AICalibrationPage() {
  const { user } = useAuth();
  const [overview, setOverview] = useState(null);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [cityFilter, setCityFilter] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [approving, setApproving] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [ovRes, catRes] = await Promise.all([
        API.get("/ai-calibration/overview"),
        API.get("/ai-calibration/categories", { params: cityFilter ? { city: cityFilter } : {} }),
      ]);
      setOverview(ovRes.data);
      setCategories(catRes.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [cityFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleApprove = async (cat) => {
    if (!window.confirm(`Одобрявате калибрация ${cat.suggested_factor.toFixed(3)}x за ${cat.activity_type}/${cat.activity_subtype}?`)) return;
    setApproving(cat);
    try {
      await API.post("/ai-calibration/approve", {
        activity_type: cat.activity_type,
        activity_subtype: cat.activity_subtype,
        city: cat.city,
        small_qty: cat.small_qty,
        factor: cat.suggested_factor,
        sample_count: cat.sample_count,
        avg_delta: cat.avg_delta_percent,
      });
      fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка");
    } finally { setApproving(null); }
  };

  const filtered = categories.filter(c => {
    if (searchFilter) {
      const s = searchFilter.toLowerCase();
      return (c.activity_type?.toLowerCase().includes(s) || c.activity_subtype?.toLowerCase().includes(s));
    }
    return true;
  });

  const uniqueCities = [...new Set(categories.map(c => c.city).filter(Boolean))];

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  }

  return (
    <div className="p-6 max-w-[1400px]" data-testid="ai-calibration-page">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
          <Sparkles className="w-6 h-6 text-violet-500" /> AI Калибрация
        </h1>
        <p className="text-sm text-muted-foreground mt-1">Анализ и калибрация на AI ценови предложения спрямо реални корекции</p>
      </div>

      {/* Overview Cards */}
      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          <div className="rounded-xl border border-border bg-card p-4" data-testid="card-total">
            <p className="text-xs text-muted-foreground">AI предложения</p>
            <p className="text-2xl font-bold text-foreground mt-1">{overview.total_proposals}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4" data-testid="card-accepted">
            <p className="text-xs text-muted-foreground">Приети без промяна</p>
            <p className="text-2xl font-bold text-emerald-400 mt-1">{overview.accepted_unchanged}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4" data-testid="card-edited">
            <p className="text-xs text-muted-foreground">Редактирани</p>
            <p className="text-2xl font-bold text-amber-400 mt-1">{overview.manually_edited}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4" data-testid="card-rate">
            <p className="text-xs text-muted-foreground">Точност</p>
            <p className="text-2xl font-bold text-foreground mt-1">{overview.acceptance_rate}%</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4" data-testid="card-delta">
            <p className="text-xs text-muted-foreground">Ср. отклонение</p>
            <p className={`text-2xl font-bold mt-1 ${overview.avg_edit_delta_percent > 0 ? "text-red-400" : overview.avg_edit_delta_percent < 0 ? "text-blue-400" : "text-foreground"}`}>
              {overview.avg_edit_delta_percent > 0 ? "+" : ""}{overview.avg_edit_delta_percent}%
            </p>
          </div>
        </div>
      )}

      {/* Top Corrected Categories */}
      {overview?.top_corrected_categories?.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4 mb-6">
          <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-amber-500" /> Най-коригирани категории
          </h3>
          <div className="flex flex-wrap gap-2">
            {overview.top_corrected_categories.map((c, i) => (
              <Badge key={i} variant="outline" className="text-xs">
                {c.category} ({c.count}x, {c.avg_delta > 0 ? "+" : ""}{c.avg_delta}%)
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-[300px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input placeholder="Търсене по категория..." value={searchFilter} onChange={e => setSearchFilter(e.target.value)} className="pl-9 bg-card" data-testid="search-filter" />
        </div>
        <Select value={cityFilter || "all"} onValueChange={v => setCityFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[160px] bg-card" data-testid="city-filter"><SelectValue placeholder="Всички градове" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Всички градове</SelectItem>
            {uniqueCities.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {/* Categories Table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="categories-table">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-xs uppercase text-muted-foreground">Категория</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground">Град</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground">Малко к-во</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground text-right">Случаи</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground text-right">Редакции</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground text-right">Ср. AI цена</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground text-right">Ср. крайна цена</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground text-right">Медиана &Delta;</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground text-right">Коефициент</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground text-right">Действия</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={11} className="text-center py-12 text-muted-foreground">
                  <BarChart3 className="w-10 h-10 mx-auto mb-3 opacity-30" />
                  <p>Няма данни за калибрация</p>
                  <p className="text-xs mt-1">Записите се натрупват при използване на AI предложения</p>
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((cat, i) => (
                <TableRow key={i} data-testid={`cal-row-${i}`}>
                  <TableCell>
                    <span className="text-sm text-foreground font-medium">{cat.activity_type}</span>
                    {cat.activity_subtype && <span className="text-xs text-muted-foreground ml-1">/ {cat.activity_subtype}</span>}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{cat.city || "—"}</TableCell>
                  <TableCell>{cat.small_qty ? <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-400">Да</Badge> : "—"}</TableCell>
                  <TableCell className="text-right font-mono text-sm">{cat.sample_count}</TableCell>
                  <TableCell className="text-right font-mono text-sm text-amber-400">{cat.edited_count}</TableCell>
                  <TableCell className="text-right font-mono text-sm">{cat.avg_ai_price.toFixed(2)}</TableCell>
                  <TableCell className="text-right font-mono text-sm">{cat.avg_final_price.toFixed(2)}</TableCell>
                  <TableCell className={`text-right font-mono text-sm font-medium ${cat.median_delta_percent > 0 ? "text-red-400" : cat.median_delta_percent < 0 ? "text-blue-400" : ""}`}>
                    {cat.median_delta_percent > 0 ? "+" : ""}{cat.median_delta_percent}%
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm font-bold">
                    {cat.approved_factor ? <span className="text-emerald-400">{cat.approved_factor.toFixed(3)}x</span> : <span className="text-muted-foreground">{cat.suggested_factor.toFixed(3)}x</span>}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-[10px] ${STATUS_COLORS[cat.calibration_status]}`}>
                      {STATUS_LABELS[cat.calibration_status]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {(cat.calibration_status === "ready" || cat.calibration_status === "suggested") && (
                      <Button size="sm" variant="outline" onClick={() => handleApprove(cat)}
                        disabled={approving === cat}
                        className="text-xs border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
                        data-testid={`approve-btn-${i}`}>
                        {approving === cat ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3 mr-1" />}
                        Одобри
                      </Button>
                    )}
                    {cat.calibration_status === "approved" && (
                      <Badge variant="outline" className="text-[10px] bg-emerald-500/10 text-emerald-400 border-emerald-500/30">
                        <Shield className="w-3 h-3 mr-0.5" /> Активно
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Legend */}
      <div className="mt-4 p-3 rounded-lg bg-muted/20 border border-border">
        <p className="text-xs text-muted-foreground">
          <span className="font-medium">Режими:</span>{" "}
          <Badge variant="outline" className="text-[9px] bg-gray-500/10 text-gray-400 mx-1">Наблюдение</Badge> &lt;{5} случая |{" "}
          <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 mx-1">Предложение</Badge> {5}-{9} случая |{" "}
          <Badge variant="outline" className="text-[9px] bg-blue-500/10 text-blue-400 mx-1">Готово</Badge> &ge;{10} случая |{" "}
          <Badge variant="outline" className="text-[9px] bg-emerald-500/10 text-emerald-400 mx-1">Одобрено</Badge> Админ одобрил
        </p>
      </div>
    </div>
  );
}
