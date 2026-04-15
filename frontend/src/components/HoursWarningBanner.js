/**
 * HoursWarningBanner — Shows warnings about daily hours.
 * Levels: ok (nothing), warning (>8h), critical (>12h)
 */
import { AlertTriangle, Clock, XCircle } from "lucide-react";

export default function HoursWarningBanner({ hoursInfo }) {
  if (!hoursInfo || hoursInfo.level === "ok") return null;

  const isCritical = hoursInfo.level === "critical";
  const borderCls = isCritical ? "border-red-500/40 bg-red-500/10" : "border-amber-500/40 bg-amber-500/10";
  const textCls = isCritical ? "text-red-400" : "text-amber-400";
  const Icon = isCritical ? XCircle : AlertTriangle;

  return (
    <div className={`rounded-lg border p-3 space-y-1.5 ${borderCls}`} data-testid="hours-warning-banner">
      <div className="flex items-center gap-2">
        <Icon className={`w-4 h-4 flex-shrink-0 ${textCls}`} />
        <span className={`text-xs font-semibold ${textCls}`}>
          {isCritical ? "Критично: " : "Внимание: "}
          {hoursInfo.total_hours}ч общо за деня
        </span>
      </div>
      {hoursInfo.warnings?.map((w, i) => (
        <p key={i} className={`text-[11px] ml-6 ${textCls}`}>{w}</p>
      ))}
      {isCritical && (
        <p className="text-[11px] ml-6 text-red-300 font-medium">
          Изисква се причина: извънреден труд, работа на повече обекти, или грешка.
        </p>
      )}
    </div>
  );
}
