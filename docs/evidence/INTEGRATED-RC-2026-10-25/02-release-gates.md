# Synology integration / acceptance / rollback plan

Status: PREPARATION ONLY — no usable integrated RC has passed yet.

## Fixed inputs

Production source baseline: `0b53bcd5b977ee27de8d4cee363fed41dd897482`; 1043/1043 files match Git objects. Served frontend SHA256: `0b2ff7788a62da4cfa2847277ee6a14e7af312694462fcc5c8e0b2cc0042fbf9`. The current container image IDs and their source mapping remain a required read-only Docker preflight.

Integration base: `c0e34e1f3037010311d352683d519c3c9d7dcbfa`. Include only exact reviewed revisions of #53, corrected #54, corrected #55 and corrected #56, recording each parent SHA. No main merge is authorized by this preparation. Existing draft file/storage/schedule work is not silently included; dependencies are declared in the scope matrix.

## Release gate order

1. Close RC-AUTH-01/02 on #56 and C16 Rule B on #55; repeat exact-head independent tests. After #55 focused gate passes, run the full real-Mongo matrix once.
2. Reconcile #53 with current main; test read-only scope, all roles, missing data and denied access. #54 requires owner's mobile/access corrections and screenshots for requester, approver and denied user; structural UI mockup first.
3. Integrate on `codex/integrated-rc-2026-10-25`, resolve only understood overlaps, record resolution diffs. Re-test cumulative auth, role/email, billing, pay-run selected-only/no-double-pay, dev-reset denial, canonical warehouse and requests. A green component test is not cumulative acceptance.
4. Embed full build SHA in backend metadata and visible UI. Record frontend/backend pairing and a mismatch failure. Do not use editable runtime configuration as the sole source identity. Include environment label without secrets.
5. Build a staging artifact from immutable Git objects with W0-09A release tools; retain manifest, SHA256SUMS, schema/config identifiers, feature flags, dependency lock information and immutable image IDs. Existing layout expects `PERMISSION_SERVICE_MODE=off`; LIVE-OPS writes require `enforce`. Resolve this explicitly with tested roles before building. No global flag change on production during preparation.
6. Start isolated staging with synthetic tenant A/B fixtures and all supported roles, separate database/storage, no production credentials or external email/billing writes. Bind a distinct address/port only after checking availability. Publish the actual reachable staging URL, full SHA and account roles; never label the existing production URL as the RC.
7. Execute the scenarios below through UI and API, including refresh/relogin and durable audit checks; capture actual pass/fail/blocked counts and screenshots. New missing FLOW screens are not represented as working by navigation placeholders.
8. Obtain final Krum decision against the exact artifact, acceptance results, limitations and rollback evidence. Only then schedule the production update.

## Backup and rollback preparation

The 2026-10-25 03:10 named backup exists: `begwork_atlas_2026-10-25_0310.archive.gz`, 800989 bytes, SHA256 `4153a69657c97a38a3063fa5666b1a7d61ca06154b214a530a520392ec68d598`. Streaming decompression/CRC passes; uncompressed 2727448 bytes. This is archive integrity, NOT database restore proof.

Before update:
- Read current container image IDs, compose/Dockerfile/nginx hashes, restart counts, disk space and thermal state. Never print `.env` values. Resolve the recorded NAS thermal incident before a heavy build/restore.
- Preserve the baseline source artifact, deployment markers and exact currently-running images. Verify image export/load or availability; rebuilding a mutable base tag is not rollback.
- Preserve the current database backup, uploads/customer-managed files and protected configuration, with a manifest of checksums/access controls. Database-only backup does not cover uploads or configuration.
- Create a fresh pre-update backup using the reviewed backup tool after a declared write window/quiescence. Do not rotate away the current rollback anchor.
- Use reviewed `ops/dr/w0_10a_restore_proof.sh` in an internal, isolated Docker network and separate volume with no production credentials. Verify collection/document/index counts, tenant boundaries and representative referential/financial invariants. Preserve report and archive checksum before/after. The September restore proof is historical and does not validate today's backup.
- Exercise W0-09A deploy → smoke → exact-image rollback in isolated staging. Force a controlled smoke failure and prove automatic rollback and persisted synthetic records. Record old/new image IDs and results.

Production update after approval: recheck approved SHA and backup, adopt verified current baseline with W0-09A if needed, stage new artifact and verify tree, apply only separately declared/approved migrations, switch/recreate planned services, validate `/api/health`, build SHA, login, roles, read-only smoke and restart stability. Stop at any mismatch.

Rollback triggers: identity mismatch, failed health/login, tenant/role regression, missing records or financial/stock inconsistency. Stop new writes; restore exact prior images/config/source through reviewed rollback tooling. Database restore is separate and potentially loses post-backup writes: do not perform it automatically as an application rollback. Reconcile writes/migration reversibility and obtain the applicable decision. Record every action and outcome in Issue #52.

## Krum's acceptance scenarios (for isolated RC, not production yet)

| Scenario | Expected proof |
|---|---|
| Build identity | Same full SHA in UI and API; environment clearly staging |
| Owner login/recovery | Correct account, successful reset, old session rejected, reused link rejected, overlapping emails leave a usable link |
| Roles and isolation | Owner/requester/approver/denied/warehouse/technician/accountant/viewer and supported driver scopes; direct URL/API and tenant B identifiers cannot widen rights; zero write after denial |
| Project → SMR → material request | Saved record survives refresh/relogin; stable project/item IDs; pending mapping cannot become usable stock |
| Request submit/approve/reject | Valid transitions, history/audit, duplicate click idempotent; requester cannot approve beyond permissions |
| Receive → dispatch → partial accept | Dispatch 10, accept 3+4+3 and 8+2; only accepted quantity costs project; zero unresolved at completion; value/layers conserved |
| Stock issue/consume/return | One canonical ledger, no legacy writers, no negative stock, reversal/history, equal rebuilt projections |
| Payroll recovery regression | Only selected eligible people; paid run cannot reopen/pay twice; account/ledger linkage and prior-period data limitations explicit |
| Finance and exports | Consistent gross/net totals and drill-down; internal cost hidden from client output; unauthorized exports denied; known unfinished paths visibly blocked |
| Daily report → quantity → act → invoice → payment | Each required stage linked and persistent; unavailable canonical stages explicitly fail acceptance rather than silently pass |
| Phone 390×844 | Request list/create/detail/approve-reject usable without horizontal overflow; compact navigation/actions |
| Failure and restart | Clear network/403/conflict errors, no fake zero totals; retries do not duplicate writes; records survive service restart |

## Current limitations / decision

NOT DEPLOY_READY. #56 and #55 have reproduced defects; #54 owner feedback remains open; full cumulative workflow, role and persistence gates have not run. Canonical Payment/DQ/Approval/File Registry/schedule and other gaps in the 216-row matrix are not closed by these PRs. Financial historical remediation remains separate. Current Docker/SSH access is unavailable, so exact image rollback and today's restore proof are blocked. No RC URL or release package is represented as ready.
