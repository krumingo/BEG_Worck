# FLOW-040 — AuditEvent / AI Audit Log / одит на критичните действия

> **Статус:** 100% — BUSINESS LOCK  
> **Последна проверка:** 21.07.2026  
> **Implementation Gate:** Wave 0 foundation; отделна техническа проверка по FLOW-042  
> **Свързани FLOW:** 002, 006, 016, 025, 030, 031, 032, 033, 034, 042, 043, 044, 045

## 1. Цел

FLOW-040 определя единния одит на BEG_Work и специализирания изглед за AI действията. Той не създава втори журнал.

```text
един AuditEvent source of truth
→ различни permission-filtered изгледи
→ AI Audit, Finance Audit, Security Audit, Project Audit и Personal Audit
```

FLOW-040 трябва да позволява да се докаже:

- кой или коя система е извършила действието;
- в каква роля и обхват;
- какво е било преди и след него;
- по каква причина и чрез кой интерфейс/tool;
- какво е предложил AI;
- кой човек е потвърдил или редактирал предложението;
- какво реално е изпълнено;
- коя версия, документ, Approval и source record са използвани;
- дали събитието е непокътнато и в срока си за съхранение.

## 2. Основен принцип

`AuditEvent` е append-only доказателствен запис.

- Събитие не се редактира и не се изтрива от нормалния интерфейс.
- Грешка в старо събитие се обяснява чрез нов correction/reversal/annotation event, който сочи към оригинала.
- Business record-ът може да бъде архивиран или коригиран, но одитната следа остава.
- FLOW-040 е изглед върху общия AuditEvent, а не паралелен AI лог.
- Dashboard, Timeline, chat history и application logs не заменят AuditEvent.

## 3. Каноничен AuditEvent envelope

Всеки AuditEvent съдържа най-малко:

```text
event_id
tenant_id
occurred_at / recorded_at
actor_type
actor_id / external_principal_id / service_id
effective_role_assignments
scope_type / scope_id
action
source_flow / module
source_channel
entity_type / entity_id / entity_version
before_reference / after_reference / structured_diff
reason / command / trigger
tool_or_endpoint
model_and_version, когато е AI
confirmation_required
confirmed_by / confirmed_at
approval_id
execution_id / execution_status
correlation_id
request_id
idempotency_key
related_file_ids / evidence_ids
retention_class
retention_anchor
sensitivity_class
visibility_scope
integrity_hash / previous_hash / manifest_id
result
error_code, когато има
```

Големи payload-и, документи, снимки, пълни prompt-и и други доказателства не се дублират в event-а. Те се пазят като защитен `AuditEvidence`/`file_id` във FLOW-016 и AuditEvent съдържа неизменяема връзка и checksum.

## 4. Задължително одитирани събития

### 4.1 Идентичност, права и сигурност

- вход, неуспешен вход, logout и session revoke;
- създаване, промяна и прекратяване на RoleAssignment;
- ExternalPrincipal и AccessGrant — издаване, използване, изтичане и revoke;
- permission denied и опит за direct-URL/API заобикаляне;
- промяна на security/retention/audit policy;
- break-glass достъп.

### 4.2 Финансови и договорни действия

- договор, анекс, оферта и версия стават Current/в сила;
- акт, измерване, фактура, Pay Run, obligation и Approval;
- плащане, allocation, correction, reversal, доплащане и удръжка;
- промяна или проверка на банкова сметка;
- ретенция, гаранция и освобождаване;
- document checklist exception по FLOW-025/034.

### 4.3 Оперативни действия

- project status transition, reopen и archive;
- дневен отчет, присъствие, correction и backdate;
- складово/материално движение;
- asset custody, ремонт, липса, отписване и QR движение;
- Work Package version, assignment, scope/budget change и acceptance;
- дефект, отговорност, гаранционна поправка и закриване;
- Master Data merge, alias, split и redirect.

### 4.4 AI действия

- въпрос към BEG Brain;
- използван контекст и разрешени read tools;
- tool call и резултат;
- AI interpretation и confidence-free structured extraction;
- показана чернова;
- предложено мапване, цена, СМР, заявка, маршрут или ресурс;
- поискано човешко потвърждение;
- човешка редакция/потвърждение/отказ;
- официално изпълнение или отказ поради права/DQ/Approval;
- използван модел, tool version, rule version и prompt template version.

## 5. AI → човек → официално действие

Когато AI участва, следата се разделя на отделни свързани събития:

```text
AI_REQUEST_RECEIVED
→ AI_TOOLS_READ
→ AI_DRAFT_SHOWN
→ HUMAN_CONFIRMED / HUMAN_EDITED / HUMAN_REJECTED
→ DOMAIN_ACTION_EXECUTED / DOMAIN_ACTION_FAILED
```

Така се различава:

- грешка в източниковите данни;
- грешка в AI разпознаването;
- човешка редакция/потвърждение;
- грешка в изходния domain service;
- повторна заявка или дублирано изпълнение.

Когато човешко потвърждение е задължително, `DOMAIN_ACTION_EXECUTED` без валиден confirmation/Approval е блокиращ инцидент.

## 6. Retention policy — класове и минимални срокове

Срокът се определя чрез `retention_class`, записан при създаване на събитието. Прилага се по-дългият срок между системния минимум, договорно/регулаторно изискване и активен hold.

### R1 — CRITICAL_BUSINESS

Обхват:

- договори, анекси, оферти и exact-version approvals;
- актове, фактури, плащания, payroll, бонуси и банкови данни;
- critical approvals, Master Data merge, permissions и asset write-off;
- Audit/Retention policy changes;
- AI действия, довели до финансово, договорно или правно значимо действие.

Минимално съхранение:

**10 години** след по-късната приложима anchor дата — приключване на свързания договор/обект/финансов период или последното действие по гаранция/спор.

### R2 — PROJECT_OPERATIONAL

Обхват:

- дневни отчети, присъствие, Work Packages;
- складови, материални и логистични движения;
- asset custody и ремонти;
- quality/defect/warranty operational history;
- project timeline и operational approvals без финансово изпълнение.

Минимално съхранение:

**7 години** след финансовото приключване на обекта или пакета. Ако събитието стане доказателство по финансов, договорен, гаранционен или спорен процес, преминава към R1.

### R3 — SECURITY_ACCESS

Обхват:

- login/logout;
- failed login;
- permission denied;
- session/device/IP security metadata;
- normal access-grant usage без бизнес действие.

Минимално съхранение:

**2 години** от събитието. Промени на права, break-glass и security incidents са R1.

### R4 — AI_CONTENT

Обхват:

- пълно raw prompt/response съдържание;
- транскрипции, които не са станали официално доказателство;
- временни AI debug payload-и.

Минимално съхранение:

- raw conversational content — **12 месеца**;
- structured metadata, tool calls, показана чернова, human confirmation и official action — наследяват R1/R2/R3 според действието;
- конкретен фрагмент, използван като доказателство, се заключва като `AuditEvidence` и наследява срока на source record-а.

### R5 — TECHNICAL_DIAGNOSTIC

Обхват:

- performance traces;
- stack traces без бизнес доказателствена стойност;
- временни diagnostic payload-и.

Минимално съхранение:

**90 дни**, освен ако са свързани с incident, security investigation или business dispute.

### R6 — LEGAL_OR_INCIDENT_HOLD

При спор, проверка, киберинцидент, съдебен/договорен процес или официално разследване събитията и доказателствата се поставят под hold.

- Автоматичното изтичане се спира.
- Hold има основание, scope, поставил, дата и release Approval.
- След release се прилага оставащият нормален срок; не се изтрива незабавно без disposition review.

## 7. Hot storage, archive и disposition

- R1/R2/R3 събитията са индексирани и бързо търсими най-малко **24 месеца**.
- След hot периода могат да преминат в криптиран immutable archive, но остават достъпни чрез одитирана заявка/restore.
- R4 и R5 следват по-кратките си срокове и data-minimization правилата.
- Политиката е versioned. Промяната ѝ не съкращава автоматично вече записан critical retention срок.
- Изтичането се изпълнява от контролиран retention job, не от ръчен Delete бутон.
- Disposition създава собствен AuditEvent и подписан manifest: клас, период, брой записи, hash, policy version, hold check и одобрил.
- При изисквана анонимизация личните полета могат да бъдат pseudonymized, но event ID, timestamp, action, source и integrity chain се запазват, доколкото е допустимо.

## 8. Immutable / tamper-evident storage

Минималният бизнес стандарт е:

- append-only primary event store;
- забранени update/delete операции за нормални роли и AI;
- correction чрез нов event;
- hash chain или подписан batch manifest по tenant и период;
- периодичен checksum/integrity verification;
- immutable/WORM архивно копие извън основната write зона;
- отделен off-site backup по FLOW-044;
- възможност индексът да бъде rebuild-нат от immutable archive;
- аларма при липсващ sequence, hash mismatch, неподписан batch или backup gap.

Изтриване на audit storage, промяна на retention policy, release на hold и break-glass export са критични действия с независимо Approval и собствен AuditEvent.

## 9. Data minimization и чувствителни данни

AuditEvent не трябва да пази:

- пароли;
- access/refresh tokens;
- API keys;
- storage credentials;
- пълни банкови данни, когато masked reference е достатъчен;
- излишни лични данни;
- цял документ/payload, когато checksum и file_id са достатъчни.

Правила:

- secrets се премахват преди запис;
- банкови сметки, лични номера, заплати и PII се маскират според ролята;
- before/after използва field-level diff и references;
- raw AI content е отделно от structured action trail;
- export-ът прилага същата permission и masking политика като екрана.

## 10. Нива на видимост

### L0 — Personal Audit

Потребителят вижда:

- собствените си действия;
- своите потвърждения, откази и корекции;
- собствените си AI разговори в рамките на срока;
- отказаните му действия и причината, без да получава забранени данни.

### L1 — Scoped Operational Audit

Виждат се operational events само в разрешения project/location/module scope, с маскирани чувствителни полета.

### L2 — Sensitive Domain Audit

Finance, payroll, contract, HR, security или quality audit в изрично назначен domain scope.

### L3 — Full Tenant Audit

Read-only изглед върху целия tenant, с masking на secrets и допълнителна защита за highly sensitive content.

### L4 — Export / Forensics

Пълен доказателствен export, integrity manifest и свързани AuditEvidence записи. Изисква re-authentication, причина и Approval според политиката.

### L5 — Break-glass Platform Access

Временен достъп при incident/restore/support, само към необходимия scope, с две независими одобрения, срок, автоматичен revoke и пълен audit.

## 11. Канонична роля → видимост матрица

| Роля / actor | Разрешен изглед | Ограничения |
|---|---|---|
| **Крум / Owner** | L3 за целия tenant; L4 export | secrets винаги masked; highly sensitive export изисква причина, re-authentication и policy Approval |
| **Изричен Auditor / Compliance** | L3 read-only; L4 при отделно право | не редактира domain records; export-ът и чувствителните търсения се одитират |
| **Администратор** | L1/L2 за administration, permissions, integrations и security според assignment | няма автоматичен достъп до payroll, банково съдържание или лични AI разговори без отделно sensitive-domain право |
| **Finance / Accounting / Payroll** | L2 в своя финансов/payroll scope | не вижда несвързани лични разговори, project chat или други domain данни |
| **Project Manager** | L1 за назначените обекти; ограничен contract/approval trail | не вижда заплати, лични данни, банкови полета и фирмен audit извън scope |
| **Технически ръководител / Склад / Логистика / Quality** | L1 в назначените обекти и модули | вижда operational actions и собствените си решения; чувствителните суми/лични данни са masked |
| **Служител / Работник** | L0 | няма достъп до чужди personal events или общия audit |
| **ExternalPrincipal / клиент / партньор** | само собствените AccessGrant, ApprovalReceipt и изрично споделени document events | няма достъп до вътрешен audit, margins, payroll, subcontractor или AI operations |
| **AI service role** | наследява най-малкия scope на конкретния invoking user/tool | няма собствен L3/L4 достъп; не може да редактира/изтрива audit; всяко четене/tool call се одитира |
| **Platform support / DR operator** | system-health metadata; L5 само при incident | business content само чрез break-glass, две одобрения и time-bound access |

По-ограниченото правило между RoleAssignment, module, project, sensitivity и event visibility има предимство.

## 12. Одит на самия одит

Следните действия задължително създават AuditEvent:

- преглед на highly sensitive event;
- full-tenant search от L3 роля;
- export;
- break-glass access;
- промяна на retention/visibility/masking policy;
- legal/incident hold и release;
- integrity verification failure;
- disposition;
- restore/rebuild на audit index.

Audit viewer никога не може да изключи одитирането на собствените си действия.

## 13. Търсене и изглед за Крум

Филтри:

- период;
- actor / роля / ExternalPrincipal / AI;
- tenant, обект, location и Work Package;
- FLOW / module;
- action и entity;
- tool, model и prompt-template version;
- confirmed / rejected / failed / denied;
- financial/contractual effect;
- automatic low-risk action;
- voice command;
- permission/security event;
- retention class, hold и archive state;
- correlation/idempotency key.

Крум трябва да вижда:

- какво е предложил AI и какво е редактирал човекът;
- кой е потвърдил;
- какво е било изпълнено;
- before/after diff;
- source records, files и approvals;
- повторни заявки и блокирани дубликати;
- действия без достатъчна информация;
- denied access и break-glass;
- integrity/backup/retention проблеми;
- историята на correction/reversal.

## 14. Export

Доказателственият export съдържа:

- филтрирания набор от събития;
- manifest с tenant, период, query, policy version и generated_at;
- hashes/checksums и chain verification result;
- references или разрешени копия на AuditEvidence;
- masking report;
- кой е поискал и одобрил export-а;
- export AuditEvent.

Export-ът не променя оригиналните събития и не дава повече данни от разрешения scope.

## 15. Какво НЕ трябва да позволява

- edit/delete на AuditEvent от UI, AI или нормален API;
- отделен скрит AI audit регистър;
- event без tenant, actor, timestamp, action и source;
- критично действие без before/after или source evidence;
- official AI action без показана чернова и изискуемо човешко потвърждение;
- raw secret/token/password в лога;
- общ администратор автоматично да вижда payroll, банкови и лични разговори;
- external principal да вижда вътрешен audit;
- export без reason, scope и audit;
- retention job да изтрие записи под hold;
- промяна на retention class със задна дата без Approval и AuditEvent;
- disposition без signed manifest;
- AI да използва audit като начин да заобиколи нормалните domain permissions.

## 16. Минимална проверка преди Implementation Gate

- canonical AuditEvent schema и critical-write coverage map;
- append-only enforcement и correction event;
- hash chain/signed manifest verification;
- immutable archive + FLOW-044 backup/restore test;
- retention-class assignment tests;
- hot→archive→restore test;
- legal/incident hold и blocked disposition test;
- role/field/scope permission matrix tests;
- secret/PII masking tests;
- audit-of-audit, export и break-glass tests;
- correlation между AI request, draft, human confirmation, Approval и domain execution;
- idempotency/retry test;
- performance и search test при голям обем;
- rebuild на индекса от immutable archive.

## 17. Източници / сесии

- Каноничен архив FLOW-001–043.
- FLOW-043 — един общ AuditEvent и Business Lock ≠ Implementation Gate.
- FLOW-002 — RoleAssignment, ExternalPrincipal и permissions.
- FLOW-016/025 — File Registry, document versions и evidence.
- FLOW-030/031/045 — BEG Brain, agent-шапки и confirmation-before-action.
- FLOW-034 — Approval и controlled exceptions.
- FLOW-044 — immutable/off-site backup и restore.
- FLOW-040 business-close pass: 21.07.2026 — retention classes, immutable storage и visibility matrix.