import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDateTime } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Bell,
  CalendarCheck,
  FileText,
  ArrowRight,
  CheckCircle2,
} from "lucide-react";

export default function NotificationsPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchNotifs = useCallback(async () => {
    try {
      const res = await API.get("/notifications/my?limit=50");
      setNotifications(res.data.notifications);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchNotifs(); }, [fetchNotifs]);

  const handleMarkRead = async () => {
    try {
      await API.post("/notifications/mark-read");
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch {}
  };

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[580px] mx-auto" data-testid="notifications-page">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Bell className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-bold text-foreground">Notifications</h1>
        </div>
        {unreadCount > 0 && (
          <Button variant="ghost" size="sm" onClick={handleMarkRead} data-testid="mark-all-read">
            <CheckCircle2 className="w-4 h-4 mr-1" /> Mark all read
          </Button>
        )}
      </div>

      {notifications.length === 0 ? (
        <div className="text-center py-16">
          <Bell className="w-12 h-12 text-muted-foreground/20 mx-auto mb-3" />
          <p className="text-muted-foreground">No notifications yet</p>
        </div>
      ) : (
        <div className="space-y-2" data-testid="notifications-list">
          {notifications.map((n) => {
            const isMissAtt = n.type === "MissingAttendance";
            const Icon = isMissAtt ? CalendarCheck : FileText;
            const iconColor = isMissAtt ? "text-amber-400" : "text-blue-400";
            const bgColor = isMissAtt ? "bg-amber-500/10 border-amber-500/20" : "bg-blue-500/10 border-blue-500/20";

            return (
              <div
                key={n.id}
                className={`flex items-start gap-4 p-4 rounded-xl border transition-colors ${
                  n.is_read ? "border-border bg-card" : `${bgColor}`
                }`}
                data-testid={`notification-${n.id}`}
              >
                <div className={`w-10 h-10 rounded-full ${isMissAtt ? "bg-amber-500/20" : "bg-blue-500/20"} flex items-center justify-center flex-shrink-0`}>
                  <Icon className={`w-5 h-5 ${iconColor}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-sm font-semibold text-foreground">{n.title}</p>
                    {!n.is_read && <Badge variant="default" className="text-[9px] px-1 py-0">New</Badge>}
                  </div>
                  <p className="text-sm text-muted-foreground mb-2">{n.message}</p>
                  <div className="flex items-center gap-2">
                    {isMissAtt ? (
                      <Button size="sm" variant="outline" onClick={() => navigate("/my-day")} data-testid={`cta-attendance-${n.id}`}>
                        Mark Attendance <ArrowRight className="w-3.5 h-3.5 ml-1" />
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => navigate(`/work-reports/new${n.data?.project_id ? `?projectId=${n.data.project_id}` : ""}`)} data-testid={`cta-report-${n.id}`}>
                        Fill Report <ArrowRight className="w-3.5 h-3.5 ml-1" />
                      </Button>
                    )}
                    <span className="text-[11px] text-muted-foreground">
                      {new Date(n.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
