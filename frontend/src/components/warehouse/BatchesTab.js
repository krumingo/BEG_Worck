/**
 * BatchesTab — FIFO batch list with filters, table, new batch modal, trace modal.
 */
import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Plus, Loader2, Package, Lock, Unlock, Eye, Trash2, Search, AlertTriangle, ShoppingCart,
} from "lucide-react";
import { toast } from "sonner";
import SalesWindow from "@/components/sales/SalesWindow";

const STATUS_CFG = {
  active: { label: "Активна", cls: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" },
  depleted: { label: "Изчерпана", cls: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
  blocked: { label: "Блокирана", cls: "bg-red-500/20 text-red-400 border-red-500/30" },
};

export default function BatchesTab() {
  const [batches, setBatches] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("active");
  const [searchText, setSearchText] = useState("");
  const [warehouses, setWarehouses] = useState([]);
  const [whFilter, setWhFilter] = useState("");

  // Modals
  const [newOpen, setNewOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceBatch, setTraceBatch] = useState(null);
  const [items, setItems] = useState([]);
  const [saleOpen, setSaleOpen] = useState(false);
  const [saleItemId, setSaleItemId] = useState("");
  const [saleWhId, setSaleWhId] = useState("");

  // New batch form
  const [form, setForm] = useState({
    item_id: "", warehouse_id: "", qty: "", unit_cost: "", currency: "BGN",
    supplier_id: "", invoice_number: "", invoice_date: "", notes: "",
  });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, page_size: 25 });
      if (statusFilter && statusFilter !== "all") params.set("status", statusFilter);
      if (whFilter) params.set("warehouse_id", whFilter);
      const res = await API.get(`/warehouse/batches?${params}`);
      let list = res.data.items || [];
      if (searchText) {
        const q = searchText.toLowerCase();
        list = list.filter(b =>
          (b.batch_number || "").toLowerCase().includes(q) ||
          (b.invoice_number || "").toLowerCase().includes(q)
        );
      }
      setBatches(list);
      setTotal(res.data.total || 0);
    } catch { setBatches([]); }
    finally { setLoading(false); }
  }, [page, statusFilter, whFilter, searchText]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    API.get("/warehouses").then(r => setWarehouses(r.data?.items || r.data || [])).catch(() => {});
    API.get("/items?page_size=200").then(r => setItems(r.data?.items || r.data || [])).catch(() => {});
  }, []);

  const handleCreate = async () => {
    if (!form.item_id || !form.warehouse_id || !form.qty || !form.unit_cost) {
      toast.error("Попълнете задължителните полета"); return;
    }
    setSaving(true);
    try {
      await API.post("/warehouse/batches", {
        ...form,
        qty: parseFloat(form.qty),
        unit_cost: parseFloat(form.unit_cost),
        source_type: "purchase",
      });
      toast.success("Партида създадена");
      setNewOpen(false);
      setForm({ item_id: "", warehouse_id: "", qty: "", unit_cost: "", currency: "BGN", supplier_id: "", invoice_number: "", invoice_date: "", notes: "" });
      load();
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  const handleBlock = async (batch) => {
    const action = batch.status === "blocked" ? "разблокирате" : "блокирате";
    if (!window.confirm(`Сигурни ли сте, че искате да ${action} партида ${batch.batch_number}?`)) return;
    try {
      await API.put(`/warehouse/batches/${batch.id}/block`);
      toast.success(`Партида ${batch.status === "blocked" ? "разблокирана" : "блокирана"}`);
      load();
    } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
  };

  const openTrace = async (batch) => {
    setTraceBatch(batch);
    setTraceOpen(true);
  };

  const pctColor = (remaining, initial) => {
    if (remaining <= 0) return "text-red-400";
    const pct = (remaining / initial) * 100;
    return pct < 20 ? "text-amber-400" : "text-emerald-400";
  };

  const totalPages = Math.ceil(total / 25);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[180px] max-w-[280px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input placeholder="Търси по партида / фактура..." value={searchText} onChange={e => setSearchText(e.target.value)} className="pl-9 h-9 text-xs" />
        </div>
        <Select value={whFilter || "all"} onValueChange={v => { setWhFilter(v === "all" ? "" : v); setPage(1); }}>
          <SelectTrigger className="w-[160px] h-9 text-xs"><SelectValue placeholder="Склад" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Всички складове</SelectItem>
            {warehouses.map(w => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={v => { setStatusFilter(v); setPage(1); }}>
          <SelectTrigger className="w-[140px] h-9 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Всички</SelectItem>
            <SelectItem value="active">Активни</SelectItem>
            <SelectItem value="depleted">Изчерпани</SelectItem>
            <SelectItem value="blocked">Блокирани</SelectItem>
          </SelectContent>
        </Select>
        <div className="ml-auto">
          <Button size="sm" onClick={() => setNewOpen(true)}><Plus className="w-4 h-4 mr-1" />Нова партида</Button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : batches.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <Package className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p>Няма партиди по тези филтри</p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs">Партида</TableHead>
                <TableHead className="text-xs">Артикул</TableHead>
                <TableHead className="text-xs">Склад</TableHead>
                <TableHead className="text-xs">Фактура</TableHead>
                <TableHead className="text-xs text-right">Получено</TableHead>
                <TableHead className="text-xs text-right">Остатък</TableHead>
                <TableHead className="text-xs text-right">Цена/ед</TableHead>
                <TableHead className="text-xs text-right">Стойност</TableHead>
                <TableHead className="text-xs">Дата</TableHead>
                <TableHead className="text-xs">Статус</TableHead>
                <TableHead className="text-xs w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {batches.map(b => {
                const st = STATUS_CFG[b.status] || STATUS_CFG.active;
                const value = ((b.remaining_qty || 0) * (b.unit_cost || 0)).toFixed(2);
                const itemName = items.find(i => i.id === b.item_id)?.name || b.item_id?.slice(0, 8);
                const whName = warehouses.find(w => w.id === b.warehouse_id)?.name || "—";
                return (
                  <TableRow key={b.id} className="text-xs hover:bg-muted/20">
                    <TableCell className="font-mono text-primary font-semibold">{b.batch_number}</TableCell>
                    <TableCell className="truncate max-w-[120px]">{itemName}</TableCell>
                    <TableCell className="text-muted-foreground">{whName}</TableCell>
                    <TableCell className="text-muted-foreground font-mono">{b.invoice_number || "—"}</TableCell>
                    <TableCell className="text-right font-mono">{b.initial_qty}</TableCell>
                    <TableCell className={`text-right font-mono font-bold ${pctColor(b.remaining_qty, b.initial_qty)}`}>{b.remaining_qty}</TableCell>
                    <TableCell className="text-right font-mono">{b.unit_cost} {b.currency}</TableCell>
                    <TableCell className="text-right font-mono">{value}</TableCell>
                    <TableCell className="text-muted-foreground">{(b.received_at || "").slice(0, 10)}</TableCell>
                    <TableCell><Badge variant="outline" className={`text-[9px] ${st.cls}`}>{st.label}</Badge></TableCell>
                    <TableCell>
                      <div className="flex gap-0.5">
                        <button onClick={() => openTrace(b)} className="p-1 hover:text-primary" title="Детайли"><Eye className="w-3.5 h-3.5" /></button>
                        {b.status === "active" && b.remaining_qty > 0 && (
                          <button onClick={() => { setSaleItemId(b.item_id); setSaleWhId(b.warehouse_id); setSaleOpen(true); }} className="p-1 hover:text-emerald-400" title="Продажба"><ShoppingCart className="w-3.5 h-3.5" /></button>
                        )}
                        <button onClick={() => handleBlock(b)} className="p-1 hover:text-amber-400" title={b.status === "blocked" ? "Разблокирай" : "Блокирай"}>
                          {b.status === "blocked" ? <Unlock className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 text-xs">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="h-7">Назад</Button>
          <span className="flex items-center text-muted-foreground">{page} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="h-7">Напред</Button>
        </div>
      )}

      {/* New Batch Modal */}
      <Dialog open={newOpen} onOpenChange={setNewOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>Нова партида</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Артикул *</Label>
              <Select value={form.item_id || "none"} onValueChange={v => setForm({ ...form, item_id: v === "none" ? "" : v })}>
                <SelectTrigger><SelectValue placeholder="Изберете..." /></SelectTrigger>
                <SelectContent>{items.map(i => <SelectItem key={i.id} value={i.id}>{i.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Склад *</Label>
              <Select value={form.warehouse_id || "none"} onValueChange={v => setForm({ ...form, warehouse_id: v === "none" ? "" : v })}>
                <SelectTrigger><SelectValue placeholder="Изберете..." /></SelectTrigger>
                <SelectContent>{warehouses.map(w => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">Количество *</Label><Input type="number" value={form.qty} onChange={e => setForm({ ...form, qty: e.target.value })} min="0.01" step="0.01" /></div>
              <div className="space-y-1"><Label className="text-xs">Ед. цена *</Label><Input type="number" value={form.unit_cost} onChange={e => setForm({ ...form, unit_cost: e.target.value })} min="0" step="0.01" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">Фактура №</Label><Input value={form.invoice_number} onChange={e => setForm({ ...form, invoice_number: e.target.value })} /></div>
              <div className="space-y-1"><Label className="text-xs">Дата фактура</Label><Input type="date" value={form.invoice_date} onChange={e => setForm({ ...form, invoice_date: e.target.value })} /></div>
            </div>
            <div className="space-y-1"><Label className="text-xs">Бележки</Label><Input value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewOpen(false)}>Отказ</Button>
            <Button onClick={handleCreate} disabled={saving}>{saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Plus className="w-4 h-4 mr-1" />}Създай</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Trace Modal */}
      <Dialog open={traceOpen} onOpenChange={setTraceOpen}>
        <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
          {traceBatch && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Package className="w-5 h-5 text-primary" />
                  {traceBatch.batch_number}
                  <Badge variant="outline" className={`text-[10px] ${(STATUS_CFG[traceBatch.status] || {}).cls}`}>{(STATUS_CFG[traceBatch.status] || {}).label}</Badge>
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-4 text-sm">
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div><span className="text-muted-foreground">Тип:</span> {traceBatch.source_type}</div>
                  <div><span className="text-muted-foreground">Валута:</span> {traceBatch.currency}</div>
                  <div><span className="text-muted-foreground">Фактура:</span> {traceBatch.invoice_number || "—"}</div>
                  <div><span className="text-muted-foreground">Дата:</span> {(traceBatch.invoice_date || traceBatch.received_at || "").slice(0, 10)}</div>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-lg border p-2"><p className="text-lg font-bold">{traceBatch.initial_qty}</p><p className="text-[9px] text-muted-foreground">Получено</p></div>
                  <div className="rounded-lg border p-2"><p className="text-lg font-bold text-red-400">{(traceBatch.initial_qty - traceBatch.remaining_qty).toFixed(2)}</p><p className="text-[9px] text-muted-foreground">Изписано</p></div>
                  <div className="rounded-lg border p-2"><p className={`text-lg font-bold ${pctColor(traceBatch.remaining_qty, traceBatch.initial_qty)}`}>{traceBatch.remaining_qty}</p><p className="text-[9px] text-muted-foreground">Остатък</p></div>
                </div>
                <div>
                  <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.max(0, (traceBatch.remaining_qty / traceBatch.initial_qty) * 100)}%` }} />
                  </div>
                </div>
                {traceBatch.notes && <p className="text-xs text-muted-foreground italic">{traceBatch.notes}</p>}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <SalesWindow open={saleOpen} onOpenChange={(v) => { setSaleOpen(v); if (!v) load(); }} presetItemId={saleItemId} prefillWarehouseId={saleWhId} />
    </div>
  );
}
