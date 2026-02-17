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
} from "lucide-react";

const PAYMENT_METHODS = ["Cash", "BankTransfer", "Card", "Check", "Other"];

export default function PaymentsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const directionParam = searchParams.get("direction") || "";
  const accountParam = searchParams.get("accountId") || "";
  const invoiceParam = searchParams.get("invoice_id") || "";

  const [payments, setPayments] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [search, setSearch] = useState("");
  const [directionFilter, setDirectionFilter] = useState(directionParam);
  const [accountFilter, setAccountFilter] = useState(accountParam);

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
  const [selectedPayment, setSelectedPayment] = useState(null);
  const [allocations, setAllocations] = useState([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (directionFilter) params.append("direction", directionFilter);
      if (accountFilter) params.append("account_id", accountFilter);

      const [paymentsRes, accountsRes, invoicesRes] = await Promise.all([
        API.get(`/finance/payments?${params.toString()}`),
        API.get("/finance/accounts"),
        API.get("/finance/invoices"),
      ]);
      setPayments(paymentsRes.data);
      setAccounts(accountsRes.data);
      setInvoices(invoicesRes.data);

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

  const filteredPayments = search
    ? payments.filter(p =>
        p.reference?.toLowerCase().includes(search.toLowerCase()) ||
        p.counterparty_name?.toLowerCase().includes(search.toLowerCase()) ||
        p.account_name?.toLowerCase().includes(search.toLowerCase())
      )
    : payments;

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
          <Button onClick={openCreateDialog} data-testid="create-payment-btn">
            <Plus className="w-4 h-4 mr-2" /> {t("finance.recordPayment")}
          </Button>
        )}
      </div>

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
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.accounts")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("finance.counterparty")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("payroll.paymentMethod")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("payroll.reference")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.amount")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("finance.allocated")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredPayments.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-12 text-muted-foreground">
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
                  <TableRow key={payment.id} className="table-row-hover" data-testid={`payment-row-${payment.id}`}>
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
                    <TableCell className="text-foreground">{payment.account_name}</TableCell>
                    <TableCell className="text-muted-foreground max-w-[150px] truncate">
                      {payment.counterparty_name || "-"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{t(`finance.paymentMethod.${getMethodKey(payment.method)}`)}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {payment.reference || "-"}
                    </TableCell>
                    <TableCell className="text-right font-mono font-medium text-foreground">
                      {formatCurrency(payment.amount, payment.currency)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="text-xs">
                        <span className={payment.unallocated_amount > 0 ? "text-amber-400" : "text-emerald-400"}>
                          {formatCurrency(payment.allocated_amount, payment.currency)}
                        </span>
                        {payment.unallocated_amount > 0 && (
                          <p className="text-muted-foreground">
                            {formatCurrency(payment.unallocated_amount, payment.currency)} {t("common.free")}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {canManage && payment.unallocated_amount > 0 && (
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
                    <SelectItem value="USD">USD</SelectItem>
                    <SelectItem value="BGN">BGN</SelectItem>
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
                <Label>{t("payroll.paymentMethod")}</Label>
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
              <Input
                value={formData.counterparty_name}
                onChange={(e) => setFormData({ ...formData, counterparty_name: e.target.value })}
                placeholder={t("finance.companyName")}
                className="bg-background"
              />
            </div>
            <div className="space-y-2">
              <Label>{t("payroll.reference")}</Label>
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
    </div>
  );
}
