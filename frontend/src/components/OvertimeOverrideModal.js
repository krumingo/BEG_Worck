/**
 * OvertimeOverrideModal — Admin override for >8h/day reports.
 * Shows each blocked report with split regular/overtime + coefficient + reason.
 */
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { AlertTriangle, Clock, Loader2 } from "lucide-react";

export default function OvertimeOverrideModal({ open, onOpenChange, blocked = [], onSubmit }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open || !blocked.length) return;
    const init = {};
    for (const b of blocked) {
      const h = b.report_hours || 0;
      init[b.id] = {
        regular_hours: String(Math.min(h, 8)),
        overtime_hours: String(Math.max(0, h - 8)),
        coef_mode: "",
        overtime_coefficient: "",
        reason: "",
      };
    }
    setRows(init);
  }, [open, blocked]);

  const update = (id, field, value) => {
    setRows(prev => ({ ...prev, [id]: { ...prev[id], [field]: value } }));
  };

  const validate = (id) => {
    const r = rows[id];
    if (!r) return [];
    const b = blocked.find(x => x.id === id);
    const h = b?.report_hours || 0;
    const errors = [];
    const reg = parseFloat(r.regular_hours) || 0;
    const ot = parseFloat(r.overtime_hours) || 0;
    if (Math.abs(reg + ot - h) > 0.01) errors.push(t("overtimeOverride.errSplit", { h }));
    if (reg < 0) errors.push(t("overtimeOverride.errRegularNeg"));
    if (ot < 0) errors.push(t("overtimeOverride.errOvertimeNeg"));
    const coef = parseFloat(r.overtime_coefficient) || 0;
    if (!coef || coef <= 1) errors.push(t("overtimeOverride.errCoef"));
    if (!r.reason?.trim()) errors.push(t("overtimeOverride.errReason"));
    return errors;
  };

  const allValid = blocked.every(b => validate(b.id).length === 0);

  const handleSubmit = async () => {
    if (!allValid) return;
    setSubmitting(true);
    const overrides = {};
    for (const b of blocked) {
      const r = rows[b.id];
      overrides[b.id] = {
        regular_hours: parseFloat(r.regular_hours),
        overtime_hours: parseFloat(r.overtime_hours),
        overtime_coefficient: parseFloat(r.overtime_coefficient),
        reason: r.reason.trim(),
      };
    }
    try {
      await onSubmit(overrides);
    } finally { setSubmitting(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-amber-400" />
            {t("overtimeOverride.title")}
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground mb-4">{t("overtimeOverride.description")}</p>

        <div className="space-y-4">
          {blocked.map(b => {
            const r = rows[b.id] || {};
            const errors = validate(b.id);
            const hasErr = errors.length > 0;

            return (
              <div key={b.id} className={`rounded-xl border p-4 space-y-3 ${hasErr ? "border-red-500/30" : "border-border"}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold">{b.worker_name}</p>
                    <p className="text-[10px] text-muted-foreground">{b.date || ""}{b.project_name ? ` · ${b.project_name}` : ""}</p>
                  </div>
                  <div className="flex gap-2">
                    <Badge variant="outline" className="text-[9px]"><Clock className="w-3 h-3 mr-1" />{t("overtimeOverride.dayTotal")}: {b.current_hours}ч</Badge>
                    <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/30">{t("overtimeOverride.reportTotal")}: {b.report_hours}ч</Badge>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label className="text-xs">{t("overtimeOverride.regularHours")}</Label>
                    <Input type="number" value={r.regular_hours || ""} onChange={e => update(b.id, "regular_hours", e.target.value)}
                      min="0" step="0.5" className={`h-9 font-mono ${hasErr ? "border-red-500/50" : ""}`} />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">{t("overtimeOverride.overtimeHours")}</Label>
                    <Input type="number" value={r.overtime_hours || ""} onChange={e => update(b.id, "overtime_hours", e.target.value)}
                      min="0" step="0.5" className={`h-9 font-mono ${hasErr ? "border-red-500/50" : ""}`} />
                  </div>
                </div>

                <div className="space-y-1">
                  <Label className="text-xs">{t("overtimeOverride.coefficient")}</Label>
                  <div className="flex gap-2">
                    <Select value={r.coef_mode || ""} onValueChange={v => {
                      update(b.id, "coef_mode", v);
                      if (v === "1.5") update(b.id, "overtime_coefficient", "1.5");
                      else if (v === "2.0") update(b.id, "overtime_coefficient", "2.0");
                      else update(b.id, "overtime_coefficient", "");
                    }}>
                      <SelectTrigger className="w-[140px] h-9"><SelectValue placeholder={t("overtimeOverride.selectCoef")} /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="1.5">1.5×</SelectItem>
                        <SelectItem value="2.0">2.0×</SelectItem>
                        <SelectItem value="custom">{t("overtimeOverride.custom")}</SelectItem>
                      </SelectContent>
                    </Select>
                    {r.coef_mode === "custom" && (
                      <Input type="number" value={r.overtime_coefficient || ""} onChange={e => update(b.id, "overtime_coefficient", e.target.value)}
                        min="1.01" step="0.1" placeholder={t("overtimeOverride.customCoefPlaceholder")} className="h-9 w-24 font-mono" />
                    )}
                  </div>
                </div>

                <div className="space-y-1">
                  <Label className="text-xs">{t("overtimeOverride.reason")}</Label>
                  <Textarea value={r.reason || ""} onChange={e => update(b.id, "reason", e.target.value)}
                    placeholder={t("overtimeOverride.reasonPlaceholder")} className="text-xs min-h-[50px]" />
                </div>

                {hasErr && (
                  <div className="text-[10px] text-red-400 space-y-0.5">
                    {errors.map((e, i) => <p key={i}>• {e}</p>)}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t("overtimeOverride.cancel")}</Button>
          <Button onClick={handleSubmit} disabled={!allValid || submitting} className="bg-amber-500 hover:bg-amber-600 text-black">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
            {t("overtimeOverride.submit", { count: blocked.length })}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
