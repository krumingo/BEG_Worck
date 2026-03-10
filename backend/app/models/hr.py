"""
Pydantic models - HR / Payroll (M4).
"""
from pydantic import BaseModel
from typing import Optional, List

PAY_TYPES = ["Hourly", "Daily", "Monthly"]
PAY_SCHEDULES = ["Weekly", "Monthly"]
ADVANCE_TYPES = ["Advance", "Loan"]
ADVANCE_STATUSES = ["Open", "Closed"]
PAYROLL_STATUSES = ["Draft", "Finalized", "Paid"]
PAYSLIP_STATUSES = ["Draft", "Finalized", "Paid"]
PAYMENT_METHODS = ["Cash", "BankTransfer"]

class EmployeeProfileCreate(BaseModel):
    user_id: str
    pay_type: str = "Monthly"
    hourly_rate: Optional[float] = None
    daily_rate: Optional[float] = None
    monthly_salary: Optional[float] = None
    standard_hours_per_day: float = 8
    working_days_per_month: float = 22
    pay_schedule: str = "Monthly"
    active: bool = True
    start_date: Optional[str] = None

class EmployeeProfileUpdate(BaseModel):
    pay_type: Optional[str] = None
    hourly_rate: Optional[float] = None
    daily_rate: Optional[float] = None
    monthly_salary: Optional[float] = None
    standard_hours_per_day: Optional[float] = None
    working_days_per_month: Optional[float] = None
    pay_schedule: Optional[str] = None
    active: Optional[bool] = None
    start_date: Optional[str] = None

class AdvanceLoanCreate(BaseModel):
    user_id: str
    type: str = "Advance"
    amount: float
    currency: str = "EUR"
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
