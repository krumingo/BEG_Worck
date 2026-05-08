import { useState, useCallback } from "react";

export default function useBulkSelection() {
  const [selectedIds, setSelectedIds] = useState(new Set());

  const toggleId = useCallback((id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback((allIds) => {
    setSelectedIds(prev => prev.size === allIds.length ? new Set() : new Set(allIds));
  }, []);

  const clear = useCallback(() => setSelectedIds(new Set()), []);
  const isSelected = useCallback((id) => selectedIds.has(id), [selectedIds]);

  return { selectedIds, toggleId, toggleAll, clear, isSelected, count: selectedIds.size };
}
