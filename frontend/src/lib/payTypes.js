// Pay types as people read them (bot F-1): the API keeps the codes (Akord, Hourly, …),
// the screens show Bulgarian. An unknown code is shown as it is, never hidden.
export const PAY_TYPE_LABELS = {
  Akord: "Акорд",
  Hourly: "Часова ставка",
  Daily: "Надница",
  Monthly: "Месечна заплата",
  Mixed: "Смесено",
  mixed: "Смесено",
  piecework: "Акорд",
  hourly: "Часова ставка",
  daily: "Надница",
  monthly: "Месечна заплата",
  mixed_akord: "Смесено (с акорд)",
};

export function payTypeLabel(code) {
  if (code === null || code === undefined || code === "") return "";
  return PAY_TYPE_LABELS[code] || String(code);
}
