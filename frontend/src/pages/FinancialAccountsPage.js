import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
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
  ArrowLeft,
  Plus,
  Wallet,
  Building2,
  Pencil,
  Trash2,
  Loader2,
} from "lucide-react";

export default function FinancialAccountsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const canManage = ["Admin", "Owner", "Accountant"].includes(user?.role);

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState(null);
  const [formData, setFormData] = useState({
    name: "",
    type: "Cash",
    currency: "EUR",
    opening_balance: 0,
    active: true,
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await API.get("/finance/accounts");
      setAccounts(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openCreateDialog = () => {
    setEditingAccount(null);
    setFormData({
      name: "",
      type: "Cash",
      currency: "EUR",
      opening_balance: 0,
      active: true,
    });
    setDialogOpen(true);
  };

  const openEditDialog = (account) => {
    setEditingAccount(account);
    setFormData({
      name: account.name,
      type: account.type,
      currency: account.currency,
      opening_balance: account.opening_balance,
      active: account.active,
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formData.name.trim()) {
      alert("Account name is required");
      return;
    }
    setSaving(true);
    try {
      if (editingAccount) {
        await API.put(`/finance/accounts/${editingAccount.id}`, formData);
      } else {
        await API.post("/finance/accounts", formData);
      }
      setDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (account) => {
    if (!window.confirm(`Delete account "${account.name}"? This cannot be undone.`)) return;
    try {
      await API.delete(`/finance/accounts/${account.id}`);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to delete");
    }
  };

  const formatCurrency = (amount, currency = "EUR") => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount || 0);
  };

  return (
    <div className="p-8 max-w-[1200px]" data-testid="financial-accounts-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/finance")} data-testid="back-btn">
            <ArrowLeft className="w-4 h-4 mr-1" /> Back
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-foreground">Financial Accounts</h1>
            <p className="text-sm text-muted-foreground mt-1">Manage cash and bank accounts</p>
          </div>
        </div>
        {canManage && (
          <Button onClick={openCreateDialog} data-testid="create-account-btn">
            <Plus className="w-4 h-4 mr-2" /> Add Account
          </Button>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="accounts-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Account</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Type</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Currency</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Opening Balance</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Current Balance</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                {canManage && <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={canManage ? 7 : 6} className="text-center py-12 text-muted-foreground">
                    <Wallet className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>No accounts found</p>
                    {canManage && (
                      <Button variant="outline" className="mt-4" onClick={openCreateDialog}>
                        Create your first account
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                accounts.map((account) => (
                  <TableRow key={account.id} className="table-row-hover" data-testid={`account-row-${account.id}`}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                          account.type === "Cash" ? "bg-amber-500/20" : "bg-blue-500/20"
                        }`}>
                          {account.type === "Cash" ? (
                            <Wallet className="w-4 h-4 text-amber-400" />
                          ) : (
                            <Building2 className="w-4 h-4 text-blue-400" />
                          )}
                        </div>
                        <span className="font-medium text-foreground">{account.name}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{account.type}</TableCell>
                    <TableCell className="font-mono text-muted-foreground">{account.currency}</TableCell>
                    <TableCell className="text-right font-mono text-muted-foreground">
                      {formatCurrency(account.opening_balance, account.currency)}
                    </TableCell>
                    <TableCell className="text-right font-mono font-medium text-foreground">
                      {formatCurrency(account.current_balance, account.currency)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={account.active 
                        ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                        : "bg-gray-500/20 text-gray-400 border-gray-500/30"
                      }>
                        {account.active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    {canManage && (
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => openEditDialog(account)} data-testid={`edit-btn-${account.id}`}>
                            <Pencil className="w-4 h-4" />
                          </Button>
                          <Button 
                            variant="ghost" 
                            size="sm" 
                            className="text-destructive hover:text-destructive"
                            onClick={() => handleDelete(account)}
                            data-testid={`delete-btn-${account.id}`}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[400px] bg-card border-border" data-testid="account-dialog">
          <DialogHeader>
            <DialogTitle>{editingAccount ? "Edit Account" : "New Account"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Account Name *</Label>
              <Input
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="e.g., Main Cash, Business Bank"
                className="bg-background"
                data-testid="account-name-input"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Type</Label>
                <Select value={formData.type} onValueChange={(v) => setFormData({ ...formData, type: v })}>
                  <SelectTrigger className="bg-background" data-testid="account-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Cash">Cash</SelectItem>
                    <SelectItem value="Bank">Bank</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Currency</Label>
                <Select value={formData.currency} onValueChange={(v) => setFormData({ ...formData, currency: v })} disabled={!!editingAccount}>
                  <SelectTrigger className="bg-background" data-testid="account-currency-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="EUR">EUR</SelectItem>
                    <SelectItem value="USD">USD</SelectItem>
                    <SelectItem value="BGN">BGN</SelectItem>
                    <SelectItem value="GBP">GBP</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>Opening Balance</Label>
              <Input
                type="number"
                step="0.01"
                value={formData.opening_balance}
                onChange={(e) => setFormData({ ...formData, opening_balance: parseFloat(e.target.value) || 0 })}
                className="bg-background"
                data-testid="opening-balance-input"
              />
            </div>
            {editingAccount && (
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="active"
                  checked={formData.active}
                  onChange={(e) => setFormData({ ...formData, active: e.target.checked })}
                  className="rounded border-border"
                />
                <Label htmlFor="active">Active</Label>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving} data-testid="save-account-btn">
              {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {editingAccount ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
