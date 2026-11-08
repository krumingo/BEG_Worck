// INV-CN-01 (Р49): credit / debit notes of an issued invoice — minimal UI.
// The invoice itself is locked after issue; a correction is a separate note:
// the Accountant drafts it, the Owner (another person) approves it and only then
// it gets its number and changes the open amount. A supplier note is registered.
import { useCallback, useEffect, useState } from "react";
import API from "@/lib/api";
import { apiErrorText, newIdempotencyKey } from "@/lib/idempotency";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const NOTE_STATUS = {
  pending_approval: "Чака одобрение",
  approved: "Одобрено",
  registered: "Регистрирано",
};

const num = (text) => parseFloat(String(text || "").replace(",", "."));

export default function InvoiceCorrectionsPanel({ invoice, user, onChanged }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const canWrite = ["Admin", "Owner", "Accountant"].includes(user?.role);
  const isOwner = user?.role === "Owner";
  const outgoing = invoice?.direction === "Issued";
  const invoiceId = invoice?.id;

  const load = useCallback(async () => {
    if (!invoiceId) return;
    try {
      const res = await API.get(`/finance/invoices/${invoiceId}/corrections`);
      setData(res.data);
    } catch {
      setData(null);
    }
  }, [invoiceId]);

  useEffect(() => { load(); }, [load]);

  const post = async (url, body) => {
    setBusy(true);
    try {
      await API.post(url, body, { headers: { "Idempotency-Key": newIdempotencyKey() } });
      await load();
      if (onChanged) await onChanged();
    } catch (err) {
      alert(apiErrorText(err, "Грешка — промяната не е записана"));
    } finally {
      setBusy(false);
    }
  };

  const createNote = async (kind) => {
    const lines = invoice.lines || [];
    if (lines.length === 0) { alert("Фактурата няма редове"); return; }
    const pick = window.prompt(
      "Ред от фактурата (номер):\n" +
        lines.map((l, i) => `${i + 1}. ${l.description} — ${l.qty} × ${l.unit_price}`).join("\n"),
      "1");
    const line = lines[(parseInt(pick, 10) || 0) - 1];
    if (!line) return;
    const qty = num(window.prompt("Количество (празно — ще въведете сума):", ""));
    let amount = null;
    if (!(qty > 0)) {
      amount = num(window.prompt("Сума без ДДС:", ""));
      if (!(amount > 0)) return;
    }
    const reason = (window.prompt("Причина:") || "").trim();
    if (!reason) return;
    const body = {
      kind,
      original_invoice_id: invoice.id,
      lines: [qty > 0 ? { original_line_id: line.id, qty } : { original_line_id: line.id, amount }],
      reason,
    };
    if (!outgoing) {
      const number = (window.prompt("Номер на известието от доставчика:") || "").trim();
      if (!number) return;
      body.number = number;
    }
    if (kind === "debit" && outgoing) {
      const actId = (window.prompt("Основание — ID на одобрен акт:") || "").trim();
      if (!actId) return;
      body.basis = { type: "act", id: actId };
    }
    await post("/finance/credit-notes", body);
  };

  const approve = (note) => post(`/finance/credit-notes/${note.id}/approve`, { version: note.version });

  if (!invoice || invoice.status === "Draft") return null;
  return (
    <div className="rounded-lg border border-border p-4 space-y-3" data-testid="invoice-corrections-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Корекции (кредитни / дебитни известия)</h3>
        {canWrite && invoice.status !== "Cancelled" && (
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => createNote("credit")} data-testid="credit-note-btn">
              Кредитно известие
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => createNote("debit")} data-testid="debit-note-btn">
              Дебитно известие
            </Button>
          </div>
        )}
      </div>
      {data && (
        <p className="text-xs text-muted-foreground">
          Остатък: {data.remaining_amount} · Кредитно салдо: {data.credit_balance}
        </p>
      )}
      {(data?.notes || []).length === 0 && <p className="text-xs text-muted-foreground">Няма известия.</p>}
      {(data?.notes || []).map((n) => (
        <div key={n.id} className="flex flex-wrap items-center justify-between gap-2 text-sm" data-testid={`note-${n.id}`}>
          <span>
            {n.kind === "credit" ? "Кредитно" : "Дебитно"} {n.number || "(без номер)"} — {n.gross} ({n.reason})
          </span>
          <span className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">{NOTE_STATUS[n.status] || n.status}</Badge>
            {n.status === "pending_approval" && isOwner && n.created_by !== user?.id && (
              <Button size="sm" disabled={busy} onClick={() => approve(n)} data-testid={`approve-note-${n.id}`}>
                Одобри
              </Button>
            )}
          </span>
        </div>
      ))}
      {(data?.expected_credit_notes || []).filter((e) => e.status === "open").map((e) => (
        <p key={e.id} className="text-xs text-amber-400">
          Очаква кредитно известие: {e.amount}
          {e.escalate_to_owner ? " — срокът от 14 дни е изтекъл, ескалирано към Собственика" : ""}
        </p>
      ))}
    </div>
  );
}
