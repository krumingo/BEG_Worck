import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Loader2, AlertTriangle, ExternalLink, Users, Hammer, Briefcase, Clock,
} from "lucide-react";

function ProgressBar({ value, color = "bg-primary" }) {
  return (
    <div className="w-full h-2 rounded-full bg-muted overflow-hidden">
      <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${Math.min(100, value || 0)}%` }} />
    </div>
  );
}

const MODE_LABELS = { internal: "Вътрешни", akord: "Акорд", mixed: "Смесен" };
const MODE_COLORS = {
  internal: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  akord: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  mixed: "bg-violet-500/15 text-violet-400 border-violet-500/30",
};

export default function ProjectSMRTab({ projectId }) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailRow, setDetailRow] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await API.get(`/project-smr-view/${projectId}`);
      setData(res.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <div className="p-4 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></div>;
  if (!data) return null;

  const mo = data.main_offer;
  const rows = data.rows || [];
  const s = data.summary || {};

  return (
    <div className="space-y-4" data-testid="smr-tab">
      {/* Main Offer Card */}
      {mo && (
        <div className="flex items-center justify-between p-3 rounded-lg border border-primary/20 bg-primary/5" data-testid="main-offer-card">
          <div className="flex items-center gap-3">
            <Briefcase className="w-5 h-5 text-primary" />
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold text-primary">{mo.offer_no}</span>
                <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400">Основна</Badge>
                <Badge variant="outline" className={`text-[10px] ${mo.status === "Accepted" ? "bg-emerald-500/15 text-emerald-400" : ""}`}>{mo.status === "Accepted" ? "Приета" : mo.status}</Badge>
              </div>
              <p className="text-sm text-muted-foreground">{mo.title} • {mo.line_count} позиции</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="font-mono text-lg font-bold text-foreground">{mo.total?.toLocaleString("en", {minimumFractionDigits: 2})} EUR</p>
            </div>
            <Button variant="outline" size="sm" onClick={() => navigate(`/offers/${mo.id}`)} data-testid="open-offer-btn">
              <ExternalLink className="w-3.5 h-3.5 mr-1" /> Отвори
            </Button>
          </div>
        </div>
      )}

      {/* Summary strip */}
      <div className="flex items-center gap-6 text-sm text-muted-foreground">
        <span>СМР: <span className="text-foreground font-bold">{s.total_packages}</span></span>
        <span>Продажба: <span className="font-mono text-foreground">{s.total_sale?.toLocaleString("en", {minimumFractionDigits: 2})} EUR</span></span>
        <span>Труд бюджет: <span className="font-mono text-foreground">{s.total_labor_budget?.toLocaleString("en", {minimumFractionDigits: 2})}</span></span>
        <span>Труд факт: <span className="font-mono text-foreground">{s.total_labor_actual?.toLocaleString("en", {minimumFractionDigits: 2})}</span></span>
        {s.with_warnings > 0 && <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-400"><AlertTriangle className="w-3 h-3 mr-0.5 inline" />{s.with_warnings}</Badge>}
      </div>

      {/* SMR Table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="smr-table">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-[10px] uppercase text-muted-foreground">СМР / Дейност</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground w-[85px]">Режим</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground text-right w-[85px]">Труд оферта</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground text-right w-[85px]">Труд бюдж.</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground text-right w-[85px]">Изхарчен</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground text-right w-[85px]">Остатък</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground w-[120px]">Прогрес</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground w-[60px]"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground">Няма СМР пакети</TableCell></TableRow>
            ) : rows.map((r, i) => {
              const hasWarn = r.flags.length > 0;
              return (
                <TableRow key={i} className={`cursor-pointer hover:bg-muted/30 ${hasWarn ? "bg-amber-500/5" : ""}`} onClick={() => setDetailRow(r)} data-testid={`smr-row-${i}`}>
                  <TableCell>
                    <p className="text-sm font-medium text-foreground">{r.activity_name}</p>
                    <p className="text-[10px] text-muted-foreground">{r.qty} {r.unit}</p>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-[9px] ${MODE_COLORS[r.mode] || ""}`}>
                      {r.mode === "internal" && <Users className="w-2.5 h-2.5 mr-0.5 inline" />}
                      {r.mode === "akord" && <Hammer className="w-2.5 h-2.5 mr-0.5 inline" />}
                      {MODE_LABELS[r.mode] || r.mode}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm text-muted-foreground">{r.offer_labor_unit_price != null ? r.offer_labor_unit_price.toFixed(2) : "—"}</TableCell>
                  <TableCell className="text-right font-mono text-sm">{r.labor_budget.toFixed(2)}</TableCell>
                  <TableCell className={`text-right font-mono text-sm ${r.flags.includes("labor_overrun") ? "text-red-400 font-bold" : ""}`}>{r.labor_actual.toFixed(2)}</TableCell>
                  <TableCell className={`text-right font-mono text-sm ${r.labor_remaining != null && r.labor_remaining < 0 ? "text-red-400" : "text-emerald-400"}`}>
                    {r.labor_remaining != null ? r.labor_remaining.toFixed(2) : "—"}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <ProgressBar value={r.progress_percent} color={!r.has_progress ? "bg-gray-500" : r.progress_percent >= 80 ? "bg-emerald-500" : "bg-primary"} />
                      <span className={`font-mono text-xs font-bold ${!r.has_progress ? "text-gray-500" : ""}`}>{r.progress_percent}%</span>
                    </div>
                    {!r.has_progress && <Badge variant="outline" className="text-[8px] bg-amber-500/10 text-amber-400 mt-0.5">Няма</Badge>}
                  </TableCell>
                  <TableCell>
                    {hasWarn && <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Detail Dialog */}
      <Dialog open={!!detailRow} onOpenChange={() => setDetailRow(null)}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="smr-detail-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Hammer className="w-5 h-5 text-primary" /> {detailRow?.activity_name}
            </DialogTitle>
          </DialogHeader>
          {detailRow && (
            <div className="space-y-3 py-2">
              <div className="flex items-center gap-3">
                <Badge variant="outline" className={`text-xs ${MODE_COLORS[detailRow.mode]}`}>{MODE_LABELS[detailRow.mode]}</Badge>
                <span className="text-sm text-muted-foreground">{detailRow.qty} {detailRow.unit}</span>
                <span className="font-mono text-sm">{detailRow.sale_total.toFixed(2)} EUR продажба</span>
              </div>

              {/* Labor section */}
              <div className="p-3 rounded-lg border border-border space-y-2">
                <p className="text-xs text-muted-foreground font-medium uppercase">Труд</p>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div><p className="text-[10px] text-muted-foreground">По оферта</p><p className="font-mono">{detailRow.offer_labor_unit_price != null ? `${detailRow.offer_labor_unit_price.toFixed(2)}/ед` : "—"}</p></div>
                  <div><p className="text-[10px] text-muted-foreground">Бюджет</p><p className="font-mono">{detailRow.labor_budget.toFixed(2)} EUR</p></div>
                  <div><p className="text-[10px] text-muted-foreground">Изхарчен</p><p className={`font-mono ${detailRow.flags.includes("labor_overrun") ? "text-red-400 font-bold" : ""}`}>{detailRow.labor_actual.toFixed(2)} EUR</p></div>
                </div>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div><p className="text-[10px] text-muted-foreground">Остатък</p><p className={`font-mono font-bold ${detailRow.labor_remaining < 0 ? "text-red-400" : "text-emerald-400"}`}>{detailRow.labor_remaining != null ? `${detailRow.labor_remaining.toFixed(2)} EUR` : "—"}</p></div>
                  <div><p className="text-[10px] text-muted-foreground">Часове</p><p className="font-mono">{detailRow.used_hours}/{detailRow.planned_hours || "?"}</p></div>
                  <div><p className="text-[10px] text-muted-foreground">Остатък ч.</p><p className="font-mono">{detailRow.remaining_hours != null ? detailRow.remaining_hours : "—"}</p></div>
                </div>
              </div>

              {/* Progress */}
              <div className="p-3 rounded-lg border border-border">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-xs text-muted-foreground font-medium uppercase">Прогрес</p>
                  <span className="font-mono text-lg font-bold text-primary">{detailRow.progress_percent}%</span>
                </div>
                <ProgressBar value={detailRow.progress_percent} color={detailRow.progress_percent >= 80 ? "bg-emerald-500" : "bg-primary"} />
                {!detailRow.has_progress && <p className="text-[10px] text-amber-400 mt-1">Няма въведен прогрес</p>}
              </div>

              {/* Other costs */}
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="p-2 rounded border border-border"><p className="text-[10px] text-muted-foreground">Материал</p><p className="font-mono">{detailRow.material_actual.toFixed(2)}</p></div>
                <div className="p-2 rounded border border-border"><p className="text-[10px] text-muted-foreground">Подизпълнител</p><p className="font-mono">{detailRow.subcontract.toFixed(2)}</p></div>
                <div className="p-2 rounded border border-border"><p className="text-[10px] text-muted-foreground">Общ разход</p><p className="font-mono font-bold">{detailRow.total_actual.toFixed(2)}</p></div>
              </div>

              {/* Warnings */}
              {detailRow.flags.length > 0 && (
                <div className="space-y-1">
                  {detailRow.flags.map((f, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs text-amber-400 p-1.5 rounded bg-amber-500/10">
                      <AlertTriangle className="w-3 h-3" />
                      {f === "no_progress" && "Няма въведен прогрес"}
                      {f === "labor_overrun" && "Надвишен бюджет за труд"}
                      {f === "hours_overrun" && "Надвишени планирани часове"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
