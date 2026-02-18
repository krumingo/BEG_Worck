import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import { useParams, useNavigate } from "react-router-dom";
import API from "@/services/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ArrowLeft, Calculator, Loader2, BarChart3, Users, Clock, Split, FolderKanban } from "lucide-react";

export default function OverheadSnapshotDetailPage() {
  const { t } = useTranslation();
  const { snapshotId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [allocating, setAllocating] = useState(false);
  const [allocateDialogOpen, setAllocateDialogOpen] = useState(false);
  const [allocateMethod, setAllocateMethod] = useState("PersonDays");

  const canWrite = ["Admin", "Owner", "Accountant"].includes(user?.role);

  const fetchSnapshot = useCallback(async () => {
    setLoading(true);
    try {
      const res = await API.get(`/overhead/snapshots/${snapshotId}`);
      setSnapshot(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [snapshotId]);

  useEffect(() => { fetchSnapshot(); }, [fetchSnapshot]);

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(amount || 0);
  };

  const handleAllocate = async () => {
    setAllocating(true);
    try {
      await API.post(`/overhead/snapshots/${snapshotId}/allocate`, { method: allocateMethod });
      setAllocateDialogOpen(false);
      await fetchSnapshot();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setAllocating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        {t("overhead.noSnapshots")}
      </div>
    );
  }

  const allocations = snapshot.allocations || [];
  const totalAllocated = allocations.reduce((sum, a) => sum + (a.allocated_amount || 0), 0);

  return (
    <div className="p-6 max-w-[1200px]" data-testid="overhead-snapshot-detail">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/overhead?tab=snapshots")} data-testid="back-btn">
            <ArrowLeft className="w-4 h-4 mr-1" /> {t("common.back")}
          </Button>
          <div>
            <h1 className="text-xl font-bold text-foreground">
              {t("overhead.snapshotDetail")}: {snapshot.period_start} - {snapshot.period_end}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t("overhead.computedAt")}: {new Date(snapshot.computed_at).toLocaleString()} 
              {snapshot.computed_by_name && ` • ${snapshot.computed_by_name}`}
            </p>
          </div>
        </div>
        {canWrite && (
          <Button onClick={() => setAllocateDialogOpen(true)} data-testid="allocate-btn">
            <Split className="w-4 h-4 mr-2" /> {t("overhead.allocateToProjects")}
          </Button>
        )}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <Calculator className="w-4 h-4" />
            <span className="text-xs uppercase">{t("overhead.totalOverhead")}</span>
          </div>
          <p className="text-2xl font-bold text-primary">{formatCurrency(snapshot.total_overhead)}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {t("overhead.totalCosts")}: {formatCurrency(snapshot.total_costs)} + {t("overhead.totalAmortization")}: {formatCurrency(snapshot.total_amortization)}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <Users className="w-4 h-4" />
            <span className="text-xs uppercase">{t("overhead.personDays")}</span>
          </div>
          <p className="text-2xl font-bold text-foreground">{snapshot.total_person_days}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <Clock className="w-4 h-4" />
            <span className="text-xs uppercase">{t("overhead.hours")}</span>
          </div>
          <p className="text-2xl font-bold text-foreground">{snapshot.total_hours}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <BarChart3 className="w-4 h-4" />
            <span className="text-xs uppercase">{t("overhead.ratePerPersonDay")}</span>
          </div>
          <p className="text-2xl font-bold text-emerald-400">{formatCurrency(snapshot.overhead_rate_per_person_day)}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <BarChart3 className="w-4 h-4" />
            <span className="text-xs uppercase">{t("overhead.ratePerHour")}</span>
          </div>
          <p className="text-2xl font-bold text-emerald-400">{formatCurrency(snapshot.overhead_rate_per_hour)}</p>
        </div>
      </div>

      {/* Method Badge */}
      <div className="mb-6">
        <Badge variant="outline" className="text-sm">
          {t("overhead.method")}: {t(`overhead.methods.${snapshot.method === "PersonDays" ? "personDays" : "hours"}`)}
        </Badge>
        {snapshot.notes && (
          <p className="text-sm text-muted-foreground mt-2">{snapshot.notes}</p>
        )}
      </div>

      {/* Allocations Section */}
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="allocations-table">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FolderKanban className="w-5 h-5 text-muted-foreground" />
            <h3 className="font-semibold">{t("overhead.allocations")}</h3>
          </div>
          {allocations.length > 0 && (
            <Badge variant="secondary">
              {t("common.total")}: {formatCurrency(totalAllocated)}
            </Badge>
          )}
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("offers.project")}</TableHead>
              <TableHead className="text-right">{t("overhead.basisPersonDays")}</TableHead>
              <TableHead className="text-right">{t("overhead.basisHours")}</TableHead>
              <TableHead className="text-right">{t("overhead.allocatedAmount")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {allocations.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center py-12 text-muted-foreground">
                  <Split className="w-10 h-10 mx-auto mb-3 opacity-30" />
                  <p>{t("overhead.noAllocations")}</p>
                  {canWrite && (
                    <Button variant="outline" className="mt-4" onClick={() => setAllocateDialogOpen(true)}>
                      {t("overhead.allocateToProjects")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ) : (
              allocations.map((alloc) => (
                <TableRow key={alloc.id} data-testid={`alloc-row-${alloc.id}`}>
                  <TableCell>
                    <p className="font-medium">{alloc.project_code} - {alloc.project_name}</p>
                  </TableCell>
                  <TableCell className="text-right">{alloc.basis_person_days || "-"}</TableCell>
                  <TableCell className="text-right">{alloc.basis_hours || "-"}</TableCell>
                  <TableCell className="text-right font-mono font-bold text-primary">
                    {formatCurrency(alloc.allocated_amount)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Allocate Dialog */}
      <Dialog open={allocateDialogOpen} onOpenChange={setAllocateDialogOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card" data-testid="allocate-dialog">
          <DialogHeader>
            <DialogTitle>{t("overhead.allocateToProjects")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="p-3 rounded-lg bg-muted/50">
              <p className="text-sm text-muted-foreground">{t("overhead.totalOverhead")}:</p>
              <p className="text-lg font-bold text-primary">{formatCurrency(snapshot.total_overhead)}</p>
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium">{t("overhead.method")}</p>
              <Select value={allocateMethod} onValueChange={setAllocateMethod}>
                <SelectTrigger className="bg-background" data-testid="allocate-method-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="PersonDays">{t("overhead.methods.personDays")}</SelectItem>
                  <SelectItem value="Hours">{t("overhead.methods.hours")}</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {allocateMethod === "PersonDays" 
                  ? `${t("overhead.personDays")}: ${snapshot.total_person_days}`
                  : `${t("overhead.hours")}: ${snapshot.total_hours}`
                }
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAllocateDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleAllocate} disabled={allocating} data-testid="confirm-allocate-btn">
              {allocating && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              <Split className="w-4 h-4 mr-1" /> {t("overhead.allocateToProjects")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
