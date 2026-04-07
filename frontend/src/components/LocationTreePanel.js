/**
 * LocationTreePanel — Дървовидна структура на локации в проект.
 * Embedded as a section in ProjectDetailPage.
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
  Building, Layers, DoorOpen, MapPin, Box, Plus, ChevronRight, ChevronDown,
  Trash2, Pencil, Check, X, Loader2, FileText, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

const TYPE_META = {
  building: { label: "Сграда", color: "text-blue-400" },
  floor: { label: "Етаж", color: "text-amber-400" },
  room: { label: "Помещение", color: "text-emerald-400" },
  zone: { label: "Зона", color: "text-purple-400" },
  element: { label: "Елемент", color: "text-rose-400" },
};

function getTypeIcon(type) {
  switch (type) {
    case "building": return Building;
    case "floor": return Layers;
    case "room": return DoorOpen;
    case "zone": return MapPin;
    default: return Box;
  }
}

// Flatten tree to render iteratively (avoids Babel max call stack)
function flattenTree(nodes, depth = 0) {
  const result = [];
  for (const node of nodes) {
    result.push({ ...node, _depth: depth });
    if (node.children && node.children.length > 0) {
      result.push(...flattenTree(node.children, depth + 1));
    }
  }
  return result;
}

export default function LocationTreePanel({ projectId }) {
  const { t } = useTranslation();
  const [tree, setTree] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({});
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState("");

  // Create dialog
  const [showCreate, setShowCreate] = useState(false);
  const [createParent, setCreateParent] = useState(null);
  const [createType, setCreateType] = useState("building");
  const [createName, setCreateName] = useState("");
  const [createCode, setCreateCode] = useState("");
  const [createArea, setCreateArea] = useState("");
  const [saving, setSaving] = useState(false);

  // SMR panel
  const [smrNode, setSmrNode] = useState(null);
  const [smrData, setSmrData] = useState(null);
  const [smrLoading, setSmrLoading] = useState(false);

  const loadTree = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/locations`);
      setTree(res.data.tree || []);
      setTotal(res.data.total || 0);
      // Auto-expand top level
      const autoExp = {};
      for (const n of res.data.tree || []) { autoExp[n.id] = true; }
      setExpanded(prev => ({ ...prev, ...autoExp }));
    } catch {
      toast.error(t("locations.loadError"));
    } finally {
      setLoading(false);
    }
  }, [projectId, t]);

  useEffect(() => { loadTree(); }, [loadTree]);

  // Build flat list of visible nodes
  const getVisibleNodes = (nodes, depth) => {
    const result = [];
    for (const node of nodes) {
      result.push({ ...node, _depth: depth });
      if (expanded[node.id] && node.children && node.children.length > 0) {
        result.push(...getVisibleNodes(node.children, depth + 1));
      }
    }
    return result;
  };
  const visibleNodes = getVisibleNodes(tree, 0);

  const toggleExpand = (id) => setExpanded(prev => ({ ...prev, [id]: !prev[id] }));

  const handleAdd = (parentNode) => {
    setCreateParent(parentNode || null);
    const typeMap = { building: "floor", floor: "room", room: "zone", zone: "element" };
    setCreateType(parentNode ? (typeMap[parentNode.type] || "room") : "building");
    setCreateName("");
    setCreateCode("");
    setCreateArea("");
    setShowCreate(true);
  };

  const handleCreate = async () => {
    if (!createName.trim()) { toast.error(t("locations.nameRequired")); return; }
    setSaving(true);
    try {
      await API.post(`/projects/${projectId}/locations`, {
        parent_id: createParent?.id || null,
        type: createType,
        name: createName.trim(),
        code: createCode.trim() || null,
        area_m2: createArea ? parseFloat(createArea) : null,
      });
      toast.success(t("locations.created"));
      setShowCreate(false);
      loadTree();
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    } finally {
      setSaving(false);
    }
  };

  const handleRename = async (nodeId) => {
    if (editName.trim()) {
      try {
        await API.put(`/locations/${nodeId}`, { name: editName.trim() });
        loadTree();
      } catch (err) {
        toast.error(err.response?.data?.detail || t("common.error"));
      }
    }
    setEditingId(null);
  };

  const handleDelete = async (node) => {
    if (!window.confirm(`${t("locations.confirmDelete")} "${node.name}"?`)) return;
    try {
      await API.delete(`/locations/${node.id}`);
      toast.success(t("locations.deleted"));
      if (smrNode?.id === node.id) { setSmrNode(null); setSmrData(null); }
      loadTree();
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    }
  };

  const handleSelectSMR = async (node) => {
    setSmrNode(node);
    setSmrLoading(true);
    try {
      const res = await API.get(`/locations/${node.id}/smr`);
      setSmrData(res.data);
    } catch {
      setSmrData({ missing_smr: [], extra_works: [], total: 0 });
    } finally {
      setSmrLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="location-tree-panel">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MapPin className="w-4 h-4 text-purple-400" />
          <span className="font-semibold text-sm">{t("locations.title")}</span>
          <Badge variant="outline" className="text-[10px]">{total}</Badge>
        </div>
        <Button size="sm" variant="outline" onClick={() => handleAdd(null)} data-testid="add-root-btn">
          <Plus className="w-3.5 h-3.5 mr-1" /> {t("locations.addBuilding")}
        </Button>
      </div>

      {tree.length === 0 ? (
        <div className="text-center py-6 text-muted-foreground text-sm">
          {t("locations.empty")}
        </div>
      ) : (
        <div className="border border-border rounded-lg p-2 max-h-[400px] overflow-y-auto bg-card/30">
          {visibleNodes.map((node) => {
            const meta = TYPE_META[node.type] || TYPE_META.element;
            const Icon = getTypeIcon(node.type);
            const hasChildren = node.children && node.children.length > 0;
            const isEditing = editingId === node.id;

            return (
              <div key={node.id} data-testid={`tree-node-${node.id}`}
                className="flex items-center gap-1 py-1.5 px-1 rounded hover:bg-muted/20 group"
                style={{ paddingLeft: `${node._depth * 20 + 4}px` }}
              >
                <button className="w-5 h-5 flex items-center justify-center flex-shrink-0" onClick={() => toggleExpand(node.id)}>
                  {hasChildren ? (
                    expanded[node.id] ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
                  ) : <span className="w-3.5" />}
                </button>

                <Icon className={`w-4 h-4 flex-shrink-0 ${meta.color}`} />

                {isEditing ? (
                  <div className="flex items-center gap-1 flex-1 min-w-0">
                    <Input value={editName} onChange={(e) => setEditName(e.target.value)} className="h-6 text-sm px-1" autoFocus
                      onKeyDown={(e) => { if (e.key === "Enter") handleRename(node.id); if (e.key === "Escape") setEditingId(null); }}
                    />
                    <button onClick={() => handleRename(node.id)} className="text-emerald-400 hover:text-emerald-300"><Check className="w-3.5 h-3.5" /></button>
                    <button onClick={() => setEditingId(null)} className="text-muted-foreground hover:text-white"><X className="w-3.5 h-3.5" /></button>
                  </div>
                ) : (
                  <button className="flex-1 text-left text-sm truncate text-foreground hover:text-white" onClick={() => handleSelectSMR(node)}>
                    {node.name}
                  </button>
                )}

                <Badge variant="outline" className="text-[9px] flex-shrink-0 opacity-60">{meta.label}</Badge>
                {node.metadata?.area_m2 && (
                  <span className="text-[10px] text-muted-foreground flex-shrink-0">{node.metadata.area_m2}м2</span>
                )}

                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                  <button onClick={() => handleAdd(node)} className="p-0.5 hover:text-emerald-400" title="Добави дете"><Plus className="w-3.5 h-3.5" /></button>
                  <button onClick={() => { setEditName(node.name); setEditingId(node.id); }} className="p-0.5 hover:text-amber-400" title="Преименувай"><Pencil className="w-3.5 h-3.5" /></button>
                  <button onClick={() => handleDelete(node)} className="p-0.5 hover:text-red-400" title="Изтрий"><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {smrNode && (
        <div className="border border-border rounded-lg p-3 bg-card/30" data-testid="smr-panel">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-amber-400" />
              <span className="text-sm font-medium">{t("locations.smrAt")} {smrNode.name}</span>
            </div>
            <Button variant="ghost" size="sm" onClick={() => { setSmrNode(null); setSmrData(null); }}>
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
          {smrLoading ? (
            <Loader2 className="w-4 h-4 animate-spin mx-auto" />
          ) : smrData && smrData.total > 0 ? (
            <div className="space-y-1 max-h-[200px] overflow-y-auto">
              {smrData.missing_smr.map((m) => (
                <div key={m.id} className="flex items-center justify-between text-xs p-1.5 rounded bg-muted/10">
                  <div className="flex items-center gap-2 min-w-0">
                    <AlertTriangle className="w-3 h-3 text-orange-400 flex-shrink-0" />
                    <span className="truncate">{m.smr_type || m.activity_type || "—"}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span>{m.qty} {m.unit}</span>
                    <Badge variant="outline" className="text-[9px]">{m.status}</Badge>
                  </div>
                </div>
              ))}
              {smrData.extra_works.map((e) => (
                <div key={e.id} className="flex items-center justify-between text-xs p-1.5 rounded bg-muted/10">
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText className="w-3 h-3 text-blue-400 flex-shrink-0" />
                    <span className="truncate">{e.title || "—"}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span>{e.qty} {e.unit}</span>
                    <Badge variant="outline" className="text-[9px]">{e.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground text-center py-2">{t("locations.noSMR")}</p>
          )}
        </div>
      )}

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("locations.addNode")}</DialogTitle>
            <DialogDescription>
              {createParent ? `${t("locations.childOf")} "${createParent.name}"` : t("locations.rootNode")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>{t("locations.nodeType")}</Label>
              <Select value={createType} onValueChange={setCreateType}>
                <SelectTrigger data-testid="create-type-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(TYPE_META).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>{t("locations.name")} *</Label>
              <Input value={createName} onChange={(e) => setCreateName(e.target.value)} placeholder={t("locations.namePlaceholder")} data-testid="create-name-input" autoFocus />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>{t("locations.code")}</Label>
                <Input value={createCode} onChange={(e) => setCreateCode(e.target.value)} placeholder="A1" />
              </div>
              <div className="space-y-1">
                <Label>{t("locations.area")}</Label>
                <Input type="number" value={createArea} onChange={(e) => setCreateArea(e.target.value)} placeholder="м2" min="0" step="0.1" />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleCreate} disabled={saving} data-testid="create-location-submit">
              {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}
              {!saving && <Plus className="w-4 h-4 mr-1" />}
              {t("common.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
