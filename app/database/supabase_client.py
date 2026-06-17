# app/database/supabase_client.py
from config import config
from typing import List, Dict, Optional, Any, Iterable
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import extensions
from app.utils.serialization import serialize_for_json

class SupabaseDB:
    def __init__(self):
        # ==================== Direct PostgreSQL Connection (psycopg2) ====================
        self.conn = None
        try:
            self.conn = psycopg2.connect(
                host=config.DB_HOST,
                port=config.DB_PORT,
                database=config.DB_NAME,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                sslmode=config.DB_SSLMODE
            )
            print("Direct PostgreSQL connection established")
        except Exception as e:
            print(f"WARNING: could not connect to direct PostgreSQL: {e}")
            self.conn = None

    def _ensure_connection(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(
                host=config.DB_HOST,
                port=config.DB_PORT,
                database=config.DB_NAME,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                sslmode=config.DB_SSLMODE,
            )
        elif self.conn.status != extensions.STATUS_READY:
            try:
                self.conn.rollback()
            except Exception:
                self.conn.close()
                self.conn = psycopg2.connect(
                    host=config.DB_HOST,
                    port=config.DB_PORT,
                    database=config.DB_NAME,
                    user=config.DB_USER,
                    password=config.DB_PASSWORD,
                    sslmode=config.DB_SSLMODE,
                )

    def _fetchall(self, query: str, params: Optional[tuple] = None) -> List[Dict]:
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params or ())
                rows = cursor.fetchall()
            return [serialize_for_json(dict(row)) for row in rows]
        except Exception:
            if self.conn:
                self.conn.rollback()
            raise

    def _fetchone(self, query: str, params: Optional[tuple] = None) -> Optional[Dict]:
        rows = self._fetchall(query, params)
        return rows[0] if rows else None

    def _execute(self, query: str, params: Optional[tuple] = None, fetch: bool = False):
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params or ())
                result = cursor.fetchall() if fetch else None
            self.conn.commit()
            return [serialize_for_json(dict(row)) for row in result] if result else []
        except Exception:
            if self.conn:
                self.conn.rollback()
            raise

    # ====================== USERS / PROJECTS / TASKS / RISKS ======================
    def get_users(self) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                user_id::text,
                name,
                email,
                role,
                avatar_url,
                skill_notes,
                created_at,
                updated_at
            FROM users
            ORDER BY created_at DESC
            """
        )

    def get_user(self, user_id: str) -> Optional[Dict]:
        return self._fetchone(
            """
            SELECT
                user_id::text,
                name,
                email,
                role,
                avatar_url,
                skill_notes,
                created_at,
                updated_at
            FROM users
            WHERE user_id = %s
            """,
            (user_id,),
        )

    def create_user(self, user_data: Dict) -> Dict:
        rows = self._execute(
            """
            INSERT INTO users (name, email, role, avatar_url, skill_notes)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING user_id::text, name, email, role, avatar_url, skill_notes, created_at, updated_at
            """,
            (
                user_data.get("name"),
                user_data.get("email"),
                user_data.get("role", "member"),
                user_data.get("avatar_url"),
                user_data.get("skill_notes"),
            ),
            fetch=True,
        )
        return rows[0] if rows else {}

    def get_projects(self) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                project_id::text,
                name,
                description,
                start_date,
                end_date,
                status,
                owner_id::text,
                progress_percentage,
                created_at,
                updated_at
            FROM projects
            ORDER BY created_at DESC
            """
        )

    def get_projects_by_owner(self, owner_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                project_id::text,
                name,
                description,
                start_date,
                end_date,
                status,
                owner_id::text,
                progress_percentage,
                created_at,
                updated_at
            FROM projects
            WHERE owner_id = %s
            ORDER BY updated_at DESC
            """,
            (owner_id,),
        )

    def create_project(self, project_data: Dict) -> Dict:
        rows = self._execute(
            """
            INSERT INTO projects (name, description, start_date, end_date, owner_id, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING
                project_id::text,
                name,
                description,
                start_date,
                end_date,
                status,
                owner_id::text,
                progress_percentage,
                created_at,
                updated_at
            """,
            (
                project_data.get("name"),
                project_data.get("description"),
                project_data.get("start_date"),
                project_data.get("end_date"),
                project_data.get("owner_id"),
                project_data.get("status", "Planning"),
            ),
            fetch=True,
        )
        return rows[0] if rows else {}

    def get_project(self, project_id: str) -> Optional[Dict]:
        return self._fetchone(
            """
            SELECT
                project_id::text,
                name,
                description,
                start_date,
                end_date,
                status,
                owner_id::text,
                progress_percentage,
                created_at,
                updated_at
            FROM projects
            WHERE project_id = %s
            """,
            (project_id,),
        )

    def get_tasks_by_project(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                task_id::text,
                project_id::text,
                title,
                description,
                status,
                priority,
                estimated_hours,
                actual_hours,
                start_date,
                due_date,
                parent_task_id::text,
                created_at,
                updated_at
            FROM tasks
            WHERE project_id = %s
            ORDER BY created_at DESC
            """,
            (project_id,),
        )
    def get_tasks_by_project_status(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                task_id::text,
                project_id::text,
                title,
                description,
                status,
                priority,
                estimated_hours,
                actual_hours,
                start_date,
                due_date,
                parent_task_id::text,
                created_at,
                updated_at
            FROM tasks
            WHERE project_id = %s AND status = 'Todo'
            ORDER BY created_at DESC
            """,
            (project_id,),
        )
    def create_tasks_batch(self, tasks: List[Dict]) -> List[Dict]:
        if not tasks:
            return []

        self._ensure_connection()
        try:
            inserted_rows: List[Dict] = []
            query = """
                INSERT INTO tasks (
                    project_id, title, description, status, priority,
                    estimated_hours, actual_hours, start_date, due_date, parent_task_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    task_id::text,
                    project_id::text,
                    title,
                    description,
                    status,
                    priority,
                    estimated_hours,
                    actual_hours,
                    start_date,
                    due_date,
                    parent_task_id::text,
                    created_at,
                    updated_at
            """
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for task in tasks:
                    cursor.execute(
                        query,
                        (
                            task.get("project_id"),
                            task.get("title"),
                            task.get("description"),
                            task.get("status", "Todo"),
                            task.get("priority", "Medium"),
                            task.get("estimated_hours"),
                            task.get("actual_hours"),
                            task.get("start_date"),
                            task.get("due_date"),
                            task.get("parent_task_id"),
                        ),
                    )
                    inserted_rows.append(serialize_for_json(dict(cursor.fetchone())))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return inserted_rows

    def update_task_status(self, task_id: str, status: str, actual_hours: float = None):
        update_data = [status, actual_hours, task_id]
        self._execute(
            """
            UPDATE tasks
            SET status = %s,
                actual_hours = COALESCE(%s, actual_hours),
                updated_at = NOW()
            WHERE task_id = %s
            """,
            tuple(update_data),
        )

    def create_risks_batch(self, risks: List[Dict]) -> List[Dict]:
        if not risks:
            return []

        self._ensure_connection()
        try:
            inserted: List[Dict] = []
            query = """
                INSERT INTO risks (
                    project_id, title, description, probability, impact,
                    status, owner_id, mitigation_plan, contingency_plan
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    risk_id::text,
                    project_id::text,
                    title,
                    description,
                    probability,
                    impact,
                    risk_score,
                    status,
                    owner_id::text,
                    mitigation_plan,
                    contingency_plan,
                    detected_at,
                    resolved_at,
                    created_at
            """
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for risk in risks:
                    cursor.execute(
                        query,
                        (
                            risk.get("project_id"),
                            risk.get("title"),
                            risk.get("description"),
                            risk.get("probability", "Medium"),
                            risk.get("impact", "Medium"),
                            risk.get("status", "Open"),
                            risk.get("owner_id"),
                            risk.get("mitigation_plan"),
                            risk.get("contingency_plan"),
                        ),
                    )
                    inserted.append(serialize_for_json(dict(cursor.fetchone())))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return inserted

    def create_task_assignments_batch(self, assignments: List[Dict]) -> List[Dict]:
        if not assignments:
            return []

        self._ensure_connection()
        try:
            inserted: List[Dict] = []
            query = """
                INSERT INTO task_assignments (
                    task_id, user_id, assigned_by
                )
                VALUES (%s, %s, %s)
                RETURNING
                    assignment_id::text,
                    task_id::text,
                    user_id::text,
                    assigned_at,
                    assigned_by::text
            """
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for assignment in assignments:
                    cursor.execute(
                        query,
                        (
                            assignment.get("task_id"),
                            assignment.get("user_id"),
                            assignment.get("assigned_by"),
                        ),
                    )
                    inserted.append(serialize_for_json(dict(cursor.fetchone())))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return inserted

    def get_task_assignments_by_project(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                ta.assignment_id::text,
                ta.task_id::text,
                ta.user_id::text,
                ta.assigned_at,
                ta.assigned_by::text,
                u.name AS assignee_name,
                u.email AS assignee_email,
                t.title AS task_title,
                t.status AS task_status,
                t.priority AS task_priority,
                t.due_date
            FROM task_assignments ta
            JOIN tasks t ON t.task_id = ta.task_id
            JOIN users u ON u.user_id = ta.user_id
            WHERE t.project_id = %s
            ORDER BY ta.assigned_at DESC
            """,
            (project_id,),
        )

    def get_task_status_summary(self, project_id: str) -> Dict[str, int]:
        rows = self._fetchall(
            """
            SELECT status, COUNT(*)::int AS count
            FROM tasks
            WHERE project_id = %s
            GROUP BY status
            """,
            (project_id,),
        )
        summary = {"Todo": 0, "InProgress": 0, "Review": 0, "Done": 0}
        for row in rows:
            status = row.get("status")
            count = row.get("count", 0)
            if status:
                summary[status] = int(count)
        return summary

    def get_overdue_tasks(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                task_id::text,
                project_id::text,
                title,
                description,
                status,
                priority,
                estimated_hours,
                actual_hours,
                start_date,
                due_date,
                parent_task_id::text,
                created_at,
                updated_at
            FROM tasks
            WHERE project_id = %s
              AND due_date < CURRENT_DATE
              AND status <> 'Done'
            ORDER BY due_date ASC
            """,
            (project_id,),
        )

    def get_risk_summary(self, project_id: str) -> Dict:
        rows = self._fetchall(
            """
            SELECT
                COUNT(*)::int AS total_risks,
                COUNT(CASE WHEN status = 'Open' THEN 1 END)::int AS open_risks,
                COUNT(CASE WHEN status = 'Mitigating' THEN 1 END)::int AS mitigating_risks,
                COUNT(CASE WHEN status = 'Closed' THEN 1 END)::int AS closed_risks,
                COALESCE(AVG(risk_score)::numeric, 0) AS avg_risk_score,
                COALESCE(MAX(risk_score), 0) AS max_risk_score
            FROM risks
            WHERE project_id = %s
            """,
            (project_id,),
        )
        return rows[0] if rows else {
            "total_risks": 0,
            "open_risks": 0,
            "mitigating_risks": 0,
            "closed_risks": 0,
            "avg_risk_score": 0,
            "max_risk_score": 0,
        }

    def get_audit_logs(self, project_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
        if project_id:
            return self._fetchall(
                """
                SELECT
                    log_id::text,
                    action,
                    entity_type,
                    entity_id::text,
                    performed_by::text,
                    details,
                    created_at
                FROM audit_logs
                WHERE entity_id::text = %s
                   OR details ->> 'project_id' = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, project_id, limit),
            )

        return self._fetchall(
            """
            SELECT
                log_id::text,
                action,
                entity_type,
                entity_id::text,
                performed_by::text,
                details,
                created_at
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )

    def get_member_workload(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                pm.user_id::text,
                u.name,
                pm.role_in_project,
                pm.workload_capacity,
                COUNT(DISTINCT ta.assignment_id)::int AS assigned_task_count,
                COALESCE(SUM(t.estimated_hours), 0) AS total_estimated_hours,
                COALESCE(SUM(t.actual_hours), 0) AS total_actual_hours
            FROM project_members pm
            JOIN users u ON u.user_id = pm.user_id
            LEFT JOIN task_assignments ta ON ta.user_id = pm.user_id
            LEFT JOIN tasks t
                ON t.task_id = ta.task_id
               AND t.project_id = pm.project_id
            WHERE pm.project_id = %s
            GROUP BY pm.user_id, u.name, pm.role_in_project, pm.workload_capacity
            ORDER BY u.name ASC
            """,
            (project_id,),
        )

    def get_risks_by_project(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                risk_id::text,
                project_id::text,
                title,
                description,
                probability,
                impact,
                risk_score,
                status,
                owner_id::text,
                mitigation_plan,
                contingency_plan,
                detected_at,
                resolved_at,
                created_at
            FROM risks
            WHERE project_id = %s
            ORDER BY created_at DESC
            """,
            (project_id,),
        )

    def update_risk_status(self, risk_id: str, status: str, actual_outcome: str = None):
        self._execute(
            """
            UPDATE risks
            SET status = %s,
                resolved_at = CASE WHEN %s = 'Closed' THEN NOW() ELSE resolved_at END
            WHERE risk_id = %s
            """,
            (status, status, risk_id),
        )

    def update_project_progress(self, project_id: str, progress_percentage: int):
        self._execute(
            """
            UPDATE projects
            SET progress_percentage = %s,
                updated_at = NOW()
            WHERE project_id = %s
            """,
            (progress_percentage, project_id),
        )

    def get_project_members(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                pm.project_member_id::text,
                pm.project_id::text,
                pm.user_id::text,
                pm.role_in_project,
                pm.workload_capacity,
                pm.joined_at,
                u.name,
                u.email,
                u.skill_notes
            FROM project_members pm
            JOIN users u ON u.user_id = pm.user_id
            WHERE pm.project_id = %s
            ORDER BY pm.joined_at DESC
            """,
            (project_id,),
        )

    def create_project_member(self, project_id: str, user_id: str, role_in_project: str, workload_capacity: int = 100) -> Dict:
        rows = self._execute(
            """
            INSERT INTO project_members (project_id, user_id, role_in_project, workload_capacity)
            VALUES (%s, %s, %s, %s)
            RETURNING project_member_id::text, project_id::text, user_id::text, role_in_project, workload_capacity, joined_at
            """,
            (project_id, user_id, role_in_project, workload_capacity),
            fetch=True,
        )
        return rows[0] if rows else {}

    def delete_project_member(self, project_member_id: str):
        self._execute(
            "DELETE FROM project_members WHERE project_member_id = %s",
            (project_member_id,),
        )

    def log_audit(self, action: str, entity_type: str, entity_id: str, performed_by: str, details: Dict):
        self._execute(
            """
            INSERT INTO audit_logs (action, entity_type, entity_id, performed_by, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (action, entity_type, entity_id, performed_by, Json(details or {})),
        )

    # ====================== ASSIGNMENT INHERITANCE ======================
    def get_task_children(self, task_id: str) -> List[Dict]:
        """Lấy danh sách children trực tiếp của 1 task (không đệ quy)"""
        return self._fetchall(
            """
            SELECT
                task_id::text,
                project_id::text,
                title,
                description,
                status,
                priority,
                estimated_hours,
                actual_hours,
                start_date,
                due_date,
                parent_task_id::text,
                created_at,
                updated_at
            FROM tasks
            WHERE parent_task_id = %s
            ORDER BY created_at ASC
            """,
            (task_id,),
        )

    def get_all_task_children_recursive(self, task_id: str) -> List[Dict]:
        """Lấy tất cả children (đệ quy) của 1 task — BFS để tránh stack overflow"""
        all_children = []
        queue = [task_id]
        seen = {task_id}
        while queue:
            current = queue.pop(0)
            direct_children = self.get_task_children(current)
            for child in direct_children:
                child_id = child.get("task_id")
                if child_id and child_id not in seen:
                    seen.add(child_id)
                    all_children.append(child)
                    queue.append(child_id)
        return all_children

    def get_task_assignee(self, task_id: str) -> Optional[Dict]:
        """Lấy assignee hiện tại của 1 task (lấy mới nhất)"""
        rows = self._fetchall(
            """
            SELECT
                ta.assignment_id::text,
                ta.task_id::text,
                ta.user_id::text,
                ta.assigned_at,
                ta.assigned_by::text,
                u.name AS assignee_name,
                u.email AS assignee_email
            FROM task_assignments ta
            JOIN users u ON u.user_id = ta.user_id
            WHERE ta.task_id = %s
            ORDER BY ta.assigned_at DESC
            LIMIT 1
            """,
            (task_id,),
        )
        return rows[0] if rows else None

    def assign_task_with_children(self, task_id: str, user_id: str, assigned_by: str) -> Dict:
        """
        Gán task + tất cả children (đệ quy) cho cùng user.
        Xóa assignment cũ, INSERT assignment mới cho mỗi task.
        Trả về số lượng task đã gán.
        """
        if not user_id:
            return {"assigned_count": 0, "task_ids": []}

        # Thu thập tất cả task IDs cần gán: chính nó + children đệ quy
        task_ids_to_assign = [task_id]
        children = self.get_all_task_children_recursive(task_id)
        for child in children:
            task_ids_to_assign.append(child["task_id"])

        self._ensure_connection()
        try:
            inserted_count = 0
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for tid in task_ids_to_assign:
                    # Xóa assignment cũ
                    cursor.execute(
                        "DELETE FROM task_assignments WHERE task_id = %s",
                        (tid,),
                    )
                    # INSERT assignment mới
                    cursor.execute(
                        """
                        INSERT INTO task_assignments (task_id, user_id, assigned_by)
                        VALUES (%s, %s, %s)
                        RETURNING assignment_id::text, task_id::text, user_id::text, assigned_at, assigned_by::text
                        """,
                        (tid, user_id, assigned_by),
                    )
                    inserted_count += 1
                    # Update status thành InProgress
                    cursor.execute(
                        "UPDATE tasks SET status = 'InProgress', updated_at = NOW() WHERE task_id = %s AND status = 'Todo'",
                        (tid,),
                    )
            self.conn.commit()
            return {
                "assigned_count": inserted_count,
                "task_ids": task_ids_to_assign,
            }
        except Exception:
            self.conn.rollback()
            raise

    def delete_task_assignments(self, task_id: str):
        """Xóa tất cả assignments của 1 task"""
        self._execute(
            "DELETE FROM task_assignments WHERE task_id = %s",
            (task_id,),
        )

    # ====================== UTILITY ======================
    def calculate_project_progress(self, project_id: str) -> int:
        tasks = self.get_tasks_by_project(project_id)
        if not tasks:
            return 0
        completed = sum(1 for t in tasks if t.get('status') == 'Done')
        return int((completed / len(tasks)) * 100) if tasks else 0


# Singleton instance
db = SupabaseDB()