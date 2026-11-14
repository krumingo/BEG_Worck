import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { toast } from "sonner";
import { Loader2, Archive, Check, X, RotateCcw, RefreshCw } from "lucide-react";
import { canDecideRetire, canRestoreMedia } from "@/lib/mediaReviewAccess";
import {
  listRetireRequests, listRetiredMedia, approveRetire, rejectRetire, restoreMedia,
} from "@/lib/mediaReview";
import { apiErrorText, createKeyHolder } from "@/lib/idempotency";

/**
 * MEDIA-SEC-01 — „Файлове за преглед“ (Owner / Admin).
 *
 *  1. „Чакащи заявки за изваждане“ — заявките за изваждане на използван файл (R83(2)).
 *     Собственикът одобрява или отказва с причина; администраторът само гледа.
 *  2. „Извадени от употреба“ — извадените файлове (FG-558). Собственикът може да върне файл
 *     с причина (R88).
 *
 * Само съществуващите API-та; кой какво може решава сървърът при всяка заявка.
 */

// Записите, които държат файл (backend/app/services/file_holders.py, HOLDERS).
const USE_LABELS = {
  missing_smr: "Липсващо СМР",
  work_report: "Отчет",
  extra_work_draft: "Допълнително СМР",
  pending_expense: "Разход",
  offer_acceptance: "Приемане на оферта",
  warehouse_movement: "Складово движение",
  payment_receipt: "Касова бележка",
  subcontractor_payment_receipt: "Бележка към подизпълнител",
  scan_doc: "Сканиран документ",
  ocr_intake: "OCR фактура",
  current_avatar: "Профилна снимка",
  pending_link: "В процес на свързване",
};

const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("bg-BG");
};

const kindsOf = (row) => {
  const kinds = row.use_kinds || [...new Set((row.uses || []).map((u) => u.kind))];
  return kinds.map((k) => USE_LABELS[k] || k);
};

function problemOf(err) {
  return err?.response?.status === 403 ? "Нямате достъп до този списък." : apiErrorText(err, "Неуспешна заявка.");
}

/** One reason form under a row: confirm needs a reason when ``required``. */
function ReasonForm({ id, label, required, busy, onConfirm, onCancel }) {
  const [reason, setReason] = useState("");
  const ok = !required || reason.trim().length > 0;
  return (
    <div className="mt-3 space-y-2" data-testid={`reason-form-${id}`}>
      <Textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder={required ? "Причина (задължителна)" : "Причина (по желание)"}
        maxLength={500}
        data-testid={`reason-input-${id}`}
      />
      <div className="flex gap-2">
        <Button size="sm" disabled={!ok || busy} onClick={() => onConfirm(reason.trim())}
          data-testid={`reason-confirm-${id}`}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : label}
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onCancel}
          data-testid={`reason-cancel-${id}`}>
          Отказ
        </Button>
      </div>
    </div>
  );
}

function useList(load) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState(null);
  const reload = useCallback(() => {
    setLoading(true);
    setProblem(null);
    return load()
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((err) => { setRows([]); setProblem(problemOf(err)); })
      .finally(() => setLoading(false));
  }, [load]);
  useEffect(() => { reload(); }, [reload]);
  return { rows, loading, problem, reload };
}

function ListState({ loading, problem, empty, testid }) {
  if (loading) {
    return <div className="py-10 flex justify-center" data-testid={`${testid}-loading`}><Loader2 className="w-6 h-6 animate-spin" /></div>;
  }
  if (problem) return <p className="py-6 text-sm text-destructive" data-testid={`${testid}-error`}>{problem}</p>;
  if (empty) return <p className="py-6 text-sm text-muted-foreground" data-testid={`${testid}-empty`}>Няма записи.</p>;
  return null;
}

export default function MediaReviewPage() {
  const { user } = useAuth();
  const mayDecide = canDecideRetire(user?.role);
  const mayRestore = canRestoreMedia(user?.role);
  const requests = useList(listRetireRequests);
  const retired = useList(listRetiredMedia);
  // which row has its reason form open: { kind: "approve"|"reject"|"restore", id }
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);
  // R29: one Idempotency-Key per submission — kept for a retry after a network error only
  const keys = useRef({});
  const keyFor = (k) => (keys.current[k] = keys.current[k] || createKeyHolder());

  const submit = async (slot, call, done) => {
    const holder = keyFor(slot);
    setBusy(true);
    try {
      await call(holder.get());
      holder.settle(null);
      toast.success(done);
      setOpen(null);
      await Promise.all([requests.reload(), retired.reload()]);
    } catch (err) {
      holder.settle(err);
      toast.error(apiErrorText(err, "Неуспешна заявка."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 max-w-5xl space-y-4" data-testid="media-review-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Archive className="w-5 h-5" />
          <h1 className="text-xl font-semibold">Файлове за преглед</h1>
        </div>
        <Button variant="outline" size="sm" onClick={() => { requests.reload(); retired.reload(); }}
          data-testid="media-review-refresh">
          <RefreshCw className="w-4 h-4 mr-1" /> Обнови
        </Button>
      </div>
      {!mayDecide && (
        <p className="text-sm text-muted-foreground" data-testid="media-review-readonly">
          Само преглед — решенията взема Собственикът.
        </p>
      )}

      <Tabs defaultValue="requests">
        <TabsList>
          <TabsTrigger value="requests" data-testid="tab-requests">
            Чакащи заявки за изваждане <Badge variant="secondary" className="ml-2">{requests.rows.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="retired" data-testid="tab-retired">
            Извадени от употреба <Badge variant="secondary" className="ml-2">{retired.rows.length}</Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="requests">
          <ListState loading={requests.loading} problem={requests.problem}
            empty={!requests.rows.length} testid="requests" />
          {!requests.loading && !requests.problem && requests.rows.map((r) => (
            <div key={r.id} className="border rounded-md p-3 mb-2" data-testid={`request-${r.id}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="space-y-1 text-sm">
                  <div><span className="text-muted-foreground">Файл:</span> {r.media_id}</div>
                  <div><span className="text-muted-foreground">Причина:</span> {r.reason || "—"}</div>
                  <div><span className="text-muted-foreground">Заявил:</span> {r.requested_by || "—"} · {fmtDate(r.requested_at)}</div>
                  <div className="flex flex-wrap gap-1">
                    <span className="text-muted-foreground">Използван в:</span>
                    {kindsOf(r).map((k) => <Badge key={k} variant="outline">{k}</Badge>)}
                  </div>
                </div>
                {mayDecide && (
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => setOpen({ kind: "approve", id: r.id })}
                      data-testid={`approve-${r.id}`}>
                      <Check className="w-4 h-4 mr-1" /> Одобри
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setOpen({ kind: "reject", id: r.id })}
                      data-testid={`reject-${r.id}`}>
                      <X className="w-4 h-4 mr-1" /> Откажи
                    </Button>
                  </div>
                )}
              </div>
              {mayDecide && open?.id === r.id && open.kind === "approve" && (
                <ReasonForm id={`approve-${r.id}`} label="Потвърди одобрението" required={false} busy={busy}
                  onCancel={() => setOpen(null)}
                  onConfirm={(reason) => submit(`approve:${r.id}`, (key) => approveRetire(r.id, reason, key),
                    "Файлът е изваден от употреба")} />
              )}
              {mayDecide && open?.id === r.id && open.kind === "reject" && (
                <ReasonForm id={`reject-${r.id}`} label="Потвърди отказа" required busy={busy}
                  onCancel={() => setOpen(null)}
                  onConfirm={(reason) => submit(`reject:${r.id}`, (key) => rejectRetire(r.id, reason, key),
                    "Заявката е отказана")} />
              )}
            </div>
          ))}
        </TabsContent>

        <TabsContent value="retired">
          <ListState loading={retired.loading} problem={retired.problem}
            empty={!retired.rows.length} testid="retired" />
          {!retired.loading && !retired.problem && retired.rows.map((m) => {
            const restorable = mayRestore && m.can_restore === true;
            return (
              <div key={m.id} className="border rounded-md p-3 mb-2" data-testid={`retired-${m.id}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="space-y-1 text-sm">
                    <div><span className="text-muted-foreground">Файл:</span> {m.filename || m.stored_filename || m.id}</div>
                    <div><span className="text-muted-foreground">Причина:</span> {m.retired_reason || "—"}</div>
                    <div><span className="text-muted-foreground">Изваден от:</span> {m.retired_by || "—"} · {fmtDate(m.retired_at)}</div>
                    {m.retired_in_use && <Badge variant="outline">Беше използван — одобрено от Собственика</Badge>}
                  </div>
                  {restorable && (
                    <Button size="sm" variant="outline" onClick={() => setOpen({ kind: "restore", id: m.id })}
                      data-testid={`restore-${m.id}`}>
                      <RotateCcw className="w-4 h-4 mr-1" /> Върни
                    </Button>
                  )}
                </div>
                {restorable && open?.id === m.id && open.kind === "restore" && (
                  <ReasonForm id={`restore-${m.id}`} label="Потвърди връщането" required busy={busy}
                    onCancel={() => setOpen(null)}
                    onConfirm={(reason) => submit(`restore:${m.id}`, (key) => restoreMedia(m.id, reason, key),
                      "Файлът е върнат")} />
                )}
              </div>
            );
          })}
        </TabsContent>
      </Tabs>
    </div>
  );
}
