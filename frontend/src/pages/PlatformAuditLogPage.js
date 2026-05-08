import { useState, useEffect } from "react";
import API from "@/lib/api";
import { ScrollText, Loader2, User, Calendar, FileText } from "lucide-react";

export default function PlatformAuditLogPage() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    fetchLogs();
  }, []);

  const fetchLogs = async () => {
    try {
      const res = await API.get("/audit-logs?limit=100");
      setLogs(res.data.logs || []);
      setTotal(res.data.total || 0);
    } catch (err) {
      console.error("Failed to fetch audit logs:", err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-violet-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="platform-audit-log-page">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <ScrollText className="w-6 h-6 text-violet-500" />
          Audit Log
        </h1>
        <p className="text-slate-400 mt-1">{total} total events</p>
      </div>

      <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="text-left text-xs font-medium text-slate-400 uppercase tracking-wider p-4">Timestamp</th>
                <th className="text-left text-xs font-medium text-slate-400 uppercase tracking-wider p-4">User</th>
                <th className="text-left text-xs font-medium text-slate-400 uppercase tracking-wider p-4">Action</th>
                <th className="text-left text-xs font-medium text-slate-400 uppercase tracking-wider p-4">Entity</th>
                <th className="text-left text-xs font-medium text-slate-400 uppercase tracking-wider p-4">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center py-8 text-slate-500">
                    No audit logs found
                  </td>
                </tr>
              ) : (
                logs.map((log, idx) => (
                  <tr key={log.id || idx} className="hover:bg-slate-800/50">
                    <td className="p-4 text-sm text-slate-300">
                      <div className="flex items-center gap-2">
                        <Calendar className="w-4 h-4 text-slate-500" />
                        {new Date(log.timestamp).toLocaleString()}
                      </div>
                    </td>
                    <td className="p-4 text-sm">
                      <div className="flex items-center gap-2">
                        <User className="w-4 h-4 text-slate-500" />
                        <span className="text-slate-300">{log.user_email || log.user_id}</span>
                      </div>
                    </td>
                    <td className="p-4">
                      <span className={`inline-flex px-2 py-1 rounded text-xs font-medium ${
                        log.action?.includes('delete') ? 'bg-red-500/20 text-red-400' :
                        log.action?.includes('create') ? 'bg-emerald-500/20 text-emerald-400' :
                        log.action?.includes('PROMOTED') ? 'bg-violet-500/20 text-violet-400' :
                        'bg-slate-700 text-slate-300'
                      }`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="p-4 text-sm text-slate-400">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-slate-500" />
                        {log.entity_type} / {log.entity_id?.slice(0, 8)}...
                      </div>
                    </td>
                    <td className="p-4 text-sm text-slate-500 max-w-xs truncate">
                      {JSON.stringify(log.changes || {})}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
