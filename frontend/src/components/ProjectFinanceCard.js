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
  const net = data.total_invoiced_net ?? data.total_revenue ?? 0;
  const invoiced = data.total_invoiced ?? data.total_revenue ?? 0;
  const received = data.total_received || 0;
  const remaining = Math.max(0, invoiced - received);
  const outVat = data.output_vat || 0;
  const inVat = data.input_vat || 0;
  const vatPayable = data.vat_payable ?? (outVat - inVat);

  const exBadge = <span className="text-[9px] px-1.5 py-px rounded-full bg-blue-500/15 text-blue-300 ml-2 shrink-0">без ДДС</span>;
  const incBadge = <span className="text-[9px] px-1.5 py-px rounded-full bg-amber-500/15 text-amber-300 ml-2 shrink-0">с ДДС</span>;
  const sectionTitle = "text-[10px] uppercase tracking-wide text-gray-500 mb-1";

  return (
    <button onClick={onNavigateFinance} className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 text-left hover:bg-gray-700/30 transition-colors w-full" data-testid="project-finance-card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2"><DollarSign className="w-5 h-5 text-primary" /><h3 className="font-semibold text-white">Финансов статус</h3></div>
        <Badge variant="outline" className={`text-[9px] ${statusCls}`}>{statusLabel}</Badge>
      </div>

      <p className={sectionTitle}>Управленски резултат</p>
      <div className="space-y-1 text-xs">
        <div className="flex justify-between items-center"><span className="text-gray-400">Приход</span><span className="flex items-center"><span className="font-mono text-white">{fmt(net)}</span>{exBadge}</span></div>
        <div className="flex justify-between items-center"><span className="text-gray-400">Разходи</span><span className="flex items-center"><span className="font-mono text-red-400">{fmt(data.total_expense)}</span>{exBadge}</span></div>
        <div className="flex justify-between items-center pt-1 border-t border-gray-700/60"><span className="text-white font-medium">Баланс</span><span className="flex items-center"><span className={`font-mono font-bold ${profit >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(profit)}</span>{exBadge}</span></div>
        <div className="flex justify-between items-center"><span className="text-gray-400">Марж</span><span className="flex items-center"><span className={`font-mono font-bold ${margin > 5 ? "text-emerald-400" : margin > -5 ? "text-amber-400" : "text-red-400"}`}>{margin}%</span>{exBadge}</span></div>
      </div>

      <p className={`${sectionTitle} mt-3`}>Парично (каса)</p>
      <div className="space-y-1 text-xs">
        <div className="flex justify-between items-center"><span className="text-gray-400">Фактурирано</span><span className="flex items-center"><span className="font-mono text-white">{fmt(invoiced)}</span>{incBadge}</span></div>
        <div className="flex justify-between items-center"><span className="text-gray-400">Получено</span><span className="flex items-center"><span className="font-mono text-emerald-400">{fmt(received)}</span>{incBadge}</span></div>
        {remaining > 0 && <div className="flex justify-between items-center"><span className="text-amber-400">Остава</span><span className="flex items-center"><span className="font-mono text-amber-400">{fmt(remaining)}</span>{incBadge}</span></div>}
      </div>

      <p className={`${sectionTitle} mt-3`}>ДДС сметка</p>
      <div className="space-y-1 text-xs">
        <div className="flex justify-between"><span className="text-gray-400">Изходящ (продажби)</span><span className="font-mono text-white">{fmt(outVat)}</span></div>
        <div className="flex justify-between"><span className="text-gray-400">− Входящ (разходи)</span><span className="font-mono text-red-400">{fmt(inVat)}</span></div>
        <div className="flex justify-between pt-1 border-t border-gray-700/60"><span className="text-white font-medium">ДДС за внасяне</span><span className="font-mono font-bold text-white">{fmt(vatPayable)}</span></div>
      </div>
    </button>
  );
}
