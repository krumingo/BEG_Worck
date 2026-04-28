/**
 * SalesHistoryTable — Sales list with filters, summary cards, detail modal.
 */
import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Loader2, TrendingUp, DollarSign, AlertTriangle, Eye, ShoppingCart,
} from "lucide-react";

export default function SalesHistoryTable() {
  const [data, setData] = useState([]);
  const [summary, setSummary] = useState({});
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [warningOnly, setWarningOnly] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  // Detail modal
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, page_size: 25, sort_by: "date", sort_dir: "desc" });
      if (warningOnly) params.set("has_warning", "true");
      if (dateFrom) params.set("from_date", dateFrom);
      if (dateTo) params.set("to_date", dateTo);
      const res = await API.get(`/sales/history?${params}`);
      setData(res.data.data || []);
      setSummary(res.data.summary || {});
      setTotal(res.data.total_count || 0);
    } catch { setData([]); }
    finally { setLoading(false); }
  }, [page, warningOnly, dateFrom, dateTo]);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (saleId) => {
    try {
      const res = await API.get(`/sales/${saleId}/details`);
      setDetail(res.data);
      setDetailOpen(true);
    } catch {}
  };

  const totalPages = Math.ceil(total / 25);

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-xl border p-3">
          <p className="text-[10px] text-muted-foreground">Общи приходи</p>
          <p className="text-lg font-bold font-mono text-emerald-400">{(summary.total_revenue || 0).toLocaleString("bg-BG")} BGN</p>
        </div>
        <div className="rounded-xl border p-3">
          <p className="text-[10px] text-muted-foreground">Себестойност</p>
          <p className="text-lg font-bold font-mono">{(summary.total_cost || 0).toLocaleString("bg-BG")} BGN</p>
        </div>
        <div className="rounded-xl border p-3">
          <p className="text-[10px] text-muted-foreground">Печалба</p>
          <p className={`text-lg font-bold font-mono ${(summary.total_profit || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>{(summary.total_profit || 0).toLocaleString("bg-BG")} BGN</p>
        </div>
        <div className="rounded-xl border p-3">
          <p className="text-[10px] text-muted-foreground">Среден марж</p>
          <p className="text-lg font-bold font-mono">{summary.avg_margin_percent || 0}%</p>
          {summary.warnings_count > 0 && <Badge className="text-[8px] bg-amber-500/20 text-amber-400 mt-1">{summary.warnings_count} warnings</Badge>}
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Input type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setPage(1); }} className="h-9 w-[140px] text-xs" />
        <span className="text-xs text-muted-foreground">—</span>
        <Input type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); setPage(1); }} className="h-9 w-[140px] text-xs" />
        <label className="flex items-center gap-1.5 text-xs"><Checkbox checked={warningOnly} onCheckedChange={v => { setWarningOnly(v); setPage(1); }} /><AlertTriangle className="w-3 h-3 text-amber-400" />Само warnings</label>
        <span className="text-xs text-muted-foreground ml-auto">{total} продажби</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : data.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <ShoppingCart className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p>Няма продажби по тези филтри</p>
        </div>
      ) : (
        <div className="rounded-xl border bg-card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="text-[10px] hover:bg-transparent">
                <TableHead>Дата</TableHead>
                <TableHead>Артикул</TableHead>
                <TableHead>Склад</TableHead>
                <TableHead className="text-right">Кол.</TableHead>
                <TableHead className="text-right">Цена</TableHead>
                <TableHead className="text-right">Приход</TableHead>
                <TableHead className="text-right">Себ-ст</TableHead>
                <TableHead className="text-right">Печалба</TableHead>
                <TableHead className="text-right">Марж</TableHead>
                <TableHead className="w-12"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map(s => (
                <TableRow key={s.sale_id} className="text-xs hover:bg-muted/20">
                  <TableCell className="text-muted-foreground">{(s.date || "").slice(0, 10)}</TableCell>
                  <TableCell className="font-medium truncate max-w-[120px]">{s.item_name || "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{s.warehouse_name}</TableCell>
                  <TableCell className="text-right font-mono">{s.quantity}</TableCell>
                  <TableCell className="text-right font-mono">{s.unit_sale_price}</TableCell>
                  <TableCell className="text-right font-mono">{s.total_sale}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">{s.total_cost}</TableCell>
                  <TableCell className={`text-right font-mono font-bold ${s.profit_amount >= 0 ? "text-emerald-400" : "text-red-400"}`}>{s.profit_amount}</TableCell>
                  <TableCell className={`text-right font-mono ${s.margin_percent >= 15 ? "text-emerald-400" : s.margin_percent >= 0 ? "text-amber-400" : "text-red-400"}`}>{s.margin_percent}%</TableCell>
                  <TableCell>
                    <div className="flex gap-0.5">
                      {s.warning_flag && <AlertTriangle className="w-3.5 h-3.5 text-red-400" />}
                      <button onClick={() => openDetail(s.sale_id)} className="p-1 hover:text-primary"><Eye className="w-3.5 h-3.5" /></button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 text-xs">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="h-7">←</Button>
          <span className="flex items-center text-muted-foreground">{page} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="h-7">→</Button>
        </div>
      )}

      {/* Detail Modal */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
          {detail && (
            <>
              <DialogHeader><DialogTitle className="flex items-center gap-2"><ShoppingCart className="w-5 h-5 text-primary" />Продажба: {detail.item_name}</DialogTitle></DialogHeader>
              <div className="space-y-4 text-sm">
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div><span className="text-muted-foreground">Дата:</span> {(detail.created_at || "").slice(0, 10)}</div>
                  <div><span className="text-muted-foreground">Количество:</span> {detail.quantity}</div>
                  <div><span className="text-muted-foreground">Ед. цена:</span> {detail.unit_sale_price} {detail.currency}</div>
                  <div><span className="text-muted-foreground">Общо:</span> {detail.total_sale_amount} {detail.currency}</div>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-lg border p-2"><p className="text-lg font-bold">{detail.total_sale_amount}</p><p className="text-[9px] text-muted-foreground">Приход</p></div>
                  <div className="rounded-lg border p-2"><p className="text-lg font-bold text-muted-foreground">{detail.cost_at_sale}</p><p className="text-[9px] text-muted-foreground">Себестойност</p></div>
                  <div className="rounded-lg border p-2"><p className={`text-lg font-bold ${detail.profit_amount >= 0 ? "text-emerald-400" : "text-red-400"}`}>{detail.profit_amount}</p><p className="text-[9px] text-muted-foreground">Печалба ({detail.margin_percent}%)</p></div>
                </div>
                {detail.fifo_allocations?.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground mb-1">FIFO разбивка:</p>
                    <Table>
                      <TableHeader><TableRow className="text-[10px]">
                        <TableHead>Партида</TableHead><TableHead className="text-right">Кол.</TableHead>
                        <TableHead className="text-right">Цена</TableHead><TableHead className="text-right">Стойност</TableHead>
                      </TableRow></TableHeader>
                      <TableBody>
                        {detail.fifo_allocations.map((a, i) => (
                          <TableRow key={i} className="text-xs">
                            <TableCell className="font-mono text-primary">{a.batch_number}</TableCell>
                            <TableCell className="text-right font-mono">{a.qty_taken}</TableCell>
                            <TableCell className="text-right font-mono">{a.unit_cost}</TableCell>
                            <TableCell className="text-right font-mono">{a.total_cost}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
                {detail.warning_flag && (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs">
                    <p className="text-red-400 font-semibold">Продажба под себестойност</p>
                    {detail.warning_reason && <p className="text-muted-foreground mt-1">Причина: {detail.warning_reason}</p>}
                  </div>
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
