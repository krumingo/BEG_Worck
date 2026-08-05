# FLOW-042 Business Close — 28.07.2026

> **FLOW:** Release / QA / Test Center  
> **Резултат:** 40% → **100% Business Lock**  
> **PR:** Draft PR #2 — не се слива автоматично

## 1. Каноничен тестов модел

- Един постоянен `Test Case` описва едно бизнес правило.
- Всеки branch/commit/release има отделен `Test Run`.
- Неуспешните runs остават в историята.
- `Business Acceptance` е отделно решение на Крум.

Всеки Test Case съдържа allowed, forbidden, permission, correction/reversal, audit, DQ/Approval, idempotency/offline и UI очаквания.

## 2. Severity и release blockers

- `P0` — пълен STOP, rollback/hotfix при production.
- `P1` — блокира засегнатия release.
- `P2` — допуска се само `Прието с условие`, с отговорник, срок и workaround.
- `P3` — не блокира и влиза в backlog.

Критичен failed test или regression не се скрива в общ процент.

## 3. Product Test Center

Има отделни изгледи:

- управленски за Крум;
- технически за разработчици и QA.

Крум вижда какво е променено, какво точно да провери, доказателствата, отворените дефекти и точната test/staging среда.

AI и Emergent могат да предлагат тестове и да обобщават, но не могат да дадат финално приемане или release approval.

## 4. Физическо разположение

```text
GitHub
→ код, branch, commit, PR и техническа история

TEST/STAGING WEB среда
→ реалният PC тест от Крум

Product Test Center в BEG_Work
→ тестове, среда, evidence и решение
```

До реализацията на runtime модула се използва Bootstrap QA Gate v0 в GitHub.

## 5. Клиентски достъп

Пълният Product Test Center е вътрешен.

Клиентът може да получи само ограничен `Tenant Acceptance Portal` за собствената си персонална разработка, test environment и test data. Няма достъп до GitHub, кода, вътрешните дефекти или други tenant-и.

## 6. Release Manifest

Всеки deployment изисква:

```text
target_type
tenant_id
environment_id
branch
commit_sha
PR
release_candidate
feature_flags
migration_version
rollback_version
```

Emergent не избира deployment target по свободен текст. Липсващо или несъвпадащо поле блокира deployment-а.

Core и tenant-specific разработките използват различни targets. Tenant-specific feature се активира само за определения tenant след необходимото Product/Tenant Acceptance.

## 7. Ново архитектурно откритие

Нужен е бъдещ отделен:

`FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements`.

Той не се включва още в официалната бройка FLOW-001–049.

## 8. Решение

FLOW-042 е **100% Business Locked**. Runtime Test Center и Bootstrap QA foundation се реализират във Wave 0, но технически PASS се доказва отделно по собствените правила на FLOW-042.
