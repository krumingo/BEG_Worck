# ST-02-C03 — режимът в Release Manifest + нова репетиция
> ОДОБРЕНА (Р15, Р25, Р26). PR #67 @ 98b18ec. Codex: не.
1. **Р26:** staging deployment записва `PERMISSION_SERVICE_MODE` и Feature Flags snapshot в Release Manifest на deployment-а (ops/release, W0-09A формат). Ако схемата на manifest-а няма поле — добави го обратно съвместимо и с валидация; съществуващите manifest-и остават валидни. Проверката след smoke сравнява manifest ↔ staging ↔ работещия backend; разминаване → fail/rollback.
2. **Р25:** без външна Mongo; тест, че `ST02_ALLOWED_MONGO_HOSTS` отказва старта, остава.
3. **Нова репетиция** (Docker, само локално, без Synology/production): в `shadow`, с именуван deployer/approver; deploy → smoke → rollback. Обнови evidence README и замени старата репетиция с `actor: "unknown"` (старата остава като история, не се трие).
Тестове: ST-02, ops/release, R0, W0 (същите 15), A2C/A1 0. `HANDOFF ST-02-C03`.
