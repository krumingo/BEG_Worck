import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
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
} from "lucide-react";

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
  const { invoiceId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const directionParam = searchParams.get("direction") || "Issued";

  const isNew = !invoiceId || invoiceId === "new";
  const canManage = ["Admin", "Owner", "Accountant"].includes(user?.role);

  const [invoice, setInvoice] = useState(null);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Form state
  const [direction, setDirection] = useState(directionParam);
  const [invoiceNo, setInvoiceNo] = useState("");
  const [projectId, setProjectId] = useState("");
  const [counterpartyName, setCounterpartyName] = useState("");
  const [issueDate, setIssueDate] = useState(new Date().toISOString().split("T")[0]);
  const [dueDate, setDueDate] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [vatPercent, setVatPercent] = useState(20);
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState([]);

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
        setIssueDate(inv.issue_date);
        setDueDate(inv.due_date);
        setCurrency(inv.currency);
        setVatPercent(inv.vat_percent);
        setNotes(inv.notes || "");
        setLines(inv.lines || []);
      } else {
        // Set default due date to 30 days from now
        const defaultDue = new Date();
        defaultDue.setDate(defaultDue.getDate() + 30);
        setDueDate(defaultDue.toISOString().split("T")[0]);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [invoiceId, isNew]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const computeLineTotals = (line) => {
    const qty = parseFloat(line.qty) || 0;
    const unitPrice = parseFloat(line.unit_price) || 0;
    return {
      ...line,
      line_total: qty * unitPrice,
    };
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
      alert("Invoice number is required");
      return;
    }
    if (!issueDate || !dueDate) {
      alert("Issue date and due date are required");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        direction,
        invoice_no: invoiceNo,
        project_id: projectId || null,
        counterparty_name: counterpartyName || null,
        issue_date: issueDate,
        due_date: dueDate,
        currency,
        vat_percent: vatPercent,
        notes: notes || null,
        lines: lines.map((l, i) => ({
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
          project_id: projectId || null,
          issue_date: issueDate,
          due_date: dueDate,
          vat_percent: vatPercent,
          notes: notes || null,
        });
        await API.put(`/finance/invoices/${invoiceId}/lines`, {
          lines: lines.map((l, i) => ({
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
      alert(err.response?.data?.detail || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleSend = async () => {
    if (lines.length === 0) {
      alert("Add at least one line before sending");
      return;
    }
    setSaving(true);
    try {
      await API.post(`/finance/invoices/${invoiceId}/send`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to send");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = async () => {
    if (!window.confirm("Are you sure you want to cancel this invoice?")) return;
    setSaving(true);
    try {
      await API.post(`/finance/invoices/${invoiceId}/cancel`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to cancel");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Delete this draft invoice? This cannot be undone.")) return;
    try {
      await API.delete(`/finance/invoices/${invoiceId}`);
      navigate("/finance/invoices");
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to delete");
    }
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "EUR" }).format(amount || 0);
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
            <ArrowLeft className="w-4 h-4 mr-1" /> Back
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-foreground">
                {isNew ? `New ${direction === "Issued" ? "Invoice" : "Bill"}` : invoice?.invoice_no}
              </h1>
              {invoice && (
                <Badge variant="outline" className={`text-xs ${STATUS_COLORS[invoice.status] || ""}`}>
                  {invoice.status}
                </Badge>
              )}
            </div>
            {invoice && (
              <p className="text-sm text-muted-foreground">
                {invoice.direction === "Issued" ? "Sales Invoice" : "Purchase Bill"}
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
                Save
              </Button>
              {!isNew && (
                <Button onClick={handleSend} disabled={saving || lines.length === 0} data-testid="send-btn">
                  <Send className="w-4 h-4 mr-1" /> Send
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
              <X className="w-4 h-4 mr-1" /> Cancel Invoice
            </Button>
          )}
          {invoice && invoice.status !== "Draft" && invoice.status !== "Cancelled" && invoice.remaining_amount > 0 && (
            <Button variant="outline" onClick={() => navigate(`/finance/payments/new?invoice_id=${invoice.id}`)} data-testid="record-payment-btn">
              <CreditCard className="w-4 h-4 mr-1" /> Record Payment
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-3 space-y-6">
          {/* Basic Info */}
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" /> Invoice Details
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>Type *</Label>
                <Select value={direction} onValueChange={setDirection} disabled={!isNew}>
                  <SelectTrigger className="bg-background" data-testid="direction-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Issued">Issued (Sale)</SelectItem>
                    <SelectItem value="Received">Received (Bill)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Invoice No. *</Label>
                <Input
                  value={invoiceNo}
                  onChange={(e) => setInvoiceNo(e.target.value)}
                  placeholder={direction === "Issued" ? "INV-0001" : "BILL-0001"}
                  disabled={!canEdit}
                  className="bg-background font-mono"
                  data-testid="invoice-no-input"
                />
              </div>
              <div className="space-y-2">
                <Label>Project</Label>
                <Select value={projectId || "none"} onValueChange={(v) => setProjectId(v === "none" ? "" : v)} disabled={!canEdit}>
                  <SelectTrigger className="bg-background" data-testid="project-select">
                    <SelectValue placeholder="No project" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">No project</SelectItem>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{direction === "Issued" ? "Customer" : "Supplier"}</Label>
                <Input
                  value={counterpartyName}
                  onChange={(e) => setCounterpartyName(e.target.value)}
                  placeholder="Company name"
                  disabled={!canEdit}
                  className="bg-background"
                  data-testid="counterparty-input"
                />
              </div>
              <div className="space-y-2">
                <Label>Issue Date *</Label>
                <Input
                  type="date"
                  value={issueDate}
                  onChange={(e) => setIssueDate(e.target.value)}
                  disabled={!canEdit}
                  className="bg-background"
                  data-testid="issue-date-input"
                />
              </div>
              <div className="space-y-2">
                <Label>Due Date *</Label>
                <Input
                  type="date"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                  disabled={!canEdit}
                  className="bg-background"
                  data-testid="due-date-input"
                />
              </div>
              <div className="space-y-2">
                <Label>Currency</Label>
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
                <Label>VAT %</Label>
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
                <Calculator className="w-4 h-4 text-primary" /> Line Items ({lines.length})
              </h2>
              {canEdit && (
                <Button size="sm" onClick={addLine} data-testid="add-line-btn">
                  <Plus className="w-4 h-4 mr-1" /> Add Line
                </Button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="lines-table">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium">Description</th>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium w-[80px]">Unit</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[80px]">Qty</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[100px]">Unit Price</th>
                    <th className="text-left p-3 text-xs uppercase text-muted-foreground font-medium w-[120px]">Category</th>
                    <th className="text-right p-3 text-xs uppercase text-muted-foreground font-medium w-[110px]">Total</th>
                    {canEdit && <th className="w-[50px]"></th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {computedLines.length === 0 ? (
                    <tr>
                      <td colSpan={canEdit ? 7 : 6} className="text-center py-8 text-muted-foreground">
                        No lines added yet
                      </td>
                    </tr>
                  ) : (
                    computedLines.map((line, idx) => (
                      <tr key={line.id || idx} className="hover:bg-muted/30" data-testid={`line-row-${idx}`}>
                        <td className="p-2">
                          <Input
                            value={line.description}
                            onChange={(e) => updateLine(idx, "description", e.target.value)}
                            placeholder="Item description"
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
                              {UNITS.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}
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
                              <SelectItem value="none">None</SelectItem>
                              {COST_CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="p-2 text-right font-mono font-medium text-foreground">
                          {formatCurrency(line.line_total)}
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
            <Label className="mb-2 block">Notes</Label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Additional notes..."
              disabled={!canEdit}
              className="bg-background min-h-[80px]"
              data-testid="notes-textarea"
            />
          </div>

          {/* Payment Allocations (for existing invoices) */}
          {invoice && invoice.allocations && invoice.allocations.length > 0 && (
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <div className="p-4 border-b border-border">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <CreditCard className="w-4 h-4 text-primary" /> Payment History
                </h2>
              </div>
              <div className="p-4 space-y-2">
                {invoice.allocations.map((alloc) => (
                  <div key={alloc.id} className="flex items-center justify-between p-3 rounded-lg bg-muted/30">
                    <div>
                      <p className="text-sm text-foreground">
                        {alloc.payment_reference || "Payment"} • {alloc.payment_method}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(alloc.payment_date).toLocaleDateString("en-GB")}
                      </p>
                    </div>
                    <p className="font-mono text-sm font-medium text-emerald-400">
                      +{formatCurrency(alloc.amount_allocated)}
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
            <h3 className="text-sm font-semibold text-foreground mb-4">Summary</h3>
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Subtotal</span>
                <span className="font-mono text-foreground">{formatCurrency(subtotal)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">VAT ({vatPercent}%)</span>
                <span className="font-mono text-foreground">{formatCurrency(vatAmount)}</span>
              </div>
              <div className="border-t border-border pt-3 flex justify-between">
                <span className="font-semibold text-foreground">Total</span>
                <span className="font-mono text-lg font-bold text-primary">{formatCurrency(total)}</span>
              </div>
              {invoice && invoice.status !== "Draft" && (
                <>
                  <div className="border-t border-border pt-3 flex justify-between text-sm">
                    <span className="text-muted-foreground">Paid</span>
                    <span className="font-mono text-emerald-400">{formatCurrency(invoice.paid_amount)}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Remaining</span>
                    <span className={`font-mono ${invoice.remaining_amount > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                      {formatCurrency(invoice.remaining_amount)}
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
