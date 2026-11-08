/**
 * 5C-C26 Addendum A — on the warehouse screen the technical states read in
 * Bulgarian: in_transit → „в път", quarantine → „карантина". Only the label
 * changes; the API value stays as is.
 */
export const STATE_LABELS = Object.freeze({
  free: "свободна",
  reserved: "резервирана",
  quarantine: "карантина",
  in_transit: "в път",
  unresolved: "неизяснена",
});

export function stateLabel(value) {
  return STATE_LABELS[value] || value;
}
