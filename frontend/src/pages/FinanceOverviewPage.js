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
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-blue-500/20 text-blue-300 border border-blue-500/30 font-medium">с ДДС</span>
          </div>
          <p className="text-sm text-muted-foreground">За събиране <span className="text-muted-foreground/60">· от клиенти</span></p>
          <p className="text-xl font-bold text-foreground mt-1">{formatCurrency(stats?.receivables_total)}</p>
          <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-border">
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted/50 text-muted-foreground">без ДДС {formatCurrency(stats?.receivables_net)}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">ДДС {formatCurrency(stats?.receivables_vat)}</span>
          </div>
          <p className="text-xs text-muted-foreground mt-2">{stats?.receivables_count || 0} отворени</p>
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
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-blue-500/20 text-blue-300 border border-blue-500/30 font-medium">с ДДС</span>
          </div>
          <p className="text-sm text-muted-foreground">За плащане <span className="text-muted-foreground/60">· към доставчици</span></p>
          <p className="text-xl font-bold text-foreground mt-1">{formatCurrency(stats?.payables_total)}</p>
          <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-border">
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted/50 text-muted-foreground">без ДДС {formatCurrency(stats?.payables_net)}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">ДДС {formatCurrency(stats?.payables_vat)}</span>
          </div>
          <p className="text-xs text-muted-foreground mt-2">{stats?.payables_count || 0} сметки</p>
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
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-blue-500/20 text-blue-300 border border-blue-500/30 font-medium">с ДДС</span>
          </div>
          <p className="text-sm text-muted-foreground">Каса <span className="text-muted-foreground/60">· в брой</span></p>
          <p className="text-xl font-bold text-foreground mt-1">{formatCurrency(stats?.cash_balance)}</p>
          <p className="text-xs text-muted-foreground mt-2">налични пари</p>
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
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-blue-500/20 text-blue-300 border border-blue-500/30 font-medium">с ДДС</span>
          </div>
          <p className="text-sm text-muted-foreground">Банка <span className="text-muted-foreground/60">· по сметки</span></p>
          <p className="text-xl font-bold text-foreground mt-1">{formatCurrency(stats?.bank_balance)}</p>
          <p className="text-xs text-muted-foreground mt-2">{accounts.length} {accounts.length === 1 ? "сметка" : "сметки"}</p>
        </div>
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Accounts (nav tile — balances live in the Bank/Cash cards above) */}
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="accounts-section">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <CreditCard className="w-4 h-4 text-primary" />
              Сметки
            </h2>
            <Button variant="ghost" size="sm" onClick={() => navigate("/finance/accounts")}>
              {t("common.viewAll")} <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
          <div className="p-4 space-y-3">
            <div
              className="p-3 rounded-lg bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors"
              onClick={() => navigate("/finance/accounts")}
            >
              <p className="text-sm text-muted-foreground">Управление на Каса / Банка</p>
              <p className="text-lg font-bold text-foreground">{accounts.length} {accounts.length === 1 ? "сметка" : "сметки"}</p>
            </div>
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
