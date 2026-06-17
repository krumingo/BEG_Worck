import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import UnitQrBlock from "@/components/UnitQrBlock";
import { warrantyStatus } from "@/lib/warranty";
import {
  ArrowLeft, MapPin, ShieldCheck, Loader2, Wrench, History,
  Calendar, Coins, Package, User,
} from "lucide-react";

const STATUS = {
  available: { label: "наличен", cls: "text-emerald-400 bg-emerald-500/10" },
  in_use: { label: "зает", cls: "text-amber-400 bg-amber-500/10" },
  repair: { label: "в ремонт", cls: "text-blue-400 bg-blue-500/10" },
  written_off: { label: "бракуван", cls: "text-muted-foreground bg-muted" },
};
const ACTION_LABELS = { take: "Взет", handover: "Предаден", drop: "Оставен", repair: "В ремонт", return: "Върнат", intake: "Заприходен" };
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("bg-BG") : "—");

export default function AssetUnitDetailPage() {
  const { unitId } = useParams();
  const navigate = useNavigate();
  const [unit, setUnit] = useState(null);
  const [moves, setMoves] = useState([]);
  const [repairs, setRepairs] = useState([]);
  const [totalPaid, setTotalPaid] = useState(0);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("moves");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const u = await API.get(`/assets/units/${unitId}`);
      setUnit(u.data);
    } catch { setUnit(null); }
    finally { setLoading(false); }
    try {
      const m = await API.get(`/assets/units/${unitId}/movements`);
      setMoves(m.data?.items || []);
    } catch { setMoves([]); }
    try {
      const r = await API.get(`/assets/units/${unitId}/repairs`);
      setRepairs(r.data?.items || []);
      setTotalPaid(r.data?.total_paid || 0);
    } catch { setRepairs([]); }
  }, [unitId]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return <div className="flex justify-center py-20"><Loader2 className="w-7 h-7 animate-spin text-primary" /></div>;
  }
  if (!unit) {
    return (
      <div className="p-6">
        <Button variant="ghost" onClick={() => navigate("/assets/units")}><ArrowLeft className="w-4 h-4 mr-1" />Активи</Button>
        <p className="text-muted-foreground mt-4">Активът не е намерен.</p>
      </div>
    );
  }

  const st = STATUS[unit.status] || STATUS.available;
  const w = warrantyStatus(unit.purchase_date, unit.warranty_months);

  return (
    <div className="p-6 space-y-4 max-w-5xl">
      <Button variant="ghost" size="sm" onClick={() => navigate("/assets/units")} data-testid="back-to-units"><ArrowLeft className="w-4 h-4 mr-1" />Активи</Button>

      {/* Шапка */}
      <div className="rounded-xl border border-border bg-card p-5 flex gap-5 items-start">
        <div className="w-20 h-20 rounded-lg bg-muted flex items-center justify-center overflow-hidden shrink-0">
          {unit.photo_url ? <img src={unit.photo_url} alt="" className="w-full h-full object-cover" /> : <Wrench className="w-8 h-8 text-muted-foreground" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-semibold">{unit.item_name || "—"}</h1>
            <span className={`text-[11px] px-2 py-0.5 rounded ${st.cls}`}>{st.label}</span>
            {w.inWarranty && <span className="text-[11px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded inline-flex items-center gap-1"><ShieldCheck className="w-3 h-3" />в гаранция</span>}
          </div>
          <p className="text-sm text-muted-foreground mt-1">{[unit.brand, unit.model].filter(Boolean).join(" · ")}{unit.serial_no ? ` · сериен № ${unit.serial_no}` : ""}</p>
          <p className="text-sm text-muted-foreground mt-1 flex items-center gap-1">
            <MapPin className="w-3.5 h-3.5" />{unit.location_name || "—"}
            {unit.created_at && <span> · въведен {fmtDate(unit.created_at)}{unit.created_by_name ? ` от ${unit.created_by_name}` : ""}</span>}
          </p>
        </div>
        <UnitQrBlock qrId={unit.qr_id} serialNo={unit.serial_no} />
      </div>

      {/* Две колони */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr_1.4fr] gap-4">
        {/* Данни */}
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-semibold text-muted-foreground mb-3">ДАННИ</p>
          <div className="space-y-2.5 text-sm">
            <Row label="Дата на покупка" icon={Calendar} value={fmtDate(unit.purchase_date)} />
            <Row label="Гаранция" icon={ShieldCheck} value={unit.warranty_months ? `${unit.warranty_months} мес.${w.untilLabel ? ` · до ${w.untilLabel}` : ""}` : "—"} />
            <Row label="Цена" icon={Coins} value={unit.purchase_price != null ? `${unit.purchase_price} €` : "—"} />
            <Row label="Похарчено ремонти" icon={Wrench} value={`${(totalPaid || 0).toLocaleString("bg-BG")} €`} valueCls="text-amber-400" />
            {unit.article_no && <Row label="Артикулен №" icon={Package} value={unit.article_no} />}
            {unit.qr_id && <Row label="QR код" icon={Package} value={unit.qr_id} mono />}
          </div>
        </div>

        {/* Табове Движения / Ремонти */}
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex gap-4 mb-3 text-sm border-b border-border">
            <button onClick={() => setTab("moves")} className={`pb-2 ${tab === "moves" ? "border-b-2 border-primary font-medium" : "text-muted-foreground"}`} data-testid="tab-moves">Движения ({moves.length})</button>
            <button onClick={() => setTab("repairs")} className={`pb-2 ${tab === "repairs" ? "border-b-2 border-primary font-medium" : "text-muted-foreground"}`} data-testid="tab-repairs">Ремонти ({repairs.length})</button>
          </div>

          {tab === "moves" ? (
            moves.length === 0 ? <p className="text-sm text-muted-foreground py-6 text-center">Няма движения.</p> : (
              <div className="space-y-2">
                {moves.map((m, i) => (
                  <div key={i} className="rounded-lg border border-border p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <Badge variant="outline">{ACTION_LABELS[m.action] || m.action}</Badge>
                      <span className="text-xs text-muted-foreground">{fmtDate(m.at)}</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{m.from_name ? `от ${m.from_name} ` : ""}{m.to_name ? `→ ${m.to_name}` : ""}</p>
                    {m.by_name && <p className="text-xs text-muted-foreground">{m.by_name}</p>}
                  </div>
                ))}
              </div>
            )
          ) : (
            repairs.length === 0 ? <p className="text-sm text-muted-foreground py-6 text-center">Няма ремонти.</p> : (
              <div className="space-y-2">
                {repairs.map((rp, i) => (
                  <div key={i} className="rounded-lg border border-border p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">{fmtDate(rp.sent_at)}{rp.returned_at ? ` → ${fmtDate(rp.returned_at)}` : " · в ремонт"}</span>
                      <div className="flex items-center gap-1.5">
                        {rp.is_warranty && <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded">гаранция</span>}
                        {rp.cost != null && rp.cost > 0 && <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded">{rp.cost} €</span>}
                      </div>
                    </div>
                    {rp.work_done && <p className="text-xs mt-1">{rp.work_done}</p>}
                    {rp.issue && !rp.work_done && <p className="text-xs mt-1 text-muted-foreground">Повреда: {rp.issue}</p>}
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {rp.service ? `${rp.service} · ` : ""}{rp.sent_by_name ? `закара: ${rp.sent_by_name}` : ""}{rp.returned_by_name ? ` · взе: ${rp.returned_by_name}` : ""}
                    </p>
                  </div>
                ))}
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, icon: Icon, valueCls = "", mono = false }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground flex items-center gap-1.5">{Icon && <Icon className="w-3.5 h-3.5" />}{label}</span>
      <b className={`${valueCls} ${mono ? "font-mono text-xs" : ""}`}>{value}</b>
    </div>
  );
}
