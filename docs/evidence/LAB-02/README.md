# LAB-02 — изработено количество + одобрение + акордна цена по СМР (evidence)

Package: `docs/architecture/tasks/LAB-02_QUANTITY_APPROVAL_PIECE_RATE.md` (canon @ a4b5782, **R33** — Krum 07.11.2026).
Branch `claude/lab-02-quantity-approval`, created from LAB-01 head `6763970` (#73). **LAB-01 and LAB-02 merge together** (R33).
Canon: FLOW-028 (akord = approved quantity × agreed piece rate), FLOW-019 (DOWNTIME apart), CLAUDE.md §7/§8, R29, R31, R36, FG-64, FG-72.

## Backend — `backend/app/routes/labor_quantities.py`
| Endpoint | Who | What |
|---|---|---|
| `GET /api/labor-terms?project_id=` | Owner, Admin, Accountant | pay type + piece rate per SMR package (R31: nobody else sees a price) |
| `PUT /api/labor-terms/{package_id}` | Owner, Admin, Accountant | `Idempotency-Key` (R29); version + row in `labor_terms_history` + AuditEvent `labor_terms.set`; Akord needs a price > 0 |
| `PUT /api/labor-quantities/entry` | author on own draft/returned; Admin/Owner/SiteManager of the project on any report (R36) | the made quantity on a line; bumps the version, voids approvals, AuditEvent |
| `GET /api/labor-quantities/pending?project_id=` | Admin, Owner, SiteManager of the project | lines with quantity / approval state; a SiteManager gets no `piece_rate` |
| `POST /api/labor-quantities/approve` | Admin, Owner, SiteManager of the project — never the worker | `Idempotency-Key`; bound to (report, `report_version`, entry) — a stale version → 409; snapshots unit, pay type and piece rate of the SMR at approval; re-approval voids (keeps) the old record; AuditEvent |
| `POST /api/labor-quantities/classify` | same | LABOR / DOWNTIME / DOWNTIME_UNCLASSIFIED with a reason (FLOW-019); `Idempotency-Key`; AuditEvent |

- **`labor_cost.py` changes:**
  - pay type and piece rate are taken first from the approval's snapshot, so a later price change does not touch an approved quantity;
  - DOWNTIME comes from the approver's `labor_line_classifications` record (the legacy line `cost_type` is used only when there is no such record);
  - a report change voids the classifications too.
- **`PUT /daily-reports`** keeps the `quantity` field on entries: it is a validated fact the author enters, not a price.
- **Order of checks:** every non-approver role gets 403 before any key or body check.
- **New tenant-owned collections:** `labor_line_classifications` and `labor_terms_history` (ownership + A2B inventory).

## Frontend
- `/labor-quantities` — „Количества и акорд“, in the Personnel menu. It has two tabs:
  - „За одобрение“ (Admin / Owner / SiteManager): quantity, unit, SMR, approve / correct, mark as престой with a reason;
  - „Акордни цени“ (finance roles): pay type + price per SMR, with the reason.
- The technician's draft editor has an „Изработено количество“ field.
- Bulgarian; mobile-first (checked at 390 px).
- Helpers and their tests: `src/lib/laborQuantities.js` and `src/lib/__tests__/laborQuantities.test.js`.

## Tests — `tests-LAB-02.txt`
- `backend/tests/test_lab_02_quantity_approval.py`, 21 tests (mongomock + real Mongo):
  - 120 м2 × 5 = 600 in the Pay Run and in "изхарчено";
  - the worker cannot approve their own work;
  - a report change voids the approval, and an approval of the stale version gets 409;
  - a price change keeps 600;
  - re-approval keeps the old record;
  - DOWNTIME is a separate line with a required reason;
  - R29 (428 without a key, replay, 409 with another body);
  - roles × off/shadow/enforce;
  - the SiteManager sees no price;
  - quantity entry follows R36.
- PM-01 matrix regenerated (+144 cells; no difference between the three modes).
- **Bot scenario** (`bot/`): a real backend and the production build, Playwright at 390×844 — **8/8 passed**. The screenshots are in `bot/screens/`.

## LAB-02-C01 — merged LAB-01-I (four-eyes) — `tests-LAB-02-C01.txt`
- **Quantity entry:** `PUT /labor-quantities/entry` on an APPROVED report sends it back to SUBMITTED, exactly like the other R36 corrections (approved_by cleared, approvals void, DQ alert, `correctors`).
- **Approve / classify:** `POST /labor-quantities/approve` and `/classify` refuse anyone who authored or corrected the report (`self_approval_ids`), as well as the worker.
- **Test:** the admin corrects a quantity → the report is SUBMITTED → the admin gets 403 on approval → the SiteManager gets 200.
