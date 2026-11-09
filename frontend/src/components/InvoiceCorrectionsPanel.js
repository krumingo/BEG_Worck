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
  rejected: "Отхвърлено",
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
      // FG-220: the Accountant links the awaited credit explicitly
      const open = (data?.expected_credit_notes || []).filter((e) => e.status === "open");
      if (kind === "credit" && open.length > 0) {
        const ids = (window.prompt(
          "Кое очаквано известие покрива (ID, разделени със запетая):\n" +
            open.map((e) => `${e.id} — ${e.amount}`).join("\n"),
          open.map((e) => e.id).join(",")) || "").split(",").map((x) => x.trim()).filter(Boolean);
        if (ids.length === 0) return;
        body.expected_credit_note_ids = ids;
      }
      if (kind === "debit") {
        // Р51(2): basis (order / additional delivery / annex) + document
        const type = (window.prompt("Основание: order / additional_delivery / annex", "order") || "").trim();
        const ref = (window.prompt("Номер/описание на основанието:") || "").trim();
        const fileId = (window.prompt("Документ (file_id):") || "").trim();
        if (!type || !ref || !fileId) return;
        body.basis = { type, ref };
        body.file_id = fileId;
      }
    }
    if (kind === "debit" && outgoing) {
      const actId = (window.prompt("Основание — ID на одобрен акт:") || "").trim();
      if (!actId) return;
      body.basis = { type: "act", id: actId };
    }
    await post("/finance/credit-notes", body);
  };

  const approve = (note) => post(`/finance/credit-notes/${note.id}/approve`, { version: note.version });
  // Р52(2) / D7: the Owner accepts a supplier note's difference (reason + AuditEvent)
  const acceptDifference = (note) => {
    const reason = (window.prompt("Причина за приемане на разликата:") || "").trim();
    if (reason) post(`/finance/credit-notes/${note.id}/accept-difference`, { reason });
  };
  // FG-276 / FG-277 / Р63: the accepted difference's journal — open lines, reversal, proposals
  const resolveLine = (note, lineId) => {
    const target = (window.prompt("Разнеси към: project / company", "project") || "").trim();
    if (target !== "project" && target !== "company") return;
    const projectId = target === "project" ? (window.prompt("ID на обект (празно — разпределението на реда):") || "").trim() : "";
    const reason = (window.prompt("Причина:") || "").trim();
    if (!reason) return;
    const body = { target, reason };
    if (projectId) body.project_id = projectId;
    post(`/finance/credit-notes/${note.id}/difference-lines/${lineId}/resolve`, body);
  };
  const reverseDifference = (note) => {
    const reason = (window.prompt("Причина за сторно на приетата разлика:") || "").trim();
    if (reason) post(`/finance/credit-notes/${note.id}/reverse-difference`, { reason });
  };
  const decideProposal = (note, proposal, decision) => {
    const reason = (window.prompt(decision === "approve" ? "Коментар (по желание):" : "Причина:") || "").trim();
    if (decision === "reject" && !reason) return;
    post(`/finance/credit-notes/${note.id}/difference-proposals/${proposal.id}/${decision}`, reason ? { reason } : {});
  };
  const pendingProposals = (note) => {
    const acc = note.difference_accepted || {};
    const decided = new Set((acc.decisions || []).map((d) => d.proposal_id));
    return (acc.proposals || []).filter((p) => !decided.has(p.id));
  };
  const openLines = (note) => {
    const acc = note.difference_accepted || {};
    const booked = {};
    (acc.postings || []).forEach((p) => { booked[p.original_line_id] = (booked[p.original_line_id] || 0) + p.net; });
    const reversed = new Set((acc.postings || []).filter((p) => p.kind === "reversal").map((p) => p.original_line_id));
    const pending = new Set(pendingProposals(note).map((p) => p.original_line_id));
    return (acc.split || []).filter((l) => l.net > 0 && Math.abs(booked[l.original_line_id] || 0) < 0.005
      && (l.target === "undetermined" || reversed.has(l.original_line_id)) && !pending.has(l.original_line_id));
  };
  const isBooked = (note) => (note.difference_accepted?.postings || []).reduce((a, p) => a + p.net, 0) !== 0;

  const reject = (note) => {
    const reason = (window.prompt("Причина за отхвърляне / оттегляне:") || "").trim();
    if (reason) post(`/finance/credit-notes/${note.id}/reject`, { reason });
  };

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
            {n.difference_accepted?.company_cost > 0 && (
              <Badge variant="outline" className="text-xs">
                Фирмен разход (загуба от връщане): {n.difference_accepted.company_cost}
              </Badge>
            )}
            {n.direction === "incoming" && !n.applied && n.expected_link?.matched === false && !n.superseded_by && (
              <Badge variant="outline" className="text-xs text-amber-400">Разлика в кредитно известие</Badge>
            )}
            {isOwner && n.direction === "incoming" && !n.applied && n.expected_link?.matched === false && !n.superseded_by && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => acceptDifference(n)} data-testid={`accept-diff-${n.id}`}>
                Приеми разликата
              </Button>
            )}
            {canWrite && openLines(n).map((l) => (
              <Button key={l.original_line_id} size="sm" variant="outline" disabled={busy}
                      onClick={() => resolveLine(n, l.original_line_id)} data-testid={`resolve-line-${n.id}-${l.original_line_id}`}>
                Разнеси разлика ({l.net})
              </Button>
            ))}
            {isOwner && n.difference_accepted?.postings && isBooked(n) && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => reverseDifference(n)} data-testid={`reverse-diff-${n.id}`}>
                Сторнирай разликата
              </Button>
            )}
            {pendingProposals(n).map((p) => (
              <span key={p.id} className="flex items-center gap-1" data-testid={`proposal-${p.id}`}>
                <Badge variant="outline" className="text-xs text-amber-400">
                  Предложено: {p.target === "company" ? "фирмен разход" : `обект ${p.project_id || ""}`} ({p.net})
                </Badge>
                {isOwner && p.by !== user?.id && (
                  <Button size="sm" disabled={busy} onClick={() => decideProposal(n, p, "approve")} data-testid={`approve-proposal-${p.id}`}>Одобри</Button>
                )}
                {(isOwner || p.by === user?.id) && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => decideProposal(n, p, "reject")} data-testid={`reject-proposal-${p.id}`}>Отхвърли</Button>
                )}
              </span>
            ))}
            {n.status === "pending_approval" && (isOwner || n.created_by === user?.id) && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => reject(n)} data-testid={`reject-note-${n.id}`}>
                Отхвърли
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
