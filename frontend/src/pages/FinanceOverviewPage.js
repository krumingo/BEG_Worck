import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import {
  Landmark,
  FileText,
  CreditCard,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  ArrowRight,
  Plus,
  Wallet,
  Building2,
} from "lucide-react";

export default function FinanceOverviewPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);

  const canManage = ["Admin", "Owner", "Accountant"].includes(user?.role);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, accountsRes] = await Promise.all([
        API.get("/finance/stats"),
        API.get("/finance/accounts"),
      ]);
      setStats(statsRes.data);
      setAccounts(accountsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1400px]" data-testid="finance-overview-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-3">
            <Landmark className="w-6 h-6 text-primary" />
            {t("finance.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{t("finance.subtitle")}</p>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => navigate("/finance/invoices/new")} data-testid="new-invoice-btn">
              <Plus className="w-4 h-4 mr-2" /> {t("finance.newInvoice")}
            </Button>
            <Button onClick={() => navigate("/finance/payments/new")} data-testid="new-payment-btn">
              <Plus className="w-4 h-4 mr-2" /> {t("finance.newPayment")}
            </Button>
          </div>
        )}
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {/* Receivables */}
        <div 
          className="rounded-xl border border-border bg-card p-5 cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => navigate("/finance/invoices?direction=Issued")}
          data-testid="receivables-card"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center">
              <TrendingUp className="w-5 h-5 text-emerald-400" />
            </div>
            <ArrowRight className="w-4 h-4 text-muted-foreground" />
          </div>
          <p className="text-sm text-muted-foreground">{t("finance.receivables")}</p>
          <p className="text-2xl font-bold text-foreground">{formatCurrency(stats?.receivables_total)}</p>
          <p className="text-xs text-muted-foreground mt-1">{t("finance.openInvoices", { count: stats?.receivables_count || 0 })}</p>
          {stats?.receivables_overdue > 0 && (
            <p className="text-xs text-red-400 mt-1 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              {formatCurrency(stats?.receivables_overdue)} {t("finance.overdue").toLowerCase()}
            </p>
          )}
        </div>

        {/* Payables */}
        <div 
          className="rounded-xl border border-border bg-card p-5 cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => navigate("/finance/invoices?direction=Received")}
          data-testid="payables-card"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="w-10 h-10 rounded-lg bg-red-500/20 flex items-center justify-center">
              <TrendingDown className="w-5 h-5 text-red-400" />
            </div>
            <ArrowRight className="w-4 h-4 text-muted-foreground" />
          </div>
          <p className="text-sm text-muted-foreground">{t("finance.payables")}</p>
          <p className="text-2xl font-bold text-foreground">{formatCurrency(stats?.payables_total)}</p>
          <p className="text-xs text-muted-foreground mt-1">{t("finance.billsToPay", { count: stats?.payables_count || 0 })}</p>
          {stats?.payables_overdue > 0 && (
            <p className="text-xs text-red-400 mt-1 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              {formatCurrency(stats?.payables_overdue)} {t("finance.overdue").toLowerCase()}
            </p>
          )}
        </div>

        {/* Cash Balance */}
        <div 
          className="rounded-xl border border-border bg-card p-5 cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => navigate("/finance/accounts")}
          data-testid="cash-card"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="w-10 h-10 rounded-lg bg-amber-500/20 flex items-center justify-center">
              <Wallet className="w-5 h-5 text-amber-400" />
            </div>
            <ArrowRight className="w-4 h-4 text-muted-foreground" />
          </div>
          <p className="text-sm text-muted-foreground">{t("finance.cashBalance")}</p>
          <p className="text-2xl font-bold text-foreground">{formatCurrency(stats?.cash_balance)}</p>
          <p className="text-xs text-muted-foreground mt-1">{t("finance.allCashAccounts")}</p>
        </div>

        {/* Bank Balance */}
        <div 
          className="rounded-xl border border-border bg-card p-5 cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => navigate("/finance/accounts")}
          data-testid="bank-card"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
              <Building2 className="w-5 h-5 text-blue-400" />
            </div>
            <ArrowRight className="w-4 h-4 text-muted-foreground" />
          </div>
          <p className="text-sm text-muted-foreground">{t("finance.bankBalance")}</p>
          <p className="text-2xl font-bold text-foreground">{formatCurrency(stats?.bank_balance)}</p>
          <p className="text-xs text-muted-foreground mt-1">{t("finance.allBankAccounts")}</p>
        </div>
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Accounts */}
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="accounts-section">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Wallet className="w-4 h-4 text-primary" />
              {t("finance.financialAccounts")}
            </h2>
            <Button variant="ghost" size="sm" onClick={() => navigate("/finance/accounts")}>
              {t("common.viewAll")} <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
          <div className="p-4 space-y-3">
            {accounts.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">{t("finance.noAccounts")}</p>
            ) : (
              accounts.slice(0, 4).map((acc) => (
                <div key={acc.id} className="flex items-center justify-between p-3 rounded-lg bg-muted/30">
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                      acc.type === "Cash" ? "bg-amber-500/20" : "bg-blue-500/20"
                    }`}>
                      {acc.type === "Cash" ? (
                        <Wallet className="w-4 h-4 text-amber-400" />
                      ) : (
                        <Building2 className="w-4 h-4 text-blue-400" />
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-foreground">{acc.name}</p>
                      <p className="text-xs text-muted-foreground">{t(`finance.accountType.${acc.type.toLowerCase()}`)}</p>
                    </div>
                  </div>
                  <p className="font-mono text-sm font-medium text-foreground">
                    {formatCurrency(acc.current_balance, acc.currency)}
                  </p>
                </div>
              ))
            )}
            {canManage && accounts.length === 0 && (
              <Button variant="outline" className="w-full" onClick={() => navigate("/finance/accounts")}>
                <Plus className="w-4 h-4 mr-2" /> {t("finance.newAccount")}
              </Button>
            )}
          </div>
        </div>

        {/* Invoices */}
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="invoices-section">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" />
              {t("finance.invoices")}
            </h2>
            <Button variant="ghost" size="sm" onClick={() => navigate("/finance/invoices")}>
              {t("common.viewAll")} <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
          <div className="p-4 space-y-3">
            <div 
              className="p-3 rounded-lg bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors"
              onClick={() => navigate("/finance/invoices?direction=Issued")}
            >
              <p className="text-sm text-muted-foreground">{t("finance.issuedSales")}</p>
              <p className="text-lg font-bold text-foreground">{stats?.receivables_count || 0} {t("common.open").toLowerCase()}</p>
            </div>
            <div 
              className="p-3 rounded-lg bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors"
              onClick={() => navigate("/finance/invoices?direction=Received")}
            >
              <p className="text-sm text-muted-foreground">{t("finance.receivedBills")}</p>
              <p className="text-lg font-bold text-foreground">{stats?.payables_count || 0} {t("common.open").toLowerCase()}</p>
            </div>
            {canManage && (
              <Button variant="outline" className="w-full" onClick={() => navigate("/finance/invoices/new")}>
                <Plus className="w-4 h-4 mr-2" /> {t("finance.newInvoice")}
              </Button>
            )}
          </div>
        </div>

        {/* Payments */}
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="payments-section">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <CreditCard className="w-4 h-4 text-primary" />
              {t("finance.payments")}
            </h2>
            <Button variant="ghost" size="sm" onClick={() => navigate("/finance/payments")}>
              {t("common.viewAll")} <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
          <div className="p-4 space-y-3">
            <div 
              className="p-3 rounded-lg bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors"
              onClick={() => navigate("/finance/payments?direction=Inflow")}
            >
              <p className="text-sm text-muted-foreground">{t("finance.moneyIn")}</p>
              <p className="text-lg font-bold text-emerald-400">{t("finance.inflows")}</p>
            </div>
            <div 
              className="p-3 rounded-lg bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors"
              onClick={() => navigate("/finance/payments?direction=Outflow")}
            >
              <p className="text-sm text-muted-foreground">{t("finance.moneyOut")}</p>
              <p className="text-lg font-bold text-red-400">{t("finance.outflows")}</p>
            </div>
            {canManage && (
              <Button variant="outline" className="w-full" onClick={() => navigate("/finance/payments/new")}>
                <Plus className="w-4 h-4 mr-2" /> {t("finance.recordPayment")}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
