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

## LAB-02-C02 — bot F-1 / F-2 — `tests-LAB-02-C02.txt`
- **F-2:** one `<AppToaster/>` (sonner; top-center for 390 px, richColors, close button) is mounted at the app root. Every `toast()` (confirmations, hints, 403/409 errors) is now visible, which was broken on main too. It is an isolated commit `a0d1ca9` (App.js + AppToaster + test) that can be cherry-picked onto main by itself.
- **F-1:**
  - pay types are shown in Bulgarian everywhere they are displayed (`lib/payTypes.js` → Pay Runs, All reports, My money, My payslips): Акорд / Часова ставка / Надница / Месечна заплата;
  - the internal code "(FLOW-028)" is removed from the screen subtitle and from user-facing messages (DQ, correction reasons, Pay Run warnings);
  - the error details of the LAB-01/LAB-02 endpoints that the screens show as toasts are now Bulgarian.
- **Bot:** 12/12, with new checks that the save, approve and "Напишете причина за престоя" toasts are visible and that no "FLOW-" text appears.

## LAB-02-B (FLOW Guard pass 9: FG-92, FG-93, FG-94; LAB-01-J merged) — `tests-LAB-02-B.txt`
- **FG-92** was already closed by LAB-01-I, which has been on this branch since 789bbd9:
  - a quantity entry on an approved report sends it back to SUBMITTED;
  - the approver must differ from the worker, `submitted_by`, the creator and every corrector.
  - Added the exact regression tests: the SiteManager sets 800 and gets 403 on his own approval, with nothing payable (no 7200), while the Owner can approve; a SiteManager who is `submitted_by` gets 403 on approve and on classify.
- **FG-93:** approve and classify return **409** on a line that is in payroll, decided from the pay-run lines as in LAB-01-J. Quantity entry is also 409 there.
- **FG-94:** classify accepts only submitted or approved lines; a draft gets **409**.

## LAB-02-B2 (audit LAB02-1) — `tests-LAB-02-B2.txt`
- **One active decision per line:** unique partial indexes on `(org_id, report_id, entry_id, report_version)`:
  - `labor_quantity_approvals` where `status = approved` (`one_approved_per_line`);
  - `labor_line_classifications` where `status = active` (`one_active_per_line`).
- **When they are created:** at startup (`server.py`) and lazily before the first decision in a database that missed startup.
- **Concurrent approvals:** with different keys, one wins and the others get **409**, with nothing written. Void history records do not block a re-approval.
- **Test:** 4 concurrent approvals give exactly 1 active record, and the pending list shows the quantity that is paid. The same test **fails** on real Mongo with the guard disabled (`repro_lab02_1_without_guard.py`, 3/3 failures).
