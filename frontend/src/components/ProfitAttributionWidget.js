/**
 * ProfitAttributionWidget — "Why am I profitable/losing" for Dashboard.
 */
import { useState, useEffect } from "react";
import { money } from "@/lib/i18nUtils";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TrendingUp, TrendingDown, PieChart, Loader2, ArrowRight } from "lucide-react";
import { PieChart as RechartsPie, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

const COLORS = { labor: "#ef4444", materials: "#f97316", overhead: "#eab308", subcontractor: "#8b5cf6" };
const LABELS = { labor: "Труд", materials: "Материали", overhead: "Режийни", subcontractor: "Подизп." };
const REASON_LABELS = { labor_over_budget: "Труд над бюджет", materials_over_budget: "Материали над бюджет", low_margin: "Нисък марж", unknown: "Неизвестно" };

export default function ProfitAttributionWidget() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    API.get("/org/pnl-attribution").then(r => setData(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="rounded-xl border border-border bg-card p-4 flex justify-center h-20"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const { totals, top_winners, top_losers, expense_breakdown } = data;
  const donutData = Object.entries(expense_breakdown || {}).filter(([, v]) => v.amount > 0).map(([k, v]) => ({ name: LABELS[k] || k, value: v.amount, pct: v.pct, fill: COLORS[k] || "#888" }));
  const fmt = (n) => `${(n || 0).toLocaleString("bg-BG", { maximumFractionDigits: 0 })} €`;

  return (
    <div className="rounded-xl border border-border bg-card p-4 mb-4" data-testid="profit-attribution">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2"><PieChart className="w-5 h-5 text-primary" /><h3 className="text-sm font-semibold">Защо си на {totals.profit >= 0 ? "печалба" : "загуба"}</h3><span className="text-[8px] px-1 py-px rounded-full bg-blue-500/15 text-blue-300">без ДДС</span></div>
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => navigate("/finance/analysis")}>Пълен анализ <ArrowRight className="w-3 h-3 ml-1" /></Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Winners */}
        <div className="space-y-2">
          <p className="text-[10px] font-semibold text-emerald-400 flex items-center gap-1"><TrendingUp className="w-3 h-3" />Най-печеливши</p>
          {top_winners.length === 0 && <p className="text-xs text-muted-foreground">Няма</p>}
          {top_winners.map(p => (
            <button key={p.id} onClick={() => navigate(`/projects/${p.id}#finance`)} className="w-full text-left flex justify-between text-xs p-1.5 rounded hover:bg-muted/20">
              <span className="truncate">{p.name || p.code}</span>
              <span className="text-emerald-400 font-mono">{fmt(p.gross_profit)} ({p.margin_pct}%)</span>
            </button>
          ))}
        </div>

        {/* Losers */}
        <div className="space-y-2">
          <p className="text-[10px] font-semibold text-red-400 flex items-center gap-1"><TrendingDown className="w-3 h-3" />Най-губещи</p>
          {top_losers.length === 0 && <p className="text-xs text-muted-foreground">Няма</p>}
          {top_losers.map(p => (
            <button key={p.id} onClick={() => navigate(`/projects/${p.id}#finance`)} className="w-full text-left flex justify-between text-xs p-1.5 rounded hover:bg-muted/20">
              <span className="truncate">{p.name || p.code}</span>
              <div className="text-right">
                <span className="text-red-400 font-mono">{fmt(p.gross_profit)}</span>
                {p.reason && <Badge variant="outline" className="text-[7px] ml-1 text-red-400 border-red-500/30">{REASON_LABELS[p.reason] || p.reason}</Badge>}
              </div>
            </button>
          ))}
        </div>

        {/* Expense donut */}
        <div>
          <p className="text-[10px] font-semibold text-muted-foreground mb-1">Разходна структура</p>
          {donutData.length > 0 ? (
            <div className="h-28">
              <ResponsiveContainer width="100%" height="100%">
                <RechartsPie>
                  <Pie data={donutData} cx="50%" cy="50%" innerRadius={25} outerRadius={45} dataKey="value" stroke="none">
                    {donutData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#1a1a2e", border: "1px solid #333", borderRadius: 8, fontSize: 11 }} formatter={(v, n) => [`${v.toLocaleString("bg-BG")} €`, n]} />
                </RechartsPie>
              </ResponsiveContainer>
            </div>
          ) : <p className="text-xs text-muted-foreground">Няма разходи</p>}
          <div className="flex flex-wrap gap-2 mt-1">
            {donutData.map(d => <span key={d.name} className="text-[9px]" style={{ color: d.fill }}>{d.name}: {d.pct}%</span>)}
          </div>
        </div>
      </div>
    </div>
  );
}
