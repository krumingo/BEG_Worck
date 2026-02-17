import { useEffect, useState, useCallback } from "react";
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
import { Plus, Pencil, Trash2, Loader2, UserCircle } from "lucide-react";

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
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ email: "", password: "", first_name: "", last_name: "", role: "Viewer", phone: "" });

  const fetchUsers = useCallback(async () => {
    try {
      const [usersRes, rolesRes] = await Promise.all([API.get("/users"), API.get("/roles")]);
      setUsers(usersRes.data);
      setRoles(rolesRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

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
          <h1 className="text-2xl font-bold text-foreground">Users & Roles</h1>
          <p className="text-sm text-muted-foreground mt-1">{users.length} users in organization</p>
        </div>
        <Button onClick={openCreate} data-testid="add-user-button">
          <Plus className="w-4 h-4 mr-2" /> Add User
        </Button>
      </div>

      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="users-table">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">User</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Email</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Role</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
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
                  <Badge variant="outline" className={`text-xs ${ROLE_COLORS[u.role] || ""}`}>{u.role}</Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={u.is_active ? "default" : "destructive"} className="text-xs">
                    {u.is_active ? "Active" : "Disabled"}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-1">
                    <Button variant="ghost" size="sm" onClick={() => openEdit(u)} data-testid={`edit-user-${u.id}`}>
                      <Pencil className="w-3.5 h-3.5" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(u)} className="hover:text-destructive" data-testid={`delete-user-${u.id}`}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </div>
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
            <DialogTitle>{editing ? "Edit User" : "Create User"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            {!editing && (
              <div className="space-y-2">
                <Label className="text-muted-foreground">Email</Label>
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
                <Label className="text-muted-foreground">Password</Label>
                <Input
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder="Set password"
                  className="bg-background"
                  data-testid="user-password-input"
                />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-muted-foreground">First Name</Label>
                <Input
                  value={form.first_name}
                  onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                  className="bg-background"
                  data-testid="user-firstname-input"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground">Last Name</Label>
                <Input
                  value={form.last_name}
                  onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                  className="bg-background"
                  data-testid="user-lastname-input"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">Role</Label>
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                <SelectTrigger className="bg-background" data-testid="user-role-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((r) => (
                    <SelectItem key={r} value={r}>{r}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">Phone</Label>
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
              {editing ? "Update User" : "Create User"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
