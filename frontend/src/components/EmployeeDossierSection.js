import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft, User, Clock, MapPin, FileText, DollarSign, Calendar,
  AlertTriangle, Banknote, Loader2, Search, ChevronLeft, ChevronRight,
  Briefcase, HeartPulse, Palmtree, HelpCircle, Check,
} from "lucide-react";

const STATUS_BADGE = {
  DRAFT: { l: "Чернова", c: "bg-gray-500/15 text-gray-400 border-gray-500/30" },
  SUBMITTED: { l: "Подаден", c: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  APPROVED: { l: "Одобрен", c: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
  REJECTED: { l: "Отхвърлен", c: "bg-red-500/15 text-red-400 border-red-500/30" },
};

const PAYROLL_BADGE = {
  none: { l: "—", c: "text-muted-foreground" },
  batched: { l: "В пакет", c: "bg-violet-500/15 text-violet-400 border-violet-500/30" },
  paid: { l: "Платен", c: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
  carry_forward: { l: "Пренесен", c: "bg-orange-500/15 text-orange-400 border-orange-500/30" },
};

const CAL_ICON = {
  working: { Icon: Briefcase, color: "text-emerald-400" },
  sick: { Icon: HeartPulse, color: "text-rose-400" },
  leave: { Icon: Palmtree, color: "text-sky-400" },
  absent: { Icon: AlertTriangle, color: "text-red-400" },
};

const BG_WEEKDAYS = ["Пон", "Вт", "Ср", "Чет", "Пет", "Съб", "Нед"];

export default function EmployeeDossierSection() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [selectedWorker, setSelectedWorker] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("reports");
  const [search, setSearch] = useState("");
  const [workerList, setWorkerList] = useState([]);
  const [listLoading, setListLoading] = useState(true);

  // Load worker list
  useEffect(() => {
    API.get("/dashboard/personnel-today")
      .then(r => setWorkerList(r.data?.personnel || []))
      .catch(() => {})
      .finally(() => setListLoading(false));
  }, []);

  const loadDossier = useCallback(async (wid) => {
    setLoading(true);
    setData(null);
    try {
      const res = await API.get(`/employee-dossier/${wid}`);
      setData(res.data);
    } catch { setData(null); }
    finally { setLoading(false); }
  }, []);

  const selectWorker = (w) => {
    setSelectedWorker(w);
    setTab("reports");
    loadDossier(w.id);
  };

  const filtered = workerList.filter(w => {
    if (!search) return true;
    const q = search.toLowerCase();
    return `${w.first_name} ${w.last_name}`.toLowerCase().includes(q) || (w.position || "").toLowerCase().includes(q);
  });

  // Worker list view
  if (!selectedWorker) {
    return (
      <div data-testid="dossier-worker-list">
        <div className="flex items-center gap-3 mb-4">
          <Search className="w-4 h-4 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={t("dossier.searchWorker")} className="max-w-xs h-9" data-testid="dossier-search" />
          <span className="text-xs text-muted-foreground">{filtered.length} {t("dossier.people")}</span>
        </div>
        {listLoading ? (
          <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" /></div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2" data-testid="worker-cards">
            {filtered.map(w => (
              <button key={w.id} onClick={() => selectWorker(w)} className="flex items-center gap-3 p-3 rounded-xl border border-border bg-card hover:border-primary/40 text-left transition-colors" data-testid={`worker-card-${w.id}`}>
                {w.avatar_url ? (
                  <img src={`${process.env.REACT_APP_BACKEND_URL}${w.avatar_url}`} className="w-10 h-10 rounded-full object-cover" alt="" />
                ) : (
                  <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center text-sm font-bold text-primary">
                    {(w.first_name?.[0] || "")}{(w.last_name?.[0] || "")}
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{w.first_name} {w.last_name}</p>
                  <p className="text-[10px] text-muted-foreground">{w.position || w.role || "—"}</p>
                </div>
                <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Dossier view
  const h = data?.header || {};
  const rpts = data?.reports || {};
  const pay = data?.payroll || {};
  const advs = data?.advances || [];
  const cal = data?.calendar || [];
  const warns = data?.warnings || [];

  const TABS = [
    { id: "reports", icon: FileText, label: t("dossier.tabReports") },
    { id: "payroll", icon: DollarSign, label: t("dossier.tabPayroll") },
    { id: "calendar", icon: Calendar, label: t("dossier.tabCalendar") },
    { id: "advances", icon: Banknote, label: t("dossier.tabAdvances") },
  ];

  return (
    <div data-testid="employee-dossier">
      {/* Back + Header */}
      <div className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={() => { setSelectedWorker(null); setData(null); }} data-testid="dossier-back"><ArrowLeft className="w-4 h-4" /></Button>
        <span className="text-xs text-muted-foreground">{t("dossier.title")}</span>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : !data ? (
        <div className="text-center py-12 text-muted-foreground">{t("dossier.noData")}</div>
      ) : (
        <>
          {/* Header Card */}
          <div className="rounded-xl border border-border bg-card p-4 mb-4 flex items-center gap-4" data-testid="dossier-header">
            {h.avatar_url ? (
              <img src={`${process.env.REACT_APP_BACKEND_URL}${h.avatar_url}`} className="w-14 h-14 rounded-full object-cover" alt="" />
            ) : (
              <div className="w-14 h-14 rounded-full bg-primary/20 flex items-center justify-center text-xl font-bold text-primary">
                {(h.first_name?.[0] || "")}{(h.last_name?.[0] || "")}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-bold">{h.first_name} {h.last_name}</h2>
              <p className="text-xs text-muted-foreground">{h.position || h.role || "—"} {h.phone && `| ${h.phone}`}</p>
            </div>
            <div className="flex items-center gap-3 flex-shrink-0">
              <div className="text-right">
                <p className="text-xs text-muted-foreground">{h.pay_type || "—"}</p>
                <p className="text-sm font-mono font-bold text-primary">{h.hourly_rate > 0 ? `${h.hourly_rate} EUR/ч` : "—"}</p>
              </div>
              <Badge variant="outline" className={h.is_active ? "text-emerald-400 border-emerald-500/30" : "text-red-400 border-red-500/30"}>
                {h.is_active ? t("dossier.active") : t("dossier.inactive")}
              </Badge>
            </div>
          </div>

          {/* Warnings */}
          {warns.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-4" data-testid="dossier-warnings">
              {warns.map((w, i) => (
                <Badge key={i} variant="outline" className={`text-[10px] ${w.type === "rate" ? "text-red-400 bg-red-500/10 border-red-500/30" : "text-amber-400 bg-amber-500/10 border-amber-500/30"}`}>
                  <AlertTriangle className="w-2.5 h-2.5 mr-1" />{w.text}
                </Badge>
              ))}
            </div>
          )}

          {/* Summary row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4" data-testid="dossier-summary">
            <div className="rounded-lg bg-card border border-border p-3 text-center">
              <p className="text-xl font-bold font-mono">{rpts.total_hours}<span className="text-sm text-muted-foreground">ч</span></p>
              <p className="text-[10px] text-muted-foreground">{t("dossier.totalHours")}</p>
            </div>
            <div className="rounded-lg bg-card border border-border p-3 text-center">
              <p className="text-xl font-bold font-mono text-primary">{rpts.total_value?.toFixed(0)}<span className="text-sm text-muted-foreground"> EUR</span></p>
              <p className="text-[10px] text-muted-foreground">{t("dossier.totalValue")}</p>
            </div>
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3 text-center">
              <p className="text-xl font-bold font-mono text-emerald-400">{pay.total_paid?.toFixed(0)}<span className="text-sm text-emerald-400/60"> EUR</span></p>
              <p className="text-[10px] text-emerald-400/70">{t("dossier.totalPaid")}</p>
            </div>
            <div className="rounded-lg bg-card border border-border p-3 text-center">
              <p className="text-xl font-bold font-mono">{rpts.count}</p>
              <p className="text-[10px] text-muted-foreground">{t("dossier.reportCount")}</p>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex items-center gap-1 mb-4 border-b border-border" data-testid="dossier-tabs">
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${tab === t.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                data-testid={`dossier-tab-${t.id}`}
              >
                <t.icon className="w-3 h-3" />{t.label}
              </button>
            ))}
          </div>

          {/* Tab: Reports */}
          {tab === "reports" && (
            <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="dossier-reports">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-[10px]">{t("dossier.colDate")}</TableHead>
                      <TableHead className="text-[10px]">{t("dossier.colSite")}</TableHead>
                      <TableHead className="text-[10px]">{t("dossier.colSmr")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.colHours")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.colOT")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.colValue")}</TableHead>
                      <TableHead className="text-[10px]">{t("dossier.colStatus")}</TableHead>
                      <TableHead className="text-[10px]">{t("dossier.colPayroll")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rpts.lines?.length === 0 ? (
                      <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground text-xs">{t("dossier.noReports")}</TableCell></TableRow>
                    ) : rpts.lines?.map((r, i) => {
                      const st = STATUS_BADGE[r.status] || { l: r.status, c: "" };
                      const ps = PAYROLL_BADGE[r.payroll_status] || PAYROLL_BADGE.none;
                      return (
                        <TableRow key={`${r.id}-${i}`} className="hover:bg-muted/10">
                          <TableCell className="text-xs font-mono">{r.date}</TableCell>
                          <TableCell>{r.project_name ? <button onClick={() => navigate(`/projects/${r.project_id}`)} className="text-[10px] text-primary hover:underline flex items-center gap-0.5"><MapPin className="w-2.5 h-2.5" />{r.project_name}</button> : <span className="text-[10px] text-muted-foreground">—</span>}</TableCell>
                          <TableCell className="text-xs truncate max-w-[120px]">{r.smr || "—"}</TableCell>
                          <TableCell className="text-center text-xs font-mono font-bold">{r.hours}</TableCell>
                          <TableCell className={`text-center text-xs font-mono ${r.overtime > 0 ? "text-amber-400 font-bold" : "text-muted-foreground"}`}>{r.overtime > 0 ? `+${r.overtime}` : "—"}</TableCell>
                          <TableCell className="text-center text-xs font-mono text-primary">{r.value > 0 ? r.value.toFixed(0) : "—"}</TableCell>
                          <TableCell><Badge variant="outline" className={`text-[9px] ${st.c}`}>{st.l}</Badge></TableCell>
                          <TableCell>{ps.l !== "—" ? <Badge variant="outline" className={`text-[9px] ${ps.c}`}>{ps.l}</Badge> : <span className="text-[10px] text-muted-foreground">—</span>}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}

          {/* Tab: Payroll */}
          {tab === "payroll" && (
            <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="dossier-payroll">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-[10px]">{t("dossier.week")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.days")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.colHours")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.gross")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.bonuses")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.deductions")}</TableHead>
                      <TableHead className="text-[10px] text-center bg-primary/5">{t("dossier.net")}</TableHead>
                      <TableHead className="text-[10px]">{t("dossier.colStatus")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pay.weeks?.length === 0 ? (
                      <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground text-xs">{t("dossier.noPayroll")}</TableCell></TableRow>
                    ) : pay.weeks?.map(w => {
                      const scfg = w.status === "paid" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : w.status === "batched" ? "bg-violet-500/15 text-violet-400 border-violet-500/30" : "bg-gray-500/15 text-gray-400 border-gray-500/30";
                      const slabel = w.status === "paid" ? "Платен" : w.status === "batched" ? "В пакет" : w.status;
                      return (
                        <TableRow key={w.batch_id} className="hover:bg-muted/10">
                          <TableCell className="text-xs font-mono">{w.week_start} → {w.week_end}</TableCell>
                          <TableCell className="text-center text-xs font-mono">{w.days}</TableCell>
                          <TableCell className="text-center text-xs font-mono font-bold">{w.hours}</TableCell>
                          <TableCell className="text-center text-xs font-mono text-primary">{w.gross > 0 ? w.gross.toFixed(0) : "—"}</TableCell>
                          <TableCell className="text-center text-xs font-mono text-emerald-400">{w.bonuses > 0 ? w.bonuses.toFixed(0) : "—"}</TableCell>
                          <TableCell className="text-center text-xs font-mono text-red-400">{w.deductions > 0 ? `-${w.deductions.toFixed(0)}` : "—"}</TableCell>
                          <TableCell className="text-center text-xs font-mono font-bold text-primary bg-primary/5">{w.net > 0 ? w.net.toFixed(0) : "—"}</TableCell>
                          <TableCell><Badge variant="outline" className={`text-[9px] ${scfg}`}>{slabel}</Badge></TableCell>
                        </TableRow>
                      );
                    })}
                    {/* Totals */}
                    {pay.weeks?.length > 0 && (
                      <TableRow className="border-t-2 border-border font-bold">
                        <TableCell className="text-xs">{t("dossier.total")}</TableCell>
                        <TableCell />
                        <TableCell className="text-center text-xs font-mono">{pay.weeks.reduce((s, w) => s + w.hours, 0).toFixed(0)}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-primary">{pay.total_gross?.toFixed(0)}</TableCell>
                        <TableCell />
                        <TableCell />
                        <TableCell className="text-center text-xs font-mono font-bold text-primary">{pay.total_net?.toFixed(0)}</TableCell>
                        <TableCell><span className="text-[9px] text-emerald-400">{t("dossier.paidTotal")}: {pay.total_paid?.toFixed(0)}</span></TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}

          {/* Tab: Calendar */}
          {tab === "calendar" && (
            <div className="space-y-1" data-testid="dossier-calendar">
              {cal.map(d => {
                const cfg = CAL_ICON[d.status] || { Icon: HelpCircle, color: "text-muted-foreground" };
                const DIcon = cfg.Icon;
                const isWeekend = d.weekday >= 5;
                return (
                  <div key={d.date} className={`flex items-center gap-3 px-3 py-2 rounded-lg ${isWeekend ? "bg-muted/20" : ""} ${d.status === "working" && !d.has_report ? "border border-amber-500/30 bg-amber-500/5" : ""}`}>
                    <span className="text-xs font-mono w-[80px] flex-shrink-0">{d.date}</span>
                    <span className="text-[10px] text-muted-foreground w-[30px]">{BG_WEEKDAYS[d.weekday]}</span>
                    {d.status ? (
                      <>
                        <DIcon className={`w-3 h-3 ${cfg.color} flex-shrink-0`} />
                        <span className={`text-xs ${cfg.color}`}>{d.status === "working" ? t("dossier.calWorking") : d.status === "sick" ? t("dossier.calSick") : d.status === "leave" ? t("dossier.calLeave") : d.status}</span>
                      </>
                    ) : <span className="text-[10px] text-muted-foreground">—</span>}
                    {d.hours > 0 && <span className="text-xs font-mono font-bold ml-auto">{d.hours}ч</span>}
                    {d.overtime > 0 && <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-[8px]">+{d.overtime}</Badge>}
                    {d.has_report && <Check className="w-3 h-3 text-emerald-400 flex-shrink-0" />}
                    {d.site_name && <button onClick={() => navigate(`/projects/${d.site_id}`)} className="text-[9px] text-primary hover:underline truncate max-w-[100px]">{d.site_name}</button>}
                  </div>
                );
              })}
            </div>
          )}

          {/* Tab: Advances */}
          {tab === "advances" && (
            <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="dossier-advances">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-[10px]">{t("dossier.advType")}</TableHead>
                      <TableHead className="text-[10px]">{t("dossier.advDate")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.advAmount")}</TableHead>
                      <TableHead className="text-[10px] text-center">{t("dossier.advRemaining")}</TableHead>
                      <TableHead className="text-[10px]">{t("dossier.advStatus")}</TableHead>
                      <TableHead className="text-[10px]">{t("dossier.advNote")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {advs.length === 0 ? (
                      <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground text-xs">{t("dossier.noAdvances")}</TableCell></TableRow>
                    ) : advs.map(a => (
                      <TableRow key={a.id} className="hover:bg-muted/10">
                        <TableCell className="text-xs">{a.type === "advance" ? t("dossier.advance") : a.type === "loan" ? t("dossier.loan") : a.type}</TableCell>
                        <TableCell className="text-xs font-mono">{a.date || "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono">{a.amount?.toFixed(0)} EUR</TableCell>
                        <TableCell className={`text-center text-xs font-mono ${a.remaining > 0 ? "text-amber-400" : "text-emerald-400"}`}>{a.remaining?.toFixed(0)} EUR</TableCell>
                        <TableCell><Badge variant="outline" className={`text-[9px] ${a.status === "active" || a.status === "approved" ? "text-amber-400 bg-amber-500/15 border-amber-500/30" : "text-muted-foreground"}`}>{a.status}</Badge></TableCell>
                        <TableCell className="text-[10px] text-muted-foreground truncate max-w-[150px]">{a.note || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
