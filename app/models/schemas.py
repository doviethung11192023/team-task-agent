from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date, datetime
from uuid import UUID


# ========================= USER =========================
class UserBase(BaseModel):
    name: str
    email: str
    role: str = "member"
    avatar_url: Optional[str] = None
    skill_notes: Optional[str] = None


class UserCreate(UserBase):
    pass


class User(UserBase):
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========================= PROJECT =========================
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str = "Planning"


class ProjectCreate(ProjectBase):
    owner_id: UUID


class Project(ProjectBase):
    project_id: UUID
    owner_id: UUID
    progress_percentage: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========================= TASK =========================
class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "Todo"
    priority: str = "Medium"
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    start_date: Optional[date] = None
    due_date: date
    parent_task_id: Optional[UUID] = None


class TaskCreate(TaskBase):
    project_id: UUID


class Task(TaskBase):
    task_id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskAssignment(BaseModel):
    assignment_id: UUID
    task_id: UUID
    user_id: UUID
    assigned_at: datetime
    assigned_by: Optional[UUID] = None


# ========================= RISK =========================
class RiskBase(BaseModel):
    title: str
    description: Optional[str] = None
    probability: str = "Medium"   # Low, Medium, High
    impact: str = "Medium"        # Low, Medium, High
    status: str = "Open"
    mitigation_plan: Optional[str] = None
    contingency_plan: Optional[str] = None


class RiskCreate(RiskBase):
    project_id: UUID
    owner_id: Optional[UUID] = None


class Risk(RiskBase):
    risk_id: UUID
    project_id: UUID
    risk_score: int
    owner_id: Optional[UUID] = None
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ========================= STATE & RESPONSE =========================
class ProjectState(BaseModel):
    """State dùng trong LangGraph"""
    user_input: str
    user_id: str
    project_id: Optional[str] = None
    messages: List[Dict] = Field(default_factory=list)
    project_data: Optional[Dict] = None
    tasks: List[Dict] = Field(default_factory=list)
    risks: List[Dict] = Field(default_factory=list)
    next_step: str = "end"
    needs_human_approval: bool = False
    approval_response: Optional[str] = None
    current_phase: str = "planning"
    error: Optional[str] = None


class AgentResponse(BaseModel):
    """Response chung từ các Agent"""
    response: str
    project_id: Optional[str] = None
    project_data: Optional[Dict] = None
    tasks: List[Dict] = Field(default_factory=list)
    risks: List[Dict] = Field(default_factory=list)
    success: bool = True
    message: str = ""


class ChatRequest(BaseModel):
    """Request từ Streamlit / API"""
    user_input: str
    user_id: str
    project_id: Optional[str] = None


class DashboardData(BaseModel):
    """Data cho Dashboard"""
    projects: List[Project]
    tasks: List[Task]
    risks: List[Risk]
    total_progress: float
    overdue_tasks: int