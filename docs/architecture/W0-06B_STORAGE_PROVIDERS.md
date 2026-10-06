# W0-06B — Storage Provider onboarding, adapters, activation and integrity foundation

> Task-ID `W0-06B` · Cycle `C01` · Issue #45 · Draft PR #46 (base `main`)
> Integration base: W0-06A Draft PR #44 head `9040fc1d4b40d5376cc8912ba316a206c02d207b`, which is a technical base and **not W0-06A PASS**.
> Canon: `docs/flows/FLOW-016.md` (Business Lock), FLOW-002 (permissions), FLOW-040 (AuditEvent), `TENANCY_MODEL.md` §4/§8 (D-15), `IMPLEMENTATION_WAVES.md` W0-06.
> **This is not a FLOW-016 Implementation Gate PASS.** The periodic scheduler and alarms, live migration and adoption, and the final FLOW-016 integration gate are still separate work.

## На човешки

Свързахме File Registry с реалните видове хранилища на клиента: S3, Google Drive, Synology/NAS и собствен сървър. Фирма не може да се активира, докато нейното хранилище не мине пълна проверка: качване, обратно четене, checksum и изтриване на тестов файл. BEG_Work вече различава дали оригиналът липсва, дали е променен, дали няма права или дали доставчикът е недостъпен, и за всеки случай показва всички засегнати актове, фактури, дефекти и други записи. Затворихме и публичния адрес за аватари, през който можеше да се изтегли чужд файл. Нищо не е пускано срещу истински NAS, Drive или S3. Всички проверки са минали само срещу временни локални имитации.

## 0. Entry gate: the four W0-06A findings (`coordination/REVIEWS/W0-06A.md`)

| # | finding | fix | proof |
|---|---|---|---|
| 1 | concurrent AuditEvent appends of one tenant forked the chain (`[1,1,2,3]`) | `app/audit/store.py`: each event is inserted into a deterministic chain slot (`_id = chain_slot_id(tenant, sequence)`). A writer that loses the race wrote nothing, re-reads the head and retries (bounded, jittered). This relies only on MongoDB's built-in `_id` index; append-only is preserved. | `tests/test_w0_06b_entry_gate.py::TestAuditChainUnderConcurrency`, including the review's exact race made deterministic and an unsafe mutation (random slot) that reproduces `[1,2,2]`. On real Mongo: 10/40 interleaved writers × 2 tenants, with and without the W0-04 indexes; the review's own `test_two_tenants_writing_at_once_keep_separate_intact_audit_chains` now passes. |
| 2 | `register_file(verify_relation_targets=False)` / `add_relation(verify_target=False)` bypassed target verification | Both parameters removed. Verification is unconditional, so a forged flag is a `TypeError` and writes nothing. No internal escape hatch exists. | `TestNoRelationTargetBypass`: missing and foreign-tenant targets are refused on both methods. Guard rule `W06B-RELBYPASS` (reinstated parameter / conditional check / bypass keyword) is mutation-tested. |
| 3 | a delete receipt for one version marked every location missing and the whole file deleted | A request has an explicit scope: `version_no=N` (optionally one `location_id`) or `whole_file=True`. Omitting both is refused. The exact location ids are frozen into the request, and the answer applies to those rows only. A version delete never changes other versions or the file status. A request is answered once. | `TestDeleteIsScopedToWhatWasAsked`, plus guard rule `W06B-DELSCOPE` with a mutation test that puts back `update_many({"file_id": ...})`. |
| 4 | the duplicate-checksum choice depended on `(created_at, random id)` | Every file gets an atomic, per-tenant `registration_seq` (`file_registry_sequences`, `$inc` on a deterministic `_id`). `find_by_checksum` orders by `file_order_key`, so the first file **registered** always wins. | A frozen clock plus ids in reverse lexical order, repeated 20×, with the physical storage order reversed. A mutation without the sequence flips the answer to the second file. Real Mongo: 25 concurrent registrations produce numbers 1..25 and exactly one counter. |

Also fixed: the two `git diff --check` EOF findings in the generated W0-06A docs (fixed in the generator).

## 1. Records and where they live

All records are `org_id`-keyed and live in the tenant's operational database. They are classified in `app/tenancy/ownership.py` (FAMILY_FILES).

| collection | owner module | holds |
|---|---|---|
| `storage_provider_bindings` | `app/files/storage.py` | role (`primary`/`backup`), provider kind, endpoint, account, container, tenant root, the credential **reference**, capabilities, connection status, last verification, activation time, accepted responsibility text |
| `storage_credentials` | `app/files/credentials.py` **only** (guard `W06B-CREDSTORE`) | AES-256-GCM sealed credentials and their field names; superseded, never deleted |
| `storage_activation_runs` | `app/files/storage.py` | one row per activation attempt: every step, result and code |
| `storage_access_grants` | `app/files/access.py` | single-use, expiring BEG_Work grants, stored as a token **hash** |
| `file_registry_sequences` | `app/files/registry.py` | the per-tenant registration counter |

**Tenant Registry** (system db, TENANCY_MODEL §4). A successful **primary** activation writes `primary_storage_provider_type`, `primary_storage_provider_reference` (the binding id), `storage_status: active`, `storage_verified_at` and the root fingerprint into `storage_root_fingerprints`. A backup writes `backup_storage_provider_*`. A failed first activation writes `storage_status: verification_failed`. A failed *re*-verification of a new provider never downgrades a tenant that is already active.

`file_id` stays the canonical identity. Provider paths, keys, URLs and Drive ids are coordinates on a `ProviderLocation`, never identities. Upload keys are opaque (`objects/<xx>/<random>`), so the provider learns nothing about the business record.

## 2. Provider contract and the four adapters

`app/files/providers/base.py` defines the contract: `capabilities`, `validate_credentials`, `check_root`, `put`, `read`, `stat`, `verify`, `request_delete`, `temporary_access` and `aclose`. An adapter is built only through `adapter_for(binding, credentials=…, transport=…)`, which refuses when there are no credentials and never returns the in-memory fake. In the runtime surface, only `app/files/storage.py` calls it (guard `W06B-ADAPTERBUILD`). Object keys and roots are validated: no traversal, absolute paths, backslashes or control characters. Credentials are held in a masked wrapper (`repr` → `***MASKED***`), and error texts never carry a URL or a header.

| adapter | protocol | integrity | temporary access | notes |
|---|---|---|---|---|
| `s3.py` S3-compatible | path-style, AWS SigV4 implemented from the spec (stdlib) | `x-amz-checksum-sha256` sent and requested back; read-and-hash if the server does not echo it | pre-signed URL, ≤ 15 min | signer matches AWS's published GET and pre-sign vectors and botocore `S3SigV4Auth` |
| `google_drive.py` Drive / Shared Drive | Drive v3 REST, OAuth refresh-token flow held server-side, `supportsAllDrives` | `sha256Checksum`, `headRevisionId` | none (BEG_Work grant) | objects outside the tenant root folder are refused; an object is found by key through `appProperties` |
| `synology.py` Synology / NAS | DSM File Station API; login POSTed (password never in a URL); re-login once on 106/107/119 | read-and-hash; `mtime:size` as the version | none (BEG_Work grant) | no overwrite (414); 105/407 → permission, 408 → missing |
| `on_prem.py` generic server | WebDAV (RFC 4918), Basic or Bearer | `OC-Checksum: SHA256` when offered, otherwise read-and-hash; ETag as the version | none (BEG_Work grant) | `If-None-Match: *` (no overwrite); `MKCOL` only below the tenant root, never the root itself |

The shared `verify()` keeps the states apart, in this order: `stat` (permission / outage / absent) → size → checksum (server-side, otherwise read and hash) → identity (same bytes under another provider id or version ⇒ `externally_changed`, a new availability state). A delete is reported `provider_confirmed` only when a fresh `stat` proves the object is absent.

## 3. Onboarding activation gate (`StorageProviderService.activate`)

Steps run in this order. Any failure leaves the binding `verification_failed`, the tenant **not** active, a run row naming the failed step and code, and a `storage.provider.verification_failed` AuditEvent. A test object that was already written is removed on a best-effort basis.

1. `provider_selected`: a customer-managed binding of **this** tenant (the fake and the legacy disk cannot even be configured).
2. `responsibility_accepted`: the FLOW-016 boundary text (BG + EN, version `FLOW-016/2026-08-03`), accepted by the same user who activates. The provider is not contacted before this step.
3. `credentials_valid`: the vault resolves the credentials and the provider accepts them.
4. `root_verified`: the root exists and is writable. No other tenant holds the same root fingerprint in the Tenant Registry. A root marker object (`_beg_work/tenant-root.json`, a hash of the tenant id) is absent or ours; if absent, it is written.
5. `test_object_uploaded`, then 6. `test_object_read_back` (byte-identical), then 7. `checksum_round_trip` (local sha256 = read-back sha256, equal to the provider's own checksum where reported, and the same size).
8. `test_object_cleaned_up`: the provider confirms, and a `stat` proves absence.
9. `registry_recorded`: Tenant Registry (primary) or backup reference.
10. `audit_recorded`: `storage.provider.verified`.

## 4. Integrity, availability and affected records (`app/files/integrity.py`)

`FileIntegrityService.check()` checks existence, size, checksum, provider id/version and access, plus whether the preview/cache could be regenerated. It records the verdict on the location and appends `file.integrity.checked`. A failure also appends one outcome event (`file.integrity.missing`, `…checksum_mismatch`, `…permission_denied`, `…provider_unreachable`, `…externally_changed`), correlated with the first. An inactive binding counts as `provider_unreachable` (`BINDING_NOT_ACTIVE`), **not** missing. A change is never adopted as a new version, and a cache entry is never promoted to the canonical original.

`AffectedRecordResolver` resolves every active FileRelation **in the tenant** and groups the records as projects, offers/contracts/annexes, acts/invoices, deliveries, daily_reports, tasks, defects_warranties, assets_repairs and other. Each record carries an `exists` flag and a label; a dangling target is reported, not hidden.

**W0-07 hand-off contract.** `beg.w0-06b.file_integrity_finding/v1` carries: tenant, file, version, location, provider/binding, availability, `finding_type`, severity (driven by the relations), expected vs observed, the method, the affected records (flat and grouped), the derived cache with `recoverable`/`is_canonical_original:false`, `treated_as_new_version:false`, a recovery owner/action (the customer, per the responsibility boundary), the audit event ids, and `dq_handoff {consumer: W0-07, state: not_consumed, blocking}`. **No** scheduler, DQ issue, alarm or W0-07 runtime is implemented here.

## 5. Security and access (`app/files/access.py`, `authorization.py`)

- Every action runs through the real W0-02 Permission Service. New actions `storage.provider.configure|activate|read`, `file.upload|open|download|share`, `file.integrity.check`, `file.sensitivity.restricted|confidential` are granted to **no** role except through the Owner/Admin full set (the W0-03D precedent). No role grant was invented. A context whose tenant is not the service's tenant is denied `CROSS_TENANT` before any assignment is read.
- A scoped request (`project`) also requires the file to be related to that very record (`FILE_NOT_IN_SCOPE`). A restricted or confidential file additionally needs its sensitivity action ("the narrower right wins").
- Grants are capped at 15 minutes. An S3 download is a provider pre-signed URL. Everything else is a single-use, revocable BEG_Work token, returned once and stored only as a sha256. On redeem it is re-authorized (FLOW-002 at every use), use-counted atomically (on a real server, 10 concurrent redeems produce exactly 1 success), and served only after the original's sha256 is re-verified.
- No secret reaches a business record, AuditEvent, API view, log or URL. `audit_trail.record` refuses to audit a secret-like field. Tests scan every collection of both databases, the views, the returned results and the logs for the fake secrets and the token.

### Legacy `GET /api/media/avatar/{filename}`: confirmed exposure, fixed in scope

**Evidence.** The pre-fix handler (reproduced verbatim in `tests/test_w0_06b_avatar_route.py::test_the_pre_fix_route_exposed_another_tenants_file_unauthenticated`) needed no session and checked no media row. It served **any** file in `/app/backend/uploads`, the directory that `media/upload`, `ocr_invoice`, `technician` and `procurement` all write tenant files into. Knowing one stored name was enough to fetch another tenant's invoice photo, bypassing the ACL that `/media/file/{filename}` enforces.

**C01 fix (not sufficient).** C01 kept the route public and narrowed it to a user's *current* profile photo. Codex's C01 review (`coordination/REVIEWS/W0-06B.md`) showed that this still returned another tenant's current avatar to a client without any session.

**C02 fix (FLOW-002).** The route now requires an authenticated, active session (`get_current_user`: the signed `(user_id, org_id)` pair, verified against the database) and resolves the photo **only inside the caller's own tenant view**:

- no session, an invalid token, a token naming another tenant for the user, or a disabled account → `401`/`403` before anything is read;
- a filename of another tenant → `404` (the caller's tenant view cannot see it), even when the URL is known;
- inside the tenant, a file is served only when exactly one `media_files` row of the tenant names it, the row is a `profile` upload of a user, that user is in the tenant with `avatar_url` equal to this file, the content type is an allowed image type, and the path stays inside the uploads directory. Invoice photos, stale avatars, orphans and an `avatar_url` pointed at a non-profile upload all get the same `404`.

**Audience.** Any authenticated, active member of the same tenant may see a colleague's current photo: the same audience that already receives `avatar_url` from the tenant's own list and roster routes. Narrowing it by role would be a FLOW-002 business decision and is not part of this correction.

**Frontend.** The ~19 avatar renderers use `components/AuthImage.js`. It fetches `/api/media/avatar/…` with the session's Bearer token and shows the bytes through an in-memory object URL. Other images are unchanged plain `<img>`. No public or permanent avatar URL exists.

**Client cache (C03).** Codex's C02 review found that the C02 object-URL cache was keyed by path only. In the same tab, tenant A's image came back for tenant B, and its five-minute lifetime was only checked lazily. `lib/protectedImageCache.js` now enforces:

- the cache holds entries of exactly one principal (the session token), and a different principal clears and revokes everything first;
- with no token, nothing is fetched and everything is revoked;
- a response that arrives after a switch or logout is discarded before it becomes an object URL;
- each entry is revoked by a timer after 5 minutes;
- `AuthContext` login and logout, and a token change in another tab (`storage` event), clear and revoke the cache, and mounted images reload under the current session.

Deterministic regressions: `node --test frontend/tests/protected_image_cache.test.mjs`.

## 6. Test and verification map

| suite | covers |
|---|---|
| `test_w0_06b_entry_gate.py` | the four findings: positive, forbidden and unsafe-mutation cases |
| `test_w0_06b_provider_adapters.py` | the contract on all four adapter families: credentials, root, round trip, the five failure states, delete answers, temporary access, URL secret scan, SigV4 vectors/botocore |
| `test_w0_06b_storage_onboarding.py` | the activation gate (every step broken deliberately), backup, replay, root/binding isolation, FLOW-002, vault cross-tenant/binding/master-key refusal, secret non-disclosure |
| `test_w0_06b_integrity_access.py` | integrity states and events, affected-record groups, preview/original separation, upload, grants (single-use, expiry, revoke, user/tenant binding, scope, sensitivity, revoked permission, changed bytes), token/secret scan |
| `test_w0_06b_avatar_route.py` | the exposure evidence and the fixed route (HTTP) |
| `test_w0_06b_static_guard.py` | `W06B-CREDSTORE`, `W06B-ADAPTERBUILD` |
| `test_w0_06b_real_mongo.py` | the real-server gate: audit concurrency (with and without the W0-04 indexes), bypass, scoped delete, determinism, onboarding/upload/integrity/grant concurrency per adapter, two-tenant root isolation |

Fake backends: `tests/w0_06b_fake_backends.py` (S3 with independent SigV4 verification, Drive, Synology, WebDAV), in-process through `httpx.MockTransport`.

## 7. Residual limits (explicitly NOT done)

- No periodic scheduler, alarm, DQ issue or W0-07 runtime. Only the finding contract exists.
- No HTTP routes for storage or file access. The services are domain-level.
- No live provider, real credential, real tenant activation, production migration or customer-original move/delete. Every adapter has been exercised only against in-process fakes. Real-provider behaviour (rate limits, Drive resumable upload for large files, S3 multipart above 5 GiB, DSM version differences, WebDAV server quirks) is unverified.
- No key rotation or credential replacement UI. `CredentialVault.supersede` exists, but no rotation flow does. The master key must be provisioned in the environment (`BEG_STORAGE_CREDENTIAL_KEY`) before any binding can be configured.
- No index migration for the new collections. The real-Mongo gate creates its own indexes.
- A failed activation can leave its root marker at the provider. This is fail-closed: the root stays claimed by the tenant that tried it.
- Avatar (C02): closed under FLOW-002 (§5). The frontend change has been syntax-checked and unit-checked, but not exercised in a browser in this container.
- Legacy upload routes still write to the app disk. Migrating them into the registry is the later FLOW-016 migration slice.
