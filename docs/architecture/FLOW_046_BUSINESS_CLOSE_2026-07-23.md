# FLOW-046 Business Close — 23.07.2026

> **FLOW:** Client Portal / Клиентски портал  
> **Резултат:** 80% → **100% Business Lock**  
> **PR:** Draft PR #2 — не се слива автоматично

## Затворени решения

### 1. Хибриден достъп

Приети са три режима върху един и същ external-access модел:

```text
Еднократно действие
→ защитен линк + код + exact resource/version AccessGrant

Продължителен обект
→ постоянен клиентски профил

Фирмен клиент
→ няколко ExternalPrincipal представители с различни права
```

Контактът не получава автоматично право да одобрява цена, договор или анекс. Правата са по tenant, организация, обект, resource/version, действие, срок и при нужда сума.

### 2. Allowlist клиентска видимост

Запис към същия обект не става автоматично клиентски видим.

Каноничните нива са:

```text
INTERNAL
CLIENT_AUTO_SAFE
CLIENT_REVIEW_REQUIRED
SHARED_WITH_SPECIFIC_PRINCIPALS
SECURE_LINK_ONLY
```

Клиентът вижда официалните оферти, договори, анекси, актове, фактури, плащания, аванси, ретенции, разрешени снимки, прогрес и клиентски Timeline. Не вижда себестойност, марж, payroll, вътрешен чат, вътрешни бюджети, подизпълнителски цени или непубликувани AI изводи.

### 3. Контекстна официална комуникация

Порталът е каноничната клиентска история. Нишките са към конкретен обект, оферта/версия, технически избор, договор/анекс, акт, фактура, промяна, рекламация или документ.

Приети са четири типа съобщения:

```text
Comment
Question
DecisionRequest
OfficialNotice
```

Email и SMS уведомяват и водят към точната нишка/карта. Verified email reply може да се импортира в правилния контекст. Свободно `ОК`, прочитане на съобщение или телефонен разговор не създават договорно одобрение.

### 4. Exact-version ApprovalReceipt

Официалното решение винаги е към точен resource/version/hash и пази:

- ExternalPrincipal;
- timestamp;
- обхват, количество, цена, ДДС и срок;
- verification method;
- file/evidence IDs;
- AuditEvent correlation;
- последващо създадените записи.

Нова версия обезсилва старите неприключени approval links. Клиентското одобрение не заобикаля FLOW-002, FLOW-025 и FLOW-034 и не извършва автоматично покупка или плащане.

## Важни инварианти

- Portal, magic link и persistent profile използват един Permission/AccessGrant модел.
- Client view е отделна безопасна проекция, не директен изглед към вътрешния запис.
- Internal и client communication threads не се смесват.
- `Прочетено ≠ одобрено`.
- AI summary не е official approval.
- Клиентската финансова картина чете FLOW-006 и не създава втори ledger.
- Всеки publish/read/reply/approve/reject/revoke/denied event е одитиран.

## Implementation Gate

Business Lock не означава готов runtime. Wave 4 трябва да докаже:

- ExternalPrincipal, corporate representatives, persistent profiles и scoped AccessGrants;
- OTP/MFA, expiry, revoke, session/device и tenant isolation;
- authority matrix по object/resource/action/amount;
- allowlist visibility и forbidden-leak tests;
- separate internal/client threads и message contracts;
- inbound email mapping и ambiguous-context confirmation;
- exact-version ApprovalReceipt и invalidation;
- Decision Inbox и client-safe AI summary/Timeline;
- restricted financial read model;
- AuditEvent, rollback/revoke, accessibility, mobile и performance tests.

## Обновен прогрес

```text
Business Locked:          40
Активни незавършени:       8
Legacy:                    1
Оставащи решения:         40
```

## Следващ business-close приоритет

1. FLOW-012, FLOW-037, FLOW-041 и FLOW-042 — по 4 решения;
2. FLOW-038 и FLOW-039 — по 5 решения;
3. FLOW-048 — 6 решения;
4. FLOW-049 — 8 решения.
