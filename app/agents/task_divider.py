# app/agents/task_divider.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.prompts.task_divider_prompts import TASK_DIVIDER_SYSTEM_PROMPT
from app.models.schemas import AgentResponse
from app.database.supabase_client import db
from app.database.redis_client import redis_client
from config import config
import json
import hashlib
from langsmith import traceable
import time
from datetime import date, timedelta
from app.utils.logger import get_logger, log_event, truncate_text, summarize_sequence
from app.utils.serialization import serialize_for_json

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    google_api_key=config.GEMINI_API_KEY
)

logger = get_logger("app.agents.task_divider")


def _resolve_assignee_user_id(assigned_to: object, team_members: list[dict] | None) -> str | None:
    if not assigned_to:
        return None

    normalized_value = str(assigned_to).strip().lower()
    for member in team_members or []:
        user_id = str(member.get("user_id") or "").strip().lower()
        name = str(member.get("name") or "").strip().lower()
        email = str(member.get("email") or "").strip().lower()
        if normalized_value in {user_id, name, email}:
            return member.get("user_id")
    return None


def _resolve_due_date(task: dict) -> date:
    due_date = task.get("due_date")
    if due_date:
        if isinstance(due_date, date):
            return due_date
        try:
            return date.fromisoformat(str(due_date))
        except ValueError:
            pass

    due_date_offset = task.get("due_date_offset")
    if due_date_offset is not None:
        try:
            return date.today() + timedelta(days=int(due_date_offset))
        except (TypeError, ValueError):
            pass

    return date.today()

@traceable(name="Task Divider Agent")
def task_divider_agent(project_id: str, project_data: dict = None, raw_tasks: list = None) -> AgentResponse:
    """
    Phân chia task và gán người
    """
    try:
        started_at = time.perf_counter()
        cache_key = f"task_divider:{project_id}"
        log_event(
            logger,
            "task_divider.enter",
            project_id=project_id,
            cache_key=cache_key,
            project_data_keys=sorted(list((project_data or {}).keys()))[:10],
            raw_tasks_summary=summarize_sequence(raw_tasks, sample_key="title"),
        )
        cached = redis_client.get(cache_key)
        if cached:
            log_event(logger, "task_divider.cache.hit", cache_key=cache_key, project_id=project_id)
            return AgentResponse(**cached)

        # Lấy danh sách thành viên
        team_members = db.get_users()
        log_event(logger, "task_divider.team_members.loaded", project_id=project_id, team_members_summary=summarize_sequence(team_members, sample_key="name"))

        # Tự động load tasks từ DB nếu không được cung cấp
        if not raw_tasks:
            raw_tasks = db.get_tasks_by_project_status(project_id) or []
            log_event(logger, "task_divider.tasks.loaded_from_db", project_id=project_id, tasks_count=len(raw_tasks))

        # Tự động load project data từ DB nếu không được cung cấp
        if not project_data:
            project = db.get_project(project_id)
            if project:
                project_data = {
                    "project_name": project.get("name"),
                    "project_description": project.get("description"),
                    "start_date": str(project.get("start_date") or ""),
                    "end_date": str(project.get("end_date") or ""),
                    "status": project.get("status"),
                }
                log_event(logger, "task_divider.project.loaded_from_db", project_id=project_id, project_name=project_data.get("project_name"))

        prompt = f"""
        {TASK_DIVIDER_SYSTEM_PROMPT}

        Thông tin Project:
        {json.dumps(serialize_for_json(project_data or {}), ensure_ascii=False, indent=2)}

        Danh sách task thô:
        {json.dumps(serialize_for_json(raw_tasks or []), ensure_ascii=False, indent=2)}

        Danh sách thành viên:
        {json.dumps(serialize_for_json(team_members), ensure_ascii=False, indent=2)}
        """

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content="Hãy phân chia task và gán người một cách hợp lý.")
        ]

        response = llm.invoke(messages)
        content = response.content.strip()
        log_event(logger, "task_divider.llm.response", project_id=project_id, content_preview=truncate_text(content, 220))

        try:
            if "{" in content:
                json_str = content[content.find("{"):content.rfind("}") + 1]
                result = json.loads(json_str)
            else:
                result = json.loads(content)
        except:
            result = {"assigned_tasks": [], "workload_summary": {}, "suggestions": ["Không parse được JSON"]}
            log_event(logger, "task_divider.parse.fallback", level="warning", project_id=project_id)

        # REFACTORED: Task Divider chỉ recommend, KHÔNG tạo task hay lưu DB
        # Tạo task_recommendations từ kết quả LLM
        task_recommendations = []
        for task in (result.get("assigned_tasks") or []):
            assigned_user_id = _resolve_assignee_user_id(task.get("assigned_to"), team_members)
            task_recommendations.append({
                "task_title": task.get("task_title"),
                "assigned_to": task.get("assigned_to"),
                "assigned_user_id": assigned_user_id,
                "reason": task.get("reason"),
                "description": task.get("description", ""),
                "priority": task.get("priority", "Medium"),
                "due_date": _resolve_due_date(task).isoformat(),
            })

        final_result = AgentResponse(
            response=f"✅ Đã phân tích {len(result.get('assigned_tasks', []))} tasks. "
                     f"Vui lòng review và approve assignments trong Dashboard.",
            tasks=task_recommendations,
            success=True
        ).dict()

        # Cache 20 phút
        redis_client.set(cache_key, final_result, expire=1200)
        log_event(
            logger,
            "task_divider.cache.save",
            cache_key=cache_key,
            project_id=project_id,
            assigned_tasks_count=len(result.get("assigned_tasks", [])),
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return AgentResponse(**final_result)

    except Exception as e:
        log_event(logger, "task_divider.exception", level="error", project_id=project_id, error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi khi phân chia task: {str(e)}",
            tasks=[],
            success=False
        )