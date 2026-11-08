// Q007 / FG-271 (Р58): the company-losses line of the company result — ONE component, the
// same label, "what it includes" text and drill-down wherever a company result is shown.
// The line and its amount are always VISIBLE; only the drill-down (the postings) folds.
// These losses are never a project's cost and never in the overhead allocation base.
import { money } from "@/lib/i18nUtils";

export default function CompanyLossesLine({ block, finalProfit, className = "" }) {
  if (!block || !block.amount) return null;
  return (
    <div className={`text-xs ${className}`} data-testid="company-losses">
      <div className="flex flex-wrap justify-between gap-2">
        <span data-testid="company-losses-label">{block.label}</span>
        <span className="text-red-400 font-mono" data-testid="company-losses-amount">−{money(block.amount)}</span>
      </div>
      {finalProfit !== undefined && finalProfit !== null && (
        <div className="flex flex-wrap justify-between gap-2 font-semibold" data-testid="company-final-result">
          <span>Краен фирмен резултат</span>
          <span className="font-mono">{money(finalProfit)}</span>
        </div>
      )}
      <p className="text-[10px] text-muted-foreground mt-1" data-testid="company-losses-includes">{block.includes}</p>
      <details className="mt-1">
        <summary className="cursor-pointer text-[10px] text-muted-foreground">Разбивка ({(block.lines || []).length})</summary>
        {(block.lines || []).map((l) => (
          <div key={`${l.ref}-${l.posting_id || l.invoice_line_id}`} className="flex justify-between gap-2 pl-2" data-testid="company-loss-line">
            <span>{l.period} · известие {l.note_number} · {l.reason}{l.posting === "reversal" ? " (сторно)" : ""}</span>
            <span className="font-mono">{money(l.value)}</span>
          </div>
        ))}
      </details>
    </div>
  );
}
