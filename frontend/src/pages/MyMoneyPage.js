import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { ArrowLeft, Calendar, Wallet, Loader2 } from "lucide-react";

const STATUS = {
  confirmed: { label: "Потвърден", cls: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
  paid: { label: "Платен", cls: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" },
  reopened: { label: "Отворен", cls: "bg-amber-500/20 text-amber-400 border-amber-500/30" },
};

function eur(a) {
  return new Intl.NumberFormat("bg-BG", { style: "currency", currency: "EUR" }).format(a || 0);
}

export default function MyMoneyPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [owed, setOwed] = useState(0);
  const [slips, setSlips] = useState([]);
  const [sel, setSel] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await API.get("/my-pay-summary");
      setOwed(res.data.owed || 0);
      setSlips(res.data.slips || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const badge = (st) => STATUS[st] || { label: st, cls: "bg-gray-500/20 text-gray-400 border-gray-500/30" };

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-[480px] mx-auto p-4">
        <div className="flex items-center gap-3 mb-4">
          <button onClick={() => navigate("/tech")} className="w-9 h-9 rounded-xl border border-border bg-card flex items-center justify-center active:scale-95 transition-all" aria-label="Назад">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <h1 className="text-lg font-semibold text-foreground">Моите пари</h1>
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
        ) : (
          <div className="space-y-4">
            {/* Owed */}
            <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
              <p className="text-xs text-muted-foreground flex items-center gap-1.5"><Wallet className="w-3.5 h-3.5 text-amber-400" /> За получаване сега</p>
              <p className="text-3xl font-bold text-amber-400 mt-1">{eur(owed)}</p>
              <p className="text-xs text-muted-foreground mt-1">от одобрени, още неплатени периоди</p>
            </div>

            {/* History */}
            <div>
              <p className="text-xs text-muted-foreground mb-2 px-1">История на плащания</p>
              {slips.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground text-sm">Все още няма фишове</div>
              ) : (
                <div className="space-y-2">
                  {slips.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => setSel(s)}
                      className="w-full rounded-2xl border border-border bg-card p-3.5 flex items-center justify-between gap-3 active:scale-[0.98] transition-all text-left"
                    >
                      <div className="flex items-center gap-2.5">
                        <Calendar className="w-4 h-4 text-muted-foreground" />
                        <div>
                          <p className="text-sm text-foreground">{s.period_start} – {s.period_end}</p>
                          <p className="text-xs text-muted-foreground">{s.paid_at ? `Платено на ${s.paid_at.slice(0, 10)}` : "Очаква изплащане"}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-semibold text-foreground">{eur(s.net_period)}</p>
                        <Badge variant="outline" className={`text-[10px] ${badge(s.status).cls}`}>{badge(s.status).label}</Badge>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Detail */}
      <Dialog open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <DialogContent className="sm:max-w-[460px] bg-card border-border">
          <DialogHeader><DialogTitle>Фиш</DialogTitle></DialogHeader>
          {sel && (
            <div className="space-y-4 py-2">
              <div className="p-3 rounded-lg bg-muted/40">
                <div className="flex items-center gap-2 mb-2">
                  <Calendar className="w-4 h-4 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">{sel.period_start} – {sel.period_end}</span>
                </div>
                <Badge variant="outline" className={`text-xs ${badge(sel.status).cls}`}>{badge(sel.status).label}</Badge>
              </div>

              <div className="space-y-2.5">
                <Row label="Тип заплащане" value={sel.pay_type || "-"} />
                {sel.approved_days !== undefined && <Row label="Дни" value={sel.approved_days} />}
                {sel.approved_hours !== undefined && <Row label="Часове" value={`${sel.approved_hours}ч${sel.overtime_hours > 0 ? ` (вкл. ${sel.overtime_hours}ч овъртайм)` : ""}`} />}
                {sel.frozen_hourly_rate > 0 && <Row label="Ставка" value={eur(sel.frozen_hourly_rate)} />}
                <Row label="Заработено" value={eur(sel.earned_amount)} />
                {sel.bonuses_amount > 0 && <Row label="Бонуси" value={`+${eur(sel.bonuses_amount)}`} valueClass="text-emerald-400" />}
                {sel.deductions_amount > 0 && <Row label="Удръжки" value={`-${eur(sel.deductions_amount)}`} valueClass="text-red-400" />}
              </div>

              <div className="p-3.5 rounded-lg bg-amber-500/10 border border-amber-500/30 flex justify-between items-center">
                <span className="font-semibold text-foreground">Нето за периода</span>
                <span className="text-2xl font-bold text-amber-400">{eur(sel.net_period)}</span>
              </div>

              {sel.paid_at && (
                <p className="text-center text-sm text-emerald-400">Платено на {sel.paid_at.slice(0, 10)}</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ label, value, valueClass = "" }) {
  return (
    <div className="flex justify-between py-1.5 border-b border-border">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm font-medium text-foreground ${valueClass}`}>{value}</span>
    </div>
  );
}
