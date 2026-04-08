/**
 * ContractPaymentsPage — Външни работници / договорни плащания.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
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
  Briefcase, Plus, Loader2, Search, Check, DollarSign, Trash2,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CFG = {
  active: { label: "Активен", color: "bg-blue-50 text-blue-700" },
  completed: { label: "Завършен", color: "bg-emerald-50 text-emerald-700" },
  cancelled: { label: "Отменен", color: "bg-zinc-100 text-zinc-500" },
};

export default function ContractPaymentsPage() {
  const { t } = useTranslation();
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

  const handlePayTranche = async (idx) => {
    if (!selected) return;
    setPayingTranche(true);
    try {
      const res = await API.post(`/contract-payments/${selected.id}/pay-tranche`, { tranche_index: idx });
      setSelected(res.data);
      toast.success(t("contractPayments.tranchePaid"));
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setPayingTranche(false); }
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
                      <TableCell className="text-right font-mono">{c.total_amount?.toFixed(2)} EUR</TableCell>
                      <TableCell className="text-right font-mono text-emerald-400">{paid.toFixed(2)} EUR</TableCell>
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
                <span className="font-mono font-bold">{selected.total_amount?.toFixed(2)} EUR</span>
              </div>
              <Progress value={(() => { const p = selected.tranches?.filter(t => t.status === "paid").reduce((s, t) => s + t.amount, 0) || 0; return selected.total_amount > 0 ? (p / selected.total_amount) * 100 : 0; })()} className="h-2" />
              <div className="space-y-2">
                {selected.tranches?.map((tr, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/10 text-sm">
                    <div>
                      <span className="font-mono">{tr.amount?.toFixed(2)} EUR</span>
                      {tr.due_date && <span className="text-xs text-muted-foreground ml-2">до {tr.due_date}</span>}
                    </div>
                    {tr.status === "paid" ? (
                      <Badge variant="outline" className="text-emerald-400 border-emerald-400/30 text-xs"><Check className="w-3 h-3 mr-1" />{t("contractPayments.paid")}</Badge>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => handlePayTranche(i)} disabled={payingTranche} data-testid={`pay-tranche-${i}`}>
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
    </div>
  );
}
