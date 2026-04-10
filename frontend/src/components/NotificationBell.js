import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Bell, AlertCircle, AlertTriangle, Info, ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const SEV_ICON = {
  critical: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};
const SEV_COLOR = {
  critical: "text-red-400",
  warning: "text-amber-400",
  info: "text-blue-400",
};

export default function NotificationBell() {
  const navigate = useNavigate();
  const [counts, setCounts] = useState({ critical: 0, warning: 0, info: 0, total: 0 });
  const [recent, setRecent] = useState([]);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const ref = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      const [countRes, recentRes] = await Promise.all([
        API.get("/alarms/count").catch(() => ({ data: { critical: 0, warning: 0, info: 0, total: 0 } })),
        API.get("/alarms?status=active&page_size=5").catch(() => ({ data: { items: [] } })),
      ]);
      setCounts(countRes.data);
      setRecent(recentRes.data.items || []);
    } catch {}
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setDropdownOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const badgeCount = counts.critical + counts.warning;
  const badgeColor = counts.critical > 0 ? "bg-red-500" : counts.warning > 0 ? "bg-amber-500" : "";

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost"
        size="sm"
        className="relative"
        onClick={() => setDropdownOpen(!dropdownOpen)}
        data-testid="notification-bell"
      >
        <Bell className="w-[18px] h-[18px] text-muted-foreground" />
        {badgeCount > 0 && (
          <span className={`absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full ${badgeColor} text-[10px] font-bold text-white flex items-center justify-center`} data-testid="notification-badge">
            {badgeCount > 9 ? "9+" : badgeCount}
          </span>
        )}
      </Button>

      {dropdownOpen && (
        <div className="absolute right-0 top-full mt-2 w-72 rounded-lg border border-border bg-card shadow-xl z-50" data-testid="alarm-dropdown">
          <div className="p-3 border-b border-border flex items-center justify-between">
            <span className="text-xs font-semibold">Аларми</span>
            <div className="flex gap-1">
              {counts.critical > 0 && <Badge className="bg-red-500/20 text-red-400 text-[9px]">{counts.critical}</Badge>}
              {counts.warning > 0 && <Badge className="bg-amber-500/20 text-amber-400 text-[9px]">{counts.warning}</Badge>}
            </div>
          </div>
          <div className="max-h-[250px] overflow-y-auto">
            {recent.length === 0 ? (
              <p className="p-4 text-xs text-muted-foreground text-center">Няма активни аларми</p>
            ) : (
              recent.map((a) => {
                const Icon = SEV_ICON[a.severity] || Info;
                const color = SEV_COLOR[a.severity] || "text-muted-foreground";
                return (
                  <div key={a.id} className="px-3 py-2 border-b border-border/50 hover:bg-muted/20 cursor-pointer" onClick={() => { navigate("/alarms"); setDropdownOpen(false); }}>
                    <div className="flex items-start gap-2">
                      <Icon className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${color}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs truncate">{a.message}</p>
                        <p className="text-[10px] text-muted-foreground">{a.site_name || ""}</p>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          <button onClick={() => { navigate("/alarms"); setDropdownOpen(false); }} className="w-full p-2 text-[10px] text-primary hover:underline flex items-center justify-center gap-1 border-t border-border">
            Виж всички <ArrowUpRight className="w-2.5 h-2.5" />
          </button>
        </div>
      )}
    </div>
  );
}
