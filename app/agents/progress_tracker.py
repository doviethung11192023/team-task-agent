# app/agents/progress_tracker.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.models.schemas import AgentResponse
from app.database.supabase_client import db
from app.database.redis_client import redis_client
from config import config
from langsmith import traceable
import time
from app.utils.logger import get_logger, log_event, truncate_text

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    google_api_key=config.GEMINI_API_KEY
)

logger = get_logger("app.agents.progress_tracker")

STATUS_PROGRESS_MAP = {"Todo": 0, "InProgress": 50, "Review": 75, "Done": 100}


def _build_task_tree(tasks: list) -> dict:
    """Build task tree map for hierarchical progress calculation"""
    task_map = {}
    for t in (tasks or []):
        tid = t.get("task_id") or t.get("title")
        task_map[tid] = {**t, "children": []}

    roots = []
    for t in task_map.values():
        parent_id = t.get("parent_task_id")
        if parent_id and parent_id in task_map:
            task_map[parent_id]["children"].append(t)
        else:
            roots.append(t)

    return {"map": task_map, "roots": roots}


def _calculate_task_progress(task, task_map: dict) -> int:
    """Calculate progress recursively: parent = average of children, leaf = from status"""
    tid = task.get("task_id") or task.get("title")
    node = task_map.get(tid, task)
    children = node.get("children", [])

    if not children:
        # Leaf task — calculate from status
        status = task.get("status", "Todo")
        return STATUS_PROGRESS_MAP.get(status, 0)

    # Parent task — average of children
    total = 0
    for child in children:
        total += _calculate_task_progress(child, task_map)
    return round(total / len(children))


def _calculate_hierarchical_progress(tasks: list) -> dict:
    """Calculate hierarchical progress for entire project"""
    tree = _build_task_tree(tasks)
    task_map = tree["map"]

    leaf_count = 0
    completed_leaves = 0
    overdue_count = 0
    blocked_count = 0
    from datetime import date

    for tid, t in task_map.items():
        if not t.get("children"):
            leaf_count += 1
            if t.get("status") == "Done":
                completed_leaves += 1
            # Check overdue
            due = t.get("due_date")
            if due and t.get("status") != "Done":
                try:
                    if isinstance(due, str):
                        due_date = date.fromisoformat(due)
                    else:
                        due_date = due
                    if due_date < date.today():
                        overdue_count += 1
                except (ValueError, TypeError):
                    pass

    # Overall project progress from root tasks
    root_progresses = []
    for root in tree["roots"]:
        root_progresses.append(_calculate_task_progress(root, task_map))

    overall = round(sum(root_progresses) / len(root_progresses)) if root_progresses else 0

    return {
        "progress_percentage": overall,
        "leaf_completed": completed_leaves,
        "leaf_total": leaf_count,
        "overdue_count": overdue_count,
        "blocked_count": blocked_count,
        "root_task_progresses": [
            {"title": r.get("title"), "progress": p}
            for r, p in zip(tree["roots"], root_progresses)
        ],
    }


@traceable(name="Progress Tracker Agent")
def progress_tracker_agent(project_id: str, user_input: str) -> AgentResponse:
    """
    Theo dõi và cập nhật tiến độ (REFACTORED: hierarchical from subtasks)
    """
    try:
        started_at = time.perf_counter()
        log_event(logger, "progress.enter", project_id=project_id, user_input_preview=truncate_text(user_input, 180))
        if not project_id:
            log_event(logger, "progress.enter.invalid_project", level="warning")
            return AgentResponse(response="Chưa có project để theo dõi tiến độ.", success=False)

        # Lấy tasks và tính hierarchical progress
        tasks = db.get_tasks_by_project(project_id) or []
        progress_data = _calculate_hierarchical_progress(tasks)

        # Cập nhật progress vào DB
        db.update_project_progress(project_id, progress_data["progress_percentage"])
        log_event(logger, "progress.db.progress_updated", project_id=project_id, progress=progress_data["progress_percentage"])

        # Build hierarchical progress LLM context
        task_tree_str = ""
        status_summary = db.get_task_status_summary(project_id) or {}

        # Tạo tree string cho LLM
        tree = _build_task_tree(tasks)
        def _tree_to_str(node, level=0):
            indent = "  " * level
            prog = _calculate_task_progress(node, tree["map"])
            return f"{indent}- {node.get('title')} ({node.get('status')}) - {prog}% done\n" + \
                   "".join(_tree_to_str(c, level + 1) for c in node.get("children", []))
        for root in tree["roots"]:
            task_tree_str += _tree_to_str(root, 0)

        prompt = f"""
        Bạn là Progress Tracker Assistant.
        Project ID: {project_id}
        Tiến độ tổng thể: {progress_data['progress_percentage']}%
        Số task lá hoàn thành: {progress_data['leaf_completed']}/{progress_data['leaf_total']}
        Số task quá hạn: {progress_data['overdue_count']}
        Số task bị block: {progress_data['blocked_count']}

        Task status summary: Todo={status_summary.get('Todo', 0)}, InProgress={status_summary.get('InProgress', 0)}, Review={status_summary.get('Review', 0)}, Done={status_summary.get('Done', 0)}

        Task tree (phân cấp với tiến độ từng phần):
        {task_tree_str}

        Input từ user: {user_input}

        Hãy phân tích tiến độ và đưa ra phản hồi hữu ích, tập trung vào các task quá hạn hoặc đang bị chậm.
        """

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=user_input)
        ]

        response = llm.invoke(messages)
        log_event(logger, "progress.llm.response", project_id=project_id, content_preview=truncate_text(response.content, 220))

        result = AgentResponse(
            response=f"📊 Tiến độ tổng thể: **{progress_data['progress_percentage']}%**\n"
                     f"✅ Hoàn thành: {progress_data['leaf_completed']}/{progress_data['leaf_total']} task lá\n"
                     f"⚠️ Quá hạn: {progress_data['overdue_count']} | Blocked: {progress_data['blocked_count']}\n\n"
                     f"{response.content}",
            success=True
        ).dict()

        return AgentResponse(**result)

    except Exception as e:
        log_event(logger, "progress.exception", level="error", project_id=project_id, error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi khi theo dõi tiến độ: {str(e)}",
            tasks=[],
            risks=[],
            success=False
        )