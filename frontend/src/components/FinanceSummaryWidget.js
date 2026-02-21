import { useState, useEffect, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";

const MONTHS = [
  "Януари", "Февруари", "Март", "Април", "Май", "Юни",
  "Юли", "Август", "Септември", "Октомври", "Ноември", "Декември"
];

const MONTHS_SHORT = ["Яну", "Фев", "Мар", "Апр", "Май", "Юни", "Юли", "Авг", "Сеп", "Окт", "Ное", "Дек"];

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

const QUARTER_PRESETS = [
  { label: "Q1 (Яну-Мар)", months: [1, 2, 3] },
  { label: "Q2 (Апр-Юни)", months: [4, 5, 6] },
  { label: "Q3 (Юли-Сеп)", months: [7, 8, 9] },
  { label: "Q4 (Окт-Дек)", months: [10, 11, 12] },
];

export default function FinanceSummaryWidget() {
  const { t } = useTranslation();
  const currentDate = new Date();
  
  // View mode: "month" or "compare"
  const [viewMode, setViewMode] = useState("month");
  
  // Single month state
  const [year, setYear] = useState(currentDate.getFullYear());
  const [month, setMonth] = useState(currentDate.getMonth() + 1);
  const [data, setData] = useState(null);
  
  // Compare mode state
  const [compareYear, setCompareYear] = useState(currentDate.getFullYear());
  const [compareMonths, setCompareMonths] = useState([1, 2, 3]);
  const [comparePreset, setComparePreset] = useState("last3");
  const [compareData, setCompareData] = useState(null);
  
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);

  // Export handler
  const handleExport = useCallback(async (format) => {
    setExporting(true);
    try {
      const response = await API.get(
        `/reports/company-finance-export?year=${year}&month=${month}&format=${format}`,
        { responseType: 'blob' }
      );
      
      const blob = new Blob([response.data], {
        type: format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      });
      
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `finance_report_${year}_${String(month).padStart(2, '0')}.${format}`;
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
  }, [year, month, t]);

  // Fetch single month data
  useEffect(() => {
    if (viewMode !== "month") return;
    
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await API.get(`/reports/company-finance-summary?year=${year}&month=${month}`);
        setData(response.data);
      } catch (err) {
        console.error("Failed to fetch finance summary:", err);
        setError(t("common.error"));
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [year, month, viewMode, t]);

  // Fetch compare data
  useEffect(() => {
    if (viewMode !== "compare") return;
    
    const fetchCompareData = async () => {
      setLoading(true);
      setError(null);
      try {
        let url;
        if (comparePreset === "last3") {
          url = `/reports/company-finance-compare?mode=last3`;
        } else {
          const monthsStr = compareMonths.map(m => String(m).padStart(2, '0')).join(',');
          url = `/reports/company-finance-compare?year=${compareYear}&months=${monthsStr}`;
        }
        const response = await API.get(url);
        setCompareData(response.data);
      } catch (err) {
        console.error("Failed to fetch compare data:", err);
        setError(t("common.error"));
      } finally {
        setLoading(false);
      }
    };
    fetchCompareData();
  }, [compareYear, compareMonths, comparePreset, viewMode, t]);

  // Handle preset selection
  const handlePresetChange = useCallback((preset) => {
    setComparePreset(preset);
    if (preset !== "last3") {
      const quarterIndex = parseInt(preset.replace("q", "")) - 1;
      if (quarterIndex >= 0 && quarterIndex < 4) {
        setCompareMonths(QUARTER_PRESETS[quarterIndex].months);
      }
    }
  }, []);

  // Memoized chart data for single month
  const singleMonthCharts = useMemo(() => {
    if (!data) return null;
    
    const barChartData = data.weeks.map((w) => ({
      name: w.label,
      income: w.income,
      expenses: w.expenses,
    }));

    const pieChartData = Object.entries(data.expense_breakdown)
      .filter(([_, value]) => value > 0)
      .map(([key, value]) => ({
        name: t(`dashboard.expenseTypes.${key}`),
        value,
        color: EXPENSE_COLORS[key] || "#6b7280",
      }));

    const lineChartData = data.cumulative_balance.map((w) => ({
      name: w.label,
      balance: w.balance,
    }));

    return { barChartData, pieChartData, lineChartData };
  }, [data, t]);

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

  return (
    <div className="space-y-6" data-testid="finance-summary-widget">
      {/* Header with view toggle and selectors */}
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
              <TabsTrigger value="month" className="text-xs px-3" data-testid="view-month-btn">
                <Calendar className="w-3.5 h-3.5 mr-1.5" />
                {t("dashboard.viewMonth") || "Месец"}
              </TabsTrigger>
              <TabsTrigger value="compare" className="text-xs px-3" data-testid="view-compare-btn">
                <CalendarRange className="w-3.5 h-3.5 mr-1.5" />
                {t("dashboard.view3Months") || "3 месеца"}
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {viewMode === "month" ? (
            <>
              <Select value={String(year)} onValueChange={(v) => setYear(parseInt(v))}>
                <SelectTrigger className="w-[90px] h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[2024, 2025, 2026].map((y) => (
                    <SelectItem key={y} value={String(y)}>{y}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={String(month)} onValueChange={(v) => setMonth(parseInt(v))}>
                <SelectTrigger className="w-[130px] h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MONTHS.map((m, i) => (
                    <SelectItem key={i + 1} value={String(i + 1)}>{m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" disabled={exporting} data-testid="export-finance-btn">
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
          ) : (
            <>
              <Select value={comparePreset} onValueChange={handlePresetChange}>
                <SelectTrigger className="w-[140px] h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="last3">{t("dashboard.last3Months") || "Последни 3"}</SelectItem>
                  <SelectItem value="q1">Q1 (Яну-Мар)</SelectItem>
                  <SelectItem value="q2">Q2 (Апр-Юни)</SelectItem>
                  <SelectItem value="q3">Q3 (Юли-Сеп)</SelectItem>
                  <SelectItem value="q4">Q4 (Окт-Дек)</SelectItem>
                </SelectContent>
              </Select>
              {comparePreset !== "last3" && (
                <Select value={String(compareYear)} onValueChange={(v) => setCompareYear(parseInt(v))}>
                  <SelectTrigger className="w-[90px] h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[2024, 2025, 2026].map((y) => (
                      <SelectItem key={y} value={String(y)}>{y}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </>
          )}
        </div>
      </div>

      {/* Single Month View */}
      {viewMode === "month" && data && singleMonthCharts && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="bg-green-500/10 border-green-500/30">
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{t("dashboard.totalIncome")}</p>
                    <p className="text-2xl font-bold text-green-500">{data.totals.income.toFixed(2)} лв.</p>
                  </div>
                  <TrendingUp className="w-8 h-8 text-green-500/50" />
                </div>
              </CardContent>
            </Card>
            <Card className="bg-red-500/10 border-red-500/30">
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{t("dashboard.totalExpenses")}</p>
                    <p className="text-2xl font-bold text-red-500">{data.totals.expenses.toFixed(2)} лв.</p>
                  </div>
                  <TrendingDown className="w-8 h-8 text-red-500/50" />
                </div>
              </CardContent>
            </Card>
            <Card className={`${data.totals.net_balance >= 0 ? "bg-blue-500/10 border-blue-500/30" : "bg-amber-500/10 border-amber-500/30"}`}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{t("dashboard.netBalance")}</p>
                    <p className={`text-2xl font-bold ${data.totals.net_balance >= 0 ? "text-blue-500" : "text-amber-500"}`}>
                      {data.totals.net_balance >= 0 ? "+" : ""}{data.totals.net_balance.toFixed(2)} лв.
                    </p>
                  </div>
                  <Wallet className={`w-8 h-8 ${data.totals.net_balance >= 0 ? "text-blue-500/50" : "text-amber-500/50"}`} />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Charts */}
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
                  <BarChart data={singleMonthCharts.barChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
                    <YAxis stroke="#9ca3af" fontSize={12} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1f2937",
                        border: "1px solid #374151",
                        borderRadius: "8px",
                      }}
                      labelStyle={{ color: "#fff" }}
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
                {singleMonthCharts.pieChartData.length === 0 ? (
                  <div className="flex items-center justify-center h-[250px] text-muted-foreground">
                    {t("common.noData")}
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={250}>
                    <PieChart>
                      <Pie
                        data={singleMonthCharts.pieChartData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={90}
                        paddingAngle={2}
                        dataKey="value"
                        label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                        labelLine={false}
                      >
                        {singleMonthCharts.pieChartData.map((entry, index) => (
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
                  <LineChart data={singleMonthCharts.lineChartData}>
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
        </>
      )}

      {/* Compare Mode View (3 Months) */}
      {viewMode === "compare" && compareData && (
        <>
          {/* Overall Totals Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="bg-green-500/10 border-green-500/30">
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{t("dashboard.totalIncome")} (3 {t("dashboard.months") || "мес."})</p>
                    <p className="text-2xl font-bold text-green-500">{compareData.overall_totals.income.toFixed(2)} лв.</p>
                  </div>
                  <TrendingUp className="w-8 h-8 text-green-500/50" />
                </div>
              </CardContent>
            </Card>
            <Card className="bg-red-500/10 border-red-500/30">
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{t("dashboard.totalExpenses")} (3 {t("dashboard.months") || "мес."})</p>
                    <p className="text-2xl font-bold text-red-500">{compareData.overall_totals.expenses.toFixed(2)} лв.</p>
                  </div>
                  <TrendingDown className="w-8 h-8 text-red-500/50" />
                </div>
              </CardContent>
            </Card>
            <Card className={`${compareData.overall_totals.net >= 0 ? "bg-blue-500/10 border-blue-500/30" : "bg-amber-500/10 border-amber-500/30"}`}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{t("dashboard.netBalance")} (3 {t("dashboard.months") || "мес."})</p>
                    <p className={`text-2xl font-bold ${compareData.overall_totals.net >= 0 ? "text-blue-500" : "text-amber-500"}`}>
                      {compareData.overall_totals.net >= 0 ? "+" : ""}{compareData.overall_totals.net.toFixed(2)} лв.
                    </p>
                  </div>
                  <Wallet className={`w-8 h-8 ${compareData.overall_totals.net >= 0 ? "text-blue-500/50" : "text-amber-500/50"}`} />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Compare Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Income vs Expenses by Month Bar Chart */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">
                  {t("dashboard.incomeVsExpensesByMonth") || "Приходи vs Разходи по месеци"}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={compareData.bar_chart_data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="month_full" stroke="#9ca3af" fontSize={12} />
                    <YAxis stroke="#9ca3af" fontSize={12} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1f2937",
                        border: "1px solid #374151",
                        borderRadius: "8px",
                      }}
                      labelStyle={{ color: "#fff" }}
                      formatter={(value) => [`${value.toFixed(2)} лв.`]}
                    />
                    <Legend />
                    <Bar dataKey="income" name={t("dashboard.income")} fill="#22c55e" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="expenses" name={t("dashboard.expenses")} fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            {/* Net Balance Trend Line Chart */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">
                  {t("dashboard.netBalanceTrend") || "Тренд на нетния баланс"}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={250}>
                  <LineChart data={compareData.line_chart_data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="month_full" stroke="#9ca3af" fontSize={12} />
                    <YAxis stroke="#9ca3af" fontSize={12} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1f2937",
                        border: "1px solid #374151",
                        borderRadius: "8px",
                      }}
                      formatter={(value) => [`${value.toFixed(2)} лв.`, t("dashboard.netBalance")]}
                    />
                    <Line
                      type="monotone"
                      dataKey="net"
                      stroke="#3b82f6"
                      strokeWidth={3}
                      dot={{ fill: "#3b82f6", strokeWidth: 2, r: 5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          {/* Monthly Details Table */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                {t("dashboard.monthlyDetails") || "Детайли по месеци"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("dashboard.month") || "Месец"}</TableHead>
                    <TableHead className="text-right text-green-500">{t("dashboard.income")}</TableHead>
                    <TableHead className="text-right text-red-500">{t("dashboard.expenses")}</TableHead>
                    <TableHead className="text-right">{t("dashboard.netBalance")}</TableHead>
                    <TableHead>{t("dashboard.topExpenseType") || "Топ разход"}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {compareData.months.map((m, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="font-medium">
                        {m.month_name} {m.year}
                      </TableCell>
                      <TableCell className="text-right text-green-500">
                        {m.totals.income_total.toFixed(2)} лв.
                      </TableCell>
                      <TableCell className="text-right text-red-500">
                        {m.totals.expenses_total.toFixed(2)} лв.
                      </TableCell>
                      <TableCell className={`text-right font-semibold ${m.totals.net >= 0 ? "text-blue-500" : "text-amber-500"}`}>
                        {m.totals.net >= 0 ? "+" : ""}{m.totals.net.toFixed(2)} лв.
                      </TableCell>
                      <TableCell>
                        {m.top_expense_type ? (
                          <Badge 
                            variant="outline" 
                            className="text-xs"
                            style={{ borderColor: EXPENSE_COLORS[m.top_expense_type], color: EXPENSE_COLORS[m.top_expense_type] }}
                          >
                            {EXPENSE_LABELS[m.top_expense_type] || m.top_expense_type}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
