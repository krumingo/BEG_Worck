"""
Pydantic models - Attendance & Work Reports.
"""
from pydantic import BaseModel
from typing import Optional, List

ATTENDANCE_STATUSES = ["Present", "Absent", "Late", "SickLeave", "Vacation"]
REPORT_STATUSES = ["Draft", "Submitted", "Approved", "Rejected"]
REMINDER_TYPES = ["MissingAttendance", "MissingWorkReport"]
REMINDER_STATUSES = ["Open", "Reminded", "Resolved", "Excused"]

class AttendanceMarkSelf(BaseModel):
    project_id: Optional[str] = None
    status: str = "Present"
    note: str = ""
    source: str = "Web"

class AttendanceMarkForUser(BaseModel):
    user_id: str
    project_id: Optional[str] = None
    status: str = "Present"
    note: str = ""
    source: str = "Web"

class WorkReportLineInput(BaseModel):
    activity_name: str
    hours: float
    note: str = ""

class WorkReportDraftCreate(BaseModel):
    project_id: str
    date: Optional[str] = None

class WorkReportUpdate(BaseModel):
    summary_note: Optional[str] = None
    lines: Optional[List[WorkReportLineInput]] = None

class WorkReportReject(BaseModel):
    reason: str

class SendReminderRequest(BaseModel):
    type: str
    date: Optional[str] = None
    user_ids: List[str]
    project_id: Optional[str] = None

class ExcuseRequest(BaseModel):
    type: str
    date: str
    user_id: str
    project_id: Optional[str] = None
    reason: str
