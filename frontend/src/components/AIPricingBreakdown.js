import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  ChevronDown, ChevronRight, Package, Clock, TrendingUp,
} from "lucide-react";

/**
 * Displays AI pricing breakdown + materials for a proposal line.
 * Props: proposal = { hourly, hint, smallQty, explanation, materials, provider, confidence, type, subtype }
 */
export default function AIPricingBreakdown({ proposal: p }) {
  const [showMaterials, setShowMaterials] = useState(false);
  if (!p) return null;

  const primaryMats = (p.materials || []).filter(m => m.category === "primary");
  const secondaryMats = (p.materials || []).filter(m => m.category === "secondary");
  const consumables = (p.materials || []).filter(m => m.category === "consumable");
  const totalMats = (p.materials || []).length;

  return (
    <div className="space-y-1.5 mt-1">
      {/* Pricing explanation badges */}
      <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
        <span className="text-muted-foreground">{p.type}/{p.subtype}</span>
        
        {p.hourly && (
          <Badge variant="outline" className="text-[9px] bg-blue-500/10 text-blue-400 border-blue-500/30">
            <Clock className="w-2.5 h-2.5 mr-0.5 inline" />
            {p.hourly.worker_type} {p.hourly.hourly_rate} EUR/ч
            {p.hourly.min_applied && " (мин. работа)"}
          </Badge>
        )}
        {p.hourly?.is_demo && (
          <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/30">ДЕМО ставки</Badge>
        )}
        
        {p.smallQty > 0 && (
          <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/30">
            +{p.smallQty}% малко к-во
          </Badge>
        )}
        
        {p.hint?.available && (
          <Badge variant="outline" className="text-[9px] bg-violet-500/10 text-violet-400 border-violet-500/30">
            <TrendingUp className="w-2.5 h-2.5 mr-0.5 inline" />
            Вътр. {p.hint.range_label} EUR ({p.hint.sample_count}x)
          </Badge>
        )}
        
        {p.explanation && (
          <span className="text-muted-foreground/50 italic">{p.explanation.slice(0, 80)}</span>
        )}
      </div>

      {/* Materials section (collapsible) */}
      {totalMats > 0 && (
        <div>
          <button
            onClick={() => setShowMaterials(!showMaterials)}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            data-testid="toggle-materials"
          >
            {showMaterials ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <Package className="w-3 h-3" />
            <span>Материали ({totalMats})</span>
          </button>
          
          {showMaterials && (
            <div className="mt-1 pl-4 space-y-1.5 text-[10px]">
              {primaryMats.length > 0 && (
                <div>
                  <span className="text-emerald-400 font-medium">Основни</span>
                  {primaryMats.map((m, i) => (
                    <div key={i} className="flex items-center justify-between text-foreground/80 py-0.5">
                      <span>{m.name}</span>
                      <span className="font-mono text-muted-foreground ml-2">
                        {m.estimated_qty != null ? `${m.estimated_qty} ${m.unit}` : m.unit}
                        {m.reason && <span className="text-muted-foreground/50 ml-1">— {m.reason}</span>}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {secondaryMats.length > 0 && (
                <div>
                  <span className="text-amber-400 font-medium">Спомагателни</span>
                  {secondaryMats.map((m, i) => (
                    <div key={i} className="flex items-center justify-between text-foreground/80 py-0.5">
                      <span>{m.name}</span>
                      <span className="font-mono text-muted-foreground ml-2">
                        {m.estimated_qty != null ? `${m.estimated_qty} ${m.unit}` : m.unit}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {consumables.length > 0 && (
                <div>
                  <span className="text-gray-400 font-medium">Консумативи</span>
                  {consumables.map((m, i) => (
                    <div key={i} className="flex items-center justify-between text-foreground/80 py-0.5">
                      <span>{m.name}</span>
                      <span className="font-mono text-muted-foreground ml-2">
                        {m.estimated_qty != null ? `${m.estimated_qty} ${m.unit}` : m.unit}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
