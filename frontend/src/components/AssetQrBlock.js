import { useState, useEffect } from "react";
import API from "@/lib/api";
import { QrCode, Printer, Loader2 } from "lucide-react";

// Reusable QR block for a card (employee / project / warehouse).
// Ensures the entity has a QR (idempotent generate → returns existing), shows the
// QR image (fetched with the auth token, so an <img src> won't do) + code + print.
export default function AssetQrBlock({ entityType, entityId, name, code }) {
  const [qrId, setQrId] = useState(null);
  const [svg, setSvg] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    if (!entityId) return;
    (async () => {
      try {
        const res = await API.post("/assets/qr/generate", { entity_type: entityType, entity_id: entityId });
        const id = res.data?.qr_id;
        if (!alive) return;
        setQrId(id);
        if (id) {
          const svgRes = await API.get(`/assets/qr/${id}/svg`, { responseType: "text" });
          if (alive) setSvg(String(svgRes.data).replace(/<\?xml[^>]*\?>/, ""));
        }
      } catch (e) {
        if (alive) setErr(true);
      }
    })();
    return () => { alive = false; };
  }, [entityType, entityId]);

  if (err) return null; // never break the card if QR can't load

  return (
    <div className="asset-qr-card border border-border rounded-lg bg-card p-2.5 text-center" style={{ width: 132 }}>
      <style>{`
        .asset-qr-svg svg { width: 100%; height: 100%; display: block; }
        @media screen { .asset-qr-print { display: none; } }
        @media print {
          body * { visibility: hidden !important; }
          .asset-qr-print, .asset-qr-print * { visibility: visible !important; }
          .asset-qr-print { position: absolute; left: 0; top: 0; width: 100%; text-align: center; }
        }
      `}</style>
      <div className="bg-white rounded mx-auto flex items-center justify-center" style={{ width: 96, height: 96 }}>
        {svg
          ? <div className="asset-qr-svg" style={{ width: 88, height: 88 }} dangerouslySetInnerHTML={{ __html: svg }} />
          : <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
      </div>
      <p className="font-mono text-xs font-semibold mt-1.5">{qrId || "—"}</p>
      <button
        onClick={() => window.print()}
        disabled={!svg}
        className="mt-1.5 w-full py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium flex items-center justify-center gap-1 disabled:opacity-50"
      >
        <Printer className="w-3.5 h-3.5" /> Печат
      </button>

      {/* Print-only label */}
      {svg && (
        <div className="asset-qr-print">
          <div style={{ display: "inline-block", padding: 16, textAlign: "center" }}>
            <div style={{ width: 200, height: 200, margin: "0 auto" }} dangerouslySetInnerHTML={{ __html: svg }} />
            <div style={{ fontSize: 16, fontWeight: 600, marginTop: 8, color: "#000" }}>{name}</div>
            <div style={{ fontSize: 13, fontFamily: "monospace", color: "#333" }}>{code || qrId}</div>
          </div>
        </div>
      )}
    </div>
  );
}
