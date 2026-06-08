import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Loader2, Hand, ArrowLeft, Wrench, Send, Warehouse, User } from "lucide-react";
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
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [kind, setKind] = useState(null);   // "unit" | "other"
  const [info, setInfo] = useState(null);    // { type, name }
  const [unit, setUnit] = useState(null);
  const [warehouses, setWarehouses] = useState([]);
  const [colleagues, setColleagues] = useState([]);
  const [picker, setPicker] = useState(null); // null | "handover" | "return"
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(""); setPicker(null);
    try {
      const res = await API.get(`/assets/qr/resolve/${qrId}`);
      const et = res.data?.entity_type;
      if (et === "asset_unit") {
        const [u, w, us] = await Promise.all([
          API.get(`/assets/units/${res.data.entity_id}`),
          API.get(`/warehouses?page_size=100&active_only=false`),
          API.get(`/users`),
        ]);
        setUnit(u.data);
        setWarehouses(w.data?.items || []);
        setColleagues((us.data || []).filter((x) => x.id !== user?.id && x.is_active !== false));
        setKind("unit");
      } else {
        setInfo({ type: et, name: res.data?.name || "" }); setKind("other");
      }
    } catch (err) {
      setError(err.response?.status === 404 ? "QR кодът не е намерен" : "Грешка при зареждане");
    } finally {
      setLoading(false);
    }
  }, [qrId, user]);

  useEffect(() => { load(); }, [load]);

  const move = async (body, okMsg) => {
    setBusy(true);
    try {
      const res = await API.post(`/assets/units/${unit.id}/move`, body);
      setUnit(res.data); setPicker(null);
      toast.success(okMsg);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    } finally {
      setBusy(false);
    }
  };

  const take = () => move({ action: "take" }, "Взе актива — вече е у теб");
  const give = (cid) => move({ action: "handover", to_type: "employee", to_id: cid }, "Предаде актива");
  const ret = (wid) => move({ action: "return", to_type: "warehouse", to_id: wid }, "Върна в склада");

  const st = unit ? (STATUS[unit.status] || {}) : {};
  const isMine = unit && unit.location_type === "employee" && unit.location_id === user?.id;

  const btn = "w-full py-3.5 rounded-xl font-semibold flex items-center justify-center gap-2 disabled:opacity-50";
  const pri = `${btn} bg-primary text-primary-foreground`;
  const out = `${btn} border border-border`;

  const renderActions = () => {
    if (picker === "handover") {
      return (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">Предай на:</p>
          {colleagues.map((c) => (
            <button key={c.id} disabled={busy} onClick={() => give(c.id)} className={out}>
              <User className="w-4 h-4" /> {`${c.first_name || ""} ${c.last_name || ""}`.trim() || c.email}
            </button>
          ))}
          <button onClick={() => setPicker(null)} className="text-xs text-muted-foreground mt-1">Отказ</button>
        </div>
      );
    }
    if (picker === "return") {
      return (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">Върни в склад:</p>
          {warehouses.map((w) => (
            <button key={w.id} disabled={busy} onClick={() => ret(w.id)} className={out}>
              <Warehouse className="w-4 h-4" /> {w.name}
            </button>
          ))}
          <button onClick={() => setPicker(null)} className="text-xs text-muted-foreground mt-1">Отказ</button>
        </div>
      );
    }
    if (unit.status === "available") {
      return <button onClick={take} disabled={busy} className={pri}>{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hand className="w-4 h-4" />} Вземи</button>;
    }
    if (isMine) {
      return (
        <div className="flex flex-col gap-2">
          <button onClick={() => setPicker("handover")} disabled={busy} className={pri}><Send className="w-4 h-4" /> Предай на колега</button>
          <button onClick={() => setPicker("return")} disabled={busy} className={out}><Warehouse className="w-4 h-4" /> Върни в склад</button>
        </div>
      );
    }
    if (unit.status === "repair") {
      return <button onClick={() => setPicker("return")} disabled={busy} className={out}><Warehouse className="w-4 h-4" /> Върни в склад</button>;
    }
    // held by someone else
    return (
      <>
        <button onClick={take} disabled={busy} className={pri}>{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hand className="w-4 h-4" />} Вземи от него</button>
        <p className="text-center text-xs text-muted-foreground mt-2">ще се прехвърли на теб</p>
      </>
    );
  };

  return (
    <div className="min-h-screen flex flex-col items-center p-4 bg-background">
      <div className="w-full max-w-sm">
        <button onClick={() => navigate(-1)} className="text-sm text-muted-foreground flex items-center gap-1 mb-4">
          <ArrowLeft className="w-4 h-4" /> Назад
        </button>

        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground justify-center py-20"><Loader2 className="w-5 h-5 animate-spin" /> Зареждане…</div>
        ) : error ? (
          <div className="text-center py-20 text-muted-foreground">{error}<div className="text-xs mt-1 font-mono">{qrId}</div></div>
        ) : kind === "unit" ? (
          <div className="rounded-2xl bg-card border border-border p-5 shadow-sm">
            <div className="h-24 rounded-xl bg-muted flex items-center justify-center text-muted-foreground mb-4">
              {unit.photo_url ? <img src={unit.photo_url} alt="" className="h-full object-contain" /> : <Wrench className="w-9 h-9" />}
            </div>
            <p className="text-lg font-bold">{unit.item_name || "Актив"}</p>
            <p className="text-xs font-mono text-muted-foreground">{unit.qr_id}{unit.model ? ` · ${unit.model}` : ""}</p>
            <div className="mt-2 mb-4 text-sm flex items-center flex-wrap gap-2">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-muted">
                <span style={{ color: st.color }}>●</span> {isMine ? "при теб" : (st.label || unit.status)}
              </span>
              {!isMine && unit.location_name && <span className="text-muted-foreground">{unit.location_type === "employee" ? "при " : ""}{unit.location_name}</span>}
            </div>
            {renderActions()}
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
