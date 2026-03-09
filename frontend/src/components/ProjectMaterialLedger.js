import { useEffect, useState, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Package, Loader2, Plus, Trash2, AlertTriangle, ArrowRight, RotateCcw, Check, Warehouse,
} from "lucide-react";

export default function ProjectMaterialLedger({ projectId }) {
  const [ledger, setLedger] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stock, setStock] = useState([]);

  // Dialogs
  const [issueOpen, setIssueOpen] = useState(false);
  const [consumeOpen, setConsumeOpen] = useState(false);
  const [returnOpen, setReturnOpen] = useState(false);
  const [opLines, setOpLines] = useState([]);
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [ledgerRes, stockRes] = await Promise.all([
        API.get(`/project-material-ledger/${projectId}`),
        API.get("/warehouse-stock"),
      ]);
      setLedger(ledgerRes.data.ledger);
      setWarnings(ledgerRes.data.warnings);
      setStock(stockRes.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Issue from warehouse
  const openIssue = () => {
    setOpLines([{ material_name: "", qty_issued: "", unit: "бр", unit_price: 0 }]);
    setIssueOpen(true);
  };
  const handleIssue = async () => {
    setSaving(true);
    try {
      await API.post("/warehouse-issue", { project_id: projectId, lines: opLines });
      setIssueOpen(false);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  // Consume on project
  const openConsume = () => {
    const lines = ledger.filter(m => m.remaining_on_project > 0).map(m => ({
      material_name: m.material_name, qty_consumed: "", unit: m.unit,
    }));
    setOpLines(lines.length > 0 ? lines : [{ material_name: "", qty_consumed: "", unit: "бр" }]);
    setConsumeOpen(true);
  };
  const handleConsume = async () => {
    setSaving(true);
    try {
      const valid = opLines.filter(l => parseFloat(l.qty_consumed) > 0);
      await API.post("/project-consumption", { project_id: projectId, lines: valid });
      setConsumeOpen(false);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  // Return to warehouse
  const openReturn = () => {
    const lines = ledger.filter(m => m.remaining_on_project > 0).map(m => ({
      material_name: m.material_name, qty_returned: "", unit: m.unit,
    }));
    setOpLines(lines.length > 0 ? lines : [{ material_name: "", qty_returned: "", unit: "бр" }]);
    setReturnOpen(true);
  };
  const handleReturn = async () => {
    setSaving(true);
    try {
      const valid = opLines.filter(l => parseFloat(l.qty_returned) > 0);
      await API.post("/warehouse-return", { project_id: projectId, lines: valid });
      setReturnOpen(false);
      fetchData();
    } catch (err) { alert(err.response?.data?.detail || "Грешка"); }
    finally { setSaving(false); }
  };

  const updateLine = (i, f, v) => { const u = [...opLines]; u[i] = { ...u[i], [f]: v }; setOpLines(u); };
  const addLine = () => setOpLines([...opLines, { material_name: "", qty_issued: "", qty_consumed: "", qty_returned: "", unit: "бр" }]);
  const removeLine = (i) => setOpLines(opLines.filter((_, idx) => idx !== i));

  if (loading) return <div className="p-4 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" /></div>;
  if (ledger.length === 0 && stock.length === 0) return null;

  return (
    <div className="space-y-4">
      {/* Material Ledger */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4" data-testid="material-ledger">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Package className="w-5 h-5 text-teal-500" />
            <h3 className="font-semibold text-white">Материална справка</h3>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={openIssue} className="text-xs border-blue-500/30 text-blue-400" data-testid="issue-btn">
              <ArrowRight className="w-3 h-3 mr-1" /> Отпусни от склад
            </Button>
            <Button size="sm" variant="outline" onClick={openConsume} className="text-xs border-amber-500/30 text-amber-400" data-testid="consume-btn">
              <Check className="w-3 h-3 mr-1" /> Отчети разход
            </Button>
            <Button size="sm" variant="outline" onClick={openReturn} className="text-xs border-violet-500/30 text-violet-400" data-testid="return-btn">
              <RotateCcw className="w-3 h-3 mr-1" /> Върни в склад
            </Button>
          </div>
        </div>

        {/* Warnings */}
        {warnings.length > 0 && (
          <div className="mb-3 space-y-1">
            {warnings.map((w, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-amber-400 p-1.5 rounded bg-amber-500/5">
                <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                <span>{w.message}</span>
              </div>
            ))}
          </div>
        )}

        {ledger.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow className="border-gray-700">
                <TableHead className="text-gray-400 text-xs">Материал</TableHead>
                <TableHead className="text-gray-400 text-xs">Ед.</TableHead>
                <TableHead className="text-gray-400 text-xs text-right">Поискано</TableHead>
                <TableHead className="text-gray-400 text-xs text-right">Купено</TableHead>
                <TableHead className="text-gray-400 text-xs text-right">Отпуснато</TableHead>
                <TableHead className="text-gray-400 text-xs text-right">Вложено</TableHead>
                <TableHead className="text-gray-400 text-xs text-right">Върнато</TableHead>
                <TableHead className="text-gray-400 text-xs text-right">Остатък</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {ledger.map((m, i) => (
                  <TableRow key={i} className="border-gray-700" data-testid={`ledger-row-${i}`}>
                    <TableCell className="text-white text-sm">{m.material_name}</TableCell>
                    <TableCell className="text-gray-400 text-sm">{m.unit}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-gray-400">{m.requested || "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-blue-400">{m.purchased || "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-cyan-400">{m.issued_to_project || "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-amber-400">{m.consumed || "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-violet-400">{m.returned || "—"}</TableCell>
                    <TableCell className={`text-right font-mono text-sm font-bold ${m.remaining_on_project > 0 ? "text-emerald-400" : "text-gray-500"}`}>
                      {m.remaining_on_project}
                      {m.remaining_on_project > 0 && <Badge variant="outline" className="ml-1 text-[8px] bg-emerald-500/10 text-emerald-400 border-emerald-500/30">!</Badge>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-gray-500 text-sm text-center py-4">Няма материали по този обект</p>
        )}
      </div>

      {/* Issue Dialog */}
      <Dialog open={issueOpen} onOpenChange={setIssueOpen}>
        <DialogContent className="sm:max-w-[600px] bg-card border-border" data-testid="issue-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Warehouse className="w-5 h-5 text-blue-500" /> Отпусни от склад</DialogTitle></DialogHeader>
          <div className="space-y-2 py-2">
            {stock.length > 0 && (
              <div className="text-xs text-muted-foreground mb-2">Налични: {stock.map(s => `${s.material_name} (${s.qty} ${s.unit})`).join(", ")}</div>
            )}
            {opLines.map((l, i) => (
              <div key={i} className="flex gap-2 items-end">
                <Input value={l.material_name} onChange={e => updateLine(i, "material_name", e.target.value)} placeholder="Материал" className="flex-1 bg-background h-8 text-sm" />
                <Input type="number" value={l.qty_issued} onChange={e => updateLine(i, "qty_issued", e.target.value)} placeholder="К-во" className="w-20 bg-background h-8 text-sm font-mono" />
                <Input value={l.unit} onChange={e => updateLine(i, "unit", e.target.value)} className="w-16 bg-background h-8 text-sm" />
                <Button variant="ghost" size="sm" onClick={() => removeLine(i)} className="h-8 w-8 p-0 text-destructive"><Trash2 className="w-3 h-3" /></Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={addLine}><Plus className="w-3 h-3 mr-1" /> Добави</Button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIssueOpen(false)}>Затвори</Button>
            <Button onClick={handleIssue} disabled={saving} className="bg-blue-600 hover:bg-blue-700" data-testid="confirm-issue-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <ArrowRight className="w-4 h-4 mr-1" />} Отпусни
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Consume Dialog */}
      <Dialog open={consumeOpen} onOpenChange={setConsumeOpen}>
        <DialogContent className="sm:max-w-[600px] bg-card border-border" data-testid="consume-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Check className="w-5 h-5 text-amber-500" /> Отчети изразходване</DialogTitle></DialogHeader>
          <div className="space-y-2 py-2">
            {opLines.map((l, i) => (
              <div key={i} className="flex gap-2 items-end">
                <Input value={l.material_name} onChange={e => updateLine(i, "material_name", e.target.value)} placeholder="Материал" className="flex-1 bg-background h-8 text-sm" />
                <Input type="number" value={l.qty_consumed} onChange={e => updateLine(i, "qty_consumed", e.target.value)} placeholder="К-во" className="w-20 bg-background h-8 text-sm font-mono" />
                <Input value={l.unit} onChange={e => updateLine(i, "unit", e.target.value)} className="w-16 bg-background h-8 text-sm" />
                <Button variant="ghost" size="sm" onClick={() => removeLine(i)} className="h-8 w-8 p-0 text-destructive"><Trash2 className="w-3 h-3" /></Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={addLine}><Plus className="w-3 h-3 mr-1" /> Добави</Button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConsumeOpen(false)}>Затвори</Button>
            <Button onClick={handleConsume} disabled={saving} className="bg-amber-600 hover:bg-amber-700" data-testid="confirm-consume-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />} Отчети
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Return Dialog */}
      <Dialog open={returnOpen} onOpenChange={setReturnOpen}>
        <DialogContent className="sm:max-w-[600px] bg-card border-border" data-testid="return-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><RotateCcw className="w-5 h-5 text-violet-500" /> Върни в склад</DialogTitle></DialogHeader>
          <div className="space-y-2 py-2">
            {opLines.map((l, i) => (
              <div key={i} className="flex gap-2 items-end">
                <Input value={l.material_name} onChange={e => updateLine(i, "material_name", e.target.value)} placeholder="Материал" className="flex-1 bg-background h-8 text-sm" />
                <Input type="number" value={l.qty_returned} onChange={e => updateLine(i, "qty_returned", e.target.value)} placeholder="К-во" className="w-20 bg-background h-8 text-sm font-mono" />
                <Input value={l.unit} onChange={e => updateLine(i, "unit", e.target.value)} className="w-16 bg-background h-8 text-sm" />
                <Button variant="ghost" size="sm" onClick={() => removeLine(i)} className="h-8 w-8 p-0 text-destructive"><Trash2 className="w-3 h-3" /></Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={addLine}><Plus className="w-3 h-3 mr-1" /> Добави</Button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReturnOpen(false)}>Затвори</Button>
            <Button onClick={handleReturn} disabled={saving} className="bg-violet-600 hover:bg-violet-700" data-testid="confirm-return-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <RotateCcw className="w-4 h-4 mr-1" />} Върни
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
