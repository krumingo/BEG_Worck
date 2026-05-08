/**
 * UnclearStatusCard — Shows count of workers with unclear daily status.
 * Reads from GET /attendance/unclear-status
 */
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, Users } from "lucide-react";

export default function UnclearStatusCard() {
  const [data, setData] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    API.get("/attendance/unclear-status").then(r => setData(r.data)).catch(() => {});
  }, []);

  if (!data || data.total === 0) return null;

  return (
    <button
      onClick={() => navigate("/site-attendance")}
      className="w-full rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-left hover:bg-amber-500/10 transition-colors mb-4"
      data-testid="unclear-status-card"
    >
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-semibold text-amber-400">Неясни по статут</p>
          <p className="text-xs text-muted-foreground">{data.total} от {data.checked} служители без ясен статус за днес</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold text-amber-400">{data.total}</p>
        </div>
      </div>
    </button>
  );
}
