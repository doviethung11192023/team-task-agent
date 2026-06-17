import streamlit as st
import sys
import os
from datetime import datetime, date
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph.orchestrator import orchestrator
from app.database.supabase_client import db
from app.models.schemas import ChatRequest
from app.database.redis_client import redis_client
from config import config
import uuid
from app.utils.helpers import build_graph_config
from app.utils.logger import read_recent_log_events


def _format_project_option(project: dict) -> str:
    return (
        f"{project.get('name', 'Untitled')} "
        f"[{project.get('status', 'Unknown')}] "
        f"{project.get('progress_percentage', 0)}% "
        f"| {project.get('project_id')}"
    )


def _get_projects_for_scope(selected_scope: str, selected_user_id: str):
    if selected_scope == "Tất cả":
        return db.get_projects() or []
    if not selected_user_id:
        return []
    return db.get_projects_by_owner(selected_user_id) or []


def _build_dashboard_snapshot(project_id: str) -> dict:
    """Build composite dashboard với Redis cache 30s — 1 lần query thay 10+"""
    # Thử lấy từ Redis cache trước
    cached = redis_client.get(f"dashboard:{project_id}")
    if cached:
        return cached

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
        if not task_id:
            continue
        assignees_by_task.setdefault(task_id, []).append(assignee_name)

    # Build task tree
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

    snapshot = {
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

    # Cache 30s
    redis_client.set(f"dashboard:{project_id}", snapshot, expire=30)
    return snapshot


def _build_task_tree(tasks: list) -> list:
    """Build hierarchical task tree from flat task list"""
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
    return roots


def _render_task_tree(node, assignees_by_task: dict, level: int = 0):
    """Render a task tree node recursively"""
    indent = "  " * level
    status_icons = {"Todo": "🔲", "InProgress": "🔄", "Review": "👀", "Done": "✅"}
    icon = status_icons.get(node.get("status", ""), "📋")
    assignees = assignees_by_task.get(node.get("task_id"), [])
    assignee_str = f"👤 {', '.join(assignees)}" if assignees else ""
    st.markdown(
        f"{indent}{icon} **{node.get('title')}** "
        f"(`{node.get('status')}`) "
        f"{assignee_str}"
    )
    for child in node.get("children", []):
        _render_task_tree(child, assignees_by_task, level + 1)


# ====================== SESSION STATE ======================
if "thread_id" not in st.session_state:
    st.session_state.thread_id = uuid.uuid4().hex
if "selected_user_id" not in st.session_state:
    st.session_state.selected_user_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None
if "pending_approval" not in st.session_state:
    st.session_state.pending_approval = None
if "project_scope" not in st.session_state:
    st.session_state.project_scope = "Theo user"
if "dashboard_snapshot" not in st.session_state:
    st.session_state.dashboard_snapshot = None
if "dashboard_snapshot_project_id" not in st.session_state:
    st.session_state.dashboard_snapshot_project_id = None
if "task_recommendations" not in st.session_state:
    st.session_state.task_recommendations = None

# ====================== CONFIG ======================
st.set_page_config(page_title="AI Team Task Agent", page_icon="🤖", layout="wide")
st.title("🤖 AI Team Task Management Agent")
st.markdown("**Hệ thống quản lý công việc nhóm thông minh**")

# ====================== SIDEBAR ======================
with st.sidebar:
    st.header("Thông tin")

    # Cache users list trong Redis 60s
    available_users = redis_client.get("users:all")
    if not available_users:
        available_users = db.get_users() or []
        if available_users:
            redis_client.set("users:all", available_users, expire=60)
    user_options = [f"{user.get('name','Unknown')} ({user.get('email','')}) | {user.get('user_id')}" for user in available_users]
    user_map = {option: user for option, user in zip(user_options, available_users)}

    if user_options:
        default_index = 0
        if st.session_state.selected_user_id:
            for index, user in enumerate(available_users):
                if user.get("user_id") == st.session_state.selected_user_id:
                    default_index = index
                    break
        selected_label = st.selectbox("Chọn user", user_options, index=default_index)
        user_id = user_map[selected_label]["user_id"]
        st.session_state.selected_user_id = user_id
        st.caption(f"Đang dùng: {user_map[selected_label].get('name')} | {user_id}")
    else:
        user_id = st.text_input("User ID (fallback)")
        st.warning("Chưa có user nào trong DB, đang dùng input fallback.")

    st.divider()
    st.subheader("📁 Chọn dự án")
    selected_scope = st.radio(
        "Phạm vi",
        options=["Theo user", "Tất cả"],
        index=0 if st.session_state.project_scope == "Theo user" else 1,
        horizontal=True,
    )
    st.session_state.project_scope = selected_scope

    projects = _get_projects_for_scope(selected_scope, st.session_state.selected_user_id)
    project_options = [_format_project_option(project) for project in projects]
    project_map = {option: project for option, project in zip(project_options, projects)}

    if projects:
        selected_index = 0
        current_project_id = st.session_state.current_project_id
        if current_project_id:
            for index, project in enumerate(projects):
                if project.get("project_id") == current_project_id:
                    selected_index = index
                    break

        selected_project_label = st.selectbox(
            "Dự án hiện tại",
            options=project_options,
            index=selected_index,
            key="dashboard_project_select",
        )
        selected_project = project_map[selected_project_label]
        selected_project_id = selected_project.get("project_id")
        if selected_project_id != st.session_state.current_project_id:
            st.session_state.dashboard_snapshot = None
        st.session_state.current_project_id = selected_project_id
    else:
        st.session_state.current_project_id = None
        st.session_state.dashboard_snapshot = None
        st.session_state.dashboard_snapshot_project_id = None
        st.info("Không có dự án trong phạm vi đã chọn.")

    refresh_projects_clicked = st.button("🔄 Refresh Project List", use_container_width=True)
    if refresh_projects_clicked:
        st.session_state.dashboard_snapshot = None
        st.rerun()

    if st.button("🔄 Reset Conversation",use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    # ====================== SIDEBAR: BACKGROUND JOBS ======================
    st.divider()
    st.header("Background Jobs")

    if st.button("▶️ Start Reminder Job"):
        from app.jobs.reminder_job import reminder_job
        reminder_job.start_background(interval_seconds=30, project_id=st.session_state.current_project_id)
        st.success("Background Reminder Job đã bắt đầu!")

    if st.button("⏹️ Stop Reminder Job"):
        from app.jobs.reminder_job import reminder_job
        reminder_job.stop()
        st.info("Background Reminder Job đã dừng.")

    if st.button("📜 Xem Reminder Logs"):
        logs = redis_client.client.lrange("reminder_logs", 0, 19)
        if logs:
            st.write("**Recent Reminder Logs:**")
            for log in logs:
                data = json.loads(log)
                st.write(f"• {data['timestamp']}: {data['message']}")
        else:
            st.info("Chưa có log nào.")


# ====================== HELPERS ======================
def run_orchestrator(inputs: dict):
    """Chạy orchestrator và trả về kết quả."""
    return orchestrator.invoke(inputs, config=build_graph_config(st.session_state.thread_id))


def render_approval_panel(user_id: str):
    """Hiển thị và xử lý bước phê duyệt thủ công."""
    pending = st.session_state.pending_approval
    if not pending:
        return

    st.warning("⚠️ Cần phê duyệt thủ công cho rủi ro cao.")
    st.write(f"**Project ID:** {pending.get('project_id')}")
    if pending.get("message"):
        st.info(pending["message"])

    with st.expander("Xem các rủi ro cần duyệt", expanded=True):
        for risk in pending.get("risks", []):
            st.write(
                f"• **{risk.get('title', 'Unknown')}** — "
                f"Probability: {risk.get('probability', 'N/A')} | Impact: {risk.get('impact', 'N/A')}"
            )

    col_approve, col_reject = st.columns(2)

    with col_approve:
        if st.button("✅ Approve", key="approve_human_gate"):
            inputs = {
                "user_input": pending.get("source_input", "Phê duyệt rủi ro cao"),
                "user_id": user_id,
                "project_id": pending.get("project_id", st.session_state.current_project_id),
                "messages": [],
                "tasks": [],
                "risks": pending.get("risks", []),
                "current_phase": "monitoring",
                "needs_human_approval": True,
                "approval_response": "approved",
            }
            result = run_orchestrator(inputs)
            response_text = result.get("messages", [])[-1].get("content", "Đã duyệt.") if result.get("messages") else "Đã duyệt."
            st.session_state.messages.append({"role": "assistant", "content": response_text})
            st.session_state.pending_approval = None
            if result.get("project_id"):
                st.session_state.current_project_id = result.get("project_id")
            st.session_state.dashboard_snapshot = None
            st.session_state.dashboard_snapshot_project_id = None
            st.rerun()

    with col_reject:
        if st.button("⛔ Reject", key="reject_human_gate"):
            inputs = {
                "user_input": pending.get("source_input", "Từ chối rủi ro cao"),
                "user_id": user_id,
                "project_id": pending.get("project_id", st.session_state.current_project_id),
                "messages": [],
                "tasks": [],
                "risks": pending.get("risks", []),
                "current_phase": "monitoring",
                "needs_human_approval": True,
                "approval_response": "rejected",
            }
            result = run_orchestrator(inputs)
            response_text = result.get("messages", [])[-1].get("content", "Đã từ chối.") if result.get("messages") else "Đã từ chối."
            st.session_state.messages.append({"role": "assistant", "content": response_text})
            st.session_state.pending_approval = None
            if result.get("project_id"):
                st.session_state.current_project_id = result.get("project_id")
            st.session_state.dashboard_snapshot = None
            st.session_state.dashboard_snapshot_project_id = None
            st.rerun()


# ====================== TABS ======================
tab1, tab2 = st.tabs(["💬 Chat với AI Agent", "📊 Dashboard"])

# ====================== TAB 1: CHAT ======================
with tab1:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    render_approval_panel(user_id)

    if prompt := st.chat_input("Nhập lệnh: 'gợi ý assignment', 'phân tích rủi ro', 'xem tiến độ'..."):
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("AI Agent đang xử lý..."):
                try:
                    inputs = {
                        "user_input": prompt,
                        "user_id": user_id,
                        "project_id": st.session_state.current_project_id,
                        "messages": [],
                        "tasks": [],
                        "risks": [],
                        "current_phase": "ready"
                    }
                    result = run_orchestrator(inputs)
                    response_text = result.get("messages", [])[-1].get("content", "Đã xử lý xong.") \
                                   if result.get("messages") else "Tôi đã nhận được yêu cầu."

                    st.markdown(response_text)
                    if result.get("project_id"):
                        st.session_state.current_project_id = result.get("project_id")
                    st.session_state.dashboard_snapshot = None
                    st.session_state.dashboard_snapshot_project_id = None

                    if result.get("needs_human_approval") and not result.get("approval_response"):
                        st.session_state.pending_approval = {
                            "project_id": result.get("project_id", st.session_state.current_project_id),
                            "risks": result.get("risks", []),
                            "message": response_text,
                            "source_input": prompt,
                        }
                    else:
                        st.session_state.pending_approval = None

                    # Lưu task recommendations nếu có
                    if result.get("tasks"):
                        st.session_state.task_recommendations = {
                            "project_id": st.session_state.current_project_id,
                            "tasks": result.get("tasks", []),
                            "response": response_text,
                        }

                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                except Exception as e:
                    st.error(f"Lỗi: {str(e)}")


# ====================== TAB 2: DASHBOARD ======================
with tab2:
    st.header("📊 Dashboard")
    selected_project_id = st.session_state.current_project_id
    dashboard_data = None
    if selected_project_id:
        needs_refresh = (
            st.session_state.dashboard_snapshot is None
            or st.session_state.dashboard_snapshot_project_id != selected_project_id
        )
        if needs_refresh:
            st.session_state.dashboard_snapshot = _build_dashboard_snapshot(selected_project_id)
            st.session_state.dashboard_snapshot_project_id = selected_project_id
        dashboard_data = st.session_state.dashboard_snapshot

    # ====================== DASHBOARD SUBTABS ======================
    subtab1, subtab2, subtab3, subtab4, subtab5, subtab6 = st.tabs([
        "📈 Tổng quan", "📋 Quản lý Task", "👥 Quản lý Team",
        "⚠️ Rủi Ro", "✅ Assignment Review", "📊 System Monitoring"
    ])

    # ==================== SUBTAB 1: TỔNG QUAN ====================
    with subtab1:
        if dashboard_data:
            project = dashboard_data.get("project") or {}
            tasks = dashboard_data.get("tasks") or []
            status_summary = dashboard_data.get("status_summary") or {}
            overdue_tasks = dashboard_data.get("overdue_tasks") or []
            assignees_by_task = dashboard_data.get("assignees_by_task") or {}

            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Tiến độ", f"{project.get('progress_percentage', 0)}%", "📈")
            with col2: st.metric("Tổng Task", len(tasks))
            with col3: st.metric("Chưa hoàn thành", len([t for t in (tasks or []) if t.get('status') != 'Done']))
            with col4: st.metric("Quá hạn", len(overdue_tasks))

            st.caption(
                "Todo: {todo} | InProgress: {in_progress} | Review: {review} | Done: {done}".format(
                    todo=status_summary.get("Todo", 0),
                    in_progress=status_summary.get("InProgress", 0),
                    review=status_summary.get("Review", 0),
                    done=status_summary.get("Done", 0),
                )
            )

            # Task Tree View
            st.subheader("🌳 Task Tree (phân cấp)")
            task_tree = _build_task_tree(tasks)
            if task_tree:
                for root in task_tree:
                    _render_task_tree(root, assignees_by_task)
            else:
                st.info("Project này chưa có task.")

            # Flat task table
            st.subheader("Danh sách Task")
            task_rows = []
            for task in tasks:
                task_id = task.get("task_id")
                parent_id = task.get("parent_task_id")
                title_prefix = "  └ " if parent_id else ""
                task_rows.append(
                    {
                        "Task": f"{title_prefix}{task.get('title', 'Untitled')}",
                        "Status": task.get("status", "Unknown"),
                        "Priority": task.get("priority", "Medium"),
                        "Due Date": task.get("due_date"),
                        "Assignees": ", ".join(assignees_by_task.get(task_id, [])) or "Unassigned",
                        "Parent Task": parent_id[:8] + "..." if parent_id else "—",
                    }
                )

            if task_rows:
                st.dataframe(task_rows, use_container_width=True, hide_index=True)
            else:
                st.info("Project này chưa có task.")
        else:
            st.info("Chưa có project nào. Hãy tạo project mới từ tab Quản lý Task hoặc chọn project ở sidebar.")

    # ==================== SUBTAB 2: QUẢN LÝ TASK (PHASE 2+3) ====================
    with subtab2:
        st.subheader("📋 Quản lý Task")

        if not selected_project_id:
            st.warning("Vui lòng chọn project từ sidebar trước.")
        else:
            # Nếu không có project nào — hiển thị form TẠO PROJECT
            project = db.get_project(selected_project_id) if selected_project_id else None

            # ---- PHASE 2: CREATE PROJECT FORM ----
            st.markdown("### 🆕 Tạo Project Mới")
            with st.expander("Tạo project thủ công", expanded=not bool(project)):
                col1, col2 = st.columns(2)
                with col1:
                    proj_name = st.text_input("Tên dự án", key="new_proj_name")
                    proj_desc = st.text_area("Mô tả", key="new_proj_desc")
                with col2:
                    proj_start = st.date_input("Ngày bắt đầu", value=date.today(), key="new_proj_start")
                    proj_end = st.date_input("Ngày kết thúc", value=None, key="new_proj_end")

                if st.button("✅ Tạo Project", key="btn_create_project"):
                    if proj_name and user_id:
                        project_data = {
                            "name": proj_name,
                            "description": proj_desc,
                            "start_date": proj_start.isoformat(),
                            "end_date": proj_end.isoformat() if proj_end else None,
                            "owner_id": user_id,
                            "status": "Planning"
                        }
                        try:
                            new_project = db.create_project(project_data)
                            st.success(f"✅ Đã tạo project: {proj_name}")
                            st.session_state.current_project_id = new_project.get("project_id")
                            st.session_state.dashboard_snapshot = None
                            st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi: {str(e)}")
                    else:
                        st.error("Vui lòng nhập tên project và chọn user ở sidebar.")

            if project:
                st.divider()
                st.markdown(f"### 📌 Dự án hiện tại: **{project.get('name')}**")

                # ---- PHASE 3: CREATE TASK FORM ----
                st.markdown("### ➕ Tạo Task / Subtask")
                existing_tasks = db.get_tasks_by_project(selected_project_id) or []
                parent_options = {"": "— None (top-level task) —"}
                for t in existing_tasks:
                    parent_options[t["task_id"]] = f"{t.get('title')} ({t.get('status')})"

                with st.form("create_task_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        task_title = st.text_input("Tiêu đề task *")
                        task_desc = st.text_area("Mô tả")
                        task_priority = st.selectbox("Priority", ["Low", "Medium", "High"])
                    with col2:
                        task_status = st.selectbox("Status", ["Todo", "InProgress", "Review", "Done"])
                        task_due = st.date_input("Due date", value=date.today() + __import__('datetime').timedelta(days=7))
                        task_est = st.number_input("Estimated hours", min_value=0.0, step=0.5)
                        task_parent = st.selectbox(
                            "Task cha (subtask của...)",
                            options=list(parent_options.keys()),
                            format_func=lambda x: parent_options.get(x, "Unknown"),
                        )

                    submitted = st.form_submit_button("✅ Tạo Task")
                    if submitted:
                        if not task_title:
                            st.error("Tiêu đề task là bắt buộc!")
                        else:
                            try:
                                task_data = {
                                    "project_id": selected_project_id,
                                    "title": task_title,
                                    "description": task_desc,
                                    "status": task_status,
                                    "priority": task_priority,
                                    "estimated_hours": task_est if task_est > 0 else None,
                                    "due_date": task_due,
                                    "parent_task_id": task_parent if task_parent else None,
                                }
                                db.create_tasks_batch([task_data])
                                st.success(f"✅ Đã tạo task: {task_title}")
                                st.session_state.dashboard_snapshot = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"Lỗi: {str(e)}")

                # ---- TASK LIST WITH UPDATE/DELETE ----
                st.divider()
                st.markdown("### ✏️ Cập nhật / Xóa Task")
                if existing_tasks:
                    for t in existing_tasks:
                        cols = st.columns([3, 1, 1, 1, 0.5])
                        parent_hint = ""
                        if t.get("parent_task_id"):
                            parent_hint = " └ "
                        with cols[0]:
                            st.write(f"{parent_hint}{t.get('title')} ({t.get('status')})")
                        with cols[1]:
                            new_status = st.selectbox(
                                f"Status_{t['task_id']}",
                                ["Todo", "InProgress", "Review", "Done"],
                                index=["Todo", "InProgress", "Review", "Done"].index(t.get("status", "Todo")),
                                key=f"status_{t['task_id']}",
                                label_visibility="collapsed",
                            )
                            if new_status != t.get("status"):
                                db.update_task_status(t["task_id"], new_status)
                                st.success(f"Đã cập nhật {t.get('title')} → {new_status}")
                                st.session_state.dashboard_snapshot = None
                                st.rerun()
                        with cols[2]:
                            if st.button("🗑️", key=f"del_task_{t['task_id']}"):
                                db._execute("DELETE FROM tasks WHERE task_id = %s", (t["task_id"],))
                                st.session_state.dashboard_snapshot = None
                                st.rerun()
                        with cols[3]:
                            # Nút tạo subtask nhanh
                            if st.button("➕Subt", key=f"sub_{t['task_id']}"):
                                st.session_state[f"quick_sub_{t['task_id']}"] = True
                        with cols[4]:
                            if t.get("parent_task_id"):
                                st.write("📎")
                        # Quick subtask form
                        if st.session_state.get(f"quick_sub_{t['task_id']}"):
                            with st.form(key=f"quick_sub_form_{t['task_id']}"):
                                sub_title = st.text_input("Subtask title", key=f"sub_title_{t['task_id']}")
                                col_a, col_b = st.columns(2)
                                with col_a:
                                    sub_status = st.selectbox("Status", ["Todo", "InProgress", "Review", "Done"], key=f"sub_st_{t['task_id']}")
                                with col_b:
                                    sub_due = st.date_input("Due", value=date.today(), key=f"sub_due_{t['task_id']}")
                                if st.form_submit_button("Tạo Subtask"):
                                    if sub_title:
                                        new_tasks = db.create_tasks_batch([{
                                            "project_id": selected_project_id,
                                            "title": sub_title,
                                            "description": "",
                                            "status": sub_status,
                                            "priority": "Medium",
                                            "due_date": sub_due,
                                            "parent_task_id": t["task_id"],
                                        }])
                                        # Auto-inherit assignee từ task cha
                                        if new_tasks:
                                            parent_assignee = db.get_task_assignee(t["task_id"])
                                            if parent_assignee:
                                                db.create_task_assignments_batch([{
                                                    "task_id": new_tasks[0]["task_id"],
                                                    "user_id": parent_assignee["user_id"],
                                                    "assigned_by": user_id,
                                                }])
                                                db.update_task_status(new_tasks[0]["task_id"], "InProgress")
                                        st.session_state[f"quick_sub_{t['task_id']}"] = False
                                        st.session_state.dashboard_snapshot = None
                                        st.rerun()
                else:
                    st.info("Chưa có task nào. Hãy tạo task đầu tiên ở form trên.")

    # ==================== SUBTAB 3: QUẢN LÝ TEAM ====================
    with subtab3:
        st.subheader("👥 Quản lý Team")

        col1, col2 = st.columns([1, 1])

        # --- Tạo Team Mới (Toàn cục) ---
        with col1:
            st.subheader("➕ Tạo User / Team Mới")
            new_name = st.text_input("Tên thành viên")
            new_email = st.text_input("Email")
            new_role = st.selectbox("Vai trò", ["leader", "member"])
            new_skill = st.text_input("Kỹ năng nổi bật", "Backend, Frontend...")

            if st.button("Tạo User Mới"):
                if new_name and new_email:
                    user_data = {
                        "name": new_name,
                        "email": new_email,
                        "role": new_role,
                        "skill_notes": new_skill
                    }
                    db.create_user(user_data)
                    st.success(f"✅ Đã tạo user: {new_name}")
                    st.rerun()
                else:
                    st.error("Vui lòng nhập tên và email")

            # Thêm member vào project
            if selected_project_id:
                st.divider()
                st.subheader("➕ Thêm Member vào Project")
                all_users = db.get_users() or []
                member_ids = {m.get("user_id") for m in (dashboard_data.get("members") or []) if dashboard_data}
                available = [u for u in all_users if u.get("user_id") not in member_ids]
                if available:
                    user_sel = st.selectbox(
                        "Chọn user",
                        available,
                        format_func=lambda u: f"{u.get('name')} ({u.get('email')})",
                    )
                    role_sel = st.selectbox("Vai trò", ["Member", "Leader", "Developer", "Designer", "Tester"])
                    if st.button("Thêm vào Project"):
                        db.create_project_member(
                            selected_project_id,
                            user_sel["user_id"],
                            role_sel,
                            100,
                        )
                        st.success(f"Đã thêm {user_sel.get('name')} vào project")
                        st.session_state.dashboard_snapshot = None
                        st.rerun()
                else:
                    st.info("Tất cả users đã là member của project này.")

        # --- Quản lý Thành viên trong Project ---
        with col2:
            st.subheader("👤 Thành viên trong Project")
            if dashboard_data:
                project = dashboard_data.get("project") or {}
                st.write(f"**Dự án:** {project.get('name', 'Untitled')}")

                members = dashboard_data.get("members") or []
                workload = dashboard_data.get("workload") or []

                for member in (members or []):
                    col_a, col_b = st.columns([4, 1])
                    with col_a:
                        st.write(f"• **{member.get('name','Unknown')}** - {member.get('role_in_project')} ({member.get('workload_capacity',0)}%)")
                    with col_b:
                        if st.button("🗑️", key=f"del_{member.get('project_member_id')}"):
                            db.delete_project_member(member.get('project_member_id'))
                            st.success("Đã xóa thành viên")
                            st.session_state.dashboard_snapshot = None
                            st.rerun()

                st.subheader("📌 Workload Summary")
                workload_rows = []
                for row in workload:
                    workload_rows.append(
                        {
                            "Member": row.get("name"),
                            "Role": row.get("role_in_project"),
                            "Capacity (%)": row.get("workload_capacity", 0),
                            "Assigned Tasks": row.get("assigned_task_count", 0),
                            "Estimated Hours": row.get("total_estimated_hours", 0),
                            "Actual Hours": row.get("total_actual_hours", 0),
                        }
                    )
                if workload_rows:
                    st.dataframe(workload_rows, use_container_width=True, hide_index=True)
            else:
                st.warning("Chưa có project. Hãy tạo project trước.")

    # ==================== SUBTAB 4: RỦI RO ====================
    with subtab4:
        st.subheader("⚠️ Rủi Ro Dự Án")
        if dashboard_data:
            risks = dashboard_data.get("risks") or []
            risk_summary = dashboard_data.get("risk_summary") or {}
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                st.metric("Tổng Risks", risk_summary.get("total_risks", 0))
            with col_b:
                st.metric("Open", risk_summary.get("open_risks", 0))
            with col_c:
                st.metric("Mitigating", risk_summary.get("mitigating_risks", 0))
            with col_d:
                st.metric("Avg Score", round(float(risk_summary.get("avg_risk_score", 0) or 0), 2))

            for risk in (risks or []):
                score = risk.get('risk_score', 0) or 0
                color = "🔴" if score >= 7 else "🟠" if score >= 4 else "🟢"
                st.write(f"{color} **{risk.get('title','Untitled')}** (Score: {score}) - {risk.get('status','Unknown')}")
        else:
            st.info("Chưa có project.")

    # ==================== SUBTAB 5: ASSIGNMENT REVIEW (PHASE 4b) ====================
    with subtab5:
        st.subheader("✅ Assignment Review")

        if not selected_project_id:
            st.warning("Vui lòng chọn project từ sidebar trước.")
        else:
            # Hiển thị recommendations từ AI
            recommendations = st.session_state.task_recommendations
            existing_assignments = db.get_task_assignments_by_project(selected_project_id) or []
            assigned_task_ids = {a.get("task_id") for a in existing_assignments}

            # Nút gọi AI để gợi ý assignment
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("**Gợi ý assignment từ AI** — Task Divider sẽ phân tích kỹ năng và workload để đề xuất.")
            with col2:
                if st.button("🤖 Gợi ý Assignment", use_container_width=True):
                    if selected_project_id:
                        inputs = {
                            "user_input": "gợi ý assignment cho project này",
                            "user_id": user_id,
                            "project_id": selected_project_id,
                            "messages": [],
                            "tasks": [],
                            "risks": [],
                            "current_phase": "ready",
                        }
                        with st.spinner("AI đang phân tích..."):
                            result = run_orchestrator(inputs)
                            if result.get("tasks"):
                                st.session_state.task_recommendations = {
                                    "project_id": selected_project_id,
                                    "tasks": result.get("tasks", []),
                                    "response": result.get("messages", [])[-1].get("content") if result.get("messages") else "",
                                }
                                st.success("Đã nhận được gợi ý! Kiểm tra bên dưới.")
                                st.rerun()
                            else:
                                st.info("Chưa có gợi ý. Hãy tạo task trước hoặc dùng chat để yêu cầu.")

            st.divider()

            # Hiển thị tasks chưa được assigned
            tasks = db.get_tasks_by_project(selected_project_id) or []
            top_level_tasks = [t for t in tasks if not t.get("parent_task_id")]
            unassigned_tasks = [t for t in top_level_tasks if t.get("task_id") not in assigned_task_ids]

            all_users = db.get_users() or []
            user_options = {"": "— Chưa gán —"}
            for u in all_users:
                user_options[u["user_id"]] = f"{u.get('name')} ({u.get('email')})"

            # ---- BATCH ASSIGNMENT: 1 button cho tất cả tasks ----
            if unassigned_tasks:
                st.markdown(f"### 📋 Task chưa được gán ({len(unassigned_tasks)})")
                st.caption("Chọn người cho từng task bên dưới, sau đó bấm **💾 Gán tất cả** để lưu 1 lần.")

                # Gom selection vào session_state
                if "batch_assign_selections" not in st.session_state:
                    st.session_state.batch_assign_selections = {}

                # Hiển thị tất cả unassigned tasks với selectbox
                batch_data = []
                for t in unassigned_tasks:
                    task_id = t["task_id"]
                    default_val = st.session_state.batch_assign_selections.get(task_id, "")
                    col_a, col_b = st.columns([2, 3])
                    with col_a:
                        st.write(f"**{t.get('title')}**")
                    with col_b:
                        sel = st.selectbox(
                            f"Người thực hiện cho {t.get('title')}",
                            options=list(user_options.keys()),
                            format_func=lambda x: user_options.get(x, "Unknown"),
                            key=f"batch_assign_{task_id}",
                            label_visibility="collapsed",
                        )
                    st.session_state.batch_assign_selections[task_id] = sel
                    if sel:
                        batch_data.append({"task_id": task_id, "user_id": sel})

                # Nút "Gán tất cả" — 1 click, 1 DB batch write, có propagate
                if batch_data:
                    if st.button(f"💾 Gán tất cả ({len(batch_data)} tasks — sẽ propagate xuống children)", use_container_width=True, type="primary"):
                        with st.spinner("Đang gán và propagate xuống children..."):
                            success_count = 0
                            total_count = 0
                            for item in batch_data:
                                try:
                                    result = db.assign_task_with_children(
                                        item["task_id"],
                                        item["user_id"],
                                        user_id,
                                    )
                                    success_count += 1
                                    total_count += result["assigned_count"]
                                except Exception as e:
                                    st.error(f"Lỗi khi gán task {item['task_id']}: {str(e)}")

                            st.session_state.batch_assign_selections = {}
                            st.session_state.dashboard_snapshot = None
                            st.success(f"✅ Đã gán {success_count} tasks cha + {total_count - success_count} children (tổng {total_count} tasks)!")
                            st.rerun()
            else:
                st.info("Tất cả tasks top-level đã được gán hoặc chưa có task nào.")

            # Hiển thị AI Recommendations (nếu có)
            if recommendations and recommendations.get("project_id") == selected_project_id:
                st.divider()
                st.markdown(f"### 💡 Đề xuất từ AI ({len(recommendations.get('tasks', []))} tasks)")

                for rec in recommendations.get("tasks", []):
                    with st.container():
                        st.markdown(f"**📌 {rec.get('task_title', 'Unknown')}**")
                        assigned_uid = rec.get("assigned_user_id")
                        recommended_name = rec.get("assigned_to", "Unknown")
                        reason = rec.get("reason", "")
                        if assigned_uid and assigned_uid in user_options:
                            st.info(f"💡 **Gợi ý**: {recommended_name} — {reason}")
                        st.divider()

            # Hiển thị assignments hiện tại
            if existing_assignments:
                st.divider()
                st.markdown(f"### 📋 Assignments hiện tại ({len(existing_assignments)})")
                assign_rows = []
                for a in existing_assignments:
                    assign_rows.append({
                        "Task": a.get("task_title", "Unknown"),
                        "Assignee": a.get("assignee_name", "Unknown"),
                        "Status": a.get("task_status", "Unknown"),
                        "Priority": a.get("task_priority", "Medium"),
                        "Due": a.get("due_date"),
                    })
                st.dataframe(assign_rows, use_container_width=True, hide_index=True)

    # ==================== SUBTAB 6: SYSTEM MONITORING ====================
    with subtab6:
        st.subheader("📊 System Monitoring (Redis)")

        col1, col2 = st.columns(2)

        with col1:
            st.metric("Redis Status", "🟢 Connected" if redis_client.client else "🔴 Disconnected")

            # Cache Statistics
            try:
                cache_keys = (
                    redis_client.client.keys("task_divider:*")
                    + redis_client.client.keys("risk:*")
                    + redis_client.client.keys("dashboard:*")
                    + redis_client.client.keys("users:*")
                )
                st.metric("Total Cached Items", len(cache_keys))
            except:
                st.metric("Total Cached Items", "N/A")

        with col2:
            # Recent Reminder Logs
            st.subheader("Recent Reminder Logs")
            logs = redis_client.client.lrange("reminder_logs", 0, 9)
            if logs:
                for log in logs:
                    data = json.loads(log)
                    st.caption(f"{data['timestamp'][:16]} - {data['message']}")
            else:
                st.info("Chưa có reminder log nào.")

        st.divider()

        # Button controls
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("🔄 Clear All Cache"):
                redis_client.clear_cache()
                st.success("Đã xóa toàn bộ cache!")
                st.rerun()

        with col_b:
            if st.button("📋 View All Cache Keys"):
                try:
                    keys = redis_client.client.keys("*")
                    st.write(keys[:30])
                except:
                    st.error("Không thể lấy keys")

        with col_c:
            if st.button("📈 Refresh Metrics"):
                st.rerun()

        st.divider()

        st.subheader("🧭 Orchestrator Event Log")
        log_limit = st.slider("Số dòng log gần nhất", min_value=10, max_value=100, value=25, step=5)
        event_filter = st.text_input("Lọc theo event prefix", value="")

        events = read_recent_log_events(limit=log_limit, event_prefix=event_filter.strip() or None)
        if events:
            st.caption(f"Hiển thị {len(events)} event gần nhất từ logs/app.log")
            for event in events:
                with st.expander(f"{event.get('event', 'unknown')} | {event.get('ts', '')}"):
                    st.json(event)
        else:
            st.info("Chưa có log orchestrator nào khớp bộ lọc.")

        if dashboard_data:
            st.divider()
            st.subheader("🧾 Audit Timeline")
            audit_logs = dashboard_data.get("audit_logs") or []
            if audit_logs:
                for log in audit_logs[:20]:
                    st.write(
                        "• {time} | {action} | {entity}".format(
                            time=log.get("created_at"),
                            action=log.get("action"),
                            entity=log.get("entity_type") or "Unknown",
                        )
                    )
            else:
                st.info("Chưa có audit log cho project này.")

st.caption("AI Team Task Agent | Version 2.0 | Refactored: Manual Project/Task Management + AI Assistant")