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
  DollarSign,
  Loader2,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";

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

  // Payment
  const [payDialog, setPayDialog] = useState(null); // invoice object
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState("BankTransfer");
  const [payRef, setPayRef] = useState("");
  const [payNote, setPayNote] = useState("");
  const [paying, setPaying] = useState(false);
  const [accounts, setAccounts] = useState([]);
  const [payAccount, setPayAccount] = useState("");
  // Batch
  const [selected, setSelected] = useState(new Set());

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
  useEffect(() => { API.get("/finance/accounts").then(r => setAccounts(r.data || [])).catch(() => {}); }, []);

  const handleAddPayment = async () => {
    if (!payDialog || !payAmount || parseFloat(payAmount) <= 0) return;
    setPaying(true);
    try {
      const amt = parseFloat(payAmount);
      const remaining = (payDialog.total || 0) - (payDialog.paid_amount || 0);
      if (amt > remaining + 0.01) { toast.error("Сумата надхвърля остатъка"); setPaying(false); return; }
      await API.post(`/finance/invoices/${payDialog.id}/payments`, {
        amount: amt,
        payment_date: new Date().toISOString().slice(0, 10),
        payment_method: payMethod,
        reference: payRef,
        notes: payNote,
        account_id: payAccount || undefined,
      });
      toast.success(`Плащане ${amt.toFixed(2)} EUR записано`);
      setPayDialog(null); setPayAmount(""); setPayRef(""); setPayNote("");
      fetchData();
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
    finally { setPaying(false); }
  };

  const handleBatchPay = async () => {
    const sel = invoices.filter(i => selected.has(i.id) && i.remaining_amount > 0);
    if (sel.length === 0) return;
    setPaying(true);
    try {
      let count = 0;
      for (const inv of sel) {
        await API.post(`/finance/invoices/${inv.id}/payments`, {
          amount: inv.remaining_amount,
          payment_date: new Date().toISOString().slice(0, 10),
          payment_method: payMethod,
          reference: payRef,
          notes: payNote || `Групово плащане (${sel.length} фактури)`,
          account_id: payAccount || undefined,
        });
        count++;
      }
      toast.success(`${count} фактури маркирани като платени`);
      setSelected(new Set()); setPayRef(""); setPayNote("");
      fetchData();
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
    finally { setPaying(false); }
  };

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
      {/* Batch action bar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 mb-3 px-3 py-2 rounded-lg bg-primary/10 border border-primary/30">
          <span className="text-xs">{selected.size} избрани</span>
          <Select value={payMethod} onValueChange={setPayMethod}>
            <SelectTrigger className="h-7 w-[130px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="BankTransfer">Банков превод</SelectItem>
              <SelectItem value="Cash">В брой</SelectItem>
              <SelectItem value="Card">Карта</SelectItem>
            </SelectContent>
          </Select>
          <Input value={payRef} onChange={e => setPayRef(e.target.value)} placeholder="Реф." className="h-7 w-[120px] text-xs" />
          <Button size="sm" className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700 gap-1" onClick={handleBatchPay} disabled={paying}>
            {paying ? <Loader2 className="w-3 h-3 animate-spin" /> : <DollarSign className="w-3 h-3" />}
            Плати пълно ({selected.size})
          </Button>
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setSelected(new Set())}>Изчисти</Button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="invoices-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[30px]"><input type="checkbox" checked={selected.size === invoices.filter(i => i.remaining_amount > 0).length && selected.size > 0} onChange={e => { if (e.target.checked) setSelected(new Set(invoices.filter(i => i.remaining_amount > 0).map(i => i.id))); else setSelected(new Set()); }} className="rounded" /></TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.invoiceNo")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.type")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.counterparty")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("offers.project")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.status")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.issueDate")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.dueDate")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.total")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Платено</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("finance.remainingAmount")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right w-[100px]">Действие</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredInvoices.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={12} className="text-center py-12 text-muted-foreground">
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
                    <TableCell onClick={e => e.stopPropagation()}>
                      {invoice.remaining_amount > 0 && <input type="checkbox" checked={selected.has(invoice.id)} onChange={() => { const s = new Set(selected); if (s.has(invoice.id)) s.delete(invoice.id); else s.add(invoice.id); setSelected(s); }} className="rounded" />}
                    </TableCell>
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
                    <TableCell className={`text-right font-mono text-sm ${(invoice.paid_amount || 0) > 0 ? "text-emerald-400" : "text-muted-foreground"}`}>
                      {(invoice.paid_amount || 0) > 0 ? formatCurrency(invoice.paid_amount, invoice.currency) : "—"}
                    </TableCell>
                    <TableCell className={`text-right font-mono text-sm ${invoice.remaining_amount > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                      {invoice.remaining_amount > 0 ? formatCurrency(invoice.remaining_amount, invoice.currency) : "✓ 0"}
                    </TableCell>
                    <TableCell className="text-right" onClick={e => e.stopPropagation()}>
                      <div className="flex gap-1 justify-end">
                        {invoice.remaining_amount > 0 && (
                          <Button variant="outline" size="sm" className="h-7 text-[10px] gap-1 text-emerald-400 border-emerald-500/30" onClick={() => { setPayDialog(invoice); setPayAmount(String(invoice.remaining_amount)); }}>
                            <DollarSign className="w-3 h-3" />Плати
                          </Button>
                        )}
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => navigate(`/finance/invoices/${invoice.id}`)}>
                          <ArrowRight className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Payment dialog */}
      <Dialog open={!!payDialog} onOpenChange={() => setPayDialog(null)}>
        <DialogContent className="max-w-sm" data-testid="pay-dialog">
          <DialogHeader><DialogTitle>Плащане по {payDialog?.invoice_no}</DialogTitle></DialogHeader>
          {payDialog && (
            <div className="space-y-3">
              <div className="text-xs text-muted-foreground">
                Обща сума: <strong>{formatCurrency(payDialog.total, payDialog.currency)}</strong> | Платено: {formatCurrency(payDialog.paid_amount, payDialog.currency)} | Остава: <strong className="text-amber-400">{formatCurrency(payDialog.remaining_amount, payDialog.currency)}</strong>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Сума *</label>
                <Input type="number" value={payAmount} onChange={e => setPayAmount(e.target.value)} className="h-9" max={payDialog.remaining_amount} />
                {parseFloat(payAmount) > payDialog.remaining_amount && <p className="text-[9px] text-red-400 mt-0.5">Сумата надхвърля остатъка</p>}
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Метод</label>
                <Select value={payMethod} onValueChange={setPayMethod}>
                  <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="BankTransfer">Банков превод</SelectItem>
                    <SelectItem value="Cash">В брой</SelectItem>
                    <SelectItem value="Card">Карта</SelectItem>
                    <SelectItem value="Other">Друго</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Референция</label>
                <Input value={payRef} onChange={e => setPayRef(e.target.value)} placeholder="Номер на превод..." className="h-9" />
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Бележка</label>
                <Input value={payNote} onChange={e => setPayNote(e.target.value)} placeholder="Бележка..." className="h-9" />
              </div>
              <Button onClick={handleAddPayment} disabled={paying || !payAmount || parseFloat(payAmount) <= 0 || parseFloat(payAmount) > payDialog.remaining_amount} className="w-full gap-1.5 bg-emerald-600 hover:bg-emerald-700">
                {paying ? <Loader2 className="w-4 h-4 animate-spin" /> : <DollarSign className="w-4 h-4" />}
                Запиши плащане
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
