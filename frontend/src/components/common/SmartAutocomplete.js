/**
 * SmartAutocomplete — Progressive filtering with substring match, case/diacritic insensitive.
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { Search, X } from "lucide-react";

function normalize(s) {
  return (s || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

function highlight(text, query) {
  if (!query) return text;
  const nq = normalize(query);
  const nt = normalize(text);
  const idx = nt.indexOf(nq);
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-primary/30 text-primary rounded px-0.5">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  );
}

export default function SmartAutocomplete({
  items = [],
  searchFields = ["name"],
  displayField = "name",
  value,
  onChange,
  onSelect,
  placeholder = "Търси...",
  className = "",
  maxResults = 50,
  minChars = 1,
}) {
  const [query, setQuery] = useState(value || "");
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const ref = useRef(null);

  useEffect(() => { setQuery(value || ""); }, [value]);

  // Click outside close
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = useCallback(() => {
    if (!query || query.length < minChars) return [];
    const nq = normalize(query);
    const scored = items
      .map(item => {
        let bestScore = 0;
        for (const field of searchFields) {
          const val = normalize(item[field] || "");
          if (val === nq) bestScore = Math.max(bestScore, 3); // exact
          else if (val.startsWith(nq)) bestScore = Math.max(bestScore, 2); // prefix
          else if (val.includes(nq)) bestScore = Math.max(bestScore, 1); // contains
        }
        return { item, score: bestScore };
      })
      .filter(r => r.score > 0)
      .sort((a, b) => b.score - a.score);
    return scored.slice(0, maxResults);
  }, [query, items, searchFields, minChars, maxResults]);

  const results = open && focused ? filtered() : [];

  return (
    <div ref={ref} className={`relative ${className}`}>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
        <Input
          value={query}
          onChange={e => {
            setQuery(e.target.value);
            onChange?.(e.target.value);
            setOpen(true);
            setActiveIdx(-1);
          }}
          onFocus={() => { setFocused(true); setOpen(true); }}
          onBlur={() => setTimeout(() => setFocused(false), 200)}
          onKeyDown={e => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, results.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)); }
            else if (e.key === "Enter" && activeIdx >= 0 && results[activeIdx]) {
              e.preventDefault();
              const item = results[activeIdx].item;
              setQuery(item[displayField] || "");
              onChange?.(item[displayField] || "");
              onSelect?.(item);
              setOpen(false);
              setActiveIdx(-1);
            }
            else if (e.key === "Escape") { setOpen(false); setActiveIdx(-1); }
          }}
          placeholder={placeholder}
          className="pl-8 pr-8 h-9 text-sm"
        />
        {query && (
          <button onClick={() => { setQuery(""); onChange?.(""); onSelect?.(null); }} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 rounded-lg border border-border bg-card shadow-xl max-h-[240px] overflow-y-auto">
          {results.map(({ item, score }, idx) => (
            <button
              key={item.id || item[displayField]}
              onMouseDown={() => {
                setQuery(item[displayField] || "");
                onChange?.(item[displayField] || "");
                onSelect?.(item);
                setOpen(false);
                setActiveIdx(-1);
              }}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-muted/30 flex items-center gap-2 ${idx === activeIdx ? "bg-muted/40" : ""}`}
            >
              <span>{highlight(item[displayField] || "", query)}</span>
              {item.code && <span className="text-[10px] text-muted-foreground font-mono">{item.code}</span>}
            </button>
          ))}
          {results.length >= maxResults && (
            <p className="px-3 py-1.5 text-[10px] text-muted-foreground text-center">Показани {maxResults} от {items.length}</p>
          )}
        </div>
      )}
    </div>
  );
}
