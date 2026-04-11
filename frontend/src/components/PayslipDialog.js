/**
 * PayslipDialog — Official payslip view for a worker in a payroll batch.
 * Shows: period, days, projects, SMR, normal/overtime, gross/deductions/net.
 */
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  FileText, Clock, MapPin, Loader2, Calendar, Check, DollarSign,
} from "lucide-react";

export default function PayslipDialog({ open, onClose, batchId, workerId }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !batchId || !workerId) { setData(null); return; }
    setLoading(true);
    API.get(`/payslip/${batchId}/${workerId}`)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [open, batchId, workerId]);

  const s = data?.summary || {};
  const w = data?.worker || {};

  const statusBadge = (st) => {
    if (st === "paid") return { label: t("payslip.paid"), cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    if (st === "batched") return { label: t("payslip.batched"), cls: "bg-violet-500/15 text-violet-400 border-violet-500/30" };
    return { label: st, cls: "bg-gray-500/15 text-gray-400 border-gray-500/30" };
  };

  const stb = statusBadge(data?.batch_status);

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="payslip-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="w-4 h-4" /> {t("payslip.title")}
          </DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
        ) : !data || data.error ? (
          <div className="text-center py-12 text-muted-foreground">{data?.error || t("payslip.noData")}</div>
        ) : (
          <div className="space-y-4">
            {/* Worker header */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/30">
              <div className="flex items-center gap-3">
                {w.avatar_url ? (
                  <img src={`${process.env.REACT_APP_BACKEND_URL}${w.avatar_url}`} className="w-10 h-10 rounded-full object-cover" alt="" />
                ) : (
                  <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center text-sm font-bold text-primary">
                    {(w.first_name?.[0] || "")}{(w.last_name?.[0] || "")}
                  </div>
                )}
                <div>
                  <p className="font-semibold">{w.first_name} {w.last_name}</p>
                  <p className="text-xs text-muted-foreground">{w.position || "—"} | {w.pay_type || "—"} | {w.hourly_rate > 0 ? `${w.hourly_rate} EUR/ч` : "—"}</p>
                </div>
              </div>
              <div className="text-right">
                <Badge variant="outline" className={stb.cls}>{stb.label}</Badge>
                <p className="text-[10px] text-muted-foreground mt-1">{data.week_start} → {data.week_end}</p>
              </div>
            </div>

            {/* Summary grid */}
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2" data-testid="payslip-summary">
              <SumCard label={t("payslip.days")} value={s.included_days} />
              <SumCard label={t("payslip.hours")} value={`${s.total_hours}ч`} />
              <SumCard label={t("payslip.normal")} value={`${s.normal_hours}ч`} color="text-emerald-400" />
              <SumCard label={t("payslip.overtime")} value={s.overtime_hours > 0 ? `+${s.overtime_hours}ч` : "—"} color={s.overtime_hours > 0 ? "text-amber-400" : ""} />
              <SumCard label={t("payslip.gross")} value={`${s.gross?.toFixed(0)} EUR`} color="text-primary" />
              <SumCard label={t("payslip.net")} value={`${s.net?.toFixed(0)} EUR`} color="text-primary" bold />
            </div>

            {/* Day breakdown */}
            <div>
              <p className="text-[10px] text-muted-foreground font-semibold uppercase mb-1">{t("payslip.byDay")}</p>
              <div className="rounded-lg border border-border overflow-hidden">
                <Table>
                  <TableHeader><TableRow>
                    <TableHead className="text-[10px]">{t("payslip.date")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payslip.hours")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payslip.normalH")}</TableHead>
                    <TableHead className="text-[10px] text-center">{t("payslip.overtimeH")}</TableHead>
                    <TableHead className="text-[10px]">{t("payslip.details")}</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {data.by_day?.map(d => (
                      <TableRow key={d.date}>
                        <TableCell className="text-xs font-mono">{d.date}</TableCell>
                        <TableCell className="text-center text-xs font-mono font-bold">{d.hours}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-emerald-400">{d.normal}</TableCell>
                        <TableCell className={`text-center text-xs font-mono ${d.overtime > 0 ? "text-amber-400 font-bold" : "text-muted-foreground"}`}>{d.overtime > 0 ? `+${d.overtime}` : "—"}</TableCell>
                        <TableCell className="text-[10px] text-muted-foreground">{d.entries?.map(e => `${e.smr} @ ${e.project}`).join(", ")}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>

            {/* Project breakdown */}
            {data.by_project?.length > 0 && (
              <div>
                <p className="text-[10px] text-muted-foreground font-semibold uppercase mb-1">{t("payslip.byProject")}</p>
                <div className="space-y-1">
                  {data.by_project.map(p => (
                    <div key={p.project_id} className="flex items-center justify-between px-3 py-2 rounded-lg bg-muted/10 border border-border/50">
                      <div className="flex items-center gap-2">
                        <MapPin className="w-3 h-3 text-primary" />
                        <span className="text-xs">{p.project_name || p.project_id}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs">
                        <span className="font-mono text-muted-foreground">{p.hours}ч</span>
                        <span className="font-mono text-primary font-bold">{p.value?.toFixed(0)} EUR</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Adjustments */}
            {s.adjustments?.length > 0 && (
              <div>
                <p className="text-[10px] text-muted-foreground font-semibold uppercase mb-1">{t("payslip.adjustments")}</p>
                <div className="space-y-1">
                  {s.adjustments.map((a, i) => (
                    <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-muted/10">
                      <span className={`text-xs ${a.type === "bonus" ? "text-emerald-400" : "text-red-400"}`}>
                        {a.type === "bonus" ? t("payslip.adjBonus") : a.type === "deduction" ? t("payslip.adjDeduction") : a.type === "loan" ? t("payslip.adjLoan") : a.type === "rent" ? t("payslip.adjRent") : a.type === "fine" ? t("payslip.adjFine") : a.type}
                        {a.note && ` (${a.note})`}
                      </span>
                      <span className="text-xs font-mono">{a.type === "bonus" ? "+" : "-"}{a.amount} EUR</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Final calculation */}
            <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-1">
              <div className="flex justify-between text-xs"><span>{t("payslip.gross")}</span><span className="font-mono">{s.gross?.toFixed(2)} EUR</span></div>
              {s.bonuses > 0 && <div className="flex justify-between text-xs text-emerald-400"><span>+ {t("payslip.bonusesTotal")}</span><span className="font-mono">+{s.bonuses?.toFixed(2)} EUR</span></div>}
              {s.deductions > 0 && <div className="flex justify-between text-xs text-red-400"><span>- {t("payslip.deductionsTotal")}</span><span className="font-mono">-{s.deductions?.toFixed(2)} EUR</span></div>}
              <div className="flex justify-between font-bold text-sm pt-1 border-t border-border">
                <span>{t("payslip.netPayable")}</span>
                <span className="font-mono text-primary">{s.net?.toFixed(2)} EUR</span>
              </div>
            </div>

            {/* Paid info */}
            {data.paid_at && (
              <div className="flex items-center gap-2 text-xs text-emerald-400">
                <Check className="w-3 h-3" />
                {t("payslip.paidOn")} {data.paid_at?.slice(0, 10)}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function SumCard({ label, value, color = "", bold = false }) {
  return (
    <div className="rounded-lg bg-muted/30 p-2 text-center">
      <p className={`text-sm font-mono ${bold ? "font-bold" : ""} ${color}`}>{value}</p>
      <p className="text-[8px] text-muted-foreground">{label}</p>
    </div>
  );
}
