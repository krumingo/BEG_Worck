/**
 * OfferVersionsPanel - Версии на оферта (History + Restore)
 * 
 * Features:
 * - Save new versions with optional note
 * - List versions with metadata
 * - Preview version snapshot
 * - Restore version (with auto-backup)
 */
import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  History,
  Loader2,
  Save,
  Eye,
  RotateCcw,
  Clock,
  User,
  FileText,
  AlertTriangle,
  CheckCircle,
  Archive,
} from "lucide-react";
import { toast } from "sonner";

export default function OfferVersionsPanel({ offerId, onRestore }) {
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [restoring, setRestoring] = useState(false);
  
  // Save dialog
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveNote, setSaveNote] = useState("");
  
  // Preview dialog
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewVersion, setPreviewVersion] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  
  // Restore confirmation
  const [restoreConfirmOpen, setRestoreConfirmOpen] = useState(false);
  const [versionToRestore, setVersionToRestore] = useState(null);
  
  // Load versions
  const loadVersions = useCallback(async () => {
    if (!offerId) return;
    setLoading(true);
    try {
      const res = await API.get(`/offers/${offerId}/versions`);
      setVersions(res.data.items || []);
    } catch (err) {
      console.error("Failed to load versions:", err);
    } finally {
      setLoading(false);
    }
  }, [offerId]);
  
  useEffect(() => {
    loadVersions();
  }, [loadVersions]);
  
  // Save new version
  const handleSaveVersion = async () => {
    setSaving(true);
    try {
      const res = await API.post(`/offers/${offerId}/versions`, {
        note: saveNote || null,
      });
      toast.success(`Версия v${res.data.version_number} е запазена`);
      setSaveDialogOpen(false);
      setSaveNote("");
      loadVersions();
    } catch (err) {
      console.error("Failed to save version:", err);
      toast.error(err.response?.data?.detail || "Грешка при запазване");
    } finally {
      setSaving(false);
    }
  };
  
  // Preview version
  const handlePreview = async (version) => {
    setPreviewLoading(true);
    setPreviewOpen(true);
    try {
      const res = await API.get(`/offers/${offerId}/versions/${version.version_number}`);
      setPreviewVersion(res.data);
    } catch (err) {
      console.error("Failed to load version:", err);
      toast.error("Грешка при зареждане на версията");
      setPreviewOpen(false);
    } finally {
      setPreviewLoading(false);
    }
  };
  
  // Restore version
  const handleRestore = async () => {
    if (!versionToRestore) return;
    
    setRestoring(true);
    try {
      const res = await API.post(`/offers/${offerId}/versions/${versionToRestore.version_number}/restore`);
      toast.success(`Възстановена версия v${versionToRestore.version_number}. Backup запазен като v${res.data.backup_version}.`);
      setRestoreConfirmOpen(false);
      setVersionToRestore(null);
      loadVersions();
      
      // Notify parent to refresh offer data
      if (onRestore) {
        onRestore(res.data.offer);
      }
    } catch (err) {
      console.error("Failed to restore version:", err);
      toast.error(err.response?.data?.detail || "Грешка при възстановяване");
    } finally {
      setRestoring(false);
    }
  };
  
  // Format date
  const formatDate = (dateStr) => {
    if (!dateStr) return "";
    const d = new Date(dateStr);
    return d.toLocaleString("bg-BG", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };
  
  // Format currency
  const formatCurrency = (val) => {
    if (val === undefined || val === null) return "0.00";
    return val.toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  
  return (
    <>
      <Card data-testid="offer-versions-panel">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <History className="w-5 h-5 text-blue-500" />
              Версии
              {versions.length > 0 && (
                <Badge variant="secondary" className="text-xs">{versions.length}</Badge>
              )}
            </CardTitle>
            <Button 
              size="sm" 
              onClick={() => setSaveDialogOpen(true)}
              data-testid="save-version-btn"
            >
              <Save className="w-4 h-4 mr-1" />
              Запази версия
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin" />
            </div>
          ) : versions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Archive className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p>Няма запазени версии</p>
              <p className="text-sm">Запазете версия, за да можете да се върнете към нея по-късно</p>
            </div>
          ) : (
            <ScrollArea className="h-[300px]">
              <div className="space-y-2">
                {versions.map((v, idx) => (
                  <div
                    key={v.id}
                    className={`flex items-center justify-between p-3 rounded-lg border ${
                      v.is_auto_backup 
                        ? "bg-amber-500/5 border-amber-500/20" 
                        : "bg-muted/30 border-border"
                    }`}
                    data-testid={`version-item-${v.version_number}`}
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex flex-col items-center">
                        <Badge 
                          variant={idx === 0 ? "default" : "outline"}
                          className="text-xs"
                        >
                          v{v.version_number}
                        </Badge>
                        {v.is_auto_backup && (
                          <span className="text-[10px] text-amber-500 mt-0.5">backup</span>
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2 text-sm">
                          <Clock className="w-3 h-3 text-muted-foreground" />
                          <span>{formatDate(v.created_at)}</span>
                        </div>
                        {v.created_by_name && (
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <User className="w-3 h-3" />
                            <span>{v.created_by_name}</span>
                          </div>
                        )}
                        {v.note && (
                          <p className="text-xs text-muted-foreground mt-1 italic">"{v.note}"</p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handlePreview(v)}
                        className="h-8"
                      >
                        <Eye className="w-4 h-4 mr-1" />
                        Преглед
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setVersionToRestore(v);
                          setRestoreConfirmOpen(true);
                        }}
                        className="h-8"
                        disabled={idx === 0}
                      >
                        <RotateCcw className="w-4 h-4 mr-1" />
                        Възстанови
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
      
      {/* Save Version Dialog */}
      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Save className="w-5 h-5" />
              Запази версия
            </DialogTitle>
            <DialogDescription>
              Ще се създаде копие на текущото състояние на офертата.
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Бележка (optional)</Label>
              <Input
                value={saveNote}
                onChange={(e) => setSaveNote(e.target.value)}
                placeholder="напр. Преди изпращане на клиент"
                data-testid="version-note-input"
              />
            </div>
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveDialogOpen(false)}>
              Отказ
            </Button>
            <Button onClick={handleSaveVersion} disabled={saving}>
              {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Запази
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      
      {/* Preview Dialog */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Eye className="w-5 h-5" />
              Преглед на версия v{previewVersion?.version_number}
              {previewVersion?.is_auto_backup && (
                <Badge variant="outline" className="border-amber-500 text-amber-500">Backup</Badge>
              )}
            </DialogTitle>
            <DialogDescription>
              Създадена на {formatDate(previewVersion?.created_at)}
              {previewVersion?.created_by_name && ` от ${previewVersion.created_by_name}`}
              {previewVersion?.note && ` — "${previewVersion.note}"`}
            </DialogDescription>
          </DialogHeader>
          
          {previewLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 animate-spin" />
            </div>
          ) : previewVersion?.snapshot_json && (
            <div className="space-y-4">
              {/* Header info */}
              <div className="grid grid-cols-3 gap-4 p-4 bg-muted/50 rounded-lg">
                <div>
                  <p className="text-xs text-muted-foreground">Заглавие</p>
                  <p className="font-medium">{previewVersion.snapshot_json.title || "-"}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Статус</p>
                  <Badge>{previewVersion.snapshot_json.status}</Badge>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">ДДС</p>
                  <p className="font-medium">{previewVersion.snapshot_json.vat_percent || 0}%</p>
                </div>
              </div>
              
              {/* Lines */}
              <div className="border rounded-lg overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Дейност</TableHead>
                      <TableHead>Тип</TableHead>
                      <TableHead className="text-right">К-во</TableHead>
                      <TableHead className="text-right">Мат. ед.</TableHead>
                      <TableHead className="text-right">Труд ед.</TableHead>
                      <TableHead className="text-right">Общо</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewVersion.snapshot_json.lines?.length > 0 ? (
                      previewVersion.snapshot_json.lines.map((line, idx) => (
                        <TableRow key={line.id || idx}>
                          <TableCell>{line.activity_name}</TableCell>
                          <TableCell className="text-muted-foreground text-sm">
                            {line.activity_type || "Общо"}
                            {line.activity_subtype && ` / ${line.activity_subtype}`}
                          </TableCell>
                          <TableCell className="text-right">{line.qty} {line.unit}</TableCell>
                          <TableCell className="text-right">{formatCurrency(line.material_unit_cost)}</TableCell>
                          <TableCell className="text-right">{formatCurrency(line.labor_unit_cost)}</TableCell>
                          <TableCell className="text-right font-medium">{formatCurrency(line.line_total)}</TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center py-4 text-muted-foreground">
                          Няма редове
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
              
              {/* Totals */}
              <div className="flex justify-end">
                <div className="w-64 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Междинна сума:</span>
                    <span>{formatCurrency(previewVersion.snapshot_json.subtotal)} лв.</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">ДДС ({previewVersion.snapshot_json.vat_percent || 0}%):</span>
                    <span>{formatCurrency(previewVersion.snapshot_json.vat_amount)} лв.</span>
                  </div>
                  <div className="flex justify-between font-bold text-base pt-2 border-t">
                    <span>Общо:</span>
                    <span>{formatCurrency(previewVersion.snapshot_json.total)} лв.</span>
                  </div>
                </div>
              </div>
            </div>
          )}
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>
              Затвори
            </Button>
            <Button 
              onClick={() => {
                setPreviewOpen(false);
                setVersionToRestore(previewVersion);
                setRestoreConfirmOpen(true);
              }}
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              Възстанови тази версия
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      
      {/* Restore Confirmation */}
      <AlertDialog open={restoreConfirmOpen} onOpenChange={setRestoreConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-amber-500" />
              Възстановяване на версия v{versionToRestore?.version_number}
            </AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <p>
                <strong>Внимание:</strong> Това действие ще замени текущата оферта с избраната версия.
              </p>
              <p className="text-green-600 flex items-center gap-2">
                <CheckCircle className="w-4 h-4" />
                Автоматично ще се създаде резервно копие на текущото състояние.
              </p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отказ</AlertDialogCancel>
            <AlertDialogAction onClick={handleRestore} disabled={restoring}>
              {restoring && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Възстанови
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
