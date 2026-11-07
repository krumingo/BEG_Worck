import { payTypeLabel } from "../payTypes";

test("pay types are shown in Bulgarian (bot F-1)", () => {
  expect(payTypeLabel("Akord")).toBe("Акорд");
  expect(payTypeLabel("Hourly")).toBe("Часова ставка");
  expect(payTypeLabel("Daily")).toBe("Надница");
  expect(payTypeLabel("Monthly")).toBe("Месечна заплата");
  expect(payTypeLabel("")).toBe("");
  expect(payTypeLabel("Unknown")).toBe("Unknown");
});
