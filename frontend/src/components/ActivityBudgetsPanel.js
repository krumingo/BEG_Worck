/**
 * ActivityBudgetsPanel - Бюджети по тип дейност
 * 
 * Shows budget vs spent by activity type/subtype for a project.
 * Allows inline editing of budgets.
 */
import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  PiggyBank,
  Loader2,
  Plus,
  Edit2,
  Trash2,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Check,
  X,
} from "lucide-react";
import { toast } from "sonner";

const ACTIVITY_TYPES = [
  "Общо",
  "Земни",
  "Кофраж",
  "Арматура",
  "Бетон",
  "Зидария",
  "Покрив",
  "Изолации",
  "Фасада",
  "Инсталации",
  "Довършителни",
  "Други",
];

export default function ActivityBudgetsPanel({ projectId }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editDialog, setEditDialog] = useState(false);
  const [editingRow, setEditingRow] = useState(null);
  
  // Form state
  const [formType, setFormType] = useState("Общо");
  const [formSubtype, setFormSubtype] = useState("");
  const [formLaborBudget, setFormLaborBudget] = useState("");
  const [formMaterialsBudget, setFormMaterialsBudget] = useState("");
  const [formNotes, setFormNotes] = useState("");
  const [saving, setSaving] = useState(false);
  
  // Load summary
  const loadSummary = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const res = await API.get(`/projects/${projectId}/activity-budget-summary`);
      setSummary(res.data);
    } catch (err) {
      console.error("Failed to load budget summary:", err);
      toast.error("Грешка при зареждане на бюджетите");
    } finally {
      setLoading(false);
    }
  }, [projectId]);
  
  useEffect(() => {
    loadSummary();
  }, [loadSummary]);
  
  // Open edit dialog
  const openEdit = (row = null) => {
    if (row) {
      setFormType(row.type);
      setFormSubtype(row.subtype || "");
      setFormLaborBudget(row.labor_budget?.toString() || "0");
      setFormMaterialsBudget(row.materials_budget?.toString() || "0");
      setFormNotes("");
      setEditingRow(row);
    } else {
      setFormType("Общо");
      setFormSubtype("");
      setFormLaborBudget("0");
      setFormMaterialsBudget("0");
      setFormNotes("");
      setEditingRow(null);
    }
    setEditDialog(true);
  };
  
  // Save budget
  const handleSave = async () => {
    setSaving(true);
    try {
      await API.post(`/projects/${projectId}/activity-budgets`, {
        type: formType,
        subtype: formSubtype,
        labor_budget: parseFloat(formLaborBudget) || 0,
        materials_budget: parseFloat(formMaterialsBudget) || 0,
        notes: formNotes || null,
      });
      toast.success("Бюджетът е записан");
      setEditDialog(false);
      loadSummary();
    } catch (err) {
      console.error("Failed to save budget:", err);
      toast.error(err.response?.data?.detail || "Грешка при записване");
    } finally {
      setSaving(false);
    }
  };
  
  // Format currency
  const fmt = (val) => {
    if (val === undefined || val === null) return "0.00";
    return val.toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  
  // Get badge for percentage
  const getPercentBadge = (percent) => {
    if (percent >= 100) {
      return <Badge variant="destructive" className="ml-2">{percent}%</Badge>;
    } else if (percent >= 80) {
      return <Badge variant="warning" className="ml-2 bg-amber-500/20 text-amber-500 border-amber-500">{percent}%</Badge>;
    } else if (percent > 0) {
      return <Badge variant="outline" className="ml-2">{percent}%</Badge>;
    }
    return null;
  };
  
  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin" />
        </CardContent>
      </Card>
    );
  }
  
  return (
    <>
      <Card data-testid="activity-budgets-panel">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <PiggyBank className="w-5 h-5 text-amber-500" />
              Бюджети по тип дейност
            </CardTitle>
            <Button size="sm" onClick={() => openEdit()} data-testid="add-budget-btn">
              <Plus className="w-4 h-4 mr-1" />
              Добави бюджет
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {/* Summary Cards */}
          {summary?.totals && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <div className="bg-muted/50 rounded-lg p-3">
                <p className="text-xs text-muted-foreground">Бюджет Труд</p>
                <p className="font-bold text-green-500">{fmt(summary.totals.labor_budget)} лв.</p>
              </div>
              <div className="bg-muted/50 rounded-lg p-3">
                <p className="text-xs text-muted-foreground">Изхарчено Труд</p>
                <p className="font-bold text-blue-500">{fmt(summary.totals.labor_spent)} лв.</p>
                {getPercentBadge(summary.totals.percent_labor_used)}
              </div>
              <div className="bg-muted/50 rounded-lg p-3">
                <p className="text-xs text-muted-foreground">Бюджет Материали</p>
                <p className="font-bold text-green-500">{fmt(summary.totals.materials_budget)} лв.</p>
              </div>
              <div className="bg-muted/50 rounded-lg p-3">
                <p className="text-xs text-muted-foreground">Изхарчено Материали</p>
                <p className="font-bold text-blue-500">{fmt(summary.totals.materials_spent)} лв.</p>
                {getPercentBadge(summary.totals.percent_materials_used)}
              </div>
            </div>
          )}
          
          {/* Budget Table */}
          {summary?.items?.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-border">
                    <TableHead>Тип</TableHead>
                    <TableHead>Подтип</TableHead>
                    <TableHead className="text-right">Бюджет Труд</TableHead>
                    <TableHead className="text-right">Изхарчено</TableHead>
                    <TableHead className="text-right">Остатък</TableHead>
                    <TableHead className="text-right">Бюджет Материали</TableHead>
                    <TableHead className="text-right">Изхарчено</TableHead>
                    <TableHead className="text-right">Остатък</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summary.items.map((row, idx) => (
                    <TableRow key={`${row.type}-${row.subtype}-${idx}`} className="border-border">
                      <TableCell className="font-medium">{row.type}</TableCell>
                      <TableCell className="text-muted-foreground">{row.subtype || "-"}</TableCell>
                      
                      {/* Labor */}
                      <TableCell className="text-right text-green-500">{fmt(row.labor_budget)}</TableCell>
                      <TableCell className="text-right">
                        {fmt(row.labor_spent)}
                        {getPercentBadge(row.percent_labor_used)}
                      </TableCell>
                      <TableCell className={`text-right font-medium ${row.labor_remaining < 0 ? "text-red-500" : "text-muted-foreground"}`}>
                        {row.labor_remaining < 0 && <AlertTriangle className="w-3 h-3 inline mr-1" />}
                        {fmt(row.labor_remaining)}
                      </TableCell>
                      
                      {/* Materials */}
                      <TableCell className="text-right text-green-500">{fmt(row.materials_budget)}</TableCell>
                      <TableCell className="text-right">
                        {fmt(row.materials_spent)}
                        {getPercentBadge(row.percent_materials_used)}
                      </TableCell>
                      <TableCell className={`text-right font-medium ${row.materials_remaining < 0 ? "text-red-500" : "text-muted-foreground"}`}>
                        {row.materials_remaining < 0 && <AlertTriangle className="w-3 h-3 inline mr-1" />}
                        {fmt(row.materials_remaining)}
                      </TableCell>
                      
                      <TableCell>
                        <Button variant="ghost" size="sm" onClick={() => openEdit(row)}>
                          <Edit2 className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <PiggyBank className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p>Няма зададени бюджети</p>
              <p className="text-sm">Добавете бюджет по тип дейност</p>
            </div>
          )}
        </CardContent>
      </Card>
      
      {/* Edit Dialog */}
      <Dialog open={editDialog} onOpenChange={setEditDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingRow ? "Редактиране на бюджет" : "Нов бюджет"}
            </DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Тип дейност *</Label>
                <Select value={formType} onValueChange={setFormType} disabled={!!editingRow}>
                  <SelectTrigger data-testid="budget-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ACTIVITY_TYPES.map(t => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Подтип (optional)</Label>
                <Input
                  value={formSubtype}
                  onChange={(e) => setFormSubtype(e.target.value)}
                  placeholder="напр. Изкоп"
                  disabled={!!editingRow}
                  data-testid="budget-subtype-input"
                />
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Бюджет Труд (лв.)</Label>
                <Input
                  type="number"
                  value={formLaborBudget}
                  onChange={(e) => setFormLaborBudget(e.target.value)}
                  placeholder="0.00"
                  data-testid="budget-labor-input"
                />
              </div>
              <div className="space-y-2">
                <Label>Бюджет Материали (лв.)</Label>
                <Input
                  type="number"
                  value={formMaterialsBudget}
                  onChange={(e) => setFormMaterialsBudget(e.target.value)}
                  placeholder="0.00"
                  data-testid="budget-materials-input"
                />
              </div>
            </div>
            
            <div className="space-y-2">
              <Label>Бележки</Label>
              <Textarea
                value={formNotes}
                onChange={(e) => setFormNotes(e.target.value)}
                placeholder="Допълнителни бележки..."
                rows={2}
              />
            </div>
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditDialog(false)}>
              Отказ
            </Button>
            <Button onClick={handleSave} disabled={saving} data-testid="save-budget-btn">
              {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Запази
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
