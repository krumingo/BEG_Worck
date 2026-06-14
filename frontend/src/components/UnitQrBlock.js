import { useState, useEffect } from "react";
import API from "@/lib/api";
import { Printer, Loader2 } from "lucide-react";

// Показва QR на СЪЩЕСТВУВАЩ актив по неговия qr_id (не генерира нов).
// Плюс серийния номер и бутон Печат.
export default function UnitQrBlock({ qrId, serialNo }) {
  const [svg, setSvg] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    if (!qrId) return;
    (async () => {
      try {
        const res = await API.get(
          `/assets/qr/${qrId}/svg?base=${encodeURIComponent(window.location.origin)}`,
          { responseType: "text" }
        );
        if (alive) setSvg(String(res.data).replace(/<\?xml[^>]*\?>/, ""));
      } catch {
        if (alive) setErr(true);
      }
    })();
    return () => { alive = false; };
  }, [qrId]);

  if (!qrId || err) return null;

  const doPrint = () => {
    const w = window.open("", "_blank", "width=400,height=500");
    if (!w) return;
    w.document.write(`<html><head><title>${qrId}</title></head><body style="text-align:center;font-family:sans-serif;padding:24px;">${svg || ""}<div style="font-family:monospace;font-size:18px;margin-top:8px;">${qrId}</div>${serialNo ? `<div style="font-size:13px;color:#555;">Сериен №: ${serialNo}</div>` : ""}<script>window.onload=function(){window.print();}<\/script></body></html>`);
    w.document.close();
  };

  return (
    <div className="border border-border rounded-lg bg-card p-3 text-center" style={{ width: 150 }}>
      <div className="asset-qr-svg w-full aspect-square flex items-center justify-center" style={{ minHeight: 110 }}>
        {svg ? (
          <div dangerouslySetInnerHTML={{ __html: svg }} style={{ width: "100%", height: "100%" }} />
        ) : (
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        )}
      </div>
      <div className="font-mono text-sm mt-1.5">{qrId}</div>
      {serialNo && <div className="text-[11px] text-muted-foreground">Сериен №: {serialNo}</div>}
      <button
        onClick={doPrint}
        className="mt-2 w-full inline-flex items-center justify-center gap-1.5 text-xs bg-primary/10 text-primary rounded-md py-1.5 hover:bg-primary/20 transition-colors"
        data-testid="unit-qr-print"
      >
        <Printer className="w-3.5 h-3.5" />Печат
      </button>
      <style>{`.asset-qr-svg svg { width: 100%; height: 100%; display: block; }`}</style>
    </div>
  );
}
