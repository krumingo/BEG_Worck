import { useState, useEffect, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  LineChart,
  Line,
} from "recharts";
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  Loader2,
  Download,
  FileText,
  FileSpreadsheet,
  CalendarRange,
  Calendar,
  ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";

const MONTHS_FULL = [
  "Януари", "Февруари", "Март", "Април", "Май", "Юни",
  "Юли", "Август", "Септември", "Октомври", "Ноември", "Декември"
];

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

const PERIOD_OPTIONS = [
  { value: "1", label: "1 месец" },
  { value: "3", label: "3 месеца" },
  { value: "6", label: "6 месеца" },
  { value: "12", label: "12 месеца" },
];

export default function FinanceSummaryWidget() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const currentDate = new Date();
  
  // Period state (1, 3, 6, 12 months)
  const [period, setPeriod] = useState("3");
  
  // For single month detailed view
  const [selectedYear, setSelectedYear] = useState(currentDate.getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(currentDate.getMonth() + 1);
  const [weeklyData, setWeeklyData] = useState(null);
  
  // Series data for N months
  const [seriesData, setSeriesData] = useState(null);
  
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);
  
  // View mode: "rolling" (N months) or "weekly" (single month details)
  const [viewMode, setViewMode] = useState("rolling");

  // Fetch series data for N months
  useEffect(() => {
    if (viewMode !== "rolling") return;
    
    const fetchSeries = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await API.get(`/reports/company-finance-series?months=${period}`);
        setSeriesData(response.data);
      } catch (err) {
        console.error("Failed to fetch finance series:", err);
        setError(t("common.error"));
      } finally {
        setLoading(false);
      }
    };
    fetchSeries();
  }, [period, viewMode, t]);

  // Fetch weekly data for single month
  useEffect(() => {
    if (viewMode !== "weekly") return;
    
    const fetchWeekly = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await API.get(`/reports/company-finance-summary?year=${selectedYear}&month=${selectedMonth}`);
        setWeeklyData(response.data);
      } catch (err) {
        console.error("Failed to fetch weekly data:", err);
        setError(t("common.error"));
      } finally {
        setLoading(false);
      }
    };
    fetchWeekly();
  }, [selectedYear, selectedMonth, viewMode, t]);

  // Export handler
  const handleExport = useCallback(async (format) => {
    setExporting(true);
    try {
      const response = await API.get(
        `/reports/company-finance-export?year=${selectedYear}&month=${selectedMonth}&format=${format}`,
        { responseType: 'blob' }
      );
      
      const blob = new Blob([response.data], {
        type: format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      });
      
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `finance_report_${selectedYear}_${String(selectedMonth).padStart(2, '0')}.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      
      toast.success(t("clients.export") + " " + format.toUpperCase() + " - " + t("common.success"));
    } catch (err) {
      console.error("Export failed:", err);
      toast.error(t("common.error"));
    } finally {
      setExporting(false);
    }
  }, [selectedYear, selectedMonth, t]);

  // Memoized chart data for rolling view
  const rollingCharts = useMemo(() => {
    if (!seriesData) return null;
    
    const barData = seriesData.months.map((m) => ({
      name: `${m.month_name} ${m.year}`,
      short: m.month_name,
      income: m.income_total,
      expenses: m.expenses_total,
    }));

    const lineData = seriesData.months.map((m) => ({
      name: `${m.month_name} ${m.year}`,
      short: m.month_name,
      net: m.net,
    }));

    // Expense breakdown aggregated
    const breakdown = seriesData.months.reduce((acc, m) => {
      Object.entries(m.breakdown).forEach(([key, val]) => {
        if (key.startsWith("expenses_")) {
          const expKey = key.replace("expenses_", "");
          acc[expKey] = (acc[expKey] || 0) + val;
        }
      });
      return acc;
    }, {});

    const pieData = Object.entries(breakdown)
      .filter(([_, value]) => value > 0)
      .map(([key, value]) => ({
        name: EXPENSE_LABELS[key] || key,
        value: Math.round(value * 100) / 100,
        color: EXPENSE_COLORS[key] || "#6b7280",
      }));

    return { barData, lineData, pieData };
  }, [seriesData]);

  // Memoized chart data for weekly view
  const weeklyCharts = useMemo(() => {
    if (!weeklyData) return null;
    
    const barData = weeklyData.weeks.map((w) => ({
      name: w.label,
      income: w.income,
      expenses: w.expenses,
    }));

    const pieData = Object.entries(weeklyData.expense_breakdown)
      .filter(([_, value]) => value > 0)
      .map(([key, value]) => ({
        name: EXPENSE_LABELS[key] || key,
        value,
        color: EXPENSE_COLORS[key] || "#6b7280",
      }));

    const lineData = weeklyData.cumulative_balance.map((w) => ({
      name: w.label,
      balance: w.balance,
    }));

    return { barData, pieData, lineData };
  }, [weeklyData]);

  // Loading state
  if (loading) {
    return (
      <Card className="col-span-full">
        <CardContent className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  // Error state
  if (error) {
    return (
      <Card className="col-span-full">
        <CardContent className="flex items-center justify-center h-64 text-muted-foreground">
          {error}
        </CardContent>
      </Card>
    );
  }

  const totals = viewMode === "rolling" ? seriesData?.totals : weeklyData?.totals;
  const netValue = viewMode === "rolling" ? totals?.net : totals?.net_balance;

  return (
    <div className="space-y-6" data-testid="finance-summary-widget">
      {/* Header with controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Wallet className="w-5 h-5 text-primary" />
          </div>
          <h2 className="text-lg font-semibold">{t("dashboard.financeSection")}</h2>
        </div>
        
        <div className="flex flex-wrap items-center gap-2">
          {/* View Mode Toggle */}
          <Tabs value={viewMode} onValueChange={setViewMode} className="mr-2">
            <TabsList className="h-9">
              <TabsTrigger value="rolling" className="text-xs px-3" data-testid="view-rolling-btn">
                <CalendarRange className="w-3.5 h-3.5 mr-1.5" />
                {t("dashboard.rollingPeriod") || "Период"}
              </TabsTrigger>
              <TabsTrigger value="weekly" className="text-xs px-3" data-testid="view-weekly-btn">
                <Calendar className="w-3.5 h-3.5 mr-1.5" />
                {t("dashboard.weeklyView") || "По седмици"}
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {viewMode === "rolling" ? (
            <>
              {/* Period Selector */}
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger className="w-[120px] h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERIOD_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          ) : (
            <>
              {/* Year/Month Selectors for weekly view */}
              <Select value={String(selectedYear)} onValueChange={(v) => setSelectedYear(parseInt(v))}>
                <SelectTrigger className="w-[90px] h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[2024, 2025, 2026].map((y) => (
                    <SelectItem key={y} value={String(y)}>{y}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={String(selectedMonth)} onValueChange={(v) => setSelectedMonth(parseInt(v))}>
                <SelectTrigger className="w-[130px] h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MONTHS_FULL.map((m, i) => (
                    <SelectItem key={i + 1} value={String(i + 1)}>{m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" disabled={exporting}>
                    {exporting ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Download className="w-4 h-4 mr-2" />
                    )}
                    {t("clients.export")}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => handleExport('pdf')}>
                    <FileText className="w-4 h-4 mr-2 text-red-500" />
                    PDF
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleExport('xlsx')}>
                    <FileSpreadsheet className="w-4 h-4 mr-2 text-green-500" />
                    Excel
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          )}

          {/* Details Button */}
          <Button 
            variant="outline" 
            size="sm" 
            onClick={() => navigate("/reports/finance-details")}
            data-testid="finance-details-btn"
          >
            <ExternalLink className="w-4 h-4 mr-2" />
            {t("dashboard.details") || "Подробно"}
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      {totals && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="bg-green-500/10 border-green-500/30">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">
                    {t("dashboard.totalIncome")} {viewMode === "rolling" ? `(${period} мес.)` : ""}
                  </p>
                  <p className="text-2xl font-bold text-green-500">{totals.income?.toFixed(2)} лв.</p>
                </div>
                <TrendingUp className="w-8 h-8 text-green-500/50" />
              </div>
            </CardContent>
          </Card>
          <Card className="bg-red-500/10 border-red-500/30">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">
                    {t("dashboard.totalExpenses")} {viewMode === "rolling" ? `(${period} мес.)` : ""}
                  </p>
                  <p className="text-2xl font-bold text-red-500">{totals.expenses?.toFixed(2)} лв.</p>
                </div>
                <TrendingDown className="w-8 h-8 text-red-500/50" />
              </div>
            </CardContent>
          </Card>
          <Card className={`${netValue >= 0 ? "bg-blue-500/10 border-blue-500/30" : "bg-amber-500/10 border-amber-500/30"}`}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">
                    {t("dashboard.netBalance")} {viewMode === "rolling" ? `(${period} мес.)` : ""}
                  </p>
                  <p className={`text-2xl font-bold ${netValue >= 0 ? "text-blue-500" : "text-amber-500"}`}>
                    {netValue >= 0 ? "+" : ""}{netValue?.toFixed(2)} лв.
                  </p>
                </div>
                <Wallet className={`w-8 h-8 ${netValue >= 0 ? "text-blue-500/50" : "text-amber-500/50"}`} />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Charts - Rolling View */}
      {viewMode === "rolling" && rollingCharts && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Income vs Expenses Bar Chart */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                {t("dashboard.incomeVsExpenses")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={rollingCharts.barData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="short" stroke="#9ca3af" fontSize={11} />
                  <YAxis stroke="#9ca3af" fontSize={11} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1f2937",
                      border: "1px solid #374151",
                      borderRadius: "8px",
                    }}
                    formatter={(value) => [`${value.toFixed(2)} лв.`]}
                    labelFormatter={(label, payload) => payload?.[0]?.payload?.name || label}
                  />
                  <Legend />
                  <Bar dataKey="income" name={t("dashboard.income")} fill="#22c55e" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="expenses" name={t("dashboard.expenses")} fill="#ef4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Net Balance Line Chart */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                {t("dashboard.netBalanceTrend") || "Тренд на нетния баланс"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={rollingCharts.lineData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="short" stroke="#9ca3af" fontSize={11} />
                  <YAxis stroke="#9ca3af" fontSize={11} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1f2937",
                      border: "1px solid #374151",
                      borderRadius: "8px",
                    }}
                    formatter={(value) => [`${value.toFixed(2)} лв.`, t("dashboard.netBalance")]}
                    labelFormatter={(label, payload) => payload?.[0]?.payload?.name || label}
                  />
                  <Line
                    type="monotone"
                    dataKey="net"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={{ fill: "#3b82f6", strokeWidth: 2 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Expense Breakdown Pie Chart */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                {t("dashboard.expenseBreakdown")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {rollingCharts.pieData.length === 0 ? (
                <div className="flex items-center justify-center h-[200px] text-muted-foreground">
                  {t("common.noData")}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie
                      data={rollingCharts.pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={2}
                      dataKey="value"
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {rollingCharts.pieData.map((entry, index) => (
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
        </div>
      )}

      {/* Charts - Weekly View */}
      {viewMode === "weekly" && weeklyCharts && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Income vs Expenses Bar Chart */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                {t("dashboard.incomeVsExpenses")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={weeklyCharts.barData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
                  <YAxis stroke="#9ca3af" fontSize={12} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1f2937",
                      border: "1px solid #374151",
                      borderRadius: "8px",
                    }}
                  />
                  <Legend />
                  <Bar dataKey="income" name={t("dashboard.income")} fill="#22c55e" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="expenses" name={t("dashboard.expenses")} fill="#ef4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Expense Breakdown Pie Chart */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                {t("dashboard.expenseBreakdown")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {weeklyCharts.pieData.length === 0 ? (
                <div className="flex items-center justify-center h-[250px] text-muted-foreground">
                  {t("common.noData")}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={250}>
                  <PieChart>
                    <Pie
                      data={weeklyCharts.pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={90}
                      paddingAngle={2}
                      dataKey="value"
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {weeklyCharts.pieData.map((entry, index) => (
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

          {/* Cumulative Balance Line Chart */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                {t("dashboard.cumulativeBalance")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={weeklyCharts.lineData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
                  <YAxis stroke="#9ca3af" fontSize={12} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1f2937",
                      border: "1px solid #374151",
                      borderRadius: "8px",
                    }}
                    formatter={(value) => [`${value.toFixed(2)} лв.`, t("dashboard.balance")]}
                  />
                  <Line
                    type="monotone"
                    dataKey="balance"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={{ fill: "#3b82f6", strokeWidth: 2 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
