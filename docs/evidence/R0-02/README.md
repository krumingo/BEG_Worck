# R0-02 — evidence: items tenant filter + guard (AUD-026)

Task package: `docs/architecture/tasks/R0-02_ITEMS_TENANT_FILTER.md` (on `claude/happy-meitner-bmcnel`).
FLOW-002, FLOW-032, FLOW-009 · W0-01 / W0-03E-A2C. Draft PR, not merged.

## Bot test (local copy, test data only)

| Part | How it ran |
|---|---|
| MongoDB | Docker `mongo:7.0` (server 7.0.45), published on `127.0.0.1:27018` only, single-node replica set |
| Backend | `uvicorn server:app` on `127.0.0.1:8001`; `DB_NAME=r002_bot`, `BEG_SYSTEM_DB=r002_bot_system`, `ENV=test`, a random per-run `JWT_SECRET` |
| Frontend | `yarn build` with `REACT_APP_BACKEND_URL=http://127.0.0.1:8001`, served as a SPA on `127.0.0.1:3000` |
| Seed | `seed_two_tenants.py`, through the real API only: `/billing/signup` per tenant, the Owner creates one Admin (`/users`) and the items (`/items`) |
| Bot | `items_bot.js`, Playwright 1.56.1 with the preinstalled Chromium (`/opt/pw-browsers/chromium`) |

Tenant A: 3 items (`A-CEM`, `A-DRL`, `A-GLV`). Tenant B: 4 items (`B-BRK`, `B-SAW`, `B-TAP`, `B-SCF`).

| # | Step | Result | Evidence |
|---|---|---|---|
| 1 | Admin A logs in through the UI and opens `/data/items` | PASS — 3 A SKUs, 0 B SKUs | `01_admin_A_items.png` |
| 2 | Same browser session requests `/api/items?filters=org_id=<B org_id>` | PASS — `400 {"detail":"Invalid filter: field 'org_id' cannot be filtered"}`, no B SKU in the body | `02_admin_A_attack_org_id_B_400.png`, `bot_result.json` |
| 3 | Admin B logs in and opens `/data/items` | PASS — 4 B SKUs, 0 A SKUs | `03_admin_B_items.png` |

`bot_result.json` holds every assertion and the raw attack response. The bot exits 0 only when all of them hold.

Reproduce (after starting MongoDB, the backend and the static frontend as above):

```
python seed_two_tenants.py http://127.0.0.1:8001 > seed.json
NODE_PATH=$(npm root -g) node items_bot.js http://127.0.0.1:3000 http://127.0.0.1:8001 seed.json .
```

The passwords in the seed and bot scripts are throwaway values for a disposable local database. They are not credentials.
