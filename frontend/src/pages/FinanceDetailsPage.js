import { useState, useEffect, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import API from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import {
  Wallet,
  Loader2,
  Download,
  Filter,
  TrendingUp,
  TrendingDown,
  Building2,
  Users,
  FolderKanban,
  Warehouse,
  ChevronLeft,
  ChevronRight,
  FileText,
  CalendarDays,
} from "lucide-react";
import { toast } from "sonner";

const EXPENSE_COLORS = {
  invoices: "#ef4444",
  cash: "#f97316",
  overhead: "#eab308",
  payroll: "#8b5cf6",
  bonus: "#ec4899",
};

const EXPENSE_LABELS = {
  invoices: "Фактури",
  cash: "Каса",
  overhead: "Режийни",
  payroll: "Заплати",
  bonus: "Бонуси",
};

const PRESETS = [
  { value: "this_month", label: "Този месец" },
  { value: "last_month", label: "Миналия месец" },
  { value: "last_3_months", label: "Последни 3 месеца" },
  { value: "last_6_months", label: "Последни 6 месеца" },
  { value: "last_12_months", label: "Последни 12 месеца" },
  { value: "this_year", label: "Тази година" },
  { value: "custom", label: "Персонализиран" },
];

const PERIOD_OPTIONS = [
  { value: "1", label: "1 месец" },
  { value: "3", label: "3 месеца" },
  { value: "6", label: "6 месеца" },
  { value: "12", label: "12 месеца" },
];

const MONTH_NAMES_BG = [
  "Януари", "Февруари", "Март", "Април", "Май", "Юни",
  "Юли", "Август", "Септември", "Октомври", "Ноември", "Декември"
];

const TRANSACTION_TYPES = [
  { value: "all", label: "Всички" },
  { value: "invoice", label: "Фактури" },
  { value: "cash", label: "Каса" },
  { value: "overhead", label: "Режийни" },
  { value: "payroll", label: "Заплати" },
  { value: "bonus", label: "Бонуси" },
];

export default function FinanceDetailsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  
  // Period state (1, 3, 6, 12 months)
  const [period, setPeriod] = useState(searchParams.get("months") || "3");
  
  // Filter state (for presets - legacy)
  const [preset, setPreset] = useState(searchParams.get("preset") || "last_3_months");
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") || "");
  const [dateTo, setDateTo] = useState(searchParams.get("date_to") || "");
  const [transactionType, setTransactionType] = useState("all");
  const [direction, setDirection] = useState("all");
  
  // Data state
  const [summary, setSummary] = useState(null);
  const [byCounterparty, setByCounterparty] = useState(null);
  const [byProject, setByProject] = useState(null);
  const [transactions, setTransactions] = useState(null);
  const [topCounterparties, setTopCounterparties] = useState(null);
  const [monthlySeries, setMonthlySeries] = useState(null);
  
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("monthly");
  
  // Pagination for transactions
  const [txnPage, setTxnPage] = useState(1);
  const [cpPage, setCpPage] = useState(1);
  const [projPage, setProjPage] = useState(1);

  // Build query params
  const buildParams = useCallback(() => {
    const params = new URLSearchParams();
    if (preset !== "custom") {
      params.append("preset", preset);
    } else {
      if (dateFrom) params.append("date_from", dateFrom);
      if (dateTo) params.append("date_to", dateTo);
    }
    return params.toString();
  }, [preset, dateFrom, dateTo]);

  // Fetch monthly series data
  useEffect(() => {
    const fetchMonthlySeries = async () => {
      try {
        const res = await API.get(`/reports/company-finance-series?months=${period}`);
        setMonthlySeries(res.data);
      } catch (err) {
        console.error("Failed to fetch monthly series:", err);
      }
    };
    fetchMonthlySeries();
  }, [period]);

  // Compute totals for monthly series
  const monthlyTotals = useMemo(() => {
    if (!monthlySeries?.months) return null;
    
    const totals = {
      income: 0,
      expenses: 0,
      net: 0,
      breakdown: {
        income_invoices: 0,
        income_cash: 0,
        expenses_invoices: 0,
        expenses_cash: 0,
        expenses_overhead: 0,
        expenses_payroll: 0,
        expenses_bonus: 0,
      }
    };
    
    monthlySeries.months.forEach(m => {
      totals.income += m.income_total || 0;
      totals.expenses += m.expenses_total || 0;
      totals.net += m.net || 0;
      if (m.breakdown) {
        Object.keys(totals.breakdown).forEach(key => {
          totals.breakdown[key] += m.breakdown[key] || 0;
        });
      }
    });
    
    return totals;
  }, [monthlySeries]);

  // Format month name
  const formatMonthName = useCallback((year, month) => {
    return `${MONTH_NAMES_BG[month - 1]} ${year}`;
  }, []);

  // Fetch summary data
  useEffect(() => {
    const fetchSummary = async () => {
      setLoading(true);
      try {
        const params = buildParams();
        const [summaryRes, topRes] = await Promise.all([
          API.get(`/reports/finance-details/summary?${params}`),
          API.get(`/reports/finance-details/top-counterparties?${params}&direction=expense`),
        ]);
        setSummary(summaryRes.data);
        setTopCounterparties(topRes.data.items);
      } catch (err) {
        console.error("Failed to fetch summary:", err);
        toast.error(t("common.error"));
      } finally {
        setLoading(false);
      }
    };
    fetchSummary();
  }, [preset, dateFrom, dateTo, t, buildParams]);

  // Fetch by counterparty data
  useEffect(() => {
    if (activeTab !== "counterparty") return;
    
    const fetchByCounterparty = async () => {
      try {
        const params = buildParams();
        const res = await API.get(`/reports/finance-details/by-counterparty?${params}&page=${cpPage}`);
        setByCounterparty(res.data);
      } catch (err) {
        console.error("Failed to fetch by counterparty:", err);
      }
    };
    fetchByCounterparty();
  }, [activeTab, cpPage, buildParams]);

  // Fetch by project data
  useEffect(() => {
    if (activeTab !== "project") return;
    
    const fetchByProject = async () => {
      try {
        const params = buildParams();
        const res = await API.get(`/reports/finance-details/by-project?${params}&page=${projPage}`);
        setByProject(res.data);
      } catch (err) {
        console.error("Failed to fetch by project:", err);
      }
    };
    fetchByProject();
  }, [activeTab, projPage, buildParams]);

  // Fetch transactions
  useEffect(() => {
    if (activeTab !== "transactions") return;
    
    const fetchTransactions = async () => {
      try {
        const params = new URLSearchParams(buildParams());
        params.append("page", txnPage);
        if (transactionType && transactionType !== "all") params.append("transaction_type", transactionType);
        if (direction && direction !== "all") params.append("direction", direction);
        
        const res = await API.get(`/reports/finance-details/transactions?${params.toString()}`);
        setTransactions(res.data);
      } catch (err) {
        console.error("Failed to fetch transactions:", err);
      }
    };
    fetchTransactions();
  }, [activeTab, txnPage, transactionType, direction, buildParams]);

  // Export handler
  const handleExport = useCallback(async () => {
    toast.info("Експортиране...");
    try {
      const params = buildParams();
      const res = await API.get(`/reports/finance-details/transactions?${params}&page=1&page_size=10000`);
      
      // Convert to CSV
      const items = res.data.items;
      const headers = ["Дата", "Тип", "Посока", "Сума", "Описание"];
      const rows = items.map(item => [
        item.date,
        item.type,
        item.direction === "income" ? "Приход" : "Разход",
        item.amount,
        item.description,
      ]);
      
      const csvContent = [headers.join(","), ...rows.map(r => r.map(c => `"${c}"`).join(","))].join("\n");
      
      const blob = new Blob(["\ufeff" + csvContent], { type: "text/csv;charset=utf-8;" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `finance_transactions_${new Date().toISOString().split("T")[0]}.csv`;
      link.click();
      window.URL.revokeObjectURL(url);
      
      toast.success("Експортът е готов!");
    } catch (err) {
      toast.error(t("common.error"));
    }
  }, [buildParams, t]);

  // Memoized pie chart data
  const breakdownPieData = useMemo(() => {
    if (!summary) return [];
    
    const bd = summary.breakdown;
    return [
      { name: "Фактури", value: bd.expenses_invoices, color: EXPENSE_COLORS.invoices },
      { name: "Каса", value: bd.expenses_cash, color: EXPENSE_COLORS.cash },
      { name: "Режийни", value: bd.expenses_overhead, color: EXPENSE_COLORS.overhead },
      { name: "Заплати", value: bd.expenses_payroll, color: EXPENSE_COLORS.payroll },
      { name: "Бонуси", value: bd.expenses_bonus, color: EXPENSE_COLORS.bonus },
    ].filter(d => d.value > 0);
  }, [summary]);

  if (loading && !summary) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6" data-testid="finance-details-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
            <Wallet className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">
              {t("financeDetails.title") || "Финансови детайли"}
            </h1>
            <p className="text-sm text-muted-foreground">
              {summary?.period?.date_from} - {summary?.period?.date_to}
            </p>
          </div>
        </div>
        <Button onClick={handleExport} variant="outline" data-testid="export-csv-btn">
          <Download className="w-4 h-4 mr-2" />
          {t("clients.export")} CSV
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap items-end gap-4">
            {/* Period Selector (1/3/6/12 months) */}
            <div className="space-y-1">
              <Label className="text-xs flex items-center gap-1">
                <CalendarDays className="w-3 h-3" />
                Период (месеци)
              </Label>
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger className="w-[140px]" data-testid="period-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERIOD_OPTIONS.map(p => (
                    <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="border-l border-border h-8 mx-2" />
            
            <div className="space-y-1">
              <Label className="text-xs">{t("financeDetails.period") || "Филтър период"}</Label>
              <Select value={preset} onValueChange={setPreset}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRESETS.map(p => (
                    <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            {preset === "custom" && (
              <>
                <div className="space-y-1">
                  <Label className="text-xs">{t("common.from")}</Label>
                  <Input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => setDateFrom(e.target.value)}
                    className="w-[150px]"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">{t("common.to")}</Label>
                  <Input
                    type="date"
                    value={dateTo}
                    onChange={(e) => setDateTo(e.target.value)}
                    className="w-[150px]"
                  />
                </div>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card className="bg-green-500/10 border-green-500/30">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">{t("dashboard.totalIncome")}</p>
                  <p className="text-xl font-bold text-green-500">{summary.totals.income.toFixed(2)} лв.</p>
                </div>
                <TrendingUp className="w-6 h-6 text-green-500/50" />
              </div>
            </CardContent>
          </Card>
          <Card className="bg-red-500/10 border-red-500/30">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">{t("dashboard.totalExpenses")}</p>
                  <p className="text-xl font-bold text-red-500">{summary.totals.expenses.toFixed(2)} лв.</p>
                </div>
                <TrendingDown className="w-6 h-6 text-red-500/50" />
              </div>
            </CardContent>
          </Card>
          <Card className={`${summary.totals.net >= 0 ? "bg-blue-500/10 border-blue-500/30" : "bg-amber-500/10 border-amber-500/30"}`}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">{t("dashboard.netBalance")}</p>
                  <p className={`text-xl font-bold ${summary.totals.net >= 0 ? "text-blue-500" : "text-amber-500"}`}>
                    {summary.totals.net >= 0 ? "+" : ""}{summary.totals.net.toFixed(2)} лв.
                  </p>
                </div>
                <Wallet className="w-6 h-6 text-blue-500/50" />
              </div>
            </CardContent>
          </Card>
          <Card className="bg-purple-500/10 border-purple-500/30">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">{t("financeDetails.avgWeeklyExpense") || "Среден разход/седм."}</p>
                  <p className="text-xl font-bold text-purple-500">{summary.kpis.avg_weekly_expenses.toFixed(2)} лв.</p>
                </div>
                <FileText className="w-6 h-6 text-purple-500/50" />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-6">
          <TabsTrigger value="monthly" data-testid="tab-monthly">
            <CalendarDays className="w-4 h-4 mr-1" />
            По месеци
          </TabsTrigger>
          <TabsTrigger value="overview" data-testid="tab-overview">
            {t("financeDetails.overview") || "Обобщение"}
          </TabsTrigger>
          <TabsTrigger value="breakdown" data-testid="tab-breakdown">
            {t("financeDetails.breakdown") || "Разбивка"}
          </TabsTrigger>
          <TabsTrigger value="counterparty" data-testid="tab-counterparty">
            {t("financeDetails.byCounterparty") || "По контрагент"}
          </TabsTrigger>
          <TabsTrigger value="project" data-testid="tab-project">
            {t("financeDetails.byProject") || "По проект"}
          </TabsTrigger>
          <TabsTrigger value="transactions" data-testid="tab-transactions">
            {t("financeDetails.transactions") || "Транзакции"}
          </TabsTrigger>
        </TabsList>

        {/* Monthly Series Tab */}
        <TabsContent value="monthly" className="space-y-6 mt-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <CalendarDays className="w-4 h-4" />
                Месечна разбивка ({period} {parseInt(period) === 1 ? "месец" : "месеца"})
              </CardTitle>
            </CardHeader>
            <CardContent>
              {monthlySeries?.months?.length > 0 ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-border">
                        <TableHead className="font-medium">Месец</TableHead>
                        <TableHead className="text-right font-medium text-green-500">Приходи</TableHead>
                        <TableHead className="text-right font-medium text-red-500">Разходи</TableHead>
                        <TableHead className="text-right font-medium text-blue-500">Нетно</TableHead>
                        <TableHead className="text-right font-medium text-muted-foreground">Фактури (П)</TableHead>
                        <TableHead className="text-right font-medium text-muted-foreground">Каса (П)</TableHead>
                        <TableHead className="text-right font-medium text-muted-foreground">Фактури (Р)</TableHead>
                        <TableHead className="text-right font-medium text-muted-foreground">Режийни</TableHead>
                        <TableHead className="text-right font-medium text-muted-foreground">Заплати</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {monthlySeries.months.map((m, idx) => (
                        <TableRow key={`${m.year}-${m.month}`} className="border-border hover:bg-muted/30">
                          <TableCell className="font-medium">
                            {formatMonthName(m.year, m.month)}
                          </TableCell>
                          <TableCell className="text-right text-green-500">
                            {(m.income_total || 0).toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} лв.
                          </TableCell>
                          <TableCell className="text-right text-red-500">
                            {(m.expenses_total || 0).toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} лв.
                          </TableCell>
                          <TableCell className={`text-right font-medium ${(m.net || 0) >= 0 ? "text-blue-500" : "text-amber-500"}`}>
                            {(m.net || 0) >= 0 ? "+" : ""}{(m.net || 0).toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} лв.
                          </TableCell>
                          <TableCell className="text-right text-muted-foreground text-sm">
                            {(m.breakdown?.income_invoices || 0).toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                          <TableCell className="text-right text-muted-foreground text-sm">
                            {(m.breakdown?.income_cash || 0).toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                          <TableCell className="text-right text-muted-foreground text-sm">
                            {(m.breakdown?.expenses_invoices || 0).toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                          <TableCell className="text-right text-muted-foreground text-sm">
                            {(m.breakdown?.expenses_overhead || 0).toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                          <TableCell className="text-right text-muted-foreground text-sm">
                            {(m.breakdown?.expenses_payroll || 0).toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                        </TableRow>
                      ))}
                      
                      {/* TOTALS Row */}
                      {monthlyTotals && (
                        <TableRow className="border-t-2 border-border bg-muted/50 sticky bottom-0">
                          <TableCell className="font-bold text-foreground">
                            ОБЩО
                          </TableCell>
                          <TableCell className="text-right font-bold text-green-400">
                            {monthlyTotals.income.toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} лв.
                          </TableCell>
                          <TableCell className="text-right font-bold text-red-400">
                            {monthlyTotals.expenses.toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} лв.
                          </TableCell>
                          <TableCell className={`text-right font-bold ${monthlyTotals.net >= 0 ? "text-blue-400" : "text-amber-400"}`}>
                            {monthlyTotals.net >= 0 ? "+" : ""}{monthlyTotals.net.toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} лв.
                          </TableCell>
                          <TableCell className="text-right font-semibold text-muted-foreground text-sm">
                            {monthlyTotals.breakdown.income_invoices.toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                          <TableCell className="text-right font-semibold text-muted-foreground text-sm">
                            {monthlyTotals.breakdown.income_cash.toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                          <TableCell className="text-right font-semibold text-muted-foreground text-sm">
                            {monthlyTotals.breakdown.expenses_invoices.toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                          <TableCell className="text-right font-semibold text-muted-foreground text-sm">
                            {monthlyTotals.breakdown.expenses_overhead.toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                          <TableCell className="text-right font-semibold text-muted-foreground text-sm">
                            {monthlyTotals.breakdown.expenses_payroll.toLocaleString("bg-BG", { minimumFractionDigits: 2 })}
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-8">{t("common.noData") || "Няма данни"}</p>
              )}
            </CardContent>
          </Card>
          
          {/* Monthly Chart */}
          {monthlySeries?.months?.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Приходи vs Разходи по месеци</CardTitle>
              </CardHeader>
              <CardContent className="h-[300px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={monthlySeries.months.map(m => ({
                    name: MONTH_NAMES_BG[m.month - 1]?.substring(0, 3) || m.month,
                    income: m.income_total || 0,
                    expenses: m.expenses_total || 0,
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                    <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                    <Tooltip 
                      contentStyle={{ 
                        backgroundColor: "hsl(var(--popover))", 
                        border: "1px solid hsl(var(--border))",
                        borderRadius: "8px"
                      }}
                      formatter={(value) => [`${value.toLocaleString("bg-BG", { minimumFractionDigits: 2 })} лв.`]}
                    />
                    <Legend />
                    <Bar dataKey="income" name="Приходи" fill="#22c55e" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="expenses" name="Разходи" fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-6 mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* KPIs */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">KPI</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Брой фактури (приходи):</span>
                  <span className="font-medium">{summary?.counts?.income_invoice_count || 0}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Брой фактури (разходи):</span>
                  <span className="font-medium">{summary?.counts?.expenses_invoice_count || 0}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Седмици в периода:</span>
                  <span className="font-medium">{summary?.kpis?.weeks_in_period || 0}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Среден приход/седмица:</span>
                  <span className="font-medium text-green-500">{summary?.kpis?.avg_weekly_income?.toFixed(2) || 0} лв.</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Среден разход/седмица:</span>
                  <span className="font-medium text-red-500">{summary?.kpis?.avg_weekly_expenses?.toFixed(2) || 0} лв.</span>
                </div>
              </CardContent>
            </Card>

            {/* Top Counterparties */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">{t("financeDetails.topCounterparties") || "Топ 10 контрагенти (разходи)"}</CardTitle>
              </CardHeader>
              <CardContent>
                {topCounterparties?.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("common.noData")}</p>
                ) : (
                  <div className="space-y-2">
                    {topCounterparties?.slice(0, 10).map((cp, idx) => (
                      <div key={cp.counterparty_id} className="flex justify-between items-center text-sm">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground w-4">{idx + 1}.</span>
                          <span className="truncate max-w-[200px]">{cp.counterparty_name}</span>
                        </div>
                        <span className="font-medium text-red-400">{cp.total.toFixed(2)} лв.</span>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Breakdown Tab */}
        <TabsContent value="breakdown" className="space-y-6 mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Pie Chart */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">{t("dashboard.expenseBreakdown")}</CardTitle>
              </CardHeader>
              <CardContent>
                {breakdownPieData.length === 0 ? (
                  <div className="flex items-center justify-center h-[250px] text-muted-foreground">
                    {t("common.noData")}
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={250}>
                    <PieChart>
                      <Pie
                        data={breakdownPieData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={90}
                        paddingAngle={2}
                        dataKey="value"
                        label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                        labelLine={false}
                      >
                        {breakdownPieData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#1f2937",
                          border: "1px solid #374151",
                          borderRadius: "8px",
                        }}
                        formatter={(value) => [`${value.toFixed(2)} лв.`]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Breakdown Table */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">{t("financeDetails.shareByType") || "Дял по тип"}</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("common.type")}</TableHead>
                      <TableHead className="text-right">{t("common.amount")}</TableHead>
                      <TableHead className="text-right">{t("financeDetails.share") || "Дял"}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {summary && (
                      <>
                        <TableRow>
                          <TableCell className="flex items-center gap-2">
                            <div className="w-3 h-3 rounded" style={{ backgroundColor: EXPENSE_COLORS.invoices }} />
                            Фактури
                          </TableCell>
                          <TableCell className="text-right">{summary.breakdown.expenses_invoices.toFixed(2)} лв.</TableCell>
                          <TableCell className="text-right">{summary.kpis.invoice_share}%</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="flex items-center gap-2">
                            <div className="w-3 h-3 rounded" style={{ backgroundColor: EXPENSE_COLORS.cash }} />
                            Каса
                          </TableCell>
                          <TableCell className="text-right">{summary.breakdown.expenses_cash.toFixed(2)} лв.</TableCell>
                          <TableCell className="text-right">{summary.kpis.cash_share}%</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="flex items-center gap-2">
                            <div className="w-3 h-3 rounded" style={{ backgroundColor: EXPENSE_COLORS.overhead }} />
                            Режийни
                          </TableCell>
                          <TableCell className="text-right">{summary.breakdown.expenses_overhead.toFixed(2)} лв.</TableCell>
                          <TableCell className="text-right">{summary.kpis.overhead_share}%</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="flex items-center gap-2">
                            <div className="w-3 h-3 rounded" style={{ backgroundColor: EXPENSE_COLORS.payroll }} />
                            Заплати
                          </TableCell>
                          <TableCell className="text-right">{summary.breakdown.expenses_payroll.toFixed(2)} лв.</TableCell>
                          <TableCell className="text-right">{summary.kpis.payroll_share}%</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="flex items-center gap-2">
                            <div className="w-3 h-3 rounded" style={{ backgroundColor: EXPENSE_COLORS.bonus }} />
                            Бонуси
                          </TableCell>
                          <TableCell className="text-right">{summary.breakdown.expenses_bonus.toFixed(2)} лв.</TableCell>
                          <TableCell className="text-right">{summary.kpis.bonus_share}%</TableCell>
                        </TableRow>
                      </>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* By Counterparty Tab */}
        <TabsContent value="counterparty" className="mt-6">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("data.counterparties")}</TableHead>
                    <TableHead>{t("common.type")}</TableHead>
                    <TableHead className="text-right text-green-500">{t("dashboard.income")}</TableHead>
                    <TableHead className="text-right text-red-500">{t("dashboard.expenses")}</TableHead>
                    <TableHead className="text-right">{t("common.total")}</TableHead>
                    <TableHead className="text-right">{t("data.invoiceCount")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {byCounterparty?.items?.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                        {t("common.noData")}
                      </TableCell>
                    </TableRow>
                  ) : (
                    byCounterparty?.items?.map((item) => (
                      <TableRow key={item.counterparty_id}>
                        <TableCell className="font-medium">{item.counterparty_name}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{item.counterparty_type}</Badge>
                        </TableCell>
                        <TableCell className="text-right text-green-500">{item.total_income?.toFixed(2) || 0} лв.</TableCell>
                        <TableCell className="text-right text-red-500">{item.total_expenses?.toFixed(2) || 0} лв.</TableCell>
                        <TableCell className="text-right font-medium">{item.total?.toFixed(2) || 0} лв.</TableCell>
                        <TableCell className="text-right">{item.invoice_count}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
              
              {/* Pagination */}
              {byCounterparty && byCounterparty.total_pages > 1 && (
                <div className="flex items-center justify-between p-4 border-t">
                  <span className="text-sm text-muted-foreground">
                    Страница {cpPage} от {byCounterparty.total_pages}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setCpPage(p => Math.max(1, p - 1))} disabled={cpPage === 1}>
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setCpPage(p => Math.min(byCounterparty.total_pages, p + 1))} disabled={cpPage === byCounterparty.total_pages}>
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* By Project Tab */}
        <TabsContent value="project" className="mt-6">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("common.code")}</TableHead>
                    <TableHead>{t("common.name")}</TableHead>
                    <TableHead className="text-right text-green-500">{t("dashboard.income")}</TableHead>
                    <TableHead className="text-right text-red-500">{t("dashboard.expenses")}</TableHead>
                    <TableHead className="text-right">{t("common.total")}</TableHead>
                    <TableHead className="text-right">{t("data.invoiceCount")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {byProject?.items?.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                        {t("common.noData")}
                      </TableCell>
                    </TableRow>
                  ) : (
                    byProject?.items?.map((item) => (
                      <TableRow key={item.project_id}>
                        <TableCell className="font-mono text-primary">{item.project_code}</TableCell>
                        <TableCell className="font-medium">{item.project_name}</TableCell>
                        <TableCell className="text-right text-green-500">{item.total_income?.toFixed(2) || 0} лв.</TableCell>
                        <TableCell className="text-right text-red-500">{item.total_expenses?.toFixed(2) || 0} лв.</TableCell>
                        <TableCell className="text-right font-medium">{item.total?.toFixed(2) || 0} лв.</TableCell>
                        <TableCell className="text-right">{item.invoice_count}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
              
              {/* Pagination */}
              {byProject && byProject.total_pages > 1 && (
                <div className="flex items-center justify-between p-4 border-t">
                  <span className="text-sm text-muted-foreground">
                    Страница {projPage} от {byProject.total_pages}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setProjPage(p => Math.max(1, p - 1))} disabled={projPage === 1}>
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setProjPage(p => Math.min(byProject.total_pages, p + 1))} disabled={projPage === byProject.total_pages}>
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Transactions Tab */}
        <TabsContent value="transactions" className="mt-6 space-y-4">
          {/* Transaction Filters */}
          <Card>
            <CardContent className="p-4">
              <div className="flex flex-wrap items-end gap-4">
                <div className="space-y-1">
                  <Label className="text-xs">{t("common.type")}</Label>
                  <Select value={transactionType} onValueChange={setTransactionType}>
                    <SelectTrigger className="w-[150px]">
                      <SelectValue placeholder="Всички" />
                    </SelectTrigger>
                    <SelectContent>
                      {TRANSACTION_TYPES.map(t => (
                        <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">{t("common.direction") || "Посока"}</Label>
                  <Select value={direction} onValueChange={setDirection}>
                    <SelectTrigger className="w-[150px]">
                      <SelectValue placeholder="Всички" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Всички</SelectItem>
                      <SelectItem value="income">Приходи</SelectItem>
                      <SelectItem value="expense">Разходи</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("common.date")}</TableHead>
                    <TableHead>{t("common.type")}</TableHead>
                    <TableHead>{t("common.direction") || "Посока"}</TableHead>
                    <TableHead>{t("common.description")}</TableHead>
                    <TableHead className="text-right">{t("common.amount")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {transactions?.items?.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                        {t("common.noData")}
                      </TableCell>
                    </TableRow>
                  ) : (
                    transactions?.items?.map((item, idx) => (
                      <TableRow key={`${item.id}-${idx}`}>
                        <TableCell className="text-muted-foreground">{item.date}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{EXPENSE_LABELS[item.type] || item.type}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge 
                            variant={item.direction === "income" ? "default" : "destructive"}
                            className={item.direction === "income" ? "bg-green-600" : ""}
                          >
                            {item.direction === "income" ? "Приход" : "Разход"}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-[300px] truncate">{item.description}</TableCell>
                        <TableCell className={`text-right font-medium ${item.direction === "income" ? "text-green-500" : "text-red-500"}`}>
                          {item.direction === "income" ? "+" : "-"}{item.amount.toFixed(2)} лв.
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
              
              {/* Pagination */}
              {transactions && transactions.total_pages > 1 && (
                <div className="flex items-center justify-between p-4 border-t">
                  <span className="text-sm text-muted-foreground">
                    Показани {((txnPage - 1) * 20) + 1}-{Math.min(txnPage * 20, transactions.total)} от {transactions.total}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setTxnPage(p => Math.max(1, p - 1))} disabled={txnPage === 1}>
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setTxnPage(p => Math.min(transactions.total_pages, p + 1))} disabled={txnPage === transactions.total_pages}>
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
