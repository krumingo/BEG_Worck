import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { formatDate } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Hammer, Trash2, FileText, Loader2, MapPin, Sparkles,
} from "lucide-react";

const STATUS_COLORS = {
  draft: "bg-gray-500/20 text-gray-400",
  converted: "bg-emerald-500/20 text-emerald-400",
  archived: "bg-gray-500/20 text-gray-500",
};
const STATUS_LABELS = { draft: "Чернова", converted: "В оферта", archived: "Архивиран" };

export default function ExtraWorksDraftPanel({ projectId, refreshKey }) {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState([]);
  const [creating, setCreating] = useState(false);

  const fetchDrafts = useCallback(async () => {
    try {
      const res = await API.get("/extra-works", { params: { project_id: projectId } });
      setDrafts(res.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { fetchDrafts(); }, [fetchDrafts, refreshKey]);

  const toggleSelect = (id) => {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const selectAllDrafts = () => {
    const draftIds = drafts.filter(d => d.status === "draft").map(d => d.id);
    setSelected(prev => prev.length === draftIds.length ? [] : draftIds);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Изтриване на реда?")) return;
    try {
      await API.delete(`/extra-works/${id}`);
      setSelected(prev => prev.filter(x => x !== id));
      fetchDrafts();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
  };

  const handleCreateOffer = async () => {
    if (selected.length === 0) return;
    setCreating(true);
    try {
      const res = await API.post("/extra-works/create-offer", {
        draft_ids: selected, currency: "EUR", vat_percent: 20,
      });
      setSelected([]);
      fetchDrafts();
      navigate(`/offers/${res.data.id}`);
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при създаване на оферта");
    } finally { setCreating(false); }
  };

  const draftItems = drafts.filter(d => d.status === "draft");
  const convertedItems = drafts.filter(d => d.status === "converted");

  if (loading) {
    return <div className="p-4 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></div>;
  }

  if (drafts.length === 0) return null;

  return (
    <div id="extra-works-section" className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="extra-works-panel">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Hammer className="w-5 h-5 text-amber-500" />
          <h3 className="font-semibold text-white">Допълнителни СМР ({drafts.length})</h3>
        </div>
        <div className="flex items-center gap-2">
          {draftItems.length > 0 && (
            <Button variant="outline" size="sm" onClick={selectAllDrafts} className="text-xs">
              {selected.length === draftItems.length ? "Размаркирай" : "Маркирай всички"}
            </Button>
          )}
          {selected.length > 0 && (
            <Button size="sm" onClick={handleCreateOffer} disabled={creating} className="bg-amber-500 hover:bg-amber-600 text-black" data-testid="create-extra-offer-btn">
              {creating ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <FileText className="w-4 h-4 mr-1" />}
              Създай оферта ({selected.length})
            </Button>
          )}
        </div>
      </div>

      {/* Draft items */}
      <div className="space-y-2">
        {draftItems.map(d => (
          <div key={d.id} className="flex items-start gap-3 p-3 rounded-lg bg-muted/20 hover:bg-muted/30 border border-transparent hover:border-border transition-colors" data-testid={`draft-row-${d.id}`}>
            <Checkbox checked={selected.includes(d.id)} onCheckedChange={() => toggleSelect(d.id)} className="mt-1" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-foreground truncate">{d.title}</span>
                <Badge variant="outline" className={`text-[10px] ${STATUS_COLORS[d.status]}`}>{STATUS_LABELS[d.status]}</Badge>
                {d.ai_confidence && (
                  <Badge variant="outline" className="text-[10px] bg-violet-500/10 text-violet-400 border-violet-500/30">
                    <Sparkles className="w-2.5 h-2.5 mr-0.5" /> AI
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1">
                <span>{d.qty} {d.unit}</span>
                {d.ai_total_price_per_unit && <span className="text-emerald-400 font-mono">{(d.ai_total_price_per_unit * d.qty).toFixed(2)} лв</span>}
                <span>{formatDate(d.work_date)}</span>
                {(d.location_floor || d.location_room) && (
                  <span className="flex items-center gap-0.5"><MapPin className="w-3 h-3" />{[d.location_floor && `Ет.${d.location_floor}`, d.location_room, d.location_zone].filter(Boolean).join(", ")}</span>
                )}
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => handleDelete(d.id)} className="text-destructive hover:text-destructive opacity-50 hover:opacity-100">
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        ))}
      </div>

      {/* Converted items */}
      {convertedItems.length > 0 && (
        <div className="mt-4 pt-3 border-t border-gray-700">
          <p className="text-xs text-muted-foreground mb-2">Конвертирани в оферта ({convertedItems.length})</p>
          {convertedItems.slice(0, 5).map(d => (
            <div key={d.id} className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
              <span className="truncate">{d.title}</span>
              <span className="font-mono">{d.qty} {d.unit}</span>
              <Badge variant="outline" className="text-[9px] bg-emerald-500/10 text-emerald-400">В оферта</Badge>
              {d.target_offer_id && (
                <Button variant="ghost" size="sm" className="h-5 text-[10px] text-primary" onClick={() => navigate(`/offers/${d.target_offer_id}`)}>
                  Виж оферта
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
