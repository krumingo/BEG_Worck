import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ChevronLeft, ChevronRight, Clock } from "lucide-react";

const ACTION_COLORS = {
  login: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  created: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  updated: "bg-primary/20 text-primary border-primary/30",
  deleted: "bg-destructive/20 text-destructive border-destructive/30",
  toggled: "bg-violet-500/20 text-violet-400 border-violet-500/30",
};

export default function AuditLogPage() {
  const { t } = useTranslation();
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const limit = 20;

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await API.get(`/audit-logs?limit=${limit}&skip=${page * limit}`);
      setLogs(res.data.logs);
      setTotal(res.data.total);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const totalPages = Math.ceil(total / limit);

  return (
    <div className="p-8 max-w-[1200px]" data-testid="audit-log-page">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">{t("auditLog.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {total} {t("common.total")}
        </p>
      </div>

      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="audit-table">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("auditLog.timestamp")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("auditLog.user")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("auditLog.action")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("auditLog.entity")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("auditLog.details")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-10 text-muted-foreground">
                    {t("auditLog.noLogs")}
                  </TableCell>
                </TableRow>
              ) : (
                logs.map((log) => (
                  <TableRow key={log.id} className="table-row-hover" data-testid={`audit-row-${log.id}`}>
                    <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <Clock className="w-3.5 h-3.5" />
                        {new Date(log.timestamp).toLocaleString()}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-foreground">{log.user_email}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs capitalize ${ACTION_COLORS[log.action] || ""}`}>
                        {t(`auditLog.actions.${log.action}`, log.action)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-foreground capitalize">{log.entity_type}</TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate">
                      {Object.keys(log.details || {}).length > 0
                        ? JSON.stringify(log.details)
                        : "-"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4" data-testid="audit-pagination">
          <p className="text-sm text-muted-foreground">
            {page + 1} / {totalPages}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              data-testid="audit-prev-page"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              data-testid="audit-next-page"
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
