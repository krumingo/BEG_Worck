/**
 * ProjectFinanceCard — Financial status card for project overview.
 * Shows: Budget, Invoiced, Received, Awaiting, Profit + margin traffic light.
 */
import { useState, useEffect } from "react";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { DollarSign, Loader2 } from "lucide-react";

export default function ProjectFinanceCard({ projectId, onNavigateFinance }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    API.get(`/projects/${projectId}/pnl/summary`).then(r => setData(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, [projectId]);

  if (loading) return <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 flex justify-center h-24"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const margin = data.margin_pct || 0;
  const profit = data.gross_profit || 0;
  const statusCls = margin > 5 ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
    : margin > -5 ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
    : "bg-red-500/10 border-red-500/30 text-red-400";
  const statusLabel = margin > 5 ? "Печеливш" : margin > -5 ? "Нулев" : "На загуба";

  const fmt = (n) => (n || 0).toLocaleString("bg-BG", { maximumFractionDigits: 0 });
  const invoiced = data.total_invoiced ?? data.total_revenue ?? 0;
  const received = data.total_received || 0;
  const remaining = Math.max(0, invoiced - received);

  return (
    <button onClick={onNavigateFinance} className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 text-left hover:bg-gray-700/30 transition-colors w-full" data-testid="project-finance-card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2"><DollarSign className="w-5 h-5 text-primary" /><h3 className="font-semibold text-white">Финансов статус</h3></div>
        <Badge variant="outline" className={`text-[9px] ${statusCls}`}>{statusLabel}</Badge>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div><p className="text-gray-400">Бюджет</p><p className="font-mono text-white">{fmt(data.total_budget)}</p></div>
        <div><p className="text-gray-400">Фактурирано</p><p className="font-mono text-white">{fmt(invoiced)}</p></div>
        <div><p className="text-gray-400">Получено</p><p className="font-mono text-emerald-400">{fmt(received)}</p></div>
        <div><p className="text-gray-400">Разходи</p><p className="font-mono text-red-400">{fmt(data.total_expense)}</p></div>
        <div><p className="text-gray-400">Печалба</p><p className={`font-mono font-bold ${profit >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(profit)}</p></div>
        <div><p className="text-gray-400">Марж</p><p className={`font-mono font-bold ${margin > 5 ? "text-emerald-400" : margin > -5 ? "text-amber-400" : "text-red-400"}`}>{margin}%</p></div>
      </div>
      {remaining > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-700 flex justify-between text-xs">
          <span className="text-amber-400">Остава за получаване:</span>
          <span className="font-mono font-bold text-amber-400">{fmt(remaining)}</span>
        </div>
      )}
    </button>
  );
}
