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
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

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
  const [weeklyData, setWeeklyData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    Promise.all([
      API.get("/cashflow/forecast/compact"),
      API.get("/cashflow/forecast"),
    ]).then(([compactRes, fullRes]) => {
      setData(compactRes.data);
      // Group timeline into 4 weeks
      const timeline = fullRes.data?.timeline || [];
      const weeks = [];
      for (let w = 0; w < 4; w++) {
        const start = w * 7;
        const end = Math.min(start + 7, timeline.length);
        const slice = timeline.slice(start, end);
        if (slice.length === 0) break;
        const income = slice.reduce((s, d) => s + (d.incoming || 0), 0);
        const expenses = slice.reduce((s, d) => s + (d.outgoing || 0), 0);
        const balance = slice[slice.length - 1]?.cumulative || 0;
        const warnLevel = balance < 0 ? "critical" : balance < (fullRes.data?.summary?.total_incoming || 1) * 0.1 ? "warning" : "ok";
        weeks.push({
          label: `Седм. ${w + 1}`,
          dateRange: `${slice[0]?.date?.slice(5)} — ${slice[slice.length - 1]?.date?.slice(5)}`,
          income: Math.round(income),
          expenses: Math.round(expenses),
          balance: Math.round(balance),
          warning_level: warnLevel,
        });
      }
      setWeeklyData(weeks);
    }).catch(() => {}).finally(() => setLoading(false));
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

      {/* Weekly forecast table + chart */}
      {weeklyData.length > 0 && (
        <div className="mb-3 space-y-3">
          <div className="grid grid-cols-4 gap-1 text-[10px]">
            {weeklyData.map(w => {
              const balColor = w.warning_level === "critical" ? "text-red-400" : w.warning_level === "warning" ? "text-amber-400" : "text-emerald-400";
              return (
                <div key={w.label} className="rounded-lg border border-border/50 p-2 text-center">
                  <p className="font-semibold text-[9px] text-muted-foreground">{w.label}</p>
                  <p className="text-[8px] text-muted-foreground mb-1">{w.dateRange}</p>
                  <p className="text-emerald-400 font-mono">+{w.income}</p>
                  <p className="text-red-400 font-mono">-{w.expenses}</p>
                  <p className={`font-mono font-bold ${balColor}`}>{w.balance}</p>
                </div>
              );
            })}
          </div>
          <div className="h-24">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={weeklyData} barGap={2}>
                <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#888" }} axisLine={false} tickLine={false} />
                <YAxis hide />
                <Tooltip contentStyle={{ background: "#1a1a2e", border: "1px solid #333", borderRadius: 8, fontSize: 11 }} />
                <Bar dataKey="balance" radius={[4, 4, 0, 0]}>
                  {weeklyData.map((w, i) => (
                    <Cell key={i} fill={w.warning_level === "critical" ? "#ef4444" : w.warning_level === "warning" ? "#f59e0b" : "#10b981"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

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
