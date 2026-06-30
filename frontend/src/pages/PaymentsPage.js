import { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
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
  CreditCard,
  Plus,
  Search,
  Filter,
  TrendingUp,
  TrendingDown,
  Loader2,
  Link2,
  Trash2,
  FileText,
  Building2,
} from "lucide-react";
import SmartAutocomplete from "@/components/common/SmartAutocomplete";

const PAYMENT_METHODS = ["Cash", "BankTransfer", "Card", "Check", "Other"];

function EmpAvatar({ name, url, size = 22 }) {
  const fullUrl = url ? (url.startsWith("http") ? url : `${process.env.REACT_APP_BACKEND_URL}${url}`) : null;
  const [imgErr, setImgErr] = useState(false);
  const initials = (name || "?").split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
  if (fullUrl && !imgErr) {
    return <img src={fullUrl} alt={name} className="rounded-full object-cover shrink-0" style={{ width: size, height: size }} onError={() => setImgErr(true)} />;
  }
  return (
    <div className="rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold shrink-0" style={{ width: size, height: size, fontSize: size * 0.4 }}>
      {initials}
    </div>
  );
}

const empLabel = (e) => e ? (e.name || [e.first_name, e.last_name].filter(Boolean).join(" ") || e.email) : "";

export default function PaymentsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const directionParam = searchParams.get("direction") || "";
  const accountParam = searchParams.get("accountId") || "";
  const invoiceParam = searchParams.get("invoice_id") || "";

  const [payments, setPayments] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [projects, setProjects] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [allClients, setAllClients] = useState([]);
  const [saving, setSaving] = useState(false);

  const [search, setSearch] = useState("");
  const [directionFilter, setDirectionFilter] = useState(directionParam);
  const [accountFilter, setAccountFilter] = useState(accountParam);
  const [typeFilter, setTypeFilter] = useState("");

  const canManage = ["Admin", "Owner", "Accountant"].includes(user?.role);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [formData, setFormData] = useState({
    direction: "Inflow",
    amount: "",
    currency: "EUR",
    date: new Date().toISOString().split("T")[0],
    method: "BankTransfer",
    account_id: "",
    counterparty_name: "",
    reference: "",
    note: "",
  });

  const [allocDialogOpen, setAllocDialogOpen] = useState(false);
  const [otherOpen, setOtherOpen] = useState(false);
  const [otherForm, setOtherForm] = useState({ project_id: "", amount: "", account_id: "", method: "Cash", counterparty_name: "", date: "", note: "" });
  const [incomeOpen, setIncomeOpen] = useState(false);
  const [incomeForm, setIncomeForm] = useState({ project_id: "", amount: "", account_id: "", method: "Cash", counterparty_name: "", date: "", note: "" });
  const [selectedPayment, setSelectedPayment] = useState(null);
  const [allocations, setAllocations] = useState([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (directionFilter) params.append("direction", directionFilter);
      if (accountFilter) params.append("account_id", accountFilter);

      const [paymentsRes, accountsRes, invoicesRes, clientsRes, projectsRes, employeesRes] = await Promise.all([
        API.get(`/finance/payments?${params.toString()}`),
        API.get("/finance/accounts"),
        API.get("/finance/invoices"),
        API.get("/clients?page_size=100"),
        API.get("/projects"),
        API.get("/employees"),
      ]);
      setPayments(paymentsRes.data);
      setEmployees(employeesRes.data || []);
      setAccounts(accountsRes.data);
      setInvoices(invoicesRes.data);
      setProjects(Array.isArray(projectsRes.data) ? projectsRes.data : (projectsRes.data?.items || []));
      setAllClients((clientsRes.data?.items || clientsRes.data || []).map(c => ({ id: c.id, name: c.companyName || c.fullName || c.name || "", eik: c.eik || "" })));

      if (invoiceParam) {
        const inv = invoicesRes.data.find(i => i.id === invoiceParam);
        if (inv) {
          setFormData({
            direction: inv.direction === "Issued" ? "Inflow" : "Outflow",
            amount: inv.remaining_amount || "",
            currency: inv.currency || "EUR",
            date: new Date().toISOString().split("T")[0],
            method: "BankTransfer",
            account_id: accountsRes.data[0]?.id || "",
            counterparty_name: inv.counterparty_name || "",
            reference: "",
            note: t("finance.paymentFor", { invoiceNo: inv.invoice_no }),
          });
          setDialogOpen(true);
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [directionFilter, accountFilter, invoiceParam, t]);

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
    if (key === "accountId") setAccountFilter(value === "all" ? "" : value);
  };

  const filteredPayments = payments.filter((p) => {
    if (typeFilter === "rezhiyni" && p.category !== "Други") return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        p.reference?.toLowerCase().includes(q) ||
        p.counterparty_name?.toLowerCase().includes(q) ||
        p.account_name?.toLowerCase().includes(q) ||
        p.note?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const openCreateDialog = () => {
    setFormData({
      direction: "Inflow",
      amount: "",
      currency: "EUR",
      date: new Date().toISOString().split("T")[0],
      method: "BankTransfer",
      account_id: accounts[0]?.id || "",
      counterparty_name: "",
      reference: "",
      note: "",
    });
    setDialogOpen(true);
  };

  const handleSavePayment = async () => {
    if (!formData.amount || parseFloat(formData.amount) <= 0) {
      alert(t("validation.positiveNumber"));
      return;
    }
    if (!formData.account_id) {
      alert(t("validation.required"));
      return;
    }
    setSaving(true);
    try {
      await API.post("/finance/payments", {
        ...formData,
        amount: parseFloat(formData.amount),
      });
      setDialogOpen(false);
      const newParams = new URLSearchParams(searchParams);
      newParams.delete("invoice_id");
      setSearchParams(newParams);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.createFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleDeletePayment = async (payment) => {
    if (!window.confirm(t("finance.confirmDeletePayment"))) return;
    try {
      await API.delete(`/finance/payments/${payment.id}`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.deleteFailed"));
    }
  };

  const openAllocDialog = async (payment) => {
    setSelectedPayment(payment);
    try {
      const res = await API.get(`/finance/payments/${payment.id}`);
      setSelectedPayment(res.data);
      setAllocations([]);
      setAllocDialogOpen(true);
    } catch (err) {
      alert(t("toast.errorOccurred"));
    }
  };

  const handleAllocate = async () => {
    if (allocations.length === 0) {
      alert(t("validation.required"));
      return;
    }
    const validAllocations = allocations.filter(a => a.amount > 0);
    if (validAllocations.length === 0) {
      alert(t("validation.required"));
      return;
    }
    setSaving(true);
    try {
      await API.post(`/finance/payments/${selectedPayment.id}/allocate`, {
        allocations: validAllocations.map(a => ({
          invoice_id: a.invoice_id,
          amount: parseFloat(a.amount),
        })),
      });
      setAllocDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.allocateFailed"));
    } finally {
      setSaving(false);
    }
  };

  const addAllocation = () => {
    setAllocations([...allocations, { invoice_id: "", amount: "" }]);
  };

  const updateAllocation = (idx, field, value) => {
    const updated = [...allocations];
    updated[idx] = { ...updated[idx], [field]: value };
    setAllocations(updated);
  };

  const removeAllocation = (idx) => {
    setAllocations(allocations.filter((_, i) => i !== idx));
  };

  const allocatableInvoices = selectedPayment 
    ? invoices.filter(inv => {
        const expectedDir = selectedPayment.direction === "Inflow" ? "Issued" : "Received";
        return inv.direction === expectedDir && 
               inv.status !== "Draft" && 
               inv.status !== "Cancelled" && 
               inv.remaining_amount > 0;
      })
    : [];

  const getMethodKey = (method) => {
    const map = { Cash: "cash", BankTransfer: "bankTransfer", Card: "card", Check: "check", Other: "other" };
    return map[method] || method.toLowerCase();
  };

  // Transfer/Funding are created from the accounts "Движение" dialog and have no i18n key.
  const methodLabel = (method) => {
    if (method === "Transfer") return "Прехвърляне";
    if (method === "Funding") return "Захранване";
    return t(`finance.paymentMethod.${getMethodKey(method)}`);
  };

  // "Друг разход" entries are overhead (режийни) expenses of subtype "Други",
  // booked to a project — not invoice payments, so they are not allocatable.
  const isOther = (p) => p.category === "Други";
  const projectName = (id) => {
    const p = projects.find((x) => x.id === id);
    return p ? (p.name || p.code || id) : id;
  };
  const hasInvoice = (p) => p.linked_invoices && p.linked_invoices.length > 0;
  const empById = (id) => (id ? employees.find((e) => e.id === id) : null);
  const isMovement = (p) => p.method === "Transfer" || p.method === "Funding" || p.is_funding;

  const openOther = () => {
    setOtherForm({ project_id: "", amount: "", account_id: accounts[0]?.id || "", method: "Cash", counterparty_name: "", date: new Date().toISOString().split("T")[0], note: "" });
    setOtherOpen(true);
  };

  const handleOther = async () => {
    if (!otherForm.project_id) { alert("Изберете обект"); return; }
    const amt = parseFloat(otherForm.amount);
    if (!amt || amt <= 0) { alert("Сумата трябва да е положителна"); return; }
    setSaving(true);
    try {
      await API.post("/finance/other-expense", {
        project_id: otherForm.project_id,
        amount: amt,
        account_id: otherForm.account_id,
        method: otherForm.method,
        counterparty_name: otherForm.counterparty_name,
        date: otherForm.date,
        note: otherForm.note,
      });
      setOtherOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const openIncome = () => {
    setIncomeForm({ project_id: "", amount: "", account_id: accounts[0]?.id || "", method: "Cash", counterparty_name: "", date: new Date().toISOString().split("T")[0], note: "" });
    setIncomeOpen(true);
  };

  const handleIncome = async () => {
    const amt = parseFloat(incomeForm.amount);
    if (!amt || amt <= 0) { alert("Сумата трябва да е положителна"); return; }
    setSaving(true);
    try {
      await API.post("/finance/other-income", {
        project_id: incomeForm.project_id || null,
        amount: amt,
        account_id: incomeForm.account_id,
        method: incomeForm.method,
        counterparty_name: incomeForm.counterparty_name,
        date: incomeForm.date,
        note: incomeForm.note,
      });
      setIncomeOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-8 max-w-[1400px]" data-testid="payments-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/finance")} data-testid="back-btn">
            <ArrowLeft className="w-4 h-4 mr-1" /> {t("common.back")}
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-foreground">{t("finance.payments")}</h1>
            <p className="text-sm text-muted-foreground mt-1">{t("finance.paymentsSubtitle")}</p>
          </div>
        </div>
        {canManage && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={openIncome} data-testid="other-income-btn">
              <Plus className="w-4 h-4 mr-2" /> Друг приход
            </Button>
            <Button variant="outline" onClick={openOther} data-testid="other-expense-btn">
              <Plus className="w-4 h-4 mr-2" /> Друг разход
            </Button>
            <Button onClick={openCreateDialog} data-testid="create-payment-btn">
              <Plus className="w-4 h-4 mr-2" /> {t("finance.recordPayment")}
            </Button>
          </div>
        )}
      </div>

      {/* Каса / Банка / Общо */}
      {accounts.length > 0 && (
        <div className="grid grid-cols-3 gap-3 mb-6">
          <button
            onClick={() => updateFilter("accountId", "all")}
            className={`text-left rounded-lg border p-3 transition-colors ${!accountFilter ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted/40"}`}
            data-testid="acct-summary-all"
          >
            <div className="text-xs text-muted-foreground">Общо</div>
            <div className="text-lg font-bold text-foreground">{accounts.reduce((s, a) => s + (a.current_balance || 0), 0).toFixed(2)} €</div>
          </button>
          {accounts.map((a) => (
            <button
              key={a.id}
              onClick={() => updateFilter("accountId", a.id)}
              className={`text-left rounded-lg border p-3 transition-colors ${accountFilter === a.id ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted/40"}`}
              data-testid={`acct-summary-${a.id}`}
            >
              <div className="text-xs text-muted-foreground">{a.type === "Cash" ? "КАСА" : a.type === "Bank" ? "БАНКА" : (a.name || "Сметка")}</div>
              <div className="text-lg font-bold text-foreground">{(a.current_balance || 0).toFixed(2)} €</div>
            </button>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6 flex-wrap" data-testid="payment-filters">
        <div className="relative flex-1 min-w-[200px] max-w-[300px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder={t("finance.searchPayments")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-card"
            data-testid="search-input"
          />
        </div>
        <Select value={directionFilter || "all"} onValueChange={(v) => updateFilter("direction", v)}>
          <SelectTrigger className="w-[150px] bg-card" data-testid="direction-filter">
            <Filter className="w-4 h-4 mr-2 text-muted-foreground" />
            <SelectValue placeholder={t("common.all")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allDirections")}</SelectItem>
            <SelectItem value="Inflow">{t("finance.inflows")} ({t("finance.inflow")})</SelectItem>
            <SelectItem value="Outflow">{t("finance.outflows")} ({t("finance.outflow")})</SelectItem>
          </SelectContent>
        </Select>
        <Select value={accountFilter || "all"} onValueChange={(v) => updateFilter("accountId", v)}>
          <SelectTrigger className="w-[180px] bg-card" data-testid="account-filter">
            <SelectValue placeholder={t("common.allAccounts")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allAccounts")}</SelectItem>
            {accounts.map((acc) => (
              <SelectItem key={acc.id} value={acc.id}>{acc.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={typeFilter || "all"} onValueChange={(v) => setTypeFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[150px] bg-card" data-testid="type-filter">
            <SelectValue placeholder="Всички видове" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Всички видове</SelectItem>
            <SelectItem value="rezhiyni">Режийни</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="payments-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.date")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.direction")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Вид</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">За какво</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Сметка · Метод</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.amount")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredPayments.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    <CreditCard className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>{t("finance.noPayments")}</p>
                    {canManage && (
                      <Button variant="outline" className="mt-4" onClick={openCreateDialog}>
                        {t("finance.createFirstPayment")}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                filteredPayments.map((payment) => (
                  <TableRow key={payment.id} className={`table-row-hover ${isOther(payment) ? "bg-amber-500/5" : ""}`} data-testid={`payment-row-${payment.id}`}>
                    <TableCell className="text-sm text-foreground">
                      {formatDate(payment.date)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={
                        payment.direction === "Inflow"
                          ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                          : "bg-red-500/20 text-red-400 border-red-500/30"
                      }>
                        <span className="flex items-center gap-1">
                          {payment.direction === "Inflow" ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                          {payment.direction === "Inflow" ? t("finance.inflow") : t("finance.outflow")}
                        </span>
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {isOther(payment) ? (
                        <span className="text-[10px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/30 font-medium whitespace-nowrap">Режийни</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="max-w-[280px]">
                      {empById(payment.user_id) ? (
                        <div className="flex items-center gap-2 min-w-0">
                          <EmpAvatar name={empLabel(empById(payment.user_id))} url={empById(payment.user_id).avatar_url} />
                          <div className="min-w-0">
                            <div className="text-foreground truncate">{empLabel(empById(payment.user_id))}</div>
                            <div className="text-[10px] text-muted-foreground/70 truncate">{payment.category || payment.note || ""}</div>
                          </div>
                        </div>
                      ) : isOther(payment) ? (
                        <div>
                          <div className="text-foreground truncate">{payment.note || "Друг разход"}</div>
                          <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">обект: {projectName(payment.project_id)}{payment.counterparty_name ? ` · ${payment.counterparty_name}` : ""}</div>
                        </div>
                      ) : hasInvoice(payment) ? (
                        <div className="truncate">
                          <span className="text-foreground">Фактура {payment.linked_invoices[0].invoice_no}</span>
                          {payment.linked_invoices[0].counterparty_name && (
                            <span className="text-muted-foreground"> · {payment.linked_invoices[0].counterparty_name}</span>
                          )}
                          {payment.linked_invoices.length > 1 && (
                            <span className="text-muted-foreground"> +{payment.linked_invoices.length - 1}</span>
                          )}
                        </div>
                      ) : payment.method === "Transfer" ? (
                        <span className="text-foreground truncate block">{payment.counterparty_name || "Прехвърляне"}</span>
                      ) : (payment.method === "Funding" || payment.is_funding) ? (
                        <span className="text-foreground">Захранване на каса</span>
                      ) : (
                        <span className="text-muted-foreground truncate block">{payment.note || payment.counterparty_name || "—"}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm whitespace-nowrap">
                      {payment.account_name} · {methodLabel(payment.method)}
                    </TableCell>
                    <TableCell className="text-right font-mono font-medium text-foreground">
                      {formatCurrency(payment.amount, payment.currency)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {hasInvoice(payment) && (
                          <Button variant="ghost" size="sm" onClick={() => navigate(`/finance/invoices/${payment.linked_invoices[0].id}`)} title="Отвори фактурата" data-testid={`open-doc-btn-${payment.id}`}>
                            <FileText className="w-4 h-4" />
                          </Button>
                        )}
                        {isOther(payment) && payment.project_id && (
                          <Button variant="ghost" size="sm" onClick={() => navigate(`/projects/${payment.project_id}`)} title="Отвори обекта" data-testid={`open-project-btn-${payment.id}`}>
                            <Building2 className="w-4 h-4" />
                          </Button>
                        )}
                        {canManage && payment.unallocated_amount > 0 && !isOther(payment) && !isMovement(payment) && !hasInvoice(payment) && (
                          <Button variant="ghost" size="sm" onClick={() => openAllocDialog(payment)} data-testid={`allocate-btn-${payment.id}`}>
                            <Link2 className="w-4 h-4" />
                          </Button>
                        )}
                        {canManage && payment.allocation_count === 0 && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive hover:text-destructive"
                            onClick={() => handleDeletePayment(payment)}
                            data-testid={`delete-btn-${payment.id}`}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create Payment Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[450px] bg-card border-border" data-testid="payment-dialog">
          <DialogHeader>
            <DialogTitle>{t("finance.recordPayment")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("finance.direction")} *</Label>
                <Select value={formData.direction} onValueChange={(v) => setFormData({ ...formData, direction: v })}>
                  <SelectTrigger className="bg-background" data-testid="payment-direction-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Inflow">{t("finance.moneyIn")}</SelectItem>
                    <SelectItem value="Outflow">{t("finance.moneyOut")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("finance.accounts")} *</Label>
                <Select value={formData.account_id} onValueChange={(v) => setFormData({ ...formData, account_id: v })}>
                  <SelectTrigger className="bg-background" data-testid="payment-account-select">
                    <SelectValue placeholder={t("common.select")} />
                  </SelectTrigger>
                  <SelectContent>
                    {accounts.map((acc) => (
                      <SelectItem key={acc.id} value={acc.id}>{acc.name} ({t(`finance.accountType.${acc.type.toLowerCase()}`)})</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("common.amount")} *</Label>
                <Input
                  type="number"
                  step="0.01"
                  value={formData.amount}
                  onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                  placeholder="0.00"
                  className="bg-background"
                  data-testid="payment-amount-input"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("common.currency")}</Label>
                <Select value={formData.currency} onValueChange={(v) => setFormData({ ...formData, currency: v })}>
                  <SelectTrigger className="bg-background">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="EUR">EUR</SelectItem>
                    <SelectItem value="GBP">GBP</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("common.date")} *</Label>
                <Input
                  type="date"
                  value={formData.date}
                  onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                  className="bg-background"
                  data-testid="payment-date-input"
                />
              </div>
              <div className="space-y-2">
                <Label>Метод</Label>
                <Select value={formData.method} onValueChange={(v) => setFormData({ ...formData, method: v })}>
                  <SelectTrigger className="bg-background">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PAYMENT_METHODS.map((m) => <SelectItem key={m} value={m}>{t(`finance.paymentMethod.${getMethodKey(m)}`)}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("finance.counterparty")}</Label>
              <SmartAutocomplete
                items={allClients}
                searchFields={["name", "eik"]}
                displayField="name"
                value={formData.counterparty_name}
                onChange={(v) => setFormData({ ...formData, counterparty_name: v })}
                onSelect={(c) => { if (c) setFormData({ ...formData, counterparty_name: c.name }); }}
                placeholder={t("finance.companyName")}
              />
            </div>
            <div className="space-y-2">
              <Label>Референция</Label>
              <Input
                value={formData.reference}
                onChange={(e) => setFormData({ ...formData, reference: e.target.value })}
                placeholder="PMT-001"
                className="bg-background font-mono"
              />
            </div>
            <div className="space-y-2">
              <Label>{t("common.note")}</Label>
              <Textarea
                value={formData.note}
                onChange={(e) => setFormData({ ...formData, note: e.target.value })}
                placeholder={t("common.notes")}
                className="bg-background min-h-[60px]"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleSavePayment} disabled={saving} data-testid="save-payment-btn">
              {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {t("common.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Allocate Payment Dialog */}
      <Dialog open={allocDialogOpen} onOpenChange={setAllocDialogOpen}>
        <DialogContent className="sm:max-w-[550px] bg-card border-border" data-testid="allocate-dialog">
          <DialogHeader>
            <DialogTitle>{t("finance.allocatePayment")}</DialogTitle>
          </DialogHeader>
          {selectedPayment && (
            <div className="space-y-4 py-4">
              <div className="p-3 rounded-lg bg-muted/30">
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-muted-foreground">{t("common.amount")}</span>
                  <span className="font-mono font-medium">{formatCurrency(selectedPayment.amount, selectedPayment.currency)}</span>
                </div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-muted-foreground">{t("finance.allocated")}</span>
                  <span className="font-mono">{formatCurrency(selectedPayment.allocated_amount, selectedPayment.currency)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">{t("finance.available")}</span>
                  <span className="font-mono text-emerald-400">{formatCurrency(selectedPayment.unallocated_amount, selectedPayment.currency)}</span>
                </div>
              </div>

              {selectedPayment.allocations && selectedPayment.allocations.length > 0 && (
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">{t("finance.existingAllocations")}</Label>
                  {selectedPayment.allocations.map((alloc) => (
                    <div key={alloc.id} className="flex items-center justify-between p-2 rounded bg-muted/20 text-sm">
                      <span className="font-mono">{alloc.invoice_no}</span>
                      <span className="font-mono">{formatCurrency(alloc.amount_allocated, selectedPayment.currency)}</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs text-muted-foreground">{t("finance.newAllocations")}</Label>
                  <Button size="sm" variant="outline" onClick={addAllocation} disabled={allocatableInvoices.length === 0}>
                    <Plus className="w-3 h-3 mr-1" /> {t("finance.addAllocation")}
                  </Button>
                </div>
                {allocations.length === 0 && allocatableInvoices.length === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    {t("finance.noUnpaidInvoices")}
                  </p>
                )}
                {allocations.map((alloc, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <Select value={alloc.invoice_id} onValueChange={(v) => updateAllocation(idx, "invoice_id", v)}>
                      <SelectTrigger className="flex-1 bg-background text-sm">
                        <SelectValue placeholder={t("finance.selectInvoice")} />
                      </SelectTrigger>
                      <SelectContent>
                        {allocatableInvoices.map((inv) => (
                          <SelectItem key={inv.id} value={inv.id}>
                            {inv.invoice_no} - {t("finance.remainingLabel", { amount: formatCurrency(inv.remaining_amount, inv.currency) })}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Input
                      type="number"
                      step="0.01"
                      value={alloc.amount}
                      onChange={(e) => updateAllocation(idx, "amount", e.target.value)}
                      placeholder={t("common.amount")}
                      className="w-[100px] bg-background"
                    />
                    <Button variant="ghost" size="sm" onClick={() => removeAllocation(idx)} className="text-destructive">
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAllocDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleAllocate} disabled={saving || allocations.length === 0} data-testid="confirm-allocate-btn">
              {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {t("finance.allocatePayment")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Other income (documentless cash income — proforma / deposit, not P&L revenue) */}
      <Dialog open={incomeOpen} onOpenChange={setIncomeOpen}>
        <DialogContent className="sm:max-w-[450px] bg-card border-border" data-testid="other-income-dialog">
          <DialogHeader>
            <DialogTitle>Друг приход <span className="text-xs text-muted-foreground">· без фактура</span></DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Сума *</Label>
                <Input type="number" step="0.01" value={incomeForm.amount} onChange={(e) => setIncomeForm({ ...incomeForm, amount: e.target.value })} className="bg-background" data-testid="income-amount-input" />
              </div>
              <div>
                <Label>Към сметка</Label>
                <Select value={incomeForm.account_id} onValueChange={(v) => setIncomeForm({ ...incomeForm, account_id: v })}>
                  <SelectTrigger className="bg-background"><SelectValue placeholder="Сметка" /></SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => (<SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Метод</Label>
                <Select value={incomeForm.method} onValueChange={(v) => setIncomeForm({ ...incomeForm, method: v })}>
                  <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Cash">{t("finance.paymentMethod.cash")}</SelectItem>
                    <SelectItem value="BankTransfer">{t("finance.paymentMethod.bankTransfer")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Дата</Label>
                <Input type="date" value={incomeForm.date} onChange={(e) => setIncomeForm({ ...incomeForm, date: e.target.value })} className="bg-background" />
              </div>
            </div>
            <div>
              <Label>Обект <span className="text-xs text-muted-foreground">(по избор)</span></Label>
              <Select value={incomeForm.project_id} onValueChange={(v) => setIncomeForm({ ...incomeForm, project_id: v })}>
                <SelectTrigger className="bg-background"><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {projects.map((p) => (<SelectItem key={p.id} value={p.id}>{p.name || p.code || p.id}</SelectItem>))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>От кого (по избор)</Label>
              <Input value={incomeForm.counterparty_name} onChange={(e) => setIncomeForm({ ...incomeForm, counterparty_name: e.target.value })} placeholder="напр. клиент / име" className="bg-background" />
            </div>
            <div>
              <Label>Бележка</Label>
              <Input value={incomeForm.note} onChange={(e) => setIncomeForm({ ...incomeForm, note: e.target.value })} className="bg-background" />
            </div>
            <p className="text-xs text-muted-foreground">Влиза в Каса/Банка като приход. Не е приход в P&amp;L (той идва от фактури).</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIncomeOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleIncome} disabled={saving} data-testid="save-income-btn">
              {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Запиши приход
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Other expense (documentless cash expense booked to a project) */}
      <Dialog open={otherOpen} onOpenChange={setOtherOpen}>
        <DialogContent className="sm:max-w-[450px] bg-card border-border" data-testid="other-expense-dialog">
          <DialogHeader>
            <DialogTitle>Друг разход <span className="text-xs text-muted-foreground">· без документ</span></DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Обект *</Label>
              <Select value={otherForm.project_id} onValueChange={(v) => setOtherForm({ ...otherForm, project_id: v })}>
                <SelectTrigger className="bg-background" data-testid="other-project-select"><SelectValue placeholder="Изберете обект" /></SelectTrigger>
                <SelectContent>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name || p.code || p.id}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Сума *</Label>
                <Input type="number" step="0.01" value={otherForm.amount} onChange={(e) => setOtherForm({ ...otherForm, amount: e.target.value })} className="bg-background" data-testid="other-amount-input" />
              </div>
              <div>
                <Label>От сметка</Label>
                <Select value={otherForm.account_id} onValueChange={(v) => setOtherForm({ ...otherForm, account_id: v })}>
                  <SelectTrigger className="bg-background"><SelectValue placeholder="Сметка" /></SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => (
                      <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Метод</Label>
                <Select value={otherForm.method} onValueChange={(v) => setOtherForm({ ...otherForm, method: v })}>
                  <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Cash">{t("finance.paymentMethod.cash")}</SelectItem>
                    <SelectItem value="BankTransfer">{t("finance.paymentMethod.bankTransfer")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Дата</Label>
                <Input type="date" value={otherForm.date} onChange={(e) => setOtherForm({ ...otherForm, date: e.target.value })} className="bg-background" />
              </div>
            </div>
            <div>
              <Label>Доставчик (по избор)</Label>
              <Input value={otherForm.counterparty_name} onChange={(e) => setOtherForm({ ...otherForm, counterparty_name: e.target.value })} placeholder="напр. магазин / име" className="bg-background" />
            </div>
            <div>
              <Label>Бележка</Label>
              <Input value={otherForm.note} onChange={(e) => setOtherForm({ ...otherForm, note: e.target.value })} className="bg-background" />
            </div>
            <p className="text-xs text-muted-foreground">Излиза от Каса/Банка и се брои като разход по обекта.</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOtherOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleOther} disabled={saving} data-testid="save-other-btn">
              {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Запиши разход
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
