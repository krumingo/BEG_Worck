// Сметка за гаранция от дата на покупка + месеци гаранция.
// Връща: { inWarranty: bool, until: Date|null, untilLabel: string }
export function warrantyStatus(purchaseDate, warrantyMonths) {
  if (!purchaseDate || !warrantyMonths) return { inWarranty: false, until: null, untilLabel: "" };
  const start = new Date(purchaseDate);
  if (isNaN(start.getTime())) return { inWarranty: false, until: null, untilLabel: "" };
  const until = new Date(start);
  until.setMonth(until.getMonth() + Number(warrantyMonths));
  const inWarranty = until.getTime() > Date.now();
  const untilLabel = until.toLocaleDateString("bg-BG", { month: "2-digit", year: "numeric" });
  return { inWarranty, until, untilLabel };
}
