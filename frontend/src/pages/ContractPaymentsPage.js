/**
 * ContractPaymentsPage — Външни работници / договорни плащания.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { apiErrorText, createKeyHolder, idempotencyHeaders } from "@/lib/idempotency";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Briefcase, Plus, Loader2, Search, Check, DollarSign, Trash2, Undo2, X,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CFG = {
  active: { label: "Активен", color: "bg-blue-50 text-blue-700" },
  completed: { label: "Завършен", color: "bg-emerald-50 text-emerald-700" },
  cancelled: { label: "Отменен", color: "bg-zinc-100 text-zinc-500" },
};

// FIX-PAY-02 (Р104): the roles that may request and decide a tranche reversal (as "Плати")
const REVERSAL_ROLES = ["Accountant", "Admin", "Owner"];

export default function ContractPaymentsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const canReverse = REVERSAL_ROLES.includes(user?.role);
  const [items, setItems] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fSite, setFSite] = useState("");
  const [fStatus, setFStatus] = useState("");

  // Create
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ worker_name: "", description: "", total_amount: "", site_id: "", contract_type: "one_time" });
  const [saving, setSaving] = useState(false);

  // Detail
  const [selected, setSelected] = useState(null);
  const [showDetail, setShowDetail] = useState(false);
  const [payingTranche, setPayingTranche] = useState(false);

  // FIX-PAY-01 (Р97): "Плати" asks for the account (Каса/Банка) and the date; the payment is
  // recorded in the single payment ledger. One Idempotency-Key per opened dialog (R29).
  const [accounts, setAccounts] = useState([]);
  const [payDialog, setPayDialog] = useState(null); // { idx, amount, account_id, date }
  const payKey = useRef(createKeyHolder()).current;

  // FIX-PAY-02 (Р104): "Сторно" = a request with a reason; ANOTHER eligible person approves
  // or rejects it. One Idempotency-Key per opened dialog / per decision click (R29).
  const [reversalDialog, setReversalDialog] = useState(null); // { idx, amount, reason }
  const [reversalBusy, setReversalBusy] = useState(false);
  const reversalKey = useRef(createKeyHolder()).current;
  const decisionKey = useRef(createKeyHolder()).current;

  useEffect(() => {
    API.get("/projects").then(r => setProjects(r.data.items || r.data || [])).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (fSite) p.append("site_id", fSite);
      if (fStatus) p.append("status", fStatus);
      const res = await API.get(`/contract-payments?${p}`);
      setItems(res.data.items || []);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [fSite, fStatus]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!form.worker_name.trim() || !form.total_amount) { toast.error(t("contractPayments.fillRequired")); return; }
    setSaving(true);
    try {
      await API.post("/contract-payments", {
        ...form,
        total_amount: parseFloat(form.total_amount),
        site_id: form.site_id || null,
      });
      toast.success(t("contractPayments.created"));
      setShowCreate(false);
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setSaving(false); }
  };

  const openPayDialog = async (idx) => {
    if (!selected) return;
    payKey.settle(null); // a new dialog = a new submission = a new key
    let list = accounts;
    try {
      const res = await API.get("/finance/accounts");
      list = (res.data || []).filter(a => a.active !== false);
      setAccounts(list);
    } catch (err) { toast.error(apiErrorText(err, t("contractPayments.accountsLoadError"))); }
    setPayDialog({
      idx,
      amount: selected.tranches?.[idx]?.amount || 0,
      account_id: list[0]?.id || "",
      date: new Date().toISOString().split("T")[0],
    });
  };

  const handlePayTranche = async () => {
    if (!selected || !payDialog) return;
    if (!payDialog.account_id) { toast.error(t("contractPayments.accountRequired")); return; }
    if (!payDialog.date) { toast.error(t("contractPayments.dateRequired")); return; }
    setPayingTranche(true);
    try {
      const res = await API.post(`/contract-payments/${selected.id}/pay-tranche`, {
        tranche_index: payDialog.idx, account_id: payDialog.account_id, date: payDialog.date,
      }, idempotencyHeaders(payKey.get()));
      payKey.settle(null);
      setSelected(res.data);
      setPayDialog(null);
      toast.success(t("contractPayments.tranchePaid"));
      load();
    } catch (err) {
      payKey.settle(err); // keep the key only for a retry after a network error
      toast.error(apiErrorText(err, t("common.error")));
    }
    finally { setPayingTranche(false); }
  };

  const openReversalDialog = (idx) => {
    if (!selected) return;
    reversalKey.settle(null); // a new dialog = a new key
    setReversalDialog({ idx, amount: selected.tranches?.[idx]?.amount || 0, reason: "" });
  };

  const handleRequestReversal = async () => {
    if (!selected || !reversalDialog) return;
    if (!reversalDialog.reason.trim()) { toast.error(t("contractPayments.reversalReasonRequired")); return; }
    setReversalBusy(true);
    try {
      const res = await API.post(
        `/contract-payments/${selected.id}/tranches/${reversalDialog.idx}/reversal-request`,
        { reason: reversalDialog.reason.trim() }, idempotencyHeaders(reversalKey.get()));
      reversalKey.settle(null);
      setSelected(res.data);
      setReversalDialog(null);
      toast.success(t("contractPayments.reversalRequested"));
      load();
    } catch (err) {
      reversalKey.settle(err);
      toast.error(apiErrorText(err, t("common.error")));
    }
    finally { setReversalBusy(false); }
  };

  const handleDecideReversal = async (idx, decision) => {
    const req = selected?.tranches?.[idx]?.reversal_request;
    if (!selected || !req) return;
    if (decision === "approve" && !window.confirm(t("contractPayments.reversalApproveConfirm"))) return;
    setReversalBusy(true);
    try {
      const res = await API.post(
        `/contract-payments/${selected.id}/tranches/${idx}/reversal-${decision}`,
        { request_id: req.id }, idempotencyHeaders(decisionKey.get()));
      decisionKey.settle(null);
      setSelected(res.data);
      toast.success(t(decision === "approve" ? "contractPayments.reversalApproved" : "contractPayments.reversalRejected"));
      load();
    } catch (err) {
      decisionKey.settle(err);
      toast.error(apiErrorText(err, t("common.error")));
    }
    finally { setReversalBusy(false); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm(t("contractPayments.confirmDelete"))) return;
    try {
      await API.delete(`/contract-payments/${id}`);
      toast.success(t("common.delete"));
      setShowDetail(false);
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-5xl mx-auto" data-testid="contract-payments-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <Briefcase className="w-5 h-5 text-violet-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold">{t("contractPayments.title")}</h1>
            <p className="text-sm text-muted-foreground">{t("contractPayments.subtitle")}</p>
          </div>
        </div>
        <Button onClick={() => { setForm({ worker_name: "", description: "", total_amount: "", site_id: "", contract_type: "one_time" }); setShowCreate(true); }} data-testid="new-contract-btn">
          <Plus className="w-4 h-4 mr-2" /> {t("contractPayments.newPayment")}
        </Button>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex gap-4">
            <div className="flex-1">
              <Label className="text-xs mb-1 block">{t("contractPayments.site")}</Label>
              <Select value={fSite || "all"} onValueChange={v => setFSite(v === "all" ? "" : v)}>
                <SelectTrigger><SelectValue placeholder={t("common.all")} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code || p.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <Label className="text-xs mb-1 block">{t("common.status")}</Label>
              <Select value={fStatus || "all"} onValueChange={v => setFStatus(v === "all" ? "" : v)}>
                <SelectTrigger><SelectValue placeholder={t("common.all")} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {Object.entries(STATUS_CFG).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center py-16 text-muted-foreground gap-2">
              <Search className="w-8 h-8 opacity-40" /><p className="text-sm">{t("contractPayments.noItems")}</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("contractPayments.worker")}</TableHead>
                  <TableHead>{t("contractPayments.description")}</TableHead>
                  <TableHead className="text-right">{t("contractPayments.total")}</TableHead>
                  <TableHead className="text-right">{t("contractPayments.paid")}</TableHead>
                  <TableHead>{t("common.status")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map(c => {
                  const paid = c.tranches?.filter(t => t.status === "paid").reduce((s, t) => s + (t.amount || 0), 0) || 0;
                  const st = STATUS_CFG[c.status] || STATUS_CFG.active;
                  return (
                    <TableRow key={c.id} className="cursor-pointer hover:bg-muted/40" onClick={() => { setSelected(c); setShowDetail(true); }} data-testid={`contract-row-${c.id}`}>
                      <TableCell className="font-medium">{c.worker_name}</TableCell>
                      <TableCell className="text-sm text-muted-foreground truncate max-w-[200px]">{c.description || "-"}</TableCell>
                      <TableCell className="text-right font-mono">{c.total_amount?.toFixed(2)} €</TableCell>
                      <TableCell className="text-right font-mono text-emerald-400">{paid.toFixed(2)} €</TableCell>
                      <TableCell><Badge className={`text-xs ${st.color}`} variant="outline">{st.label}</Badge></TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("contractPayments.newPayment")}</DialogTitle>
            <DialogDescription>{t("contractPayments.newDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>{t("contractPayments.worker")} *</Label>
              <Input value={form.worker_name} onChange={e => setForm(f => ({ ...f, worker_name: e.target.value }))} placeholder={t("contractPayments.workerPlaceholder")} data-testid="create-worker-name" />
            </div>
            <div className="space-y-1">
              <Label>{t("contractPayments.description")}</Label>
              <Input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder={t("contractPayments.descPlaceholder")} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>{t("contractPayments.total")} *</Label>
                <Input type="number" value={form.total_amount} onChange={e => setForm(f => ({ ...f, total_amount: e.target.value }))} placeholder="0.00" data-testid="create-amount" />
              </div>
              <div className="space-y-1">
                <Label>{t("contractPayments.site")}</Label>
                <Select value={form.site_id || "none"} onValueChange={v => setForm(f => ({ ...f, site_id: v === "none" ? "" : v }))}>
                  <SelectTrigger><SelectValue placeholder="-" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">-</SelectItem>
                    {projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code || p.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleCreate} disabled={saving} data-testid="create-contract-submit">{saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}{t("common.create")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Detail Dialog */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{selected?.worker_name}</DialogTitle>
            <DialogDescription>{selected?.description}</DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">{t("contractPayments.total")}</span>
                <span className="font-mono font-bold">{selected.total_amount?.toFixed(2)} €</span>
              </div>
              <Progress value={(() => { const p = selected.tranches?.filter(t => t.status === "paid").reduce((s, t) => s + t.amount, 0) || 0; return selected.total_amount > 0 ? (p / selected.total_amount) * 100 : 0; })()} className="h-2" />
              <div className="space-y-2">
                {selected.tranches?.map((tr, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/10 text-sm">
                    <div>
                      <span className="font-mono">{tr.amount?.toFixed(2)} €</span>
                      {tr.due_date && <span className="text-xs text-muted-foreground ml-2">до {tr.due_date}</span>}
                      {tr.payment_history?.length > 0 && (
                        <div className="text-xs text-muted-foreground" data-testid={`reversal-history-${i}`}>
                          {t("contractPayments.reversalHistory", { count: tr.payment_history.length })}
                        </div>
                      )}
                    </div>
                    {tr.status === "paid" ? (
                      <div className="flex flex-col items-end gap-1">
                        <Badge variant="outline" className="text-emerald-400 border-emerald-400/30 text-xs"><Check className="w-3 h-3 mr-1" />{t("contractPayments.paid")}</Badge>
                        {tr.reversal_request ? (
                          <div className="text-right" data-testid={`reversal-pending-${i}`}>
                            <div className="text-xs text-amber-500">{t("contractPayments.reversalPending")}: {tr.reversal_request.reason}</div>
                            {canReverse && tr.reversal_request.requested_by !== user?.id ? (
                              <div className="flex gap-1 justify-end mt-1">
                                <Button size="sm" variant="destructive" onClick={() => handleDecideReversal(i, "approve")} disabled={reversalBusy} data-testid={`reversal-approve-${i}`}>
                                  <Check className="w-3 h-3 mr-1" /> {t("contractPayments.reversalApprove")}
                                </Button>
                                <Button size="sm" variant="outline" onClick={() => handleDecideReversal(i, "reject")} disabled={reversalBusy} data-testid={`reversal-reject-${i}`}>
                                  <X className="w-3 h-3 mr-1" /> {t("contractPayments.reversalReject")}
                                </Button>
                              </div>
                            ) : (
                              <div className="text-xs text-muted-foreground">{t("contractPayments.reversalWaitsOther")}</div>
                            )}
                          </div>
                        ) : (canReverse && tr.payment_id && (
                          <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => openReversalDialog(i)} disabled={reversalBusy} data-testid={`reversal-request-${i}`}>
                            <Undo2 className="w-3 h-3 mr-1" /> {t("contractPayments.reversal")}
                          </Button>
                        ))}
                      </div>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => openPayDialog(i)} disabled={payingTranche} data-testid={`pay-tranche-${i}`}>
                        <DollarSign className="w-3 h-3 mr-1" /> {t("contractPayments.payTranche")}
                      </Button>
                    )}
                  </div>
                ))}
              </div>
              {selected.status !== "completed" && (
                <Button variant="destructive" size="sm" onClick={() => handleDelete(selected.id)} className="w-full" data-testid="delete-contract-btn">
                  <Trash2 className="w-4 h-4 mr-1" /> {t("common.delete")}
                </Button>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Reversal request Dialog — FIX-PAY-02 (Р104) */}
      <Dialog open={!!reversalDialog} onOpenChange={o => { if (!o && !reversalBusy) setReversalDialog(null); }}>
        <DialogContent className="max-w-sm" data-testid="reversal-request-dialog">
          <DialogHeader>
            <DialogTitle>{t("contractPayments.reversalDialogTitle")}</DialogTitle>
            <DialogDescription>{selected?.worker_name} · {t("contractPayments.reversalDialogDesc")}</DialogDescription>
          </DialogHeader>
          {reversalDialog && (
            <div className="space-y-3">
              <div className="space-y-1">
                <Label>{t("contractPayments.total")}</Label>
                <Input value={`${Number(reversalDialog.amount).toFixed(2)} €`} readOnly disabled />
              </div>
              <div className="space-y-1">
                <Label>{t("contractPayments.reversalReason")} *</Label>
                <Input value={reversalDialog.reason} onChange={e => setReversalDialog(d => ({ ...d, reason: e.target.value }))} maxLength={500} data-testid="reversal-reason" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setReversalDialog(null)} disabled={reversalBusy}>{t("common.cancel")}</Button>
            <Button variant="destructive" onClick={handleRequestReversal} disabled={reversalBusy || !reversalDialog?.reason?.trim()} data-testid="reversal-request-confirm">
              {reversalBusy && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}{t("contractPayments.reversalSubmit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Pay tranche Dialog — FIX-PAY-01 (Р97) */}
      <Dialog open={!!payDialog} onOpenChange={o => { if (!o && !payingTranche) setPayDialog(null); }}>
        <DialogContent className="max-w-sm" data-testid="pay-tranche-dialog">
          <DialogHeader>
            <DialogTitle>{t("contractPayments.payDialogTitle")}</DialogTitle>
            <DialogDescription>{selected?.worker_name} · {t("contractPayments.payDialogDesc")}</DialogDescription>
          </DialogHeader>
          {payDialog && (
            <div className="space-y-3">
              <div className="space-y-1">
                <Label>{t("contractPayments.total")}</Label>
                <Input value={`${Number(payDialog.amount).toFixed(2)} €`} readOnly disabled data-testid="pay-tranche-amount" />
              </div>
              <div className="space-y-1">
                <Label>{t("contractPayments.account")} *</Label>
                <Select value={payDialog.account_id || undefined} onValueChange={v => setPayDialog(d => ({ ...d, account_id: v }))}>
                  <SelectTrigger data-testid="pay-tranche-account"><SelectValue placeholder={t("contractPayments.accountPlaceholder")} /></SelectTrigger>
                  <SelectContent>
                    {accounts.map(a => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>{t("contractPayments.payDate")} *</Label>
                <Input type="date" value={payDialog.date} onChange={e => setPayDialog(d => ({ ...d, date: e.target.value }))} data-testid="pay-tranche-date" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPayDialog(null)} disabled={payingTranche}>{t("common.cancel")}</Button>
            <Button onClick={handlePayTranche} disabled={payingTranche || !payDialog?.account_id || !payDialog?.date} data-testid="pay-tranche-confirm">
              {payingTranche && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}{t("contractPayments.confirmPay")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
