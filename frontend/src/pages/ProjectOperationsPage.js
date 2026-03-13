import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
  ArrowLeft, Loader2, Plus, Check, X, Hammer, FileText, CreditCard,
  Shield, AlertTriangle, DollarSign, Building2,
} from "lucide-react";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";

export default function ProjectOperationsPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);

  // Subcontractors
  const [subs, setSubs] = useState([]);
  const [packages, setPackages] = useState([]);
  const [subActs, setSubActs] = useState([]);
  const [subPayments, setSubPayments] = useState([]);

  // Client acts
  const [clientActs, setClientActs] = useState([]);

  // Revenue snapshots
  const [snapshots, setSnapshots] = useState([]);

  // Overhead
  const [ohSnapshots, setOhSnapshots] = useState([]);

  // Offers for dropdowns
  const [offers, setOffers] = useState([]);

  // Dialogs
  const [dialog, setDialog] = useState(null); // { type, data }
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState(null);

  const fetchAll = useCallback(async () => {
    try {
      const [projRes, subsRes, pkgRes, actsRes, payRes, caRes, snapRes, ohRes, offRes] = await Promise.all([
        API.get(`/projects/${projectId}`),
        API.get("/subcontractors"),
        API.get(`/subcontractor-packages?project_id=${projectId}`),
        API.get(`/subcontractor-acts?project_id=${projectId}`),
        API.get(`/subcontractor-payments?project_id=${projectId}`),
        API.get(`/client-acts?project_id=${projectId}`),
        API.get(`/revenue-snapshots?project_id=${projectId}`),
        API.get("/overhead-snapshots"),
        API.get("/offers"),
      ]);
      setProject(projRes.data);
      setSubs(subsRes.data);
      setPackages(pkgRes.data);
      setSubActs(actsRes.data);
      setSubPayments(payRes.data);
      setClientActs(caRes.data);
      setSnapshots(snapRes.data);
      setOhSnapshots(ohRes.data);
      setOffers(offRes.data.filter(o => o.project_id === projectId));
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Generic save with confirm
  const handleSave = async (endpoint, payload, method = "post") => {
    setSaving(true);
    try {
      if (method === "post") await API.post(endpoint, payload);
      else await API.put(endpoint, payload);
      setDialog(null);
      setConfirmDialog(null);
      fetchAll();
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка");
    } finally { setSaving(false); }
  };

  // Confirm wrapper
  const showConfirm = (action, label, onConfirm) => {
    setConfirmDialog({ action, label, onConfirm });
  };

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  const acceptedOffers = offers.filter(o => o.status === "Accepted");

  return (
    <div className="p-6 max-w-[1400px]" data-testid="project-operations-page">
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="sm" onClick={() => navigate(`/projects/${projectId}`)}><ArrowLeft className="w-4 h-4 mr-1" /> Обект</Button>
        <div>
          <h1 className="text-xl font-bold text-foreground">Операции</h1>
          <p className="text-sm text-muted-foreground">{project?.code} — {project?.name}</p>
        </div>
      </div>

      <Tabs defaultValue="subcontractors">
        <TabsList className="mb-4 flex-wrap">
          <TabsTrigger value="subcontractors"><Hammer className="w-4 h-4 mr-1" /> Подизпълнители ({packages.length})</TabsTrigger>
          <TabsTrigger value="client-acts"><FileText className="w-4 h-4 mr-1" /> Актове ({clientActs.length})</TabsTrigger>
          <TabsTrigger value="revenue"><Shield className="w-4 h-4 mr-1" /> Приходи ({snapshots.length})</TabsTrigger>
          <TabsTrigger value="overhead"><DollarSign className="w-4 h-4 mr-1" /> Режийни ({ohSnapshots.length})</TabsTrigger>
        </TabsList>

        {/* ═══ SUBCONTRACTORS TAB ═══ */}
        <TabsContent value="subcontractors">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Пакети подизпълнители</h3>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => { setForm({ name: "", phone: "", contact_person: "" }); setDialog({ type: "new-sub" }); }} data-testid="new-sub-btn"><Plus className="w-3 h-3 mr-1" /> Подизпълнител</Button>
              <Button size="sm" onClick={() => { setForm({ subcontractor_id: "", title: "", source_offer_id: "" }); setDialog({ type: "new-pkg" }); }} data-testid="new-pkg-btn"><Plus className="w-3 h-3 mr-1" /> Нов пакет</Button>
            </div>
          </div>
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-[10px] uppercase text-muted-foreground">Пакет</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Подизпълнител</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Договор</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Сертифицирано</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Платено</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Статус</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground w-[160px]">Действия</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {packages.length === 0 ? (
                  <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">Няма пакети</TableCell></TableRow>
                ) : packages.map((pkg, i) => {
                  const sub = subs.find(s => s.id === pkg.subcontractor_id);
                  return (
                    <TableRow key={i} data-testid={`pkg-row-${i}`}>
                      <TableCell className="font-mono text-sm text-primary">{pkg.package_no}</TableCell>
                      <TableCell className="text-sm">{sub?.name || "—"}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{pkg.contract_total?.toFixed(2)}</TableCell>
                      <TableCell className="text-right font-mono text-sm text-emerald-400">{pkg.certified_total?.toFixed(2)}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{pkg.paid_total?.toFixed(2)}</TableCell>
                      <TableCell><Badge variant="outline" className="text-[9px]">{pkg.status}</Badge></TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          {pkg.status === "draft" && <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => showConfirm("confirm-pkg", `Потвърди ${pkg.package_no}?`, () => handleSave(`/subcontractor-packages/${pkg.id}/confirm`, {}))} data-testid={`confirm-pkg-${i}`}><Check className="w-3 h-3 mr-0.5" />Потвърди</Button>}
                          {pkg.status !== "draft" && pkg.status !== "closed" && (
                            <>
                              <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => { setForm({ package_id: pkg.id, lines: [], act_date: new Date().toISOString().split("T")[0], notes: "" }); setDialog({ type: "new-act", pkg }); }} data-testid={`new-act-${i}`}><FileText className="w-3 h-3 mr-0.5" />Акт</Button>
                              <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => { setForm({ package_id: pkg.id, amount: "", payment_date: new Date().toISOString().split("T")[0], payment_type: "partial", payment_method: "bank", notes: "" }); setDialog({ type: "new-pay", pkg }); }} data-testid={`new-pay-${i}`}><CreditCard className="w-3 h-3 mr-0.5" />Плати</Button>
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* ═══ CLIENT ACTS TAB ═══ */}
        <TabsContent value="client-acts">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Клиентски актове</h3>
            <Button size="sm" onClick={() => { setForm({ source_offer_id: acceptedOffers[0]?.id || "", percent: 100, act_date: new Date().toISOString().split("T")[0] }); setDialog({ type: "new-client-act" }); }} data-testid="new-client-act-btn"><Plus className="w-3 h-3 mr-1" /> Нов акт</Button>
          </div>
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-[10px] uppercase text-muted-foreground">Номер</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Дата</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground text-right">Сума</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Статус</TableHead>
                <TableHead className="text-[10px] uppercase text-muted-foreground">Действия</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {clientActs.length === 0 ? (
                  <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Няма актове</TableCell></TableRow>
                ) : clientActs.map((act, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-sm text-primary">{act.act_number}</TableCell>
                    <TableCell className="text-sm">{formatDate(act.act_date)}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{act.subtotal?.toFixed(2)} EUR</TableCell>
                    <TableCell><Badge variant="outline" className={`text-[9px] ${act.status === "Accepted" ? "bg-emerald-500/15 text-emerald-400" : ""}`}>{act.status === "Draft" ? "Чернова" : act.status === "Accepted" ? "Приет" : act.status}</Badge></TableCell>
                    <TableCell>
                      {act.status === "Draft" && <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => showConfirm("confirm-act", `Потвърди акт ${act.act_number}?`, () => handleSave(`/client-acts/${act.id}/confirm`, {}))} data-testid={`confirm-ca-${i}`}><Check className="w-3 h-3 mr-0.5" />Потвърди</Button>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* ═══ REVENUE TAB ═══ */}
        <TabsContent value="revenue">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Revenue Snapshots</h3>
            {acceptedOffers.length > 0 && (
              <Button size="sm" onClick={() => showConfirm("create-snapshot", `Замрази приходна база от ${acceptedOffers[0].offer_no}?`, () => handleSave(`/revenue-snapshots/from-offer/${acceptedOffers[0].id}`, {}))} data-testid="new-snapshot-btn"><Shield className="w-3 h-3 mr-1" /> Замрази</Button>
            )}
          </div>
          <div className="space-y-2">
            {snapshots.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">Няма замразени приходни бази</p>
            ) : snapshots.map((s, i) => (
              <div key={i} className="flex items-center justify-between p-3 rounded-lg border border-border bg-card" data-testid={`snapshot-${i}`}>
                <div>
                  <span className="font-mono text-sm text-primary">{s.offer_no}</span>
                  <Badge variant="outline" className="text-[9px] ml-2">{s.offer_type === "extra" ? "Допълнителна" : "Основна"}</Badge>
                  <span className="text-xs text-muted-foreground ml-2">v{s.version}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm font-bold">{s.total_contract_value?.toFixed(2)} EUR</span>
                  <span className="text-xs text-muted-foreground">{formatDate(s.frozen_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </TabsContent>

        {/* ═══ OVERHEAD TAB ═══ */}
        <TabsContent value="overhead">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Режийни разходи</h3>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => { setForm({ category_code: "general", category_name: "", period_key: new Date().toISOString().slice(0, 7), amount: "", notes: "" }); setDialog({ type: "new-overhead" }); }} data-testid="new-oh-btn"><Plus className="w-3 h-3 mr-1" /> Режиен разход</Button>
              <Button size="sm" onClick={() => showConfirm("allocate-oh", "Разпредели режийни към този проект?", () => handleSave(`/overhead-allocation/compute/${projectId}`, {}))} data-testid="allocate-oh-btn"><DollarSign className="w-3 h-3 mr-1" /> Разпредели</Button>
            </div>
          </div>
          <div className="space-y-2">
            {ohSnapshots.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">Няма режийни записи</p>
            ) : ohSnapshots.slice(0, 10).map((o, i) => (
              <div key={i} className="flex items-center justify-between p-2 rounded border border-border text-sm">
                <div><span className="text-foreground">{o.category_name || o.category_code}</span> <span className="text-muted-foreground">• {o.period_key}</span></div>
                <span className="font-mono">{o.amount?.toFixed(2)} EUR</span>
              </div>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      {/* ═══ CREATE DIALOGS ═══ */}

      {/* New Subcontractor */}
      <Dialog open={dialog?.type === "new-sub"} onOpenChange={() => setDialog(null)}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="new-sub-dialog">
          <DialogHeader><DialogTitle><Building2 className="w-5 h-5 text-primary inline mr-2" />Нов подизпълнител</DialogTitle></DialogHeader>
          <div className="space-y-2 py-2">
            <div><Label className="text-xs">Име *</Label><Input value={form.name || ""} onChange={e => setForm({...form, name: e.target.value})} className="bg-background" /></div>
            <div><Label className="text-xs">Контакт</Label><Input value={form.contact_person || ""} onChange={e => setForm({...form, contact_person: e.target.value})} className="bg-background" /></div>
            <div><Label className="text-xs">Телефон</Label><Input value={form.phone || ""} onChange={e => setForm({...form, phone: e.target.value})} className="bg-background" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Отказ</Button>
            <Button onClick={() => handleSave("/subcontractors", form)} disabled={saving || !form.name} data-testid="save-sub-btn">{saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}Създай</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Package */}
      <Dialog open={dialog?.type === "new-pkg"} onOpenChange={() => setDialog(null)}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="new-pkg-dialog">
          <DialogHeader><DialogTitle><Hammer className="w-5 h-5 text-primary inline mr-2" />Нов пакет</DialogTitle></DialogHeader>
          <div className="space-y-2 py-2">
            <div><Label className="text-xs">Подизпълнител *</Label>
              <Select value={form.subcontractor_id || ""} onValueChange={v => setForm({...form, subcontractor_id: v})}>
                <SelectTrigger className="bg-background"><SelectValue placeholder="Избери" /></SelectTrigger>
                <SelectContent>{subs.map(s => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label className="text-xs">Заглавие *</Label><Input value={form.title || ""} onChange={e => setForm({...form, title: e.target.value})} className="bg-background" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Отказ</Button>
            <Button onClick={() => handleSave("/subcontractor-packages", { ...form, project_id: projectId })} disabled={saving || !form.subcontractor_id || !form.title} data-testid="save-pkg-btn">{saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4 mr-1" />}Създай</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Subcontractor Payment */}
      <Dialog open={dialog?.type === "new-pay"} onOpenChange={() => setDialog(null)}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="new-pay-dialog">
          <DialogHeader><DialogTitle><CreditCard className="w-5 h-5 text-emerald-500 inline mr-2" />Плащане</DialogTitle></DialogHeader>
          <div className="space-y-2 py-2">
            <div className="p-2 rounded bg-muted/30 text-sm"><span className="text-muted-foreground">Пакет:</span> <span className="font-mono">{dialog?.pkg?.package_no}</span></div>
            <div><Label className="text-xs">Сума (EUR) *</Label><Input type="number" step="0.01" value={form.amount || ""} onChange={e => setForm({...form, amount: e.target.value})} className="bg-background font-mono" /></div>
            <div><Label className="text-xs">Дата</Label><Input type="date" value={form.payment_date || ""} onChange={e => setForm({...form, payment_date: e.target.value})} className="bg-background" /></div>
            <div><Label className="text-xs">Бележка</Label><Input value={form.notes || ""} onChange={e => setForm({...form, notes: e.target.value})} className="bg-background" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Отказ</Button>
            <Button onClick={() => showConfirm("pay", `Потвърди плащане ${form.amount} EUR?`, () => handleSave("/subcontractor-payments", form))} disabled={saving || !form.amount} className="bg-emerald-600 hover:bg-emerald-700" data-testid="save-pay-btn"><CreditCard className="w-4 h-4 mr-1" />Плати</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Client Act */}
      <Dialog open={dialog?.type === "new-client-act"} onOpenChange={() => setDialog(null)}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="new-client-act-dialog">
          <DialogHeader><DialogTitle><FileText className="w-5 h-5 text-primary inline mr-2" />Нов клиентски акт</DialogTitle></DialogHeader>
          <div className="space-y-2 py-2">
            <div><Label className="text-xs">Оферта *</Label>
              <Select value={form.source_offer_id || ""} onValueChange={v => setForm({...form, source_offer_id: v})}>
                <SelectTrigger className="bg-background"><SelectValue placeholder="Избери оферта" /></SelectTrigger>
                <SelectContent>{acceptedOffers.map(o => <SelectItem key={o.id} value={o.id}>{o.offer_no} ({o.total} EUR)</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label className="text-xs">% изпълнение</Label><Input type="number" min="0" max="100" value={form.percent || 100} onChange={e => setForm({...form, percent: e.target.value})} className="bg-background font-mono" /></div>
            <div><Label className="text-xs">Дата</Label><Input type="date" value={form.act_date || ""} onChange={e => setForm({...form, act_date: e.target.value})} className="bg-background" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Отказ</Button>
            <Button onClick={() => handleSave(`/client-acts/from-offer/${form.source_offer_id}`, { percent: parseFloat(form.percent) || 100, act_date: form.act_date })} disabled={saving || !form.source_offer_id} data-testid="save-ca-btn"><Check className="w-4 h-4 mr-1" />Създай</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Overhead */}
      <Dialog open={dialog?.type === "new-overhead"} onOpenChange={() => setDialog(null)}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="new-oh-dialog">
          <DialogHeader><DialogTitle><DollarSign className="w-5 h-5 text-primary inline mr-2" />Режиен разход</DialogTitle></DialogHeader>
          <div className="space-y-2 py-2">
            <div><Label className="text-xs">Категория</Label><Input value={form.category_name || ""} onChange={e => setForm({...form, category_name: e.target.value})} placeholder="Наем, Комунални..." className="bg-background" /></div>
            <div><Label className="text-xs">Период</Label><Input type="month" value={form.period_key || ""} onChange={e => setForm({...form, period_key: e.target.value})} className="bg-background" /></div>
            <div><Label className="text-xs">Сума (EUR) *</Label><Input type="number" step="0.01" value={form.amount || ""} onChange={e => setForm({...form, amount: e.target.value})} className="bg-background font-mono" /></div>
            <div><Label className="text-xs">Бележка</Label><Input value={form.notes || ""} onChange={e => setForm({...form, notes: e.target.value})} className="bg-background" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Отказ</Button>
            <Button onClick={() => handleSave("/overhead-snapshots", { ...form, amount: parseFloat(form.amount) || 0 })} disabled={saving || !form.amount} data-testid="save-oh-btn"><Check className="w-4 h-4 mr-1" />Запази</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ═══ CONFIRM DIALOG ═══ */}
      <Dialog open={!!confirmDialog} onOpenChange={() => setConfirmDialog(null)}>
        <DialogContent className="sm:max-w-[350px] bg-card border-border" data-testid="confirm-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><AlertTriangle className="w-5 h-5 text-amber-500" />Потвърждение</DialogTitle></DialogHeader>
          <p className="text-sm text-foreground py-2">{confirmDialog?.label}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDialog(null)}>Отказ</Button>
            <Button onClick={() => { confirmDialog?.onConfirm(); }} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700" data-testid="confirm-action-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}Потвърди
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
