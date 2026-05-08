import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  ArrowLeft, Loader2, AlertTriangle, CheckCircle2, Clock, TrendingUp,
  Plus, History, BarChart3, Shield,
} from "lucide-react";
import { formatDate } from "@/lib/i18nUtils";

function ProgressBar({ value, max = 100, color = "bg-primary", height = "h-2" }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className={`w-full ${height} rounded-full bg-muted overflow-hidden`}>
      <div className={`${height} rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function ProjectProgressPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [warnings, setWarnings] = useState(null);
  const [loading, setLoading] = useState(true);

  // Input dialog
  const [inputOpen, setInputOpen] = useState(false);
  const [inputPkg, setInputPkg] = useState(null);
  const [inputPercent, setInputPercent] = useState(0);
  const [inputNote, setInputNote] = useState("");
  const [inputDate, setInputDate] = useState(new Date().toISOString().split("T")[0]);
  const [saving, setSaving] = useState(false);

  // History dialog
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyPkg, setHistoryPkg] = useState(null);
  const [historyData, setHistoryData] = useState(null);

  // Comparison dialog
  const [compOpen, setCompOpen] = useState(false);
  const [compData, setCompData] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [sumRes, warnRes] = await Promise.all([
        API.get(`/project-progress-summary/${projectId}`),
        API.get(`/progress-warnings/${projectId}`),
      ]);
      setSummary(sumRes.data);
      setWarnings(warnRes.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Save progress
  const handleSaveProgress = async () => {
    if (!inputPkg) return;
    setSaving(true);
    try {
      await API.post("/progress-updates", {
        execution_package_id: inputPkg.id,
        progress_percent_actual: parseFloat(inputPercent) || 0,
        note: inputNote,
        date: inputDate,
      });
      setInputOpen(false);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  // Open history
  const openHistory = async (pkg) => {
    setHistoryPkg(pkg);
    setHistoryOpen(true);
    try {
      const res = await API.get(`/progress-updates/${pkg.id}/history`);
      setHistoryData(res.data);
    } catch { setHistoryData(null); }
  };

  // Open comparison
  const openComparison = async (pkg) => {
    setCompOpen(true);
    try {
      const res = await API.get(`/progress-comparison/${pkg.id}`);
      setCompData(res.data);
    } catch { setCompData(null); }
  };

  // Open input with current values
  const openInput = (pkg) => {
    setInputPkg(pkg);
    setInputPercent(pkg.progress_percent || 0);
    setInputNote("");
    setInputDate(new Date().toISOString().split("T")[0]);
    setInputOpen(true);
  };

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  const s = summary?.summary || {};
  const pkgs = summary?.packages || [];
  const bf = summary?.budget_freeze;
  const warns = warnings?.warnings || [];

  return (
    <div className="p-6 max-w-[1400px]" data-testid="project-progress-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate(`/projects/${projectId}`)}>
            <ArrowLeft className="w-4 h-4 mr-1" /> Обект
          </Button>
          <div>
            <h1 className="text-xl font-bold text-foreground flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-primary" /> Прогрес по изпълнение
            </h1>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={async () => {
          try { await API.post(`/budget-freezes/${projectId}`, {}); fetchData(); } catch (e) { alert(e.response?.data?.detail || "Грешка"); }
        }} data-testid="freeze-btn">
          <Shield className="w-4 h-4 mr-1" /> Замрази бюджет
        </Button>
      </div>

      {/* ═══ PHASE 1: Overview ═══ */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6" data-testid="progress-overview">
        <div className="rounded-xl border border-border bg-card p-4 col-span-2">
          <p className="text-[10px] text-muted-foreground uppercase">Общ прогрес (претеглен)</p>
          <p className="text-3xl font-bold text-primary font-mono mt-1">{s.weighted_progress_percent || 0}%</p>
          <ProgressBar value={s.weighted_progress_percent || 0} color="bg-primary" height="h-3" />
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-[10px] text-muted-foreground uppercase">Пакети</p>
          <p className="text-2xl font-bold text-foreground">{s.total_packages || 0}</p>
          <p className="text-xs text-muted-foreground">{s.packages_with_progress || 0} с прогрес</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-[10px] text-muted-foreground uppercase">Бюджет freeze</p>
          <p className="text-lg font-bold text-foreground">{bf ? `v${bf.version}` : "Няма"}</p>
          {bf && <p className="text-xs text-muted-foreground">{formatDate(bf.frozen_at)}</p>}
        </div>
        <div className={`rounded-xl border p-4 ${warns.length > 0 ? "border-amber-500/30 bg-amber-500/5" : "border-border bg-card"}`}>
          <p className="text-[10px] text-muted-foreground uppercase">Предупреждения</p>
          <p className={`text-2xl font-bold ${warns.length > 0 ? "text-amber-400" : "text-foreground"}`}>{warns.length}</p>
        </div>
      </div>

      {/* Warnings strip */}
      {warns.length > 0 && (
        <div className="mb-4 space-y-1" data-testid="warnings-strip">
          {warns.map((w, i) => (
            <div key={i} className={`flex items-center gap-2 p-2 rounded text-xs ${w.severity === "critical" ? "bg-red-500/10 text-red-400" : w.severity === "warning" ? "bg-amber-500/10 text-amber-400" : "bg-blue-500/10 text-blue-400"}`}>
              <AlertTriangle className="w-3 h-3 flex-shrink-0" />
              <span>{w.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* ═══ PHASE 2: Packages Table ═══ */}
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="packages-progress-table">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-[10px] uppercase text-muted-foreground">Дейност</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground w-[140px]">Прогрес</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground text-right w-[80px]">Труд ч.</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground text-right w-[70px]">Труд %</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground text-right w-[70px]">Мат %</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground w-[80px]">Обновен</TableHead>
              <TableHead className="text-[10px] uppercase text-muted-foreground w-[140px]">Действия</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pkgs.length === 0 ? (
              <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">Няма пакети</TableCell></TableRow>
            ) : pkgs.map((pkg, i) => {
              const laborPct = pkg.planned_hours > 0 ? Math.round(pkg.used_hours / pkg.planned_hours * 100) : null;
              const noProgress = !pkg.has_progress_update;
              return (
                <TableRow key={i} className={noProgress ? "bg-amber-500/5" : ""} data-testid={`pkg-progress-row-${i}`}>
                  <TableCell>
                    <p className="text-sm font-medium text-foreground">{pkg.activity_name}</p>
                    <p className="text-[10px] text-muted-foreground">{pkg.qty} {pkg.unit}</p>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <ProgressBar value={pkg.progress_percent} color={noProgress ? "bg-gray-500" : pkg.progress_percent >= 80 ? "bg-emerald-500" : "bg-primary"} />
                      <span className={`font-mono text-sm font-bold ${noProgress ? "text-gray-500" : "text-foreground"}`}>{pkg.progress_percent}%</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">{pkg.used_hours}/{pkg.planned_hours || "?"}</TableCell>
                  <TableCell className={`text-right font-mono text-sm ${laborPct && laborPct > pkg.progress_percent + 15 ? "text-red-400" : ""}`}>
                    {laborPct != null ? `${laborPct}%` : "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">—</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{pkg.last_updated ? formatDate(pkg.last_updated) : <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400">Няма</Badge>}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="outline" size="sm" className="h-7 text-[10px] px-2" onClick={() => openInput(pkg)} data-testid={`input-btn-${i}`}>
                        <Plus className="w-3 h-3 mr-0.5" /> Прогрес
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => openHistory(pkg)} data-testid={`history-btn-${i}`}>
                        <History className="w-3.5 h-3.5" />
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => openComparison(pkg)} data-testid={`compare-btn-${i}`}>
                        <TrendingUp className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* ═══ PHASE 3: Progress Input Dialog ═══ */}
      <Dialog open={inputOpen} onOpenChange={setInputOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="progress-input-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-emerald-500" /> Въвеждане на прогрес
            </DialogTitle>
          </DialogHeader>
          {inputPkg && (
            <div className="space-y-3 py-2">
              <div className="p-2 rounded bg-muted/30 border border-border text-sm">
                <p className="font-medium text-foreground">{inputPkg.activity_name}</p>
                <p className="text-xs text-muted-foreground">Текущ: {inputPkg.progress_percent}%</p>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Дата</Label>
                <Input type="date" value={inputDate} onChange={e => setInputDate(e.target.value)} className="bg-background" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Реален прогрес (%)</Label>
                <div className="flex items-center gap-3">
                  <Input type="number" min="0" max="100" step="1" value={inputPercent}
                    onChange={e => setInputPercent(e.target.value)}
                    className="bg-background font-mono text-lg w-24" data-testid="progress-percent-input" />
                  <input type="range" min="0" max="100" step="5" value={inputPercent}
                    onChange={e => setInputPercent(e.target.value)}
                    className="flex-1 accent-primary" />
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Бележка</Label>
                <Textarea value={inputNote} onChange={e => setInputNote(e.target.value)} placeholder="Какво е свършено..." className="bg-background min-h-[50px] text-sm" data-testid="progress-note-input" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setInputOpen(false)}>Отказ</Button>
            <Button onClick={handleSaveProgress} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700" data-testid="save-progress-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <CheckCircle2 className="w-4 h-4 mr-1" />}
              Запази
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ═══ PHASE 4: History Dialog ═══ */}
      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="progress-history-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <History className="w-5 h-5 text-primary" /> История: {historyPkg?.activity_name}
            </DialogTitle>
          </DialogHeader>
          {historyData ? (
            <div className="space-y-2 py-2 max-h-[400px] overflow-y-auto">
              {historyData.entries.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">Няма записи</p>
              ) : historyData.entries.map((e, i) => (
                <div key={i} className="flex items-start gap-3 p-2 rounded bg-muted/20 border border-border" data-testid={`history-entry-${i}`}>
                  <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center font-mono text-sm font-bold text-primary flex-shrink-0">
                    {e.progress_percent_actual}%
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-foreground">{formatDate(e.date)}</span>
                      {e.updated_by_name && <span className="text-[10px] text-muted-foreground">{e.updated_by_name}</span>}
                    </div>
                    {e.note && <p className="text-xs text-muted-foreground mt-0.5">{e.note}</p>}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-8 text-center"><Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" /></div>
          )}
        </DialogContent>
      </Dialog>

      {/* ═══ PHASE 5: Comparison Dialog ═══ */}
      <Dialog open={compOpen} onOpenChange={setCompOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="progress-comparison-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-primary" /> Прогрес vs Разход
            </DialogTitle>
          </DialogHeader>
          {compData ? (
            <div className="space-y-4 py-2">
              <div className="text-center">
                <p className="text-[10px] text-muted-foreground uppercase">Реален прогрес</p>
                <p className="text-4xl font-bold font-mono text-primary">{compData.progress.actual_percent}%</p>
                {!compData.progress.has_update && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 mt-1">Няма въведен прогрес</Badge>}
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg border border-border text-center">
                  <p className="text-[10px] text-muted-foreground">Труд</p>
                  <p className="font-mono text-lg font-bold">{compData.usage.labor_percent != null ? `${compData.usage.labor_percent}%` : "—"}</p>
                  {compData.gaps.labor_vs_progress != null && (
                    <p className={`text-[10px] font-mono ${compData.gaps.labor_vs_progress > 10 ? "text-red-400" : compData.gaps.labor_vs_progress < -10 ? "text-blue-400" : "text-muted-foreground"}`}>
                      {compData.gaps.labor_vs_progress > 0 ? "+" : ""}{compData.gaps.labor_vs_progress}
                    </p>
                  )}
                </div>
                <div className="p-3 rounded-lg border border-border text-center">
                  <p className="text-[10px] text-muted-foreground">Материали</p>
                  <p className="font-mono text-lg font-bold">{compData.usage.material_percent != null ? `${compData.usage.material_percent}%` : "—"}</p>
                  {compData.gaps.material_vs_progress != null && (
                    <p className={`text-[10px] font-mono ${compData.gaps.material_vs_progress > 10 ? "text-red-400" : "text-muted-foreground"}`}>
                      {compData.gaps.material_vs_progress > 0 ? "+" : ""}{compData.gaps.material_vs_progress}
                    </p>
                  )}
                </div>
                <div className="p-3 rounded-lg border border-border text-center">
                  <p className="text-[10px] text-muted-foreground">Подизп.</p>
                  <p className="font-mono text-lg font-bold">{compData.usage.subcontract_percent != null ? `${compData.usage.subcontract_percent}%` : "—"}</p>
                  {compData.gaps.subcontract_vs_progress != null && (
                    <p className={`text-[10px] font-mono ${compData.gaps.subcontract_vs_progress > 10 ? "text-red-400" : "text-muted-foreground"}`}>
                      {compData.gaps.subcontract_vs_progress > 0 ? "+" : ""}{compData.gaps.subcontract_vs_progress}
                    </p>
                  )}
                </div>
              </div>

              <div className="p-3 rounded-lg bg-muted/20 border border-border text-xs text-muted-foreground">
                <p>Планирани часове: {compData.raw.planned_hours || "?"} | Използвани: {compData.raw.used_hours}</p>
                <p>Мат. бюджет: {compData.raw.material_budget} EUR | Факт: {compData.raw.material_actual} EUR</p>
              </div>

              {compData.metrics_partial && (
                <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-400">Частични данни</Badge>
              )}
            </div>
          ) : (
            <div className="py-8 text-center"><Loader2 className="w-6 h-6 animate-spin mx-auto" /></div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
