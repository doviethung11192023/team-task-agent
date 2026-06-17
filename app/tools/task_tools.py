# app/tools/task_tools.py
from typing import List, Dict
from datetime import datetime, timedelta
from app.database.supabase_client import db
from app.utils.helpers import log_audit

def create_project_tool(user_input: str, user_id: str, team_members: List[Dict]) -> Dict:
    """Tool tạo project mới"""
    # Tạm thời tạo project data đơn giản (sẽ kết nối với Planner Agent sau)
    project_data = {
        "name": "New Project from AI",
        "description": user_input,
        "start_date": datetime.now().date().isoformat(),
        "end_date": (datetime.now() + timedelta(days=30)).date().isoformat(),
        "owner_id": user_id,
        "status": "Planning"
    }
    
    project = db.create_project(project_data)
    
    log_audit("create_project", "Project", project['project_id'], user_id, project_data)
    
    return {
        "success": True,
        "project_id": project['project_id'],
        "project": project,
        "message": f"✅ Đã tạo project: {project['name']}"
    }


def create_tasks_batch_tool(project_id: str, tasks: List[Dict], assigned_by: str) -> Dict:
    """Tạo nhiều task cùng lúc"""
    for task in tasks:
        task['project_id'] = project_id
    
    created_tasks = db.create_tasks_batch(tasks)
    
    log_audit("create_tasks_batch", "Task", project_id, assigned_by, {"count": len(tasks)})
    
    return {
        "success": True,
        "tasks": created_tasks,
        "message": f"✅ Đã tạo {len(tasks)} tasks cho project."
    }


def update_task_status_tool(task_id: str, status: str, user_id: str, actual_hours: float = None) -> Dict:
    """Cập nhật trạng thái task"""
    db.update_task_status(task_id, status, actual_hours)
    
    log_audit("update_task_status", "Task", task_id, user_id, {"new_status": status})
    
    return {
        "success": True,
        "message": f"✅ Đã cập nhật task thành {status}"
    }


update_task_status = update_task_status_tool


def get_project_tasks_tool(project_id: str) -> List[Dict]:
    """Lấy danh sách task của project"""
    return db.get_tasks_by_project(project_id)


def get_project_risks_tool(project_id: str) -> List[Dict]:
    """Lấy danh sách rủi ro"""
    return db.get_risks_by_project(project_id)