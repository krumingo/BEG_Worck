/**
 * LocationPicker — Reusable dropdown/tree picker for selecting a location node.
 * Accepts project_id, loads tree, user picks a node, returns location_id + path.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Popover, PopoverContent, PopoverTrigger,
} from "@/components/ui/popover";
import {
  Building, Layers, DoorOpen, MapPin, Box,
  ChevronRight, ChevronDown, Loader2, X, ChevronsUpDown,
} from "lucide-react";

const TYPE_ICONS = {
  building: Building,
  floor: Layers,
  room: DoorOpen,
  zone: MapPin,
  element: Box,
};

const TYPE_LABELS = {
  building: "Сграда",
  floor: "Етаж",
  room: "Помещение",
  zone: "Зона",
  element: "Елемент",
};

function PickerNode({ node, depth, onSelect, selectedId }) {
  const [expanded, setExpanded] = useState(depth < 1);
  const hasChildren = node.children && node.children.length > 0;
  const Icon = TYPE_ICONS[node.type] || Box;
  const isSelected = selectedId === node.id;

  return (
    <div>
      <div
        className={`flex items-center gap-1 py-1 px-1 rounded cursor-pointer text-sm ${isSelected ? "bg-primary/20 text-primary" : "hover:bg-muted/30"}`}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        onClick={() => onSelect(node)}
      >
        {hasChildren ? (
          <button onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }} className="w-4 h-4 flex items-center justify-center">
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </button>
        ) : <span className="w-4" />}
        <Icon className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
        <span className="truncate flex-1">{node.name}</span>
        <span className="text-[9px] text-muted-foreground flex-shrink-0">{TYPE_LABELS[node.type]}</span>
      </div>
      {expanded && hasChildren && node.children.map((c) => (
        <PickerNode key={c.id} node={c} depth={depth + 1} onSelect={onSelect} selectedId={selectedId} />
      ))}
    </div>
  );
}

function buildPath(tree, targetId, path = []) {
  for (const node of tree) {
    if (node.id === targetId) return [...path, node];
    if (node.children?.length) {
      const found = buildPath(node.children, targetId, [...path, node]);
      if (found) return found;
    }
  }
  return null;
}

export default function LocationPicker({ projectId, value, onChange, placeholder }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [tree, setTree] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);

  const loadTree = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const res = await API.get(`/projects/${projectId}/locations`);
      setTree(res.data.tree || []);
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { if (open && tree.length === 0) loadTree(); }, [open, tree.length, loadTree]);
  useEffect(() => { setTree([]); setSelectedNode(null); }, [projectId]);

  // Find selected node in tree on mount if value provided
  useEffect(() => {
    if (value && tree.length > 0 && !selectedNode) {
      const path = buildPath(tree, value);
      if (path) setSelectedNode(path[path.length - 1]);
    }
  }, [value, tree, selectedNode]);

  const handleSelect = (node) => {
    setSelectedNode(node);
    onChange?.(node.id, node);
    setOpen(false);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    setSelectedNode(null);
    onChange?.(null, null);
  };

  const displayPath = selectedNode && tree.length > 0
    ? buildPath(tree, selectedNode.id)?.map((n) => n.name).join(" > ")
    : null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className="w-full justify-between text-sm h-9 font-normal"
          data-testid="location-picker-trigger"
        >
          {selectedNode ? (
            <div className="flex items-center gap-1 min-w-0 flex-1">
              {(() => { const I = TYPE_ICONS[selectedNode.type] || Box; return <I className="w-3.5 h-3.5 flex-shrink-0 text-muted-foreground" />; })()}
              <span className="truncate">{displayPath || selectedNode.name}</span>
            </div>
          ) : (
            <span className="text-muted-foreground">{placeholder || t("locations.selectLocation")}</span>
          )}
          <div className="flex items-center gap-1 flex-shrink-0">
            {selectedNode && (
              <button onClick={handleClear} className="hover:text-destructive p-0.5"><X className="w-3 h-3" /></button>
            )}
            <ChevronsUpDown className="w-3.5 h-3.5 text-muted-foreground" />
          </div>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-2 max-h-[300px] overflow-y-auto" align="start">
        {loading ? (
          <div className="flex items-center justify-center py-4"><Loader2 className="w-4 h-4 animate-spin" /></div>
        ) : tree.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-3">{t("locations.empty")}</p>
        ) : (
          tree.map((node) => (
            <PickerNode key={node.id} node={node} depth={0} onSelect={handleSelect} selectedId={value} />
          ))
        )}
      </PopoverContent>
    </Popover>
  );
}
