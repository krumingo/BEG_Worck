import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ArrowLeft, Loader2, QrCode, Wrench, Send, Warehouse } from "lucide-react";
import { toast } from "sonner";

export default function MyToolsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [tools, setTools] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [colleagues, setColleagues] = useState([]);
  const [scanOpen, setScanOpen] = useState(false);
  const [code, setCode] = useState("");
  const [actionFor, setActionFor] = useState(null); // { id, mode: "handover" | "return" }
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!user?.id) return;
    setLoading(true);
    try {
      const [u, w, us] = await Promise.all([
        API.get(`/assets/units?location_type=employee&location_id=${user.id}&page_size=100`),
        API.get(`/warehouses?page_size=100&active_only=false`),
        API.get(`/users`),
      ]);
      setTools(u.data?.items || []);
      setWarehouses(w.data?.items || []);
      setColleagues((us.data || []).filter((x) => x.id !== user.id && x.is_active !== false));
    } catch (err) {
      toast.error("Грешка при зареждане");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { load(); }, [load]);

  const openScan = () => {
    const c = code.trim();
    if (c) navigate(`/s/${c}`);
  };

  const doAction = async (unit) => {
    if (!target) { toast.error("Избери къде"); return; }
    setBusy(true);
    try {
      const body = actionFor.mode === "handover"
        ? { action: "handover", to_type: "employee", to_id: target }
        : { action: "return", to_type: "warehouse", to_id: target };
      await API.post(`/assets/units/${unit.id}/move`, body);
      toast.success(actionFor.mode === "handover" ? "Предаде инструмента" : "Върна в склада");
      setActionFor(null); setTarget("");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-background p-4 max-w-md mx-auto">
      <div className="flex items-center gap-2 mb-4">
        <Button variant="ghost" size="sm" onClick={() => navigate("/tech")}><ArrowLeft className="w-4 h-4" /></Button>
        <h1 className="text-lg font-bold">Моите инструменти</h1>
      </div>

      <Button onClick={() => setScanOpen((s) => !s)} className="w-full h-12 rounded-2xl mb-2 flex items-center justify-center gap-2">
        <QrCode className="w-5 h-5" /> Сканирай инструмент
      </Button>
      {scanOpen && (
        <div className="flex gap-2 mb-2">
          <Input placeholder="или въведи код (QR-000012)" value={code} onChange={(e) => setCode(e.target.value)} />
          <Button onClick={openScan}>Отвори</Button>
        </div>
      )}
      <p className="text-[11px] text-muted-foreground mb-4">Сканирай стикера с камерата на телефона, за да вземеш инструмент.</p>

      <p className="text-xs text-muted-foreground mb-2">При теб ({tools.length})</p>
      {loading ? (
        <div className="py-12 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
      ) : tools.length === 0 ? (
        <div className="py-10 text-center text-muted-foreground text-sm">Нямаш зачислени инструменти. Сканирай инструмент, за да го вземеш.</div>
      ) : (
        <div className="flex flex-col gap-2">
          {tools.map((it) => (
            <div key={it.id} className="rounded-xl border border-border p-3">
              <div className="flex items-center gap-3">
                <Wrench className="w-5 h-5 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold truncate">{it.item_name || "Актив"}{it.model ? ` · ${it.model}` : ""}</p>
                  <p className="text-[11px] text-muted-foreground font-mono">{it.qr_id}</p>
                </div>
              </div>
              {actionFor?.id === it.id ? (
                <div className="mt-3 flex flex-col gap-2">
                  <Select value={target} onValueChange={setTarget}>
                    <SelectTrigger><SelectValue placeholder={actionFor.mode === "handover" ? "Избери колега" : "Избери склад"} /></SelectTrigger>
                    <SelectContent>
                      {(actionFor.mode === "handover" ? colleagues : warehouses).map((o) => (
                        <SelectItem key={o.id} value={o.id}>
                          {actionFor.mode === "handover" ? (`${o.first_name || ""} ${o.last_name || ""}`.trim() || o.email) : o.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="flex gap-2">
                    <Button onClick={() => doAction(it)} disabled={busy} className="flex-1">{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Потвърди"}</Button>
                    <Button variant="outline" onClick={() => { setActionFor(null); setTarget(""); }}>Отказ</Button>
                  </div>
                </div>
              ) : (
                <div className="mt-2 flex gap-2">
                  <Button variant="outline" size="sm" className="flex-1" onClick={() => { setActionFor({ id: it.id, mode: "handover" }); setTarget(""); }}><Send className="w-3.5 h-3.5 mr-1" />Предай</Button>
                  <Button variant="outline" size="sm" className="flex-1" onClick={() => { setActionFor({ id: it.id, mode: "return" }); setTarget(""); }}><Warehouse className="w-3.5 h-3.5 mr-1" />Върни в склад</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
