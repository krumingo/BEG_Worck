/**
 * SMRGroupsPanel — Локация → Група → СМР линии (triple hierarchy).
 * Embedded in ProjectDetailPage.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  MapPin, Package, ChevronRight, ChevronDown, Plus, Trash2,
  Loader2, Layers, X,
} from "lucide-react";
import { toast } from "sonner";

export default function SMRGroupsPanel({ projectId }) {
  const { t } = useTranslation();
  const [treeData, setTreeData] = useState([]);
  const [grandTotal, setGrandTotal] = useState({});
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({});

  // Create group
  const [showCreate, setShowCreate] = useState(false);
  const [locations, setLocations] = useState([]);
  const [createLocId, setCreateLocId] = useState("");
  const [createName, setCreateName] = useState("");
  const [saving, setSaving] = useState(false);

  const loadTree = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/smr-groups/tree`);
      setTreeData(res.data.tree || []);
      setGrandTotal(res.data.grand_total || {});
      // Auto-expand first level
      const exp = {};
      for (const node of res.data.tree || []) {
        if (node.location?.id) exp[`loc-${node.location.id}`] = true;
      }
      setExpanded(prev => ({ ...prev, ...exp }));
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { loadTree(); }, [loadTree]);

  // Load locations for create dialog
  const openCreate = async () => {
    try {
      const res = await API.get(`/projects/${projectId}/locations`);
      setLocations(res.data.tree || []);
    } catch { /* */ }
    setCreateLocId("");
    setCreateName("");
    setShowCreate(true);
  };

  // Flatten location tree for dropdown
  const flatLocs = [];
  const flattenLocs = (nodes, depth = 0) => {
    for (const n of nodes) {
      flatLocs.push({ id: n.id, name: "  ".repeat(depth) + n.name, type: n.type });
      if (n.children) flattenLocs(n.children, depth + 1);
    }
  };
  flattenLocs(locations);

  const handleCreate = async () => {
    if (!createName.trim()) { toast.error(t("smrGroups.nameRequired")); return; }
    setSaving(true);
    try {
      await API.post(`/projects/${projectId}/smr-groups`, {
        location_id: createLocId || null,
        name: createName.trim(),
      });
      toast.success(t("smrGroups.created"));
      setShowCreate(false);
      loadTree();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setSaving(false); }
  };

  const handleDeleteGroup = async (groupId) => {
    if (!window.confirm(t("smrGroups.confirmDelete"))) return;
    try {
      await API.delete(`/smr-groups/${groupId}`);
      toast.success(t("smrGroups.deleted"));
      loadTree();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  const toggle = (key) => setExpanded(p => ({ ...p, [key]: !p[key] }));

  if (loading) return <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  return (
    <div className="space-y-3" data-testid="smr-groups-panel">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-indigo-400" />
          <span className="font-semibold text-sm">{t("smrGroups.title")}</span>
        </div>
        <Button size="sm" variant="outline" onClick={openCreate} data-testid="new-group-btn">
          <Plus className="w-3.5 h-3.5 mr-1" /> {t("smrGroups.newGroup")}
        </Button>
      </div>

      {treeData.length === 0 ? (
        <p className="text-center text-muted-foreground text-sm py-6">{t("smrGroups.empty")}</p>
      ) : (
        <div className="border border-border rounded-lg p-2 max-h-[500px] overflow-y-auto bg-card/30">
          {treeData.map((locNode) => {
            const locKey = `loc-${locNode.location?.id || "none"}`;
            const isLocExpanded = expanded[locKey];
            return (
              <div key={locKey} data-testid={`loc-node-${locNode.location?.id || "none"}`}>
                {/* Location header */}
                <div className="flex items-center gap-1 py-1.5 px-1 rounded hover:bg-muted/20 cursor-pointer" onClick={() => toggle(locKey)}>
                  {isLocExpanded ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />}
                  <MapPin className="w-4 h-4 text-blue-400" />
                  <span className="text-sm font-medium flex-1">{locNode.location?.name || t("smrGroups.noLocation")}</span>
                  <span className="text-xs text-muted-foreground">{locNode.groups?.length || 0} {t("smrGroups.groups")}</span>
                </div>

                {/* Groups */}
                {isLocExpanded && locNode.groups?.map((g) => {
                  const gKey = `grp-${g.id}`;
                  const isGrpExpanded = expanded[gKey];
                  return (
                    <div key={g.id} className="ml-5" data-testid={`group-node-${g.id}`}>
                      {/* Group header */}
                      <div className="flex items-center gap-1 py-1 px-1 rounded hover:bg-muted/20 group">
                        <button onClick={() => toggle(gKey)} className="w-4 h-4 flex items-center justify-center">
                          {g.lines?.length > 0 ? (isGrpExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />) : <span className="w-3" />}
                        </button>
                        <Package className="w-3.5 h-3.5" style={{ color: g.color || "#a78bfa" }} />
                        <span className="text-sm flex-1">{g.name}</span>
                        <span className="font-mono text-xs font-bold text-primary mr-1">{g.summary?.total_cost?.toFixed(0) || 0} лв</span>
                        <Badge variant="outline" className="text-[9px]">{g.summary?.lines_count || 0}</Badge>
                        <button onClick={() => handleDeleteGroup(g.id)} className="p-0.5 opacity-0 group-hover:opacity-100 hover:text-red-400">
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>

                      {/* Lines */}
                      {isGrpExpanded && g.lines?.map((ln) => (
                        <div key={ln.line_id || ln.source_id} className="ml-7 flex items-center gap-2 py-0.5 px-1 text-xs text-muted-foreground">
                          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 flex-shrink-0" />
                          <span className="flex-1 truncate">{ln.smr_type || "—"}</span>
                          <span className="font-mono">{ln.qty} {ln.unit}</span>
                          <span className="font-mono font-bold text-foreground">{(ln.final_total || 0).toFixed(0)} лв</span>
                          <Badge variant="outline" className="text-[8px]">{ln.source === "smr_analysis" ? "Анализ" : ln.source === "missing_smr" ? "Липсв." : "Доп."}</Badge>
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {/* Grand total bar */}
      {grandTotal.total_cost > 0 && (
        <div className="flex items-center justify-between p-2 rounded-lg bg-muted/20 text-xs">
          <span className="text-muted-foreground">{t("smrGroups.grandTotal")}</span>
          <div className="flex gap-4">
            <span>{t("smrGroups.material")}: <strong className="font-mono">{grandTotal.total_material?.toFixed(0) || 0}</strong></span>
            <span>{t("smrGroups.labor")}: <strong className="font-mono">{grandTotal.total_labor?.toFixed(0) || 0}</strong></span>
            <span className="font-bold text-primary font-mono">{grandTotal.total_cost?.toFixed(0) || 0} лв</span>
          </div>
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("smrGroups.newGroup")}</DialogTitle>
            <DialogDescription>{t("smrGroups.newGroupDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>{t("smrGroups.location")}</Label>
              <Select value={createLocId || "none"} onValueChange={v => setCreateLocId(v === "none" ? "" : v)}>
                <SelectTrigger data-testid="create-group-location"><SelectValue placeholder={t("smrGroups.selectLocation")} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("smrGroups.noLocationOpt")}</SelectItem>
                  {flatLocs.map(l => <SelectItem key={l.id} value={l.id}>{l.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>{t("smrGroups.groupName")} *</Label>
              <Input value={createName} onChange={e => setCreateName(e.target.value)} placeholder={t("smrGroups.groupNamePlaceholder")} data-testid="create-group-name" autoFocus />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleCreate} disabled={saving} data-testid="create-group-submit">
              {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}{t("common.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
