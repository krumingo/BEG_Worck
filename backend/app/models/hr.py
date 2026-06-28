"""
Pydantic models - HR / Payroll (M4).
"""
from pydantic import BaseModel
from typing import Optional, List

PAY_TYPES = ["Monthly", "Akord"]
PAY_SCHEDULES = ["Weekly", "Monthly"]
ADVANCE_TYPES = ["Advance", "Loan"]
ADVANCE_STATUSES = ["Open", "Closed"]
PAYROLL_STATUSES = ["Draft", "Finalized", "Paid"]
PAYSLIP_STATUSES = ["Draft", "Finalized", "Paid"]
PAYMENT_METHODS = ["Cash", "BankTransfer"]

class EmployeeProfileCreate(BaseModel):
    user_id: str
    pay_type: str = "Monthly"
    position: Optional[str] = None
    hourly_rate: Optional[float] = None
    daily_rate: Optional[float] = None
    monthly_salary: Optional[float] = None
    akord_note: Optional[str] = None
    insurance_pct: Optional[float] = None      # employer social-security %, e.g. 0.328
    insurance_amount: Optional[float] = None   # optional fixed осигуровки amount (overrides %)
    standard_hours_per_day: float = 8
    working_days_per_month: float = 22
    pay_schedule: str = "Monthly"
    active: bool = True
    start_date: Optional[str] = None

class EmployeeProfileUpdate(BaseModel):
    pay_type: Optional[str] = None
    position: Optional[str] = None
    hourly_rate: Optional[float] = None
    daily_rate: Optional[float] = None
    monthly_salary: Optional[float] = None
    akord_note: Optional[str] = None
    insurance_pct: Optional[float] = None
    insurance_amount: Optional[float] = None
    standard_hours_per_day: Optional[float] = None
    working_days_per_month: Optional[float] = None
    pay_schedule: Optional[str] = None
    active: Optional[bool] = None
    start_date: Optional[str] = None

class AdvanceLoanCreate(BaseModel):
    user_id: Optional[str] = None
    guest_name: Optional[str] = None
    type: str = "Advance"
    amount: float
    currency: str = "EUR"
    account_id: Optional[str] = None
    project_id: Optional[str] = None
    issued_date: Optional[str] = None
    note: Optional[str] = None

class PayrollRunCreate(BaseModel):
    period_type: str = "Monthly"
    period_start: str
    period_end: str

class SetDeductionsRequest(BaseModel):
    deductions_amount: float = 0
    advances_to_deduct: List[dict] = []

class MarkPaidRequest(BaseModel):
    method: str = "Cash"
    reference: Optional[str] = None
    note: Optional[str] = None
