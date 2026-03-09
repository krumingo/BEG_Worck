import { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
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
  Package, FileText, Plus, Loader2, Trash2, Search, Upload, Eye,
  ClipboardList, Warehouse, ArrowRight, Check, ExternalLink,
} from "lucide-react";

const REQ_STATUS = { draft: "Чернова", submitted: "Подадена", partially_fulfilled: "Частично", fulfilled: "Изпълнена", cancelled: "Отменена" };
const REQ_COLORS = { draft: "bg-gray-500/20 text-gray-400", submitted: "bg-blue-500/20 text-blue-400", partially_fulfilled: "bg-amber-500/20 text-amber-400", fulfilled: "bg-emerald-500/20 text-emerald-400", cancelled: "bg-red-500/20 text-red-400" };
const INV_STATUS = { uploaded: "Качена", reviewed: "Прегледана", posted_to_warehouse: "В склада" };
const INV_COLORS = { uploaded: "bg-blue-500/20 text-blue-400", reviewed: "bg-amber-500/20 text-amber-400", posted_to_warehouse: "bg-emerald-500/20 text-emerald-400" };

export default function ProcurementPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") || "requests";
  const [requests, setRequests] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [projects, setProjects] = useState([]);
  const [counterparties, setCounterparties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  // Dialogs
  const [invDialogOpen, setInvDialogOpen] = useState(false);
  const [invForm, setInvForm] = useState({ supplier_name: "", invoice_number: "", invoice_date: new Date().toISOString().split("T")[0], project_id: "", purchased_by: "", notes: "" });
  const [saving, setSaving] = useState(false);

  // Review dialog
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewInv, setReviewInv] = useState(null);
  const [reviewLines, setReviewLines] = useState([]);
  const [posting, setPosting] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [reqRes, invRes, projRes, cpRes] = await Promise.all([
        API.get("/material-requests"),
        API.get("/supplier-invoices"),
        API.get("/projects"),
        API.get("/counterparties").catch(() => ({ data: [] })),
      ]);
      setRequests(reqRes.data);
      setInvoices(invRes.data);
      setProjects(projRes.data);
      setCounterparties(cpRes.data?.items || cpRes.data || []);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Create supplier invoice
  const handleCreateInvoice = async () => {
    if (!invForm.invoice_number.trim()) return;
    setSaving(true);
    try {
      const res = await API.post("/supplier-invoices", invForm);
      setInvDialogOpen(false);
      // Open review for new invoice
      openReview(res.data);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  // Open review for invoice
  const openReview = async (inv) => {
    if (typeof inv === "string") {
      const res = await API.get(`/supplier-invoices/${inv}`);
      inv = res.data;
    }
    setReviewInv(inv);
    setReviewLines(inv.lines?.length > 0 ? inv.lines : [{ id: Date.now().toString(), material_name: "", qty: 1, unit: "бр", unit_price: 0, discount_percent: 0 }]);
    setReviewOpen(true);
  };

  // Save review
  const saveReview = async () => {
    if (!reviewInv) return;
    setSaving(true);
    try {
      await API.put(`/supplier-invoices/${reviewInv.id}`, { lines: reviewLines, status: "reviewed" });
      setReviewOpen(false);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  // Post to warehouse
  const postToWarehouse = async (invId) => {
    if (!window.confirm("Потвърдете приемане в Основен склад?")) return;
    setPosting(true);
    try {
      await API.post(`/supplier-invoices/${invId}/post-to-warehouse`);
      setReviewOpen(false);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setPosting(false); }
  };

  // Review line helpers
  const addReviewLine = () => setReviewLines([...reviewLines, { id: Date.now().toString(), material_name: "", qty: 1, unit: "бр", unit_price: 0, discount_percent: 0 }]);
  const removeReviewLine = (i) => setReviewLines(reviewLines.filter((_, idx) => idx !== i));
  const updateReviewLine = (i, f, v) => { const u = [...reviewLines]; u[i] = { ...u[i], [f]: v }; setReviewLines(u); };

  const filteredReqs = search ? requests.filter(r => r.request_number?.toLowerCase().includes(search.toLowerCase()) || r.project_code?.toLowerCase().includes(search.toLowerCase())) : requests;
  const filteredInvs = search ? invoices.filter(r => r.invoice_number?.toLowerCase().includes(search.toLowerCase()) || r.supplier_name?.toLowerCase().includes(search.toLowerCase())) : invoices;

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  return (
    <div className="p-6 max-w-[1400px]" data-testid="procurement-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2"><Package className="w-6 h-6 text-amber-500" /> Снабдяване</h1>
          <p className="text-sm text-muted-foreground mt-1">Заявки за материали, входящи фактури и складов прием</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => { setInvForm({ supplier_name: "", invoice_number: "", invoice_date: new Date().toISOString().split("T")[0], project_id: "", purchased_by: "", notes: "" }); setInvDialogOpen(true); }} data-testid="new-invoice-btn">
            <Plus className="w-4 h-4 mr-1" /> Входяща фактура
          </Button>
        </div>
      </div>

      <div className="relative max-w-[300px] mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input placeholder="Търсене..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9 bg-card" />
      </div>

      <Tabs value={tab} onValueChange={v => setSearchParams({ tab: v })}>
        <TabsList className="mb-4">
          <TabsTrigger value="requests" data-testid="tab-requests"><ClipboardList className="w-4 h-4 mr-1" /> Заявки ({requests.length})</TabsTrigger>
          <TabsTrigger value="invoices" data-testid="tab-invoices"><FileText className="w-4 h-4 mr-1" /> Входящи фактури ({invoices.length})</TabsTrigger>
        </TabsList>

        {/* Material Requests Tab */}
        <TabsContent value="requests">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="requests-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Номер</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Проект</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Етап</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Редове</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Нужна дата</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Дата</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {filteredReqs.length === 0 ? (
                  <TableRow><TableCell colSpan={7} className="text-center py-12 text-muted-foreground"><ClipboardList className="w-10 h-10 mx-auto mb-3 opacity-30" /><p>Няма заявки</p></TableCell></TableRow>
                ) : filteredReqs.map(r => (
                  <TableRow key={r.id} className="cursor-pointer hover:bg-muted/30" data-testid={`req-row-${r.id}`}>
                    <TableCell className="font-mono text-sm text-primary">{r.request_number}</TableCell>
                    <TableCell className="text-sm">{r.project_code} {r.project_name}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{r.stage_name || "—"}</TableCell>
                    <TableCell className="text-sm font-mono">{r.lines?.length || 0}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{r.needed_date ? formatDate(r.needed_date) : "—"}</TableCell>
                    <TableCell><Badge variant="outline" className={`text-[10px] ${REQ_COLORS[r.status] || ""}`}>{REQ_STATUS[r.status] || r.status}</Badge></TableCell>
                    <TableCell className="text-sm text-muted-foreground">{formatDate(r.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* Supplier Invoices Tab */}
        <TabsContent value="invoices">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="invoices-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Фактура №</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Доставчик</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Проект</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Дата</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Сума</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Документ</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Действия</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {filteredInvs.length === 0 ? (
                  <TableRow><TableCell colSpan={8} className="text-center py-12 text-muted-foreground"><FileText className="w-10 h-10 mx-auto mb-3 opacity-30" /><p>Няма входящи фактури</p></TableCell></TableRow>
                ) : filteredInvs.map(inv => (
                  <TableRow key={inv.id} className="hover:bg-muted/30" data-testid={`inv-row-${inv.id}`}>
                    <TableCell className="font-mono text-sm text-primary">{inv.invoice_number}</TableCell>
                    <TableCell className="text-sm">{inv.supplier_name || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{inv.project_code || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{formatDate(inv.invoice_date)}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{inv.total > 0 ? formatCurrency(inv.total, "BGN") : "—"}</TableCell>
                    <TableCell>
                      {inv.original_file_url ? (
                        <Button variant="ghost" size="sm" onClick={() => window.open(inv.original_file_url, '_blank')} className="text-xs text-primary"><Eye className="w-3 h-3 mr-1" /> Документ</Button>
                      ) : <span className="text-xs text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell><Badge variant="outline" className={`text-[10px] ${INV_COLORS[inv.status] || ""}`}>{INV_STATUS[inv.status] || inv.status}</Badge></TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {inv.status !== "posted_to_warehouse" && (
                          <Button variant="ghost" size="sm" onClick={() => openReview(inv.id)} data-testid={`review-btn-${inv.id}`}><Eye className="w-4 h-4" /></Button>
                        )}
                        {inv.status === "reviewed" && (
                          <Button variant="ghost" size="sm" onClick={() => postToWarehouse(inv.id)} className="text-emerald-400" data-testid={`post-btn-${inv.id}`}><Warehouse className="w-4 h-4" /></Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>

      {/* New Invoice Dialog */}
      <Dialog open={invDialogOpen} onOpenChange={setInvDialogOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="new-invoice-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><FileText className="w-5 h-5 text-primary" /> Нова входяща фактура</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label>Фактура № *</Label><Input value={invForm.invoice_number} onChange={e => setInvForm({...invForm, invoice_number: e.target.value})} className="bg-background font-mono" data-testid="inv-number" /></div>
              <div className="space-y-1"><Label>Дата *</Label><Input type="date" value={invForm.invoice_date} onChange={e => setInvForm({...invForm, invoice_date: e.target.value})} className="bg-background" /></div>
            </div>
            <div className="space-y-1"><Label>Доставчик</Label><Input value={invForm.supplier_name} onChange={e => setInvForm({...invForm, supplier_name: e.target.value})} placeholder="Име на доставчик" className="bg-background" data-testid="inv-supplier" /></div>
            <div className="space-y-1">
              <Label>Проект</Label>
              <Select value={invForm.project_id || "none"} onValueChange={v => setInvForm({...invForm, project_id: v === "none" ? "" : v})}>
                <SelectTrigger className="bg-background"><SelectValue placeholder="Без проект" /></SelectTrigger>
                <SelectContent><SelectItem value="none">Без проект</SelectItem>{projects.map(p => <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Купил</Label><Input value={invForm.purchased_by} onChange={e => setInvForm({...invForm, purchased_by: e.target.value})} placeholder="Име на купуващия" className="bg-background" /></div>
            <div className="space-y-1"><Label>Бележки</Label><Textarea value={invForm.notes} onChange={e => setInvForm({...invForm, notes: e.target.value})} className="bg-background min-h-[50px]" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setInvDialogOpen(false)}>Затвори</Button>
            <Button onClick={handleCreateInvoice} disabled={saving || !invForm.invoice_number.trim()} data-testid="save-invoice-btn">{saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Plus className="w-4 h-4 mr-1" />} Създай</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Review/Correction Dialog */}
      <Dialog open={reviewOpen} onOpenChange={setReviewOpen}>
        <DialogContent className="sm:max-w-[800px] bg-card border-border max-h-[90vh] overflow-y-auto" data-testid="review-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Eye className="w-5 h-5 text-amber-500" /> Преглед: {reviewInv?.invoice_number}</DialogTitle></DialogHeader>
          {reviewInv && (
            <div className="space-y-4 py-2">
              {/* Header info */}
              <div className="grid grid-cols-3 gap-3 text-sm p-3 rounded-lg bg-muted/30 border border-border">
                <div><span className="text-muted-foreground">Доставчик:</span> <span className="text-foreground">{reviewInv.supplier_name || "—"}</span></div>
                <div><span className="text-muted-foreground">Дата:</span> <span className="text-foreground">{reviewInv.invoice_date}</span></div>
                <div><span className="text-muted-foreground">Купил:</span> <span className="text-foreground">{reviewInv.purchased_by || "—"}</span></div>
              </div>

              {reviewInv.original_file_url && (
                <Button variant="outline" size="sm" onClick={() => window.open(reviewInv.original_file_url, '_blank')} className="text-primary"><ExternalLink className="w-4 h-4 mr-1" /> Оригинален документ</Button>
              )}

              {/* Lines */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <Label className="text-sm font-medium">Редове</Label>
                  <Button size="sm" variant="outline" onClick={addReviewLine}><Plus className="w-3 h-3 mr-1" /> Добави</Button>
                </div>
                <div className="space-y-2">
                  {reviewLines.map((line, i) => {
                    const qty = parseFloat(line.qty) || 0;
                    const up = parseFloat(line.unit_price) || 0;
                    const disc = parseFloat(line.discount_percent) || 0;
                    const finalUp = up * (1 - disc / 100);
                    const total = qty * finalUp;
                    return (
                      <div key={line.id || i} className="grid grid-cols-12 gap-2 items-end p-2 rounded bg-muted/20 border border-border" data-testid={`review-line-${i}`}>
                        <div className="col-span-3"><Input value={line.material_name} onChange={e => updateReviewLine(i, "material_name", e.target.value)} placeholder="Материал" className="bg-background text-sm h-8" /></div>
                        <div className="col-span-1"><Input type="number" value={line.qty} onChange={e => updateReviewLine(i, "qty", e.target.value)} className="bg-background text-sm h-8 font-mono" /></div>
                        <div className="col-span-1"><Input value={line.unit} onChange={e => updateReviewLine(i, "unit", e.target.value)} className="bg-background text-sm h-8" /></div>
                        <div className="col-span-1"><Input value={line.dimension_spec || ""} onChange={e => updateReviewLine(i, "dimension_spec", e.target.value)} placeholder="Разм." className="bg-background text-sm h-8" /></div>
                        <div className="col-span-2"><Input type="number" step="0.01" value={line.unit_price} onChange={e => updateReviewLine(i, "unit_price", e.target.value)} placeholder="Цена" className="bg-background text-sm h-8 font-mono" /></div>
                        <div className="col-span-1"><Input type="number" step="0.1" value={line.discount_percent} onChange={e => updateReviewLine(i, "discount_percent", e.target.value)} placeholder="%" className="bg-background text-sm h-8 font-mono" /></div>
                        <div className="col-span-2 flex items-center gap-1">
                          <span className="font-mono text-sm text-foreground">{total.toFixed(2)}</span>
                          <Button variant="ghost" size="sm" onClick={() => removeReviewLine(i)} className="text-destructive h-7 w-7 p-0"><Trash2 className="w-3 h-3" /></Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="text-right mt-2 font-mono text-sm">
                  Общо: <span className="font-bold text-primary">{reviewLines.reduce((s, l) => s + (parseFloat(l.qty) || 0) * ((parseFloat(l.unit_price) || 0) * (1 - (parseFloat(l.discount_percent) || 0) / 100)), 0).toFixed(2)} лв</span>
                </div>
              </div>
            </div>
          )}
          <DialogFooter className="flex-col sm:flex-row gap-2">
            <Button variant="outline" onClick={() => setReviewOpen(false)}>Затвори</Button>
            <Button onClick={saveReview} disabled={saving} data-testid="save-review-btn">{saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />} Запази преглед</Button>
            {reviewInv?.status === "reviewed" && (
              <Button onClick={() => postToWarehouse(reviewInv.id)} disabled={posting} className="bg-emerald-600 hover:bg-emerald-700" data-testid="post-warehouse-btn">
                {posting ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Warehouse className="w-4 h-4 mr-1" />} Приеми в склад
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
