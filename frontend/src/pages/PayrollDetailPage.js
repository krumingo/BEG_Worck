import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
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
  Loader2,
  Play,
  Lock,
  CheckCircle2,
  DollarSign,
  AlertTriangle,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Finalized: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Paid: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
};

export default function PayrollDetailPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [run, setRun] = useState(null);
  const [advances, setAdvances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [warnings, setWarnings] = useState([]);

  // Payslip edit dialog
  const [payslipDialogOpen, setPayslipDialogOpen] = useState(false);
  const [selectedPayslip, setSelectedPayslip] = useState(null);
  const [deductions, setDeductions] = useState(0);
  const [selectedAdvances, setSelectedAdvances] = useState([]);
  const [savingPayslip, setSavingPayslip] = useState(false);

  // Mark paid dialog
  const [payDialogOpen, setPayDialogOpen] = useState(false);
  const [payMethod, setPayMethod] = useState("Cash");
  const [payReference, setPayReference] = useState("");
  const [paying, setPaying] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [runRes, advRes] = await Promise.all([
        API.get(`/payroll-runs/${runId}`),
        API.get("/advances?status=Open"),
      ]);
      setRun(runRes.data);
      setAdvances(advRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleGenerate = async () => {
    setGenerating(true);
    setWarnings([]);
    try {
      const res = await API.post(`/payroll-runs/${runId}/generate`);
      setWarnings(res.data.warnings || []);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to generate");
    } finally {
      setGenerating(false);
    }
  };

  const handleFinalize = async () => {
    if (!confirm("Finalize this payroll? After finalization, payslips cannot be edited.")) return;
    setFinalizing(true);
    try {
      await API.post(`/payroll-runs/${runId}/finalize`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to finalize");
    } finally {
      setFinalizing(false);
    }
  };

  const openPayslipEdit = (payslip) => {
    setSelectedPayslip(payslip);
    setDeductions(payslip.deductions_amount || 0);
    setSelectedAdvances(payslip.advance_deductions || []);
    setPayslipDialogOpen(true);
  };

  const handleSavePayslip = async () => {
    setSavingPayslip(true);
    try {
      await API.post(`/payslips/${selectedPayslip.id}/set-deductions`, {
        deductions_amount: parseFloat(deductions) || 0,
        advances_to_deduct: selectedAdvances,
      });
      setPayslipDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to save");
    } finally {
      setSavingPayslip(false);
    }
  };

  const openPayDialog = (payslip) => {
    setSelectedPayslip(payslip);
    setPayMethod("Cash");
    setPayReference("");
    setPayDialogOpen(true);
  };

  const handleMarkPaid = async () => {
    setPaying(true);
    try {
      await API.post(`/payslips/${selectedPayslip.id}/mark-paid`, {
        method: payMethod,
        reference: payReference || null,
      });
      setPayDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to mark paid");
    } finally {
      setPaying(false);
    }
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(amount || 0);
  };

  const userAdvances = (userId) => advances.filter(a => a.user_id === userId);

  const toggleAdvance = (advId, amount) => {
    const exists = selectedAdvances.find(a => a.advance_id === advId);
    if (exists) {
      setSelectedAdvances(selectedAdvances.filter(a => a.advance_id !== advId));
    } else {
      setSelectedAdvances([...selectedAdvances, { advance_id: advId, amount }]);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!run) {
    return (
      <div className="p-8 text-center text-muted-foreground">Payroll run not found</div>
    );
  }

  const payslips = run.payslips || [];
  const totalNet = payslips.reduce((sum, ps) => sum + (ps.net_pay || 0), 0);
  const paidCount = payslips.filter(ps => ps.status === "Paid").length;

  return (
    <div className="p-6 max-w-[1400px]" data-testid="payroll-detail-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/payroll")} data-testid="back-btn">
            <ArrowLeft className="w-4 h-4 mr-1" /> Back
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-foreground">
                Payroll: {run.period_start} - {run.period_end}
              </h1>
              <Badge variant="outline" className={`text-xs ${STATUS_COLORS[run.status] || ""}`}>
                {run.status === "Finalized" && <Lock className="w-3 h-3 mr-1" />}
                {run.status}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">{run.period_type} payroll</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {run.status === "Draft" && (
            <>
              <Button variant="outline" onClick={handleGenerate} disabled={generating} data-testid="generate-btn">
                {generating ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Play className="w-4 h-4 mr-1" />}
                Generate
              </Button>
              {payslips.length > 0 && (
                <Button onClick={handleFinalize} disabled={finalizing} data-testid="finalize-btn">
                  {finalizing ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Lock className="w-4 h-4 mr-1" />}
                  Finalize
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="mb-6 p-4 rounded-lg bg-amber-500/10 border border-amber-500/30" data-testid="warnings">
          <div className="flex items-center gap-2 text-amber-400 mb-2">
            <AlertTriangle className="w-4 h-4" />
            <span className="font-medium">Warnings</span>
          </div>
          <ul className="text-sm text-amber-300 list-disc list-inside">
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm text-muted-foreground mb-1">Total Employees</p>
          <p className="text-2xl font-bold text-foreground">{payslips.length}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm text-muted-foreground mb-1">Paid</p>
          <p className="text-2xl font-bold text-emerald-400">{paidCount} / {payslips.length}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm text-muted-foreground mb-1">Total Net Pay</p>
          <p className="text-2xl font-bold text-primary">{formatCurrency(totalNet)}</p>
        </div>
      </div>

      {/* Payslips Table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="payslips-table">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Employee</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Pay Type</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Base</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Deductions</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Advances</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Net Pay</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {payslips.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center py-12 text-muted-foreground">
                  <p>No payslips generated yet</p>
                  {run.status === "Draft" && (
                    <Button variant="outline" className="mt-4" onClick={handleGenerate}>
                      Generate Payslips
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ) : (
              payslips.map((ps) => (
                <TableRow key={ps.id} className="table-row-hover" data-testid={`payslip-row-${ps.id}`}>
                  <TableCell>
                    <p className="font-medium text-foreground">{ps.user_name}</p>
                    <p className="text-xs text-muted-foreground">{ps.user_email}</p>
                  </TableCell>
                  <TableCell className="text-sm">
                    {ps.details_json?.pay_type || "-"}
                    {ps.details_json?.days_present !== undefined && (
                      <span className="text-xs text-muted-foreground ml-1">({ps.details_json.days_present} days)</span>
                    )}
                    {ps.details_json?.total_hours !== undefined && (
                      <span className="text-xs text-muted-foreground ml-1">({ps.details_json.total_hours}h)</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">{formatCurrency(ps.base_amount)}</TableCell>
                  <TableCell className="text-right font-mono text-sm text-red-400">
                    {ps.deductions_amount > 0 ? `-${formatCurrency(ps.deductions_amount)}` : "-"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm text-amber-400">
                    {ps.advances_deducted_amount > 0 ? `-${formatCurrency(ps.advances_deducted_amount)}` : "-"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm font-bold text-primary">{formatCurrency(ps.net_pay)}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-xs ${STATUS_COLORS[ps.status] || ""}`}>
                      {ps.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      {run.status === "Draft" && (
                        <Button variant="ghost" size="sm" onClick={() => openPayslipEdit(ps)} data-testid={`edit-payslip-${ps.id}`}>
                          <DollarSign className="w-4 h-4" />
                        </Button>
                      )}
                      {run.status === "Finalized" && ps.status !== "Paid" && (
                        <Button size="sm" onClick={() => openPayDialog(ps)} data-testid={`pay-btn-${ps.id}`}>
                          <CheckCircle2 className="w-4 h-4 mr-1" /> Pay
                        </Button>
                      )}
                      {ps.status === "Paid" && (
                        <span className="text-xs text-emerald-400">Paid</span>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Edit Payslip Dialog */}
      <Dialog open={payslipDialogOpen} onOpenChange={setPayslipDialogOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="payslip-edit-dialog">
          <DialogHeader>
            <DialogTitle>Edit Deductions</DialogTitle>
          </DialogHeader>
          {selectedPayslip && (
            <div className="space-y-4 py-4">
              <div className="p-3 rounded-lg bg-muted/50">
                <p className="font-medium text-foreground">{selectedPayslip.user_name}</p>
                <p className="text-sm text-muted-foreground">Base: {formatCurrency(selectedPayslip.base_amount)}</p>
              </div>

              <div className="space-y-2">
                <Label>Manual Deductions (€)</Label>
                <Input type="number" value={deductions} onChange={(e) => setDeductions(e.target.value)} className="bg-background" data-testid="deductions-input" />
              </div>

              {userAdvances(selectedPayslip.user_id).length > 0 && (
                <div className="space-y-2">
                  <Label>Deduct from Advances/Loans</Label>
                  <div className="space-y-2 max-h-[200px] overflow-y-auto">
                    {userAdvances(selectedPayslip.user_id).map((adv) => {
                      const isSelected = selectedAdvances.some(a => a.advance_id === adv.id);
                      return (
                        <div
                          key={adv.id}
                          className={`p-3 rounded-lg border cursor-pointer transition-colors ${isSelected ? "border-primary bg-primary/10" : "border-border hover:bg-muted/50"}`}
                          onClick={() => toggleAdvance(adv.id, adv.remaining_amount)}
                          data-testid={`advance-option-${adv.id}`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="text-sm font-medium">{adv.type} - {adv.issued_date}</p>
                              <p className="text-xs text-muted-foreground">Remaining: {formatCurrency(adv.remaining_amount)}</p>
                            </div>
                            {isSelected && <CheckCircle2 className="w-4 h-4 text-primary" />}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="p-3 rounded-lg bg-muted/50 border-t border-border">
                <div className="flex justify-between text-sm">
                  <span>Base</span>
                  <span>{formatCurrency(selectedPayslip.base_amount)}</span>
                </div>
                <div className="flex justify-between text-sm text-red-400">
                  <span>Deductions</span>
                  <span>-{formatCurrency(deductions)}</span>
                </div>
                <div className="flex justify-between text-sm text-amber-400">
                  <span>Advances</span>
                  <span>-{formatCurrency(selectedAdvances.reduce((s, a) => s + a.amount, 0))}</span>
                </div>
                <div className="flex justify-between font-bold text-foreground border-t border-border pt-2 mt-2">
                  <span>Net Pay</span>
                  <span className="text-primary">
                    {formatCurrency(
                      selectedPayslip.base_amount 
                      - (parseFloat(deductions) || 0) 
                      - selectedAdvances.reduce((s, a) => s + a.amount, 0)
                    )}
                  </span>
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPayslipDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSavePayslip} disabled={savingPayslip} data-testid="save-deductions-btn">
              {savingPayslip && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Mark Paid Dialog */}
      <Dialog open={payDialogOpen} onOpenChange={setPayDialogOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="pay-dialog">
          <DialogHeader>
            <DialogTitle>Mark as Paid</DialogTitle>
          </DialogHeader>
          {selectedPayslip && (
            <div className="space-y-4 py-4">
              <div className="p-3 rounded-lg bg-muted/50">
                <p className="font-medium text-foreground">{selectedPayslip.user_name}</p>
                <p className="text-lg font-bold text-primary">{formatCurrency(selectedPayslip.net_pay)}</p>
              </div>

              <div className="space-y-2">
                <Label>Payment Method</Label>
                <Select value={payMethod} onValueChange={setPayMethod}>
                  <SelectTrigger className="bg-background" data-testid="pay-method-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Cash">Cash</SelectItem>
                    <SelectItem value="BankTransfer">Bank Transfer</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {payMethod === "BankTransfer" && (
                <div className="space-y-2">
                  <Label>Reference</Label>
                  <Input value={payReference} onChange={(e) => setPayReference(e.target.value)} placeholder="Transfer reference" className="bg-background" data-testid="pay-reference-input" />
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPayDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleMarkPaid} disabled={paying} data-testid="confirm-pay-btn">
              {paying && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              Mark Paid
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
