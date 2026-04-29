import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/i18nUtils";
import { cn } from "@/lib/utils";
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
  ArrowLeft,
  Plus,
  Trash2,
  Send,
  Save,
  Loader2,
  FileText,
  Calculator,
  X,
  CreditCard,
  SplitSquareVertical,
  CheckCircle2,
  AlertCircle,
  Banknote,
  Clock,
  CircleDollarSign,
  Download,
  ExternalLink,
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import SmartAutocomplete from "@/components/common/SmartAutocomplete";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Sent: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  PartiallyPaid: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  Paid: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Overdue: "bg-red-500/20 text-red-400 border-red-500/30",
  Cancelled: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

const STATUS_BG_LABELS = {
  Draft: "Чернова",
  Sent: "Издадена",
  PartiallyPaid: "Частично платена",
  Paid: "Платена",
  Overdue: "Просрочена",
  Cancelled: "Анулирана",
};

const UNITS = ["pcs", "m", "m2", "m3", "hours", "lot", "kg", "l"];
const PAYMENT_METHODS = ["Cash", "BankTransfer", "Card", "Check", "Other"];
const METHOD_LABELS = {
  Cash: "В брой",
  BankTransfer: "Банков превод",
  Card: "Карта",
  Check: "Чек",
  Other: "Друго",
};

export default function InvoiceEditorPage() {
  const { t } = useTranslation();
  const { invoiceId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const directionParam = searchParams.get("direction") || "Issued";
  const projectIdParam = searchParams.get("project_id") || "";

  const isNew = !invoiceId || invoiceId === "new";
  const canManage = ["Admin", "Owner", "Accountant"].includes(user?.role);

  const [invoice, setInvoice] = useState(null);
  const [projects, setProjects] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [invoicePayments, setInvoicePayments] = useState([]);
  const [allClients, setAllClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [direction, setDirection] = useState(directionParam);
  const [invoiceNo, setInvoiceNo] = useState("");
  const [projectId, setProjectId] = useState(projectIdParam);
  const [counterpartyName, setCounterpartyName] = useState("");
  const [counterpartyEik, setCounterpartyEik] = useState("");
  const [counterpartyVatNo, setCounterpartyVatNo] = useState("");
  const [counterpartyAddress, setCounterpartyAddress] = useState("");
  const [counterpartyMol, setCounterpartyMol] = useState("");
  const [counterpartyEmail, setCounterpartyEmail] = useState("");
  const [counterpartyPhone, setCounterpartyPhone] = useState("");
  const [issueDate, setIssueDate] = useState(new Date().toISOString().split("T")[0]);
  const [dueDate, setDueDate] = useState("");
  const [dueDateManuallyEdited, setDueDateManuallyEdited] = useState(false);
  const [currency, setCurrency] = useState("EUR");
  const [vatPercent, setVatPercent] = useState(20);
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState([]);
  
  // Auto-fill state
  const [clientAutoFilled, setClientAutoFilled] = useState(false);
  const [noClientWarning, setNoClientWarning] = useState(false);
  const [autoFilledFields, setAutoFilledFields] = useState([]);
  const [clientType, setClientType] = useState(null);
  
  // Payment dialog state
  const [payDialogOpen, setPayDialogOpen] = useState(false);
  const [payForm, setPayForm] = useState({
    amount: "",
    date: new Date().toISOString().split("T")[0],
    method: "BankTransfer",
    account_id: "",
    reference: "",
    note: "",
  });
  const [paySaving, setPaySaving] = useState(false);
  
  // Date validation
  const dateError = dueDate && issueDate && dueDate < issueDate 
    ? "Падежът не може да бъде преди датата на издаване" 
    : null;

  const calculateDefaultDueDate = (fromDate) => {
    const date = new Date(fromDate);
    date.setDate(date.getDate() + 30);
    return date.toISOString().split("T")[0];
  };

  const handleIssueDateChange = (newIssueDate) => {
    setIssueDate(newIssueDate);
    if (!dueDateManuallyEdited) {
      setDueDate(calculateDefaultDueDate(newIssueDate));
    }
  };

  const handleDueDateChange = (newDueDate) => {
    setDueDate(newDueDate);
    setDueDateManuallyEdited(true);
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [projectsRes, accountsRes, clientsRes] = await Promise.all([
        API.get("/projects"),
        API.get("/finance/accounts"),
        API.get("/clients?page_size=500"),
      ]);
      setProjects(projectsRes.data);
      setAccounts(accountsRes.data);
      setAllClients((clientsRes.data?.items || clientsRes.data || []).map(c => ({ id: c.id, name: c.companyName || c.fullName || c.name || "", eik: c.eik || "" })));

      if (!isNew) {
        const invoiceRes = await API.get(`/finance/invoices/${invoiceId}`);
        const inv = invoiceRes.data;
        setInvoice(inv);
        setDirection(inv.direction);
        setInvoiceNo(inv.invoice_no);
        setProjectId(inv.project_id || "");
        setCounterpartyName(inv.counterparty_name || "");
        setCounterpartyEik(inv.counterparty_eik || "");
        setCounterpartyVatNo(inv.counterparty_vat_no || "");
        setCounterpartyAddress(inv.counterparty_address || "");
        setCounterpartyMol(inv.counterparty_mol || "");
        setCounterpartyEmail(inv.counterparty_email || "");
        setCounterpartyPhone(inv.counterparty_phone || "");
        setIssueDate(inv.issue_date);
        setDueDate(inv.due_date);
        setDueDateManuallyEdited(true);
        setCurrency(inv.currency);
        setVatPercent(inv.vat_percent);
        setNotes(inv.notes || "");
        setLines(inv.lines || []);
        
        // Load invoice payments
        try {
          const payRes = await API.get(`/finance/invoices/${invoiceId}/payments`);
          setInvoicePayments(payRes.data);
        } catch { setInvoicePayments([]); }
      } else {
        const defaultDue = new Date();
        defaultDue.setDate(defaultDue.getDate() + 30);
        setDueDate(defaultDue.toISOString().split("T")[0]);
        
        try {
          const numRes = await API.get("/finance/next-invoice-number", { params: { direction: directionParam } });
          if (numRes.data.auto_numbering && numRes.data.next_number) {
            setInvoiceNo(numRes.data.next_number);
          }
        } catch (err) {
          console.error("Failed to get next invoice number:", err);
        }
        
        if (projectIdParam) {
          try {
            const dashboardRes = await API.get(`/projects/${projectIdParam}/dashboard`);
            const { client } = dashboardRes.data;
            
            if (client?.owner_data) {
              const ownerData = client.owner_data;
              const filledFields = [];
              setClientType(ownerData.type);
              
              if (ownerData.type === "company") {
                if (ownerData.name && ownerData.name.trim()) { setCounterpartyName(ownerData.name); filledFields.push("Име на фирма"); }
                if (ownerData.eik && ownerData.eik.trim()) { setCounterpartyEik(ownerData.eik); filledFields.push("ЕИК"); }
                if (ownerData.vat_number && ownerData.vat_number.trim()) { setCounterpartyVatNo(ownerData.vat_number); filledFields.push("ДДС номер"); }
                if (ownerData.address && ownerData.address.trim()) { setCounterpartyAddress(ownerData.address); filledFields.push("Адрес"); }
                if (ownerData.mol && ownerData.mol.trim()) { setCounterpartyMol(ownerData.mol); filledFields.push("МОЛ"); }
                if (ownerData.email && ownerData.email.trim()) { setCounterpartyEmail(ownerData.email); filledFields.push("Имейл"); }
                if (ownerData.phone && ownerData.phone.trim()) { setCounterpartyPhone(ownerData.phone); filledFields.push("Телефон"); }
              } else {
                const personName = `${ownerData.first_name || ""} ${ownerData.last_name || ""}`.trim();
                if (personName) { setCounterpartyName(personName); filledFields.push("Име"); }
                if (ownerData.address && ownerData.address.trim()) { setCounterpartyAddress(ownerData.address); filledFields.push("Адрес"); }
                if (ownerData.email && ownerData.email.trim()) { setCounterpartyEmail(ownerData.email); filledFields.push("Имейл"); }
                if (ownerData.phone && ownerData.phone.trim()) { setCounterpartyPhone(ownerData.phone); filledFields.push("Телефон"); }
                setCounterpartyEik("");
                setCounterpartyVatNo("");
                setCounterpartyMol("");
              }
              
              if (filledFields.length > 0) { setClientAutoFilled(true); setAutoFilledFields(filledFields); }
              else { setNoClientWarning(true); }
            } else {
              setNoClientWarning(true);
            }
          } catch (err) {
            console.error("Failed to fetch project client data:", err);
          }
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [invoiceId, isNew, projectIdParam, directionParam]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const computeLineTotals = (line) => {
    const qty = parseFloat(line.qty) || 0;
    const unitPrice = parseFloat(line.unit_price) || 0;
    return { ...line, line_total: qty * unitPrice };
  };

  const computedLines = lines.map(computeLineTotals);
  const subtotal = computedLines.reduce((sum, l) => sum + (l.line_total || 0), 0);
  const vatAmount = subtotal * (vatPercent / 100);
  const total = subtotal + vatAmount;

  const addLine = () => {
    setLines([...lines, { id: Date.now().toString(), description: "", unit: "pcs", qty: 1, unit_price: 0 }]);
  };
  const removeLine = (idx) => { setLines(lines.filter((_, i) => i !== idx)); };
  const updateLine = (idx, field, value) => {
    const updated = [...lines];
    updated[idx] = { ...updated[idx], [field]: value };
    setLines(updated);
  };

  const handleSave = async () => {
    if (!invoiceNo.trim()) { alert(t("validation.required")); return; }
    if (!issueDate || !dueDate) { alert(t("validation.required")); return; }
    if (dueDate < issueDate) { alert("Падежът не може да бъде преди датата на издаване"); return; }
    setSaving(true);
    try {
      const payload = {
        direction, invoice_no: invoiceNo, project_id: projectId || null,
        counterparty_name: counterpartyName || null, counterparty_eik: counterpartyEik || null,
        counterparty_vat_no: counterpartyVatNo || null, counterparty_address: counterpartyAddress || null,
        counterparty_mol: counterpartyMol || null, counterparty_email: counterpartyEmail || null,
        counterparty_phone: counterpartyPhone || null, issue_date: issueDate, due_date: dueDate,
        currency, vat_percent: vatPercent, notes: notes || null,
        lines: lines.map((l) => ({
          description: l.description || "", unit: l.unit || "pcs",
          qty: parseFloat(l.qty) || 0, unit_price: parseFloat(l.unit_price) || 0,
        })),
      };
      if (isNew) {
        const res = await API.post("/finance/invoices", payload);
        navigate(`/finance/invoices/${res.data.id}`, { replace: true });
      } else {
        await API.put(`/finance/invoices/${invoiceId}`, {
          invoice_no: invoiceNo, counterparty_name: counterpartyName || null,
          counterparty_eik: counterpartyEik || null, counterparty_vat_no: counterpartyVatNo || null,
          counterparty_address: counterpartyAddress || null, counterparty_mol: counterpartyMol || null,
          counterparty_email: counterpartyEmail || null, counterparty_phone: counterpartyPhone || null,
          project_id: projectId || null, issue_date: issueDate, due_date: dueDate,
          vat_percent: vatPercent, notes: notes || null,
        });
        await API.put(`/finance/invoices/${invoiceId}/lines`, {
          lines: lines.map((l) => ({
            description: l.description || "", unit: l.unit || "pcs",
            qty: parseFloat(l.qty) || 0, unit_price: parseFloat(l.unit_price) || 0,
          })),
        });
        await fetchData();
      }
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally { setSaving(false); }
  };

  const handleSend = async () => {
    if (lines.length === 0) { alert(t("finance.noLines")); return; }
    setSaving(true);
    try {
      await API.post(`/finance/invoices/${invoiceId}/send`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.sendFailed"));
    } finally { setSaving(false); }
  };

  const handleCancel = async () => {
    if (!window.confirm(t("finance.confirmCancel"))) return;
    setSaving(true);
    try {
      await API.post(`/finance/invoices/${invoiceId}/cancel`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally { setSaving(false); }
  };

  const handleDelete = async () => {
    if (!window.confirm(t("finance.confirmDeleteInvoice"))) return;
    try {
      await API.delete(`/finance/invoices/${invoiceId}`);
      navigate("/finance/invoices");
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.deleteFailed"));
    }
  };

  // Payment handlers
  const openPayDialog = () => {
    setPayForm({
      amount: invoice?.remaining_amount || "",
      date: new Date().toISOString().split("T")[0],
      method: "BankTransfer",
      account_id: accounts[0]?.id || "",
      reference: "",
      note: "",
    });
    setPayDialogOpen(true);
  };

  const handleAddPayment = async () => {
    const amount = parseFloat(payForm.amount);
    if (!amount || amount <= 0) { alert("Сумата трябва да е положителна"); return; }
    if (!payForm.account_id) { alert("Изберете сметка"); return; }
    setPaySaving(true);
    try {
      await API.post(`/finance/invoices/${invoiceId}/payments`, {
        amount,
        date: payForm.date,
        method: payForm.method,
        account_id: payForm.account_id,
        reference: payForm.reference,
        note: payForm.note,
      });
      setPayDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при записване на плащане");
    } finally { setPaySaving(false); }
  };

  const handleRemovePayment = async (allocationId) => {
    if (!window.confirm(t("finance.confirmRemovePayment"))) return;
    try {
      await API.delete(`/finance/invoices/${invoiceId}/payments/${allocationId}`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при премахване на плащане");
    }
  };

  const isDraft = !invoice || invoice.status === "Draft";
  // Allow editing: Draft, Sent, PartiallyPaid, Overdue. Not: Paid, Cancelled
  const canEdit = canManage && (!invoice || !["Paid", "Cancelled"].includes(invoice.status));
  const canSend = isDraft && !isNew && canManage;
  const canDeleteDraft = isDraft && !isNew && canManage;
  const canCancel = invoice && ["Sent", "PartiallyPaid", "Overdue"].includes(invoice.status) && canManage;
  const canPay = invoice && !["Draft", "Cancelled", "Paid"].includes(invoice.status) && canManage && (invoice.remaining_amount > 0);
  const hasProject = invoice && invoice.project_id;

  const handleDownloadPdf = async () => {
    try {
      const res = await API.get(`/finance/invoices/${invoiceId}/pdf`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `invoice_${invoice.invoice_no || invoiceId}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при генериране на PDF");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px]" data-testid="invoice-editor-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/finance/invoices")} data-testid="back-btn">
            <ArrowLeft className="w-4 h-4 mr-1" /> {t("common.back")}
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-foreground">
                {isNew ? `${t("common.new")} ${direction === "Issued" ? t("finance.invoiceType.sale") : t("finance.invoiceType.bill")}` : invoice?.invoice_no}
              </h1>
              {invoice && (
                <Badge variant="outline" className={`text-xs ${STATUS_COLORS[invoice.status] || ""}`} data-testid="invoice-status-badge">
                  {STATUS_BG_LABELS[invoice.status] || invoice.status}
                </Badge>
              )}
            </div>
            {invoice && (
              <p className="text-sm text-muted-foreground">
                {invoice.direction === "Issued" ? t("finance.issuedSales") : t("finance.receivedBills")}
                {invoice.project_code && ` • ${invoice.project_code}`}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canEdit && (
            <Button variant="outline" onClick={handleSave} disabled={saving} data-testid="save-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />}
              {t("common.save")}
            </Button>
          )}
          {canSend && (
            <Button onClick={handleSend} disabled={saving || lines.length === 0} data-testid="send-btn">
              <Send className="w-4 h-4 mr-1" /> {t("finance.send")}
            </Button>
          )}
          {hasProject && (
            <Button variant="outline" onClick={() => navigate(`/projects/${invoice.project_id}`)} data-testid="go-to-project-btn">
              <ExternalLink className="w-4 h-4 mr-1" /> Към обекта
            </Button>
          )}
          {!isNew && (
            <Button variant="outline" onClick={handleDownloadPdf} data-testid="download-pdf-btn">
              <Download className="w-4 h-4 mr-1" /> PDF
            </Button>
          )}
          {canPay && (
            <Button onClick={openPayDialog} className="bg-emerald-600 hover:bg-emerald-700" data-testid="add-payment-btn">
              <Banknote className="w-4 h-4 mr-1" /> {t("finance.addPayment")}
            </Button>
          )}
          {canCancel && (
            <Button variant="outline" className="text-red-400 border-red-500/30" onClick={handleCancel} disabled={saving} data-testid="cancel-btn">
              <X className="w-4 h-4 mr-1" /> {t("finance.cancelInvoice")}
            </Button>
          )}
          {canDeleteDraft && (
            <Button variant="destructive" size="sm" onClick={handleDelete} data-testid="delete-btn">
              <Trash2 className="w-4 h-4" />
            </Button>
          )}
          {invoice && invoice.direction === "Received" && isDraft && (
            <Button 
              variant="outline" 
              onClick={() => navigate(`/finance/invoices/${invoiceId}/lines`)} 
              data-testid="allocate-lines-btn"
              className="border-purple-500/30 text-purple-400 hover:bg-purple-500/10"
            >
              <SplitSquareVertical className="w-4 h-4 mr-1" /> Разпределение
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-3 space-y-6">
          
          {/* Auto-fill info banners */}
          {isNew && clientAutoFilled && autoFilledFields.length > 0 && (
            <Alert className="bg-emerald-500/10 border-emerald-500/30" data-testid="client-autofilled-alert">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              <AlertDescription className="text-emerald-400">
                <span className="font-medium">Автоматично попълнени полета от проекта:</span>
                <span className="ml-2 text-emerald-300/80">{autoFilledFields.join(", ")}</span>
              </AlertDescription>
            </Alert>
          )}
          {isNew && noClientWarning && (
            <Alert className="bg-amber-500/10 border-amber-500/30" data-testid="no-client-warning-alert">
              <AlertCircle className="h-4 w-4 text-amber-500" />
              <AlertDescription className="text-amber-400">
                Към проекта няма избран клиент. Попълнете клиента ръчно или изберете клиент в проекта.
              </AlertDescription>
            </Alert>
          )}
          
          {/* Basic Info */}
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" /> {t("finance.invoiceDetails")}
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>{t("common.type")} *</Label>
                <Select value={direction} onValueChange={setDirection} disabled={!isNew}>
                  <SelectTrigger className="bg-background" data-testid="direction-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Issued">{t("finance.issuedSales")}</SelectItem>
                    <SelectItem value="Received">{t("finance.receivedBills")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("finance.invoiceNo")} *</Label>
                <div className="relative">
                  <Input value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)}
                    placeholder={direction === "Issued" ? "INV-0001" : "BILL-0001"}
                    disabled={!canEdit || (isNew && invoiceNo.startsWith("INV-"))}
                    className={cn("bg-background font-mono", isNew && invoiceNo && "bg-muted/50")}
                    data-testid="invoice-no-input" />
                  {isNew && invoiceNo && (
                    <div className="absolute right-2 top-1/2 -translate-y-1/2">
                      <Badge variant="outline" className="text-[10px] bg-primary/10 text-primary border-primary/30">Авто</Badge>
                    </div>
                  )}
                </div>
                {isNew && invoiceNo && <p className="text-[10px] text-muted-foreground">Номерът е генериран автоматично</p>}
                {invoice?.status === "Paid" && <p className="text-[10px] text-amber-400">Платена фактура — само за преглед</p>}
                {invoice?.status === "Cancelled" && <p className="text-[10px] text-red-400">Анулирана фактура — само за преглед</p>}
              </div>
              <div className="space-y-2">
                <Label>{t("offers.project")}</Label>
                <Select value={projectId || "none"} onValueChange={(v) => setProjectId(v === "none" ? "" : v)} disabled={!canEdit}>
                  <SelectTrigger className="bg-background" data-testid="project-select"><SelectValue placeholder={t("common.noProject")} /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t("common.noProject")}</SelectItem>
                    {projects.map((p) => <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{direction === "Issued" ? t("finance.customer") : t("finance.supplier")}</Label>
                {canEdit ? (
                  <SmartAutocomplete
                    items={allClients}
                    searchFields={["name", "eik"]}
                    displayField="name"
                    value={counterpartyName}
                    onChange={(v) => setCounterpartyName(v)}
                    onSelect={(client) => {
                      if (client) {
                        setCounterpartyName(client.name);
                        if (client.eik) setCounterpartyEik(client.eik);
                      }
                    }}
                    placeholder={clientType === "person" ? "Търси по име..." : "Търси клиент/контрагент..."}
                  />
                ) : (
                  <Input value={counterpartyName} disabled className="bg-background" data-testid="counterparty-input" />
                )}
              </div>
              {clientType !== "person" && (
                <>
                  <div className="space-y-2">
                    <Label>ЕИК</Label>
                    <Input value={counterpartyEik} onChange={(e) => setCounterpartyEik(e.target.value)}
                      placeholder="ЕИК на фирмата" disabled={!canEdit}
                      className="bg-background font-mono placeholder:text-muted-foreground/50" data-testid="counterparty-eik-input" />
                  </div>
                  <div className="space-y-2">
                    <Label>ДДС номер</Label>
                    <Input value={counterpartyVatNo} onChange={(e) => setCounterpartyVatNo(e.target.value)}
                      placeholder="ДДС номер" disabled={!canEdit}
                      className="bg-background font-mono placeholder:text-muted-foreground/50" data-testid="counterparty-vat-input" />
                  </div>
                  <div className="space-y-2">
                    <Label>МОЛ</Label>
                    <Input value={counterpartyMol} onChange={(e) => setCounterpartyMol(e.target.value)}
                      placeholder="Материално отговорно лице" disabled={!canEdit}
                      className="bg-background placeholder:text-muted-foreground/50" data-testid="counterparty-mol-input" />
                  </div>
                </>
              )}
              <div className="space-y-2">
                <Label>Адрес</Label>
                <Input value={counterpartyAddress} onChange={(e) => setCounterpartyAddress(e.target.value)}
                  placeholder="Адрес" disabled={!canEdit}
                  className="bg-background placeholder:text-muted-foreground/50" data-testid="counterparty-address-input" />
              </div>
              <div className="space-y-2">
                <Label>Имейл</Label>
                <Input type="email" value={counterpartyEmail} onChange={(e) => setCounterpartyEmail(e.target.value)}
                  placeholder="Имейл адрес" disabled={!canEdit}
                  className="bg-background placeholder:text-muted-foreground/50" data-testid="counterparty-email-input" />
              </div>
              <div className="space-y-2">
                <Label>Телефон</Label>
                <Input value={counterpartyPhone} onChange={(e) => setCounterpartyPhone(e.target.value)}
                  placeholder="Телефон" disabled={!canEdit}
                  className="bg-background placeholder:text-muted-foreground/50" data-testid="counterparty-phone-input" />
              </div>
              <div className="space-y-2">
                <Label>{t("finance.issueDate")} *</Label>
                <Input type="date" value={issueDate} onChange={(e) => handleIssueDateChange(e.target.value)}
                  disabled={!canEdit} className="bg-background" data-testid="issue-date-input" />
              </div>
              <div className="space-y-2">
                <Label>{t("finance.dueDate")} *</Label>
                <Input type="date" value={dueDate} onChange={(e) => handleDueDateChange(e.target.value)}
                  disabled={!canEdit} min={issueDate}
                  className={cn("bg-background", dateError && "border-red-500")} data-testid="due-date-input" />
                {dateError && (
                  <p className="text-xs text-red-500 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />{dateError}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label>{t("common.currency")}</Label>
                <Select value={currency} onValueChange={setCurrency} disabled={!isNew}>
                  <SelectTrigger className="bg-background" data-testid="currency-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="EUR">EUR</SelectItem>
                    <SelectItem value="USD">USD</SelectItem>
                    <SelectItem value="BGN">BGN</SelectItem>
                    <SelectItem value="GBP">GBP</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("offers.vatPercent")}</Label>
                <Input type="number" value={vatPercent} onChange={(e) => setVatPercent(parseFloat(e.target.value) || 0)}
                  disabled={!canEdit} className="bg-background" data-testid="vat-input" />
              </div>
            </div>
          </div>

          {/* Lines Table */}
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <div className="p-4 border-b border-border flex items-center justify-between">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Calculator className="w-4 h-4 text-primary" /> {t("finance.lineItems")} ({lines.length})
              </h2>
              {canEdit && (
                <Button size="sm" onClick={addLine} data-testid="add-line-btn">
                  <Plus className="w-4 h-4 mr-1" /> {t("finance.addLine")}
                </Button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="lines-table">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium">{t("common.description")}</th>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">{t("offers.unit")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">{t("offers.qty")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[120px]">{t("finance.unitPrice")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[120px]">{t("common.total")}</th>
                    {canEdit && <th className="w-[50px]"></th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {computedLines.length === 0 ? (
                    <tr><td colSpan={canEdit ? 6 : 5} className="text-center py-8 text-muted-foreground">{t("finance.noLines")}</td></tr>
                  ) : (
                    computedLines.map((line, idx) => (
                      <tr key={line.id || idx} className="hover:bg-muted/30" data-testid={`line-row-${idx}`}>
                        <td className="p-2">
                          <Input value={line.description} onChange={(e) => updateLine(idx, "description", e.target.value)}
                            placeholder={t("finance.itemDescription")} disabled={!canEdit} className="bg-background h-9 text-sm" />
                        </td>
                        <td className="p-2">
                          <Select value={line.unit} onValueChange={(v) => updateLine(idx, "unit", v)} disabled={!canEdit}>
                            <SelectTrigger className="bg-background h-9 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              {UNITS.map((u) => <SelectItem key={u} value={u}>{t(`units.${u}`)}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="p-2">
                          <Input type="number" min="0" step="0.01" value={line.qty}
                            onChange={(e) => updateLine(idx, "qty", e.target.value)}
                            disabled={!canEdit} className="bg-background h-9 text-sm text-right font-mono" />
                        </td>
                        <td className="p-2">
                          <Input type="number" min="0" step="0.01" value={line.unit_price}
                            onChange={(e) => updateLine(idx, "unit_price", e.target.value)}
                            disabled={!canEdit} className="bg-background h-9 text-sm text-right font-mono" />
                        </td>
                        <td className="p-2 text-right font-mono font-medium text-foreground">
                          {formatCurrency(line.line_total, currency)}
                        </td>
                        {canEdit && (
                          <td className="p-2">
                            <Button variant="ghost" size="sm" onClick={() => removeLine(idx)} className="text-destructive hover:text-destructive">
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </td>
                        )}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Notes */}
          <div className="rounded-xl border border-border bg-card p-5">
            <Label className="mb-2 block">{t("common.notes")}</Label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("common.notes")}
              disabled={!canEdit} className="bg-background min-h-[80px]" data-testid="notes-textarea" />
          </div>

          {/* Payment History */}
          {!isNew && invoice && invoice.status !== "Draft" && (
            <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="payment-history-panel">
              <div className="p-4 border-b border-border flex items-center justify-between">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <CreditCard className="w-4 h-4 text-primary" /> {t("finance.paymentHistory")}
                  {invoicePayments.length > 0 && (
                    <Badge variant="outline" className="text-xs ml-1">{invoicePayments.length}</Badge>
                  )}
                </h2>
                {canPay && (
                  <Button size="sm" onClick={openPayDialog} className="bg-emerald-600 hover:bg-emerald-700" data-testid="add-payment-inline-btn">
                    <Plus className="w-4 h-4 mr-1" /> {t("finance.addPayment")}
                  </Button>
                )}
              </div>
              <div className="divide-y divide-border">
                {invoicePayments.length === 0 ? (
                  <div className="p-6 text-center text-muted-foreground" data-testid="no-payments-message">
                    <Banknote className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    <p className="text-sm">{t("finance.noPaymentsYet")}</p>
                  </div>
                ) : (
                  invoicePayments.map((pay) => (
                    <div key={pay.id} className="p-4 flex items-center justify-between hover:bg-muted/20 transition-colors" data-testid={`payment-row-${pay.id}`}>
                      <div className="flex items-center gap-4">
                        <div className="w-9 h-9 rounded-lg bg-emerald-500/15 flex items-center justify-center flex-shrink-0">
                          <CircleDollarSign className="w-4 h-4 text-emerald-400" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-foreground">
                              {formatCurrency(pay.amount, currency)}
                            </span>
                            <Badge variant="outline" className="text-[10px]">
                              {METHOD_LABELS[pay.method] || pay.method}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                            <Clock className="w-3 h-3" />
                            <span>{formatDate(pay.date)}</span>
                            {pay.account_name && <span>• {pay.account_name}</span>}
                            {pay.reference && <span>• Реф: {pay.reference}</span>}
                          </div>
                          {pay.note && <p className="text-xs text-muted-foreground/70 mt-0.5">{pay.note}</p>}
                        </div>
                      </div>
                      {canManage && invoice.status !== "Cancelled" && (
                        <Button variant="ghost" size="sm" onClick={() => handleRemovePayment(pay.id)}
                          className="text-destructive hover:text-destructive opacity-50 hover:opacity-100" data-testid={`remove-payment-${pay.id}`}>
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar - Totals & Payment Summary */}
        <div className="space-y-6">
          {/* Totals Card */}
          <div className="rounded-xl border border-border bg-card p-5 sticky top-6" data-testid="totals-card">
            <h3 className="text-sm font-semibold text-foreground mb-4">{t("offers.summary")}</h3>
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">{t("offers.subtotal")}</span>
                <span className="font-mono text-foreground">{formatCurrency(subtotal, currency)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">{t("offers.vat")} ({vatPercent}%)</span>
                <span className="font-mono text-foreground">{formatCurrency(vatAmount, currency)}</span>
              </div>
              <div className="border-t border-border pt-3 flex justify-between">
                <span className="font-semibold text-foreground">{t("common.total")}</span>
                <span className="font-mono text-lg font-bold text-primary">{formatCurrency(total, currency)}</span>
              </div>
              
              {/* Payment summary - only for non-draft invoices */}
              {invoice && invoice.status !== "Draft" && (
                <>
                  <div className="border-t border-border pt-3 space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground flex items-center gap-1.5">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                        {t("finance.paidAmount")}
                      </span>
                      <span className="font-mono text-emerald-400 font-medium">
                        {formatCurrency(invoice.paid_amount || 0, currency)}
                      </span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground flex items-center gap-1.5">
                        <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
                        {t("finance.remainingAmount")}
                      </span>
                      <span className={cn(
                        "font-mono font-medium",
                        (invoice.remaining_amount || 0) > 0 ? "text-amber-400" : "text-emerald-400"
                      )}>
                        {formatCurrency(invoice.remaining_amount || 0, currency)}
                      </span>
                    </div>
                    
                    {/* Progress bar */}
                    {invoice.total > 0 && (
                      <div className="mt-2">
                        <div className="h-2 rounded-full bg-muted overflow-hidden">
                          <div
                            className={cn(
                              "h-full rounded-full transition-all duration-500",
                              invoice.remaining_amount <= 0 ? "bg-emerald-500" : "bg-amber-500"
                            )}
                            style={{ width: `${Math.min(100, ((invoice.paid_amount || 0) / invoice.total) * 100)}%` }}
                            data-testid="payment-progress-bar"
                          />
                        </div>
                        <p className="text-[10px] text-muted-foreground mt-1 text-center">
                          {Math.round(((invoice.paid_amount || 0) / invoice.total) * 100)}% платено
                        </p>
                      </div>
                    )}
                  </div>
                  
                  {/* Quick pay button in sidebar */}
                  {canPay && (
                    <div className="pt-2">
                      <Button onClick={openPayDialog} className="w-full bg-emerald-600 hover:bg-emerald-700" size="sm" data-testid="sidebar-pay-btn">
                        <Banknote className="w-4 h-4 mr-1" />
                        {invoice.remaining_amount === invoice.total ? t("finance.fullPayment") : t("finance.addPayment")}
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Payment Dialog */}
      <Dialog open={payDialogOpen} onOpenChange={setPayDialogOpen}>
        <DialogContent className="sm:max-w-[450px] bg-card border-border" data-testid="pay-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Banknote className="w-5 h-5 text-emerald-500" />
              {t("finance.quickPayTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {/* Invoice reference */}
            <div className="p-3 rounded-lg bg-muted/30 border border-border">
              <div className="flex justify-between text-sm mb-1">
                <span className="text-muted-foreground">Фактура</span>
                <span className="font-mono font-medium">{invoice?.invoice_no}</span>
              </div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-muted-foreground">{t("common.total")}</span>
                <span className="font-mono">{formatCurrency(invoice?.total || 0, currency)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">{t("finance.remainingAmount")}</span>
                <span className="font-mono text-amber-400">{formatCurrency(invoice?.remaining_amount || 0, currency)}</span>
              </div>
            </div>
            
            {/* Amount with quick buttons */}
            <div className="space-y-2">
              <Label>{t("common.amount")} *</Label>
              <Input type="number" step="0.01" value={payForm.amount}
                onChange={(e) => setPayForm({ ...payForm, amount: e.target.value })}
                placeholder="0.00" className="bg-background font-mono text-lg" data-testid="pay-amount-input" />
              {invoice && invoice.remaining_amount > 0 && (
                <div className="flex gap-2">
                  <Button type="button" variant="outline" size="sm" className="text-xs"
                    onClick={() => setPayForm({ ...payForm, amount: invoice.remaining_amount })}
                    data-testid="pay-full-btn">
                    Пълна сума ({formatCurrency(invoice.remaining_amount, currency)})
                  </Button>
                  {invoice.remaining_amount !== invoice.total && (
                    <Button type="button" variant="outline" size="sm" className="text-xs"
                      onClick={() => setPayForm({ ...payForm, amount: Math.round(invoice.remaining_amount / 2 * 100) / 100 })}
                      data-testid="pay-half-btn">
                      50% ({formatCurrency(invoice.remaining_amount / 2, currency)})
                    </Button>
                  )}
                </div>
              )}
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("finance.paymentDate")}</Label>
                <Input type="date" value={payForm.date}
                  onChange={(e) => setPayForm({ ...payForm, date: e.target.value })}
                  className="bg-background" data-testid="pay-date-input" />
              </div>
              <div className="space-y-2">
                <Label>{t("payroll.paymentMethod")}</Label>
                <Select value={payForm.method} onValueChange={(v) => setPayForm({ ...payForm, method: v })}>
                  <SelectTrigger className="bg-background" data-testid="pay-method-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PAYMENT_METHODS.map((m) => <SelectItem key={m} value={m}>{METHOD_LABELS[m]}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            
            <div className="space-y-2">
              <Label>{t("finance.paymentAccount")} *</Label>
              <Select value={payForm.account_id} onValueChange={(v) => setPayForm({ ...payForm, account_id: v })}>
                <SelectTrigger className="bg-background" data-testid="pay-account-select"><SelectValue placeholder="Изберете сметка" /></SelectTrigger>
                <SelectContent>
                  {accounts.map((acc) => <SelectItem key={acc.id} value={acc.id}>{acc.name} ({acc.type})</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            
            <div className="space-y-2">
              <Label>{t("finance.paymentRef")}</Label>
              <Input value={payForm.reference}
                onChange={(e) => setPayForm({ ...payForm, reference: e.target.value })}
                placeholder="PMT-001" className="bg-background font-mono" data-testid="pay-reference-input" />
            </div>
            
            <div className="space-y-2">
              <Label>{t("finance.paymentNote")}</Label>
              <Textarea value={payForm.note}
                onChange={(e) => setPayForm({ ...payForm, note: e.target.value })}
                placeholder={t("common.notes")} className="bg-background min-h-[50px]" data-testid="pay-note-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPayDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleAddPayment} disabled={paySaving} className="bg-emerald-600 hover:bg-emerald-700" data-testid="confirm-pay-btn">
              {paySaving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {t("finance.addPayment")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
