import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import API from "@/lib/api";
import DataTable from "@/components/DataTable";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { BarChart3, TrendingUp, TrendingDown, FileText, ExternalLink } from "lucide-react";
import { formatCurrency } from "@/lib/i18nUtils";

export default function TurnoverPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [type, setType] = useState(searchParams.get("type") || "purchases");
  const [grandTotals, setGrandTotals] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedCounterparty, setSelectedCounterparty] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [invoicesLoading, setInvoicesLoading] = useState(false);

  const columns = [
    {
      key: "counterparty_name",
      label: t("data.counterparty"),
      sortable: true,
      filterable: true,
      filterType: "contains",
      render: (value, row) => (
        <div>
          <div className="font-medium">{value}</div>
          {row.counterparty_eik && (
            <div className="text-xs text-muted-foreground">
              {t("data.eik")}: {row.counterparty_eik}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "counterparty_type",
      label: t("data.type"),
      width: "100px",
      render: (value) =>
        value ? (
          <Badge variant="outline">{value}</Badge>
        ) : (
          "-"
        ),
    },
    {
      key: "count_invoices",
      label: t("data.invoiceCount"),
      sortable: true,
      width: "100px",
      render: (value) => <Badge variant="secondary">{value}</Badge>,
    },
    {
      key: "sum_subtotal",
      label: t("data.sumNet"),
      sortable: true,
      width: "120px",
      render: (value) => `${value.toFixed(2)} лв.`,
    },
    {
      key: "sum_vat",
      label: t("data.sumVat"),
      sortable: true,
      width: "100px",
      render: (value) => `${value.toFixed(2)} лв.`,
    },
    {
      key: "sum_total",
      label: t("data.sumTotal"),
      sortable: true,
      width: "120px",
      render: (value) => <span className="font-bold">{value.toFixed(2)} лв.</span>,
    },
    {
      key: "sum_paid",
      label: t("data.sumPaid"),
      sortable: true,
      width: "110px",
      render: (value) => (
        <span className="text-green-600">{value.toFixed(2)} лв.</span>
      ),
    },
    {
      key: "sum_remaining",
      label: t("data.sumRemaining"),
      sortable: true,
      width: "110px",
      render: (value) =>
        value > 0 ? (
          <span className="text-red-600 font-medium">{value.toFixed(2)} лв.</span>
        ) : (
          <span className="text-muted-foreground">0.00 лв.</span>
        ),
    },
    {
      key: "first_invoice_date",
      label: t("data.firstInvoice"),
      width: "110px",
    },
    {
      key: "last_invoice_date",
      label: t("data.lastInvoice"),
      width: "110px",
    },
  ];

  const fetchData = useCallback(
    async (params) => {
      const queryParams = new URLSearchParams();
      queryParams.append("page", params.page);
      queryParams.append("page_size", params.page_size);
      queryParams.append("type", type);
      if (params.sort_by) queryParams.append("sort_by", params.sort_by);
      if (params.sort_dir) queryParams.append("sort_dir", params.sort_dir);

      // Parse filters for date range
      if (params.filters) {
        const filterParts = params.filters.split(",");
        filterParts.forEach((part) => {
          const [keyOp, value] = part.split("=");
          if (!keyOp || !value) return;
          if (keyOp === "date.from") {
            queryParams.append("date_from", value);
          } else if (keyOp === "date.to") {
            queryParams.append("date_to", value);
          }
        });
      }

      // Check URL params
      const dateFrom = searchParams.get("date_from");
      if (dateFrom) queryParams.set("date_from", dateFrom);
      const dateTo = searchParams.get("date_to");
      if (dateTo) queryParams.set("date_to", dateTo);
      
      // Filter by specific counterparty if provided
      const counterpartyId = searchParams.get("counterparty_id");
      if (counterpartyId) queryParams.set("counterparty_id", counterpartyId);

      const response = await API.get(
        `/reports/turnover-by-counterparty?${queryParams.toString()}`
      );

      // Store grand totals
      setGrandTotals(response.data.grand_totals);

      return response.data;
    },
    [type, searchParams]
  );

  const handleTypeChange = (newType) => {
    setType(newType);
    const newParams = new URLSearchParams(searchParams);
    newParams.set("type", newType);
    setSearchParams(newParams);
    setRefreshKey((k) => k + 1);
  };

  const handleRowClick = async (row) => {
    if (!row.counterparty_id) return;
    setSelectedCounterparty(row);
    setDrawerOpen(true);
    setInvoicesLoading(true);

    try {
      const params = new URLSearchParams();
      params.append("type", type);
      const dateFrom = searchParams.get("date_from");
      const dateTo = searchParams.get("date_to");
      if (dateFrom) params.append("date_from", dateFrom);
      if (dateTo) params.append("date_to", dateTo);

      const response = await API.get(
        `/reports/turnover-by-counterparty/${row.counterparty_id}/invoices?${params.toString()}`
      );
      setInvoices(response.data.items || []);
    } catch (err) {
      console.error(err);
      setInvoices([]);
    } finally {
      setInvoicesLoading(false);
    }
  };

  const navigateToPrices = (counterpartyId) => {
    const params = new URLSearchParams();
    params.set("supplier_id", counterpartyId);
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    navigate(`/data/prices?${params.toString()}`);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <BarChart3 className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold" data-testid="turnover-page-title">
              {t("data.turnover")}
            </h1>
            <p className="text-sm text-muted-foreground">{t("data.turnoverDesc")}</p>
          </div>
        </div>

        {/* Type selector */}
        <Select value={type} onValueChange={handleTypeChange}>
          <SelectTrigger className="w-[180px]" data-testid="turnover-type-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="purchases">
              <div className="flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-red-500" />
                {t("data.purchases")}
              </div>
            </SelectItem>
            <SelectItem value="sales">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-green-500" />
                {t("data.sales")}
              </div>
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Grand Totals Cards */}
      {grandTotals && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t("data.totalInvoices")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{grandTotals.total_invoices}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t("data.totalNet")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {grandTotals.total_subtotal?.toFixed(2)} лв.
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t("data.totalVat")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {grandTotals.total_vat?.toFixed(2)} лв.
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t("data.grandTotal")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-primary">
                {grandTotals.total_amount?.toFixed(2)} лв.
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t("data.totalPaid")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-600">
                {grandTotals.total_paid?.toFixed(2)} лв.
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t("data.totalRemaining")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-600">
                {grandTotals.total_remaining?.toFixed(2)} лв.
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Data Table */}
      <DataTable
        columns={columns}
        fetchData={fetchData}
        refreshKey={refreshKey}
        exportFilename={`turnover-${type}.csv`}
        onRowClick={handleRowClick}
        searchPlaceholder={t("data.searchCounterparty")}
      />

      {/* Drilldown Drawer */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent className="w-[500px] sm:max-w-lg">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <FileText className="w-5 h-5" />
              {selectedCounterparty?.counterparty_name}
            </SheetTitle>
          </SheetHeader>
          <div className="mt-6 space-y-4">
            {/* Summary */}
            <div className="grid grid-cols-2 gap-4 p-4 bg-muted rounded-lg">
              <div>
                <div className="text-sm text-muted-foreground">{t("data.invoiceCount")}</div>
                <div className="text-lg font-bold">{selectedCounterparty?.count_invoices}</div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground">{t("data.sumTotal")}</div>
                <div className="text-lg font-bold">
                  {selectedCounterparty?.sum_total?.toFixed(2)} лв.
                </div>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigateToPrices(selectedCounterparty?.counterparty_id)}
              >
                <ExternalLink className="w-4 h-4 mr-2" />
                {t("data.viewPrices")}
              </Button>
            </div>

            {/* Invoices list */}
            <div className="space-y-2">
              <h4 className="font-medium">{t("data.invoices")}</h4>
              {invoicesLoading ? (
                <div className="text-center py-4 text-muted-foreground">
                  {t("common.loading")}
                </div>
              ) : invoices.length === 0 ? (
                <div className="text-center py-4 text-muted-foreground">
                  {t("common.noData")}
                </div>
              ) : (
                <div className="space-y-2 max-h-[400px] overflow-y-auto">
                  {invoices.map((inv) => (
                    <div
                      key={inv.id}
                      className="flex items-center justify-between p-3 border rounded-lg hover:bg-muted/50 cursor-pointer"
                      onClick={() => navigate(`/finance/invoices/${inv.id}`)}
                    >
                      <div>
                        <div className="font-medium">{inv.invoice_no}</div>
                        <div className="text-sm text-muted-foreground">
                          {inv.issue_date}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-bold">{inv.total?.toFixed(2)} лв.</div>
                        <Badge
                          variant={inv.status === "Paid" ? "default" : "secondary"}
                          className="text-xs"
                        >
                          {inv.status}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
