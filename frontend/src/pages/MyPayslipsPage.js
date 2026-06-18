import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
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
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Receipt,
  Eye,
  Calendar,
  DollarSign,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Generated: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Finalized: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Paid: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Reversed: "bg-red-500/20 text-red-400 border-red-500/30",
  confirmed: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  paid: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  reopened: "bg-amber-500/20 text-amber-400 border-amber-500/30",
};

const STATUS_LABEL = {
  confirmed: "Confirmed",
  paid: "Paid",
  reopened: "Reopened",
};

export default function MyPayslipsPage() {
  const { user } = useAuth();
  const [payslips, setPayslips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedPayslip, setSelectedPayslip] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const fetchPayslips = useCallback(async () => {
    try {
      const res = await API.get("/payment-slips?page_size=100");
      setPayslips(res.data.items || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchPayslips(); }, [fetchPayslips]);

  const openDetail = async (payslip) => {
    try {
      const res = await API.get(`/payment-slips/${payslip.id}`);
      setSelectedPayslip(res.data);
      setDetailOpen(true);
    } catch (err) {
      console.error(err);
    }
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(amount || 0);
  };

  return (
    <div className="p-8 max-w-[1000px]" data-testid="my-payslips-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">My Payslips</h1>
          <p className="text-sm text-muted-foreground mt-1">View your pay history</p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="my-payslips-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Period</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Base</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Deductions</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Net Pay</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {payslips.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-12 text-muted-foreground">
                    <Receipt className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>No payslips yet</p>
                  </TableCell>
                </TableRow>
              ) : (
                payslips.map((ps) => (
                  <TableRow key={ps.id} className="table-row-hover" data-testid={`payslip-row-${ps.id}`}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Calendar className="w-4 h-4 text-muted-foreground" />
                        <span className="text-sm">{ps.period_start} - {ps.period_end}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">{formatCurrency(ps.earned_amount)}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-red-400">
                      {(ps.deductions_amount || 0) > 0
                        ? `-${formatCurrency(ps.deductions_amount)}`
                        : "-"}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm font-bold text-primary">{formatCurrency(ps.paid_now_amount)}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs ${STATUS_COLORS[ps.status] || ""}`}>
                        {STATUS_LABEL[ps.status] || ps.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => openDetail(ps)} data-testid={`view-btn-${ps.id}`}>
                        <Eye className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="payslip-detail-dialog">
          <DialogHeader>
            <DialogTitle>Payslip Details</DialogTitle>
          </DialogHeader>
          {selectedPayslip && (
            <div className="space-y-4 py-4">
              <div className="p-4 rounded-lg bg-muted/50">
                <div className="flex items-center gap-2 mb-2">
                  <Calendar className="w-4 h-4 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">
                    {selectedPayslip.period_start} - {selectedPayslip.period_end}
                  </span>
                </div>
                <Badge variant="outline" className={`text-xs ${STATUS_COLORS[selectedPayslip.status] || ""}`}>
                  {STATUS_LABEL[selectedPayslip.status] || selectedPayslip.status}
                </Badge>
              </div>

              <div className="space-y-3">
                <div className="flex justify-between py-2 border-b border-border">
                  <span className="text-sm text-muted-foreground">Pay Type</span>
                  <span className="text-sm font-medium">{selectedPayslip.pay_type || "-"}</span>
                </div>
                {selectedPayslip.approved_days !== undefined && (
                  <div className="flex justify-between py-2 border-b border-border">
                    <span className="text-sm text-muted-foreground">Days</span>
                    <span className="text-sm font-medium">{selectedPayslip.approved_days}</span>
                  </div>
                )}
                {selectedPayslip.approved_hours !== undefined && (
                  <div className="flex justify-between py-2 border-b border-border">
                    <span className="text-sm text-muted-foreground">Hours Worked</span>
                    <span className="text-sm font-medium">{selectedPayslip.approved_hours}h{selectedPayslip.overtime_hours > 0 ? ` (incl. ${selectedPayslip.overtime_hours}h OT)` : ""}</span>
                  </div>
                )}
                {selectedPayslip.frozen_hourly_rate > 0 && (
                  <div className="flex justify-between py-2 border-b border-border">
                    <span className="text-sm text-muted-foreground">Hourly Rate</span>
                    <span className="text-sm font-medium">{formatCurrency(selectedPayslip.frozen_hourly_rate)}</span>
                  </div>
                )}
                <div className="flex justify-between py-2 border-b border-border">
                  <span className="text-sm text-muted-foreground">Base Amount</span>
                  <span className="text-sm font-medium">{formatCurrency(selectedPayslip.earned_amount)}</span>
                </div>
                {selectedPayslip.bonuses_amount > 0 && (
                  <div className="flex justify-between py-2 border-b border-border">
                    <span className="text-sm text-muted-foreground">Bonuses</span>
                    <span className="text-sm font-medium text-emerald-400">+{formatCurrency(selectedPayslip.bonuses_amount)}</span>
                  </div>
                )}
                {selectedPayslip.deductions_amount > 0 && (
                  <div className="flex justify-between py-2 border-b border-border">
                    <span className="text-sm text-muted-foreground">Deductions</span>
                    <span className="text-sm font-medium text-red-400">-{formatCurrency(selectedPayslip.deductions_amount)}</span>
                  </div>
                )}
              </div>

              <div className="p-4 rounded-lg bg-primary/10 border border-primary/30">
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <DollarSign className="w-5 h-5 text-primary" />
                    <span className="font-semibold">Net Pay</span>
                  </div>
                  <span className="text-2xl font-bold text-primary">{formatCurrency(selectedPayslip.paid_now_amount)}</span>
                </div>
              </div>

              {selectedPayslip.paid_at && (
                <div className="text-center text-sm text-emerald-400">
                  Paid on {selectedPayslip.paid_at.slice(0, 10)}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
