import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Users, Plus, Loader2, Trash2, ArrowLeft, UserPlus, X } from "lucide-react";

export default function BrigadesPage() {
  const navigate = useNavigate();
  const [brigades, setBrigades] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [addUserId, setAddUserId] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, e] = await Promise.all([API.get("/brigades"), API.get("/employees")]);
      setBrigades(b.data || []);
      setEmployees(e.data || []);
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const openBrigade = async (id) => {
    try {
      const res = await API.get(`/brigades/${id}`);
      setSelected(res.data);
    } catch (err) { console.error(err); }
  };

  const createBrigade = async () => {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      const res = await API.post("/brigades", { name: newName.trim() });
      setNewName("");
      await load();
      openBrigade(res.data.id);
    } catch (err) { console.error(err); }
    setBusy(false);
  };

  const addMember = async () => {
    if (!addUserId || !selected) return;
    setBusy(true);
    try {
      const res = await API.post(`/brigades/${selected.id}/members`, { user_id: addUserId });
      setSelected(res.data);
      setAddUserId("");
      load();
    } catch (err) { console.error(err); }
    setBusy(false);
  };

  const removeMember = async (uid) => {
    if (!selected) return;
    try {
      const res = await API.delete(`/brigades/${selected.id}/members/${uid}`);
      setSelected(res.data);
      load();
    } catch (err) { console.error(err); }
  };

  // Akord employees not already in the selected brigade
  const akordCandidates = employees.filter(
    (e) => e.pay_type === "Akord" && !(selected?.member_ids || []).includes(e.user_id || e.id)
  );

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-5">
        <Button variant="ghost" size="sm" onClick={() => navigate("/employees")}><ArrowLeft className="w-4 h-4 mr-1" /> Служители</Button>
        <h1 className="text-xl font-bold flex items-center gap-2"><Users className="w-5 h-5" /> Бригади</h1>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[300px_1fr] gap-5">
        {/* List + create */}
        <div>
          <div className="flex gap-2 mb-3">
            <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Нова бригада…" className="h-9" />
            <Button onClick={createBrigade} disabled={busy || !newName.trim()} size="sm"><Plus className="w-4 h-4" /></Button>
          </div>
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
          ) : (
            <div className="flex flex-col gap-2">
              {brigades.length === 0 && <p className="text-sm text-muted-foreground px-1">Няма бригади още.</p>}
              {brigades.map((b) => (
                <button key={b.id} onClick={() => openBrigade(b.id)}
                  className={`text-left rounded-lg border p-3 transition ${selected?.id === b.id ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted/40"}`}>
                  <div className="font-medium text-sm">{b.name}</div>
                  <div className="text-[11px] text-muted-foreground">{(b.member_ids || []).length} души · акорд</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Detail */}
        <div className="rounded-lg border border-border p-4 bg-card">
          {!selected ? (
            <p className="text-sm text-muted-foreground">Избери бригада отляво или създай нова.</p>
          ) : (
            <>
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-semibold text-lg">{selected.name}</h2>
                <Badge variant="outline">{(selected.members || []).length} души</Badge>
              </div>

              <div className="text-xs text-muted-foreground mb-2">Членове (акорд досиета)</div>
              <div className="flex flex-col gap-2 mb-4">
                {(selected.members || []).length === 0 && <p className="text-sm text-muted-foreground">Няма добавени хора.</p>}
                {(selected.members || []).map((m) => (
                  <div key={m.user_id} className="flex items-center justify-between bg-muted/30 rounded-lg px-3 py-2">
                    <span className="text-sm">{m.name || m.user_id}
                      {selected.leader_user_id === m.user_id && <Badge className="ml-2 text-[9px]" variant="secondary">бригадир</Badge>}
                    </span>
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => removeMember(m.user_id)}><X className="w-4 h-4" /></Button>
                  </div>
                ))}
              </div>

              <div className="flex gap-2 items-center border-t border-border pt-3">
                <Select value={addUserId} onValueChange={setAddUserId}>
                  <SelectTrigger className="h-9 text-sm"><SelectValue placeholder="Добави човек (акорд досиета)…" /></SelectTrigger>
                  <SelectContent>
                    {akordCandidates.length === 0 && <div className="px-3 py-2 text-xs text-muted-foreground">Няма свободни акорд служители</div>}
                    {akordCandidates.map((e) => (
                      <SelectItem key={e.user_id || e.id} value={e.user_id || e.id}>{e.first_name} {e.last_name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button onClick={addMember} disabled={busy || !addUserId} size="sm"><UserPlus className="w-4 h-4 mr-1" /> Добави</Button>
              </div>
              <p className="text-[11px] text-muted-foreground mt-3">Член може да е и на заплата в други периоди — досието е едно; тук се групира само за акорд.</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
