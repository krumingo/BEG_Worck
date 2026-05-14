# BASELINE_M19_10_CLEAN.md
## M19.10 Clean Production Baseline — Заключващ документ

**Дата:** 2026-05-14 14:56 UTC
**Автор:** Emergent Agent (read-only audit)
**Preview:** https://client-registry-17.preview.emergentagent.com

---

## 1. Executive Summary

Текущото състояние на кода е **M19.10 Clean Production Baseline**.

- F7 (Expenses / Cost Allocations) е **напълно rollback-нат**. Нито един F7 файл, route, модел, nav item или i18n ключ не съществува в кода.
- Кодът е byte-perfect identical с production ZIP 058.
- Този документ служи като **reference point** за всички бъдещи промени, включително планираната M9 overhead интеграция.

---

## 2. Проверка на CHANGELOG

| Проверка | Резултат |
|---|---|
| Последен entry | `[M19.10] - 2026-05-11 — UI преименуване: яснота на заглавията за труд и режийни` |
| F7 entries | **Липсват** (няма F7.1, F7.2, F7.3 записи) |
| M19.10 преименувания | Запазени ("Натрупан труд", "Труд по активности", "Фирмени режийни", etc.) |

---

## 3. Проверка за F7 файлове

| Файл | Статус |
|---|---|
| `backend/app/models/cost_allocations.py` | NOT FOUND |
| `backend/app/routes/cost_allocations.py` | NOT FOUND |
| `frontend/src/pages/ExpensesListPage.js` | NOT FOUND |
| `frontend/src/components/ExpenseFormModal.js` | NOT FOUND |

**Заключение:** Нито един F7 файл не съществува.

---

## 4. Проверка за F7 references в кода

| Търсен термин | Намерени файлове | Статус |
|---|---|---|
| `cost_allocations` | 0 | CLEAN |
| `ExpensesListPage` | 0 | CLEAN |
| `ExpenseFormModal` | 0 | CLEAN |
| `nav.expenses` | 0 | CLEAN |
| `"/expenses"` | 0 | CLEAN |
| `F7` | 0 | CLEAN |

**Забележка:** `revenue_expense` (server.py ред 194) и `"expenses": "Разходи"` (bg.json) са pre-existing M5 finance модул — НЕ са F7.

---

## 5. Проверка на routes / nav / i18n

| Компонент | Проверка | Резултат |
|---|---|---|
| `server.py` | Няма `include_router` за F7/cost_allocations | CLEAN |
| `server.py` | Startup indexes — няма F7 indexes | CLEAN |
| `App.js` | Няма F7 route (`/expenses`, etc.) | CLEAN |
| `DashboardLayout.js` | Няма F7 nav item | CLEAN |
| `bg.json` | Няма `nav.expenses` ключ | CLEAN |
| `en.json` | Няма `nav.expenses` ключ | CLEAN |

---

## 6. Хешове / Baseline Evidence

```
Команда: find backend frontend memory -type f (excluding node_modules, __pycache__, build, dist, .git, venv, *.pyc) | sort | xargs sha256sum | sha256sum
Дата/час: 2026-05-14 14:56:44 UTC
Резултат: 58a6a5f028f67dabd006db3cfd8c4e10dcf3688b2a2de6423a1c8011d97f9e60
Git HEAD: 5bb1d35
```

Сравнение със ZIP 058: **byte-perfect identical** (потвърдено при rollback проверката).

---

## 7. Какво Е включено в baseline

| Модул | Описание | Статус |
|---|---|---|
| M19.8 | Per-line overtime split + frozen approval | Production |
| M19.9 | Running-total overtime + GroupedReportsTable | Production |
| M19.9.1 | Hotfix: rows sort by created_at in groups | Production |
| M19.10 | UI преименуване — яснота на заглавията | Production |
| F7.1 | Expenses CRUD + Cost Allocations | **Rolled back** |
| F7.2 | Expenses UI + Nav integration | **Rolled back** |
| F7.3 | Overhead link to expenses | **Rolled back** |

---

## 8. Какво НЕ е включено в baseline

- Няма нов F7 expenses модул
- Няма cost_allocations модел / API / UI
- Няма нова интеграция на режийни
- Няма нов payment link за overhead
- Няма cost_center поле
- Няма unified expenses view
- Няма expenses collection в MongoDB
- Няма cost_allocations collection в MongoDB

---

## 9. Риск и Rollback Note

**Ако бъдеща M9 интеграция счупи нещо:**
- Връщаме се към **този baseline** (commit `5bb1d35`, checksum `58a6a5f0...`).
- CHANGELOG последен entry: M19.10.
- MongoDB: 4 collections (`media_files`, `organizations`, `subscriptions`, `users`).

**Доказателства за clean baseline:**
- Секция 3: F7 файлове — NOT FOUND
- Секция 4: F7 references — 0 намерени
- Секция 5: Routes/nav/i18n — CLEAN
- Секция 6: Checksum записан

**Как да се използва този документ:**
- При съмнение за регресия — сравни текущия checksum с `58a6a5f0...`
- При нужда от rollback — върни се към commit `5bb1d35`
- При code review на M9 — провери че нищо от секция 8 не е добавено без explicit approval

---

## 10. Финално заключение

| | |
|---|---|
| **Baseline статус** | ЗАКЛЮЧЕН |
| **Блокери** | Няма |
| **Готовност за Стъпка 1** | Може да се започне M9 read-only audit |
