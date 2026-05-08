/**
 * AlarmsDashboardPage — Centralized alarm dashboard.
 * Route: /alarms
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Bell, AlertTriangle, AlertCircle, Info, Loader2, Check, Eye, RefreshCcw,
} from "lucide-react";
import { toast } from "sonner";

const SEV_CFG = {
  critical: { icon: AlertCircle, color: "text-red-400", bg: "bg-red-500/10 border-red-500/30", label: "Critical" },
  warning: { icon: AlertTriangle, color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/30", label: "Warning" },
  info: { icon: Info, color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/30", label: "Info" },
};

export default function AlarmsDashboardPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({ critical: 0, warning: 0, info: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [fSeverity, setFSeverity] = useState("");
  const [fStatus, setFStatus] = useState("active");
  const [evaluating, setEvaluating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (fSeverity) p.append("severity", fSeverity);
      if (fStatus) p.append("status", fStatus);
      const [alarmsRes, countRes] = await Promise.all([
        API.get(`/alarms?${p}`),
        API.get("/alarms/count"),
      ]);
      setItems(alarmsRes.data.items || []);
      setCounts(countRes.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [fSeverity, fStatus]);

  useEffect(() => { load(); }, [load]);

  const handleAcknowledge = async (id) => {
    try {
      await API.put(`/alarms/${id}/acknowledge`, {});
      toast.success(t("alarms.acknowledged"));
      load();
    } catch (err) { toast.error(t("common.error")); }
  };

  const handleResolve = async (id) => {
    try {
      await API.put(`/alarms/${id}/resolve`, {});
      toast.success(t("alarms.resolved"));
      load();
    } catch (err) { toast.error(t("common.error")); }
  };

  const handleEvaluate = async () => {
    setEvaluating(true);
    try {
      const res = await API.post("/alarms/evaluate");
      toast.success(`${t("alarms.evaluated")}: ${res.data.new_events} ${t("alarms.newEvents")}`);
      load();
    } catch (err) { toast.error(t("common.error")); }
    finally { setEvaluating(false); }
  };

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-5xl mx-auto" data-testid="alarms-dashboard-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-red-500/10 flex items-center justify-center">
            <Bell className="w-5 h-5 text-red-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold">{t("alarms.title")}</h1>
            <p className="text-sm text-muted-foreground">{t("alarms.subtitle")}</p>
          </div>
        </div>
        <Button variant="outline" onClick={handleEvaluate} disabled={evaluating} data-testid="evaluate-btn">
          {evaluating ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <RefreshCcw className="w-4 h-4 mr-1" />}
          {t("alarms.evaluate")}
        </Button>
      </div>

      {/* Severity cards */}
      <div className="grid grid-cols-3 gap-3">
        {["critical", "warning", "info"].map(sev => {
          const cfg = SEV_CFG[sev];
          const Icon = cfg.icon;
          return (
            <Card key={sev} className={`border ${counts[sev] > 0 ? cfg.bg : ""}`}>
              <CardContent className="p-4 text-center">
                <Icon className={`w-6 h-6 mx-auto mb-1 ${cfg.color}`} />
                <p className={`text-2xl font-bold font-mono ${cfg.color}`}>{counts[sev]}</p>
                <p className="text-[10px] text-muted-foreground uppercase">{cfg.label}</p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <Select value={fSeverity || "all"} onValueChange={v => setFSeverity(v === "all" ? "" : v)}>
          <SelectTrigger className="w-40"><SelectValue placeholder={t("alarms.allSeverity")} /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.all")}</SelectItem>
            <SelectItem value="critical">Critical</SelectItem>
            <SelectItem value="warning">Warning</SelectItem>
            <SelectItem value="info">Info</SelectItem>
          </SelectContent>
        </Select>
        <Select value={fStatus || "all"} onValueChange={v => setFStatus(v === "all" ? "" : v)}>
          <SelectTrigger className="w-40"><SelectValue placeholder={t("common.status")} /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.all")}</SelectItem>
            <SelectItem value="active">{t("alarms.active")}</SelectItem>
            <SelectItem value="acknowledged">{t("alarms.ack")}</SelectItem>
            <SelectItem value="resolved">{t("alarms.resolvedStatus")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Events table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          ) : items.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">{t("alarms.noAlarms")}</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20"></TableHead>
                  <TableHead>{t("alarms.message")}</TableHead>
                  <TableHead>{t("alarms.site")}</TableHead>
                  <TableHead>{t("alarms.when")}</TableHead>
                  <TableHead>{t("common.status")}</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map(ev => {
                  const cfg = SEV_CFG[ev.severity] || SEV_CFG.info;
                  const Icon = cfg.icon;
                  return (
                    <TableRow key={ev.id} data-testid={`alarm-row-${ev.id}`}>
                      <TableCell>
                        <Badge variant="outline" className={`text-xs ${cfg.color}`}>
                          <Icon className="w-3 h-3 mr-1" />{cfg.label}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm">{ev.message}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{ev.site_name || "-"}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{new Date(ev.triggered_at).toLocaleString("bg-BG")}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px]">{ev.status}</Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          {ev.status === "active" && (
                            <Button size="sm" variant="ghost" onClick={() => handleAcknowledge(ev.id)} data-testid={`ack-${ev.id}`}>
                              <Eye className="w-3.5 h-3.5" />
                            </Button>
                          )}
                          {ev.status !== "resolved" && (
                            <Button size="sm" variant="ghost" onClick={() => handleResolve(ev.id)} data-testid={`resolve-${ev.id}`}>
                              <Check className="w-3.5 h-3.5" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
