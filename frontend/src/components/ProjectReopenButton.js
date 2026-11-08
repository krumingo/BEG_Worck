import { useState } from "react";
import { RotateCcw, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { apiErrorText } from "@/lib/idempotency";
import { REOPEN_KINDS, reopenProject } from "@/lib/projectLifecycle";

/**
 * PRJ-01 (FLOW-001 P-08, R54): a Completed project is opened again to Active — the
 * warranty work is done in THIS project, never in a new one. Owner/Admin; reason required.
 */
export default function ProjectReopenButton({ project, role, onDone }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("warranty");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  if (!project || project.status !== "Completed" || !["Owner", "Admin"].includes(role)) return null;

  const submit = async () => {
    if (!reason.trim()) { setError("Посочете причина"); return; }
    setSaving(true); setError("");
    try {
      const res = await reopenProject(project.id, kind, reason.trim());
      setOpen(false); setReason("");
      onDone && onDone(res.data);
    } catch (err) {
      setError(apiErrorText(err, "Обектът не беше отворен отново"));
    } finally { setSaving(false); }
  };

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)} data-testid="project-reopen-btn">
        <RotateCcw className="w-4 h-4 mr-1" /> Отвори отново
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Повторно отваряне на обекта</DialogTitle>
            <DialogDescription>
              Обектът става Активен; работата и разходите остават в този обект. След работата го приключете отново.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Вид</Label>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger data-testid="project-reopen-kind"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(REOPEN_KINDS).map(([k, label]) => <SelectItem key={k} value={k}>{label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Причина *</Label>
              <Textarea value={reason} onChange={e => setReason(e.target.value)} data-testid="project-reopen-reason" />
            </div>
            {error && <p className="text-xs text-red-400" data-testid="project-reopen-error">{error}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Отказ</Button>
            <Button onClick={submit} disabled={saving} data-testid="project-reopen-submit">
              {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />} Отвори отново
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
