/**
 * StockValueCard — Shows total warehouse value from FIFO batches.
 */
import { useState, useEffect } from "react";
import API from "@/lib/api";
import { DollarSign, Loader2 } from "lucide-react";

export default function StockValueCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    API.get("/warehouse/value").then(r => setData(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="rounded-xl border border-border bg-card p-4 flex items-center justify-center h-24"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  return (
    <div className="rounded-xl border border-border bg-card p-4" data-testid="stock-value-card">
      <div className="flex items-center gap-3 mb-2">
        <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center">
          <DollarSign className="w-5 h-5 text-emerald-400" />
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Стойност на склада</p>
          <p className="text-xl font-bold font-mono text-emerald-400">{(data.grand_total || 0).toLocaleString("bg-BG", { maximumFractionDigits: 0 })} BGN</p>
        </div>
      </div>
      {data.warehouses?.length > 0 && (
        <div className="space-y-1 mt-2">
          {data.warehouses.map(w => (
            <div key={w.warehouse_id} className="flex justify-between text-xs">
              <span className="text-muted-foreground">{w.name}</span>
              <span className="font-mono">{w.total_value.toLocaleString("bg-BG")} BGN ({w.items_count} арт.)</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
