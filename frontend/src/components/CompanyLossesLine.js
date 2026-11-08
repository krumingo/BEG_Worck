// Q007 / FG-271 (Р58): the company-losses line of the company result — ONE component, the
// same label, "what it includes" text and drill-down wherever a company result is shown.
// These losses are never a project's cost and never in the overhead allocation base.
import { money } from "@/lib/i18nUtils";

export default function CompanyLossesLine({ block, finalProfit, className = "" }) {
  if (!block || !(block.amount > 0)) return null;
  return (
    <details className={`text-xs ${className}`} data-testid="company-losses">
      <summary className="cursor-pointer flex flex-wrap justify-between gap-2" title={block.includes}>
        <span>{block.label}</span>
        <span className="text-red-400 font-mono">
          −{money(block.amount)}
          {finalProfit !== undefined && finalProfit !== null && <> · Краен резултат: {money(finalProfit)}</>}
        </span>
      </summary>
      <p className="text-[10px] text-muted-foreground mt-1">{block.includes}</p>
      {(block.lines || []).map((l) => (
        <div key={`${l.ref}-${l.invoice_line_id}`} className="flex justify-between gap-2 pl-2" data-testid="company-loss-line">
          <span>{l.period} · известие {l.note_number} · {l.reason}</span>
          <span className="font-mono">{money(l.value)}</span>
        </div>
      ))}
    </details>
  );
}
