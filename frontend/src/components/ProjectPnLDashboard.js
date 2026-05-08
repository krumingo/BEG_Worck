/**
 * ProjectPnLDashboard — Unified P&L view per project.
 * Embedded in ProjectDetailPage.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  DollarSign, TrendingUp, TrendingDown, Loader2, Wallet,
  Hammer, Package, Users, Building2, ChevronDown, ChevronRight,
} from "lucide-react";

export default function ProjectPnLDashboard({ projectId }) {
  const { t } = useTranslation();
  const [pnl, setPnl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/pnl`);
      setPnl(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!pnl) return null;

  const { budget, revenue, expense, profit } = pnl;
  const statusColor = profit.status === "profitable" ? "text-emerald-400" : profit.status === "loss" ? "text-red-400" : "text-amber-400";
  const statusBg = profit.status === "profitable" ? "bg-emerald-500/10" : profit.status === "loss" ? "bg-red-500/10" : "bg-amber-500/10";

  return (
    <div className="space-y-4" data-testid="project-pnl-dashboard">
      <div className="flex items-center gap-2 mb-1">
        <DollarSign className="w-4 h-4 text-emerald-400" />
        <span className="font-semibold text-sm">{t("pnl.title")}</span>
        <Badge variant="outline" className={`text-xs ${statusColor} ${statusBg}`}>
          {profit.status === "profitable" ? t("pnl.profitable") : profit.status === "loss" ? t("pnl.loss") : t("pnl.breakEven")}
        </Badge>
      </div>

      {/* 4 main cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-lg border border-border p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">{t("pnl.budget")}</p>
          <p className="font-mono font-bold text-lg">{budget.total_budget.toFixed(0)}</p>
          <p className="text-[9px] text-muted-foreground">EUR</p>
        </div>
        <div className="rounded-lg border border-border p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">{t("pnl.revenue")}</p>
          <p className="font-mono font-bold text-lg text-blue-400">{revenue.total_revenue.toFixed(0)}</p>
          <p className="text-[9px] text-muted-foreground">{t("pnl.paid")}: {revenue.paid_total.toFixed(0)}</p>
        </div>
        <div className="rounded-lg border border-border p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">{t("pnl.expense")}</p>
          <p className="font-mono font-bold text-lg text-orange-400">{expense.total_expense.toFixed(0)}</p>
          <p className="text-[9px] text-muted-foreground">{expense.labor_hours.toFixed(0)}ч {t("pnl.labor")}</p>
        </div>
        <div className={`rounded-lg border border-border p-3 text-center ${statusBg}`}>
          <p className="text-[10px] text-muted-foreground uppercase">{t("pnl.profit")}</p>
          <p className={`font-mono font-bold text-lg ${statusColor}`}>{profit.gross_profit.toFixed(0)}</p>
          <p className={`text-[9px] ${statusColor}`}>{profit.margin_pct}%</p>
        </div>
      </div>

      {/* Burn progress */}
      {budget.total_budget > 0 && (
        <div>
          <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
            <span>{t("pnl.budgetUsed")}</span>
            <span>{Math.min(Math.round(expense.total_expense / budget.total_budget * 100), 999)}%</span>
          </div>
          <Progress value={Math.min(expense.total_expense / budget.total_budget * 100, 100)} className="h-1.5" />
        </div>
      )}

      {/* Expandable breakdown */}
      <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground w-full">
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {t("pnl.breakdown")}
      </button>

      {expanded && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          {/* Expense breakdown */}
          <div className="space-y-1.5">
            <p className="font-medium text-muted-foreground uppercase text-[10px]">{t("pnl.expenseBreakdown")}</p>
            {[
              { icon: Hammer, label: t("pnl.laborCost"), val: expense.labor_cost, sub: `${expense.labor_hours.toFixed(0)}ч (OT: ${expense.overtime_cost.toFixed(0)})` },
              { icon: Package, label: t("pnl.materialCost"), val: expense.material_cost },
              { icon: Users, label: t("pnl.subcontractorCost"), val: expense.subcontractor_cost },
              { icon: Building2, label: t("pnl.contractCost"), val: expense.contract_cost },
              { icon: Wallet, label: t("pnl.overhead"), val: expense.overhead },
            ].map(({ icon: Icon, label, val, sub }) => (
              <div key={label} className="flex items-center justify-between p-1.5 rounded bg-muted/10">
                <div className="flex items-center gap-2">
                  <Icon className="w-3 h-3 text-muted-foreground" />
                  <span>{label}</span>
                </div>
                <div className="text-right">
                  <span className="font-mono font-bold">{(val || 0).toFixed(0)} лв</span>
                  {sub && <p className="text-[9px] text-muted-foreground">{sub}</p>}
                </div>
              </div>
            ))}
            <div className="flex justify-between p-1.5 rounded bg-muted/20 font-bold">
              <span>{t("pnl.totalExpense")}</span>
              <span className="font-mono">{expense.total_expense.toFixed(0)} лв</span>
            </div>
          </div>

          {/* Revenue breakdown */}
          <div className="space-y-1.5">
            <p className="font-medium text-muted-foreground uppercase text-[10px]">{t("pnl.revenueBreakdown")}</p>
            {[
              { label: t("pnl.invoiced"), val: revenue.invoiced_total },
              { label: t("pnl.paid"), val: revenue.paid_total },
              { label: t("pnl.clientActs"), val: revenue.acts_total },
              { label: t("pnl.additionalOffered"), val: revenue.additional_offered },
            ].map(({ label, val }) => (
              <div key={label} className="flex items-center justify-between p-1.5 rounded bg-muted/10">
                <span>{label}</span>
                <span className="font-mono font-bold">{(val || 0).toFixed(0)} лв</span>
              </div>
            ))}
            <div className="flex justify-between p-1.5 rounded bg-muted/20 font-bold">
              <span>{t("pnl.totalRevenue")}</span>
              <span className="font-mono text-blue-400">{revenue.total_revenue.toFixed(0)} лв</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
