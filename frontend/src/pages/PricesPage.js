import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import API from "@/lib/api";
import DataTable from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DollarSign, TrendingUp } from "lucide-react";
import { formatCurrency, formatDate } from "@/lib/i18nUtils";

export default function PricesPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const [counterparties, setCounterparties] = useState([]);
  const [projects, setProjects] = useState([]);
  const [warehouses, setWarehouses] = useState([]);

  // Fetch reference data for filters
  useEffect(() => {
    Promise.all([
      API.get("/counterparties?page_size=100&active_only=false"),
      API.get("/projects?status=all"),
      API.get("/warehouses?page_size=100&active_only=false"),
    ])
      .then(([cpRes, projRes, whRes]) => {
        setCounterparties(cpRes.data.items || cpRes.data || []);
        setProjects(projRes.data || []);
        setWarehouses(whRes.data.items || whRes.data || []);
      })
      .catch(console.error);
  }, []);

  const columns = [
    { 
      key: "description", 
      label: t("data.item"), 
      sortable: true, 
      filterable: true, 
      filterType: "contains",
      render: (value, row) => (
        <div>
          <div className="font-medium">{value}</div>
          {row.invoice_no && (
            <div className="text-xs text-muted-foreground">
              {t("data.invoice")}: {row.invoice_no}
            </div>
          )}
        </div>
      )
    },
    { 
      key: "supplier_name", 
      label: t("data.supplier"), 
      sortable: true, 
      filterable: true,
      filterType: "contains",
      width: "180px",
    },
    { 
      key: "invoice_date", 
      label: t("data.invoiceDate"), 
      sortable: true, 
      filterable: true, 
      filterType: "dateRange",
      width: "120px",
      render: (value) => value ? formatDate(value) : "-",
    },
    { 
      key: "qty", 
      label: t("data.qty"), 
      sortable: true,
      width: "80px",
      render: (value, row) => `${value} ${row.unit || ""}`,
    },
    { 
      key: "unit_price", 
      label: t("data.unitPrice"), 
      sortable: true,
      filterable: true,
      filterType: "numberRange",
      width: "100px",
      render: (value) => value ? `${value.toFixed(2)} лв.` : "-",
    },
    { 
      key: "line_total_ex_vat", 
      label: t("data.totalExVat"), 
      sortable: true,
      width: "110px",
      render: (value) => value ? `${value.toFixed(2)} лв.` : "-",
    },
    { 
      key: "vat_amount", 
      label: t("data.vat"), 
      sortable: true,
      width: "80px",
      render: (value) => value ? `${value.toFixed(2)} лв.` : "-",
    },
    { 
      key: "line_total_inc_vat", 
      label: t("data.totalIncVat"), 
      sortable: true,
      width: "110px",
      render: (value) => (
        <span className="font-medium">{value ? `${value.toFixed(2)} лв.` : "-"}</span>
      ),
    },
    { 
      key: "allocation_summary", 
      label: t("data.allocation"), 
      width: "150px",
      render: (value) => value ? (
        <Badge variant="outline" className="font-mono text-xs">
          {value}
        </Badge>
      ) : "-",
    },
    { 
      key: "cost_category", 
      label: t("data.category"), 
      sortable: true,
      width: "100px",
      render: (value) => value ? <Badge variant="secondary">{value}</Badge> : "-",
    },
  ];

  const fetchData = useCallback(async (params) => {
    const queryParams = new URLSearchParams();
    queryParams.append("page", params.page);
    queryParams.append("page_size", params.page_size);
    if (params.sort_by) queryParams.append("sort_by", params.sort_by);
    if (params.sort_dir) queryParams.append("sort_dir", params.sort_dir);
    if (params.search) queryParams.append("search", params.search);
    
    // Parse filter string and extract specific filters
    if (params.filters) {
      const filterParts = params.filters.split(",");
      filterParts.forEach(part => {
        const [keyOp, value] = part.split("=");
        if (!keyOp || !value) return;
        
        if (keyOp === "invoice_date.from") {
          queryParams.append("date_from", value);
        } else if (keyOp === "invoice_date.to") {
          queryParams.append("date_to", value);
        } else if (keyOp.startsWith("supplier_id")) {
          queryParams.append("supplier_id", value);
        }
      });
    }
    
    // Check URL params for pre-filters (e.g., from turnover drilldown)
    const supplierId = searchParams.get("supplier_id");
    if (supplierId) queryParams.set("supplier_id", supplierId);
    const dateFrom = searchParams.get("date_from");
    if (dateFrom) queryParams.set("date_from", dateFrom);
    const dateTo = searchParams.get("date_to");
    if (dateTo) queryParams.set("date_to", dateTo);
    const projectId = searchParams.get("project_id");
    if (projectId) queryParams.set("project_id", projectId);
    const warehouseId = searchParams.get("warehouse_id");
    if (warehouseId) queryParams.set("warehouse_id", warehouseId);

    const response = await API.get(`/prices?${queryParams.toString()}`);
    return response.data;
  }, [searchParams]);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-primary/10">
          <TrendingUp className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold" data-testid="prices-page-title">
            {t("data.prices")}
          </h1>
          <p className="text-sm text-muted-foreground">{t("data.pricesDesc")}</p>
        </div>
      </div>

      {/* Data Table (read-only) */}
      <DataTable
        columns={columns}
        fetchData={fetchData}
        exportFilename="prices.csv"
        searchPlaceholder={t("data.searchPrices")}
      />
    </div>
  );
}
