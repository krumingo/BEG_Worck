import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { MapPin, Calendar, History, Loader2, Package, Wrench, Boxes } from "lucide-react";

const ACTION_LABELS = { take: "Взет", handover: "Предаден", drop: "Оставен", repair: "В ремонт", return: "Върнат", intake: "Заприходен" };
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("bg-BG") : "—");

export default function ProjectAssetsTab({ projectId }) {
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [moveHist, setMoveHist] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await API.get(`/assets/units?location_type=project&location_id=${projectId}&page_size=300`);
      setUnits(r.data?.items || []);
    } catch {
      setUnits([]);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { if (projectId) load(); }, [projectId, load]);

  const openHistory = async (unit) => {
    setMoveHist({ unit, items: null });
    try {
      const r = await API.get(`/assets/units/${unit.id}/movements`);
      setMoveHist({ unit, items: r.data?.items || [] });
    } catch {
      setMoveHist({ unit, items: [] });
    }
  };

  const machines = units.filter((u) => u.item_type === "machine").length;
  const tools = units.filter((u) => u.item_type !== "machine").length;

  if (loading) {
    return <div className="flex items-center gap-2 text-muted-foreground py-10 justify-center"><Loader2 className="w-5 h-5 animate-spin" /> Зареждане…</div>;
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground flex items-center gap-1"><Package className="w-3.5 h-3.5" />Машини</p>
          <p className="text-2xl font-semibold mt-0.5">{machines}</p>
        </div>
        <div className="rounded-lg bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground flex items-center gap-1"><Wrench className="w-3.5 h-3.5" />Инструменти</p>
          <p className="text-2xl font-semibold mt-0.5">{tools}</p>
        </div>
        <div className="rounded-lg bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground flex items-center gap-1"><Boxes className="w-3.5 h-3.5" />Материали</p>
          <p className="text-2xl font-semibold mt-0.5">0</p>
        </div>
      </div>

      {units.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground text-sm">Няма активи на този обект.</div>
      ) : (
        <div className="rounded-xl border border-border overflow-hidden">
          <div className="grid grid-cols-[2fr_1.2fr_1.1fr_0.7fr] gap-3 px-4 py-2.5 border-b border-border text-xs text-muted-foreground">
            <span>Актив</span><span>Тип</span><span>Откога тук</span><span className="text-right">История</span>
          </div>
          {units.map((u) => (
            <div key={u.id} className="grid grid-cols-[2fr_1.2fr_1.1fr_0.7fr] gap-3 px-4 py-3 border-b border-border last:border-0 items-center hover:bg-muted/40" data-testid={`pa-unit-${u.id}`}>
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center shrink-0 overflow-hidden">
                  {u.photo_url ? <img src={u.photo_url} alt="" className="w-full h-full object-cover" /> : <Wrench className="w-4 h-4 text-muted-foreground" />}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{u.item_name || "—"}</p>
                  <p className="text-[10px] font-mono text-muted-foreground truncate">{[u.qr_id || u.serial_no, u.brand].filter(Boolean).join(" · ") || "—"}</p>
                </div>
              </div>
              <span className="text-sm">
                <Badge variant="outline">{u.item_type === "machine" ? "Машина" : "Инструмент"}</Badge>
              </span>
              <span className="text-sm text-muted-foreground">{fmtDate(u.created_at)}</span>
              <div className="text-right">
                <Button variant="ghost" size="icon" onClick={() => openHistory(u)} data-testid={`pa-hist-${u.id}`}>
                  <History className="w-4 h-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={!!moveHist} onOpenChange={(o) => !o && setMoveHist(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><History className="w-5 h-5" />История · {moveHist?.unit?.item_name}</DialogTitle>
          </DialogHeader>
          {moveHist?.items === null ? (
            <div className="flex justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>
          ) : (moveHist?.items || []).length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">Няма движения.</p>
          ) : (
            <div className="space-y-2">
              {moveHist.items.map((m, i) => (
                <div key={i} className="rounded-lg border border-border p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <Badge variant="outline">{ACTION_LABELS[m.action] || m.action}</Badge>
                    <span className="text-xs text-muted-foreground">{fmtDate(m.at)}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{m.from_name ? `от ${m.from_name} ` : ""}{m.to_name ? `→ ${m.to_name}` : ""}</p>
                  <p className="text-xs text-muted-foreground">{m.by_name}</p>
                  {m.note && <p className="text-xs mt-1">{m.note}</p>}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
