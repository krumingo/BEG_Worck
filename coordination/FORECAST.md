# BEG_WORK management forecast v1.0 — evidence map, estimates pending

Machine source: [`FORECAST.json`](FORECAST.json). This document is a planning read-model, not a business rule, implementation gate, merge, deploy or production forecast. As of 27 September 2026, the canonical scope is mapped but **engineering-hour baselines are not calibrated or approved**. Therefore Whole BEG_WORK %, Wave 0 %, W0-03 %, W0-03D/C01 % and total/remaining hours are `NOT ESTIMATED`, not zero. No dashboard may substitute FLOW count, PR count, lifecycle stages or an equal-weight average.

## Proven visible facts

- Business design: **49/50 Business Locked; 1 legacy** (`FLOW-018` absorbed by `FLOW-039`), per `docs/flows/README.md`. This conveys no implementation credit.
- Current Wave: **Wave 0**. The current task is `W0-03D/C01`, Draft PR #30 at `7a84b1721e6d874e0e5f3a140aaf7b288cfc52cd`.
- Current task lifecycle: **4/6 stages observed** — Assignment, Claude implementation, HANDOFF and Codex review. Review outcome is `CHANGES_REQUESTED`; bounded correction is prepared but its Send is still `PENDING`, and final review has not happened. The stage count is **not an effort percentage**.
- W0-03C is merged to `main` at `4f46212486e7f2704007cece774939230e0a51f0`, but Master Data as a whole remains open and no production index build or deployment is inferred.
- `IMPLEMENTATION_WAVES.md` and `IMPLEMENTATION_GATE_MATRIX.md` contain a 20 September implementation snapshot that still calls W0-03C “in review”. For current status, use live PR metadata and the queue's exact-head ACTIVE/REVIEWS. Do not silently repeat the older snapshot as current.

## Forecast grain and inclusion

Each row in the JSON is a distinct canonical implementation deliverable. Wave 0 covers every `W0-01…W0-11` item and the named A/B/C/D/E or core/B splits present in the canonical plan. Waves 1–4 are grouped only by deliverables already named in `IMPLEMENTATION_WAVES.md`; Wave 2.1 remains a Wave 2 substage. This does not rename, add or reorder Waves. A completed row requires acceptance evidence; `PARTIAL` earns no default 50% credit. `UNVERIFIED` means the current sources do not establish canonical implementation completion, even if legacy code exists.

| Wave | Current evidence-backed position | Unclosed scope |
|---|---|---|
| W0 | W0-01, W0-02 and W0-04 cores; W0-03 A/B/C and office intake; W0-09A; W0-10A have bounded evidence | Remaining parts of W0-01/02/04/09/10; W0-03D/E; full W0-05/06/07/08/11 |
| W1 | No accepted Wave 1 implementation evidence mapped yet | Commercial lifecycle, payment/financial read model, document control and approvals |
| W2 | No accepted Wave 2 implementation evidence mapped yet | Modern Field Experience, field operations, cost/logistics/assets, quality/payroll, Wave 2.1 schedule/readiness |
| W3 | No accepted Wave 3 implementation evidence mapped yet | Governed BEG Brain, agents/decision tools, AI UI and timeline |
| W4 | No accepted Wave 4 implementation evidence mapped yet | Client Portal and separate Marketplace product boundary |

## Calculation contract

One estimate is an engineering-hour forecast for a row's accepted implementation package, including coding, tests and independent review; calendar waiting and owner decisions are excluded. Each row needs an approved `estimated_total_hours` and current `estimated_remaining_hours`. Whole and Wave percentages use the estimated hours of evidence-backed completed rows over the estimated hours of all scoped rows. Remaining hours are the sum of current estimates. **If any required row lacks an approved estimate, the corresponding aggregate is null/NOT ESTIMATED; the denominator must never silently shrink.** Review status and Implementation Gate PASS remain independent fields.

Estimate revisions are append-only: a later estimate adds a dated version and its assumptions to `estimate_history` before replacing current values. No historical snapshot is overwritten. The present v1.0 draft has `null` hour estimates because GitHub evidence proves scope/status but not productive engineering time or team velocity. A low-confidence numeric guess is not more useful than an explicit unknown. Populate hours only after a documented calibration pass; then dashboard aggregation is deterministic and labeled `FORECAST / ESTIMATE`.

## Sources and boundaries

Canonical scope: `docs/architecture/IMPLEMENTATION_WAVES.md` and `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md` on `main`; business count: `docs/flows/README.md`; current operations: `coordination/ACTIVE.md`, `coordination/REVIEWS/W0-03D.md`, exact merged PRs #3, #6, #9, #14, #16–#20, and Draft PR #30. `FORECAST.json` is a management projection only. It does not change locked FLOW/D, grant permissions, authorize a new slice or activate runtime behavior.
