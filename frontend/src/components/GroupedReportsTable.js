import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eye, MapPin, AlertTriangle, Check } from "lucide-react";

const STATUS_BADGE = {
  DRAFT:     { label: "Чернова",  cls: "bg-gray-500/15 text-gray-400 border-gray-500/30" },
  SUBMITTED: { label: "Подаден",  cls: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  APPROVED:  { label: "Одобрен",  cls: "bg-green-700/30 text-green-300 border-green-600/40", icon: Check },
  REJECTED:  { label: "Отхвърлен", cls: "bg-red-500/15 text-red-400 border-red-500/30" },
};

const PAYROLL_BADGE = {
  none:           { label: "—",          cls: "text-muted-foreground" },
  eligible:       { label: "За заплата", cls: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  batched:        { label: "В пакет",    cls: "bg-violet-500/15 text-violet-400 border-violet-500/30" },
  paid:           { label: "Платен",     cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
  partially_paid: { label: "Частично",   cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
  carry_forward:  { label: "Пренесен",   cls: "bg-orange-500/15 text-orange-400 border-orange-500/30" },
};

const GLASS = {
  critical: "bg-red-500/5 border-red-500/30 ring-1 ring-red-500/10",
  warning:  "bg-amber-500/5 border-amber-500/30 ring-1 ring-amber-500/10",
  ok:       "bg-card border-border",
};

export default function GroupedReportsTable({ items, bulk, onOpenDetail, onOpenOverrideForGroup }) {
  const groups = useMemo(() => {
    const map = new Map();
    for (const r of items) {
      const key = `${r.worker_id}__${r.date}`;
      if (!map.has(key)) {
        map.set(key, {
          key,
          worker_id: r.worker_id,
          worker_name: r.worker_name,
          worker_avatar: r.worker_avatar,
          date: r.date,
          day_total_hours: r.day_total_hours || 0,
          day_normal_hours: r.day_normal_hours || 0,
          day_overtime_hours: r.day_overtime_hours || 0,
          day_aggregate_overtime_hours: r.day_aggregate_overtime_hours || 0,
          day_warning_level: r.day_warning_level || "ok",
          day_warnings: r.day_warnings || [],
          day_report_count: r.day_report_count || 1,
          rows: [],
        });
      }
      map.get(key).rows.push(r);
    }
    // Sort rows within each group by created_at (oldest first).
    // Backend's enrich_hours_batch assigns normal/overtime in this order, so
    // the UI must display in the same order — otherwise the user sees, e.g.,
    // a "norm=3 ot=+5" row appearing before a "norm=5 ot=0" row, which is
    // confusing because it looks like the running total ran backwards.
    for (const g of map.values()) {
      g.rows.sort((a, b) => {
        const aCa = a.created_at || "";
        const bCa = b.created_at || "";
        if (aCa !== bCa) return aCa < bCa ? -1 : 1;
        return (a.id || "").localeCompare(b.id || "");
      });
    }
    return [...map.values()];
  }, [items]);

  if (!items.length) {
    return (
      <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground text-xs">
        Няма отчети за показване
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="grouped-reports">
      {groups.map(g => {
        const glass = GLASS[g.day_warning_level] || GLASS.ok;
        const isMulti = g.rows.length > 1;
        const hasOt = g.day_aggregate_overtime_hours > 0;
        const needsOverride = hasOt && g.rows.some(r => r.status !== "APPROVED" && r.overtime_hours > 0);

        return (
          <div key={g.key} className={`rounded-xl border p-3 transition-all ${glass}`} data-testid={`group-${g.key}`}>
            {/* Group header */}
            <div className="flex items-center gap-3 mb-2">
              {g.worker_avatar ? (
                <img src={`${process.env.REACT_APP_BACKEND_URL}${g.worker_avatar}`} className="w-7 h-7 rounded-full object-cover" alt="" />
              ) : (
                <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary">
                  {(g.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}
                </div>
              )}
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium text-foreground">{g.worker_name}</span>
                <span className="text-[10px] text-muted-foreground ml-2">{g.date}</span>
                {isMulti && <span className="text-[10px] text-muted-foreground ml-1">({g.rows.length} отчета)</span>}
              </div>
              <div className="flex items-center gap-3 text-xs font-mono">
                <span className="text-muted-foreground">{g.day_total_hours}ч</span>
                <span className="text-emerald-400">{g.day_normal_hours}н</span>
                {g.day_aggregate_overtime_hours > 0 && (
                  <span className="text-red-400 font-medium">+{g.day_aggregate_overtime_hours}и</span>
                )}
                {g.day_warning_level === "critical" && <AlertTriangle className="w-3.5 h-3.5 text-red-400" />}
                {g.day_warning_level === "warning" && <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
              </div>
              {needsOverride && (
                <button
                  onClick={() => onOpenOverrideForGroup?.(g)}
                  className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 transition-colors"
                  data-testid={`override-btn-${g.key}`}
                >
                  Изисква override
                </button>
              )}
            </div>

            {/* Warnings */}
            {g.day_warnings.length > 0 && (
              <div className="text-[10px] mb-2 px-2">
                {g.day_warnings.map((w, i) => (
                  <span key={i} className={g.day_warning_level === "critical" ? "text-red-400" : "text-amber-400"}>
                    {w}{" "}
                  </span>
                ))}
              </div>
            )}

            {/* Rows */}
            <div className="space-y-0.5">
              {g.rows.map((r, ri) => {
                const stCfg = STATUS_BADGE[r.status] || { label: r.status, cls: "bg-muted text-muted-foreground" };
                const payCfg = PAYROLL_BADGE[r.payroll_status] || PAYROLL_BADGE.none;
                const isApproved = r.status === "APPROVED";
                const hasRowOt = r.overtime_hours > 0;

                return (
                  <div
                    key={r.id}
                    className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-colors hover:bg-muted/20 ${bulk?.isSelected(r.id) ? "bg-primary/10" : ""}`}
                    data-testid={`report-row-${r.id}`}
                  >
                    <input
                      type="checkbox"
                      disabled={isApproved}
                      checked={bulk?.isSelected(r.id) || false}
                      onChange={() => bulk?.toggleId(r.id)}
                      className="rounded disabled:opacity-30 disabled:cursor-not-allowed w-3.5 h-3.5"
                      title={isApproved ? "Вече одобрен" : ""}
                    />
                    <span className="text-[10px] text-muted-foreground w-4">{ri + 1}</span>
                    {r.site_name ? (
                      <span className="text-[10px] text-primary truncate max-w-[90px] flex items-center gap-0.5">
                        <MapPin className="w-2.5 h-2.5 flex-shrink-0" />{r.site_name}
                      </span>
                    ) : <span className="text-[10px] text-muted-foreground w-[90px]">—</span>}
                    <span className="text-[10px] truncate max-w-[100px] text-muted-foreground">{r.smr_type || "—"}</span>
                    <span className="font-mono font-bold ml-auto w-8 text-right">{r.hours}</span>
                    <span className="font-mono text-emerald-400 w-8 text-right">{r.normal_hours}</span>
                    <span className={`font-mono w-8 text-right ${hasRowOt ? "text-red-400 font-medium" : "text-muted-foreground"}`}>
                      {hasRowOt ? `+${r.overtime_hours}` : "—"}
                    </span>
                    <span className="font-mono text-muted-foreground w-10 text-right text-[10px]">{r.hourly_rate > 0 ? r.hourly_rate : "—"}</span>
                    <span className={`font-mono w-12 text-right ${hasRowOt ? "text-red-400" : "text-primary"}`} title={r.earned_formula || ""}>
                      {r.labor_value > 0 ? r.labor_value.toFixed(0) : "—"}
                      {hasRowOt && r.overtime_coefficient && r.overtime_coefficient !== 1 ? ` ×${r.overtime_coefficient}` : ""}
                    </span>
                    <Badge variant="outline" className={`text-[8px] px-1.5 ${stCfg.cls}`}>
                      {stCfg.icon && <stCfg.icon className="w-2 h-2 mr-0.5" />}{stCfg.label}
                    </Badge>
                    {payCfg.label !== "—" && <Badge variant="outline" className={`text-[8px] px-1.5 ${payCfg.cls}`}>{payCfg.label}</Badge>}
                    <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => onOpenDetail?.(r)}>
                      <Eye className="w-3 h-3" />
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
