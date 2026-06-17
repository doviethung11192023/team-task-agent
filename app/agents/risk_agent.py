# app/agents/risk_agent.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.prompts.risk_prompts import RISK_SYSTEM_PROMPT
from app.models.schemas import AgentResponse
from app.database.supabase_client import db
from app.database.redis_client import redis_client
from config import config
import json
import hashlib
from langsmith import traceable
import time
from datetime import date, datetime
from app.utils.logger import get_logger, log_event, truncate_text, summarize_sequence
from app.utils.serialization import serialize_for_json

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    google_api_key=config.GEMINI_API_KEY
)

logger = get_logger("app.agents.risk_agent")

HIGH_RISK_THRESHOLD = 7


def _detect_rule_based_risks(project_id: str, project: dict, tasks: list) -> list:
    """Detect risks based on predefined rules (Phase 6)"""
    rule_risks = []
    today = date.today()

    # 1. Task overdue detection
    overdue_tasks = []
    for t in (tasks or []):
        due = t.get("due_date")
        status = t.get("status", "Todo")
        if due and status != "Done":
            try:
                if isinstance(due, str):
                    due_date = date.fromisoformat(due)
                elif isinstance(due, datetime):
                    due_date = due.date()
                else:
                    due_date = due
                if due_date < today:
                    overdue_tasks.append(t)
            except (ValueError, TypeError):
                pass

    if len(overdue_tasks) >= 2:
        rule_risks.append({
            "title": f"Nhiều task quá hạn ({len(overdue_tasks)})",
            "description": f"Có {len(overdue_tasks)} task đã quá hạn: {', '.join(t.get('title', '') for t in overdue_tasks[:5])}",
            "probability": "High",
            "impact": "High",
            "risk_score": 9,
            "mitigation_plan": "Review deadlines, phân bổ lại nguồn lực cho các task quá hạn",
            "contingency_plan": "Ưu tiên hoàn thành các task quá hạn trước, điều chỉnh timeline",
        })
    elif overdue_tasks:
        rule_risks.append({
            "title": f"Task quá hạn: {overdue_tasks[0].get('title')}",
            "description": f"Task '{overdue_tasks[0].get('title')}' đã quá hạn {abs((today - due_date).days)} ngày",
            "probability": "Medium",
            "impact": "Medium",
            "risk_score": 6,
            "mitigation_plan": "Kiểm tra nguyên nhân chậm, phân công lại nếu cần",
            "contingency_plan": "Gia hạn deadline hoặc chuyển task cho người khác",
        })

    # 2. High workload detection
    workload = db.get_member_workload(project_id) or []
    for w in workload:
        capacity = w.get("workload_capacity", 100) or 100
        assigned = w.get("assigned_task_count", 0) or 0
        if assigned >= 5:
            rule_risks.append({
                "title": f"Quá tải: {w.get('name')} ({assigned} tasks)",
                "description": f"{w.get('name')} đang được giao {assigned} tasks (capacity: {capacity}%)",
                "probability": "High",
                "impact": "Medium",
                "risk_score": 7,
                "mitigation_plan": "Phân bổ lại task cho member khác",
                "contingency_plan": "Thêm thành viên mới hoặc giảm scope",
            })

    # 3. Progress below expectations
    progress = db.calculate_project_progress(project_id)
    if progress < 20:
        rule_risks.append({
            "title": "Tiến độ thấp",
            "description": f"Dự án mới đạt {progress}% tiến độ, có nguy cơ chậm tiến độ tổng thể",
            "probability": "Medium",
            "impact": "High",
            "risk_score": 7,
            "mitigation_plan": "Xác định blockers, tăng tốc độ phát triển",
            "contingency_plan": "Điều chỉnh scope hoặc thêm nhân lực",
        })

    return rule_risks


@traceable(name="Risk Management Agent", run_type="chain")
def risk_agent(project_id: str, project_data: dict = None, tasks: list = None) -> AgentResponse:
    """
    Risk Agent với Redis Caching (REFACTORED: rule-based detection + cached tasks)
    """
    try:
        started_at = time.perf_counter()
        if not project_id:
            log_event(logger, "risk.enter.invalid_project", level="warning")
            return AgentResponse(response="Chưa có project để phân tích rủi ro.", success=False)

        # ==================== CACHING ====================
        cache_key = f"risk:{project_id}"
        log_event(
            logger,
            "risk.enter",
            project_id=project_id,
            cache_key=cache_key,
            project_data_keys=sorted(list((project_data or {}).keys()))[:10],
            tasks_summary=summarize_sequence(tasks, sample_key="title"),
        )

        cached_result = redis_client.get(cache_key)
        if cached_result:
            log_event(logger, "risk.cache.hit", cache_key=cache_key, project_id=project_id)
            return AgentResponse(**cached_result)

        # ==================== LOAD DATA ====================
        project = serialize_for_json(project_data or db.get_project(project_id) or {})
        tasks = serialize_for_json(tasks or (project_data or {}).get("tasks") or db.get_tasks_by_project(project_id) or [])
        log_event(logger, "risk.data.loaded", project_id=project_id, tasks_summary=summarize_sequence(tasks, sample_key="title"))

        # ==================== RULE-BASED DETECTION ====================
        rule_risks = _detect_rule_based_risks(project_id, project, tasks)
        log_event(logger, "risk.rule_based.detected", project_id=project_id, rule_risks_count=len(rule_risks))

        # ==================== GỌI LLM ====================
        prompt = f"""
        {RISK_SYSTEM_PROMPT}

        Thông tin Project:
        Tên: {project.get('name') or project.get('project_name')}
        Mô tả: {project.get('description') or project.get('project_description')}
        Deadline: {project.get('end_date')}
        Tiến độ hiện tại: {project.get('progress_percentage', 0)}%

        Danh sách Tasks ({len(tasks)} tasks):
        {json.dumps(tasks, ensure_ascii=False, indent=2)}

        Cảnh báo đã phát hiện tự động:
        {json.dumps(rule_risks, ensure_ascii=False, indent=2)}

        Lưu ý: Bổ sung thêm rủi ro LLM phát hiện được mà rule chưa bắt được.
        KHÔNG trùng lặp với các rủi ro đã được phát hiện ở trên.
        """

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content="Phân tích rủi ro chi tiết cho project này, bổ sung các rủi ro mà rule chưa phát hiện.")
        ]

        response = llm.invoke(messages)
        content = response.content.strip()
        log_event(logger, "risk.llm.response", project_id=project_id, content_preview=truncate_text(content, 220))

        try:
            if "{" in content:
                json_str = content[content.find("{"):content.rfind("}") + 1]
                result_data = json.loads(json_str)
            else:
                result_data = json.loads(content)
        except:
            result_data = {"risks": []}
            log_event(logger, "risk.parse.fallback", level="warning", project_id=project_id)

        # Merge rule-based + LLM risks (dedup by title)
        llm_risks = result_data.get("risks", [])
        seen_titles = {r.get("title", "").lower().strip() for r in rule_risks}
        for r in llm_risks:
            if r.get("title", "").lower().strip() not in seen_titles:
                rule_risks.append(r)

        # ==================== LƯU VÀO DATABASE ====================
        if rule_risks:
            risks_to_save = []
            for risk in rule_risks[:10]:
                risks_to_save.append({
                    "project_id": project_id,
                    "title": risk.get("title"),
                    "description": risk.get("description"),
                    "probability": risk.get("probability", "Medium"),
                    "impact": risk.get("impact", "Medium"),
                    "status": "Open",
                    "mitigation_plan": risk.get("mitigation_plan"),
                    "contingency_plan": risk.get("contingency_plan"),
                })
            if risks_to_save:
                db.create_risks_batch(risks_to_save)
                log_event(logger, "risk.db.risks_created", project_id=project_id, risks_to_save_count=len(risks_to_save))

        result = AgentResponse(
            response=f"⚠️ Đã phân tích rủi ro. Tìm thấy {len(rule_risks)} rủi ro "
                     f"(gồm {len(rule_risks) - len(llm_risks)} phát hiện tự động + {len(llm_risks)} từ AI).",
            risks=rule_risks,
            success=True
        ).dict()

        # ==================== LƯU CACHE ====================
        redis_client.set(cache_key, result, expire=900)   # Cache 15 phút

        log_event(
            logger,
            "risk.cache.save",
            cache_key=cache_key,
            project_id=project_id,
            risks_count=len(rule_risks),
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return AgentResponse(**result)

    except Exception as e:
        log_event(logger, "risk.exception", level="error", project_id=project_id, error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi khi phân tích rủi ro: {str(e)}",
            risks=[],
            success=False
        )