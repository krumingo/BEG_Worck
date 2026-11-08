# FLOW GUARD — състояние

Последен проход: **23** — 08.11.2026 12:50 UTC (периодичен).

## Последно проверен SHA по клон

| Клон / PR | Проверен SHA | Проход | Бележка |
|---|---|---|---|
| `main` | `8c52e92` | 23c | merge #80 (`8c52e92`, docs); merge #69 (`4bca18a`); merge #55 (`cd03324`); по-рано merge PM-01 (#68), ST-02 (#67), AUTH-01/02 (#56), W0-04-C01 (#72), PAY-01 (#70), W0-04-C02 (#78). Бавен преглед: FLOW-002 (1), FLOW-006 (2), FLOW-040 (3), FLOW-028 (4), FLOW-019 (5), FLOW-008 (6), FLOW-024 (7), FLOW-020 (8), FLOW-021 (9), FLOW-005 (10), FLOW-004 (11), FLOW-007 (12), FLOW-003 (13), FLOW-013 (14), FLOW-014 (15), FLOW-016 (16), FLOW-009 (17), FLOW-010 (18), FLOW-011 (19), FLOW-012 (20), FLOW-015 (22), FLOW-017 (23), FLOW-018 (24) |
| #55 `task5c/live-ops-01-canonical-stock-core` | `ed48595` | 15 | слят в main (`cd03324`); склад: FLOW-009/020/008, Р10/Р11/Р13 |
| #56 `claude/auth-owner-recovery-forgot-password-sfv359` | `3234446` | 9 | слят в main (`0f870c3`); auth: FLOW-002/040, Р6, Р19 (D-16) |
| #67 `claude/st-02-staging-stack` | `675faba` | 4 | слят в main (`35ae10b`) |
| #68 `claude/pm-01-permission-matrix` | `4e20084` | 3 | слят в main (`8e3b190`) |
| #69 `claude/sec-01-money-write-permissions` | `faa3da0` | 23 | слят в main (`4bca18a`);  SEC-01 + C01 + C02 + SEC-R1 + C03 (+G) |
| #70 `claude/pay-01-payment-reversal` | `16a886f` | 13 | слят в main (`d226c49`) |
| #71 `claude/sec-02-finance-read` | `021a078` | 24 | SEC-02, Р20/Р31 |
| #72 `claude/w0-04-c01-audit-indexes` | `04e0a1b` | 13 | слят в main (`7b6da64`) |
| #73 `claude/lab-01-labor-cost` | `ef8661c` | 21 | LAB-01, FLOW-019/028 |
| `claude/oh-01-overhead` (OH-01) | `31a9478` | 13 | FLOW-024 |
| `claude/lab-02-quantity-approval` (LAB-02) | `388b81c` | 21 | FLOW-028, Р33 |
| `claude/sub-adv-01-advance` (SUB-ADV-01) | `b313933` | 17 | FLOW-021, Р39/Р40 |
| `claude/act-01-client-act-from-offer` (ACT-01) | `2cc1147` | 15 | FLOW-004 |
| `claude/off-01-offer-version-accept` (OFF-01) | `8dc3c45` | 21 | FLOW-003, FLOW-002 magic link |
| #81 `claude/wh-fix-01-post-55` (WH-FIX-01) | `ac66058` | 24 | FLOW-009/020/008, Р44, Р45; FG-199, FG-215 resolved |
| #82 `claude/wh-rev-01-receipt-reversal` (WH-REV-01) | `1622f62` | 22 | FLOW-009/006, Р46, Р47 |
| #83 `claude/cp-01-counterparty-iban` (CP-01) | `ea51030` | 23 | FLOW-010, Р48 |
| #84 `claude/inv-cn-01-credit-notes` (INV-CN-01) | `5cce932` | 24 | FLOW-006/025/034, Р47, Р49, Р51, Р52 |
| пакети (`claude/happy-meitner-bmcnel`) | `d4946bb` | 23c | Р53, Р52; Р50, Р51; Р48, Р49, CP-01, INV-CN-01; Р46, Р47; Р44, Р45, WH-FIX-01, WH-REV-01; по-рано Р43; OFF-01; Р42; D-17, ACT-01; Р39–Р41, SUB-ADV-01; Р37, Р38; Р33–Р36, LAB-02; OH-01; 5C-C26 I; 5C-C26 G/H; по-рано LAB-01, W0-04-C01 + добавки; по-рано Р28–Р32; по-рано Р25–Р27, 5C-C26, SEC-01-C03, PAY-01-C01, ST-02-C03, SEC-02-A; по-рано Р21–Р24, D-16, PAY-01; преди това Р17–Р20, 5C-C24/C25, AUTH-02, SEC-01-C02, ST-02-C02, добавка SEC-02 |

## Отворени PR, непрегледани в този проход

Стари, без нов commit след 25.10.2026. Ще се прегледат, ако получат нов commit:

- #64, #57, #54, #53, #51, #49, #47, #46, #44, #31, #28, #24, #23, #21, #11, #8.

## Чакащо действие

- Повторният преглед на FLOW-009 след merge на #55 е направен в проход 20b.
- #81 + #82: при сливане да се провери FG-213/FG-214/FG-216 (конкурентни корекции, DQ хранилища, тестове).

## Бавен преглед на main

| FLOW | Проход | Резултат |
|---|---|---|
| FLOW-002 | 1 | `COVERAGE.md` |
| FLOW-006 | 2 | `COVERAGE.md` |
| FLOW-040 | 3 | `COVERAGE.md` |
| FLOW-028 | 4 | `COVERAGE.md` |
| FLOW-019 | 5 | `COVERAGE.md` |
| FLOW-008 | 6 | `COVERAGE.md` |
| FLOW-024 | 7 | `COVERAGE.md` |
| FLOW-020 | 8 | `COVERAGE.md` |
| FLOW-021 | 9 | `COVERAGE.md` |
| FLOW-005 | 10 | `COVERAGE.md` (не е започнат) |
| FLOW-004 | 11 | `COVERAGE.md` |
| FLOW-007 | 12 | `COVERAGE.md` |
| FLOW-003 | 13 | `COVERAGE.md` |
| FLOW-013 | 14 | `COVERAGE.md` |
| FLOW-014 | 15 | `COVERAGE.md` |
| FLOW-016 | 16 | `COVERAGE.md` (не е започнат) |
| FLOW-009 | 17 | `COVERAGE.md` |
| FLOW-010 | 18 | `COVERAGE.md` |
| FLOW-011 | 19 | `COVERAGE.md` |
| FLOW-012 | 20 | `COVERAGE.md` |
| FLOW-015 | 22 | `COVERAGE.md` |
| FLOW-017 | 23 | `COVERAGE.md` |
| FLOW-018 | 24 | `COVERAGE.md` |
| следващ: FLOW-001 (main) | — | — |
