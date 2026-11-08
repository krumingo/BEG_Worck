# ST-02-C02 — staging по подразбиране в shadow (Р15)
> ОДОБРЕНА (Р9, Р15). PR #67, клон `claude/st-02-staging-stack`. FLOW Guard FG-2 (доказано): staging тръгва с `PERMISSION_SERVICE_MODE=enforce`; пакетът ST-02 ред 13 също казва enforce — **поправено от Р15: shadow**.
Поправка: стойност по подразбиране `shadow` в скриптовете, README и тестовете; `enforce` само с изричен параметър; тест, че по подразбиране е shadow. Плюс FG-3…FG-6 (medium/low от `docs/flow-guard/DIVERGENCES.md` @ `claude/flow-guard`), ако са в обхвата на #67 — всяко поправено или обосновано в HANDOFF.
Проверки: ST-02 тестове, ops/release, R0, W0 1085/15/50, A2C/A1 0. `HANDOFF ST-02-C02`.
