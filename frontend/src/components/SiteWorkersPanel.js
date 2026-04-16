/**
 * SiteWorkersPanel — Historical shortlist of workers who have been on this site.
 * Filtered extraction from reports + attendance + work_sessions. No new table.
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Users, Loader2, Eye } from "lucide-react";

export default function SiteWorkersPanel({ projectId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/site-workers`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  const workers = data?.workers || [];
  if (workers.length === 0) return (
    <div className="text-center py-6 text-muted-foreground text-sm">Няма регистрирани работници за този обект.</div>
  );

  return (
    <div className="space-y-3" data-testid="site-workers-panel">
      <div className="flex items-center gap-2">
        <Users className="w-4 h-4 text-cyan-400" />
        <h3 className="text-sm font-semibold">Работници на обекта</h3>
        <Badge variant="outline" className="text-[10px]">{workers.length}</Badge>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="border-gray-700">
              <TableHead className="text-gray-400 text-xs">Служител</TableHead>
              <TableHead className="text-gray-400 text-xs">Длъжност</TableHead>
              <TableHead className="text-gray-400 text-xs text-center">От дата</TableHead>
              <TableHead className="text-gray-400 text-xs text-center">Дни</TableHead>
              <TableHead className="text-gray-400 text-xs text-center">Отчети</TableHead>
              <TableHead className="text-gray-400 text-xs text-right">Часове</TableHead>
              <TableHead className="text-gray-400 text-xs text-right">Изплатено</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {workers.map(w => (
              <TableRow key={w.worker_id} className="border-gray-700 hover:bg-gray-800/30 cursor-pointer" onClick={() => navigate(`/employees/${w.worker_id}`)}>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {w.avatar_url ? (
                      <img src={`${process.env.REACT_APP_BACKEND_URL}${w.avatar_url}`} className="w-7 h-7 rounded-full object-cover" alt="" />
                    ) : (
                      <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary">
                        {(w.worker_name || "?").split(" ").map(n => n[0]).join("").slice(0, 2)}
                      </div>
                    )}
                    <div>
                      <p className="text-sm font-medium text-white">{w.worker_name}</p>
                      {!w.is_active && <Badge className="text-[8px] bg-red-500/20 text-red-400 border-red-500/30">Неактивен</Badge>}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-xs text-gray-400">{w.position || "—"}</TableCell>
                <TableCell className="text-xs text-center text-gray-400 font-mono">{w.first_date ? formatDate(w.first_date) : "—"}</TableCell>
                <TableCell className="text-xs text-center font-mono">{w.days_count}</TableCell>
                <TableCell className="text-xs text-center font-mono">{w.report_count}</TableCell>
                <TableCell className="text-xs text-right font-mono">{w.total_hours}ч</TableCell>
                <TableCell className="text-xs text-right font-mono text-emerald-400">{w.total_earned > 0 ? formatCurrency(w.total_earned, "BGN") : "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
