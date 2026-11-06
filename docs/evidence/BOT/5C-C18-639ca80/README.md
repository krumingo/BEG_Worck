# BOT 5C-C18 — PR #55 @ `639ca80e89db3d603d17cdded769b01aa4c92bd9`

Branch `task5c/live-ops-01-canonical-stock-core`. Local only, synthetic data, `PERMISSION_SERVICE_MODE=enforce`. No production, no merge, no deploy.
**Result: FAIL 33/42** (2 steps are "no screen", counted as not passed). `bot_result.json` has every step with its detail; screenshots `01…30_*.png` (1280 and 390×844).

## Exact commands
```bash
git fetch origin task5c/live-ops-01-canonical-stock-core
git worktree add -f /tmp/botwt/639ca80 639ca80e89db3d603d17cdded769b01aa4c92bd9
docs/evidence/BOT/5C-C18-639ca80/setup.sh /tmp/botwt/639ca80      # Mongo 7 RS + backend(enforce) + prod frontend build + 2 tenants
BOT_OUT=$PWD/docs/evidence/BOT/5C-C18-639ca80 BOT_SHA=639ca80 NODE_PATH=$(npm root -g) \
  node docs/evidence/BOT/5C-C18-639ca80/5C-C18.js
docs/evidence/BOT/runner/stop_stack.sh
```
`setup.sh` (all synthetic): second firm via the real seed path; distinct slugs → distinct tenant DBs; `w0_01_bootstrap_tenant_registry.py --apply`; authoritative company assignments for the two seeded admins (`grant_admins.py`; the W0-02 bootstrap script refuses to run outside its sanctioned validation env); `ensure_required_indexes` on both tenant DBs (`indexes.py`, see F-1b). Other users (Warehousekeeper, Technician, Viewer, Accountant), project, SMR group are created through the real API; two `md_item` rows are inserted directly (synthetic).

## Findings on this head (not workarounds — as deployed)
| # | What | Evidence |
|---|---|---|
| F-1 | **First canonical write fails on any tenant that already has an AuditEvent.** `AUDIT_CHAIN_WRITE_FAILED` (500): the command service starts its own chain at `sequence 1` (`audit_chain_head`), but `audit_events` already holds the W0-04 event(s) (here the `permission.role_assignment.granted` of user creation) under the same unique `(tenant_id, sequence)` index. Any later permission/master-data AuditEvent would collide the same way. | step 0a, `01_*.png` |
| F-1b | **Required indexes are created only by test fixtures** (`ensure_required_indexes` has no caller outside `tests/`); a fresh enforce deploy answers 503 `INDEX_MISSING` until something creates them. | probe before setup; `indexes.py` |
| F-2 | **The second inbound batch of a tenant fails.** The legacy unique index `warehouse_batches(org_id, batch_number)` (`fifo_service.py:181`) collides because canonical batch rows have no `batch_number` (null). Error is reported as `AUDIT_CHAIN_WRITE_FAILED`. This is what breaks every acceptance/second receive. | step 1.1b, `03_*.png` |
| F-3 | `GET /warehouse/canonical/integrity-warnings` → **500** (`TypeError: TenantCollection.distinct() got an unexpected keyword argument 'session'`, `queries.py:309`). The UI "Аларми" panel then shows **"Няма активни аларми"** — a false all-clear on an error. | step 1.7, `11_*.png` |
| F-4 | Dispatch via the UI form (destination `project`, state always `free`) returns 200 and credits `project:free` immediately — the stock is on the project **before any acceptance** (Rule B bypass). The form cannot send `in_transit` state, so a proper dispatch needs the API. | step 1.3p, `06_*.png` |
| F-5 | An identical resend of an outbound command (consume) returns 409 `IDEMPOTENCY_CONFLICT` ("different request payload") instead of the original result; inbound replay works. No duplicate row is created. Matters for offline retries. | step 2.8b |
| F-6 | `/warehouse/canonical` is `AdminRoute` (Admin/Owner/SiteManager/Accountant): the **Accountant (read-only role, API 403 on writes) sees the full write form**; the **Warehousekeeper (allowed to receive/dispatch/accept on the API) has no screen** (redirected to `/tech`). There is no SMR field on the form. | steps 3.5 (accountant), 3.6, 2.7a |

## Workarounds (synthetic local DB only; every step after them says "with workaround")
- W1 after 0a: `audit_events`/`audit_counters` of tenant A cleared so the canonical chain can start at 1.
- W2 after 1.1b: legacy unique index `org_id_1_batch_number_1` dropped on tenant A.
Without them the scenario cannot get past the first receive/second receive; they are not part of the PR.

## Scenario results (with W1+W2)
- Run 1 (1280, UI): receive 10 → dispatch 10 (API, `in_transit` state) → accept 3+4+3: all 200; open discrepancies 1 → 2 → **0**; `warehouse_in_transit` unresolved map empty. PASS (steps 1.4, 1.5).
- Run 2 (390×844, UI): receive 10 → dispatch 10 → accept 8 (1 open) → accept 2 → **0 open**. PASS (2.3, 2.4). Open = `transit_discrepancy` rows with no `discrepancy_resolved` row (append-only ledger).
- Consume 3 to an SMR: API only (**no screen** for SMR binding) → exactly **one** `material_entries` row for the movement and for the SMR, also after the resend. PASS (2.8). Project page ledger visible at both widths (2.9, 2.10).
- Permissions (direct API): Warehousekeeper receive 200 / consume 403 / read 200; Technician and Viewer 403 on receive, consume and read; Accountant receive 403 / read 200. PASS (3.1–3.4). Technician/Viewer/Keeper are redirected to `/tech` (no write action visible) at both widths; Accountant is not (F-6).
- Tenant B: balance/history/stock of A's item empty, cannot accept A's dispatch, UI stock panel empty at both widths; tenant A still sees its stock. PASS (4.1–4.4).

## Not covered
No-screen steps are marked `NO_SCREEN` (2.7a, 3.6), not pass. Reservation, quarantine, write-off, return-to-supplier, SiteManager project-scope consume, and the Project Material Ledger numbers were not exercised.
Cosmetic: dark-mode field labels on the canonical form are almost unreadable (see `16_*.png`).
