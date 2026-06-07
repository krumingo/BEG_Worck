import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Loader2, Hand, ArrowLeft, Wrench } from "lucide-react";
import { toast } from "sonner";

const STATUS = {
  available: { label: "наличен", color: "#16a34a" },
  in_use: { label: "зает", color: "#d97706" },
  repair: { label: "в ремонт", color: "#2563eb" },
  written_off: { label: "бракуван", color: "#9ca3af" },
};

const TYPE_LABEL = {
  employee: "Служител", warehouse: "Склад", project: "Обект",
  guest: "Гост", repair: "Ремонт",
};

export default function ScanLandingPage() {
  const { qrId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [kind, setKind] = useState(null); // "unit" | "other"
  const [info, setInfo] = useState(null); // { type, name }
  const [unit, setUnit] = useState(null);
  const [acting, setActing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const res = await API.get(`/assets/qr/resolve/${qrId}`);
      const et = res.data?.entity_type;
      if (et === "asset_unit") {
        const u = await API.get(`/assets/units/${res.data.entity_id}`);
        setUnit(u.data); setKind("unit");
      } else {
        setInfo({ type: et, name: res.data?.name || "" }); setKind("other");
      }
    } catch (err) {
      setError(err.response?.status === 404 ? "QR кодът не е намерен" : "Грешка при зареждане");
    } finally {
      setLoading(false);
    }
  }, [qrId]);

  useEffect(() => { load(); }, [load]);

  const take = async () => {
    setActing(true);
    try {
      const res = await API.post(`/assets/units/${unit.id}/move`, { action: "take" });
      setUnit(res.data);
      toast.success("Взе актива — вече е у теб");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    } finally {
      setActing(false);
    }
  };

  const st = unit ? (STATUS[unit.status] || {}) : {};

  return (
    <div className="min-h-screen flex flex-col items-center p-4 bg-background">
      <div className="w-full max-w-sm">
        <button onClick={() => navigate(-1)} className="text-sm text-muted-foreground flex items-center gap-1 mb-4">
          <ArrowLeft className="w-4 h-4" /> Назад
        </button>

        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground justify-center py-20">
            <Loader2 className="w-5 h-5 animate-spin" /> Зареждане…
          </div>
        ) : error ? (
          <div className="text-center py-20 text-muted-foreground">
            {error}
            <div className="text-xs mt-1 font-mono">{qrId}</div>
          </div>
        ) : kind === "unit" ? (
          <div className="rounded-2xl bg-card border border-border p-5 shadow-sm">
            <div className="h-24 rounded-xl bg-muted flex items-center justify-center text-muted-foreground mb-4">
              {unit.photo_url
                ? <img src={unit.photo_url} alt="" className="h-full object-contain" />
                : <Wrench className="w-9 h-9" />}
            </div>
            <p className="text-lg font-bold">{unit.item_name || "Актив"}</p>
            <p className="text-xs font-mono text-muted-foreground">
              {unit.qr_id}{unit.model ? ` · ${unit.model}` : ""}
            </p>
            <div className="mt-2 mb-4 text-sm flex items-center flex-wrap gap-2">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-muted">
                <span style={{ color: st.color }}>●</span> {st.label || unit.status}
              </span>
              {unit.location_name && <span className="text-muted-foreground">{unit.location_name}</span>}
            </div>
            <button
              onClick={take}
              disabled={acting}
              className="w-full py-3.5 rounded-xl bg-primary text-primary-foreground font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
              data-testid="scan-take-btn"
            >
              {acting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hand className="w-4 h-4" />} Вземи
            </button>
            <p className="text-center text-xs text-muted-foreground mt-3">Предай · Остави тук · Ремонт — идват скоро</p>
          </div>
        ) : (
          <div className="rounded-2xl bg-card border border-border p-5 text-center">
            <p className="text-sm text-muted-foreground">Това е {TYPE_LABEL[info?.type] || "запис"}:</p>
            <p className="text-lg font-bold mt-1">{info?.name}</p>
            <p className="text-xs font-mono text-muted-foreground mt-2">{qrId}</p>
          </div>
        )}
      </div>
    </div>
  );
}
