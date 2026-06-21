import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Check, X, Loader2, Package, MapPin, User, Inbox, CheckCheck } from "lucide-react";

export default function AssetsIntakeReviewPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState({}); // id -> bool
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    API.get("/assets/intake/pending")
      .then((r) => setItems(r.data?.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const act = async (id, action) => {
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      await API.post(`/assets/intake/${id}/${action}`);
      toast.success(action === "approve" ? "Одобрено — в склада" : "Отхвърлено");
      setItems((prev) => prev.filter((x) => x.id !== id));
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  };

  const approveAll = async () => {
    if (!items.length) return;
    setBulkBusy(true);
    try {
      const res = await API.post("/assets/intake/approve-bulk", { ids: items.map((x) => x.id) });
      toast.success(`Одобрени: ${res.data.approved?.length || 0}`);
      load();
    } catch {
      toast.error("Грешка при груповото одобрение");
    } finally {
      setBulkBusy(false);
    }
  };

  return (
    <div className="p-4 md:p-6 max-w-3xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2"><Inbox className="w-5 h-5" />Чакащи за одобрение</h1>
          <p className="text-sm text-muted-foreground">Заскладени, които още не са влезли в склада.</p>
        </div>
        {items.length > 0 && (
          <Button onClick={approveAll} disabled={bulkBusy} variant="outline" data-testid="approve-all">
            {bulkBusy ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <CheckCheck className="w-4 h-4 mr-1" />}Одобри всички
          </Button>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <Inbox className="w-10 h-10 mx-auto mb-2 opacity-40" />
          <p>Няма чакащи записи.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((it) => {
            const s = it.suggestion || {};
            return (
              <div key={it.id} className="rounded-2xl border border-border bg-card p-4" data-testid={`pending-${it.id}`}>
                <div className="flex gap-3">
                  {it.photo_b64 ? (
                    <img src={`data:image/jpeg;base64,${it.photo_b64}`} alt="" className="w-20 h-20 rounded-xl object-cover border border-border shrink-0" />
                  ) : (
                    <div className="w-20 h-20 rounded-xl bg-muted flex items-center justify-center shrink-0"><Package className="w-7 h-7 text-muted-foreground" /></div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold">{s.name || "Без име"}</span>
                      {s.type_label && <Badge variant="outline" className="text-[10px]">{s.type_label}</Badge>}
                      {it.matched_item_id && <Badge className="bg-emerald-500/20 text-emerald-400 text-[10px]">към съществуващ</Badge>}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {[s.brand, s.model].filter(Boolean).join(" ") || "—"}{s.serial_no ? ` · сер.№ ${s.serial_no}` : ""}
                    </p>
                    <div className="flex items-center gap-3 mt-1.5 text-xs text-muted-foreground flex-wrap">
                      <span className="flex items-center gap-1"><MapPin className="w-3 h-3" />{it.location_name || it.location_type}</span>
                      <span className="flex items-center gap-1"><User className="w-3 h-3" />{it.submitted_by_name}</span>
                      {s.estimated_price_eur != null && <span className="text-amber-400">~{s.estimated_price_eur} €</span>}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2 mt-3">
                  <Button variant="outline" size="sm" disabled={busy[it.id]} onClick={() => act(it.id, "reject")} className="flex-1"><X className="w-4 h-4 mr-1" />Отхвърли</Button>
                  <Button size="sm" disabled={busy[it.id]} onClick={() => act(it.id, "approve")} className="flex-1 bg-emerald-600 hover:bg-emerald-700">
                    {busy[it.id] ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Check className="w-4 h-4 mr-1" />Одобри</>}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
