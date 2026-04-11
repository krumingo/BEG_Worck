import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  ChevronLeft, ChevronRight, Clock, MapPin, FileText, AlertTriangle,
} from "lucide-react";

const NORMAL_DAY = 8;
const BG_DAY_NAMES = ["Съб", "Нед", "Пон", "Вт", "Ср", "Чет", "Пет"];
const BG_DAY_FULL = ["Събота", "Неделя", "Понеделник", "Вторник", "Сряда", "Четвъртък", "Петък"];

function getPayrollWeek(refDate) {
  const d = new Date(refDate + "T12:00:00");
  const day = d.getDay(); // Sun=0 .. Sat=6
  const daysSinceSat = (day - 6 + 7) % 7;
  const sat = new Date(d);
  sat.setDate(d.getDate() - daysSinceSat);
  return sat.toISOString().slice(0, 10);
}

function formatWeekLabel(satStr) {
  const sat = new Date(satStr + "T12:00:00");
  const fri = new Date(sat);
  fri.setDate(sat.getDate() + 6);
  const fmt = (d) => `${d.getDate().toString().padStart(2, "0")}.${(d.getMonth() + 1).toString().padStart(2, "0")}`;
  return `${fmt(sat)} – ${fmt(fri)}.${fri.getFullYear()}`;
}

export default function WeeklyMatrixPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dayDetail, setDayDetail] = useState(null); // {worker, dayData}

  const [weekStart, setWeekStart] = useState(() => getPayrollWeek(new Date().toISOString().slice(0, 10)));

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await API.get(`/weekly-matrix?week_of=${weekStart}`);
      setData(res.data);
    } catch { setData(null); }
    finally { setLoading(false); }
  }, [weekStart]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const prevWeek = () => {
    const d = new Date(weekStart + "T12:00:00");
    d.setDate(d.getDate() - 7);
    setWeekStart(d.toISOString().slice(0, 10));
  };
  const nextWeek = () => {
    const d = new Date(weekStart + "T12:00:00");
    d.setDate(d.getDate() + 7);
    setWeekStart(d.toISOString().slice(0, 10));
  };
  const goToday = () => setWeekStart(getPayrollWeek(new Date().toISOString().slice(0, 10)));

  const tot = data?.totals || {};

  return (
    <div data-testid="weekly-matrix-section">
      {/* Week Picker */}
      <div className="flex items-center justify-between mb-4" data-testid="week-picker">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={prevWeek} className="h-8 w-8 p-0" data-testid="prev-week"><ChevronLeft className="w-4 h-4" /></Button>
          <div className="text-center min-w-[180px]">
            <p className="text-sm font-bold">{formatWeekLabel(data?.week_start || weekStart)}</p>
            <p className="text-[10px] text-muted-foreground">{t("weekly.satToFri")}</p>
          </div>
          <Button variant="outline" size="sm" onClick={nextWeek} className="h-8 w-8 p-0" data-testid="next-week"><ChevronRight className="w-4 h-4" /></Button>
          <Button variant="ghost" size="sm" onClick={goToday} className="text-xs ml-2" data-testid="go-today">{t("weekly.today")}</Button>
        </div>
        {data && (
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span>{t("weekly.workers")}: <strong className="text-foreground">{tot.workers_with_data}</strong>/{tot.workers}</span>
            <span>{t("weekly.totalHours")}: <strong className="text-foreground font-mono">{tot.hours}ч</strong></span>
            <span className="text-emerald-400">{t("weekly.normal")}: {tot.normal}ч</span>
            {tot.overtime > 0 && <span className="text-amber-400">{t("weekly.overtime")}: +{tot.overtime}ч</span>}
            <span className="text-primary font-mono font-bold">{tot.value?.toFixed(0)} EUR</span>
          </div>
        )}
      </div>

      {/* Matrix Table */}
      {loading ? (
        <div className="rounded-xl border border-border bg-card p-12 flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : !data ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center text-muted-foreground">{t("weekly.noData")}</div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="weekly-table">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[10px] sticky left-0 bg-card z-10 min-w-[160px]">{t("weekly.worker")}</TableHead>
                  {data.dates.map((d, i) => {
                    const dt = new Date(d + "T12:00:00");
                    const isWeekend = i < 2;
                    return (
                      <TableHead key={d} className={`text-[10px] text-center min-w-[64px] ${isWeekend ? "bg-muted/30" : ""}`}>
                        <div>{BG_DAY_NAMES[i]}</div>
                        <div className="text-[9px] text-muted-foreground font-normal">{dt.getDate().toString().padStart(2, "0")}.{(dt.getMonth() + 1).toString().padStart(2, "0")}</div>
                      </TableHead>
                    );
                  })}
                  <TableHead className="text-[10px] text-center bg-muted/20 min-w-[50px]">{t("weekly.totalH")}</TableHead>
                  <TableHead className="text-[10px] text-center bg-muted/20 min-w-[40px]">{t("weekly.days")}</TableHead>
                  <TableHead className="text-[10px] text-center bg-muted/20 min-w-[50px]">{t("weekly.rate")}</TableHead>
                  <TableHead className="text-[10px] text-center bg-muted/20 min-w-[65px]">{t("weekly.laborVal")}</TableHead>
                  <TableHead className="text-[10px] text-center bg-muted/20 min-w-[50px]">{t("weekly.bonuses")}</TableHead>
                  <TableHead className="text-[10px] text-center bg-muted/20 min-w-[55px]">{t("weekly.deductions")}</TableHead>
                  <TableHead className="text-[10px] text-center bg-primary/10 min-w-[65px]">{t("weekly.netPay")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.rows.map(row => (
                  <TableRow key={row.worker_id} className="hover:bg-muted/10" data-testid={`matrix-row-${row.worker_id}`}>
                    {/* Worker */}
                    <TableCell className="sticky left-0 bg-card z-10">
                      <div className="flex items-center gap-2 cursor-pointer" onClick={() => navigate(`/employees/${row.worker_id}?tab=calendar`)}>
                        {row.avatar_url ? (
                          <img src={`${process.env.REACT_APP_BACKEND_URL}${row.avatar_url}`} className="w-7 h-7 rounded-full object-cover flex-shrink-0" alt="" />
                        ) : (
                          <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-bold text-primary flex-shrink-0">
                            {(row.first_name?.[0] || "")}{(row.last_name?.[0] || "")}
                          </div>
                        )}
                        <div className="min-w-0">
                          <p className="text-xs font-medium truncate max-w-[110px] hover:text-primary transition-colors">{row.first_name} {row.last_name}</p>
                          <p className="text-[9px] text-muted-foreground truncate max-w-[110px]">{row.position || row.pay_type || "—"}</p>
                        </div>
                      </div>
                    </TableCell>

                    {/* Day cells */}
                    {row.days.map((day, i) => {
                      const isWeekend = i < 2;
                      return (
                        <TableCell
                          key={day.date}
                          className={`text-center p-1 ${isWeekend ? "bg-muted/20" : ""} ${day.has_data ? "cursor-pointer hover:bg-primary/10" : ""}`}
                          onClick={() => day.has_data && setDayDetail({ worker: row, day })}
                          data-testid={`cell-${row.worker_id}-${day.date}`}
                        >
                          {day.has_data ? (
                            <div className="flex flex-col items-center gap-0.5">
                              <span className="text-xs font-mono font-bold">{day.hours}</span>
                              {day.overtime > 0 && (
                                <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-[8px] px-1 py-0 h-3.5">+{day.overtime}</Badge>
                              )}
                            </div>
                          ) : (
                            <span className="text-[10px] text-muted-foreground/30">—</span>
                          )}
                        </TableCell>
                      );
                    })}

                    {/* Summary columns */}
                    <TableCell className="text-center bg-muted/10">
                      <span className={`text-xs font-mono font-bold ${row.total_hours > 0 ? "" : "text-muted-foreground"}`}>{row.total_hours || "—"}</span>
                      {row.total_overtime > 0 && <div className="text-[8px] text-amber-400">+{row.total_overtime}</div>}
                    </TableCell>
                    <TableCell className="text-center text-xs font-mono bg-muted/10">{row.worked_days || "—"}</TableCell>
                    <TableCell className="text-center text-[10px] font-mono text-muted-foreground bg-muted/10">{row.hourly_rate > 0 ? row.hourly_rate : "—"}</TableCell>
                    <TableCell className="text-center text-xs font-mono text-primary bg-muted/10">{row.labor_value > 0 ? row.labor_value.toFixed(0) : "—"}</TableCell>
                    <TableCell className="text-center text-xs font-mono text-emerald-400 bg-muted/10">{row.bonuses > 0 ? row.bonuses : "—"}</TableCell>
                    <TableCell className="text-center text-xs font-mono text-red-400 bg-muted/10">{row.deductions > 0 ? `-${row.deductions}` : "—"}</TableCell>
                    <TableCell className="text-center text-xs font-mono font-bold text-primary bg-primary/5">{row.net_pay > 0 ? row.net_pay.toFixed(0) : "—"}</TableCell>
                  </TableRow>
                ))}

                {/* Totals Row */}
                <TableRow className="border-t-2 border-border font-bold bg-muted/10">
                  <TableCell className="sticky left-0 bg-muted/10 z-10 text-xs">{t("weekly.grandTotal")}</TableCell>
                  {data.dates.map(d => <TableCell key={d} />)}
                  <TableCell className="text-center text-xs font-mono">{tot.hours}</TableCell>
                  <TableCell className="text-center text-xs font-mono">{tot.workers_with_data}</TableCell>
                  <TableCell />
                  <TableCell className="text-center text-xs font-mono text-primary">{tot.value?.toFixed(0)}</TableCell>
                  <TableCell className="text-center text-xs font-mono text-emerald-400">—</TableCell>
                  <TableCell className="text-center text-xs font-mono text-red-400">—</TableCell>
                  <TableCell className="text-center text-xs font-mono font-bold text-primary">{tot.value?.toFixed(0)}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>

          {/* Value Disclaimer */}
          <div className="px-4 py-2 border-t border-border text-[10px] text-muted-foreground">
            {t("weekly.valueDisclaimer")}
          </div>
        </div>
      )}

      {/* Day Detail Dialog */}
      <Dialog open={!!dayDetail} onOpenChange={() => setDayDetail(null)}>
        <DialogContent className="max-w-md" data-testid="day-detail-modal">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <Clock className="w-4 h-4" />
              {dayDetail && `${dayDetail.worker.first_name} ${dayDetail.worker.last_name} — ${BG_DAY_FULL[data?.dates.indexOf(dayDetail.day.date)] || dayDetail.day.date}`}
            </DialogTitle>
          </DialogHeader>
          {dayDetail && (
            <div className="space-y-3">
              {/* Day summary */}
              <div className="grid grid-cols-3 gap-2">
                <div className="rounded-lg bg-muted/30 p-2 text-center">
                  <p className="text-lg font-bold font-mono">{dayDetail.day.hours}<span className="text-xs text-muted-foreground">ч</span></p>
                  <p className="text-[9px] text-muted-foreground">{t("weekly.totalHours")}</p>
                </div>
                <div className="rounded-lg bg-emerald-500/10 p-2 text-center">
                  <p className="text-lg font-bold font-mono text-emerald-400">{dayDetail.day.normal}<span className="text-xs text-emerald-400/60">ч</span></p>
                  <p className="text-[9px] text-emerald-400/70">{t("weekly.normal")}</p>
                </div>
                <div className={`rounded-lg p-2 text-center ${dayDetail.day.overtime > 0 ? "bg-amber-500/10" : "bg-muted/30"}`}>
                  <p className={`text-lg font-bold font-mono ${dayDetail.day.overtime > 0 ? "text-amber-400" : "text-muted-foreground"}`}>{dayDetail.day.overtime > 0 ? `+${dayDetail.day.overtime}` : "0"}<span className="text-xs">ч</span></p>
                  <p className={`text-[9px] ${dayDetail.day.overtime > 0 ? "text-amber-400/70" : "text-muted-foreground"}`}>{t("weekly.overtime")}</p>
                </div>
              </div>

              {/* Entries */}
              <div className="space-y-2">
                {dayDetail.day.entries.map((e, i) => (
                  <div key={i} className="rounded-lg border border-border p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium">{e.smr || "—"}</span>
                      <span className="text-sm font-mono font-bold">{e.hours}ч</span>
                    </div>
                    {e.project_name && (
                      <button onClick={() => { setDayDetail(null); navigate(`/projects/${e.project_id}`); }} className="text-[10px] text-primary hover:underline flex items-center gap-0.5">
                        <MapPin className="w-2.5 h-2.5" />{e.project_name}
                      </button>
                    )}
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="outline" className={`text-[8px] ${
                        e.status === "APPROVED" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" :
                        e.status === "SUBMITTED" ? "bg-blue-500/15 text-blue-400 border-blue-500/30" :
                        e.status === "REJECTED" ? "bg-red-500/15 text-red-400 border-red-500/30" :
                        "bg-gray-500/15 text-gray-400 border-gray-500/30"
                      }`}>{e.status || "DRAFT"}</Badge>
                      {e.notes && <span className="text-[9px] text-muted-foreground truncate">{e.notes}</span>}
                    </div>
                  </div>
                ))}
              </div>

              {/* Day value */}
              <div className="flex items-center justify-between pt-2 border-t border-border">
                <span className="text-xs text-muted-foreground">{t("weekly.dayValue")}</span>
                <span className="text-sm font-mono font-bold text-primary">{(dayDetail.day.hours * dayDetail.worker.hourly_rate).toFixed(2)} EUR</span>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
