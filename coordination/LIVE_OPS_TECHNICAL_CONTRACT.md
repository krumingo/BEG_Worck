# LIVE-OPS-01 — Technical Contract

> **Status:** CONTRACT FREEZE READY  
> **Version:** v6-contract-freeze — independently reviewed and verified  
> **Task:** LIVE-OPS-01 / TASK 4  
> **Freeze date:** 2026-10-10  
> **Audit baseline:** merged `main` at `79af297612f57c055bb7caef3f0c48493800d1b6`  
> **Authority:** approved FLOW documents and later explicit owner decisions  
> **Boundary:** contract only; no implementation, migration, merge, deploy, production activation, or customer-original mutation

## 0. Purpose and authority

This document freezes the intended technical behavior of the first LIVE-OPS slice: material requests, warehouse/material movements, assets/custody/repairs, permissions, audit, and file relations. It translates the following authoritative sources into an implementation contract:

- FLOW-002 — permissions and RoleAssignment;
- FLOW-009 — warehouse/material movements;
- FLOW-011 — assets, QR, and two-phase custody;
- FLOW-012 — logistics, delivery, partial quantities, and acceptance;
- FLOW-016 — File Registry and provider abstraction;
- FLOW-020 — material requests, delivery, invoice matching, and material readiness;
- FLOW-032 — Master Data identity;
- FLOW-040 — canonical append-only AuditEvent;
- FLOW-043 — architecture decisions D-04, D-08, D-11, D-12, and D-15;
- Issue #52 `OWNER_DECISIONS — LIVE-OPS-01` and `UX V2 — OWNER APPROVAL`.

If this candidate conflicts with a FLOW or a later explicit owner decision, the FLOW/owner decision wins and the contract returns to DRAFT. Existing code is evidence, not authority.

### 0.1 Approved owner decisions incorporated here

1. A write-enabled pilot is allowed only after canonical Permission Service and AuditEvent enforcement.
2. `warehouse_transactions` is the authoritative movement ledger and stock source of truth.
3. `warehouse_batches` is a FIFO/batch/cost projection, never an independent stock source.
4. `central` is the canonical warehouse type.
5. `main` is legacy and must be reconciled/migrated to `central` only after inventory, dry-run, backup, validation, and rollback proof.
6. Warehouse primary display label is its human-readable `name`; `code` and ID are secondary.
7. No third canonical warehouse or stock model may be introduced.
8. **F-09 = B — acceptance recognition.** Project cost is recognized only for destination-accepted quantity. If 10 units are dispatched, 8 are accepted, and 2 are missing, project cost is 8; the remaining quantity/value 2 stays `in_transit/unresolved` until a canonical acceptance, return, correction, or authorized write-off resolves it.

## 1. Normative language and global invariants

`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative.

| ID | Frozen invariant |
|---|---|
| LO-I-001 | No consequential LIVE-OPS write executes unless `PERMISSION_SERVICE_MODE=enforce` and the canonical AuditEvent write participates in the command's atomic boundary. A LIVE-OPS writer fails closed when permission mode is `off`, `shadow`, unknown, or unavailable. |
| LO-I-002 | Tenant is resolved server-side. Project/action scope is deny-by-default. IDs, body fields, query parameters, QR payloads, and URLs cannot select or widen tenant/project access. |
| LO-I-003 | `warehouse_transactions` is the only authoritative material movement/stock ledger. |
| LO-I-004 | `warehouse_batches` is derived from canonical movements and is rebuildable; it never accepts an independent business write. |
| LO-I-005 | Every actionable material line references one canonical FLOW-032 `item_id`; supplier/free-text names are evidence or aliases, not identity. A request draft/submission or received-into-quarantine line MAY instead reference one `md_pending_mapping` candidate, but it cannot become available, reserved, issued, consumed, or project-costed until audited human confirmation links it to `item_id`. |
| LO-I-006 | `central` is canonical. `main` cannot be created by normal post-freeze application writers. |
| LO-I-007 | Warehouse UI displays `name` first. `code`/ID remains visible only as secondary technical context where useful. |
| LO-I-008 | State changes occur only through named action/command endpoints. Generic update endpoints cannot write state, custody, stock, approval, audit, or derived quantities. |
| LO-I-009 | Every retryable command has a tenant-scoped `idempotency_key` and a `correlation_id`. Same key + same payload returns the original result; same key + different payload is rejected. |
| LO-I-010 | No successful command may silently produce negative available stock, double posting, double cost, two active custodians, or an unaudited consequential write. |
| LO-I-011 | Stock and dashboard projections process the complete ledger or a verified checkpoint plus complete tail. Fixed `to_list(N)` truncation is forbidden. |
| LO-I-012 | Asset responsibility changes only on accepted two-phase handover. Pending/declined/problem transfers do not change the authoritative custodian. |
| LO-I-013 | `audit_events` is append-only. No normal API edits or deletes an AuditEvent. |
| LO-I-014 | A file is identified by canonical `file_id`; local path and provider URL are never authoritative identity. |
| LO-I-015 | Inventory and dry-run are read-only. Ambiguous mapping is `STOP`, never guessed. Production mutation is outside this task. |
| LO-I-016 | Corrections use compensating/reversal records; committed ledger/audit history is not rewritten or hard-deleted. |
| LO-I-017 | Quantity and value are conserved across movement, batch/FIFO, request-line, project-cost, and rollback projections. |
| LO-I-018 | Each physical fact has exactly one canonical writer. Request/readiness views derive warehouse, delivery, and acceptance facts through stable references; they do not create a second physical record. |
| LO-I-019 | Outbound value and FIFO allocation are server-derived. Clients cannot author outbound unit/total value or FIFO order. |
| LO-I-020 | Legacy parallel writers are inventoried, frozen at cutover, and either migrated as read-only input or rebuilt as projections; none remains a competing source of truth. |
| LO-I-021 | Dispatch to transport does not recognize project cost. Destination acceptance recognizes project cost exactly once for accepted quantity only; unresolved remainder retains its original valuation layers or, for a supplier origin that has no stock layer yet, its allocated quantity/value in `in_transit/unresolved`. Later `consume` allocates accepted project stock to Work Package/SMR and does not recognize the cost again. |
| LO-I-022 | The destination-acceptance command is the sole writer of quantity acceptance. In P0 its canonical `receive` ledger line is itself the acceptance record; no parallel Delivery/Acceptance persistence may write the same fact. |
| LO-I-023 | If a FLOW makes evidence mandatory, the command fails closed until canonical File Registry evidence is available. Only FLOW-optional evidence may be omitted; a path or URL is never a substitute. |
| LO-I-024 | Every in-transit quantity/value is scoped to one canonical origin line: warehouse dispatch or supplier-delivery source allocation. For that origin, accepted + returned-to-source + written-off + corrected quantity cannot exceed the origin quantity. Every acceptance/resolution references that origin. |

## 2. Canonical entities

### 2.1 Material / Item

- **Canonical model:** FLOW-032 Master Data entity `item`; merged-main collection convention `md_item`.
- **Canonical ID:** stable `item_id` (`md_item.id`) within the resolved tenant.
- **Allowed writers:** Master Data create/review/merge/archive services after human confirmation and permission checks.
- **Read projections:** item picker/search, confirmed supplier aliases, normalized unit/conversion view, warehouse/request display snapshots.
- **Forbidden writers:** procurement, invoice OCR, warehouse, request, and frontend code MUST NOT create a new item from free text. They submit a mapping candidate or select an existing `item_id`.
- **Immutable:** `id`, `tenant_id`, `entity_type`, creation provenance; confirmed identifiers and legacy references are append/history-preserving.
- **Mutable only through Master Data actions:** display name, aliases, category, unit metadata, archive/merge state. Merge keeps a redirect and AuditEvent.

### 2.2 Material Request

- **Canonical model:** `material_requests` aggregate with stable embedded line IDs or an equivalent normalized persistence that preserves the same aggregate contract.
- **Canonical IDs:** `request_id` and stable `request_line_id`; request number is display/numbering, not identity.
- **Allowed writers:** Material Request command service only.
- **Read projections:** request list/detail, approval queue, line fulfillment/readiness, project needs, logistics queue.
- **Forbidden writers:** generic `PUT/PATCH` of `status`, fulfilled quantities, approver, or line facts; invoice-post, dashboard, and frontend code cannot set request state directly.
- **Immutable after submit:** tenant, project, requester, source offer/version refs, line IDs, original requested item/spec/unit, created timestamp. A correction is a versioned/actioned change, not silent overwrite.
- **Mutable in DRAFT:** needed date, priority, reason, notes, destination/source preference, subobject/location, SMR/Work Package reference, allowed equivalents, partial-delivery flag, blocking rule, evidence relation when enabled, and line quantities/specifications.
- **Mutable after submit:** only explicit action results, evidence links, approved quantities/limits, maximum unit/total price and VAT basis, cancellation/rejection reason, and derived line facts.

### 2.3 Warehouse

- **Canonical model:** `warehouses`.
- **Canonical ID:** `warehouse_id` (`warehouses.id`); `code` is a tenant-scoped alternate key.
- **Allowed writers:** Warehouse Administration command service with Permission Service and AuditEvent.
- **Read projections:** warehouse picker/cards, stock by warehouse, source/destination labels, project/vehicle/person association.
- **Forbidden writers:** invoice intake and stock helpers cannot auto-create `main` or any warehouse; domain code cannot identify a warehouse solely by display name.
- **Immutable:** ID, tenant, creation provenance; type changes that alter identity semantics require an explicit audited migration/action.
- **Mutable:** human name, address, notes, active/archive state, valid association metadata. Archive is refused while stock/reservations/quarantine/pending movements exist.
- **Identity rule:** type `central` is canonical; `main` is migration-only legacy input.

### 2.4 Warehouse Transaction

- **Canonical model:** append-only `warehouse_transactions`.
- **Canonical ID:** `warehouse_transaction_id` plus tenant-scoped unique `idempotency_key` for the originating command.
- **Allowed writers:** Warehouse Movement domain service only, inside the atomic command boundary defined in §4.
- **Read projections:** on-hand/reserved/available/quarantine, request fulfillment, project material ledger/cost, movement timeline, reconciliation, dashboard.
- **Forbidden writers:** invoice, request, dashboard, batch/FIFO, and frontend modules cannot insert/update ledger rows directly. No free-text-only movement identity.
- **Immutable:** the complete committed transaction: tenant, type, item, source/destination, quantities, unit/value, references, actor, timestamps, idempotency/correlation, evidence.
- **Correction:** append an explicit reversal/correction transaction referencing the original; never update/delete the original.
- **Canonical granularity:** one command MAY append one document with `lines[]` or one document per line plus `command_id`, but every line has a stable ID and the complete §4.1 envelope. Idempotency is per command and reconciliation is per line. Legacy multi-line rows are read through a frozen adapter; their original shape is never rewritten.

### 2.5 Warehouse Batch / FIFO projection

- **Canonical model:** `warehouse_batches` as a derived FIFO/batch/cost projection of canonical transactions.
- **Canonical ID:** stable `batch_id` tied to its originating accepted `receive` line or migration-only `opening_balance` line.
- **Allowed writers:** FIFO projection service invoked by/replaying the canonical Warehouse Movement service.
- **Read projections:** FIFO layers, remaining quantity/value, expiry/lot views, stock valuation.
- **Forbidden writers:** no independent intake/consume/return API may mutate batches without a corresponding canonical transaction.
- **Immutable:** tenant, item, warehouse, origin transaction/line, original quantity/value, lot/provenance.
- **Mutable projection fields:** remaining quantity/value and derived status/checkpoint. All must be reproducible by replaying the ledger's recorded layer allocations; replay MUST NOT re-run a potentially different FIFO choice.

### 2.5.1 Legacy/derived stores with explicit disposition

- `project_material_ops` and `material_consumption_log` are legacy parallel material writers. They are read-only migration/reconciliation inputs and are frozen when the canonical writer is enabled.
- `material_entries` is a rebuildable project-cost projection derived only from canonical ledger facts after cutover. A controlled `delete_many` rebuild is permitted only for this disposable projection, never for source/ledger data.
- `asset_movements` is the append-only asset movement history. After cutover it is written only by Custody/Repair command services and cannot independently change accepted custody/location.
- No endpoint may dual-write these stores and treat them as an additional source of truth.

### 2.6 Asset Unit

- **Canonical model:** physical asset identity backed by existing `asset_units`, mapped to FLOW-032 `physical_asset` identity where required.
- **Canonical ID:** `asset_unit_id`; QR/serial/inventory numbers are alternate identifiers, not record identity.
- **Allowed writers:** Asset domain service; identity changes through Master Data where applicable.
- **Read projections:** asset list/detail, QR view, location, accepted custodian, pending recipient, expected return, repair state, history.
- **Forbidden writers:** generic unit update cannot directly set custodian, custody state, location transition, repair state, written-off state, or QR movement result.
- **Immutable:** ID, tenant, stable item/type relation, creation provenance, confirmed serial/QR/inventory identity history.
- **Mutable through named actions:** descriptive fields, lifecycle status, accepted location, expected-return policy/date, archive/write-off after required approval. No hard-delete of a used asset.

### 2.7 Asset Custody

- **Canonical model:** `asset_custody` transfer/accepted-responsibility records.
- **Canonical ID:** `custody_id`/handover ID with stable asset, from-custodian, pending-recipient, and correlation.
- **Allowed writers:** Custody command service only.
- **Read projections:** current accepted custodian, pending acceptance, declined/problem history, overdue acceptance/return alerts.
- **Forbidden writers:** open `give`, `take`, QR, or generic asset update that bypasses two-phase rules; raw close/reassign by ID.
- **Immutable:** parties, asset, initiator, initial location/state snapshot, created time, correlation/idempotency, evidence links.
- **Mutable only by valid actions:** pending → accepted/declined/problem/cancelled with actor, reason, evidence, and timestamps. History is never removed.

### 2.8 Asset Repair

- **Canonical model:** `asset_repairs`.
- **Canonical ID:** `repair_id`.
- **Allowed writers:** Repair command service only.
- **Read projections:** active repair, history, cost, warranty, provider, return location, asset operational status.
- **Forbidden writers:** `move action=repair` without a repair record; direct status-only repair/return; hard-delete of repair history.
- **Immutable:** asset, opening actor/time, source location/custodian snapshot, initial defect/evidence.
- **Mutable through lifecycle actions:** provider, diagnosis, evidence, cost, warranty, completion/return facts. Completing repair closes the repair record and opens a pending handover to the destination; accepted location/responsibility changes only when that handover is accepted.

### 2.9 AuditEvent

- **Canonical model:** FLOW-040 envelope in `audit_events`, using `backend/app/audit/*`.
- **Canonical ID:** `event_id`; hash-chain/order fields follow the canonical store.
- **Allowed writers:** canonical audit store called by domain/permission/file/migration services.
- **Read projections:** scoped audit timeline, object history, security/denial view, correlation trace, export.
- **Forbidden writers:** legacy-only `audit_logs` for consequential LIVE-OPS actions; direct UI/API edit/delete; domain-specific parallel audit tables as source of truth.
- **Immutable:** entire event after append.

### 2.10 Permission / RoleAssignment

- **Canonical model:** FLOW-002 RoleAssignment through Permission Service; merged-main authoritative registry `tenant_role_assignments`.
- **Canonical ID:** `role_assignment_id` with tenant, principal, role/action catalog, and scope.
- **Allowed writers:** Permission workflow/service only; every create/change/revoke is audited.
- **Read projections:** effective permissions for tenant/project/module/action, assignment administration, decision explanation.
- **Forbidden writers:** route-local role-name lists as the only guard for critical actions; client-supplied tenant/project scope; direct registry mutation.
- **Immutable:** ID, tenant, principal, creation provenance, revision history.
- **Mutable through workflow:** enabled/revoked status, scoped action set, validity window, revision. No silent in-place history loss.

### 2.11 File Registry

- **Canonical model:** FLOW-016 File Registry record and provider relation. It is a required Wave-0 predecessor and does not yet exist in the reviewed merged-main baseline. Merged-main local upload paths are legacy, not canonical.
- **Canonical ID:** stable `file_id`; business relations reference `file_id`.
- **Allowed writers:** File Registry service and approved provider adapters after permission/scope checks.
- **Read projections:** invoice/receipt/evidence attachment, preview/download availability, checksum/version/provider status.
- **Forbidden writers:** module-owned original-file copies, permanent local paths, or provider URLs used as identity; direct overwrite/delete of approved originals.
- **Immutable:** file ID, tenant, original version/checksum and version lineage.
- **Mutable through audited actions:** business relations, metadata allowed by FLOW-016, availability/provider location during controlled migration, new versions, unlink/disposition subject to policy.
- **Pilot gate:** P0 creates no new file/evidence write while FLOW-016 is absent; legacy local upload endpoints are disabled for LIVE-OPS and existing URLs are read-only migration input. Any P0 action for which FLOW mandates evidence—at minimum `revision_adjustment`, GUEST/external handover acceptance, recipient-absent delivery, configured mandatory acceptance photo, and required damage/shortage resolution—remains disabled until File Registry is available. Only FLOW-optional evidence may be omitted. P1 evidence/photo actions remain disabled until the File Registry gate passes.

## 3. Material Request state and action contract

### 3.1 Control state is not fulfillment state

`request_state` controls request authoring/approval only. Procurement and physical readiness are separate line-level facts. The UI may present a friendly progress summary, but MUST NOT collapse these facts into one writable status:

`requested`, `approved`, `ordered`, `supplier_confirmed`, `reserved`, `issued`, `in_transit`, `delivered`, `quantity_accepted`, `technical_accepted`, `site_available`, `consumed`, `returned`, `quarantined`, `cancelled_qty`, `remaining_qty`.

`fulfilled` is a read projection only when every line has zero actionable remainder under its approved partial/cancellation decisions. Invoice posting alone cannot set it.

### 3.2 Valid control transitions

The paths below are illustrative route bindings; the frozen contract is the command/action code and its semantics. Final paths MUST align with existing resource prefixes and MUST NOT imply a second persistence model.

| From | Action endpoint | To | Minimum permission | Rules |
|---|---|---|---|---|
| none | `POST /material-requests` | `draft` | `material_request.create` in project | Creates stable request/line IDs; no stock effect. |
| `draft` | `PATCH /material-requests/{id}/draft` | `draft` | requester or `material_request.edit_draft` in project | Only §2.2 draft fields; no raw state field. |
| `draft` | `POST /material-requests/{id}/submit` | `submitted` | `material_request.submit` in project | Validates item IDs, units, positive quantities, destination/source, needed date and required evidence. |
| `submitted` | `POST /material-requests/{id}/approve` | `approved` | `material_request.approve` in project | Records approver, approved quantities/limits/equivalents and partial-delivery rule. Approver cannot be inferred from client data. |
| `submitted` | `POST /material-requests/{id}/reject` | `rejected` | `material_request.approve` in project | Reason required; no stock/order effect. |
| `draft`/`submitted` | `POST /material-requests/{id}/cancel` | `cancelled` | requester before approval or `material_request.cancel` | Reason required. |
| `approved` | `POST /material-requests/{id}/cancel` | `cancelled` or partially cancelled lines | `material_request.cancel_approved` | Refused if it would erase executed facts; only remaining quantity is cancellable and history remains. Linked active reservations for cancelled remainder are released atomically. |

No other control transition is valid in the pilot. Reopen/return-for-correction is not silently inferred; it requires a future explicit contract amendment or a new draft/version.

### 3.3 Line facts and single-writer commands

Request lines hold derived facts only. Each physical/readiness fact has one canonical writer and is linked by `request_line_id`:

- warehouse `reserve`, `issue`, `return`, `quarantine`, and `consume` commands own their stock facts;
- the canonical destination-acceptance command (`delivery.accept` action semantics; route spelling is illustrative) is the **only** writer of delivery quantity acceptance. In P0 it atomically appends the canonical `receive` ledger line, and that line is itself the minimal FLOW-012 acceptance record; no second Delivery/Acceptance collection or request-line writer is created;
- every `receive` line has a stable `acceptance_id`/`acceptance_line_id`, recipient/acceptor, condition, accepted quantity, destination and dispatch reference. A tenant-scoped unique ledger index on `acceptance_line_id` prevents a second physical acceptance fact;
- the technical-acceptance command owns only technical acceptance and references that `receive`/acceptance line;
- order and supplier-confirmation facts are outside P0; when enabled later, their writer is the FLOW-012/038 order record, not the request aggregate.

No separate request-line, invoice, or Delivery/Acceptance endpoint may record the same dispatch/receipt/acceptance quantity. They may only project or reference the canonical ledger line. Route paths remain an implementation binding; command action codes and writer ownership are normative.

Each action MUST:

1. resolve tenant and project server-side;
2. make one Permission Service decision for the exact action/scope;
3. validate current facts and positive quantity against the remaining quantity;
4. claim idempotency inside the command transaction before the domain write;
5. execute domain, projection, and AuditEvent writes under the required atomic boundary;
6. return the prior result on an identical retry;
7. reject conflicting replay or invalid transition without partial writes.

### 3.4 Edit and quantity rules

- After submit, original requested quantities/specification/item/unit are immutable evidence.
- Approval records approved values separately; it does not overwrite requested values.
- Every partial action adds a quantity fact against one stable line.
- `remaining_qty` is derived, never client-authored.
- Delivered, accepted, technical-accepted, warehouse-received, site-available, and consumed quantities are distinct.
- Over-delivery, under-delivery, damage, rejection, or unknown item requires an exception/reason/evidence path; it is not folded into a success badge.
- A pending-mapping material may be received only into quarantine. Approval/reserve/issue/consume require a confirmed `item_id`.
- A generic `PUT /material-requests/{id}` MUST be draft-only or removed. It MUST reject `status`, approvals, actor fields, fulfillment quantities, and line fact fields.

### 3.5 Request AuditEvent

Create, submit, approve, reject, cancel, partial cancellation, order, delivery, acceptance, and exception decisions append a canonical AuditEvent containing request/line IDs, project, actor, effective RoleAssignments, action, before/after state or quantity delta, reason, correlation/idempotency keys, and related `file_id` evidence.

## 4. Warehouse movement contract

### 4.1 Required transaction envelope

Every committed `warehouse_transactions` record MUST contain:

- `id`, server-resolved tenant owner, `movement_type`, `status=posted`;
- `item_id` and canonical unit ID/code plus display snapshots;
- positive `qty`; direction is defined by movement type/source/destination, never negative client input;
- `source_type/source_id` and `destination_type/destination_id` as required by the movement;
- `warehouse_id` where the movement affects a warehouse;
- `project_id`, request/line, invoice allocation/line, `transit_origin_type`/`transit_origin_line_id`, `acceptance_id`/`acceptance_line_id`, repair/asset references when applicable;
- `value_status` plus currency and valuation provenance. `unit_value`/`total_value` are mandatory for final-valued movements; an acceptance before an invoice may carry `value_status=pending_invoice` with no final monetary value, never a fabricated zero;
- for outbound lines, server-computed `layer_allocations[{batch_id, qty, value_status, unit_value?}]`; final-valued allocations satisfy `total_value = Σ(qty × unit_value)`. Pending-valued layers omit monetary value and propagate `value_status=pending_invoice`; client-supplied outbound value is always rejected;
- actor/creator, `confirmed_by`/`confirmed_at` and acceptance reference when confirmation is required, source channel (`desktop`, `phone`, `qr`, `offline_sync`, `migration`), server ledger sequence/commit timestamp and optional original offline timestamp;
- tenant-scoped `idempotency_key`, `correlation_id`, reason, and related evidence `file_id` values;
- reversal/correction reference when compensating a prior movement.

Free-text name/unit may be stored only as immutable display/evidence snapshots beside `item_id`; they never drive identity or balance.

### 4.2 Movement types and effects

| Movement | Required source → destination | Physical/availability rule |
|---|---|---|
| `intake` | supplier/direct source → warehouse | Action/subtype of destination acceptance, not a separately postable stock-in command. `delivery.accept` appends exactly one accepted `receive` line with `receive_kind=supplier_intake`; `intake` itself creates no second line or layer. |
| `reserve` | warehouse available → reserved for request/project | Does not change physical on-hand; reduces available. |
| `release_reservation` | reservation → warehouse available | Restores available; cannot exceed active reservation. |
| `issue` | warehouse → person/vehicle/transport or accepted project destination | Atomically consumes reservation where present and reduces warehouse on-hand/value. A transport dispatch creates `in_transit` quantity/value and no project cost; an immediately accepted destination may recognize only its accepted quantity. |
| `receive` | transport/source → destination warehouse/project | Records confirmed receipt/acceptance. Project cost is recognized exactly once for destination-accepted quantity; unaccepted or missing remainder stays `in_transit/unresolved` and is neither available nor project-costed. |
| `return` | project/person/vehicle → quarantine at warehouse | Physical return enters quarantine, not available stock. |
| `quarantine` | current physical location → quarantine state | Excluded from available until an inspected resolution. |
| `release_quarantine` | quarantine → available/another object/supplier/write-off | Requires authorized inspection decision and evidence. |
| `consume` | accepted project/site stock → Work Package/SMR consumption | Allocates already recognized project cost to the applicable work scope; it never recognizes that cost a second time. |
| `transfer` | warehouse/project/vehicle → warehouse/project/vehicle | Source decrement and accepted destination increment are correlated; in-transit remains distinct until receipt. |
| `reversal/correction` | compensating reference | Reverses/corrects without rewriting original history. |
| `opening_balance` | approved legacy source → canonical location/state/layer | Migration-only under the W0-03E `plan_token`/run ledger. Seeds canonical quantity/value provenance without writing a batch directly; never used by normal application commands. |
| `transit_discrepancy` | one warehouse/supplier transit origin → its unresolved investigation | Non-moving ledger fact recording unresolved quantity, reporter, reason, status and available evidence; it cannot make stock available or recognize project cost. Damage classification and its mandatory evidence occur only in the later resolution action. |
| `valuation_adjustment` | pending-valued acceptance/batch → final allocated invoice value | Changes value only, never quantity; references exactly one acceptance, originating batch and invoice allocation, is idempotent/append-only, and finalizes derived downstream allocation values without rewriting their ledger rows. |
| `supplier_delivery_origin` | supplier allocation/dispatch → in-transit origin | Non-acceptance source fact with stable line ID, tenant-scoped `supplier_source_line_key`, and expected quantity/value. Exactly one origin exists for each linked supplier source line (approved order line, delivery-note line, or invoice allocation). It may be created before delivery or atomically by the first acceptance command; every later order/invoice/acceptance links to that existing origin and MUST NOT create a second one. Quantity/value differences use an authorized, audited correction against the same origin. It never makes stock available or recognizes project cost. |

The movement vocabulary also includes:

- `revision_adjustment`: explicit correction after stocktake, with reason, responsible person, AuditEvent, mandatory protocol/photo `file_id`, and DQ/Approval above the configured significance threshold; it fails closed while File Registry evidence is unavailable;
- `return_to_supplier`: removes the traced quantity/value toward the supplier;
- `write_off`: scrap/loss/theft disposition with its own permission and required approval.

`release_quarantine` destinations are available stock, another object, return to supplier, or write-off. `repair` is not a material destination. Supplier → warehouse/project on-hand arises only from the sole destination-acceptance command appending the accepted `receive` line; `intake` is its subtype/UX action and cannot be posted in addition.

Direct delivery to a project follows FLOW-009 Path B and MUST NOT also be costed as warehouse issue. Under owner decision F-09=B, both Path A warehouse dispatches and Path B direct deliveries recognize project cost only for quantity accepted at the destination. Dispatch to transport retains the traced quantity/value as `in_transit`; missing, rejected, or otherwise unaccepted remainder stays `in_transit/unresolved` until a canonical acceptance, return, `revision_adjustment`, or authorized `write_off` resolves it. `consume` only allocates accepted project cost to a Work Package/SMR and never recognizes it again. One physical/value quantity is recognized once.

An outbound `transfer` or `return` from a project de-recognizes that project's unconsumed cost for the dispatched quantity at the original layer values in the same transaction; the value moves to the dispatch-scoped `in_transit` location or to quarantine. Already-consumed quantity cannot transfer/return without an authorized reversal/correction. Destination acceptance recognizes only the accepted quantity/value for the destination project.

### 4.3 Atomicity, concurrency, and idempotency

For the write-enabled pilot, one Mongo transaction (real replica-set semantics) MUST cover:

1. idempotency claim/result state;
2. conditional invariant check for the relevant item/location/reservation;
3. canonical transaction append;
4. synchronous batch/FIFO projection update when applicable;
5. request/project projection update when stored;
6. canonical AuditEvent append.

If any required write fails, the command aborts. A successful domain write without its AuditEvent is not a successful command.

The transaction precondition includes session-aware `begin_idempotent`, `record_event`, and `complete_idempotent`; bounded retry on `TransientTransactionError` and audit-sequence collision after re-reading the chain head; and defined recovery for an idempotency record left `started` by a crash. Replica-set transaction support is mandatory in staging and pilot production.

Concurrent commands for the same item/location MUST serialize or use a conditional version/quantity guard. Exactly one concurrent last-unit normal issue may succeed. Normal issue/consume/transfer MUST NOT make available stock negative. A negative balance may arise only from explicit `revision_adjustment` with `warehouse.correct`, reason, alarm, AuditEvent, and required DQ/Approval; there is no silent bypass. The implementation may use a rebuildable balance/version projection as a guard, but it is not a new source of truth.

### 4.4 Stock projection

The stock key is `(item_id, location_type, location_id, state)`. `location_type` is one of `warehouse`, `project`, `subproject`, `person`, `vehicle`, or `in_transit`; `state` is `available`, `reserved`, `quarantine`, or `unresolved`. For `in_transit`, `location_id` is the stable `transit_origin_line_id`: a warehouse `issue`/`transfer` line or a canonical `supplier_delivery_origin`/source-allocation line, never a pooled item/vehicle bucket. A real place is represented once: a project-type warehouse and a bare `project_id` cannot be parallel identities for the same place. Quarantine is state at a real location, not a separate location.

For item `i` at location `l`:

- `physical_on_hand` derives from the complete posted movement ledger;
- `reserved` derives from active reserve/release/issue facts;
- `quarantined` derives from unresolved quarantine facts;
- `available = physical_on_hand - reserved - quarantined`;
- in-transit, delivered-unaccepted, accepted/site-available, and consumed are separate projections.
- `in_transit/unresolved` retains the original `layer_allocations` and value or, for a supplier origin that has no stock layer yet, its allocated quantity/value; it is unavailable for reserve/issue/consume and contributes no project cost until canonical destination acceptance. Resolution cannot silently erase quantity or value.
- For each transit origin, `Σ(accepted + returned_to_source + written_off + corrected) ≤ origin_qty`; every acceptance/resolution references that origin. A partial acceptance atomically appends the accepted `receive` line and a `transit_discrepancy` for the unresolved remainder with status `under_investigation`. Supplier-path and warehouse-path shortages use the same rule. That remainder is not delivered/fulfilled and cannot trigger automatic reorder before FLOW-012 resolution.
- In P0, partial acceptance never holds accepted good quantity hostage to unavailable evidence. The remainder is initially `under_investigation` without classifying it as damaged. A later resolution may classify damage/shortage; if that classification requires FLOW evidence, the resolution fails closed until File Registry evidence is available.
- Accepted quantity with `value_status=pending_invoice` is in the project's cost scope but is never reported as zero-valued. Monetary totals/dashboard cards MUST show an explicit incomplete/pending-valuation state until the correlated `valuation_adjustment` finalizes the value.

The calculation MUST use full aggregation or a verified checkpoint plus every later transaction. A checkpoint stores last transaction/order/hash and can be rebuilt/reconciled from the ledger. Pagination limits may limit a response page, never the calculation.

### 4.5 FIFO/batch projection and reconciliation

- Exactly two events originate batch layers: an accepted `receive` line and a migration-only `opening_balance` line. Transfer/return carry existing layers; the `intake` action cannot create an additional layer. FIFO order is the server ledger sequence/commit order, never client/offline time.
- Issue/transfer/consume/write-off/return-to-supplier consumes layers by the frozen FIFO rule under the same concurrency boundary and records the chosen allocations on the ledger line.
- Return starts in quarantine and carries the original issue's lot/value allocations proportionally. Release restores those traced allocations; value changes require a correction movement rather than an invented valuation rule.
- Partial destination acceptance splits the transit origin's recorded layer/value allocations proportionally between accepted and unresolved quantities, using deterministic currency/quantity rounding with any remainder assigned to the final allocation. Both sides preserve the same original provenance.
- Outbound allocations from a pending-valued layer record `batch_id`, quantity and `value_status=pending_invoice` without a monetary value. The one later `valuation_adjustment` finalizes the originating acceptance/batch value; every downstream allocation/project/inventory projection derives its proportional value from that finalized batch without rewriting historical ledger lines. Pending state propagates through transfer/issue/return until finalized.
- Sum of available batch remaining quantities/value by item/location MUST equal the corresponding canonical transaction projection.
- Every batch row references its source movement(s); every projection mutation has a ledger cause.
- Rebuild from ledger into a disposable projection replays recorded allocations and compares; it never re-runs FIFO selection.
- Any quantity/value/provenance mismatch blocks cutover and write-enabled pilot.

### 4.6 Invoice double-post protection

Invoice posting uses a tenant-scoped idempotency key and a unique business guard over the invoice/version/posting action. Every invoice line has typed allocations with valid FLOW-020 owners/destinations, `Σ allocation.qty == invoice_line.qty`, and `Σ allocation.value == invoice_line.value` under deterministic currency rounding; otherwise posting is refused.

- Material/consumable allocations record valuation-source facts and link through `invoice_allocation_id`; they do not write acceptance. On-hand/project cost arises only from the canonical warehouse/destination acceptance command.
- Asset/tool allocations route to the FLOW-011 asset/intake owner; service, overhead and logistics allocations route to their respective FLOW owners. They MUST NOT be forced into warehouse stock.
- If the invoice allocation exists first, later acceptance uses its server-side allocated **unit** value. If acceptance occurs first, it records quantity with `value_status=pending_invoice`; the later invoice command appends exactly one correlated `valuation_adjustment` per acceptance line/batch. Final accepted project/inventory value equals `accepted_qty × server-derived allocation unit_value` under the frozen rounding rule. Only when the full allocation quantity is accepted does accepted value equal the full allocation value. Unaccepted quantity/value remains on the supplier delivery origin as `unresolved` with `transit_discrepancy`; it never becomes project/inventory cost. No client-authored or fabricated-zero valuation is allowed.
- Invoice allocation validation, its valuation facts/adjustments, applicable projections, idempotency result, and AuditEvent are one atomic command. A second identical request returns the first result; a different payload for the same invoice/version is rejected. Posting an invoice does not mark the request fulfilled.

## 5. Warehouse identity and `main` reconciliation

### 5.1 Canonical behavior after freeze

- Normal create/update accepts canonical types from the warehouse model and uses `central`, never `main`.
- Stock/intake code receives an explicit resolved `warehouse_id`; it does not find or create a warehouse by hard-coded type/name.
- UI renders `warehouse.name` as the main label and may show `code`/ID secondarily.
- Tenant-scoped uniqueness and archive rules are validated before write.

### 5.2 Migration sequence (future task only)

1. **Read-only inventory:** enumerate every `central`/`main` warehouse, aliases/codes/names, associations, movements, reservations, quarantine, batches, requests, and references.
2. **Dry-run map:** classify each legacy `main` as exactly one `central`, create-new-canonical candidate, duplicate, unknown, or ambiguous.
3. **STOP conditions:** more than one plausible target, incompatible association/location, unknown owner, inconsistent stock/value, orphan reference, duplicate code/ID, or incomplete inventory.
4. **Backup:** produce verified database backup/snapshot, manifest, counts, hashes, timestamps, baseline SHA/schema/config, and restore proof on a disposable target.
5. **Approved mapping:** only unambiguous, reviewed rows receive a signed/hashed mapping plan. No name-only guessing.
6. **Migration:** reuse the FLOW-032/W0-03E location merge/attach runner (`plan_token`, `md_legacy_refs`, per-tenant lock, run ledger and rollback state). There is no second migration runner. Ledger rows keep their original `warehouse_id`; reads/projections resolve the approved redirect. Preserve legacy refs/aliases. Canonical cutover stock is established only by migration-channel `opening_balance` ledger lines per item × location × state × valuation layer, with approved mapping and legacy-row/batch provenance; projections are never seeded directly.
   Legacy auto-created `main` rows may have null `code`; index dry-run MUST tolerate them until approved merge/attach and MUST NOT invent a code.
7. **Validation:** counts, referential integrity, complete ledger balances/value, batches, reservations, quarantine, request links, UI labels, tenant/project isolation, and AuditEvent chain.
8. **Cutover:** application writers reject `main`; reads may resolve the approved legacy bridge until retirement.
9. **Rollback:** restore the backup or apply a proven reverse mapping from the immutable run ledger. Migration `opening_balance` lines are reversed/disabled only through the same run ledger and verified rollback anchor; projections are rebuilt rather than edited. Rollback must restore references, writers, projections, and configuration together.

No step above is executed by TASK 4.

## 6. Assets, custody, QR, and repair

### 6.1 Two-phase handover

1. The `asset.handover.create` command creates one `asset_custody` record in `PENDING_ACCEPTANCE` with current custodian, pending recipient, source/target location, expected-return rule/date where applicable, condition/kit snapshot, reason, evidence, idempotency, and correlation. Any route shown here is illustrative; `handover_id == asset_custody.id` and no `asset_handovers` collection is created.
2. While pending, the prior accepted custodian and responsibility remain authoritative. The asset's accepted location/status is not silently replaced.
3. Only the named recipient, object responsible person/official substitute, or approved external-recipient mechanism can execute `asset.handover.accept`.
4. Acceptance atomically closes the previous accepted custody, creates/activates the new custody, updates the accepted location projection, and appends AuditEvent.
5. `asset.handover.decline` or `asset.handover.problem` records reason/evidence and leaves/restores the prior authoritative custodian. Nothing becomes unassigned.
6. Expiry creates reminder/escalation; it never auto-accepts.

There MUST be a tenant-scoped database invariant preventing more than one active accepted custody per asset and more than one live pending handover for the same asset unless a later FLOW decision explicitly allows it.

### 6.2 Prohibited bypasses

- Remove/disable open `take` and `give` semantics that let any logged-in user replace responsibility.
- Generic asset updates cannot alter custody/location as a substitute for handover.
- `drop` to a project requires the project responsible person or substitute to accept.
- Written-off, lost, stolen, quarantined, or in-repair assets reject incompatible move/handover commands.
- QR is only an input method. It calls the same permission-checked, idempotent canonical commands and cannot choose another tenant/project/recipient outside the authorized scope.

### 6.3 Expected return and status/location

- Status and location are separate.
- Custody/handover carries `expected_return_at` or a documented return rule when required by FLOW-011/012; external/GUEST custody requires the mandated identity/contact/company/return details.
- Overdue is a derived alert, not a manually writable status.
- `PENDING_ACCEPTANCE` is transfer state, not asset lifecycle status.

### 6.4 Repair lifecycle

- `asset.repair.open` opens one repair record and initiates a two-phase handover to the service/GUEST acceptance mechanism; route spelling follows the existing asset-unit/repair resource and is not normative.
- Return/completion closes that same repair record, records provider/work/cost/warranty/evidence, and creates `PENDING_ACCEPTANCE` custody to the destination. Accepted location/responsibility changes only on recipient acceptance.
- `move action=repair` without a repair record is forbidden.
- Custody during repair follows the applicable accepted service/warehouse handover rule; the responsible party never disappears.
- Write-off/lost/stolen decisions require the FLOW-011 permission/approval and AuditEvent; normal hard-delete is forbidden. Above the tenant-configured expensive-asset threshold, initiator and approver MUST be two different authorized people. Write-off fails closed until the threshold/approval policy is configured and can never be executed by QR channel alone.
- Legacy asset statuses are deterministically mapped to FLOW-011 using status, location, and accepted custody; ambiguous `in_use` or other rows are `STOP`. The UX color/overdue indicator is derived and never stored as status.

## 7. Permission and AuditEvent contract

### 7.1 Permission decision

Every consequential command calls Permission Service in `enforce` mode with:

- authenticated principal and server-resolved tenant;
- exact action code;
- project/module/object/sensitivity scope;
- target object loaded inside that tenant;
- current effective RoleAssignment revisions.

For existing-object commands, the service first loads the target within the server-resolved tenant, derives `(scope_type, scope_id)` from the stored target, then evaluates the exact action. Scope is never trusted from the request body or inferred only from a route path. Create commands evaluate project scope first and validate any body `project_id` against it. The pilot uses project scope until documented project→subobject containment is implemented.

The most restrictive tenant/project/module/action rule wins. Missing assignment, unknown action, mismatched project, foreign ID, expired/revoked assignment, unresolved scope, or permission mode other than `enforce` is deny-by-default/fail-closed. Subscription/module entitlement is not a substitute for action permission.

Minimum action families include request create/edit/submit/approve/cancel, supplier-delivery origin and destination `delivery.accept`, warehouse intake/reserve/issue/receive/return/quarantine/consume/correct/opening-balance/value-adjustment, asset handover/accept/decline/repair/write-off, warehouse administration, File Registry link/upload/version/unlink, and migration inventory/dry-run/execute/rollback.

Denials are auditable where FLOW-002/040 requires them without leaking forbidden object existence.

### 7.2 Canonical AuditEvent

Every consequential success, denial, validation stop, idempotent replay, exception decision, migration phase, reconciliation result, and rollback result uses the canonical `backend/app/audit` envelope/store.

Minimum envelope data:

- event ID, server-resolved tenant, source FLOW/module;
- actor type/ID and effective RoleAssignment IDs/revisions;
- action/outcome/reason code;
- object type/ID and project/scope;
- safe before/after state or quantity/value delta;
- `correlation_id` and `idempotency_key`;
- server timestamp and allowed original/offline timestamp;
- related request/transaction/custody/repair/file/evidence IDs;
- retention/visibility class and hash-chain fields.

Large payloads and originals remain in domain/File Registry storage; AuditEvent references IDs/checksums. Legacy `log_audit`/`audit_logs` cannot be the only audit path for LIVE-OPS writes.

## 8. File contract

- Invoice, receipt, delivery, acceptance, damage, custody, condition, and repair evidence is linked by canonical `file_id`.
- Upload creates/uses a File Registry record with tenant, checksum, version, provider/account/object identity, availability, uploader/time, sensitivity, and relations.
- Business entities store `file_id` relations, not `/app/backend/uploads/...` paths or permanent provider URLs.
- Preview/download uses short-lived authorized operations and rechecks tenant/project/sensitivity scope.
- One original can have multiple relations without copies. Unlink removes one relation, not the original.
- Approved/signed/financial evidence is not overwritten or normally deleted; a new version preserves lineage.
- Storage/provider migration preserves `file_id`, versions, relations, checksum, and AuditEvent. Missing/changed original creates an alarm/data-quality issue and AuditEvent.
- While File Registry is unavailable, every action for which FLOW mandates evidence fails closed. This includes stocktake correction protocol/photo, GUEST/external acceptance proof, recipient-absent delivery evidence, configured mandatory acceptance photos, and required damage/shortage evidence. Only optional evidence may be omitted, and legacy paths/URLs cannot satisfy the gate.
- TASK 4 performs no original upload, move, overwrite, or delete.

## 9. Migration and reconciliation contract

### 9.1 Read-only inventory and dry-run

The future migration tool MUST first produce a read-only, per-tenant report containing:

- all warehouses and `central`/`main` candidates;
- all `warehouse_transactions`, batches and computed quantities/value, plus legacy `project_material_ops`, `material_consumption_log`, and derived `material_entries`;
- free-text material variants, units, supplier aliases, current `item_id` links and candidate Master items;
- requests/invoice lines without stable item, project, warehouse, value, or file relation;
- duplicate/unknown/orphan assets, `asset_movements`, custody, repairs, QR and files;
- deterministic legacy asset-status mapping using accepted custody/location; ambiguous rows are `STOP`;
- tenant/project/action and audit coverage gaps;
- counts, hashes, collisions, proposed mapping, risk, and reason per row.

Dry-run writes no business collection. Its report is versioned and hashable. Re-running unchanged input produces the same plan and counts.

### 9.2 Free-text → `item_id`

- Exact confirmed legacy refs, confirmed supplier aliases, and stable identifiers may produce a deterministic mapping.
- Normalized-name similarity, AI confidence, or free-text equality alone may only propose a candidate.
- Duplicate candidates, unit/conversion conflict, different specifications, or no confirmed item are `UNKNOWN/AMBIGUOUS` and block that row/cutover.
- A human with Master Data permission confirms mappings; the decision and evidence are audited.
- Original text remains as evidence/display snapshot after mapping.
- A received unknown item is quarantined against `md_pending_mapping`; confirmed mapping appends an audited correction/link. It cannot be available or costed before confirmation.

### 9.3 Preconditions for any future cutover

- approved mapping with zero unresolved blocking rows;
- Permission Service and AuditEvent coverage gates green;
- real-Mongo transaction/concurrency evidence green;
- verified backup and successful disposable restore;
- stock quantity/value and batch reconciliation green;
- File Registry predecessor gate green before any mandatory-evidence command or P1 evidence/photo write; P0 may omit only FLOW-optional evidence;
- tenant/project isolation green;
- verified unique indexes exist in every pilot tenant database for AuditEvent `(tenant_id, sequence)`, `event_id`, audit idempotency keys, command idempotency, `acceptance_line_id`, supplier-origin `(tenant_id, supplier_source_line_key)`, warehouse identity, and active/pending custody;
- signed run plan, per-tenant lock, idempotency, checkpoints, abort/rollback criteria;
- owner approval for production mutation in a separate task.

### 9.4 Rollback

Rollback is designed and proven before execute. It restores the exact pre-cutover references/configuration/projections from a verified anchor without deleting immutable audit/ledger evidence. The migration run ledger records every step, checkpoint, validation, failure, and rollback result. Any mismatch after rollback is a failed gate.

## 10. Required tests and acceptance gates

No write-enabled pilot may pass with a required skip. Tests use disposable data and no production credentials/customer originals.

| Gate | Required evidence |
|---|---|
| Real Mongo | Replica-set transaction semantics; committed/aborted domain + projection + AuditEvent behavior. |
| Tenant A/B | Colliding IDs in both storage orders; no cross-tenant read/write/enrichment/file/audit leak. |
| Project/action denial | Each critical endpoint denies missing/wrong/revoked RoleAssignment and emits the required safe denial event. |
| Permission enforce mode | Every LIVE-OPS writer fails closed outside `enforce`; the denial is audited without leaking object existence. |
| Request state machine | Every valid transition succeeds once; all invalid/raw-status/direct-URL transitions fail without partial writes. |
| Partial quantities | Multiple partial deliveries/acceptances retain remainder and never make invoice-post equal fulfillment. |
| F-09=B acceptance cost | For both warehouse dispatch and supplier direct-delivery origins: 10 expected/sent, 8 accepted, 2 missing means project cost/site-available quantity and value are exactly the accepted 8; quantity/value 2 remains traced `in_transit/unresolved`, is not consumable, and resolves only through an audited canonical action without double cost. Run invoice-before-accept and accept-before-invoice supplier cases. |
| Transit-origin conservation | Every receive/resolution references one warehouse-dispatch or supplier-delivery origin; accepted + returned-to-source + written-off + corrected never exceeds origin quantity, and partial acceptance creates a separate unresolved discrepancy fact. |
| Project-to-project F-09 | Project A dispatches 10 unconsumed units, project B accepts 8, 2 unresolved: A de-recognizes 10 at original layers, B recognizes 8, and 2 remains in the dispatch-scoped in-transit value without double counting. |
| Retry/idempotency | Same key/same payload replays original result; same key/different payload conflicts; offline retries are safe. |
| Double invoice-post | Concurrent/repeated posting produces exactly one invoice-allocation/valuation effect, applicable projection effect, and AuditEvent; it never creates a second acceptance or stock layer. |
| Concurrent last unit | Two simultaneous issues for the last unit: exactly one succeeds; available never negative. |
| Cross-item audit concurrency | Concurrent commands for different items in one tenant complete/retry without lost, duplicate, or unaudited events and preserve the hash chain. |
| FIFO concurrency | Concurrent consumes preserve layer ordering, quantity/value, provenance, and ledger parity. |
| Value preservation | Intake → reserve → issue/consume → return/quarantine/resolution conserves quantity/value and D-04 cost exactly once. |
| Server-derived outbound value | Client value is rejected; recorded FIFO allocations and totals replay exactly without re-running FIFO. |
| Invoice allocation | Every typed allocation routes to its FLOW owner; splits sum exactly to invoiced quantity **and value** under the frozen rounding rule; missing/invalid destination or either sum mismatch is refused. |
| Acceptance/invoice order | Invoice-before-accept uses allocated server unit value; accept-before-invoice records pending valuation then exactly one idempotent value-only adjustment. Both orders converge for the same accepted quantity. Also prove accept → issue/transfer → invoice propagates final batch value to every downstream projection without rewriting history. |
| Supplier-origin uniqueness | Accept-before-invoice and invoice-before-accept each produce exactly one `supplier_delivery_origin` for the linked tenant-scoped supplier source line; later documents and acceptances link to it, and concurrent creation cannot create a duplicate origin or accept/cost the delivery twice. |
| >1000 movements | Full stock/project/dashboard result remains correct beyond prior 100/500/1000 caps and across checkpoints/pages. |
| Quarantine | Return is unavailable until authorized inspection resolution; every branch is audited. |
| Revision/correction | Stocktake variance creates an authorized correction, alarm and AuditEvent; normal movements cannot silently go negative. |
| Pending mapping | Unknown material can be received only into quarantine and cannot be issued/costed before audited Master Data confirmation. |
| Opening balance | Migration-only opening balances reproduce approved legacy quantity/value/layers with provenance and rollback; no direct batch seed is possible. |
| Custody | Correct recipient accept, decline/problem, wrong recipient, expiry, concurrent handover, prior-custodian restoration, unique active custody. |
| Direct URL/QR bypass | Hidden button or forged endpoint/QR cannot bypass tenant/project/action/state rules. |
| Repair | Open, in-repair, evidence/cost, completion/return through pending handover, no responsibility change before acceptance, invalid direct move, and write-off separation-of-duties paths. |
| AuditEvent completeness | One correlated append-only event per required success/denial/replay; actor, role, object, before/after, evidence and hash chain verified. |
| File Registry | Stable `file_id`, scope checks, checksum/version, multi-relation, missing/changed original alarm, no authoritative path/URL. |
| Mandatory evidence fail-closed | Revision, GUEST handover, recipient-absent delivery, configured acceptance photo, and required damage/shortage **resolution** cannot execute while File Registry/evidence is unavailable; partial acceptance still accepts good quantity and leaves the remainder unclassified `under_investigation`. |
| Migration dry-run | Deterministic counts/hash; duplicate/unknown/ambiguous mappings stop; no business mutation. |
| Backup/restore | Verified backup restores disposable DB/config/files registry relations and matches manifest/counts/hashes. |
| Rollback | Forced failure at every checkpoint restores exact pre-cutover functional state; run/audit evidence remains. |
| Desktop + phone E2E | Admin/Owner, Warehousekeeper, Technician/recipient: happy paths, denial, offline retry, loading/empty/error/stale/incomplete states. |
| Legacy writer retirement | Static scan of every write to the scoped collections finds only canonical command services; every route in §12.1 has a runtime denial/redirect/read-only proof before cutover. |
| Required unique indexes | Every pilot tenant DB proves the required audit, idempotency, acceptance provenance, supplier-origin `(tenant_id, supplier_source_line_key)`, warehouse identity, and custody unique indexes before writes are enabled. |

Release evidence MUST state exact SHA, environment, commands, counts, skips, fixtures, Mongo topology, and artifacts. Static guards are reported as static only; they do not replace runtime tests.

## 11. Impacted implementation areas (for later tasks)

This draft changes no code. A future implementation plan is expected to touch or replace behavior in these areas:

- `backend/app/routes/procurement.py`
- `backend/app/routes/warehouses.py`
- `backend/app/models/warehouse.py`
- `backend/app/routes/warehouse_batches.py`
- `backend/app/services/fifo_service.py`
- `backend/app/routes/materials_baseline.py`
- `backend/app/routes/material_smr.py`
- `backend/app/routes/assets_units.py`
- `backend/app/routes/assets_custody.py`
- `backend/app/routes/assets_repairs.py`
- `backend/app/routes/assets_qr.py`
- `backend/app/permissions/*`
- `backend/app/audit/*`
- `backend/app/master_data/*`
- File Registry/provider implementation selected under FLOW-016;
- inventory/reconciliation/migration scripts and rollback run ledger;
- `frontend/src/pages/ProcurementPage.js`
- `frontend/src/pages/InventoryDashboardPage.js`
- `frontend/src/pages/WarehousesPage.js`
- `frontend/src/components/ProjectMaterialLedger.js`
- `frontend/src/components/warehouse/*`
- `frontend/src/pages/AssetsUnitsPage.js`
- `frontend/src/pages/AssetUnitDetailPage.js`
- `frontend/src/pages/MyToolsPage.js`
- `frontend/src/pages/ScanLandingPage.js`
- `frontend/src/pages/TechnicianDashboard.js`
- existing and new backend/frontend/E2E test suites for every §10 gate.

## 12. Unresolved technical questions for independent review

These do not request a new business rule and are not `OWNER_DECISION` items:

1. **Atomic guard implementation:** select the exact Mongo transaction + conditional version/balance mechanism that proves §4.3 without creating a third source of truth.
2. **File Registry predecessor:** define and deliver the FLOW-016 implementation/API in its Wave-0 gate. The reviewed merged `main` has no File Registry; LIVE-OPS must not bind to local invoice upload behavior.
3. **Unit migration:** specify the deterministic mapping from legacy unit strings to FLOW-032 canonical unit IDs/conversions and the STOP criteria for incompatible units.
4. **Projection checkpoint schema:** define checkpoint/order/hash fields and replay procedure for stock/dashboard and FIFO projections.
5. **Index rollout plan:** dry-run and prove the frozen unique indexes for AuditEvent `(tenant_id, sequence)`/`event_id`, audit and command idempotency, `acceptance_line_id`, supplier-origin `(tenant_id, supplier_source_line_key)`, warehouse code/type constraints, transaction provenance, and active/pending custody without rejecting valid legacy data before reconciliation. Index presence is a precondition, not an optional implementation choice.
6. **Legacy route retirement:** produce a route-by-route compatibility/disable plan plus collection-write static scan so no old writer remains after cutover, covering the complete §12.1 inventory.

### 12.1 Complete known legacy route retirement inventory at the reviewed baseline

- `POST /material-requests`
- `POST /project-consumption`
- `POST /warehouse-return`
- `POST /warehouse-issue`
- `POST /warehouse/batches`
- `POST /warehouse/consume`
- `PUT /warehouse/batches/{id}/block`
- `POST /material-entries/sync/{project_id}`
- `PUT /warehouses/{id}` type change
- `DELETE /warehouses/{id}` archive with incomplete stock guard
- `DELETE /assets/units/{id}` hard-delete path
- `POST /assets/custody/give`
- `POST /assets/custody/{id}/accept`
- `POST /assets/custody/{id}/decline`
- `POST /assets/custody/{id}/release`
- `PUT /assets/units/{id}` raw status/location path
- `POST /assets/units/{id}/move`
- `POST /assets/units/{id}/repair/send`
- `POST /assets/units/{id}/repair/return`
- `POST /assets/intake/{id}/approve`
- `POST /assets/intake/approve-bulk`
- `POST /supplier-invoices/{id}/upload-file`
- `POST /supplier-invoices`
- `PUT /supplier-invoices/{id}` raw status path
- `POST /supplier-invoices/{id}/post-to-warehouse`
- `POST /material-requests/from-offer/{offer_id}`
- `POST /material-requests/{id}/submit`
- `PUT /material-requests/{id}` raw status/line path
- `DELETE /material-requests/{id}` delete path
- `POST /technician/material-request`
- `POST /technician/photo-invoice`
- `POST /execution-packages/recompute-material/{project_id}` legacy material-cost projection writer
- `POST /dev/reset-warehouses`
- `POST /warehouses`
- `POST /assets/units`

This list is complete for known baseline routes but cannot be the sole proof. Before cutover, a static scan of all `insert`, `update`, `delete`, `replace`, and bulk writes to `warehouse_transactions`, `warehouse_batches`, `material_entries`, `project_material_ops`, `material_consumption_log`, `material_requests`, `supplier_invoices`, `warehouses`, `asset_units`, `asset_custody`, `asset_movements`, `asset_repairs`, and material fields of `execution_packages` MUST find only canonical command/projection services. Every retired route also requires runtime denial, canonical redirect, or read-only evidence.

### 12.2 Resolved owner decision — F-09 = B

**OD-01 — project-cost recognition for warehouse → transport → object with loss in transit: RESOLVED, Option B.**

Smallest counterexample: 10 bags leave the central warehouse for project X; 8 are accepted on site and 2 are missing at unload under investigation.

- **Frozen rule:** project X carries cost 8 only on site acceptance; quantity/value 2 remains `in_transit/unresolved` under investigation until canonical resolution. Dispatch alone creates no project cost. `consume` only allocates already-recognized accepted project material to SMR/Work Package and never recognizes cost again.

This rule is the explicit owner decision recorded for TASK 4. There is no remaining business choice in this contract candidate. The exact implementation mechanism for the `in_transit/unresolved` projection remains a bounded technical design item and cannot introduce another ledger or writer.

## 13. Independent CLAUDE freeze review checklist

Claude must review this draft against the exact merged-main baseline and authoritative FLOWs before reading CODEX conclusions, then report:

- [ ] every owner decision in §0.1 is present without reinterpretation;
- [ ] F-09=B is enforced end to end: dispatch creates no project cost, destination acceptance costs only accepted quantity, unresolved remainder keeps traced layers/value, and consume cannot cost twice;
- [ ] every entity has one model/ID, allowed writer, projection, forbidden writer, and immutable/mutable boundary;
- [ ] request control states do not collapse line fulfillment facts;
- [ ] action endpoints close the current raw-status/permission bypass;
- [ ] partial quantities and invoice/request semantics match FLOW-012/020;
- [ ] `warehouse_transactions` is the only stock source and batches are replayable FIFO/cost projection;
- [ ] movement envelope preserves identity, quantity, unit and value;
- [ ] atomicity/concurrency/idempotency prevent double post and negative stock;
- [ ] stock calculations have no hidden truncation;
- [ ] `central`/`main` inventory, STOP, backup, validation and rollback rules are complete;
- [ ] custody preserves prior responsibility until acceptance and on decline/problem;
- [ ] QR and direct URLs cannot bypass canonical actions;
- [ ] repair and expected-return behavior matches FLOW-011/012;
- [ ] project/action Permission Service and tenant isolation are deny-by-default;
- [ ] all consequential actions use canonical append-only AuditEvent with correlation/idempotency;
- [ ] invoices/evidence use File Registry `file_id`, not authoritative paths/URLs;
- [ ] free-text material mapping never invents a Master item;
- [ ] migration/dry-run/rollback remain non-production in TASK 4;
- [ ] §10 covers every audit finding and owner gate with real-Mongo/runtime evidence;
- [ ] no third stock model, new business rule, implementation authorization, or unsupported runtime PASS was introduced;
- [ ] any proposed correction is bounded and cites exact section, FLOW, code evidence, and a plain-language counterexample.

## 14. Freeze gate

This document is **CONTRACT FREEZE READY** and authorizes no implementation. The freeze was reached only after:

1. CLAUDE independent freeze review of this exact candidate/version/hash is published;
2. CODEX verifies every finding against the authoritative FLOWs, owner decisions, and exact merged-main baseline;
3. any necessary correction loop is bounded, re-hashed, and independently acknowledged;
4. the resulting contract has no freeze blocker or unresolved business decision.

`OWNER_DECISION: NONE`. `CONTRACT_FREEZE_READY` freezes this contract text only; implementation, migration execution, merge, deploy, production activation, and customer-original mutation remain unauthorized and require later tasks plus their stated gates.
