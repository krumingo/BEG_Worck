/**
 * SalesPage — Sales history + "Нова продажба" trigger for SalesWindow.
 */
import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { ShoppingCart, Plus, Loader2 } from "lucide-react";
import SalesWindow from "@/components/sales/SalesWindow";

export default function SalesPage() {
  const [sales, setSales] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showSale, setShowSale] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await API.get("/warehouse/batches?status=all&page_size=1");
      // Load sales from sales collection
      // For now show empty — sales collection is new
    } catch {}
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 space-y-6" data-testid="sales-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <ShoppingCart className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Продажби</h1>
            <p className="text-sm text-muted-foreground">FIFO продажби с маржова защита</p>
          </div>
        </div>
        <Button onClick={() => setShowSale(true)} data-testid="new-sale-btn">
          <Plus className="w-4 h-4 mr-2" />Нова продажба
        </Button>
      </div>

      <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground">
        <ShoppingCart className="w-10 h-10 mx-auto mb-3 opacity-30" />
        <p>Историята на продажбите ще се показва тук</p>
        <p className="text-xs mt-1">Натиснете "Нова продажба" за да започнете</p>
      </div>

      <SalesWindow
        open={showSale}
        onOpenChange={setShowSale}
        presetItemId=""
      />
    </div>
  );
}
