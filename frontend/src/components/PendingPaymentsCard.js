import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { FileText, AlertTriangle, ArrowUpRight } from "lucide-react";

export default function PendingPaymentsCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);

  useEffect(() => {
    API.get("/dashboard/pending-payments").then(r => setData(r.data)).catch(() => {});
  }, []);

  if (!data || data.count === 0) return null;

  return (
    <div className="rounded-xl border border-border bg-card p-5 mb-6" data-testid="pending-payments-card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-amber-400" />
          <h2 className="text-sm font-semibold">{t("pendingPay.title")}</h2>
          <Badge variant="outline" className="text-[10px] text-amber-400 bg-amber-500/10 border-amber-500/30">{data.count}</Badge>
        </div>
        <button onClick={() => navigate("/finance/invoices")} className="text-xs text-primary hover:underline flex items-center gap-1">
          {t("common.viewAll")} <ArrowUpRight className="w-3 h-3" />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-3">
        <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-2 text-center">
          <p className="text-lg font-bold font-mono text-amber-400">{data.total_unpaid.toFixed(0)}<span className="text-xs text-muted-foreground"> EUR</span></p>
          <p className="text-[8px] text-amber-400/70">{t("pendingPay.unpaid")}</p>
        </div>
        {data.total_overdue > 0 && (
          <div className="rounded-lg bg-red-500/5 border border-red-500/20 p-2 text-center">
            <p className="text-lg font-bold font-mono text-red-400">{data.total_overdue.toFixed(0)}<span className="text-xs text-muted-foreground"> EUR</span></p>
            <p className="text-[8px] text-red-400/70">{t("pendingPay.overdue")}</p>
          </div>
        )}
        <div className="rounded-lg bg-card border border-border p-2 text-center">
          <p className="text-lg font-bold font-mono">{data.count}</p>
          <p className="text-[8px] text-muted-foreground">{t("pendingPay.invoices")}</p>
        </div>
      </div>

      <div className="space-y-1 max-h-[180px] overflow-y-auto">
        {data.items.map(inv => (
          <div key={inv.id} className={`flex items-center justify-between px-3 py-1.5 rounded-lg text-xs ${inv.is_overdue ? "bg-red-500/5 border border-red-500/20" : "hover:bg-muted/20"}`}>
            <div className="flex items-center gap-2 min-w-0">
              {inv.is_overdue && <AlertTriangle className="w-3 h-3 text-red-400 flex-shrink-0" />}
              <span className="font-mono font-medium">{inv.invoice_no}</span>
              <span className="text-muted-foreground truncate">{inv.counterparty}</span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {inv.due_date && <span className="text-[10px] text-muted-foreground">{inv.due_date}</span>}
              <span className={`font-mono font-bold ${inv.is_overdue ? "text-red-400" : "text-amber-400"}`}>{inv.remaining.toFixed(0)} EUR</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
