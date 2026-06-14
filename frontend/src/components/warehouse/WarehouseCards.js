import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Warehouse, MapPin, Package, Wrench, Boxes, Eye, Pencil, Archive,
  Loader2, Camera, ArrowRightLeft, Printer, AlertTriangle, History,
} from "lucide-react";

const STATUS_LABELS = {
  available: { label: "наличен", cls: "text-emerald-400 bg-emerald-500/10" },
  in_use: { label: "зает", cls: "text-amber-400 bg-amber-500/10" },
  repair: { label: "в ремонт", cls: "text-blue-400 bg-blue-500/10" },
  written_off: { label: "бракуван", cls: "text-muted-foreground bg-muted" },
};
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("bg-BG") : "—");

export default function WarehouseCards({ refreshKey, onEdit, onArchive, onQr }) {
  const [warehouses, setWarehouses] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);   // избран склад
  const [detailUnits, setDetailUnits] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [wh, sum] = await Promise.all([
        API.get("/warehouses?active_only=true&page_size=200"),
        API.get("/warehouses/asset-summary"),
      ]);
      setWarehouses(wh.data?.items || []);
      setSummary(sum.data?.summary || {});
    } catch {
      setWarehouses([]);
      setSummary({});
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  const openDetail = async (wh) => {
    setDetail(wh);
    setDetailUnits(null);
    try {
      const r = await API.get(`/assets/units?location_type=warehouse&location_id=${wh.id}&page_size=300`);
      setDetailUnits(r.data?.items || []);
    } catch {
      setDetailUnits([]);
    }
  };

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>;
  }

  if (warehouses.length === 0) {
    return <div className="text-center py-12 text-muted-foreground text-sm">Няма складове.</div>;
  }

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {warehouses.map((wh) => {
          const s = summary[wh.id] || { machines: 0, tools: 0, value: 0 };
          return (
            <div key={wh.id} className="rounded-xl border border-border bg-card p-4" data-testid={`wh-card-${wh.id}`}>
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <Warehouse className="w-5 h-5 text-primary" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-base truncate">{wh.name}</p>
                    {wh.address && <p className="text-xs text-muted-foreground flex items-center gap-1 truncate"><MapPin className="w-3 h-3 shrink-0" />{wh.address}</p>}
                  </div>
                </div>
                <Badge variant="outline" className="text-emerald-400 border-emerald-500/30 shrink-0">Активен</Badge>
              </div>

              <div className="grid grid-cols-3 gap-2 mb-3">
                <div className="bg-muted/40 rounded-lg p-2.5 text-center">
                  <Package className="w-4 h-4 mx-auto text-primary" />
                  <p className="text-xl font-semibold mt-1">{s.machines}</p>
                  <p className="text-[10px] text-muted-foreground">Машини</p>
                </div>
                <div className="bg-muted/40 rounded-lg p-2.5 text-center">
                  <Wrench className="w-4 h-4 mx-auto text-primary" />
                  <p className="text-xl font-semibold mt-1">{s.tools}</p>
                  <p className="text-[10px] text-muted-foreground">Инструменти</p>
                </div>
                <div className="bg-muted/40 rounded-lg p-2.5 text-center">
                  <Boxes className="w-4 h-4 mx-auto text-muted-foreground" />
                  <p className="text-xl font-semibold mt-1">0</p>
                  <p className="text-[10px] text-muted-foreground">Материали</p>
                </div>
              </div>

              {s.value > 0 && (
                <p className="text-xs text-muted-foreground mb-3">Стойност тук: <span className="text-emerald-400 font-medium">~{s.value.toLocaleString("bg-BG")} €</span></p>
              )}

              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" className="flex-1" onClick={() => openDetail(wh)} data-testid={`wh-detail-${wh.id}`}>
                  <Eye className="w-4 h-4 mr-1.5" />Детайли
                </Button>
                <Button variant="ghost" size="icon" onClick={() => onQr?.(wh)}><Printer className="w-4 h-4" /></Button>
                <Button variant="ghost" size="icon" onClick={() => onEdit?.(wh)}><Pencil className="w-4 h-4" /></Button>
                <Button variant="ghost" size="icon" onClick={() => onArchive?.(wh)}><Archive className="w-4 h-4 text-amber-500" /></Button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Детайл на склада */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-2xl max-h-[88vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Warehouse className="w-5 h-5 text-primary" />{detail?.name}
            </DialogTitle>
          </DialogHeader>

          {detail && (() => {
            const s = summary[detail.id] || { machines: 0, tools: 0, value: 0 };
            return (
              <div className="space-y-4">
                {detail.address && <p className="text-sm text-muted-foreground flex items-center gap-1"><MapPin className="w-4 h-4" />{detail.address}</p>}

                <div className="grid grid-cols-4 gap-2">
                  <div className="bg-muted/40 rounded-lg p-3 text-center"><p className="text-2xl font-semibold">{s.machines}</p><p className="text-[10px] text-muted-foreground">Машини</p></div>
                  <div className="bg-muted/40 rounded-lg p-3 text-center"><p className="text-2xl font-semibold">{s.tools}</p><p className="text-[10px] text-muted-foreground">Инструменти</p></div>
                  <div className="bg-muted/40 rounded-lg p-3 text-center"><p className="text-2xl font-semibold">0</p><p className="text-[10px] text-muted-foreground">Материали</p></div>
                  <div className="bg-muted/40 rounded-lg p-3 text-center"><p className="text-2xl font-semibold text-emerald-400">~{(s.value || 0).toLocaleString("bg-BG")}<span className="text-xs"> €</span></p><p className="text-[10px] text-muted-foreground">Стойност</p></div>
                </div>

                <div>
                  <p className="text-sm text-muted-foreground mb-2">Активи в склада</p>
                  {detailUnits === null ? (
                    <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-primary" /></div>
                  ) : detailUnits.length === 0 ? (
                    <p className="text-sm text-muted-foreground py-6 text-center">Няма активи в този склад.</p>
                  ) : (
                    <div className="rounded-lg border border-border overflow-hidden">
                      {detailUnits.map((u) => {
                        const st = STATUS_LABELS[u.status] || STATUS_LABELS.available;
                        return (
                          <div key={u.id} className="flex items-center gap-2.5 px-3 py-2.5 border-b border-border last:border-0">
                            <div className="w-7 h-7 rounded bg-muted flex items-center justify-center shrink-0 overflow-hidden">
                              {u.photo_url ? <img src={u.photo_url} alt="" className="w-full h-full object-cover" /> : <Wrench className="w-3.5 h-3.5 text-muted-foreground" />}
                            </div>
                            <span className="text-sm flex-1 truncate">{u.item_name} <span className="text-[10px] font-mono text-muted-foreground">{u.qr_id}</span></span>
                            <span className={`text-[10px] px-2 py-0.5 rounded ${st.cls}`}>{st.label}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>
    </>
  );
}
