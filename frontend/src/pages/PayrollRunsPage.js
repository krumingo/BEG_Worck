import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Receipt,
  Plus,
  Loader2,
  Filter,
  ArrowRight,
  Play,
  Lock,
  Trash2,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Finalized: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Paid: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
};

export default function PayrollRunsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");

  // Form state
  const [periodType, setPeriodType] = useState("Monthly");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");

  const fetchRuns = useCallback(async () => {
    try {
      const res = await API.get(`/payroll-runs${statusFilter ? `?status=${statusFilter}` : ""}`);
      setRuns(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  // Set default period dates
  useEffect(() => {
    const now = new Date();
    const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
    const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    setPeriodStart(firstDay.toISOString().slice(0, 10));
    setPeriodEnd(lastDay.toISOString().slice(0, 10));
  }, []);

  const openCreate = () => {
    setDialogOpen(true);
  };

  const handleCreate = async () => {
    if (!periodStart || !periodEnd) {
      alert("Period start and end dates are required");
      return;
    }
    setSaving(true);
    try {
      const res = await API.post("/payroll-runs", {
        period_type: periodType,
        period_start: periodStart,
        period_end: periodEnd,
      });
      setDialogOpen(false);
      navigate(`/payroll/${res.data.id}`);
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to create");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (runId) => {
    if (!confirm("Delete this payroll run?")) return;
    try {
      await API.delete(`/payroll-runs/${runId}`);
      await fetchRuns();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to delete");
    }
  };

  return (
    <div className="p-8 max-w-[1200px]" data-testid="payroll-runs-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Payroll Runs</h1>
          <p className="text-sm text-muted-foreground mt-1">Generate and manage payroll</p>
        </div>
        <Button onClick={openCreate} data-testid="create-payroll-btn">
          <Plus className="w-4 h-4 mr-2" /> New Payroll
        </Button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6" data-testid="payroll-filters">
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[150px] bg-card" data-testid="status-filter">
            <Filter className="w-4 h-4 mr-2 text-muted-foreground" />
            <SelectValue placeholder="All Statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="Draft">Draft</SelectItem>
            <SelectItem value="Finalized">Finalized</SelectItem>
            <SelectItem value="Paid">Paid</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="payroll-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Period</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Type</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-center">Payslips</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-center">Paid</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Created</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    <Receipt className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>No payroll runs found</p>
                    <Button variant="outline" className="mt-4" onClick={openCreate}>
                      Create your first payroll
                    </Button>
                  </TableCell>
                </TableRow>
              ) : (
                runs.map((run) => (
                  <TableRow key={run.id} className="table-row-hover cursor-pointer" onClick={() => navigate(`/payroll/${run.id}`)} data-testid={`payroll-row-${run.id}`}>
                    <TableCell>
                      <p className="font-medium text-foreground">{run.period_start} - {run.period_end}</p>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{run.period_type}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs ${STATUS_COLORS[run.status] || ""}`}>
                        {run.status === "Finalized" && <Lock className="w-3 h-3 mr-1" />}
                        {run.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-center text-sm">{run.payslip_count || 0}</TableCell>
                    <TableCell className="text-center text-sm">{run.paid_count || 0}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{run.created_at?.slice(0, 10)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        {run.status === "Draft" && (
                          <Button variant="ghost" size="sm" onClick={() => handleDelete(run.id)} className="text-destructive hover:text-destructive">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        )}
                        <Button variant="ghost" size="sm" onClick={() => navigate(`/payroll/${run.id}`)}>
                          <ArrowRight className="w-4 h-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="create-payroll-dialog">
          <DialogHeader>
            <DialogTitle>New Payroll Run</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Period Type</Label>
              <Select value={periodType} onValueChange={setPeriodType}>
                <SelectTrigger className="bg-background" data-testid="period-type-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Weekly">Weekly</SelectItem>
                  <SelectItem value="Monthly">Monthly</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Start Date</Label>
                <Input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} className="bg-background" data-testid="period-start-input" />
              </div>
              <div className="space-y-2">
                <Label>End Date</Label>
                <Input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} className="bg-background" data-testid="period-end-input" />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={saving} data-testid="create-run-btn">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
