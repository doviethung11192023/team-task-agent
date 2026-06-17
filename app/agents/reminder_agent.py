# app/agents/reminder_agent.py
from datetime import datetime, date
from app.database.supabase_client import db
from app.models.schemas import AgentResponse
from app.database.redis_client import redis_client
from app.utils.slack_client import send_slack_notification
from app.tools.notification_tools import notification_tools
from langsmith import traceable
import time
import json
from app.utils.logger import get_logger, log_event, summarize_sequence


logger = get_logger("app.agents.reminder_agent")


def _send_slack_reminder(task_title: str, assignee_name: str, due_date: date, days_left: int, project_name: str):
    """Send a formatted Slack reminder message"""
    if days_left > 3:
        # Only send > 3 days for 7-day threshold
        if days_left == 7:
            msg = (
                f"📋 **Nhắc nhở sớm**: Task *{task_title}* còn **7 ngày** đến hạn ({due_date})\n"
                f"👤 **Assignee**: {assignee_name or 'Chưa gán'}\n"
                f"📁 **Project**: {project_name}\n"
                f"⏰ **Days Remaining**: {days_left}"
            )
            return msg
        return None

    thresholds = {
        3: ("⏰", "Sắp đến hạn"),
        1: ("🚨", "Gần hạn, cần hoàn thành sớm!"),
    }

    if days_left >= 0 and days_left in thresholds:
        icon, label = thresholds[days_left]
        msg = (
            f"{icon} **{label}**: Task *{task_title}* còn **{days_left} ngày**\n"
            f"👤 **Assignee**: {assignee_name or 'Chưa gán'}\n"
            f"📅 **Deadline**: {due_date}\n"
            f"📁 **Project**: {project_name}\n"
            f"⏰ **Days Remaining**: {days_left}"
        )
        return msg

    if days_left < 0:
        msg = (
            f"❌ **QUÁ HẠN**: Task *{task_title}* đã trễ {abs(days_left)} ngày!\n"
            f"👤 **Assignee**: {assignee_name or 'Chưa gán'}\n"
            f"📅 **Deadline**: {due_date}\n"
            f"📁 **Project**: {project_name}\n"
            f"⏰ **Overdue by**: {abs(days_left)} ngày"
        )
        return msg

    return None


@traceable(name="Reminder Agent")
def reminder_agent(project_id: str = None) -> AgentResponse:
    """
    Reminder Agent - Kiểm tra và gửi nhắc nhở deadline
    (REFACTORED: 4 thresholds, assignee-aware, detailed output)
    """
    try:
        started_at = time.perf_counter()
        notifications = []
        today = date.today()
        log_event(logger, "reminder.enter", project_id=project_id)

        # Lấy project(s)
        if project_id:
            projects = [db.get_project(project_id)]
        else:
            projects = db.get_projects()

        log_event(logger, "reminder.projects.loaded", project_id=project_id, projects_summary=summarize_sequence(projects, sample_key="name"))

        for project in projects:
            if not project:
                continue

            tasks = db.get_tasks_by_project(project['project_id'])
            assignments = db.get_task_assignments_by_project(project['project_id']) or []
            # Build assignee map: task_id -> assignee_name
            assignee_map = {}
            for a in assignments:
                tid = a.get("task_id")
                aname = a.get("assignee_name", "")
                if tid and aname:
                    assignee_map[tid] = aname

            log_event(logger, "reminder.tasks.loaded", project_id=project.get("project_id"), tasks_summary=summarize_sequence(tasks, sample_key="title"))

            for task in tasks:
                if not task.get('due_date') or task.get('status') == 'Done':
                    continue

                try:
                    due_date_str = str(task['due_date'])
                    due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date() if '-' in due_date_str else date.fromisoformat(due_date_str)
                    days_left = (due_date - today).days
                    task_title = task.get('title', 'Unknown')
                    assignee_name = assignee_map.get(task.get('task_id'), '')

                    msg = _send_slack_reminder(
                        task_title=task_title,
                        assignee_name=assignee_name,
                        due_date=due_date,
                        days_left=days_left,
                        project_name=project.get('name', 'Unknown'),
                    )

                    if msg:
                        notifications.append(msg)
                        notification_tools.send_notification(msg)
                        log_event(logger, "reminder.notification.sent", task_title=task_title, days_left=days_left, assignee=assignee_name)

                except Exception as task_error:
                    log_event(
                        logger,
                        "reminder.task_parse_error",
                        level="warning",
                        project_id=project.get("project_id"),
                        task_id=task.get("task_id"),
                        task_title=task.get("title"),
                        error_type=type(task_error).__name__,
                        error=str(task_error),
                    )
                    continue

        if notifications:
            summary = f"📢 Đã gửi **{len(notifications)}** thông báo nhắc nhở."
        else:
            summary = "✅ Hiện tại không có task nào cần nhắc nhở."

        # Lưu log vào Redis
        log_entry = json.dumps({
            "timestamp": datetime.now().isoformat(),
            "message": summary,
            "count": len(notifications),
        })
        redis_client.client.lpush("reminder_logs", log_entry)
        redis_client.client.ltrim("reminder_logs", 0, 99)
        log_event(logger, "reminder.redis.log_saved", summary=summary, notifications_count=len(notifications))

        log_event(logger, "reminder.exit", elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2), notifications_count=len(notifications))

        return AgentResponse(
            response=summary,
            success=True
        )

    except Exception as e:
        log_event(logger, "reminder.exception", level="error", project_id=project_id, error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi Reminder Agent: {str(e)}",
            tasks=[],
            risks=[],
            success=False
        )