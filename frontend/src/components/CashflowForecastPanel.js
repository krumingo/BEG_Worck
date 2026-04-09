/**
 * CashflowForecastPanel — 30-day cash flow projection.
 */
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  TrendingUp, TrendingDown, DollarSign, AlertTriangle,
  Loader2, ArrowUpRight, ChevronDown, ChevronRight,
} from "lucide-react";

const WARN_CFG = {
  ok: { color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20", label: "OK" },
  watch: { color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20", label: "Внимание" },
  risk: { color: "text-orange-400", bg: "bg-orange-500/10 border-orange-500/20", label: "Риск" },
  critical: { color: "text-red-400", bg: "bg-red-500/10 border-red-500/20", label: "Критично" },
};

export default function CashflowForecastPanel() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    API.get("/cashflow/forecast/compact").then(r => setData(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="rounded-xl border border-border bg-card p-4 flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const warn = WARN_CFG[data.warning_level] || WARN_CFG.ok;

  return (
    <div className={`rounded-xl border p-5 mb-6 ${warn.bg}`} data-testid="cashflow-forecast-panel">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center">
          <DollarSign className="w-5 h-5 text-emerald-400" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold">{t("dashboard.cashflowForecast.title")}</h2>
            <Badge variant="outline" className={`text-[10px] ${warn.color}`}>{warn.label}</Badge>
          </div>
          <p className="text-xs text-muted-foreground">{data.headline}</p>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        <div className="text-center">
          <TrendingUp className="w-4 h-4 mx-auto mb-1 text-emerald-400" />
          <p className="font-mono font-bold text-sm text-emerald-400">{(data.total_incoming || 0).toFixed(0)}</p>
          <p className="text-[9px] text-muted-foreground">{t("dashboard.cashflowForecast.incoming")}</p>
        </div>
        <div className="text-center">
          <TrendingDown className="w-4 h-4 mx-auto mb-1 text-red-400" />
          <p className="font-mono font-bold text-sm text-red-400">{(data.total_outgoing || 0).toFixed(0)}</p>
          <p className="text-[9px] text-muted-foreground">{t("dashboard.cashflowForecast.outgoing")}</p>
        </div>
        <div className="text-center">
          <DollarSign className="w-4 h-4 mx-auto mb-1 text-primary" />
          <p className={`font-mono font-bold text-sm ${(data.net_forecast || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>{(data.net_forecast || 0).toFixed(0)}</p>
          <p className="text-[9px] text-muted-foreground">{t("dashboard.cashflowForecast.net")}</p>
        </div>
        <div className="text-center">
          <AlertTriangle className={`w-4 h-4 mx-auto mb-1 ${(data.overdue_receivables || 0) > 0 ? "text-red-400" : "text-emerald-400"}`} />
          <p className="font-mono font-bold text-sm">{(data.overdue_receivables || 0).toFixed(0)}</p>
          <p className="text-[9px] text-muted-foreground">{t("dashboard.cashflowForecast.overdue")}</p>
        </div>
      </div>

      {/* Expand for top items */}
      <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground w-full">
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {t("dashboard.cashflowForecast.details")}
      </button>

      {expanded && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
          {data.top_incoming?.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">{t("dashboard.cashflowForecast.topIncoming")}</p>
              {data.top_incoming.map((item, i) => (
                <div key={i} className="flex justify-between text-xs p-1.5 rounded bg-emerald-500/5 mb-1">
                  <span className="truncate flex-1">{item.title}</span>
                  <span className="font-mono text-emerald-400 ml-2">+{item.amount?.toFixed(0)}</span>
                </div>
              ))}
            </div>
          )}
          {data.top_outgoing?.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">{t("dashboard.cashflowForecast.topOutgoing")}</p>
              {data.top_outgoing.map((item, i) => (
                <div key={i} className="flex justify-between text-xs p-1.5 rounded bg-red-500/5 mb-1">
                  <span className="truncate flex-1">{item.title}</span>
                  <span className="font-mono text-red-400 ml-2">-{item.amount?.toFixed(0)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Quick links */}
      <div className="flex gap-3 mt-3 text-[10px]">
        <button onClick={() => navigate("/finance")} className="text-primary hover:underline flex items-center gap-0.5">{t("dashboard.cashflowForecast.viewFinance")} <ArrowUpRight className="w-2.5 h-2.5" /></button>
        <button onClick={() => navigate("/payroll")} className="text-primary hover:underline flex items-center gap-0.5">{t("dashboard.cashflowForecast.viewPayroll")} <ArrowUpRight className="w-2.5 h-2.5" /></button>
      </div>
    </div>
  );
}
