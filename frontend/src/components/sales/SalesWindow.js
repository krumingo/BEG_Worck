/**
 * SalesWindow — FIFO sale modal with preview, margin protection, historical context.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Loader2, ShoppingCart, AlertTriangle, TrendingUp, TrendingDown, Minus, Check,
} from "lucide-react";
import { toast } from "sonner";

export default function SalesWindow({ open, onOpenChange, presetItemId }) {
  const [items, setItems] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [margins, setMargins] = useState({ low: 20, medium: 30, high: 50, minimum: 15 });

  // Form
  const [itemId, setItemId] = useState(presetItemId || "");
  const [warehouseId, setWarehouseId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [clientId, setClientId] = useState("");
  const [projectId, setProjectId] = useState("");

  // Preview
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [history, setHistory] = useState(null);

  // Protection
  const [acknowledged, setAcknowledged] = useState(false);
  const [reason, setReason] = useState("");

  // Submit
  const [submitting, setSubmitting] = useState(false);

  const debounceRef = useRef(null);

  // Load base data
  useEffect(() => {
    if (!open) return;
    setPreview(null); setHistory(null); setAcknowledged(false); setReason(""); setUnitPrice("");
    Promise.all([
      API.get("/items?page_size=500"),
      API.get("/warehouses"),
      API.get("/settings/sales-margins"),
    ]).then(([iRes, wRes, mRes]) => {
      setItems(iRes.data?.items || iRes.data || []);
      setWarehouses(wRes.data?.items || wRes.data || []);
      setMargins(mRes.data || { low: 20, medium: 30, high: 50, minimum: 15 });
    }).catch(() => {});
    if (presetItemId) setItemId(presetItemId);
  }, [open, presetItemId]);

  // Debounced FIFO preview
  const triggerPreview = useCallback(() => {
    if (!itemId || !warehouseId || !quantity || parseFloat(quantity) <= 0) {
      setPreview(null); return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setPreviewLoading(true);
      try {
        const res = await API.post("/sales/fifo-preview", {
          item_id: itemId, warehouse_id: warehouseId, quantity: parseFloat(quantity),
        });
        setPreview(res.data);
      } catch { setPreview(null); }
      finally { setPreviewLoading(false); }
    }, 400);
  }, [itemId, warehouseId, quantity]);

  useEffect(() => { triggerPreview(); }, [triggerPreview]);

  // Historical context
  useEffect(() => {
    if (!itemId || !open) { setHistory(null); return; }
    API.get(`/sales/historical-context?item_id=${itemId}`).then(r => setHistory(r.data)).catch(() => setHistory(null));
  }, [itemId, open]);

  // Derived values
  const cost = preview?.weighted_avg_cost || 0;
  const totalCost = preview?.total_cost || 0;
  const qty = parseFloat(quantity) || 0;
  const price = parseFloat(unitPrice) || 0;
  const profit = round2((price - cost) * qty);
  const marginPct = cost > 0 ? round1((price - cost) / cost * 100) : 0;
  const minPrice = round2(cost * (1 + margins.minimum / 100));

  // Protection level
  let level = "ok"; // green
  if (price > 0 && cost > 0) {
    if (price < cost) level = "critical"; // red
    else if (price < minPrice) level = "warning"; // yellow
  }

  const canSubmit = preview?.available && price > 0 && qty > 0 && (
    level === "ok" ||
    (level === "warning" && acknowledged) ||
    (level === "critical" && acknowledged && reason.trim().length >= 10)
  );

  const setMarginPrice = (pct) => {
    if (cost > 0) setUnitPrice(round2(cost * (1 + pct / 100)).toString());
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const res = await API.post("/sales/commit", {
        item_id: itemId, warehouse_id: warehouseId, quantity: qty,
        unit_sale_price: price, currency: "BGN",
        client_id: clientId || null, project_id: projectId || null,
        snapshot_token: preview.snapshot_token,
        warning_acknowledged: acknowledged,
        warning_reason: reason,
      });
      toast.success(`Продажба записана: ${res.data.total_sale} BGN (марж ${res.data.margin_percent}%)`);
      onOpenChange(false);
    } catch (err) {
      const detail = err.response?.data?.detail || "Грешка";
      if (err.response?.status === 409) {
        toast.error("Наличността се промени, презареждам...");
        triggerPreview();
      } else {
        toast.error(detail);
      }
    } finally { setSubmitting(false); }
  };

  const TREND_ICON = { rising: TrendingUp, falling: TrendingDown, stable: Minus };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><ShoppingCart className="w-5 h-5 text-primary" />Нова продажба</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* LEFT: Form + FIFO */}
          <div className="lg:col-span-2 space-y-4">
            {/* Section 1: Item & Qty */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Артикул *</Label>
                <Select value={itemId || "none"} onValueChange={v => { setItemId(v === "none" ? "" : v); setPreview(null); }}>
                  <SelectTrigger><SelectValue placeholder="Изберете..." /></SelectTrigger>
                  <SelectContent>{items.map(i => <SelectItem key={i.id} value={i.id}>{i.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Склад *</Label>
                <Select value={warehouseId || "none"} onValueChange={v => { setWarehouseId(v === "none" ? "" : v); setPreview(null); }}>
                  <SelectTrigger><SelectValue placeholder="Изберете..." /></SelectTrigger>
                  <SelectContent>{warehouses.map(w => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Количество *</Label>
                <Input type="number" value={quantity} onChange={e => setQuantity(e.target.value)} min="0.01" step="0.01" />
              </div>
            </div>

            {/* Section 2: FIFO breakdown */}
            {previewLoading && <div className="flex justify-center py-4"><Loader2 className="w-5 h-5 animate-spin" /></div>}
            {preview && !preview.available && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                <AlertTriangle className="w-4 h-4 inline mr-1" />
                Недостатъчна наличност: налични {preview.total_qty_in_stock}, липсват {preview.shortage}
              </div>
            )}
            {preview?.available && (
              <div className="rounded-lg border border-border p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-muted-foreground">FIFO разбивка</p>
                  <Badge variant="outline" className="text-[9px]">Себестойност: {preview.weighted_avg_cost} BGN/ед</Badge>
                </div>
                <Table>
                  <TableHeader><TableRow className="text-[10px]">
                    <TableHead>Партида</TableHead><TableHead className="text-right">Кол.</TableHead>
                    <TableHead className="text-right">Цена/ед</TableHead><TableHead className="text-right">Стойност</TableHead>
                    <TableHead>Дата</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {preview.fifo_breakdown.map((r, i) => (
                      <TableRow key={i} className="text-xs">
                        <TableCell className="font-mono text-primary">{r.batch_number}</TableCell>
                        <TableCell className="text-right font-mono">{r.qty_taken}</TableCell>
                        <TableCell className="text-right font-mono">{r.unit_price}</TableCell>
                        <TableCell className="text-right font-mono">{r.line_cost}</TableCell>
                        <TableCell className="text-muted-foreground">{r.received_at}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <div className="flex justify-between text-xs pt-1 border-t">
                  <span className="text-muted-foreground">Обща себестойност:</span>
                  <span className="font-bold font-mono">{preview.total_cost} BGN</span>
                </div>
              </div>
            )}

            {/* Section 3: Price & Margins */}
            {preview?.available && (
              <div className="space-y-3">
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" className="text-xs" onClick={() => setMarginPrice(margins.low)}>{margins.low}% марж</Button>
                  <Button variant="outline" size="sm" className="text-xs" onClick={() => setMarginPrice(margins.medium)}>{margins.medium}% марж</Button>
                  <Button variant="outline" size="sm" className="text-xs" onClick={() => setMarginPrice(margins.high)}>{margins.high}% марж</Button>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div className="space-y-1">
                    <Label className="text-xs">Продажна цена/ед *</Label>
                    <Input type="number" value={unitPrice} onChange={e => { setUnitPrice(e.target.value); setAcknowledged(false); setReason(""); }} min="0" step="0.01"
                      className={level === "critical" ? "border-red-500" : level === "warning" ? "border-amber-500" : ""} />
                  </div>
                  <div className="rounded-lg border p-2 text-center">
                    <p className="text-[9px] text-muted-foreground">Печалба</p>
                    <p className={`text-sm font-bold font-mono ${profit >= 0 ? "text-emerald-400" : "text-red-400"}`}>{profit} BGN</p>
                  </div>
                  <div className="rounded-lg border p-2 text-center">
                    <p className="text-[9px] text-muted-foreground">Реален марж</p>
                    <p className={`text-sm font-bold font-mono ${marginPct >= margins.minimum ? "text-emerald-400" : marginPct >= 0 ? "text-amber-400" : "text-red-400"}`}>{marginPct}%</p>
                  </div>
                </div>

                {/* Protection warnings */}
                {level === "warning" && (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 space-y-2">
                    <p className="text-xs text-amber-400"><AlertTriangle className="w-3.5 h-3.5 inline mr-1" />Цената е под минималния марж ({margins.minimum}%)</p>
                    <label className="flex items-center gap-2 text-xs"><Checkbox checked={acknowledged} onCheckedChange={setAcknowledged} />Разбирам и продължавам</label>
                  </div>
                )}
                {level === "critical" && (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 space-y-2">
                    <p className="text-xs text-red-400 font-bold"><AlertTriangle className="w-3.5 h-3.5 inline mr-1" />ВНИМАНИЕ: Цената е под себестойност!</p>
                    <label className="flex items-center gap-2 text-xs"><Checkbox checked={acknowledged} onCheckedChange={setAcknowledged} />Разбирам и продължавам</label>
                    <Textarea value={reason} onChange={e => setReason(e.target.value)} placeholder="Причина (мин. 10 символа)..." className="text-xs min-h-[50px]" />
                  </div>
                )}

                {/* Submit */}
                <Button onClick={handleSubmit} disabled={!canSubmit || submitting} className="w-full h-11">
                  {submitting ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Check className="w-4 h-4 mr-2" />}
                  Потвърди продажба
                </Button>
              </div>
            )}
          </div>

          {/* RIGHT: Historical context */}
          <div className="space-y-3">
            {history && !history.insufficient_data ? (
              <div className="rounded-lg border border-border p-3 space-y-2">
                <p className="text-xs font-semibold text-muted-foreground">Историческа справка ({history.period_months}м)</p>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div><span className="text-muted-foreground">Мин:</span> <span className="font-mono">{history.min_price}</span></div>
                  <div><span className="text-muted-foreground">Макс:</span> <span className="font-mono">{history.max_price}</span></div>
                  <div><span className="text-muted-foreground">Средна:</span> <span className="font-mono">{history.avg_price}</span></div>
                  <div><span className="text-muted-foreground">Медиана:</span> <span className="font-mono">{history.median_price}</span></div>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">Тренд:</span>
                  {(() => { const I = TREND_ICON[history.trend] || Minus; const c = history.trend === "rising" ? "text-emerald-400" : history.trend === "falling" ? "text-red-400" : "text-gray-400"; return <I className={`w-4 h-4 ${c}`} />; })()}
                  <span>{history.sales_count} продажби</span>
                </div>
                {history.last_sale && (
                  <div className="text-[10px] text-muted-foreground pt-1 border-t">
                    Последна: {history.last_sale.date} — {history.last_sale.price} BGN × {history.last_sale.quantity}
                  </div>
                )}
              </div>
            ) : history?.insufficient_data ? (
              <div className="rounded-lg border border-border p-3 text-xs text-muted-foreground text-center">Няма достатъчно история</div>
            ) : null}

            {/* Margin config */}
            <div className="rounded-lg border border-border p-3 text-[10px] text-muted-foreground space-y-1">
              <p className="font-semibold">Маржови настройки</p>
              <p>Нисък: {margins.low}% | Среден: {margins.medium}% | Висок: {margins.high}%</p>
              <p>Минимален: {margins.minimum}%</p>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function round2(n) { return Math.round(n * 100) / 100; }
function round1(n) { return Math.round(n * 10) / 10; }
