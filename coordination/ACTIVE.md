# BEG_WORK — active implementation assignment

Status: W0-06B/C01 REVIEWING — FINAL EXACT-HEAD HANDOFF OBSERVED
Human-Summary-BG: Продължаваме File Registry към реалните storage providers. Първо затваряме четирите доказани дефекта от основата; после изграждаме безопасно свързване, тест за активиране и проверки дали оригиналите са налични и непроменени.
Current-Agent: CODEX
Current-State: REVIEW
Claude-State: HANDOFF_READY
Codex-State: REVIEWING
Pipeline-Step: REVIEW
Transition-Phase: OBSERVED
Now: Claude публикува финален HANDOFF за W0-06B/C01 на 888d32e2abf029c5740bc6d7d9484a0cf037809c и сесията приключи. Draft PR #46 head съвпада и е стабилен; Codex започва независим whole-package review и real-Mongo gate. Verdict още няма.
Next-Agent: GPT
Relay-State: NO_RELAY_NEEDED
Relay-From: NONE
Relay-To: NONE
Krum-Action: NONE (W0-06B start and exact base approved)
Dispatch-State: NONE (Claude final HANDOFF observed; never resend)
Dispatch-Run: https://claude.ai/code/session_01CC1BoxYWrVaLdT85riupTG
Dispatch-Observed-At: 2026-10-04T22:01:04Z
Task-ID: W0-06B
Cycle-ID: C01
Base-branch: codex/w0-06a-file-registry-foundation (technical integration base only; PR #44 remains Draft/CHANGES_REQUESTED)
Base-SHA: 9040fc1d4b40d5376cc8912ba316a206c02d207b
Implementation-branch: codex/w0-06b-storage-provider-foundation (created at exact Base-SHA)
PR-URL: https://github.com/krumingo/BEG_Worck/pull/46 (Draft, base main; currently base-only/incomplete)
PR-Head: 888d32e2abf029c5740bc6d7d9484a0cf037809c
Merge-SHA: NONE
Main-Head: 79af297612f57c055bb7caef3f0c48493800d1b6
Issue: https://github.com/krumingo/BEG_Worck/issues/45
HANDOFF-URL: https://github.com/krumingo/BEG_Worck/pull/46#issuecomment-5985467082
Review: coordination/REVIEWS/W0-06A.md — predecessor C01 independent CHANGES_REQUESTED on exact PR #44 head 9040fc1d4b40d5376cc8912ba316a206c02d207b; no W0-06B review.
Final-Verdict: NONE for W0-06B; independent review in progress. W0-06A remains CHANGES_REQUESTED; FLOW-016 Implementation Gate remains OPEN.
Predecessor-Task-ID: W0-06A/C01
Predecessor-PR: https://github.com/krumingo/BEG_Worck/pull/44 (Draft, unmerged, head 9040fc1d4b40d5376cc8912ba316a206c02d207b)
Predecessor-Review: https://github.com/krumingo/BEG_Worck/pull/44#issuecomment-5967976829
Authorization: Krum explicitly approved W0-06B/C01 start and exact technical integration base 9040fc1d4b40d5376cc8912ba316a206c02d207b, with the four W0-06A defects as the entry gate. W0-06A/C02 was never sent or started. The new branch, Issue #45 and Draft PR #46 were created after live recheck. Dashboard-first PENDING was published at b1c49658f6b711d91779523959b3f6d689b80673 before exactly one Claude Code Cloud Send; session https://claude.ai/code/session_01CC1BoxYWrVaLdT85riupTG then initialized on the B branch. Never resend or start a Routine. No merge, deploy, live provider access, production migration or customer-original operation is authorized.

## Canonical W0-06B/C01 — Storage Provider onboarding, adapters and activation/integrity foundation (FINAL HANDOFF; CODEX REVIEWING)

Claude published a final exact-head HANDOFF in Draft PR #46 at https://github.com/krumingo/BEG_Worck/pull/46#issuecomment-5985467082 on `888d32e2abf029c5740bc6d7d9484a0cf037809c`. The Claude session reports completion; live PR and remote branch heads match this SHA on repeated checks. Codex independently reviews the whole `main@79af297612f57c055bb7caef3f0c48493800d1b6 → final W0-06B head` package. The HANDOFF claims 434/434 focused and 33/33 real-Mongo passes, but also reports 15 adjacent W0 failures and residual avatar reachability without authentication; none of these claims is yet an independent Codex verdict. No merge or deploy is authorized.

**На човешки:** Продължаваме File Registry към реалните storage providers. Първо затваряме четирите доказани дефекта от основата; после изграждаме безопасно свързване, тест за активиране и проверки дали оригиналите са налични и непроменени.

**Identity and start gate.** Repository `krumingo/BEG_Worck`; Task-ID `W0-06B`, Cycle-ID `C01`; implementation branch `codex/w0-06b-storage-provider-foundation` starts exactly at `9040fc1d4b40d5376cc8912ba316a206c02d207b`, the current W0-06A Draft PR #44 head. Krum approved this technical integration base explicitly; it is **not W0-06A PASS**. New Issue #45 and Draft PR #46 to `main` exist. Whole-package review will inspect `main → final W0-06B head`, containing A foundation, four defect fixes and B implementation. PR #44 remains Draft/CHANGES_REQUESTED, unmerged separately. Source of truth: `CLAUDE.md`, `coordination/README.md`, `docs/flows/FLOW-016.md`, `FLOW-002.md`, `FLOW-040.md`, `docs/architecture/IMPLEMENTATION_WAVES.md`, `IMPLEMENTATION_GATE_MATRIX.md`, `TENANCY_MODEL.md`, W0-06A Issue #43 / Draft PR #44 and `coordination/REVIEWS/W0-06A.md`. Live refs and duplicate absence were checked before branch/Issue/PR creation. Dashboard-first PENDING was published before one authorized Claude Code Cloud Send. The observed session is https://claude.ai/code/session_01CC1BoxYWrVaLdT85riupTG; Dispatch is RUNNING and must never be sent twice.

**Entry gate — inherited W0-06A defects, not a separate product task.** Before provider work advances beyond foundation integration, close and independently prove all four findings from `coordination/REVIEWS/W0-06A.md`: (1) atomic tenant-safe concurrent AuditEvent sequence/chain; (2) no caller-controlled relation-target verification bypass; (3) version/location-scoped physical-delete result without over-deleting other versions or whole-file state; (4) deterministic duplicate-checksum selection and equal-timestamp acceptance test. Include focused positive/forbidden tests, static guards and unsafe-mutation checks, and disposable loopback real-Mongo with **0 failed / 0 required skipped**. This gate is not W0-06A PASS by assertion, and no code from PR #44 is treated as verified merely because it is a predecessor.

**Provider binding and adapters.** Model tenant-bound mandatory Primary and optional Backup Provider configuration: provider type, account/root/bucket/share, encrypted tenant-specific credential reference (never raw secrets in business records), capabilities, connection status, last verification and activation state in Tenant Registry. Implement shared provider contract plus Synology/NAS, Google Drive/Shared Drive, S3-compatible and generic on-prem/server adapters for put/upload, stat/exists, read/download, checksum verification, temporary protected access, delete request/result, capability reporting, and provider/account/object identity. `file_id` stays canonical; provider path/URL is never business identity. All provider operations use only fake/test credentials and disposable local resources in this task.

**Onboarding activation gate.** Test-tenant storage state remains unverified/inactive unless provider selected, credentials validated, tenant-specific root verified, temporary object uploaded and read back, checksum round-trip matched, test object cleanup succeeded, Primary binding stored in Tenant Registry, AuditEvent recorded connection/verification, and customer-vs-BEG_Work responsibility boundary recorded. Every failure leaves activation blocked. Do not activate a real BEG tenant or live NAS/Drive/S3 account.

**Integrity, availability and affected records.** Reusable service checks object existence, expected size/checksum, provider ID/version, permission/access state and preview/cache recoverability. Distinguish missing, permission denied, checksum mismatch, provider unavailable and changed external object; never promote preview/cache to canonical original. Resolve every FileRelation of the affected `file_id` and report projects, offers/contracts/annexes, acts/invoices, deliveries, daily reports, tasks, defects/warranties, assets/repairs and other target kinds. Expose an explicit event/result contract for later W0-07 DQ/Approval consumption, but do not implement W0-07 runtime, periodic scheduler/alarms or live migration in B.

**Security and audit.** Tenant-specific encrypted credential references and provider roots; no permanent credentials to browser/client, no cross-tenant binding/account/object/identifier access, temporary expiring protected links only, and FLOW-002 permission check before open/download/share. Inspect legacy unauthenticated `GET /api/media/avatar/{filename}`: if cross-user/tenant reachability is confirmed, secure it in this file-access slice or formally BLOCK W0-06B with evidence and a dedicated security-remediation proposal; do not leave a confirmed exposure as ordinary debt. Canonical AuditEvent covers provider connected/verified/verification failed, upload, open/download, provider location change, integrity check, checksum mismatch, missing file, permission failure and delete request/result. Prove concurrent audit sequence on real MongoDB. No raw secrets in API, schema responses, logs, prompts or Git.

**Required verification and HANDOFF.** Provider contract tests for all four adapter families; invalid credentials; tenant root/binding isolation; read/write/checksum round-trip; blocked activation until every step passes; cross-tenant denial; checksum/missing/permission/external-mutation distinctions; preview/original separation; affected-record resolution; expiring access; secret non-disclosure; all four inherited A defects. Run focused, adjacent W0, static guards and disposable local real-Mongo on `127.0.0.1` with fresh dbpath and proven cleanup; require **0 failed / 0 required skipped**. Deliver architecture contract, binding models, adapters, activation/integrity services, resolver, security/contract/real-Mongo tests, and final exact-head HANDOFF in existing Draft PR #46. Codex independently reviews the whole `main → final W0-06B head` package and actual diff; skipped/unrun is not PASS. Potential verdict: `W0-06B PASS — STORAGE PROVIDER ONBOARDING AND INTEGRITY FOUNDATION CLOSED`; this is **not** full FLOW-016 Gate PASS.

**Hard boundaries.** No production credentials or real BEG NAS/Drive/S3 activation, production migration, moving/deleting customer originals, deploy, merge without explicit Krum approval, W0-07 implementation, unrelated FLOW/D changes, or automatic next task. After B, periodic scheduler/alarms, live migration/adoption and final FLOW-016 integration gate remain separate work. STOP for a new business/security rule, unresolved integration base, unsafe provider deletion, confirmed avatar exposure that cannot be safely remediated in scope, external credential need, or failed required gate; report exact evidence rather than narrowing scope silently.

---

## Archived superseded W0-06A/C02 intent — prepared but never sent

The following historical C02 snapshot was replaced by Krum's W0-06B preparation direction. It remains evidence of an unsent plan only; it is not a live dispatch pointer, implementation, HANDOFF or verdict.

# BEG_WORK — former active implementation assignment

Status: W0-06A/C02 PENDING — BOUNDED CORRECTION PREPARED; SEND NOT CONFIRMED
Human-Summary-BG: Поправяме само четирите доказани проблема от независимия преглед на File Registry, после повтаряме същите тестове. Не започваме нова задача и не местим реални файлове.
Current-Agent: CODEX
Current-State: WORKING
Claude-State: WAITING
Codex-State: WORKING
Pipeline-Step: ASSIGNMENT
Transition-Phase: INTENT
Now: Codex подготви W0-06A/C02 само за четирите доказани дефекта. Dispatch е PENDING, но няма C02 Send или Claude start; очаква се изрично потвърждение от Крум.
Next-Agent: CLAUDE
Relay-State: NO_RELAY_NEEDED
Relay-From: NONE
Relay-To: NONE
Krum-Action: CONFIRM ONE-TIME W0-06A/C02 SEND TO CLAUDE
Dispatch-State: PENDING (preparation only; no Send until explicit Krum confirmation)
Dispatch-Run: NONE (C02; C01 session is archived below)
Dispatch-Observed-At: NONE (C02)
Task-ID: W0-06A
Cycle-ID: C02
Base-branch: main
Base-SHA: 79af297612f57c055bb7caef3f0c48493800d1b6
Implementation-branch: codex/w0-06a-file-registry-foundation
PR-URL: https://github.com/krumingo/BEG_Worck/pull/44 (Draft; independent CHANGES_REQUESTED published; unmerged)
PR-Head: 9040fc1d4b40d5376cc8912ba316a206c02d207b
Correction-Base-SHA: 9040fc1d4b40d5376cc8912ba316a206c02d207b
Merge-SHA: NONE
Main-Head: 79af297612f57c055bb7caef3f0c48493800d1b6
Issue: https://github.com/krumingo/BEG_Worck/issues/43
HANDOFF-URL: https://github.com/krumingo/BEG_Worck/issues/43#issuecomment-5967741410
Review: coordination/REVIEWS/W0-06A.md — C01 independent CHANGES_REQUESTED on exact head, published https://github.com/krumingo/BEG_Worck/pull/44#issuecomment-5967976829; C02 review not started.
Final-Verdict: C01 W0-06A CHANGES_REQUESTED; C02 has no HANDOFF or verdict.
Predecessor-Task-ID: W0-03E-A2C/C02
Predecessor-Integration: PR #42 merged into main at 79af297612f57c055bb7caef3f0c48493800d1b6; no deploy.
Authorization: Krum supplied the bounded C02 preparation instruction only. C01's final HANDOFF and independent CHANGES_REQUESTED remain published at exact PR #44 head 9040fc1d4b40d5376cc8912ba316a206c02d207b. Codex verified that PR #44 remains open/Draft on the same branch/head and main remains at the specified base; no C02 assignment, HANDOFF or dispatch was found. A separate explicit Krum confirmation is required before the one-time C02 Send. No correction has started; no merge, deploy, production migration, live provider credential use or customer-file move is authorized.

## Canonical W0-06A/C02 — bounded correction (PENDING; NOT SENT)

**На човешки:** Поправяме само четирите доказани проблема от независимия преглед на File Registry, после повтаряме същите тестове. Не започваме нова задача и не местим реални файлове.

**Identity and preflight.** Repository `krumingo/BEG_Worck`; same Task-ID `W0-06A`; Cycle-ID `C02`; same implementation branch `codex/w0-06a-file-registry-foundation`; same open Draft PR #44; exact correction start head `9040fc1d4b40d5376cc8912ba316a206c02d207b`; unchanged base `main@79af297612f57c055bb7caef3f0c48493800d1b6`. Before any Send, recheck PR head, `coordination/REVIEWS/W0-06A.md`, the published C01 `CHANGES_REQUESTED`, and absence of an existing C02 session/dispatch. STOP on drift. Do not create a new Task-ID, branch, PR or Claude Routine.

**Only allowed corrections and proof.**
1. Make concurrent AuditEvent sequence allocation atomic and tenant-safe: same-tenant simultaneous writes yield unique increasing `[1, 2, 3, 4]`, two tenants stay independent, the audit chain remains intact, and idempotent retry cannot duplicate sequence numbers. Do not weaken the real-Mongo test.
2. Remove the caller-controlled relation-target verification bypass from public/business registry writes: missing and foreign-tenant targets must be rejected, including when the caller supplies a bypass flag. Any indispensable internal/test-only escape hatch must be explicit, isolated from the normal API and fail-closed.
3. Scope confirmed physical-delete results to the requested version/location. Deleting version N must leave unrelated historical/current versions and valid locations available; whole-file deletion requires an explicit whole-file action; AuditEvent records the exact scope.
4. Make duplicate-checksum candidate selection and its acceptance test deterministic under equal timestamps with an immutable stable tie-breaker. Repeated runs must choose/order the same candidate without weakening the duplicate semantics.

Small cleanup: fix the two `git diff --check` EOF whitespace findings in the new W0-06A docs, with no unrelated formatting churn.

**Execution and HANDOFF.** Do not Send until Krum explicitly confirms the single C02 Send. Then use the existing Claude Code workflow on the same branch/PR from the exact correction head. Only an observed session start changes `Dispatch-State` to `RUNNING`, Claude to `WORKING` and Codex to `WAITING`. Claude must publish one final exact-new-head HANDOFF with the C01→C02 delta, focused results, real-Mongo result if available, and confirmation of no unrelated changes; no self-declared PASS.

**Independent re-review after final HANDOFF.** Codex inspects both the whole `main→corrected head` package and C01→C02 delta, reruns focused W0-06A, adjacent W0, all static guards and unsafe-mutation tests, fake provider and disposable real-Mongo gate on `127.0.0.1` with fresh dbpath and proven cleanup. Specifically rerun `test_two_tenants_writing_at_once_keep_separate_intact_audit_chains` and all `test_w0_06a_real_mongo.py`. Require **0 failed / 0 required skipped** before considering `W0-06A PASS — FILE REGISTRY FOUNDATION CLOSED`; otherwise publish one exact remaining `CHANGES_REQUESTED` or `BLOCKED` finding. Update this assignment, control state, board and `coordination/REVIEWS/W0-06A.md` dashboard-first. W0-06A PASS is not FLOW-016 Gate PASS.

**Out of scope and hard boundaries.** Do not fix `/api/media/avatar/{filename}` or the other five legacy file defects in C02. No provider onboarding/activation, HTTP File Registry routes, DQ/Approval runtime, migration runner, full FLOW-016 gate, W0-07, unrelated FLOW/D work, merge, deploy, production migration, customer-original move/delete, or NAS/Drive/S3 credentials. No automatic next task.

---

## Archived W0-06A/C01 — File Registry foundation and legacy file inventory

**На човешки / Какво правим.** Ще направим едно общо място, което знае кой е всеки файл, къде се пази, към какво е свързан и коя е текущата му версия. Така снимки, договори, фактури и други документи няма да се копират и разхвърлят по модулите, а всички ще сочат към един стабилен `file_id`.

**Identity and exact base.** Repository `krumingo/BEG_Worck`; Task-ID `W0-06A`; Cycle-ID `C01`; implementation branch `codex/w0-06a-file-registry-foundation` starts exactly at `main@79af297612f57c055bb7caef3f0c48493800d1b6`. Open one new Draft PR against `main`. Before work, recheck repository, branch, exact head, Issue #43 and absence of duplicate W0-06A PR/session. STOP on drift.

**Read first.** `CLAUDE.md`, `coordination/README.md`, this ACTIVE assignment, Issue #43, `docs/flows/FLOW-016.md`, `docs/architecture/TENANCY_MODEL.md`, `docs/architecture/IMPLEMENTATION_WAVES.md`, `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`, and relevant FLOW-002/FLOW-040 contracts. Treat FLOW-016 as business source of truth. Do not invent provider or deletion business rules.

**Scope.**
1. Inventory all legacy file/media/document paths and writers in the active backend.
2. Implement tenant-bound provider-neutral File Registry foundation: File, FileVersion, FileRelation, ProviderLocation/object reference, derived/cache metadata.
3. Stable `file_id` is the business identity; provider URL/path is never the business ID.
4. One file may have many business relations without physical duplication.
5. Versioning must preserve old versions read-only and keep exactly one current version per family.
6. Implement provider adapter contract only; no live credentials or real provider activation in A.
7. Use merged tenant boundary infrastructure; all registry reads/writes/relations are tenant-scoped.
8. Audit/idempotency for register/version/relation/provider-location/integrity/delete-request-result where current W0-04 supports it.
9. Produce deterministic legacy migration map; no real customer file move.
10. Add static guards for provider-path-as-business-ID, ownerless File Registry write, tenantless/foreign FileRelation and unsafe physical-delete path.
11. Add in-memory/fake-adapter tests and a disposable real-Mongo tenant-isolation gate with 0 required skips.

**Required inventory row.** `path | function/route | current storage location | current id/path/url field | tenant field | business relation | read/write/delete behaviour | migration action`. No ASSUMED SAFE.

**Acceptance.** PASS only if:
- one stable file_id can serve multiple relations without duplicate registry records;
- tenant A cannot read B metadata/provider location/relations, including colliding IDs;
- new version never overwrites old;
- duplicate checksum behavior is deterministic;
- unlink removes only one relation;
- unavailable/mutated provider object does not turn preview/cache into canonical original;
- fake provider contract passes;
- idempotent retries are proven;
- guard mutation tests pass;
- independent real-Mongo isolation gate can be run later by Codex with 0 required skips.

Expected Claude verdict at HANDOFF is implementation complete, not PASS. Codex independently reviews the whole `main→W0-06A` package and runs the real-Mongo gate before PASS.

**Hard boundaries.** No merge, deploy, production migration, real BEG/NAS/Drive/S3 file move, live provider credentials, customer-original deletion, W0-07 implementation, unrelated FLOW/D changes, or automatic next task.

**Dispatch protocol.** Krum confirmed one-time Computer Use Send for `W0-06A/C01` on `codex/w0-06a-file-registry-foundation`; the direct Code Cloud session above was observed starting and verifying the exact base. Final exact-head HANDOFF is published in Issue #43, the session ended, and PR #44 head matches the HANDOFF. Codex published independent CHANGES_REQUESTED in PR #44; no PASS, correction dispatch or second Send.

---

## Archived previous assignment

# BEG_WORK — active implementation assignment

Status: W0-03E-A2C/C02 PASS — PR #42 MERGED INTO MAIN; FLOW-032 LIVE GATE OPEN
Human-Summary-BG: Крум одобри и PR #42 е слят в main с целия W0-03E кодов пакет. Това не е deploy или production migration; FLOW-032 live gate остава отворен.
Current-Agent: CODEX
Current-State: PASS
Claude-State: WAITING
Codex-State: WAITING
Pipeline-Step: REVIEW
Transition-Phase: OBSERVED (independent exact-head PASS published in PR #42)
Now: PR #42 е merge-нат в main на exact PASS head; GPT е следващ за решение по програмата, без автоматичен deploy или следваща задача.
Next-Agent: GPT
Relay-State: NOT_SENT
Relay-From: CODEX
Relay-To: GPT
Krum-Action: RELAY PR #42 MERGE RESULT TO GPT; NO DEPLOY
Dispatch-State: NONE (C02 session finished)
Dispatch-Run: https://claude.ai/epitaxy/session_01EwGs439P7mdMskveoBbFNf (C02 finished direct follow-up in existing C01 session)
Dispatch-Observed-At: 2026-10-02T17:04:26Z
Task-ID: W0-03E-A2C
Cycle-ID: C02
Base-branch: main
Base-SHA: bbdb94dafa09a483b35ccdf6ed13604b77b86a96
Implementation-branch: codex/w0-03e-a2c-full-tenant-boundary
PR-URL: https://github.com/krumingo/BEG_Worck/pull/42 (MERGED into main; PR #40 remains Draft/BLOCKED and untouched)
PR-Head: 5e16cb90c175f6b697b256f63b8e652ed9d00e43
Remediation-Base-SHA: 62cf2a53a6fe1d3b7c61f1c0ef943e07f2c2c473
Implementation-Branch-Head: 5e16cb90c175f6b697b256f63b8e652ed9d00e43 (exact C02 final HANDOFF head, rechecked in PR metadata)
Merge-SHA: 79af297612f57c055bb7caef3f0c48493800d1b6
Main-Head: 79af297612f57c055bb7caef3f0c48493800d1b6
HANDOFF-URL: C01 https://github.com/krumingo/BEG_Worck/pull/42#issuecomment-5951482130; C02 https://github.com/krumingo/BEG_Worck/pull/42#issuecomment-5957526882.
Review: coordination/REVIEWS/W0-03E-A2C.md — C01 BLOCKED historical on 1308f20b38ef94ac396b1607ade49eb7e0d18f46; C02 independent PASS on exact head 5e16cb90c175f6b697b256f63b8e652ed9d00e43, published https://github.com/krumingo/BEG_Worck/pull/42#issuecomment-5957832541. Final package assessment: coordination/REVIEWS/W0-03E.md.
Final-Verdict: W0-03E-A2C/C02 PASS; W0-03E implementation code package MERGED into main at 79af297612f57c055bb7caef3f0c48493800d1b6; FLOW-032 live gate OPEN. No deploy or production migration.
Predecessor-Task-ID: W0-03E-A2B/C01
Predecessor-Review: coordination/REVIEWS/W0-03E-A2B.md (final BLOCKED on exact head 62cf2a53a6fe1d3b7c61f1c0ef943e07f2c2c473)
Predecessor-Integration: PR #40 remains Draft/BLOCKED and unmerged as a separate PR, but its exact predecessor code head was included as an ancestor of merged PR #42; the stack's code is now in main. Do not call PR #40 individually merged.
Authorization: Owner's bounded C02 correction in PR #42 https://github.com/krumingo/BEG_Worck/pull/42#issuecomment-5956888750 authorized only the test fix. Claude published final exact-head HANDOFF https://github.com/krumingo/BEG_Worck/pull/42#issuecomment-5957526882; Codex published independent exact-head PASS https://github.com/krumingo/BEG_Worck/pull/42#issuecomment-5957832541. On 2026-10-03 Krum explicitly approved merge of PR #42 into main at exact head 5e16cb90c175f6b697b256f63b8e652ed9d00e43 without deploy. GitHub reports PR #42 MERGED at 79af297612f57c055bb7caef3f0c48493800d1b6; git proves the approved head is its second parent. No deploy, production migration or next-task dispatch was authorized.
Correction-cycles: W0-03E C02/C03, R1, A1, A2 and A2B outcomes remain immutable. A2C/C01 BLOCKED remains historical; A2C/C02 is one owner-authorized bounded correction, not a new Task-ID or C04.

## Canonical W0-03E-A2C/C02 — bounded committed real-Mongo test correction — HANDOFF / REVIEW

**На човешки / Какво правим.** Поправяме само грешката в real-Mongo теста. След това Claude пуска теста наново, а Codex го проверява независимо; ако committed gate мине чисто, A2C може да получи PASS.

**Identity and exact base.** Repository `krumingo/BEG_Worck`; Task-ID `W0-03E-A2C`; Cycle-ID `C02`; same implementation branch `codex/w0-03e-a2c-full-tenant-boundary`; same Draft PR #42 against `main`. Start only from exact head `1308f20b38ef94ac396b1607ade49eb7e0d18f46`. Before Send, recheck selected repository/branch, exact PR head, latest owner authorization https://github.com/krumingo/BEG_Worck/pull/42#issuecomment-5956888750, C01 BLOCKED review, and absence of duplicate C02 Claude session/dispatch. Stop on mismatch. No new branch, PR, task or Claude Routine.

**Allowed edit only.** In `backend/tests/test_w0_03e_a2c_two_tenant_boundary.py`, replace the erroneous `AsyncIOMotorClient(os.environ[REAL_URL])` usage with the already-resolved Mongo URI (`REAL_URL`) or exactly equivalent minimal correction. Do not alter `scenario(...)`, A/B fixtures, assertions, skip policy, production/runtime/business logic, guard, inventory, settings, FLOW/D or any other file. The C01 whole-package review remains evidence but is not C02 PASS.

**Claude proof and HANDOFF.** Run the committed A2C real-Mongo pytest test against a disposable local MongoDB bound to `127.0.0.1` with a fresh dbpath: required scenario actually executes, `0 failed / 0 skipped`, scratch DB and server cleaned up. Re-run focused A2C guard/settings/in-process tests; report exact command, collected/passed/failed/skipped, exact new head, one-file diff and cleanup. If Claude Code Cloud cannot run real Mongo, report it as NOT RUN/BLOCKED, not PASS. Publish final exact-head HANDOFF in PR #42 and stop. No intermediate push is HANDOFF.

**Independent Codex gate after HANDOFF.** Confirm Claude session finished and PR head stable, inspect the exact one-file diff, then independently run the **committed test itself** on a separate disposable local MongoDB with `0 failed / 0 skipped`; direct `scenario(...)` invocation is not a substitute. Repeat focused guard/settings checks and exact-head review. Only then may `W0-03E-A2C PASS — FULL ACTIVE TENANT BOUNDARY CLOSED` be recorded, followed by the final W0-03E closure review. Otherwise record exact BLOCKED evidence; do not dispatch another correction automatically.

**Hard boundaries.** No merge, deploy, production migration, Atlas/NAS/production write, real second production tenant, W0-06, unrelated FLOW/D or any change outside this one test file. Krum retains merge/deploy/production decisions. The one separately confirmed direct Send and observed Claude start changed Dispatch to `RUNNING`; only final exact-head HANDOFF and ended session allow Codex review.

## Canonical W0-03E-A2C/C01 — full active backend tenant boundary — HANDOFF received, independent review in progress

**На човешки / Какво правим.** Сега пускаме Claude да затвори tenant-разделението по целия активен backend, не само по отделни маршрути. Целта е при две фирми с еднакви ID-та нито четене, нито запис, нито права, нито настройки да могат да прескочат между тях.

**Identity and sources.** Repository `krumingo/BEG_Worck`; Task-ID `W0-03E-A2C`; Cycle-ID `C01`; implementation branch `codex/w0-03e-a2c-full-tenant-boundary` at exact base `62cf2a53a6fe1d3b7c61f1c0ef943e07f2c2c473` from blocked Draft PR #40. Main is `bbdb94dafa09a483b35ccdf6ed13604b77b86a96`. Read Issue #41 and the latest owner decision in PR #40, `coordination/REVIEWS/W0-03E-A2B.md`, complete main→A2B diff, `CLAUDE.md`, `coordination/README.md`, `docs/architecture/W0-03E-A2B_SINGLE_TENANT_BACKFILL.md`, `W0-03E-A2B_INVENTORY.md` §3, `TENANCY_MODEL.md` (D-15), `W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §6, `IMPLEMENTATION_WAVES.md`, `IMPLEMENTATION_GATE_MATRIX.md`, and `docs/flows/FLOW-032.md`. Recheck exact branch/base and absence of duplicate A2C PR/session before editing. Open one new Draft PR against `main`; PR #40 stays Draft/BLOCKED and untouched. Draft is not integration.

**Inventory and implementation scope.** Inventory every active route, service, job and helper that reads or writes tenant-owned operational data. For every access report `path | function | collection | operation | current tenant predicate | risk | action`; no hidden exclusion or `ASSUMED SAFE`. The prior 314 unscoped reads / 169 unscoped writes are starting evidence only. Close all active bare-ID reads and enrichments with server-resolved tenant context; join/report/export source and related sides must be tenant-scoped, with no global ID/name/first-match fallback. Every tenant-owned update/delete/upsert must include the tenant predicate in the write filter itself; a prior scoped read is insufficient. Fix all `invoice_lines.py` read/enrichment/update/allocate/recalculate paths. Replace fixed `_id` settings (`worker_rates`, `employee_cost_config`, `overtime_config` and any discovered peers) with tenant-safe identity that preserves current BEG settings migration without inventing a new business rule.

**Whole-backend enforcement.** Extend the static/AST guard to the entire active backend, not only the former W0-03E protected subset. It must reject unsafe bare reads, tenantless update/delete/upsert, foreign enrichment, ownerless create, caller tenant override, unsafe authorization relation and globally colliding settings identity. Every exclusion needs narrow technical justification and may not hide tenant-owned business access. Demonstrate clean-tree PASS, deliberate unsafe mutations FAIL, and Windows/POSIX path portability.

**Acceptance and independent gate.** In a disposable environment, complete BEG backfill and zero-ownerless checks, then create synthetic TEST COMPANY B through canonical onboarding. Exercise deliberately colliding IDs with both B-first and BEG-first storage order across *all active route families* found by inventory, at minimum projects/team, users/persons, clients/companies/counterparties/subcontractors, invoices/invoice-lines, payments/allocations, offers, warehouses/locations/items/materials, settings, reports/exports. Use HTTP-level reads and writes; each attempted foreign write must leave the foreign document byte-equal. Run disposable local real Mongo bound only to `127.0.0.1` with fresh dbpath, zero required skips and verified cleanup. Codex after final exact-head HANDOFF independently reviews the **whole main→A2C package**, reruns focused/adjacent/static guard and a separate real-Mongo A/B gate. PASS only with zero active tenant-owned bare reads/writes, closed fixed-ID collision, whole-backend guard coverage and two-way isolation. Only then separately repeat final W0-03E closure review; no automatic merge.

**HANDOFF and stop.** After one direct Claude Code Cloud Send and observed start, Claude publishes a new Draft PR and final exact-head HANDOFF with full inventory/action matrix, actual diff, residual limits, focused/adjacent/HTTP/real-Mongo commands and collected/passed/failed/skipped counts, mutation proof and cleanup; then STOPS. Codex records PASS or `W0-03E-A2C BLOCKED — <one exact remaining blocker>` after independent review. No unverified tests as PASS. No merge, deploy, production migration, Atlas/NAS/production writes, real second production tenant, W0-06, unrelated locked FLOW/D changes, duplicate Send or Claude Routine. Krum retains security/access, merge, deploy and production decisions. Dispatch remains PENDING until the specifically confirmed Send is actually observed; an intermediate push is not HANDOFF.

## Archived predecessor W0-03E-A2B/C01 — final independent BLOCKED

## Canonical W0-03E-A2B/C01 — BEG legacy backfill + two-tenant isolation — BLOCKED

**На човешки / Какво правим.** Claude приключи промяната, с която старите данни се закачат към BEG и се проверява работа с втора тестова фирма. Сега Codex трябва независимо да провери дали между двете фирми никъде не се смесват данни, права или финансови записи и дали останалите непроверени места са достатъчно сериозни, за да блокират задачата.

**Identity and sources.** Repository `krumingo/BEG_Worck`; Task-ID `W0-03E-A2B`; Cycle-ID `C01`; code base exact `43ba7e35e9b14899cc3054f1f9c65f30996162ae` from blocked Draft PR #36. Implementation branch `codex/w0-03e-a2b-single-tenant-backfill` currently points at architecture-only commit `bd2cd362bf7b6009d82407925c76c0a9390737fb`, a descendant of the code base. Read Issue #38 **including the latest owner canonical assignment and test-tenant extension**, `docs/architecture/W0-03E-A2B_SINGLE_TENANT_BACKFILL.md` at bd2cd362, `CLAUDE.md`, `coordination/README.md`, this ACTIVE assignment, predecessor `coordination/REVIEWS/W0-03E-A1.md` and `W0-03E-A2.md`, `docs/architecture/TENANCY_MODEL.md` (D-15), `W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §6, `IMPLEMENTATION_WAVES.md`, `IMPLEMENTATION_GATE_MATRIX.md`, `docs/flows/FLOW-032.md`, W0-02 permission/bootstrap code and the complete main→A2 package. Recheck branch/base, absence of another A2B session/PR and exact queue SHA before editing. Open one new Draft PR against main; PR #32/#33/#34/#36 stay Draft and untouched. Draft is not integration.

**Phase 1 — fail-closed precondition.** Resolve canonical BUILDING EXPRESS GROUP / BEG tenant only from trusted server-side Registry/organization state; do not hard-code UUID/name or trust request fields. Prove exactly one eligible active operational tenant for the current legacy source and no conflicting pre-owned records before any migration write. If this cannot be proven, STOP with exact blocker. This owner-approved one-time inference is *only* for the current BEG legacy dataset, not future imports or a future real second tenant.

**Phase 2–3 — inventory and test-only backfill.** Inventory every tenant-owned business/operational/authorization collection in the protected W0-03E scope; for each report `collection | total | already tenant-bound | ownerless | conflicting | writer paths | migration action`, with no ASSUMED SAFE. Include the minimum collection families named in Issue #38: projects/team, users/persons/profiles, companies/clients/counterparties/subcontractors, offers/contracts/invoices/lines, payments/allocations/advances/loans, warehouses/locations, items/materials/requests, work/SMR, assets, tasks/schedules/relations, files/doc metadata and audit/business history. Implement dry-run, idempotent/resumable backfill of current ownerless rows to the resolved BEG tenant **only in isolated test data**; preserve business IDs, never overwrite conflicting ownership, audit/reconcile before/after, no silent partial success. Prove zero ownerless operational and authorization records in the defined protected test scope and zero unresolved conflicts. No production migration.

**Phase 4–6 — writers, membership, bootstrap, guards.** Every new protected tenant-owned record must stamp server-resolved active tenant at creation and reject caller override/ownerless creation. `project_team` must be tenant-bound; authorization uses tenant + project + user [+ role], never bare IDs. Harden `backend/scripts/w0_02_bootstrap_permissions.py` and equivalent permission backfills: consume only tenant-bound memberships, reject any remaining ownerless row, never infer tenant from bare user/project IDs. Static guard must pass clean tree on Windows/POSIX and fail deliberate ownerless-writer, bare-ID lookup and tenantless authorization mutations.

**Phase 7–9 — second tenant and gate.** Only after verified zero-ownerless test backfill, create TEST COMPANY B through the canonical onboarding path in the same disposable test environment; do not copy BEG data. Seed A/B colliding IDs across project, user/person, company/client/counterparty, team membership, invoice, payment/allocation, warehouse/location, offer/export/report. Insert B first where useful. Demonstrate bidirectional isolation, no cross-tenant permission, enrichment, financial value, legacy reference, XLSX/PDF export or report/drilldown leak; each new A/B record gets its own server-derived tenant. Include HTTP route-level tests for project/team authorization, invoice list/detail, offers XLSX/PDF, reports/drilldowns, payment/allocation projections and protected legacy/Master reads. Run disposable real Mongo bound only to `127.0.0.1`, fresh temp dbpath, 0 skipped required scenarios, verified cleanup; never Atlas/NAS/production DB or a real second production tenant.

**HANDOFF and independent gate.** After one confirmed direct Code Cloud Send and observed start, Claude implements on the exact A2B branch, opens a new Draft PR, publishes exact-head HANDOFF with full main→A2B diff/inventory, dry-run and test migration reconciliation, writer/access/guard matrix, focused/adjacent/HTTP tests, real-Mongo counts and cleanup, then STOPS. Codex changes dashboard to REVIEWING only after final HANDOFF and ended session, independently reviews the **whole main→A2B package**, runs focused/adjacent/static guard and a separate disposable real-Mongo A/B collision gate with zero required skips. PASS only when all Issue #38 conditions are proven; then separately review final W0-03E closure. If a correctness gate fails, record `W0-03E-A2B BLOCKED — <one exact blocker>`, no automatic new cycle.

**Hard boundaries and lifecycle.** No merge, deploy, production migration, Atlas/NAS/production write, real second production tenant, W0-06 implementation, unrelated locked FLOW/D changes, automatic Master Data production activation, Claude Routine or duplicate Send. PENDING is intent, not implementation; only observed Claude start allows RUNNING/CLAUDE WORKING, only final exact-head HANDOFF allows CODEX REVIEWING, and a verdict exists only after independent evidence. Krum retains Send, architecture/security, merge and deploy decisions.

## Canonical W0-03E-A2/C01 — project-team authorization tenant provenance — BLOCKED

**Identity and base.** Repository `krumingo/BEG_Worck`; Task-ID `W0-03E-A2`; Cycle-ID `C01`; implementation branch `codex/w0-03e-a2-project-team-provenance` is already published at exact blocked A1 head `4b7f9869c288a9b9596bb8d2c02136b0fb749acb`. Open one **new Draft PR against `main`** for the complete stacked A2 package; clearly identify PR #34 as an unaccepted predecessor code base. Leave PR #32/#33/#34 open/Draft and untouched. Recheck exact branch/base and absence of duplicate A2 session/PR before work; STOP on drift. Draft is not integration.

**Read first.** `CLAUDE.md`, `coordination/README.md`, this ACTIVE assignment, `coordination/REVIEWS/W0-03E-A1.md`, the prior W0-03E/R1 reviews, `docs/architecture/IMPLEMENTATION_WAVES.md`, `IMPLEMENTATION_GATE_MATRIX.md`, `W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §6, `TENANCY_MODEL.md` (D-15), applicable locked FLOW/D including `docs/flows/FLOW-032.md`, and the actual complete `main`→A1 head package. Treat A1's team-membership counterexample and Windows guard failure as entry evidence, not optional observations.

**Authoritative rule.** `project_team` is a tenant-bound authorization relation. Every new row carries `tenant_id` from the verified **server-side active tenant** only; reject caller/form/body/query tenant overrides. Membership queries require `tenant_id + project_id + user_id` and optional role, never ID pairs alone. An ownerless legacy row grants **zero** authorization; no global/name/role/ID inference. Preserve W0-01 Tenant Guard, W0-02 permission boundary and W0-04 AuditEvent. Do not invent a business rule or relax existing approvals. Existing legacy `org_id` data may be a compatibility input only after trusted server-side tenant resolution, never a substitute for proven row provenance.

**Schema, writes and protected reads.** Add minimal tenant provenance to project-team schema/runtime. Find every in-scope project-team writer and authorization reader, including project team routes, finance invoice list/detail, offers, reports, exports and the A1 `assigned_project_ids()`/`is_project_member()` helpers. All new writes stamp the server-resolved `tenant_id`, enforce permission/resource ownership and emit the canonical AuditEvent; no caller override. All authorization reads filter on the exact `tenant_id`, `project_id`, `user_id` and role where needed; ownerless or mismatched rows are refused/ignored. Do not leave a route-local bare membership bypass. Keep `MASTER_DATA_MODE=off` inert and shadow non-writing.

**Deterministic legacy migration.** Classify each legacy row `PROVEN_TENANT` or `UNRESOLVED_PROVENANCE`; count `proven`, `unresolved` and `conflicting` in a read-only dry-run. Only a **provably single-tenant source database** verified against Tenant Registry/database context may backfill its own tenant_id. An ambiguous shared/unknown-source row is `UNRESOLVED`, goes to existing DQ/pending mapping for explicit human resolution and never participates in authorization. No guess from project/user IDs, name, role or coincident records. Migration is implementation/dry-run only; no live/production migration or external write. If the current DQ/pending model cannot represent provenance safely, STOP with the exact architectural blocker rather than inventing a new approval flow.

**Tests.** Deterministic A/B collision matrix: same project ID, same user ID, same role, B membership inserted first, A project exists, B row gives **no** A access. Also prove A-proven row authorizes only A, ownerless row DENY, forged tenant DENY, unresolved migration row DENY, mixed/contradictory source provenance fail-closed, and no unauthorized write. Exercise actual HTTP authorization through project-team, finance invoice list/detail, offers, reports/exports and relevant protected A1 access paths, not helpers alone. Add migration dry-run counts and provenance fixtures; preserve permission/audit and adjacent W0-03 regressions.

**Static guard and HANDOFF.** Normalize Windows/POSIX paths so the A1 guard passes the clean protected tree and fails a deliberately injected unsafe bare-ID lookup on both platforms. Do not hide violations via exclusions. Claude runs focused/adjacent tests and an isolated disposable **real MongoDB** A/B collision and ownerless migration matrix with zero skipped (bind `127.0.0.1`, fresh dbpath, cleanup proven; never Atlas/NAS/production). HANDOFF in the new Draft PR must give exact head, actual diff, writer/reader/migration inventory, concrete test commands and collected/passed/failed/skipped counts, guard positive/negative evidence, real-Mongo evidence, cleanup and limitations; then STOP. Intermediate push is not HANDOFF.

**Codex independent gate.** Only after observed final exact-head HANDOFF, ended Claude session and stable PR head, review the **whole `main`→A2 package**, not just A2 delta. Independently search every protected team authorization path, run static guard and synthetic unsafe injection, focused and adjacent tests, HTTP A/B collisions, ownerless/provenance migration cases and a separate disposable real-Mongo matrix with **0 skipped**. PASS only if B/ownerless rows cannot authorize A, proven A membership works, all in-scope writes carry server-resolved tenant, the guard passes and rejects unsafe code, and real Mongo is 100% PASS. Verdict `W0-03E-A2 PASS — PROJECT TEAM TENANT PROVENANCE CLOSED`; then independently repeat the final W0-03E gate before claiming W0-03E ready for merge decision. Any unresolved provenance/authorization correctness defect is `W0-03E-A2 BLOCKED — LEGACY AUTHORIZATION PROVENANCE UNRESOLVED`; no automatic new cycle.

**Hard boundaries and lifecycle.** No merge, deploy, production migration, Atlas/NAS/production writes, real BEG database, W0-06 implementation, locked FLOW/D edit, new business rule, Claude Routine, duplicate Send or modification of PR #32/#33/#34. `PENDING` was published/validated before Claude Send; observed start changed Dispatch to RUNNING/Claude WORKING; only final exact-head HANDOFF changes Codex to REVIEWING; publish final verdict only after independent review. Krum retains merge, deploy and security decisions. Claude is now working in the recorded direct Code Cloud session; Codex waits for final HANDOFF.

## Archived predecessor W0-03E-A1/C01 — final independent BLOCKED; no automatic correction

## Canonical W0-03E-A1/C01 — tenant-safe data access architecture — final independent BLOCKED

**Identity and exact base.** Repository `krumingo/BEG_Worck`; Task-ID `W0-03E-A1`; Cycle-ID `C01`; branch `codex/w0-03e-a1-tenant-safe-access` starts at exact `2cd40a377b67beb4cc60bf211e42708e2a69f881` from blocked Draft PR #33. Open one **new Draft PR against `main`** for A1; leave PR #32 and #33 open/Draft and untouched. Recheck exact base/branch and absence of duplicate A1 session/PR before work. Draft is not integration. If identities drift, STOP.

**Read first.** `CLAUDE.md`, `coordination/README.md`, this ACTIVE file, `coordination/REVIEWS/W0-03E-R1.md`, `coordination/REVIEWS/W0-03E.md`, `docs/architecture/IMPLEMENTATION_WAVES.md`, `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`, `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §6, `docs/architecture/TENANCY_MODEL.md`, `docs/flows/FLOW-032.md` and other applicable locked FLOW/D, plus the complete actual `main`→PR #33 code diff. The R1 real-Mongo HTTP invoice list/detail leak is the entry evidence, not the whole boundary.

**Full protected-surface inventory.** Search the entire W0-03E/FLOW-032 protected read surface for `find_one({"id": ...})`, reads on `..._id` without tenant predicate, `$lookup` matching only an ID, and helpers resolving project/client/company/user/warehouse/invoice/counterparty/person/payment/allocation or any other identity-bearing record without server-resolved tenant context. Inventory every actual path as `path | entity | lookup key | tenant predicate | risk | action`. Include nested aggregation foreign sides and adapter calls. No `ASSUMED SAFE`; an unverified path is BLOCKED, not silently omitted.

**Central access layer, no bypass.** Implement one reusable tenant-safe repository/access layer with scoped accessors for project, client, company, user, warehouse, invoice, counterparty, person, payment and allocation as applicable. Tenant comes only from verified server-side resolver/context; each lookup includes tenant predicate and enforces resource ownership. No global-ID, name or fuzzy fallback. Fail closed on absent/mismatched related record. Legacy resolution goes only through proven tenant-bound mapping. Preserve current business behavior where safely possible; do not invent identity matching or change business rules. Migrate the whole assigned surface: finance invoice list/detail and enrichment, offers XLSX/PDF, reports, exports, drilldowns, payment/allocation projections, legacy adapter reads, and relevant import/report projections. No route-local bare identity lookup in the protected modules.

**Static enforcement.** Add CI-runnable deterministic guard that rejects new bare-ID reads or ID-only `$lookup` in the protected modules for at least projects, clients, companies, users, warehouses, invoices, counterparties, persons, payments and allocations. Demonstrate that the guard FAILS on a deliberately injected unsafe `db.projects.find_one({"id": project_id})` and PASSES the corrected tree. Do not satisfy it through exclusions or cosmetic renaming that leaves a bypass. Scope any allowlist narrowly with proof; no `ASSUMED SAFE`.

**Collision and HTTP tests.** Tenant A/B fixtures with identical IDs for project, client, company, user, warehouse, invoice, counterparty, person, payment and allocation; B records inserted first where ordering could expose global lookups. Prove A responses contain zero B name, code, financial value, Master reference or legacy reference, including foreign related document only in B and missing A relation. Exercise actual route-level HTTP for finance invoice list/detail, offers XLSX/PDF, reports, drilldowns, exports and payment/allocation projections, not helper tests alone. Preserve accepted same-tenant behavior and fail-closed denials.

**Real Mongo and HANDOFF.** Run a disposable local MongoDB bound only to `127.0.0.1`, with fresh empty dbpath, all A/B collision scenarios and zero skipped; verify process/database cleanup. Never use Atlas, NAS, production or real BEG databases. Publish exact new head, new Draft PR URL, full inventory with SAFE/FIXED/BLOCKED evidence, central-layer and guard design, intentionally failing guard demonstration, actual diff, focused/adjacent/HTTP/real-Mongo commands and collected/passed/failed/skipped counts, cleanup, residual limits and final exact-head `W0-03E-A1/C01 HANDOFF`; then STOP Claude. An intermediate push/green run is not HANDOFF.

**Codex independent gate.** Only after observed final HANDOFF, ended Claude session and stable PR head: independently inspect **whole `main`→A1 package**, search for bare protected lookups, prove the static guard catches an injected unsafe lookup, run focused and adjacent regressions and a separate disposable real-Mongo collision matrix with 0 skipped. PASS requires no proven tenant leak, no bare identity lookup in the protected surface, a genuinely effective guard and 100% real-Mongo matrix PASS. Then publish `W0-03E-A1 PASS — TENANT-SAFE DATA ACCESS ARCHITECTURE CLOSED` and separately `W0-03E READY FOR FINAL MERGE DECISION`, without merging. Any residual leak or incomplete central layer is `W0-03E-A1 BLOCKED — CENTRAL TENANT DATA ACCESS INCOMPLETE` with exact evidence; do not fabricate PASS.

**Hard boundaries and lifecycle.** No merge, deploy, production/Atlas/NAS writes, W0-06 implementation, locked FLOW/D edits, new business rule, Claude Routine, duplicate Send, or edits to PR #32/#33. Preserve `MASTER_DATA_MODE=off` inert and shadow non-writing, W0-02 permission, W0-04 AuditEvent, W0-07 Approval fail-closed, historical IDs and financial rules. Publish/validate PENDING before Claude Send; only observed Claude start changes Dispatch to RUNNING/Claude WORKING; only final exact-head HANDOFF changes Codex to REVIEWING; publish final verdict only after independent review. Krum retains merge/deploy and business/security decisions.

## Archived predecessor W0-03E-R1/C01 — final BLOCKED; no automatic correction

## Canonical W0-03E-R1/C01 tenant export remediation — final HANDOFF published; Codex reviewing

**Identity, base and PR.** Repository `krumingo/BEG_Worck`. Task-ID `W0-03E-R1`; Cycle-ID `C01`. New branch `codex/w0-03e-r1-tenant-export` already exists at **exact** `47a0c59a4eac974d7bab144f71c076a5748243d0`, the blocked PR #32 head. Recheck branch SHA, PR #32 status/head, `main` head `bbdb94dafa09a483b35ccdf6ed13604b77b86a96`, and that no R1 run/PR exists before coding. Open one **new Draft PR against `main`** for the final full W0-03E package, clearly linking blocked PR #32 and identifying this as R1 remediation, not C04. Do not edit, close or merge PR #32. Draft is not integration. If a base/head mismatch or duplicate R1 dispatch appears, STOP and report it.

**Read first.** `CLAUDE.md`, this `coordination/ACTIVE.md`, `coordination/README.md`, predecessor `coordination/REVIEWS/W0-03E.md` (especially final C03 review), `docs/architecture/IMPLEMENTATION_WAVES.md`, `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`, `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §6, `docs/architecture/TENANCY_MODEL.md`, applicable locked FLOW/D including `docs/flows/FLOW-032.md`, and the actual PR #32 base-to-head diff. The C03 review's cross-tenant offer XLSX leak is the entry point, not the whole audit boundary.

**Fix, fail closed.** Scope the offer XLSX and PDF `project_id` joins to the **server-resolved tenant** before reading project fields. Audit and fix any other in-scope offer/export helper resolving `project_id`, `client_id`, `company_id`, `user_id`, `warehouse_id` or another legacy identity key without a tenant predicate. When a related document is absent in the caller tenant, do not use another tenant's document or infer an identity from matching IDs/names. Preserve the existing export contract where safe; if a named path cannot be made safe without a new architectural/business decision, mark that exact path BLOCKED with evidence rather than guessing.

**Bounded complete audit.** Inspect offer XLSX and PDF, finance exports, КСС exports, client-invoice exports, report drilldowns and report helpers already in W0-03E scope. HANDOFF must contain a complete table for each actual path: `path | collection | join key | tenant predicate | SAFE/FIXED/BLOCKED`, with code/test evidence. No `ASSUMED SAFE`, no silent omission, no full-repository rewrite. Scope every identity-bearing lookup/aggregation by server-resolved tenant, including all foreign sides of joins.

**Regressions.** Deterministic tenant A/B fixtures with duplicate `project_id`, client, company, user and warehouse IDs; a foreign related document existing only in B; forged/foreign legacy references; both XLSX and PDF leak cases; export/report responses containing **zero** B data, references or derived labels for A. Include negative/fail-closed cases and preserve accepted same-tenant behavior. Cover the actual HTTP export responses, not only helper calls, and prove no forbidden side effects.

**Tests and HANDOFF.** Run focused W0-03E and adjacent W0-03 tests and disposable local real-Mongo tests with exact A/B duplicate-ID fixtures; bind only to `127.0.0.1`, use a new empty dbpath, and clean it up. Count collected/passed/failed/skipped; skipped or unrun is not PASS. Publish the actual remediation diff, full audit matrix, exact new head, new Draft PR URL, test commands/results, remaining limitations and explicit final `W0-03E-R1/C01 HANDOFF`; then STOP Claude. Codex reviews only after observed final HANDOFF and stable PR head, independently checks the **whole `main`→R1 head W0-03E package**, not just R1 delta, repeats focused/adjacent tests and a disposable real-Mongo gate, and reproduces the tenant A/B export responses. If safe, verdict `W0-03E PASS — READY FOR MERGE DECISION`; if any tenant-isolation correctness defect remains, verdict `W0-03E-R1 BLOCKED` and stop for architectural redesign. No automatic next task/cycle.

**Boundaries and lifecycle.** No merge, deploy, Atlas/NAS/production write, real BEG database, W0-06 implementation, locked FLOW/D edit, new business rule, Claude Routine or duplicate session. `MASTER_DATA_MODE=off` and shadow non-writing, W0-02 permission, W0-04 AuditEvent, W0-07 fail-closed Approval and existing financial rules remain intact. Publish/validate `PENDING` before Send; only observed Claude start may set `RUNNING`/Claude WORKING; only exact-head HANDOFF may set Codex REVIEWING; publish verdict only after independent review. User owns merge/deploy/security/business decisions.

## Archived W0-03E/C03 final bounded correction #2 — BLOCKED, budget exhausted

## Canonical W0-03E/C03 final bounded correction #2 — HANDOFF published, Codex reviewing

**Identity and gate.** Repository `krumingo/BEG_Worck`, Task-ID `W0-03E`, Cycle-ID `C03`, same branch `codex/w0-03e-legacy-migration`, same Draft PR #32 against `main`. Correction base and expected current PR head: **`117072c4529cf29af716c5673ad106ab2a0d465b`**. STOP on head or branch mismatch, duplicate active dispatch, or a material requirement conflict. This is the last authorized technical correction; there is no C04. Before implementation, read `CLAUDE.md`, this ACTIVE file and `coordination/REVIEWS/W0-03E.md`, original C01 and C02 assignments below, `docs/architecture/IMPLEMENTATION_WAVES.md`, `IMPLEMENTATION_GATE_MATRIX.md`, `W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` especially §§4.5 and 6, `TENANCY_MODEL.md`, applicable locked FLOW/D, and the actual PR #32 base-to-head diff. Do not treat historical C02 HANDOFF or review as C03 completion.

**Fix the proven `/prices` leak, fail closed.** `backend/app/routes/reports.py` currently scopes `invoice_lines.org_id` but joins `invoices` by bare `invoice_id=id`, allowing tenant B's invoice fields in tenant A's response when IDs collide. Scope every `/prices` invoice/customer/counterparty/company/user lookup by the **server-resolved** tenant, never caller-supplied `org_id`; no global-ID or name fallback. A missing tenant-consistent relation must be omitted or refused according to the existing route contract, without foreign data or references. Add a deterministic A/B duplicate-ID regression proving A's response contains no B name, value or canonical/legacy reference, including `off`, `shadow` and `enforce` modes as applicable.

**Bounded audit and correction of the assigned report/export surface.** Inspect the identity-bearing paths already in W0-03E scope: `/prices`, turnover by counterparty/client, drilldowns, related finance/report lookup helpers, identity-bearing export adapters, and offer/client-invoice report projections where those helpers are used. For each in-scope join or lookup publish `path | collection | join key | tenant predicate | result` with result `SAFE`, `FIXED`, `NOT APPLICABLE` or `BLOCKED`; never `ASSUMED SAFE`. No join by `id`, name, `client_id`, `company_id`, `user_id`, `warehouse_id` or another legacy key may cross a tenant boundary. This is not a full-repo rewrite; if a named in-scope path cannot be made safe without an architectural/business choice, STOP with exact evidence instead of narrowing scope or claiming PASS.

**Adapter helper check.** Inspect C01/C02 legacy-ref resolution, annotations, report/import adapters, AI/OCR pending paths, financial recipient resolution, client/counterparty/company resolution and warehouse/location resolution. Each must use server-resolved tenant context, tenant-scoped queries, cross-tenant legacy-ref refusal and no global-ID or name-based automatic match. Preserve the accepted C02 Advance/Loan identity guard, no financial write on refusal and auditable denial; do not change financial or merge/unmerge business rules.

**Security regressions.** Cover same client, company, user and warehouse IDs in tenant A/B; an A invoice pointing to an ID present only in B; foreign side of a report aggregation present only in B; forged B `legacy_ref`; unmapped recipient; mapped-person mismatch; report drilldown and export leakage; and an import-produced reference read through a report. For every case prove tenant B data does not appear in A response, audit, adapter result or canonical reference. Targeted deterministic and real-Mongo tests may share fixtures, but record each scenario's actual coverage and any gap honestly.

**Implementation HANDOFF.** Work only in the authorized W0-03E correction surface and tests on the same branch/PR. Run focused W0-03E and adjacent W0-03 regressions with exact collected/passed/failed/skipped. Use only a disposable local MongoDB bound to `127.0.0.1` with separate temporary dbpath for real-Mongo `/prices`, turnover, legacy-ref isolation, recipient identity, migration plan/resume, pending mapping, annotations and export/report coverage; no skipped/unrun result may be called PASS. Stop Mongo, drop temporary DB and verify cleanup. Publish the actual diff, coverage table, exact new PR head, test evidence, remaining limitations and **final C03 HANDOFF** in PR #32; then STOP Claude for independent Codex review. Intermediate push is not HANDOFF.

**Codex-only closure after HANDOFF.** Only after the Claude session ends and a stable exact-head HANDOFF is published, Codex independently reviews the **entire PR head**, not merely C03 diff: migration dry-run purity, plan, idempotent resume/checkpoint/retry/reconciliation; Person/Organization roles/Activity/Item/Asset/Location identity, refs/aliases/pending mapping; proven financial recipient and denial audit; assigned reads/writes/import/export/deletion paths and tenant isolation; W0-02 permission, W0-04 AuditEvent, W0-07 fail-closed boundary and safe `MASTER_DATA_MODE`. Codex repeats focused, adjacent and disposable real-Mongo gates. If any correctness defect remains, publish `W0-03E BLOCKED — FINAL CORRECTION CYCLE EXHAUSTED` with exact blocker; do not dispatch C04. If C03 passes, publish `W0-03E PASS — READY FOR MERGE DECISION`, but do **not** merge.

**Separate closure review after C03 PASS only.** Evaluate W0-03A inventory/contract, W0-03B foundation/mapping/intake/normalization/aliases, W0-03C uniqueness, W0-03D merge/redirect/history and W0-03E migration/adapters/isolation. Report `W0-03 IMPLEMENTATION PACKAGE = PASS/OPEN` separately from `FLOW-032 LIVE GATE = PASS/OPEN`; W0-07 Approval may leave the live gate OPEN even if the implementation package passes. Do not infer either gate from business lock or a Draft PR. Only upon W0-03E PASS, prepare a **read-only** W0-06 File Registry package inventorying upload/download/storage routes, local/NAS paths, Drive refs, attachment/file IDs, documents/photos, duplicate stores, providers, missing hash/integrity/version, tenant/deletion/retention dependencies; no W0-06 implementation or dispatch.

**Hard boundaries.** No merge/deploy, Atlas/NAS/production write, real BEG DB, live Master activation/index, locked FLOW/D edit, new business rule, W0-06 code, another PR/branch, Claude Routine or duplicate session. Krum owns merge/deploy and new business/security decisions. Dashboard-first transitions: C03 `PENDING` before Send; `RUNNING`/Claude `WORKING` only after observed start; Codex `REVIEWING` only after exact-head HANDOFF; final verdict only after independent review publication. This assignment is intent, not implementation evidence.

## Canonical W0-03E/C02 bounded correction #1 — final HANDOFF, independent review in progress

Krum accepts Codex's C01 `CHANGES_REQUESTED` verdict and explicitly authorizes one bounded technical correction, without a new business decision. Continue the **same Task-ID W0-03E**, implementation branch `codex/w0-03e-legacy-migration`, and existing Draft PR #32. The **exact correction base head** is `67c172e3066a53d0d6fa5c594997e2b7af0d1747`; stop on any mismatch. This is **Cycle-ID C02**, correction 1 of at most 2, not a new feature or a new PR. Read this ACTIVE file, `coordination/REVIEWS/W0-03E.md`, `CLAUDE.md`, `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §§4.5 and 6, the original C01 assignment below, applicable locked FLOW/D, and the exact PR diff before editing.

Correct **both** independent review findings in one package:

1. **Financial recipient identity.** New Advance/Loan must refer to a proven canonical Master Person. `user_id`, `guest_name` and `person_id` must not describe different people. If a supplied legacy recipient has no proven mapping to the supplied canonical `person_id`, fail closed: no name guess, fuzzy match or automatic person creation. Add deterministic negative regressions for unmapped `user_id` plus a different valid `person_id`; contradictory `guest_name` plus `person_id`; mapped legacy person versus different canonical person; no advance **or payment** persisted on refusal; and canonical auditable denial. Preserve accepted same-person and historical `guest_name` behavior required by §4.5, without changing business rules.
2. **Incomplete adapter coverage.** Inventory the **specific identity-bearing** legacy import, export, report and AI-adjacent paths covered by the original assignment and contract §6, including relevant route/service entry points. Add bounded, tenant-safe adapter coverage and focused tests for those paths; retain old IDs and preserve pending-only AI/OCR/Excel behavior. Do not rewrite unrelated routes, expand to all 3,673 legacy `org_id` uses, or claim missing paths as PASS. If a named in-scope path cannot safely be covered without a new architectural choice, STOP for that exact path with concrete evidence instead of silently narrowing the package.

Run focused W0-03E and adjacent W0-03 regressions; record collected/passed/failed/skipped. Claude may run disposable loopback real-Mongo tests if safely available, but Codex independently repeats the real-Mongo gate after final HANDOFF; skipped/unrun is **not** PASS. Publish the actual diff, exact new PR head, final HANDOFF, path coverage, tests and residual limits in PR #32, then STOP. Codex reviews only after observed final HANDOFF and stable exact head. No automatic new correction if there is another defect; the remaining bounded cycle requires a separate decision. No merge, deploy, Atlas/NAS/production write, locked FLOW/D change, Claude Routine, or other PR change.

## Original W0-03E/C01 implementation assignment — HANDOFF reviewed, CHANGES_REQUESTED

Repository `krumingo/BEG_Worck`; base branch `main` at **exact** `bbdb94dafa09a483b35ccdf6ed13604b77b86a96`; implementation branch `codex/w0-03e-legacy-migration` already exists at that SHA. Task-ID `W0-03E`, Cycle-ID `C01`. Recheck all three identities and confirm there is no other active W0-03E PR/session before editing. Work only on this branch; publish one Draft PR against `main`, then final exact-head HANDOFF and STOP for independent Codex review. An intermediate push is not completion.

Read, in order: `CLAUDE.md`; `docs/architecture/IMPLEMENTATION_WAVES.md` (W0-03 and execution order); `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md` (FLOW-032 gate); `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` (especially §§2–6, W0-03E, §4.5); `docs/architecture/W0-03C_UNIQUENESS_READINESS.md`; `docs/architecture/TENANCY_MODEL.md`; `docs/flows/FLOW-032.md`, `FLOW-002.md`, `FLOW-040.md`, and applicable FLOW-033/034 and locked D decisions. Inspect current `backend/app/master_data/`, tenancy, permissions, audit, all inventoried legacy routes and tests. The contract's dated status summary is historical; live `main` and exact PR evidence supersede it.

Implement the **entire canonical W0-03E legacy migration foundation as one bounded package**, not separate unrelated tasks: inventory/report and deterministic plan; dry-run that provably performs zero writes; per-tenant, batchable, resumable, idempotent execution with lock/checkpoint/schema-version/evidence/retry, explicit validation and reconciliation/rollback strategy; fail-closed ambiguous matches and partial writes. Preserve every old ID through tenant-bound `legacy_refs`, a reverse reference and deterministic resolution; reconcile counts before/after so no legacy reference silently disappears. Canonical Master uses server-resolved `tenant_id`; legacy `org_id` is compatibility evidence only, never a caller override or future tenant key. No cross-tenant guessing, fuzzy auto-merge or hard delete.

Cover all inventoried identity sources: `users`/`persons`/`employee_profiles` → person; `companies`/`clients`/`counterparties`/`subcontractors` → one organization with roles; `work_types`/`smr_groups` → activity; `items` → item; `asset_item_types`/`asset_items`/`asset_units` → asset_type/physical_asset; `warehouses`/`location_nodes` → location; source/external IDs. Ambiguous identity, even an exact name match without authoritative identity, stays a candidate in pending mapping until authorized human confirmation. AI/OCR/Excel never creates official Master as a side effect. Legacy adapters for the affected read/write routes, import/export and reports must allow staged migration while retaining old IDs and tenant checks; do not rewrite the entire backend.

Audit **all seven** delete-by-ID identity paths identified in the contract (`auth.py`, `clients.py`, `counterparties.py`, `locations.py`, `projects.py` person/company, `smr_groups.py`) **plus** `warehouses.py` bulk `delete_many({"org_id": ...})` and relevant asset deletion. Scope the actual delete/archive operation by server-resolved tenant and Master ownership; used identity cannot be hard-deleted; preserve permitted legacy behavior only when demonstrably outside Master ownership. Add cross-tenant and used-record refusal regressions. New advances in enforce mode require official Master Person ID; old `guest_name` advances remain readable and unchanged; a read-only manual-mapping report on a restored copy may propose but never auto-map. Preserve one canonical organization across client/supplier/counterparty/subcontractor roles.

For every W0-03E migration/adapter write: W0-02 permission boundary default deny, server-side tenant guard, W0-04 canonical AuditEvent including denial and correlation/idempotency evidence. Do not migrate all 229 unrelated legacy permission checks. `MASTER_DATA_MODE=off` stays inert, `shadow` stays non-writing, and no production activation occurs. W0-07 Approval runtime remains absent; do not bypass its fail-closed boundary or claim full FLOW-032 gate PASS.

Acceptance tests: positive/forbidden/correction paths for all source collections, aliases, old-ID resolution, same legacy ID and same normalized name in two tenants, forged `org_id`/tenant, cross-tenant `legacy_ref` injection, mapping ambiguity and exact-name non-auto-match, tenant A/B reads and writes, merge redirect/unmerge/history, duplicates, archive/delete refusals, new advance without canonical person, old `guest_name` preservation, AI/OCR/Excel pending behavior, permissions and AuditEvent, idempotent retry/interruption/checkpoint, counts and zero lost references, no silent partial success. Run focused and adjacent W0-03 suites; record collected/passed/failed/skipped. Add real-Mongo tests for a disposable local loopback instance; Claude may run them only if safely available. Codex independently repeats the gate after HANDOFF; skipped is never PASS.

Excluded: new business policy, fuzzy matching thresholds, automatic merge, production data migration, live index build, Atlas/NAS/production writes, `MASTER_DATA_MODE` activation, W0-06 implementation, broad W0-02 cleanup, locked FLOW/D edits, deployment and merge. If the full canonical scope cannot be completed safely in one package, do not quietly shrink it or claim PASS: publish exact partial evidence and STOP with a concrete blocker. Krum remains owner of new business rules, security/access, live operations and merge/deploy decisions.

HANDOFF must give actual diff, exact new head, Draft PR URL, source-to-Master coverage, deletion-path coverage, migration/retry/rollback evidence, permission/audit evidence, focused/adjacent/real-Mongo results and honest residual limits. Then STOP. Codex alone reviews exact head, permits at most two bounded purely technical corrections, and performs independent disposable real-Mongo gate and whole-W0-03 closure review if evidence supports it.

## Archived predecessor context — W0-03D/C02, completed

## Integration result and remaining W0-03 scope
W0-03D is accepted in `main` at merge `bbdb94dafa09a483b35ccdf6ed13604b77b86a96`; the implementation head `ad99598543be60d83c5dbaa29e06a2e8b2063a21` is an ancestor. W0-03 as a whole and FLOW-032 implementation are **not complete**. W0-03E legacy migration, adapters, reference reconciliation and database-per-tenant isolation proof remain; live critical merge also depends on trusted W0-07 Approval evidence. Await a new, explicit GPT/Krum decision before assigning any successor. No production adoption or index build is implied.

## Canonical W0-03D/C02 technical correction assignment — completed, independent PASS
Use only repository `krumingo/BEG_Worck`, branch `codex/w0-03d-merge-redirect`, existing Draft PR #30, and exact C02 base head `dd6ba1a89b4a5a488d91e082f10f82f323b91c22`. Read this ACTIVE file, the final BLOCKED evidence in `coordination/REVIEWS/W0-03D.md`, `CLAUDE.md`, `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §W0-03D, and `docs/flows/FLOW-032.md` before editing. Recheck the remote PR head; stop on mismatch.

Correct only `history()` causal ordering before limit/truncation. Apply the requested limit and hard cap 500 only to causally ordered history, never to an unsorted Mongo cursor. Ensure a returned unmerge cannot lack the merge it reverses because of pre-sort truncation; if a requested limit itself would cut off the causal predecessor, fail closed or provide a bounded, explicit and deterministic response rather than silently presenting a false history. Preserve append-only history, tenant isolation, existing merge/unmerge business rules, Approval behavior, feature-off boundary and unrelated code. No scope expansion, locked FLOW/D changes, merge, deployment, production/NAS/Atlas writes or W0-03E.

Add deterministic regression tests for `merge(seq=1) -> unmerge(seq=2) -> merge(seq=3)`, reverse physical storage order, and `history(limit=2)` showing a causal and deterministic result with no orphaned unmerge. Test the hard cap 500 with more than 500 history events arranged so unsorted truncation would select the wrong causal window. Run focused W0-03D and adjacent W0-03 suites. Run real-Mongo only against a disposable local instance if safely available; report skipped tests separately, never as PASS. Publish one final HANDOFF with exact new head, actual diff, tests, and limitations in the same PR #30; then STOP for independent Codex re-review. This C02 cycle is one bounded correction, not authorization to start C03 automatically.

## Bounded C01 correction assignment — final HANDOFF reviewed; gate BLOCKED
Use the same repository `krumingo/BEG_Worck`, implementation branch `codex/w0-03d-merge-redirect`, Draft PR #30, and exact correction base head `7a84b1721e6d874e0e5f3a140aaf7b288cfc52cd`. Read `coordination/REVIEWS/W0-03D.md` at the current queue head and change only the reviewed defect: preserve append-only history and guarantee causal `merge` → `unmerge` ordering when `recorded_at` timestamps tie. Add a deterministic equal-timestamp regression test and rerun the focused and adjacent W0-03 suites. Do not alter business rules, Approval fail-closed behavior, tenant isolation, unrelated files, locked FLOW/D, or other PRs. Do not merge, deploy, or touch production/NAS/Atlas/secrets. Publish an exact-new-head HANDOFF with actual tests and residual limits, then STOP for independent Codex re-review. This is the only permitted correction attempt; no new Task-ID or cycle.

## Human purpose
Prepare the next FLOW-032 Master Data stage: a human can inspect a proposed merge before it changes anything; historical IDs must continue to resolve, and merge history must remain immutable. This is technical implementation behind the existing feature-off boundary, not authorization to merge real data.

## Canonical authority and prerequisites
Read `CLAUDE.md`, `coordination/README.md`, `docs/architecture/IMPLEMENTATION_WAVES.md`, `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`, `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §6 W0-03D, `docs/architecture/W0-03C_UNIQUENESS_READINESS.md`, `docs/flows/FLOW-032.md`, and applicable locked D decisions. Recheck `main` and queue exact SHAs before editing. PRs #16–#20 completed W0-03A/B/C; PR #20 exact head `e3c4ad8cd5b204eb806c39202cc00dd586bc9049` has independent PASS and 20/20 disposable real-Mongo gate evidence, then merged to `main` at the base SHA above. W0-07 Approval runtime is NOT STARTED, so any critical merge must fail closed until trusted Approval evidence exists; an arbitrary `approval_id` string is not itself approval. No W0-03D or later active implementation PR was found at assignment time.

## In scope — one bounded W0-03D technical package
Implement a feature-off Master Data merge/redirect foundation in `backend/app/master_data/` with focused backend tests and only necessary additive, scoped API/permission wiring:

1. Deterministic, read-only preview for two same-tenant, same-entity-type Master records. Show source, target, references to redirect, alias/identifier and other conflicting fields, and exact planned effects. Preview never writes.
2. A guarded merge operation that verifies a preview/version or equivalent stale-state token, tenant and permission context, idempotency, canonical AuditEvent, and explicit trusted Approval for any critical merge. Since W0-07 is absent, fail closed when trustworthy approval cannot be checked. Do not treat a caller-provided `approval_id` or role alone as proof. Keep `MASTER_DATA_MODE=off` inert and `shadow` non-writing.
3. Preserve the source record and immutable merge history; set `merged_into` without hard delete. Resolve an old ID through redirects to the canonical target while refusing cross-tenant/type redirects and cycles. Reject a redirect cycle before any write.
4. Define safe correction/unmerge semantics that append history rather than erase a merge event; if this cannot be made atomic or safely recoverable with existing primitives, fail closed and report the exact technical limitation in HANDOFF instead of claiming a complete operation.

Use existing W0-01 tenant resolver, W0-02 permission boundary, W0-04 AuditEvent and W0-03 repository/service conventions. Any necessary permission action must be scoped and default-denied. The package may include minimal internal schema additions required for traceable history, but no new business decision or runtime activation.

## Excluded
No auto-duplicate detection, automatic merge, heuristic conflict resolution, legacy migration/adapters (W0-03E), W0-07 Approval runtime, production index build, production/NAS/Atlas writes, deployment, merge to `main`, unrelated refactors, secrets, locked FLOW/D edits or other PRs. No real Master data merge. Keep the new PR Draft.

## Acceptance tests and evidence
Tests must cover preview purity and deterministic conflict/reference reporting; changed-record/stale-preview refusal; same-tenant/type and cross-tenant/type rejection; permissions and denial audit; fail-closed missing/unverified Approval (including forged `approval_id`); `off` and `shadow` non-writing behavior; idempotent retry and interrupted/partial-write recovery; immutable history, old-ID resolution, cycle refusal, no hard delete, correction/unmerge history, and canonical AuditEvent success/failure. Run focused and adjacent W0-03 regression tests. Real Mongo tests may run only against a disposable local instance; mark unavailable/skipped honestly. Publish the actual diff, test commands/results, exact new head, residual risks and a final HANDOFF in one Draft PR; stop Claude's session for independent Codex review. Intermediate push, PR body or green CI is not HANDOFF.

## Stop conditions
STOP without inventing a business rule if canonical FLOW/D leaves a material conflict/Approval choice unresolved. STOP for uncertain base SHA, another active W0-03D task, scope expansion, trusted-Approval bypass, inability to preserve history or tenant isolation, external/production access, merge/deploy request, or need for secrets. Ask Codex to mark BLOCKED with evidence rather than guessing. Codex may send at most one bounded correction after independent review; no next task dispatch after PASS.
