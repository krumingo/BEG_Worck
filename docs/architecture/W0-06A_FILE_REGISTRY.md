# W0-06A — File Registry foundation (FLOW-016)

> Task-ID `W0-06A`, Cycle-ID `C01`. Base `main@79af297612f57c055bb7caef3f0c48493800d1b6`.
> Issue: https://github.com/krumingo/BEG_Worck/issues/43
> Canon: `docs/flows/FLOW-016.md` (Business Lock), FLOW-002, FLOW-040,
> `TENANCY_MODEL.md` (D-15), `IMPLEMENTATION_WAVES.md` W0-06,
> CLAUDE.md v15 §2 rules 6, 7, 9 and 12.
>
> **W0-06A PASS is not FLOW-016 Implementation Gate PASS.** This is the
> foundation and the inventory. Provider onboarding, live adapters, the
> integrity scheduler and the real migration are later slices.

## На човешки

Направихме едно общо място, което знае **кой е всеки файл, къде се пази, към
какво е свързан и коя е текущата му версия**. Всеки файл получава стабилен
`file_id`; снимки, договори, фактури и други документи вече могат да сочат към
него, вместо да се копират по модулите.

Засега **не местим реални файлове и не пипаме NAS, Drive, S3 или production**.
Този етап прави основата, пълната инвентаризация на съществуващото и
детерминирания план за миграция — нищо повече.

## 1. What this slice contains

| | |
| --- | --- |
| `backend/app/files/models.py` | the six canonical records and the one vocabulary |
| `backend/app/files/registry.py` | the tenant-bound service — the ONE write path |
| `backend/app/files/providers/base.py` | the storage provider adapter CONTRACT |
| `backend/app/files/providers/fake.py` | the in-memory double the contract is proven against |
| `backend/app/files/migration_map.py` | the deterministic legacy migration plan |
| `backend/scripts/w0_06a_file_registry_guard.py` | the static guard (9 rules) |
| `backend/scripts/w0_06a_file_inventory.py` | the inventory generator + reconciliation |
| `backend/scripts/w0_06a_migration_plan.py` | the migration-map document generator |
| `docs/architecture/W0-06A_FILE_INVENTORY.md` | generated: every file-bearing site |
| `docs/architecture/W0-06A_MIGRATION_MAP.md` | generated: the plan and its blockers |

Two existing modules changed, minimally:

* `app/tenancy/ownership.py` — the six registry collections are classified
  `ORG_KEYED` / `FAMILY_FILES`. There is one classification in this codebase and
  a new collection that is not in it is `UNCLASSIFIED` to the W0-03E-A2C guard.
* `app/tenancy/data_access.py` — one accessor, `TenantData.audit_store_db()`,
  so the registry can append to the W0-04 audit store in the SAME database as
  the records it describes (the rule `app/permissions/audit_hooks.py` already
  follows) without a raw handle appearing in a non-boundary module.

No route is registered, no existing route changes behaviour, and no existing
collection is written differently. Importing `app.files` changes nothing.

## 2. The six records, and why each is separate

A file's identity, its content, its physical location and what it belongs to
change at different times and for different reasons. Keeping them in one
document would mean a new version rewriting the identity, or a provider
migration rewriting the content — both of which FLOW-016 forbids, and both of
which CLAUDE.md §2 rule 12 calls a second source of truth.

| record | collection | holds | deliberately does NOT hold |
| --- | --- | --- | --- |
| File | `file_registry` | `file_id`, category, sensitivity, current version no | checksum, size, mime, path, availability |
| FileVersion | `file_versions` | checksum, size, mime, author, reason, approval seal | where the bytes are |
| FileRelation | `file_relations` | one business record this file belongs to | anything about the bytes |
| ProviderLocation | `file_provider_locations` | provider kind, binding, container, object key, availability | **any credential** |
| DerivedArtifact | `file_derived_cache` | thumbnail / preview / OCR / PDF cache ref | any claim to be the original |
| DeleteRequest | `file_delete_requests` | who asked, why, and what the provider answered | permission to delete on its own |

### `file_id` is the business identity

Minted by BEG_Work, meaningless to any provider: no path, no bucket, no account,
no file name. It survives a provider migration, which is exactly what FLOW-016
§"Какво НЕ трябва да позволява" requires ("migration да счупи `file_id` и
relations" is forbidden). Nothing in `app/files` resolves a file by an object
key, and the `W06A-PROVIDERID` guard rule refuses new code that stores a
provider path as a file's identity.

### Ownership is server-derived and never optional

Every record carries `org_id`, the same tenant key the W0-03E-A2C boundary
scopes by — not `tenant_id` — because the registry's relations point at
`org_id`-keyed business records, and splitting the two keys would put half of
each relation on each side of the boundary. An ownerless record is refused at
BUILD time, before any database is involved (`models._require_owner`), and
again by the `W06A-OWNERLESS` guard rule.

### One file, many relations

A relation row carries the owner ITSELF rather than inheriting it from either
side. W0-03E-A2 proved why: an ownerless relation cannot say who wrote it, so
with colliding ids a row written by tenant B is honoured for tenant A. Adding a
relation also verifies the target record exists **in this tenant**, so a link
cannot be created across the boundary even when the target id also exists here.

Unlinking marks the relation removed, with an author and a reason, and touches
nothing else — not the file, not the other relations, not the provider object.
`remove_relation` contains no provider call at all.

### Versions are immutable

A new version is a new row. The previous row keeps every content fact
byte-identical and gains only the two fields that record that a successor
arrived. `models.assert_version_update_allowed` enumerates the four mutable
fields and refuses everything else, so "старите версии са read-only" is code
rather than prose. An approved or signed version can be FOLLOWED but never
re-sealed or replaced.

### A cache is never an original

`build_derived` hard-codes `is_canonical_original=False` and offers no
parameter to change it. `canonical_original()` reports `available=False` for a
missing, mutated, permission-denied or unreachable original **whatever the
cache holds**, and returns the derivatives in a separate field so a caller that
shows a stale preview does so knowingly. The `W06A-CACHEORIGINAL` guard rule
refuses code that claims otherwise.

### A delete is a request with a provider's answer

`request_physical_delete` deletes nothing. Only `record_delete_result`,
carrying a provider receipt, can close it, and only a CONFIRMED receipt marks
the original destroyed — a refusal or a failure returns the file to `active`,
because an original that still exists must not read as gone. The registry
record and its relation history survive the bytes either way.

## 3. The provider contract

`StorageProviderAdapter` covers put, read, stat, verify, request_delete,
temporary_access and capability reporting. Four properties are structural:

* **no permanent URL.** The only thing that hands back a link is
  `temporary_access`, every grant carries a mandatory expiry, and the contract
  caps a grant at 15 minutes. There is no `public_url` anywhere in the interface.
* **credentials never leave the server.** An adapter is built from a
  `ProviderBinding` that names the tenant's account and a *reference* to its
  encrypted secret. The value is not a field, so the binding can be logged and
  audited without leaking anything.
* **capabilities are declared, not assumed.** A provider without server-side
  checksums means a weaker integrity guarantee, and the Health Dashboard should
  be able to state that rather than imply it.
* **failures are distinguishable.** A lost permission, a missing object and an
  outage are three different availability states, as FLOW-016 requires. An
  externally mutated object is reported as a checksum mismatch; the adapter
  never heals and never decides to create a version.

**Nothing is activated.** `GoogleDriveAdapter`, `SynologyNasAdapter`,
`S3CompatibleAdapter` and `OnPremServerAdapter` are declared and every
operation raises `ProviderNotActivated`. `adapter_for` cannot return the
in-memory double, and the `W06A-FAKEPROVIDER` guard rule refuses an import of
it from the runtime surface. W0-06A reads no credential and touches no NAS,
Drive or bucket.

## 4. Audit and idempotency

Every consequential action appends one canonical FLOW-040 AuditEvent
(`source_flow: FLOW-016`) and accepts an idempotency key:

| action | retention |
| --- | --- |
| `file.registered`, `file.version.added`, `file.version.sealed` | R1 |
| `file.provider_location.set`, `file.physical_delete.requested`, `file.physical_delete.result` | R1 |
| `file.relation.added`, `file.relation.removed`, `file.integrity.checked` | R2 |
| `file.derived.cached` | R5 |

An integrity failure records the availability, the severity and **every
business record the file is attached to, by name** — FLOW-016 forbids reporting
a missing or altered file without the list of what it affects — and records
`treated_as_new_version: false`.

The key is reserved before the write and completed after the AuditEvent, so a
retry arriving in between finds a reservation. A replay of the same key with
the same payload returns the first result; the same key with a DIFFERENT
payload raises `IdempotencyConflict`, because the availability of a customer's
original is not something to guess at.

## 5. The inventory, and why it cannot be incomplete

`docs/architecture/W0-06A_FILE_INVENTORY.md` is **generated by scanning the
code**, not by listing it, and the scan is reconciled against the declared
sources three ways:

* a file-bearing site the scan finds that no declared source accounts for fails
  the run (`UNACCOUNTED`);
* a declared writer whose function no longer exists fails the run (`STALE`);
* a writer whose file field is set through a dynamic list — which no static
  scan can see as a document key — must be declared explicitly, with its
  reason, and is proven to still exist.

The scan resolves one level of indirection (`doc = {...}` … `insert_one(doc)`),
because nearly every real write site in this codebase has that shape; a scanner
that only read literal arguments would have found three sites instead of
thirty-five and still printed "no ASSUMED SAFE".

Current state: **16 declared sources, 35 distinct file-bearing sites, 0
reconciliation problems.**

### Defects the inventory found, recorded as debt (CLAUDE.md §18)

Not fixed by W0-06A. Each is in the inventory with its migration action:

1. **`GET /api/media/avatar/{filename}` serves any file in the uploads root
   without authentication** and without a media row, so it reaches another
   tenant's uploaded bytes by name alone. A FLOW-002 bypass. W0-06A adds no
   route and removes none; this belongs to the slice that owns the file HTTP
   surface.
2. **`POST /api/supplier-invoices/{id}/upload-file` stores a URL no route can
   serve.** It writes `/api/media/{uuid.ext}` while the media route serves
   `/api/media/file/{filename}` and requires a `media_files` row this path never
   creates. The bytes are written and never readable or deleted.
3. **`DELETE /api/scan-docs/{id}` deletes a file named by `doc["file_path"]`
   or `doc["url"]` joined onto `"uploads"`** — a provider-path-as-identity
   delete path, and the fields it reads are not the ones the create route writes.
4. **Three routes destroy a customer's original on an ordinary screen delete**
   (`media.py::delete_media`, `projects.py::delete_project_photo`,
   `scan_docs.py::delete_scan_doc`). FLOW-016 requires a right, a provider
   response and an AuditEvent. They are frozen by `W06A-PHYSDELETE` so no
   fourth one appears.
5. **The same photo is stored twice** — base64 on `asset_intake_pending` and
   again as a `data:` URI on `asset_items` — and **the same link is stored
   twice** (`invoices.scan_doc_id` and `scan_docs.linked_invoice_id`) with
   nothing keeping them consistent.
6. **`media_files` can express exactly ONE relation** (`context_type` /
   `context_id`), which is the per-module duplication FLOW-016 removes.

## 6. The migration map

`docs/architecture/W0-06A_MIGRATION_MAP.md`, generated. A `file_id` is derived
as `sha256(org_id | source key | legacy reference)`, so the plan is resumable
and diffable, and the owner inside the hash means the same legacy id in two
tenants never produces one id (0 collisions in the generated check).

**0 of 30 content-bearing rows are executable**, for two structural reasons:
no legacy row stores a checksum (computing one means reading the bytes, a
provider operation), and every relate/replace row depends on a file a register
row must create first. Provider onboarding is the gate on executing any of it.

Blockers that need a human answer, not more code: an ownerless row; the legacy
`message` media context, which has no collection in the active backend; opaque
attachment strings with no media record behind them; and photos stored as
base64 inside a database row, whose migration means WRITING bytes to a provider
for the first time.

## 7. The static guard

`backend/scripts/w0_06a_file_registry_guard.py` — whole active backend
(`app/**/*.py` + `server.py`), no module list, exit 1 on any violation.

| rule | what it refuses |
| --- | --- |
| `W06A-REGISTRY-WRITE` | a registry write outside `app/files/registry.py` |
| `W06A-OWNERLESS` | a registry record built without its owner |
| `W06A-RELTENANT` | a hand-assembled relation, or one with a literal tenant |
| `W06A-PROVIDERID` | a NEW persisted write of a provider path as a file's identity |
| `W06A-PHYSDELETE` | a NEW `os.remove` / `unlink` / `rmtree` on a stored object |
| `W06A-CACHEORIGINAL` | a cache entry claiming to be the original, or a derived kind written as a version |
| `W06A-FAKEPROVIDER` | importing the in-memory double from the runtime surface |
| `W06A-UNCLASSIFIED` | a `file_*` collection the models module does not declare |
| `W06A-STALE` | a declared legacy site whose code is gone |

The legacy is FROZEN, not ignored: 13 pointer sites and 3 physical-delete
sites are declared with the exact function they live in. A fourteenth or a
fourth is a violation from today, and a declaration that no longer matches real
code fails the run.

`W06A-PROVIDERID` and `W06A-RELTENANT` are anchored on PERSISTED writes, not on
any dict carrying the field name. A projection (`{"_id": 0, "avatar_url": 1}`),
a response body, or a query filter that happens to carry `file_id` and
`relation_type` stores no identity; a rule that reported those would bury the
real finding under dozens of false ones, which is how a guard gets switched off.

## 8. Residual limits — what this slice does NOT do

Stated so a reviewer does not have to find them:

1. **No HTTP route.** The registry has no API surface, so no FLOW-002
   permission check is wired to it yet. The service assumes its caller has
   already authorized the action and never widens access by itself. The file
   HTTP surface is a later slice.
2. **No DQ/Approval runtime.** `DeleteRequest.approval_id` records a reference;
   W0-05 issues one. A physical delete is therefore not yet gated by an
   Approval in code, only by the explicit request/result shape.
3. **No Data Quality / Alarm record.** An integrity failure produces the
   AuditEvent and the affected-record list FLOW-016 requires; creating the
   DQ/alarm row (FLOW-033/034) and the Health Dashboard are later slices. The
   result object already carries everything they need.
4. **No index migration.** The unique indexes the registry needs on a real
   server are declared and exercised in `tests/test_w0_06a_real_mongo.py`
   (`create_indexes`); installing them is the slice that owns the migration
   runner.
5. **No tenant onboarding gate.** FLOW-016 forbids activating a tenant without
   a verified Primary Storage Provider. `app/tenancy/onboarding.py` is
   unchanged; the gate belongs to provider onboarding.
6. **Nothing is migrated.** The legacy paths keep working exactly as they do
   today. The plan is a document.
7. **`update_change_order` writes its attachment field through a dynamic field
   list**, so no static scan can see it as a document key. It is declared in
   `DYNAMIC_FIELD_WRITERS` with that reason and proven to still exist.

## 9. How to verify this slice

```bash
cd backend

# the two guards, over the whole active backend
python scripts/w0_06a_file_registry_guard.py          # expect 0 violations
python scripts/w0_03e_a2c_tenant_boundary_guard.py    # expect 0 violations

# the inventory must reconcile with the code
python scripts/w0_06a_file_inventory.py --check       # expect 0 problems

# the in-memory suites
python -m pytest tests/test_w0_06a_file_registry.py \
                 tests/test_w0_06a_tenant_isolation.py \
                 tests/test_w0_06a_provider_contract.py \
                 tests/test_w0_06a_migration_map.py \
                 tests/test_w0_06a_static_guard.py -v --noconftest

# the disposable real-MongoDB gate — 0 required skips when the URL is given
W0_06A_REAL_MONGO_URL=mongodb://127.0.0.1:27017 \
  python -m pytest tests/test_w0_06a_real_mongo.py -v --noconftest
```

The gate refuses anything but a plain local `mongodb://` server (no Atlas, no
NAS, no `mongodb+srv`), works in its own `w006a_realmongo_<random>` database
and drops exactly that database afterwards.
