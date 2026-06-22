/**
 * FinanceAnalysisPage — Full financial analysis with P&L by project, expense donut, trend.
 */
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BarChart3, Loader2, TrendingUp, TrendingDown } from "lucide-react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis } from "recharts";

const COLORS = { labor: "#ef4444", materials: "#f97316", overhead: "#eab308", subcontractor: "#8b5cf6" };
const LABELS = { labor: "Труд", materials: "Материали", overhead: "Режийни", subcontractor: "Подизп." };

export default function FinanceAnalysisPage() {
  const [data, setData] = useState(null);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState("profit");
  const navigate = useNavigate();

  useEffect(() => {
    Promise.all([
      API.get("/org/pnl-attribution"),
      API.get("/org/pnl-overview"),
    ]).then(([aRes, oRes]) => {
      setData(aRes.data);
      setOverview(oRes.data);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-6 flex justify-center"><Loader2 className="w-8 h-8 animate-spin" /></div>;

  const { expense_breakdown } = data || { expense_breakdown: {} };
  const projects = overview?.projects || [];
  const totals = overview?.totals || { revenue: 0, expense: 0, profit: 0, margin_pct: 0 };
  const fmt = (n) => (n || 0).toLocaleString("bg-BG", { maximumFractionDigits: 0 });

  const sorted = [...projects].sort((a, b) => {
    if (sortBy === "profit") return (b.profit || 0) - (a.profit || 0);
    if (sortBy === "revenue") return (b.revenue || 0) - (a.revenue || 0);
    if (sortBy === "margin") return (b.margin_pct || 0) - (a.margin_pct || 0);
    return (a.name || "").localeCompare(b.name || "");
  });

  const donutData = Object.entries(expense_breakdown || {}).filter(([, v]) => v.amount > 0).map(([k, v]) => ({ name: LABELS[k] || k, value: v.amount, pct: v.pct, fill: COLORS[k] || "#888" }));

  const barData = sorted.slice(0, 10).map(p => ({
    name: (p.code || p.name || "").slice(0, 12),
    Приходи: p.revenue || 0,
    Разходи: p.expense || 0,
  }));

  return (
    <div className="p-6 space-y-6 max-w-[1400px]">
      <div className="flex items-center gap-3">
        <BarChart3 className="w-6 h-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Финансов анализ</h1>
          <p className="text-sm text-muted-foreground">P&L по обекти, разходна структура, тренд</p>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-xl border p-3"><p className="text-[10px] text-muted-foreground flex items-center gap-1">Приходи<span className="text-[8px] px-1 py-px rounded-full bg-blue-500/15 text-blue-300">без ДДС</span></p><p className="text-lg font-bold font-mono">{fmt(totals.revenue)} €</p></div>
        <div className="rounded-xl border p-3"><p className="text-[10px] text-muted-foreground flex items-center gap-1">Разходи<span className="text-[8px] px-1 py-px rounded-full bg-blue-500/15 text-blue-300">без ДДС</span></p><p className="text-lg font-bold font-mono text-red-400">{fmt(totals.expense)} €</p></div>
        <div className="rounded-xl border p-3"><p className="text-[10px] text-muted-foreground flex items-center gap-1">Печалба<span className="text-[8px] px-1 py-px rounded-full bg-blue-500/15 text-blue-300">без ДДС</span></p><p className={`text-lg font-bold font-mono ${totals.profit >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(totals.profit)} €</p></div>
        <div className="rounded-xl border p-3"><p className="text-[10px] text-muted-foreground flex items-center gap-1">Марж<span className="text-[8px] px-1 py-px rounded-full bg-blue-500/15 text-blue-300">без ДДС</span></p><p className="text-lg font-bold font-mono">{totals.margin_pct || 0}%</p></div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Projects table */}
        <div className="lg:col-span-2 rounded-xl border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center justify-between">
            <h3 className="text-sm font-semibold">P&L по обекти</h3>
            <div className="flex gap-1">
              {["profit", "revenue", "margin", "name"].map(s => (
                <button key={s} onClick={() => setSortBy(s)} className={`px-2 py-1 text-[10px] rounded ${sortBy === s ? "bg-primary/20 text-primary" : "text-muted-foreground"}`}>
                  {{ profit: "Печалба", revenue: "Приходи", margin: "Марж", name: "Име" }[s]}
                </button>
              ))}
            </div>
          </div>
          <Table>
            <TableHeader><TableRow className="text-[10px]">
              <TableHead>Обект</TableHead><TableHead className="text-right">Бюджет</TableHead>
              <TableHead className="text-right">Приходи</TableHead><TableHead className="text-right">Разходи</TableHead>
              <TableHead className="text-right">Печалба</TableHead><TableHead className="text-right">Марж</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {sorted.map(p => (
                <TableRow key={p.id} className="text-xs cursor-pointer hover:bg-muted/20" onClick={() => navigate(`/projects/${p.id}#finance`)}>
                  <TableCell className="font-medium">{p.name || p.code}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(p.budget)}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(p.revenue)}</TableCell>
                  <TableCell className="text-right font-mono text-red-400">{fmt(p.expense)}</TableCell>
                  <TableCell className={`text-right font-mono font-bold ${(p.profit || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(p.profit)}</TableCell>
                  <TableCell className="text-right font-mono">{p.margin_pct || 0}%</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        {/* Right column: donut + bar */}
        <div className="space-y-4">
          <div className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-semibold mb-2">Разходна структура</h3>
            {donutData.length > 0 ? (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={donutData} cx="50%" cy="50%" innerRadius={40} outerRadius={70} dataKey="value" stroke="none">
                      {donutData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "#1a1a2e", border: "1px solid #333", borderRadius: 8, fontSize: 11 }} formatter={(v) => [`${v.toLocaleString("bg-BG")} €`]} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            ) : <p className="text-xs text-muted-foreground text-center py-8">Няма разходи</p>}
            <div className="flex flex-wrap gap-3 mt-2">
              {donutData.map(d => <div key={d.name} className="text-xs"><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ backgroundColor: d.fill }} />{d.name}: {d.pct}%</div>)}
            </div>
          </div>

          <div className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-semibold mb-2">Приходи vs Разходи (топ 10)</h3>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barData}>
                  <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#888" }} axisLine={false} />
                  <YAxis tick={{ fontSize: 9, fill: "#666" }} axisLine={false} />
                  <Tooltip contentStyle={{ background: "#1a1a2e", border: "1px solid #333", borderRadius: 8, fontSize: 11 }} />
                  <Bar dataKey="Приходи" fill="#10b981" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="Разходи" fill="#ef4444" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
