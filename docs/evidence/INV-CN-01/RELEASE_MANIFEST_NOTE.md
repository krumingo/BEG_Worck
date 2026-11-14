# INV-CN-01: Release Manifest note (FG-217 / FG-231 / Р49(1) data and index migration)

This PR has a **data and index migration**. It is a critical migration (CLAUDE.md §8): it runs only after the Owner approves the exact dry-run report.

## Steps per tenant operational database (Staging first, then Production)

1. **Deploy the build.**
   - At startup the application builds the partial index for our outgoing series (`inv_cn_02_outgoing_invoice_no`).
   - The per-supplier index (`inv_cn_02_supplier_invoice_no`) is built at startup and at first use wherever the data allows (FG-264): a fresh tenant, or one already migrated. On a legacy database whose rows collide the build is refused; there every create or edit of a supplier invoice decides under the (supplier, number) lock in one transaction until the migration below backfills `supplier_key` and builds the index.
   - Until the migration has run, any create that hits the legacy index answers **409**, never a 500.
2. **Dry run (read only):** `python scripts/inv_cn_01_migrate.py`, with `MONGO_URL` / `DB_NAME` of the target. It prints a JSON report:
   - `legacy_index`: the legacy unique+sparse `(org_id, invoice_no)` index and the superseded `inv_cn_01_invoice_no_by_direction`, both to be dropped;
   - `missing_indexes`: the indexes still to be built;
   - per tenant:
     - `drafts_number_removed`: drafts whose `invoice_no` is null or "", which lose the field;
     - `legacy_numbered_drafts_to_issue`: outgoing drafts numbered before INV-CN-01; Р49(1) makes them `Issued`;
     - `supplier_keys_to_set`: the `supplier_key` backfill (ЕИК, else counterparty record, else name);
     - `supplier_conflicts`: the same supplier + number twice. `apply` refuses while any exist; each must be resolved first (cancel the wrong one, Р51(3));
     - `supplier_tax_id_missing`: legacy supplier invoices without ЕИК / foreign tax number. `apply` opens one canonical `dq_issues` record per invoice for the Accountant (Р55(1)).
   - `changes`: the total. 0 means nothing to do.
3. **Owner approval of that exact report**, recorded with the deployment (approver, report hash, time).
4. **Apply:** `python scripts/inv_cn_01_migrate.py --apply --actor <approved operator id>`. It is idempotent: a second run finds `changes: 0`. Each legacy draft that becomes `Issued` gets one AuditEvent, `finance.invoice.issued_by_migration`.
5. **Post-deployment check:** the dry run again → `changes: 0`. Then create two outgoing drafts and issue one (`INV-…` continues the series).

## Rollback

- **Code:** revert the PR.
- **Data:** the report lists every invoice id changed.
  - The status of the migrated drafts can be set back to `Draft`, and `issued_number` / `issued_by_migration` unset.
  - The legacy index can be re-created only once no two drafts lack a number.
  - Both steps need the same Owner approval.

## Not covered by the migration

D1/D2/D4/D13 (missing models) and D5 (File Registry #44); see the README.
