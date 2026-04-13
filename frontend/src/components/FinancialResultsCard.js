/**
 * FinancialResultsCard — Cash / Operating / Fully Loaded results per project.
 * Reads from GET /projects/{id}/financial-results
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Wallet, TrendingUp, Target, AlertTriangle, ChevronDown, ChevronRight,
  Loader2, DollarSign, Users, Package, Building2, Shield,
} from "lucide-react";

function fmt(n) { return n == null ? "—" : n.toLocaleString("bg-BG", { maximumFractionDigits: 0 }); }

const CARD_CFG = {
  cash: { icon: Wallet, color: "text-blue-400", border: "border-blue-500/20", bg: "bg-blue-500/5" },
  operating: { icon: TrendingUp, color: "text-emerald-400", border: "border-emerald-500/20", bg: "bg-emerald-500/5" },
  loaded: { icon: Target, color: "text-purple-400", border: "border-purple-500/20", bg: "bg-purple-500/5" },
};

export default function FinancialResultsCard({ projectId }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showBreakdown, setShowBreakdown] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/financial-results`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const { cash, operating, fully_loaded, labor, warnings } = data;
  const resultColor = (val) => val > 0 ? "text-emerald-400" : val < 0 ? "text-red-400" : "text-muted-foreground";
  const lb = labor || {};

  return (
    <div className="space-y-4" data-testid="financial-results-card">
      {/* 3 Result Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Cash */}
        <div className={`rounded-xl border p-4 ${CARD_CFG.cash.border} ${CARD_CFG.cash.bg}`}>
          <div className="flex items-center gap-2 mb-3">
            <Wallet className={`w-4 h-4 ${CARD_CFG.cash.color}`} />
            <span className="text-xs font-semibold">{t("finResults.cash")}</span>
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between"><span className="text-muted-foreground">{t("finResults.invoiced")}</span><span className="font-mono">{fmt(cash.invoices?.invoiced)}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">{t("finResults.cashIn")}</span><span className="font-mono text-emerald-400">+{fmt(cash.cash_in)}</span></div>
            {cash.invoices?.unpaid > 0 && <div className="flex justify-between"><span className="text-amber-400">{t("finResults.unpaid")}</span><span className="font-mono text-amber-400">{fmt(cash.invoices.unpaid)}</span></div>}
            {cash.invoices?.overdue > 0 && <div className="flex justify-between"><span className="text-red-400">{t("finResults.overdue")}</span><span className="font-mono text-red-400">{fmt(cash.invoices.overdue)}</span></div>}
            <div className="flex justify-between"><span className="text-muted-foreground">{t("finResults.cashOut")}</span><span className="font-mono text-red-400">-{fmt(cash.cash_out)}</span></div>
            <div className="flex justify-between pt-1 border-t border-border">
              <span className="font-semibold">{t("finResults.balance")}</span>
              <span className={`font-mono font-bold text-base ${resultColor(cash.cash_balance)}`}>{fmt(cash.cash_balance)}</span>
            </div>
          </div>
          <p className="text-[9px] text-muted-foreground mt-2">{t("finResults.cashHint")}</p>
        </div>

        {/* Operating */}
        <div className={`rounded-xl border p-4 ${CARD_CFG.operating.border} ${CARD_CFG.operating.bg}`}>
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className={`w-4 h-4 ${CARD_CFG.operating.color}`} />
            <span className="text-xs font-semibold">{t("finResults.operating")}</span>
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between"><span className="text-muted-foreground">{t("finResults.revenue")}</span><span className="font-mono">{fmt(operating.earned_revenue)}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">{t("finResults.directCost")}</span><span className="font-mono">-{fmt(operating.operating_cost)}</span></div>
            <div className="flex justify-between pt-1 border-t border-border">
              <span className="font-semibold">{t("finResults.result")}</span>
              <span className={`font-mono font-bold text-base ${resultColor(operating.operating_result)}`}>{fmt(operating.operating_result)}</span>
            </div>
          </div>
          <div className="flex items-center justify-between mt-2">
            <p className="text-[9px] text-muted-foreground">{t("finResults.operatingHint")}</p>
            <Badge variant="outline" className={`text-[9px] ${resultColor(operating.operating_result)}`}>{operating.operating_margin_pct}%</Badge>
          </div>
        </div>

        {/* Fully Loaded */}
        <div className={`rounded-xl border p-4 ${CARD_CFG.loaded.border} ${CARD_CFG.loaded.bg}`}>
          <div className="flex items-center gap-2 mb-3">
            <Target className={`w-4 h-4 ${CARD_CFG.loaded.color}`} />
            <span className="text-xs font-semibold">{t("finResults.fullyLoaded")}</span>
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between"><span className="text-muted-foreground">{t("finResults.operatingShort")}</span><span className="font-mono">{fmt(operating.operating_result)}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">{t("finResults.burdens")}</span><span className="font-mono text-red-400">-{fmt(fully_loaded.insurance_burden + fully_loaded.overhead_allocation + fully_loaded.subcontractor_burden + fully_loaded.contract_burden)}</span></div>
            <div className="flex justify-between pt-1 border-t border-border">
              <span className="font-semibold">{t("finResults.realResult")}</span>
              <span className={`font-mono font-bold text-base ${resultColor(fully_loaded.fully_loaded_result)}`}>{fmt(fully_loaded.fully_loaded_result)}</span>
            </div>
          </div>
          <div className="flex items-center justify-between mt-2">
            <p className="text-[9px] text-muted-foreground">{t("finResults.loadedHint")}</p>
            <Badge variant="outline" className={`text-[9px] ${resultColor(fully_loaded.fully_loaded_result)}`}>{fully_loaded.fully_loaded_margin_pct}%</Badge>
          </div>
        </div>
      </div>

      {/* Warnings */}
      {warnings?.length > 0 && (
        <div className="space-y-1">
          {warnings.map((w, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-amber-400">
              <AlertTriangle className="w-3 h-3 flex-shrink-0" /> {w}
            </div>
          ))}
        </div>
      )}

      {/* Breakdown toggle */}
      <button onClick={() => setShowBreakdown(!showBreakdown)} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground">
        {showBreakdown ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {t("finResults.breakdown")}
      </button>

      {showBreakdown && (
        <div className="rounded-lg border border-border p-3 space-y-1.5 text-xs">
          {/* Labor: Reported vs Paid */}
          {(lb.reported_labor_value > 0 || lb.paid_labor_expense > 0) && (
            <div className="space-y-1 mb-2 pb-2 border-b border-border/50">
              <p className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider mb-1">{t("finResults.laborSection")}</p>
              {lb.reported_labor_value > 0 && (
                <div className="flex items-center justify-between py-1 px-2 rounded bg-muted/10">
                  <div className="flex items-center gap-2"><Users className={`w-3 h-3 text-blue-400`} /><span>{t("finResults.reportedLabor")}</span></div>
                  <span className="font-mono">{fmt(lb.reported_labor_value)}</span>
                </div>
              )}
              {lb.paid_labor_expense > 0 && (
                <div className="flex items-center justify-between py-1 px-2 rounded bg-emerald-500/10 border border-emerald-500/20">
                  <div className="flex items-center gap-2"><DollarSign className={`w-3 h-3 text-emerald-400`} /><span className="text-emerald-400 font-medium">{t("finResults.paidLabor")}</span></div>
                  <span className="font-mono text-emerald-400 font-bold">{fmt(lb.paid_labor_expense)}</span>
                </div>
              )}
              {lb.unpaid_approved_labor > 0 && (
                <div className="flex items-center justify-between py-1 px-2 rounded bg-amber-500/10">
                  <div className="flex items-center gap-2"><AlertTriangle className={`w-3 h-3 text-amber-400`} /><span className="text-amber-400">{t("finResults.unpaidLabor")}</span></div>
                  <span className="font-mono text-amber-400">{fmt(lb.unpaid_approved_labor)}</span>
                </div>
              )}
            </div>
          )}

          {[
            { icon: Shield, label: t("finResults.insurance"), val: fully_loaded.insurance_burden, color: "text-cyan-400" },
            { icon: Package, label: t("finResults.materials"), val: operating.materials, color: "text-orange-400" },
            { icon: Building2, label: t("finResults.subDirect"), val: operating.subcontractor_direct, color: "text-violet-400" },
            { icon: Building2, label: t("finResults.subBurden"), val: fully_loaded.subcontractor_burden, color: "text-violet-300" },
            { icon: Building2, label: t("finResults.contractBurden"), val: fully_loaded.contract_burden, color: "text-violet-300" },
          ].map(({ icon: Icon, label, val, color }) => val > 0 ? (
            <div key={label} className="flex items-center justify-between py-1 px-2 rounded bg-muted/10">
              <div className="flex items-center gap-2"><Icon className={`w-3 h-3 ${color}`} /><span>{label}</span></div>
              <span className="font-mono">{fmt(val)}</span>
            </div>
          ) : null)}

          {/* Overhead pools */}
          {Object.entries(fully_loaded.overhead_by_pool || {}).map(([pool, val]) => val > 0 ? (
            <div key={pool} className="flex items-center justify-between py-1 px-2 rounded bg-muted/10">
              <span className="text-muted-foreground">{t("finResults.oh")} {pool}</span>
              <span className="font-mono">{fmt(val)}</span>
            </div>
          ) : null)}

          <div className="flex items-center justify-between py-1 px-2 rounded bg-muted/20 font-bold border-t border-border">
            <span>{t("finResults.totalCost")}</span>
            <span className="font-mono">{fmt(fully_loaded.fully_loaded_cost)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
