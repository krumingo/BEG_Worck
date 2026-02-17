import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotificationBell() {
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);

  const fetchCount = useCallback(async () => {
    try {
      const res = await API.get("/notifications/my?limit=1");
      setUnread(res.data.unread_count);
    } catch {}
  }, []);

  useEffect(() => {
    fetchCount();
    const interval = setInterval(fetchCount, 60000);
    return () => clearInterval(interval);
  }, [fetchCount]);

  return (
    <Button
      variant="ghost"
      size="sm"
      className="relative"
      onClick={() => navigate("/notifications")}
      data-testid="notification-bell"
    >
      <Bell className="w-[18px] h-[18px] text-muted-foreground" />
      {unread > 0 && (
        <span className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-destructive text-[10px] font-bold text-white flex items-center justify-center" data-testid="notification-badge">
          {unread > 9 ? "9+" : unread}
        </span>
      )}
    </Button>
  );
}
