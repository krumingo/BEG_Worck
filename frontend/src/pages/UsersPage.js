import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Plus, Pencil, Trash2, Loader2, UserCircle, MoreHorizontal, KeyRound } from "lucide-react";
import AdminResetPasswordModal from "@/components/AdminResetPasswordModal";

const ROLE_COLORS = {
  Admin: "bg-primary/20 text-primary border-primary/30",
  Owner: "bg-violet-500/20 text-violet-400 border-violet-500/30",
  SiteManager: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Technician: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Accountant: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
  Warehousekeeper: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  Driver: "bg-rose-500/20 text-rose-400 border-rose-500/30",
  Viewer: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

export default function UsersPage() {
  const { t } = useTranslation();
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ email: "", password: "", first_name: "", last_name: "", role: "Viewer", phone: "" });
  const [resetPasswordUser, setResetPasswordUser] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);

  const fetchUsers = useCallback(async () => {
    try {
      const [usersRes, rolesRes, meRes] = await Promise.all([
        API.get("/users"), 
        API.get("/roles"),
        API.get("/auth/me")
      ]);
      setUsers(usersRes.data);
      setRoles(rolesRes.data);
      setCurrentUser(meRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const isAdmin = currentUser?.role === "Admin" || currentUser?.role === "Owner";

  const openCreate = () => {
    setEditing(null);
    setForm({ email: "", password: "", first_name: "", last_name: "", role: "Viewer", phone: "" });
    setDialogOpen(true);
  };

  const openEdit = (u) => {
    setEditing(u);
    setForm({ email: u.email, password: "", first_name: u.first_name, last_name: u.last_name, role: u.role, phone: u.phone || "" });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (editing) {
        await API.put(`/users/${editing.id}`, {
          first_name: form.first_name,
          last_name: form.last_name,
          role: form.role,
          phone: form.phone,
        });
      } else {
        await API.post("/users", form);
      }
      setDialogOpen(false);
      await fetchUsers();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to save user");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (u) => {
    if (!window.confirm(`Delete ${u.first_name} ${u.last_name}?`)) return;
    try {
      await API.delete(`/users/${u.id}`);
      await fetchUsers();
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to delete user");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1200px]" data-testid="users-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("users.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{users.length} {t("users.usersInOrg")}</p>
        </div>
        <Button onClick={openCreate} data-testid="add-user-button">
          <Plus className="w-4 h-4 mr-2" /> {t("users.newUser")}
        </Button>
      </div>

      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="users-table">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.user")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("users.email")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.role")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.status")}</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.id} className="table-row-hover" data-testid={`user-row-${u.id}`}>
                <TableCell>
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center">
                      <UserCircle className="w-4 h-4 text-muted-foreground" />
                    </div>
                    <span className="font-medium text-foreground">{u.first_name} {u.last_name}</span>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">{u.email}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={`text-xs ${ROLE_COLORS[u.role] || ""}`}>{t(`users.roles.${u.role.toLowerCase()}`, u.role)}</Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={u.is_active ? "default" : "destructive"} className="text-xs">
                    {u.is_active ? t("common.active") : t("users.disabled")}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="sm" data-testid={`user-actions-${u.id}`}>
                        <MoreHorizontal className="w-4 h-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-48">
                      <DropdownMenuItem onClick={() => openEdit(u)} data-testid={`edit-user-${u.id}`}>
                        <Pencil className="w-3.5 h-3.5 mr-2" />
                        {t("common.edit")}
                      </DropdownMenuItem>
                      {isAdmin && u.id !== currentUser?.id && (
                        <DropdownMenuItem onClick={() => setResetPasswordUser(u)} data-testid={`reset-password-${u.id}`}>
                          <KeyRound className="w-3.5 h-3.5 mr-2" />
                          {t("users.resetPassword")}
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuSeparator />
                      <DropdownMenuItem 
                        onClick={() => handleDelete(u)} 
                        className="text-destructive focus:text-destructive"
                        data-testid={`delete-user-${u.id}`}
                      >
                        <Trash2 className="w-3.5 h-3.5 mr-2" />
                        {t("common.delete")}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[440px] bg-card border-border" data-testid="user-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? t("users.editUser") : t("users.createUser")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            {!editing && (
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("users.email")}</Label>
                <Input
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="user@company.com"
                  className="bg-background"
                  data-testid="user-email-input"
                />
              </div>
            )}
            {!editing && (
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("users.password")}</Label>
                <Input
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder={t("users.setPassword")}
                  className="bg-background"
                  data-testid="user-password-input"
                />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("users.firstName")}</Label>
                <Input
                  value={form.first_name}
                  onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                  className="bg-background"
                  data-testid="user-firstname-input"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground">{t("users.lastName")}</Label>
                <Input
                  value={form.last_name}
                  onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                  className="bg-background"
                  data-testid="user-lastname-input"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("common.role")}</Label>
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                <SelectTrigger className="bg-background" data-testid="user-role-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((r) => (
                    <SelectItem key={r} value={r}>{t(`users.roles.${r.toLowerCase()}`, r)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("users.phone")}</Label>
              <Input
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="+1234567890"
                className="bg-background"
                data-testid="user-phone-input"
              />
            </div>
            <Button onClick={handleSave} disabled={saving} className="w-full" data-testid="user-save-button">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              {editing ? t("users.updateUser") : t("users.createUser")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
