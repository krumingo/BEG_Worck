import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  ArrowLeft, TrendingUp, TrendingDown, AlertTriangle, Shield, Loader2,
  DollarSign, Users, Package, Hammer, Building2, BarChart3,
} from "lucide-react";

import BudgetForecastPanel from "@/components/BudgetForecastPanel";

function Metric({ label, value, suffix = "", color = "", partial = false, small = false }) {
  return (
    <div className={small ? "" : ""}>
      <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className={`font-mono ${small ? "text-sm" : "text-lg"} font-bold ${color || "text-foreground"} ${partial ? "opacity-60" : ""}`}>
        {value != null ? `${typeof value === "number" ? value.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : value}${suffix ? ` ${suffix}` : ""}` : "—"}
        {partial && <span className="text-[8px] ml-1 font-normal text-muted-foreground">(частично)</span>}
      </p>
    </div>
  );
}

const SEVERITY_COLORS = {
  info: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  warning: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  critical: "bg-red-500/15 text-red-400 border-red-500/30",
};

export default function ProjectFinancialPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [profit, setProfit] = useState(null);
  const [packages, setPackages] = useState([]);
  const [alerts, setAlerts] = useState(null);
  const [risk, setRisk] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailPkg, setDetailPkg] = useState(null);
  const [detailData, setDetailData] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [profitRes, pkgRes, alertRes, riskRes] = await Promise.all([
        API.get(`/project-net-profit/${projectId}`),
        API.get(`/execution-packages/financial-breakdown/${projectId}`),
        API.get(`/financial-alerts/${projectId}`),
        API.get(`/project-risk/${projectId}`),
      ]);
      setProfit(profitRes.data);
      setPackages(pkgRes.data.packages || []);
      setAlerts(alertRes.data);
      setRisk(riskRes.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openDetail = async (pkgId) => {
    try {
      const res = await API.get(`/execution-packages/${pkgId}/net-financial`);
      setDetailData(res.data);
      setDetailPkg(pkgId);
    } catch { /* */ }
  };

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  const r = profit?.revenue || {};
  const c = profit?.costs || {};
  const p = profit?.profit || {};
  const ma = profit?.metrics_available || {};

  return (
    <div className="p-6 max-w-[1400px]" data-testid="project-financial-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate(`/projects/${projectId}`)}>
            <ArrowLeft className="w-4 h-4 mr-1" /> Обект
          </Button>
          <div>
            <h1 className="text-xl font-bold text-foreground flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-primary" /> Финансов преглед
            </h1>
            <p className="text-sm text-muted-foreground">{profit?.project_code} — {profit?.project_name}</p>
          </div>
        </div>
        {risk && (
          <Badge variant="outline" className={`text-sm px-3 py-1 ${risk.risk_level === "high" ? "bg-red-500/15 text-red-400" : risk.risk_level === "medium" ? "bg-amber-500/15 text-amber-400" : risk.risk_level === "low" ? "bg-blue-500/15 text-blue-400" : "bg-emerald-500/15 text-emerald-400"}`} data-testid="risk-badge">
            <Shield className="w-4 h-4 mr-1 inline" /> Риск: {risk.risk_level === "high" ? "Висок" : risk.risk_level === "medium" ? "Среден" : risk.risk_level === "low" ? "Нисък" : "OK"}
          </Badge>
        )}
      </div>

      {/* ═══ PHASE 1: Financial Overview ═══ */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6" data-testid="financial-overview">
        {/* Revenue */}
        <div className="rounded-xl border border-border bg-card p-4 col-span-2 md:col-span-4">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3 flex items-center gap-1"><DollarSign className="w-3.5 h-3.5" /> Приходи (EUR)</h3>
          <div className="grid grid-cols-5 gap-4">
            <Metric label="Договорено" value={r.contracted} partial={!ma.revenue} />
            <Metric label="Изпълнено" value={r.earned} color="text-emerald-400" partial={!ma.earned} />
            <Metric label="Фактурирано" value={r.billed} />
            <Metric label="Събрано" value={r.collected} color="text-emerald-400" />
            <Metric label="Вземания" value={r.receivables} color={r.receivables > 0 ? "text-amber-400" : ""} />
          </div>
        </div>

        {/* Costs */}
        <div className="rounded-xl border border-border bg-card p-4 col-span-2 md:col-span-4">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3 flex items-center gap-1"><Package className="w-3.5 h-3.5" /> Разходи (EUR)</h3>
          <div className="grid grid-cols-6 gap-4">
            <Metric label="Материали" value={c.material} partial={!ma.material} />
            <Metric label="Труд" value={c.labor} partial={!ma.labor} />
            <Metric label="Подизпълнители" value={c.subcontract} partial={!ma.subcontract} />
            <Metric label="Режийни" value={c.overhead} partial={!ma.overhead} />
            <Metric label="Общ разход" value={c.total_cost} color="text-red-400" />
            <div>
              <p className="text-[10px] text-muted-foreground uppercase">Труд часове</p>
              <p className="font-mono text-lg font-bold text-foreground">{profit?.detail?.labor?.total_hours || "—"}ч</p>
            </div>
          </div>
        </div>

        {/* Profit */}
        <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 col-span-2">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3">Печалба</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-[10px] text-muted-foreground">Бруто печалба</p>
              <p className={`font-mono text-2xl font-bold ${(p.gross_profit || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {p.gross_profit != null ? p.gross_profit.toLocaleString("en", {minimumFractionDigits: 2}) : "—"}
              </p>
              <p className="text-xs text-muted-foreground">{p.gross_margin_percent != null ? `${p.gross_margin_percent}%` : ""} марж</p>
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground">Нето печалба</p>
              <p className={`font-mono text-2xl font-bold ${(p.net_profit || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {p.net_profit != null ? p.net_profit.toLocaleString("en", {minimumFractionDigits: 2}) : "—"}
              </p>
              <p className="text-xs text-muted-foreground">{p.net_margin_percent != null ? `${p.net_margin_percent}%` : ""} нето марж</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4 col-span-2">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3">Очаквано vs Реално</h3>
          <div className="grid grid-cols-2 gap-4">
            <Metric label="Очаквана печалба" value={p.expected_profit} />
            <Metric label="Отклонение" value={p.actual_vs_expected_variance} color={p.actual_vs_expected_variance < 0 ? "text-red-400" : "text-emerald-400"} />
          </div>
        </div>
      </div>

      {/* ═══ PHASE 3: Alerts Panel ═══ */}
      {alerts && alerts.total > 0 && (
        <div className="mb-6 space-y-2" data-testid="alerts-panel">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500" /> Предупреждения ({alerts.total})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {alerts.alerts.map((a, i) => (
              <div key={i} className={`flex items-start gap-3 p-3 rounded-lg border ${SEVERITY_COLORS[a.severity] || ""}`} data-testid={`alert-${i}`}>
                <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium">{a.message}</p>
                  {a.amount && <p className="text-xs opacity-70">{a.amount} EUR</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Risk flags */}
      {risk && risk.flag_count > 0 && (
        <div className="mb-6 p-3 rounded-lg border border-border bg-muted/10" data-testid="risk-panel">
          <div className="flex flex-wrap gap-2">
            {risk.risk_flags.map((f, i) => (
              <Badge key={i} variant="outline" className="text-[10px]">{risk.explanations[i]}</Badge>
            ))}
          </div>
        </div>
      )}

      {/* ═══ PHASE 2: Execution Packages Table ═══ */}
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="packages-table">
        <div className="p-4 border-b border-border">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Hammer className="w-4 h-4 text-primary" /> Изпълнителни пакети ({packages.length})
          </h3>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-[10px] uppercase text-muted-foreground">Дейност</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Продажба</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Мат. бюдж.</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Мат. факт</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Труд бюдж.</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Труд факт</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Подизп.</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Общ разход</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Марж</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {packages.length === 0 ? (
                <TableRow><TableCell colSpan={10} className="text-center py-8 text-muted-foreground">Няма пакети</TableCell></TableRow>
              ) : packages.map((pkg, i) => {
                const hasVar = (pkg.material_variance != null && pkg.material_variance > 0) || (pkg.labor_variance != null && pkg.labor_variance > 0);
                return (
                  <TableRow key={i} className={`cursor-pointer hover:bg-muted/30 ${hasVar ? "bg-red-500/5" : ""}`} onClick={() => openDetail(pkg.id)} data-testid={`pkg-row-${i}`}>
                    <TableCell className="text-sm font-medium">{pkg.activity_name}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{pkg.sale_total?.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-muted-foreground">{pkg.material_budget?.toFixed(2)}</TableCell>
                    <TableCell className={`text-right font-mono text-sm ${pkg.material_variance > 0 ? "text-red-400" : ""}`}>{pkg.material_actual?.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-muted-foreground">{pkg.labor_budget?.toFixed(2)}</TableCell>
                    <TableCell className={`text-right font-mono text-sm ${pkg.labor_variance > 0 ? "text-red-400" : ""}`}>{pkg.labor_actual?.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{pkg.subcontract_actual?.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-sm font-bold">{pkg.total_actual?.toFixed(2)}</TableCell>
                    <TableCell className={`text-right font-mono text-sm font-bold ${(pkg.gross_margin || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {pkg.gross_margin != null ? pkg.gross_margin.toFixed(2) : "—"}
                    </TableCell>
                    <TableCell>
                      {hasVar && <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Budget Forecast & EV Analysis */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="budget-forecast-section">
        <BudgetForecastPanel projectId={projectId} />
      </div>

      {/* ═══ PHASE 4: Package Detail Dialog ═══ */}
      <Dialog open={!!detailPkg} onOpenChange={() => { setDetailPkg(null); setDetailData(null); }}>
        <DialogContent className="sm:max-w-[600px] bg-card border-border" data-testid="pkg-detail-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Hammer className="w-5 h-5 text-primary" /> {detailData?.activity_name}
            </DialogTitle>
          </DialogHeader>
          {detailData && (
            <div className="space-y-4 py-2">
              {/* Revenue */}
              <div className="p-3 rounded-lg bg-muted/20 border border-border">
                <p className="text-xs text-muted-foreground mb-2 uppercase">Приход</p>
                <p className="text-xl font-mono font-bold text-foreground">{detailData.sale_total?.toFixed(2)} EUR</p>
              </div>

              {/* Costs breakdown */}
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 rounded-lg border border-border">
                  <p className="text-[10px] text-muted-foreground">Материали</p>
                  <p className="font-mono text-sm">{detailData.costs?.material?.toFixed(2)} EUR</p>
                </div>
                <div className="p-3 rounded-lg border border-border">
                  <p className="text-[10px] text-muted-foreground">Труд</p>
                  <p className="font-mono text-sm">{detailData.costs?.labor?.toFixed(2)} EUR</p>
                </div>
                <div className="p-3 rounded-lg border border-border">
                  <p className="text-[10px] text-muted-foreground">Подизпълнители</p>
                  <p className="font-mono text-sm">{detailData.costs?.subcontract?.toFixed(2)} EUR</p>
                </div>
                <div className="p-3 rounded-lg border border-border">
                  <p className="text-[10px] text-muted-foreground">Режийни</p>
                  <p className="font-mono text-sm">{detailData.costs?.overhead?.toFixed(2)} EUR</p>
                </div>
              </div>

              {/* Margin */}
              <div className="grid grid-cols-2 gap-3">
                <div className={`p-3 rounded-lg border ${(detailData.margin?.gross_margin || 0) >= 0 ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5"}`}>
                  <p className="text-[10px] text-muted-foreground">Бруто марж</p>
                  <p className={`font-mono text-lg font-bold ${(detailData.margin?.gross_margin || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {detailData.margin?.gross_margin?.toFixed(2)} EUR
                  </p>
                  <p className="text-xs text-muted-foreground">{detailData.margin?.gross_margin_percent}%</p>
                </div>
                <div className={`p-3 rounded-lg border ${(detailData.margin?.net_margin || 0) >= 0 ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5"}`}>
                  <p className="text-[10px] text-muted-foreground">Нето марж</p>
                  <p className={`font-mono text-lg font-bold ${(detailData.margin?.net_margin || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {detailData.margin?.net_margin?.toFixed(2)} EUR
                  </p>
                  <p className="text-xs text-muted-foreground">{detailData.margin?.net_margin_percent}%</p>
                </div>
              </div>

              {/* Expected vs actual */}
              <div className="flex items-center gap-4 text-sm">
                <span className="text-muted-foreground">Очакван марж:</span>
                <span className="font-mono">{detailData.margin?.expected_margin?.toFixed(2) || "—"} EUR</span>
                <span className="text-muted-foreground">Отклонение:</span>
                <span className={`font-mono font-bold ${(detailData.margin?.margin_variance || 0) < 0 ? "text-red-400" : "text-emerald-400"}`}>
                  {detailData.margin?.margin_variance?.toFixed(2) || "—"} EUR
                </span>
              </div>

              {detailData.metrics_partial && (
                <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-400">Частични данни — някои компоненти липсват</Badge>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
