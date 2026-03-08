# CHANGELOG

## Mar 8, 2026 (Session 2)
### P0: Complete Invoice Workflow Fix
- **Invoice → Project Link**: "Към обекта" button in header navigates to linked project
- **PDF Export**: GET /api/finance/invoices/{id}/pdf - reportlab with DejaVu Cyrillic font, clean A4 layout
- **Full Editing**: Sent/PartiallyPaid/Overdue editable. Paid/Cancelled blocked. Line edits recalculate remaining with existing payments
- **ROOT FIX - Payment→Project Sync**: Project dashboard used non-existent fields (total_ex_vat, client_id). Fixed to use paid_amount, remaining_amount, counterparty_name. Balance.income now aggregates from actual payments, not just Paid status
- **Project Invoice Table**: New columns (Статус badge, Общо, Платено, Остатък). Old broken columns (paid_ex_vat etc.) removed
- **UX Header**: Ordered buttons: Запази, Към обекта, PDF, Добави плащане, Анулирай, Изтрий
- Test report: /app/test_reports/iteration_17.json (100% backend, 100% frontend, 16 tests)

## Mar 8, 2026
### P0: Invoice Numbering Verification
- Verified auto-numbering system with 7 test scenarios
- Start number 1000, sequential INV-1000/1001/1002
- No duplicates, no re-numbering on re-open
- Settings UI at Company Settings → Invoice Numbering

### P0: Invoice Payments + Automatic Invoice Status Logic
- New API: POST /api/finance/invoices/{id}/payments (quick-pay: creates payment + allocation in one step)
- New API: GET /api/finance/invoices/{id}/payments (payment history)
- New API: DELETE /api/finance/invoices/{id}/payments/{alloc_id} (remove payment with status recalc)
- Automatic status transitions: Draft → Sent → PartiallyPaid → Paid / Overdue → Cancelled
- Status recalculation on payment add/remove (incl. Paid → PartiallyPaid → Sent/Overdue)
- Over-payment prevention
- Frontend: Inline payment dialog with quick-pay buttons (full, 50%)
- Frontend: Payment history panel with details
- Frontend: Progress bar and payment summary in sidebar
- Frontend: Bulgarian status labels
- Fix: update_invoice_status correctly handles reverting from PartiallyPaid when all payments removed
- Test report: /app/test_reports/iteration_16.json (100% backend, 100% frontend)
