/**
 * BudgetForecastPanel — Labor budget forecast with man-days formula + burn tracking.
 * Embedded in ProjectFinancialPage or ProjectProgressPage.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Calculator, TrendingUp, AlertTriangle, Loader2, RefreshCcw,
  Users, Calendar, DollarSign, Target,
} from "lucide-react";

export default function BudgetForecastPanel({ projectId }) {
  const { t } = useTranslation();
  const [health, setHealth] = useState(null);
  const [ev, setEv] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [hRes, evRes] = await Promise.all([
        API.get(`/projects/${projectId}/budget-health`),
        API.get(`/projects/${projectId}/earned-value`),
      ]);
      setHealth(hRes.data);
      setEv(evRes.data);
    } catch { /* optional */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  const burnColor = (pct) => pct > 100 ? "text-red-400" : pct > 80 ? "text-amber-400" : "text-emerald-400";
  const burnBg = (pct) => pct > 100 ? "bg-red-500" : pct > 80 ? "bg-amber-500" : "bg-emerald-500";

  return (
    <div className="space-y-4" data-testid="budget-forecast-panel">
      {/* Budget Health */}
      {health && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <DollarSign className="w-4 h-4 text-emerald-400" />
            <span className="font-semibold text-sm">{t("budgetForecast.budgetHealth")}</span>
          </div>

          {/* Summary bar */}
          <div className="grid grid-cols-4 gap-3 mb-3">
            <div className="text-center">
              <p className="text-[10px] text-muted-foreground">{t("budgetForecast.totalBudget")}</p>
              <p className="font-mono font-bold text-sm">{health.total_budget.toFixed(0)}</p>
            </div>
            <div className="text-center">
              <p className="text-[10px] text-muted-foreground">{t("budgetForecast.totalSpent")}</p>
              <p className={`font-mono font-bold text-sm ${burnColor(health.burn_pct)}`}>{health.total_spent.toFixed(0)}</p>
            </div>
            <div className="text-center">
              <p className="text-[10px] text-muted-foreground">{t("budgetForecast.remaining")}</p>
              <p className="font-mono font-bold text-sm">{health.total_remaining.toFixed(0)}</p>
            </div>
            <div className="text-center">
              <p className="text-[10px] text-muted-foreground">{t("budgetForecast.burnPct")}</p>
              <p className={`font-mono font-bold text-sm ${burnColor(health.burn_pct)}`}>{health.burn_pct}%</p>
            </div>
          </div>

          <Progress value={Math.min(health.burn_pct, 100)} className="h-2" />

          {/* Activities */}
          {health.activities.length > 0 && (
            <div className="mt-3 space-y-1">
              {health.activities.map((a, i) => {
                const st = a.status === "over_budget" ? "bg-red-500/20 text-red-400" : a.status === "warning" ? "bg-amber-500/20 text-amber-400" : "bg-emerald-500/20 text-emerald-400";
                return (
                  <div key={i} className="flex items-center justify-between text-xs p-1.5 rounded bg-muted/10">
                    <span className="truncate flex-1">{a.type} {a.subtype && `/ ${a.subtype}`}</span>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="font-mono">{a.spent.toFixed(0)}/{a.budget.toFixed(0)}</span>
                      <Badge variant="outline" className={`text-[9px] ${st}`}>{a.burn_pct}%</Badge>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Earned Value */}
      {ev && ev.BAC > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Target className="w-4 h-4 text-cyan-400" />
            <span className="font-semibold text-sm">{t("budgetForecast.earnedValue")}</span>
            <Badge variant="outline" className={`text-[9px] ${ev.status === "on_track" ? "text-emerald-400" : ev.status === "at_risk" ? "text-amber-400" : "text-red-400"}`}>
              {ev.status === "on_track" ? "On Track" : ev.status === "at_risk" ? "At Risk" : "Over Budget"}
            </Badge>
          </div>

          <div className="grid grid-cols-3 gap-3 text-center text-xs">
            <div>
              <p className="text-muted-foreground">CPI</p>
              <p className={`font-mono font-bold text-lg ${ev.CPI >= 1 ? "text-emerald-400" : ev.CPI >= 0.8 ? "text-amber-400" : "text-red-400"}`}>{ev.CPI.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">SPI</p>
              <p className={`font-mono font-bold text-lg ${ev.SPI >= 1 ? "text-emerald-400" : ev.SPI >= 0.8 ? "text-amber-400" : "text-red-400"}`}>{ev.SPI.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("budgetForecast.progress")}</p>
              <p className="font-mono font-bold text-lg">{ev.progress_pct}%</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 mt-2 text-xs">
            {[
              { label: "BAC", val: ev.BAC },
              { label: "EV", val: ev.EV },
              { label: "AC", val: ev.AC },
              { label: "PV", val: ev.PV },
              { label: "EAC", val: ev.EAC },
              { label: "VAC", val: ev.VAC },
            ].map(({ label, val }) => (
              <div key={label} className="flex justify-between p-1 bg-muted/10 rounded">
                <span className="text-muted-foreground">{label}</span>
                <span className="font-mono">{(val || 0).toFixed(0)} лв</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!health && !ev && (
        <p className="text-xs text-muted-foreground text-center py-4">{t("budgetForecast.noData")}</p>
      )}
    </div>
  );
}
