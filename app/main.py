# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID
from psycopg2.extras import RealDictCursor

from app.graph.orchestrator import orchestrator
from app.jobs.reminder_job import reminder_job
from app.database.supabase_client import db
from app.utils.helpers import build_graph_config
from app.utils.logger import get_logger, log_event

app = FastAPI(
    title="AI Team Task Management Agent",
    description="Hệ thống quản lý công việc nhóm bằng AI",
    version="2.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = get_logger("app.main")


# ====================== SCHEMAS ======================

class ChatRequest(BaseModel):
    user_input: str
    user_id: Optional[str] = None
    project_id: Optional[str] = None


class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    owner_id: str
    status: str = "Planning"


class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "Todo"
    priority: str = "Medium"
    estimated_hours: Optional[float] = None
    start_date: Optional[date] = None
    due_date: date
    parent_task_id: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    start_date: Optional[date] = None
    due_date: Optional[date] = None


class MemberAddRequest(BaseModel):
    user_id: str
    role_in_project: str = "Member"
    workload_capacity: int = 100


class AssignmentSaveRequest(BaseModel):
    task_id: str
    user_id: str
    assigned_by: Optional[str] = None


class AssignTaskRequest(BaseModel):
    user_id: str
    assigned_by: Optional[str] = None
    propagate_to_children: bool = True


# ====================== HELPERS ======================

def _ensure_user(user_id: str) -> str:
    existing_user = db.get_user(user_id)
    if existing_user:
        return user_id

    created_user = db.create_user({
        "name": user_id,
        "email": f"{user_id}@internal.local",
        "role": "member",
        "skill_notes": "Auto-created for chat runtime",
    })
    return str(created_user["user_id"])


# ====================== CHAT (KEEP) ======================

@app.post("/chat")
async def chat(request: ChatRequest):
    """Endpoint chính để chat với AI Agent"""
    user_id = _ensure_user(request.user_id or "anonymous")
    inputs = {
        "user_input": request.user_input,
        "user_id": user_id,
        "project_id": request.project_id,
        "messages": [],
        "tasks": [],
        "risks": [],
        "current_phase": "ready"
    }

    result = orchestrator.invoke(inputs, config=build_graph_config(user_id))
    return {
        "response": result.get("messages", [])[-1].get("content") if result.get("messages") else "Đã xử lý",
        "project_id": result.get("project_id"),
        "success": True
    }


# ====================== PHASE 2: PROJECT CRUD ======================

@app.get("/api/users")
async def list_users():
    """Lấy danh sách users"""
    return {"data": db.get_users() or []}


@app.post("/api/projects")
async def create_project(req: ProjectCreateRequest):
    """Tạo project mới (manual, không LLM)"""
    try:
        project_data = {
            "name": req.name,
            "description": req.description,
            "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None,
            "owner_id": req.owner_id,
            "status": req.status,
        }
        project = db.create_project(project_data)
        log_event(logger, "api.project.created", project_id=project.get("project_id"), name=req.name)
        return {"success": True, "data": project}
    except Exception as e:
        log_event(logger, "api.project.create.error", level="error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/projects")
async def list_projects(owner_id: Optional[str] = None):
    """Lấy danh sách projects"""
    if owner_id:
        return {"data": db.get_projects_by_owner(owner_id) or []}
    return {"data": db.get_projects() or []}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Chi tiết project"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"data": project}


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, req: ProjectCreateRequest):
    """Cập nhật project"""
    existing = db.get_project(project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")

    # Direct SQL update via existing method
    db._execute(
        """
        UPDATE projects SET name=%s, description=%s, start_date=%s, end_date=%s, status=%s, updated_at=NOW()
        WHERE project_id=%s
        """,
        (req.name, req.description, req.start_date, req.end_date, req.status, project_id),
    )
    log_event(logger, "api.project.updated", project_id=project_id)
    return {"success": True, "data": db.get_project(project_id)}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Xóa project"""
    db._execute("DELETE FROM projects WHERE project_id = %s", (project_id,))
    log_event(logger, "api.project.deleted", project_id=project_id)
    return {"success": True, "message": "Project deleted"}


# ====================== PROJECT MEMBERS ======================

@app.post("/api/projects/{project_id}/members")
async def add_project_member(project_id: str, req: MemberAddRequest):
    """Thêm member vào project"""
    try:
        member = db.create_project_member(project_id, req.user_id, req.role_in_project, req.workload_capacity)
        log_event(logger, "api.project.member.added", project_id=project_id, user_id=req.user_id)
        return {"success": True, "data": member}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/projects/{project_id}/members/{user_id}")
async def remove_project_member(project_id: str, user_id: str):
    """Xóa member khỏi project"""
    members = db.get_project_members(project_id) or []
    target = [m for m in members if m.get("user_id") == user_id or m.get("project_member_id") == user_id]
    if target:
        db.delete_project_member(target[0]["project_member_id"])
        log_event(logger, "api.project.member.removed", project_id=project_id, user_id=user_id)
    return {"success": True, "message": "Member removed"}


@app.get("/api/projects/{project_id}/members")
async def list_project_members(project_id: str):
    """Danh sách members"""
    return {"data": db.get_project_members(project_id) or []}


@app.get("/api/projects/{project_id}/workload")
async def get_workload(project_id: str):
    """Workload của các member"""
    return {"data": db.get_member_workload(project_id) or []}


# ====================== PHASE 3: TASK CRUD ======================

@app.post("/api/projects/{project_id}/tasks")
async def create_task(project_id: str, req: TaskCreateRequest):
    """Tạo task mới"""
    try:
        tasks = db.create_tasks_batch([{
            "project_id": project_id,
            "title": req.title,
            "description": req.description,
            "status": req.status,
            "priority": req.priority,
            "estimated_hours": req.estimated_hours,
            "start_date": req.start_date,
            "due_date": req.due_date,
            "parent_task_id": req.parent_task_id,
        }])
        log_event(logger, "api.task.created", project_id=project_id, title=req.title)
        from app.database.redis_client import redis_client
        redis_client.delete_pattern(f"dashboard:{project_id}")
        return {"success": True, "data": tasks[0] if tasks else None}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/projects/{project_id}/tasks")
async def list_tasks(project_id: str):
    """Lấy danh sách tasks (flat)"""
    return {"data": db.get_tasks_by_project(project_id) or []}


@app.get("/api/projects/{project_id}/tasks/tree")
async def get_task_tree(project_id: str):
    """Lấy task tree (hierarchical)"""
    tasks = db.get_tasks_by_project(project_id) or []
    task_map = {}
    for t in tasks:
        tid = t.get("task_id")
        task_map[tid] = {**t, "children": []}

    roots = []
    for t in task_map.values():
        parent_id = t.get("parent_task_id")
        if parent_id and parent_id in task_map:
            task_map[parent_id]["children"].append(t)
        else:
            roots.append(t)
    return {"data": roots}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """Chi tiết task"""
    tasks = db._fetchall(
        "SELECT task_id::text, project_id::text, title, description, status, priority, "
        "estimated_hours, actual_hours, start_date, due_date, parent_task_id::text, created_at, updated_at "
        "FROM tasks WHERE task_id = %s", (task_id,)
    )
    if not tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"data": tasks[0]}


@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, req: TaskUpdateRequest):
    """Cập nhật task"""
    updates = {}
    for field in ["title", "description", "status", "priority", "estimated_hours", "actual_hours", "start_date", "due_date"]:
        val = getattr(req, field, None)
        if val is not None:
            if isinstance(val, date):
                updates[field] = val.isoformat()
            else:
                updates[field] = val

    if not updates:
        return {"success": True, "data": db._fetchone("SELECT task_id::text FROM tasks WHERE task_id = %s", (task_id,))}

    set_clauses = ", ".join([f"{k} = %s" for k in updates.keys()])
    values = list(updates.values()) + [task_id]
    db._execute(f"UPDATE tasks SET {set_clauses}, updated_at = NOW() WHERE task_id = %s", tuple(values))
    log_event(logger, "api.task.updated", task_id=task_id)
    return {"success": True, "data": db._fetchone(
        "SELECT task_id::text, project_id::text, title, description, status, priority, "
        "estimated_hours, actual_hours, start_date, due_date, parent_task_id::text, created_at, updated_at "
        "FROM tasks WHERE task_id = %s", (task_id,)
    )}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Xóa task"""
    db._execute("DELETE FROM tasks WHERE task_id = %s", (task_id,))
    log_event(logger, "api.task.deleted", task_id=task_id)
    return {"success": True, "message": "Task deleted"}


@app.put("/api/tasks/{task_id}/status")
async def update_task_status(task_id: str, status: str, actual_hours: Optional[float] = None):
    """Cập nhật trạng thái task"""
    db.update_task_status(task_id, status, actual_hours)
    log_event(logger, "api.task.status.updated", task_id=task_id, status=status)
    return {"success": True, "message": f"Status updated to {status}"}


@app.post("/api/tasks/{task_id}/subtasks")
async def create_subtask(task_id: str, req: TaskCreateRequest):
    """Tạo subtask (gắn parent_task_id) — tự động inherit assignee từ task cha nếu có"""
    parent = db._fetchone(
        "SELECT task_id, project_id FROM tasks WHERE task_id = %s",
        (task_id,),
    )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent task not found")

    tasks = db.create_tasks_batch([{
        "project_id": parent["project_id"],
        "title": req.title,
        "description": req.description,
        "status": req.status,
        "priority": req.priority,
        "estimated_hours": req.estimated_hours,
        "start_date": req.start_date,
        "due_date": req.due_date,
        "parent_task_id": task_id,
    }])
    new_task = tasks[0] if tasks else None

    # Auto-inherit assignee từ task cha
    if new_task:
        parent_assignee = db.get_task_assignee(task_id)
        if parent_assignee:
            db.create_task_assignments_batch([{
                "task_id": new_task["task_id"],
                "user_id": parent_assignee["user_id"],
                "assigned_by": parent_assignee.get("assigned_by") or parent_assignee["user_id"],
            }])
            log_event(
                logger, "api.subtask.auto_assigned",
                task_id=new_task["task_id"], parent_task_id=task_id,
                user_id=parent_assignee["user_id"],
            )
            # Update status
            db.update_task_status(new_task["task_id"], "InProgress")

    log_event(logger, "api.subtask.created", parent_task_id=task_id, title=req.title)
    return {"success": True, "data": new_task}


# ====================== ASSIGNMENTS ======================

@app.post("/api/projects/{project_id}/assignments")
async def save_assignments(project_id: str, assignments: List[AssignmentSaveRequest]):
    """Lưu assignments (sau khi PM approve)"""
    assignment_list = [a.model_dump() for a in assignments]
    result = db.create_task_assignments_batch(assignment_list)
    log_event(logger, "api.assignments.saved", project_id=project_id, count=len(result))
    return {"success": True, "data": result, "count": len(result)}


@app.get("/api/projects/{project_id}/assignments")
async def get_assignments(project_id: str):
    """Lấy assignments của project"""
    return {"data": db.get_task_assignments_by_project(project_id) or []}


# ====================== COMPOSITE DASHBOARD ======================

@app.get("/api/projects/{project_id}/dashboard")
async def get_dashboard(project_id: str):
    """Composite endpoint — trả về tất cả dữ liệu Dashboard trong 1 request"""
    from app.database.redis_client import redis_client

    cache_key = f"dashboard:{project_id}"
    cached = redis_client.get(cache_key)
    if cached:
        return {"data": cached, "cached": True}

    project = db.get_project(project_id) or {}
    tasks = db.get_tasks_by_project(project_id) or []
    members = db.get_project_members(project_id) or []
    assignments = db.get_task_assignments_by_project(project_id) or []
    status_summary = db.get_task_status_summary(project_id) or {}
    overdue_tasks = db.get_overdue_tasks(project_id) or []
    risks = db.get_risks_by_project(project_id) or []
    risk_summary = db.get_risk_summary(project_id) or {}
    workload = db.get_member_workload(project_id) or []
    audit_logs = db.get_audit_logs(project_id=project_id, limit=30) or []

    assignees_by_task = {}
    for assignment in assignments:
        task_id = assignment.get("task_id")
        assignee_name = assignment.get("assignee_name") or "Unknown"
        if task_id:
            assignees_by_task.setdefault(task_id, []).append(assignee_name)

    task_map = {}
    for t in tasks:
        tid = t.get("task_id")
        task_map[tid] = {**t, "children": []}
    roots = []
    for t in task_map.values():
        parent_id = t.get("parent_task_id")
        if parent_id and parent_id in task_map:
            task_map[parent_id]["children"].append(t)
        else:
            roots.append(t)

    data = {
        "project": project,
        "tasks": tasks,
        "task_tree": roots,
        "members": members,
        "assignments": assignments,
        "assignees_by_task": assignees_by_task,
        "status_summary": status_summary,
        "overdue_tasks": overdue_tasks,
        "risks": risks,
        "risk_summary": risk_summary,
        "workload": workload,
        "audit_logs": audit_logs,
    }

    redis_client.set(cache_key, data, expire=30)
    return {"data": data, "cached": False}


# ====================== ASSIGN TASK (WITH PROPAGATION) ======================

@app.post("/api/tasks/{task_id}/assign")
async def assign_task(task_id: str, req: AssignTaskRequest):
    """Gán task cho user — mặc định propagate xuống tất cả children"""
    task = db._fetchone(
        "SELECT task_id::text, project_id::text, title, status FROM tasks WHERE task_id = %s",
        (task_id,),
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if req.propagate_to_children:
        result = db.assign_task_with_children(task_id, req.user_id, req.assigned_by or req.user_id)
        log_event(
            logger, "api.task.assign.propagated",
            task_id=task_id, user_id=req.user_id,
            assigned_count=result["assigned_count"],
        )
    else:
        db._ensure_connection()
        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("DELETE FROM task_assignments WHERE task_id = %s", (task_id,))
                cursor.execute(
                    """
                    INSERT INTO task_assignments (task_id, user_id, assigned_by)
                    VALUES (%s, %s, %s)
                    RETURNING assignment_id::text, task_id::text, user_id::text, assigned_at, assigned_by::text
                    """,
                    (task_id, req.user_id, req.assigned_by or req.user_id),
                )
                cursor.execute(
                    "UPDATE tasks SET status = 'InProgress', updated_at = NOW() WHERE task_id = %s AND status = 'Todo'",
                    (task_id,),
                )
            db.conn.commit()
            result = {"assigned_count": 1, "task_ids": [task_id]}
        except Exception:
            db.conn.rollback()
            raise

    from app.database.redis_client import redis_client
    redis_client.delete_pattern(f"dashboard:{task.get('project_id')}")

    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "user_id": req.user_id,
            "assigned_count": result["assigned_count"],
            "task_ids": result["task_ids"],
            "propagated_to_children": req.propagate_to_children,
        },
    }


# ====================== RISKS ======================

@app.get("/api/projects/{project_id}/risks")
async def get_risks(project_id: str):
    """Lấy danh sách rủi ro"""
    return {"data": db.get_risks_by_project(project_id) or []}


@app.get("/api/projects/{project_id}/risks/summary")
async def get_risk_summary(project_id: str):
    """Tổng quan rủi ro"""
    return {"data": db.get_risk_summary(project_id) or {}}


# ====================== PROGRESS ======================

@app.get("/api/projects/{project_id}/progress")
async def get_progress(project_id: str):
    """Tiến độ project"""
    progress = db.calculate_project_progress(project_id)
    summary = db.get_task_status_summary(project_id) or {}
    overdue = db.get_overdue_tasks(project_id) or []
    return {
        "data": {
            "progress_percentage": progress,
            "status_summary": summary,
            "overdue_count": len(overdue),
        }
    }


# ====================== REMINDER ======================

@app.post("/start-reminder")
async def start_reminder():
    """Khởi động background reminder job"""
    reminder_job.start_background(interval_seconds=1800)  # 30 phút
    return {"status": "Reminder job started"}


@app.get("/health")
async def health():
    return {"status": "healthy", "message": "AI Team Task Agent is running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)