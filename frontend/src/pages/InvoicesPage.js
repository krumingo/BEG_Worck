import { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
  ArrowLeft,
  FileText,
  Plus,
  Search,
  Filter,
  ArrowRight,
  AlertTriangle,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Sent: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  PartiallyPaid: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  Paid: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Overdue: "bg-red-500/20 text-red-400 border-red-500/30",
  Cancelled: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

export default function InvoicesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const directionParam = searchParams.get("direction") || "";
  const statusParam = searchParams.get("status") || "";
  const projectParam = searchParams.get("projectId") || "";

  const [invoices, setInvoices] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [directionFilter, setDirectionFilter] = useState(directionParam);
  const [statusFilter, setStatusFilter] = useState(statusParam);
  const [projectFilter, setProjectFilter] = useState(projectParam);

  const canCreate = ["Admin", "Owner", "Accountant"].includes(user?.role);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (directionFilter) params.append("direction", directionFilter);
      if (statusFilter) params.append("status", statusFilter);
      if (projectFilter) params.append("project_id", projectFilter);

      const [invoicesRes, projectsRes] = await Promise.all([
        API.get(`/finance/invoices?${params.toString()}`),
        API.get("/projects"),
      ]);
      setInvoices(invoicesRes.data);
      setProjects(projectsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [directionFilter, statusFilter, projectFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const updateFilter = (key, value) => {
    const newParams = new URLSearchParams(searchParams);
    if (value && value !== "all") {
      newParams.set(key, value);
    } else {
      newParams.delete(key);
    }
    setSearchParams(newParams);
    
    if (key === "direction") setDirectionFilter(value === "all" ? "" : value);
    if (key === "status") setStatusFilter(value === "all" ? "" : value);
    if (key === "projectId") setProjectFilter(value === "all" ? "" : value);
  };

  const filteredInvoices = search
    ? invoices.filter(inv =>
        inv.invoice_no?.toLowerCase().includes(search.toLowerCase()) ||
        inv.counterparty_name?.toLowerCase().includes(search.toLowerCase()) ||
        inv.project_code?.toLowerCase().includes(search.toLowerCase())
      )
    : invoices;

  const getStatusKey = (status) => {
    const map = {
      Draft: "draft",
      Sent: "sent",
      PartiallyPaid: "partiallyPaid",
      Paid: "paid",
      Overdue: "overdue",
      Cancelled: "cancelled",
    };
    return map[status] || status.toLowerCase();
  };

  const getTitle = () => {
    if (directionFilter === "Issued") return t("finance.salesInvoices");
    if (directionFilter === "Received") return t("finance.bills");
    return t("finance.invoices");
  };

  const getSubtitle = () => {
    if (directionFilter === "Issued") return t("finance.issuedSales");
    if (directionFilter === "Received") return t("finance.receivedBills");
    return t("finance.invoicesSubtitle");
  };

  return (
    <div className="p-8 max-w-[1400px]" data-testid="invoices-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/finance")} data-testid="back-btn">
            <ArrowLeft className="w-4 h-4 mr-1" /> {t("common.back")}
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-foreground">{getTitle()}</h1>
            <p className="text-sm text-muted-foreground mt-1">{getSubtitle()}</p>
          </div>
        </div>
        {canCreate && (
          <Button onClick={() => navigate("/finance/invoices/new")} data-testid="create-invoice-btn">
            <Plus className="w-4 h-4 mr-2" /> {t("finance.newInvoice")}
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6 flex-wrap" data-testid="invoice-filters">
        <div className="relative flex-1 min-w-[200px] max-w-[300px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder={t("finance.searchInvoices")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-card"
            data-testid="search-input"
          />
        </div>
        <Select value={directionFilter || "all"} onValueChange={(v) => updateFilter("direction", v)}>
          <SelectTrigger className="w-[180px] bg-card" data-testid="direction-filter">
            <Filter className="w-4 h-4 mr-2 text-muted-foreground" />
            <SelectValue placeholder={t("common.allDirections")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allDirections")}</SelectItem>
            <SelectItem value="Issued">{t("finance.issuedSales")}</SelectItem>
            <SelectItem value="Received">{t("finance.receivedBills")}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={statusFilter || "all"} onValueChange={(v) => updateFilter("status", v)}>
          <SelectTrigger className="w-[160px] bg-card" data-testid="status-filter">
            <SelectValue placeholder={t("common.allStatuses")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allStatuses")}</SelectItem>
            <SelectItem value="Draft">{t("finance.status.draft")}</SelectItem>
            <SelectItem value="Sent">{t("finance.status.sent")}</SelectItem>
            <SelectItem value="PartiallyPaid">{t("finance.status.partiallyPaid")}</SelectItem>
            <SelectItem value="Paid">{t("finance.status.paid")}</SelectItem>
            <SelectItem value="Overdue">{t("finance.status.overdue")}</SelectItem>
            <SelectItem value="Cancelled">{t("finance.status.cancelled")}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={projectFilter || "all"} onValueChange={(v) => updateFilter("projectId", v)}>
          <SelectTrigger className="w-[200px] bg-card" data-testid="project-filter">
            <SelectValue placeholder={t("common.allProjects")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allProjects")}</SelectItem>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="invoices-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.invoiceNo")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.type")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.counterparty")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("offers.project")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.status")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.issueDate")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.dueDate")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.total")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("finance.remainingAmount")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredInvoices.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={10} className="text-center py-12 text-muted-foreground">
                    <FileText className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>{t("finance.noInvoices")}</p>
                    {canCreate && (
                      <Button variant="outline" className="mt-4" onClick={() => navigate("/finance/invoices/new")}>
                        {t("finance.createFirstInvoice")}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                filteredInvoices.map((invoice) => (
                  <TableRow 
                    key={invoice.id} 
                    className="table-row-hover cursor-pointer"
                    onClick={() => navigate(`/finance/invoices/${invoice.id}`)}
                    data-testid={`invoice-row-${invoice.id}`}
                  >
                    <TableCell>
                      <p className="font-mono text-sm text-primary">{invoice.invoice_no}</p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={
                        invoice.direction === "Issued" 
                          ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                          : "bg-amber-500/20 text-amber-400 border-amber-500/30"
                      }>
                        {invoice.direction === "Issued" ? t("finance.invoiceType.sale") : t("finance.invoiceType.bill")}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-foreground max-w-[150px] truncate">
                      {invoice.counterparty_name || "-"}
                    </TableCell>
                    <TableCell>
                      {invoice.project_code ? (
                        <span className="font-mono text-xs text-muted-foreground">{invoice.project_code}</span>
                      ) : "-"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Badge variant="outline" className={`text-xs ${STATUS_COLORS[invoice.status] || ""}`}>
                          {t(`finance.status.${getStatusKey(invoice.status)}`)}
                        </Badge>
                        {invoice.is_overdue && (
                          <AlertTriangle className="w-3 h-3 text-red-400" />
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(invoice.issue_date)}
                    </TableCell>
                    <TableCell className={`text-sm ${invoice.is_overdue ? "text-red-400 font-medium" : "text-muted-foreground"}`}>
                      {formatDate(invoice.due_date)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm text-foreground">
                      {formatCurrency(invoice.total, invoice.currency)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm text-muted-foreground">
                      {formatCurrency(invoice.remaining_amount, invoice.currency)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/finance/invoices/${invoice.id}`); }}>
                        <ArrowRight className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
