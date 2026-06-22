/**
 * FinancePulseCard — Top-level financial overview for Dashboard.
 * Shows: P&L this month, overdue count+amount, upcoming due count+amount.
 */
import { useState, useEffect } from "react";
import { money } from "@/lib/i18nUtils";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { DollarSign, AlertTriangle, Clock, TrendingUp, Loader2 } from "lucide-react";

export default function FinancePulseCard() {
  const [stats, setStats] = useState(null);
  const [pnl, setPnl] = useState(null);
  const [aging, setAging] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    Promise.all([
      API.get("/finance/stats").catch(() => ({ data: {} })),
      API.get("/org/pnl-overview").catch(() => ({ data: { totals: {} } })),
      API.get("/finance/aging-report").catch(() => ({ data: { totals: {} } })),
    ]).then(([sRes, pRes, aRes]) => {
      setStats(sRes.data);
      setPnl(pRes.data?.totals || {});
      setAging(aRes.data?.totals || {});
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="rounded-xl border border-border bg-card p-4 flex items-center justify-center h-24"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  const profit = pnl?.profit || 0;
  const profitCls = profit > 0 ? "text-emerald-400" : profit < 0 ? "text-red-400" : "text-gray-400";
  const overdueCount = aging?.overdue_count || 0;
  const overdueAmount = aging?.overdue_amount || 0;
  const oldestDays = aging?.oldest_overdue_days || 0;
  const receivablesTotal = stats?.receivables_total || 0;

  return (
    <div className="rounded-xl border border-border bg-card p-4 mb-4" data-testid="finance-pulse-card">
      <div className="flex items-center gap-2 mb-3">
        <DollarSign className="w-5 h-5 text-primary" />
        <h3 className="text-sm font-semibold">Финансов pulse</h3>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* P&L */}
        <button onClick={() => navigate("/finance")} className="text-left rounded-lg border border-border p-3 hover:bg-muted/20 transition-colors">
          <p className="text-[10px] text-muted-foreground">Печалба (общо)<span className="text-[8px] px-1 py-px rounded-full bg-blue-500/15 text-blue-300 ml-1">без ДДС</span></p>
          <p className={`text-lg font-bold font-mono ${profitCls}`}>{money(profit)}</p>
          <p className="text-[9px] text-muted-foreground">Марж: {pnl?.margin_pct || 0}%</p>
        </button>

        {/* Receivables */}
        <button onClick={() => navigate("/finance/invoices")} className="text-left rounded-lg border border-border p-3 hover:bg-muted/20 transition-colors">
          <p className="text-[10px] text-muted-foreground">Вземания<span className="text-[8px] px-1 py-px rounded-full bg-amber-500/15 text-amber-300 ml-1">с ДДС</span></p>
          <p className="text-lg font-bold font-mono">{money(receivablesTotal)}</p>
          <p className="text-[9px] text-muted-foreground">{stats?.receivables_count || 0} фактури</p>
        </button>

        {/* Overdue */}
        <button onClick={() => navigate("/finance/invoices?status=overdue")} className={`text-left rounded-lg border p-3 hover:bg-muted/20 transition-colors ${overdueCount > 0 ? "border-red-500/30 bg-red-500/5" : "border-border"}`}>
          <p className="text-[10px] text-muted-foreground flex items-center gap-1">
            {overdueCount > 0 && <AlertTriangle className="w-3 h-3 text-red-400" />}Просрочени<span className="text-[8px] px-1 py-px rounded-full bg-amber-500/15 text-amber-300 ml-1">с ДДС</span>
          </p>
          <p className={`text-lg font-bold font-mono ${overdueCount > 0 ? "text-red-400" : "text-muted-foreground"}`}>{money(overdueAmount)}</p>
          {overdueCount > 0 && <p className="text-[9px] text-red-400">{overdueCount} бр. · Най-стара: {oldestDays}д</p>}
          {overdueCount === 0 && <p className="text-[9px] text-emerald-400">Няма просрочени</p>}
        </button>

        {/* Cash */}
        <div className="rounded-lg border border-border p-3">
          <p className="text-[10px] text-muted-foreground">Каса + Банка</p>
          <p className="text-lg font-bold font-mono">{money((stats?.cash_balance || 0) + (stats?.bank_balance || 0))}</p>
          <p className="text-[9px] text-muted-foreground">Каса: {stats?.cash_balance || 0} · Банка: {stats?.bank_balance || 0}</p>
        </div>
      </div>
    </div>
  );
}
