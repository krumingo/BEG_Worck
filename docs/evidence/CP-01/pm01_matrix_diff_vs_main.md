| method | path | main → CP-01 (status/wrote × cells) |
|---|---|---|
| DELETE | /api/counterparties/{counterparty_id}/unlink-client | 404/no→428/no ×9 |
| PATCH | /api/projects/{project_id}/client-link | 200/yes→403/no ×15; 200/yes→428/no ×9 |
| POST | /api/clients | 201/yes→428/no ×9 |
| POST | /api/clients/company | 400/no→403/no ×15; 400/no→428/no ×9 |
| POST | /api/clients/find-or-create | 200/yes→403/no ×15; 200/yes→428/no ×9 |
| POST | /api/clients/person | 201/yes→403/no ×15; 201/yes→428/no ×9 |
| POST | /api/companies | 201/yes→403/no ×15; 201/yes→428/no ×9 |
| POST | /api/counterparties | 201/yes→428/no ×9 |
| POST | /api/counterparties/{counterparty_id}/auto-link-client | 404/no→428/no ×9 |
| POST | /api/counterparties/{counterparty_id}/link-client | 404/no→428/no ×9 |
| POST | /api/persons | 201/yes→403/no ×15; 201/yes→428/no ×9 |
| POST | /api/subcontractors | 201/yes→403/no ×15; 201/yes→428/no ×9 |
| PUT | /api/clients/{client_id} | 404/no→428/no ×9 |
| PUT | /api/companies/{company_id} | 404/no→403/no ×15; 404/no→428/no ×9 |
| PUT | /api/counterparties/{counterparty_id} | 404/no→428/no ×9 |
| PUT | /api/persons/{person_id} | 404/no→403/no ×15; 404/no→428/no ×9 |

New routes (528 cells):

| method | path | status/wrote × cells |
|---|---|---|
| GET | /api/counterparties/{party_id}/bank-accounts | 403/no ×15, 404/no ×9 |
| GET | /api/subcontractors/{party_id}/bank-accounts | 403/no ×15, 404/no ×9 |
| POST | /api/bank-accounts/{account_id}/approve-change | 403/no ×18, 428/no ×6 |
| POST | /api/bank-accounts/{account_id}/reject | 403/no ×18, 428/no ×6 |
| POST | /api/bank-accounts/{account_id}/verify | 403/no ×18, 428/no ×6 |
| POST | /api/clients/{record_id}/archive | 403/no ×18, 428/no ×6 |
| POST | /api/clients/{record_id}/deactivate | 403/no ×15, 428/no ×9 |
| POST | /api/clients/{record_id}/reactivate | 403/no ×15, 428/no ×9 |
| POST | /api/companies/{record_id}/archive | 403/no ×18, 428/no ×6 |
| POST | /api/companies/{record_id}/deactivate | 403/no ×15, 428/no ×9 |
| POST | /api/companies/{record_id}/reactivate | 403/no ×15, 428/no ×9 |
| POST | /api/counterparties/{counterparty_id}/archive | 403/no ×18, 428/no ×6 |
| POST | /api/counterparties/{counterparty_id}/deactivate | 403/no ×15, 428/no ×9 |
| POST | /api/counterparties/{counterparty_id}/eik-change/approve | 403/no ×15, 428/no ×9 |
| POST | /api/counterparties/{counterparty_id}/eik-change/reject | 403/no ×15, 428/no ×9 |
| POST | /api/counterparties/{counterparty_id}/reactivate | 403/no ×15, 428/no ×9 |
| POST | /api/counterparties/{party_id}/bank-accounts | 403/no ×15, 428/no ×9 |
| POST | /api/persons/{person_id}/egn/reveal | 403/no ×18, 404/no ×6 |
| POST | /api/persons/{record_id}/archive | 403/no ×18, 428/no ×6 |
| POST | /api/persons/{record_id}/deactivate | 403/no ×15, 428/no ×9 |
| POST | /api/persons/{record_id}/reactivate | 403/no ×15, 428/no ×9 |
| POST | /api/subcontractors/{party_id}/bank-accounts | 403/no ×15, 428/no ×9 |
