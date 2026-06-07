import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { toast } from "sonner";
import { QrCode, Printer, Plus, Search, Loader2 } from "lucide-react";

const TYPE_FILTERS = [
  { key: "all", label: "Всички" },
  { key: "project", label: "Обекти" },
  { key: "employee", label: "Служители" },
  { key: "warehouse", label: "Складове" },
  { key: "guest", label: "Гости" },
  { key: "repair", label: "Ремонт" },
];

const TYPE_BG = {
  project: "Обект",
  employee: "Служител",
  warehouse: "Склад",
  guest: "Гост",
  repair: "Ремонт",
};

const TYPE_CLASS = {
  project: "bg-blue-500/15 text-blue-400",
  employee: "bg-emerald-500/15 text-emerald-400",
  warehouse: "bg-muted text-muted-foreground",
  guest: "bg-amber-500/15 text-amber-400",
  repair: "bg-red-500/15 text-red-400",
};

// Fetches the QR as an SVG through the authenticated API client and renders it inline.
function QrSvg({ qrId, size = 64 }) {
  const [svg, setSvg] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let alive = true;
    API.get(`/assets/qr/${qrId}/svg`, { responseType: "text" })
      .then((res) => {
        if (!alive) return;
        const clean = String(res.data).replace(/<\?xml[^>]*\?>/, "");
        setSvg(clean);
      })
      .catch(() => alive && setErr(true));
    return () => { alive = false; };
  }, [qrId]);
  if (err) return <div style={{ width: size, height: size }} className="flex items-center justify-center text-muted-foreground"><QrCode className="w-5 h-5" /></div>;
  if (!svg) return <div style={{ width: size, height: size }} className="flex items-center justify-center"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>;
  return <div className="qr-svg bg-white rounded p-1" style={{ width: size, height: size }} dangerouslySetInnerHTML={{ __html: svg }} />;
}

export default function AssetsQrBasePage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [type, setType] = useState("all");
  const [q, setQ] = useState("");
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page_size: 500 };
      if (type !== "all") params.type = type;
      if (q.trim()) params.q = q.trim();
      const res = await API.get("/assets/qr", { params });
      setItems(res.data.items || []);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка при зареждане");
    } finally {
      setLoading(false);
    }
  }, [type, q]);

  useEffect(() => { load(); }, [type]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const t = setTimeout(() => load(), 350);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const generateAll = async () => {
    setGenerating(true);
    try {
      const res = await API.post("/assets/qr/generate-bulk", { types: ["project", "employee", "warehouse"] });
      const c = res.data.created || {};
      toast.success(`Генерирани: ${c.project || 0} обекта · ${c.employee || 0} служители · ${c.warehouse || 0} склада`);
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка при генериране");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <style>{`
        .qr-svg svg { width: 100%; height: 100%; display: block; }
        @media print {
          body * { visibility: hidden !important; }
          #qr-print, #qr-print * { visibility: visible !important; }
          #qr-print { position: absolute; left: 0; top: 0; width: 100%; }
        }
      `}</style>

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><QrCode className="w-6 h-6 text-primary" /> QR база</h1>
          <p className="text-sm text-muted-foreground">{items.length} кода</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => window.print()} className="px-3 py-2 rounded-lg border border-border text-sm flex items-center gap-2 hover:bg-muted/40">
            <Printer className="w-4 h-4" /> Печат на всички
          </button>
          <button onClick={generateAll} disabled={generating} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium flex items-center gap-2 disabled:opacity-50">
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Генерирай за всички
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {TYPE_FILTERS.map((f) => (
          <button key={f.key} onClick={() => setType(f.key)}
            className={`px-3 py-1.5 rounded-full text-sm transition-colors ${type === f.key ? "bg-primary text-primary-foreground" : "bg-muted/30 text-muted-foreground hover:bg-muted/50"}`}>
            {f.label}
          </button>
        ))}
        <div className="relative ml-auto">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Търсене по име/код…"
            className="pl-9 pr-3 py-2 rounded-lg bg-card border border-border text-sm w-64 outline-none focus:border-primary/50" />
        </div>
      </div>

      <div className="rounded-2xl border border-border overflow-hidden">
        <div className="grid grid-cols-[110px_1fr_140px_90px_120px] gap-3 px-4 py-3 bg-muted/20 text-xs text-muted-foreground">
          <span>Тип</span><span>Име</span><span>Код</span><span>QR</span><span className="text-center">Статус</span>
        </div>
        {loading ? (
          <div className="py-12 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
        ) : items.length === 0 ? (
          <div className="py-12 text-center text-muted-foreground text-sm">Няма кодове. Натисни „Генерирай за всички“, за да създадеш QR за обектите, служителите и складовете.</div>
        ) : items.map((it) => (
          <div key={it.qr_id} className="grid grid-cols-[110px_1fr_140px_90px_120px] gap-3 px-4 py-3 items-center border-t border-border/60 text-sm">
            <span><span className={`text-[11px] px-2 py-1 rounded-md ${TYPE_CLASS[it.entity_type] || "bg-muted text-muted-foreground"}`}>{TYPE_BG[it.entity_type] || it.entity_type}</span></span>
            <span className="truncate font-medium">{it.name || "—"}</span>
            <span className="font-mono text-xs text-muted-foreground">{it.code || it.qr_id}</span>
            <span className="flex items-center gap-2"><QrSvg qrId={it.qr_id} size={48} /></span>
            <span className="text-center">
              <button onClick={async () => {
                try {
                  await API.patch(`/assets/qr/${it.qr_id}/status`, { status: it.status === "active" ? "inactive" : "active" });
                  load();
                } catch (err) { toast.error(err.response?.data?.detail || "Грешка"); }
              }} className={`text-[11px] px-2 py-1 rounded-md ${it.status === "active" ? "bg-emerald-500/15 text-emerald-400" : "bg-muted text-muted-foreground"}`}>
                {it.status === "active" ? "Активен" : "Неактивен"}
              </button>
            </span>
          </div>
        ))}
      </div>

      {/* Print layout — labels with QR + name + code */}
      <div id="qr-print" className="hidden print:block">
        <div className="grid grid-cols-3 gap-4">
          {items.map((it) => (
            <div key={it.qr_id} className="border border-gray-300 rounded p-3 flex flex-col items-center text-center break-inside-avoid">
              <QrSvg qrId={it.qr_id} size={120} />
              <div className="mt-2 text-sm font-semibold text-black">{it.name}</div>
              <div className="text-xs text-gray-600 font-mono">{it.code || it.qr_id}</div>
              <div className="text-[10px] text-gray-500">{TYPE_BG[it.entity_type] || it.entity_type}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
