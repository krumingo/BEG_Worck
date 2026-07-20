# Master Knowledge Base Seed

## Core domains
- Master Data — FLOW-032
- Permissions — FLOW-002
- Projects — FLOW-001
- Offers — FLOW-003/023
- Acts — FLOW-004
- Contracts — FLOW-005
- Finance — FLOW-006/008
- Extra works — FLOW-007
- Inventory — FLOW-009
- Assets — FLOW-011
- Logistics — FLOW-012
- Presence/Labor — FLOW-013/014
- Materials — FLOW-020
- Subcontractors — FLOW-021
- Payroll — FLOW-028
- Media — FLOW-029
- Approval — FLOW-034
- Audit — AuditEvent/FLOW-040

## Non-negotiable invariants
1. Един Master ID.
2. Без hard delete на използвани записи.
3. Един финансов регистър.
4. Net/VAT/Gross отделно.
5. Одобрено/платено не се редактира тихо.
6. Всеки факт има scope.
7. Quantity задължително при акорд/измерване/прогрес.
8. Presence → Report → Approved Labor → Obligation → Payment.
9. AI предлага; човек потвърждава.
10. Derived views не са source of truth.
11. Idempotency за импорт/OCR/delivery/payment/sync.
12. Audit envelope за критични действия.
