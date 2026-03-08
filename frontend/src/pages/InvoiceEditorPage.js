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
  Info,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Sent: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  PartiallyPaid: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  Paid: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Overdue: "bg-red-500/20 text-red-400 border-red-500/30",
  Cancelled: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

const UNITS = ["pcs", "m", "m2", "m3", "hours", "lot", "kg", "l"];
const COST_CATEGORIES = ["Materials", "Labor", "Subcontract", "Other"];

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
  const [clientType, setClientType] = useState(null); // "company" or "person"
  
  // Date validation
  const dateError = dueDate && issueDate && dueDate < issueDate 
    ? "Падежът не може да бъде преди датата на издаване" 
    : null;

  // Helper: Calculate default due date (30 days from issue date)
  const calculateDefaultDueDate = (fromDate) => {
    const date = new Date(fromDate);
    date.setDate(date.getDate() + 30);
    return date.toISOString().split("T")[0];
  };

  // Handle issue date change with auto-update of due date
  const handleIssueDateChange = (newIssueDate) => {
    setIssueDate(newIssueDate);
    // Only auto-update due date if it wasn't manually edited
    if (!dueDateManuallyEdited) {
      setDueDate(calculateDefaultDueDate(newIssueDate));
    }
  };

  // Handle due date change (mark as manually edited)
  const handleDueDateChange = (newDueDate) => {
    setDueDate(newDueDate);
    setDueDateManuallyEdited(true);
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const projectsRes = await API.get("/projects");
      setProjects(projectsRes.data);

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
        setDueDateManuallyEdited(true); // Existing invoice - treat as manually set
        setCurrency(inv.currency);
        setVatPercent(inv.vat_percent);
        setNotes(inv.notes || "");
        setLines(inv.lines || []);
      } else {
        const defaultDue = new Date();
        defaultDue.setDate(defaultDue.getDate() + 30);
        setDueDate(defaultDue.toISOString().split("T")[0]);
        
        // Auto-fill client data from project if project_id is provided
        if (projectIdParam) {
          try {
            const dashboardRes = await API.get(`/projects/${projectIdParam}/dashboard`);
            const { client } = dashboardRes.data;
            
            if (client?.owner_data) {
              const ownerData = client.owner_data;
              const filledFields = [];
              
              // Set client type for conditional field rendering
              setClientType(ownerData.type);
              
              if (ownerData.type === "company") {
                // Company: full set of fields - only fill if data exists
                if (ownerData.name && ownerData.name.trim()) {
                  setCounterpartyName(ownerData.name);
                  filledFields.push("Име на фирма");
                }
                if (ownerData.eik && ownerData.eik.trim()) {
                  setCounterpartyEik(ownerData.eik);
                  filledFields.push("ЕИК");
                }
                if (ownerData.vat_number && ownerData.vat_number.trim()) {
                  setCounterpartyVatNo(ownerData.vat_number);
                  filledFields.push("ДДС номер");
                }
                if (ownerData.address && ownerData.address.trim()) {
                  setCounterpartyAddress(ownerData.address);
                  filledFields.push("Адрес");
                }
                if (ownerData.mol && ownerData.mol.trim()) {
                  setCounterpartyMol(ownerData.mol);
                  filledFields.push("МОЛ");
                }
                if (ownerData.email && ownerData.email.trim()) {
                  setCounterpartyEmail(ownerData.email);
                  filledFields.push("Имейл");
                }
                if (ownerData.phone && ownerData.phone.trim()) {
                  setCounterpartyPhone(ownerData.phone);
                  filledFields.push("Телефон");
                }
              } else {
                // Person: only name + contact info (NO company fields!)
                const personName = `${ownerData.first_name || ""} ${ownerData.last_name || ""}`.trim();
                if (personName) {
                  setCounterpartyName(personName);
                  filledFields.push("Име");
                }
                if (ownerData.address && ownerData.address.trim()) {
                  setCounterpartyAddress(ownerData.address);
                  filledFields.push("Адрес");
                }
                if (ownerData.email && ownerData.email.trim()) {
                  setCounterpartyEmail(ownerData.email);
                  filledFields.push("Имейл");
                }
                if (ownerData.phone && ownerData.phone.trim()) {
                  setCounterpartyPhone(ownerData.phone);
                  filledFields.push("Телефон");
                }
                // Explicitly clear company-specific fields for person clients
                setCounterpartyEik("");
                setCounterpartyVatNo("");
                setCounterpartyMol("");
              }
              
              if (filledFields.length > 0) {
                setClientAutoFilled(true);
                setAutoFilledFields(filledFields);
              } else {
                setNoClientWarning(true);
              }
            } else {
              // No client associated with project
              setNoClientWarning(true);
            }
          } catch (err) {
            console.error("Failed to fetch project client data:", err);
            // Don't show warning if API call fails - just continue normally
          }
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [invoiceId, isNew, projectIdParam]);

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
    setLines([...lines, {
      id: Date.now().toString(),
      description: "",
      unit: "pcs",
      qty: 1,
      unit_price: 0,
      project_id: projectId || null,
      cost_category: null,
      sort_order: lines.length,
    }]);
  };

  const removeLine = (idx) => {
    setLines(lines.filter((_, i) => i !== idx));
  };

  const updateLine = (idx, field, value) => {
    const updated = [...lines];
    updated[idx] = { ...updated[idx], [field]: value };
    setLines(updated);
  };

  const handleSave = async () => {
    if (!invoiceNo.trim()) {
      alert(t("validation.required"));
      return;
    }
    if (!issueDate || !dueDate) {
      alert(t("validation.required"));
      return;
    }
    // Date validation - dueDate must be >= issueDate
    if (dueDate < issueDate) {
      alert("Падежът не може да бъде преди датата на издаване");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        direction,
        invoice_no: invoiceNo,
        project_id: projectId || null,
        counterparty_name: counterpartyName || null,
        counterparty_eik: counterpartyEik || null,
        counterparty_vat_no: counterpartyVatNo || null,
        counterparty_address: counterpartyAddress || null,
        counterparty_mol: counterpartyMol || null,
        counterparty_email: counterpartyEmail || null,
        counterparty_phone: counterpartyPhone || null,
        issue_date: issueDate,
        due_date: dueDate,
        currency,
        vat_percent: vatPercent,
        notes: notes || null,
        lines: lines.map((l) => ({
          description: l.description,
          unit: l.unit,
          qty: parseFloat(l.qty) || 0,
          unit_price: parseFloat(l.unit_price) || 0,
          project_id: l.project_id || null,
          cost_category: l.cost_category || null,
        })),
      };

      if (isNew) {
        const res = await API.post("/finance/invoices", payload);
        navigate(`/finance/invoices/${res.data.id}`, { replace: true });
      } else {
        await API.put(`/finance/invoices/${invoiceId}`, {
          invoice_no: invoiceNo,
          counterparty_name: counterpartyName || null,
          counterparty_eik: counterpartyEik || null,
          counterparty_vat_no: counterpartyVatNo || null,
          counterparty_address: counterpartyAddress || null,
          counterparty_mol: counterpartyMol || null,
          counterparty_email: counterpartyEmail || null,
          counterparty_phone: counterpartyPhone || null,
          project_id: projectId || null,
          issue_date: issueDate,
          due_date: dueDate,
          vat_percent: vatPercent,
          notes: notes || null,
        });
        await API.put(`/finance/invoices/${invoiceId}/lines`, {
          lines: lines.map((l) => ({
            description: l.description,
            unit: l.unit,
            qty: parseFloat(l.qty) || 0,
            unit_price: parseFloat(l.unit_price) || 0,
            project_id: l.project_id || null,
            cost_category: l.cost_category || null,
          })),
        });
        await fetchData();
      }
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleSend = async () => {
    if (lines.length === 0) {
      alert(t("finance.noLines"));
      return;
    }
    setSaving(true);
    try {
      await API.post(`/finance/invoices/${invoiceId}/send`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.sendFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = async () => {
    if (!window.confirm(t("finance.confirmCancel"))) return;
    setSaving(true);
    try {
      await API.post(`/finance/invoices/${invoiceId}/cancel`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
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

  const getStatusKey = (status) => {
    const map = { Draft: "draft", Sent: "sent", PartiallyPaid: "partiallyPaid", Paid: "paid", Overdue: "overdue", Cancelled: "cancelled" };
    return map[status] || status.toLowerCase();
  };

  const getCostCategoryKey = (cat) => {
    if (!cat) return "none";
    return cat.toLowerCase();
  };

  const isDraft = !invoice || invoice.status === "Draft";
  const canEdit = isDraft && canManage;
  const canCancel = invoice && ["Sent", "PartiallyPaid", "Overdue"].includes(invoice.status) && canManage;

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
                <Badge variant="outline" className={`text-xs ${STATUS_COLORS[invoice.status] || ""}`}>
                  {t(`finance.status.${getStatusKey(invoice.status)}`)}
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
            <>
              <Button variant="outline" onClick={handleSave} disabled={saving} data-testid="save-btn">
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />}
                {t("common.save")}
              </Button>
              {!isNew && (
                <Button onClick={handleSend} disabled={saving || lines.length === 0} data-testid="send-btn">
                  <Send className="w-4 h-4 mr-1" /> {t("finance.send")}
                </Button>
              )}
              {!isNew && (
                <Button variant="destructive" size="sm" onClick={handleDelete} data-testid="delete-btn">
                  <Trash2 className="w-4 h-4" />
                </Button>
              )}
            </>
          )}
          {canCancel && (
            <Button variant="outline" className="text-red-400 border-red-500/30" onClick={handleCancel} disabled={saving} data-testid="cancel-btn">
              <X className="w-4 h-4 mr-1" /> {t("finance.cancelInvoice")}
            </Button>
          )}
          {invoice && invoice.status !== "Draft" && invoice.status !== "Cancelled" && invoice.remaining_amount > 0 && (
            <Button variant="outline" onClick={() => navigate(`/finance/payments/new?invoice_id=${invoice.id}`)} data-testid="record-payment-btn">
              <CreditCard className="w-4 h-4 mr-1" /> {t("finance.recordPayment")}
            </Button>
          )}
          {invoice && invoice.direction === "Received" && (
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
                <span className="ml-2 text-emerald-300/80">
                  {autoFilledFields.join(", ")}
                </span>
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
                  <SelectTrigger className="bg-background" data-testid="direction-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Issued">{t("finance.issuedSales")}</SelectItem>
                    <SelectItem value="Received">{t("finance.receivedBills")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("finance.invoiceNo")} *</Label>
                <Input
                  value={invoiceNo}
                  onChange={(e) => setInvoiceNo(e.target.value)}
                  placeholder={direction === "Issued" ? t("finance.invoiceNoPlaceholder") : t("finance.billNoPlaceholder")}
                  disabled={!canEdit}
                  className="bg-background font-mono"
                  data-testid="invoice-no-input"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("offers.project")}</Label>
                <Select value={projectId || "none"} onValueChange={(v) => setProjectId(v === "none" ? "" : v)} disabled={!canEdit}>
                  <SelectTrigger className="bg-background" data-testid="project-select">
                    <SelectValue placeholder={t("common.noProject")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t("common.noProject")}</SelectItem>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{direction === "Issued" ? t("finance.customer") : t("finance.supplier")}</Label>
                <Input
                  value={counterpartyName}
                  onChange={(e) => setCounterpartyName(e.target.value)}
                  placeholder={clientType === "person" ? "Име и фамилия" : t("finance.companyName")}
                  disabled={!canEdit}
                  className="bg-background"
                  data-testid="counterparty-input"
                />
              </div>
              
              {/* Company-specific fields - hidden for person clients */}
              {clientType !== "person" && (
                <>
                  <div className="space-y-2">
                    <Label>ЕИК</Label>
                    <Input
                      value={counterpartyEik}
                      onChange={(e) => setCounterpartyEik(e.target.value)}
                      placeholder="ЕИК на фирмата"
                      disabled={!canEdit}
                      className="bg-background font-mono placeholder:text-muted-foreground/50"
                      data-testid="counterparty-eik-input"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>ДДС номер</Label>
                    <Input
                      value={counterpartyVatNo}
                      onChange={(e) => setCounterpartyVatNo(e.target.value)}
                      placeholder="ДДС номер"
                      disabled={!canEdit}
                      className="bg-background font-mono placeholder:text-muted-foreground/50"
                      data-testid="counterparty-vat-input"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>МОЛ</Label>
                    <Input
                      value={counterpartyMol}
                      onChange={(e) => setCounterpartyMol(e.target.value)}
                      placeholder="Материално отговорно лице"
                      disabled={!canEdit}
                      className="bg-background placeholder:text-muted-foreground/50"
                      data-testid="counterparty-mol-input"
                    />
                  </div>
                </>
              )}
              <div className="space-y-2">
                <Label>Адрес</Label>
                <Input
                  value={counterpartyAddress}
                  onChange={(e) => setCounterpartyAddress(e.target.value)}
                  placeholder="Адрес"
                  disabled={!canEdit}
                  className="bg-background placeholder:text-muted-foreground/50"
                  data-testid="counterparty-address-input"
                />
              </div>
              <div className="space-y-2">
                <Label>Имейл</Label>
                <Input
                  type="email"
                  value={counterpartyEmail}
                  onChange={(e) => setCounterpartyEmail(e.target.value)}
                  placeholder="Имейл адрес"
                  disabled={!canEdit}
                  className="bg-background placeholder:text-muted-foreground/50"
                  data-testid="counterparty-email-input"
                />
              </div>
              <div className="space-y-2">
                <Label>Телефон</Label>
                <Input
                  value={counterpartyPhone}
                  onChange={(e) => setCounterpartyPhone(e.target.value)}
                  placeholder="Телефон"
                  disabled={!canEdit}
                  className="bg-background placeholder:text-muted-foreground/50"
                  data-testid="counterparty-phone-input"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("finance.issueDate")} *</Label>
                <Input
                  type="date"
                  value={issueDate}
                  onChange={(e) => handleIssueDateChange(e.target.value)}
                  disabled={!canEdit}
                  className="bg-background"
                  data-testid="issue-date-input"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("finance.dueDate")} *</Label>
                <Input
                  type="date"
                  value={dueDate}
                  onChange={(e) => handleDueDateChange(e.target.value)}
                  disabled={!canEdit}
                  min={issueDate}
                  className={cn("bg-background", dateError && "border-red-500")}
                  data-testid="due-date-input"
                />
                {dateError && (
                  <p className="text-xs text-red-500 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />
                    {dateError}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label>{t("common.currency")}</Label>
                <Select value={currency} onValueChange={setCurrency} disabled={!isNew}>
                  <SelectTrigger className="bg-background" data-testid="currency-select">
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
              <div className="space-y-2">
                <Label>{t("offers.vatPercent")}</Label>
                <Input
                  type="number"
                  value={vatPercent}
                  onChange={(e) => setVatPercent(parseFloat(e.target.value) || 0)}
                  disabled={!canEdit}
                  className="bg-background"
                  data-testid="vat-input"
                />
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
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium w-[80px]">{t("offers.unit")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[80px]">{t("offers.qty")}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">{t("finance.unitPrice")}</th>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium w-[120px]">{t("finance.costCategory.materials").split(' ')[0]}</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[110px]">{t("common.total")}</th>
                    {canEdit && <th className="w-[50px]"></th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {computedLines.length === 0 ? (
                    <tr>
                      <td colSpan={canEdit ? 7 : 6} className="text-center py-8 text-muted-foreground">
                        {t("finance.noLines")}
                      </td>
                    </tr>
                  ) : (
                    computedLines.map((line, idx) => (
                      <tr key={line.id || idx} className="hover:bg-muted/30" data-testid={`line-row-${idx}`}>
                        <td className="p-2">
                          <Input
                            value={line.description}
                            onChange={(e) => updateLine(idx, "description", e.target.value)}
                            placeholder={t("finance.itemDescription")}
                            disabled={!canEdit}
                            className="bg-background h-8 text-sm"
                          />
                        </td>
                        <td className="p-2">
                          <Select value={line.unit} onValueChange={(v) => updateLine(idx, "unit", v)} disabled={!canEdit}>
                            <SelectTrigger className="bg-background h-8 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {UNITS.map((u) => <SelectItem key={u} value={u}>{t(`units.${u}`)}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="p-2">
                          <Input
                            type="number"
                            value={line.qty}
                            onChange={(e) => updateLine(idx, "qty", e.target.value)}
                            disabled={!canEdit}
                            className="bg-background h-8 text-sm text-right"
                          />
                        </td>
                        <td className="p-2">
                          <Input
                            type="number"
                            step="0.01"
                            value={line.unit_price}
                            onChange={(e) => updateLine(idx, "unit_price", e.target.value)}
                            disabled={!canEdit}
                            className="bg-background h-8 text-sm text-right"
                          />
                        </td>
                        <td className="p-2">
                          <Select value={line.cost_category || "none"} onValueChange={(v) => updateLine(idx, "cost_category", v === "none" ? null : v)} disabled={!canEdit}>
                            <SelectTrigger className="bg-background h-8 text-xs">
                              <SelectValue placeholder="-" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">{t("finance.costCategory.none")}</SelectItem>
                              {COST_CATEGORIES.map((c) => <SelectItem key={c} value={c}>{t(`finance.costCategory.${getCostCategoryKey(c)}`)}</SelectItem>)}
                            </SelectContent>
                          </Select>
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
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t("common.notes")}
              disabled={!canEdit}
              className="bg-background min-h-[80px]"
              data-testid="notes-textarea"
            />
          </div>

          {/* Payment Allocations */}
          {invoice && invoice.allocations && invoice.allocations.length > 0 && (
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <div className="p-4 border-b border-border">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <CreditCard className="w-4 h-4 text-primary" /> {t("finance.paymentHistory")}
                </h2>
              </div>
              <div className="p-4 space-y-2">
                {invoice.allocations.map((alloc) => (
                  <div key={alloc.id} className="flex items-center justify-between p-3 rounded-lg bg-muted/30">
                    <div>
                      <p className="text-sm text-foreground">
                        {alloc.payment_reference || t("finance.payments")} • {t(`finance.paymentMethod.${alloc.payment_method?.toLowerCase()}`)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {formatDate(alloc.payment_date)}
                      </p>
                    </div>
                    <p className="font-mono text-sm font-medium text-emerald-400">
                      +{formatCurrency(alloc.amount_allocated, currency)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar - Totals */}
        <div className="space-y-6">
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
              {invoice && invoice.status !== "Draft" && (
                <>
                  <div className="border-t border-border pt-3 flex justify-between text-sm">
                    <span className="text-muted-foreground">{t("finance.paidAmount")}</span>
                    <span className="font-mono text-emerald-400">{formatCurrency(invoice.paid_amount, currency)}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">{t("finance.remainingAmount")}</span>
                    <span className={`font-mono ${invoice.remaining_amount > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                      {formatCurrency(invoice.remaining_amount, currency)}
                    </span>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
