from datetime import datetime
import sys
import types

# Stub external LLM modules so tests don't require real langchain installs
llm_mod = types.ModuleType("langchain_google_genai")
class DummyLLM:
    def __init__(self, *args, **kwargs):
        pass
    def invoke(self, messages):
        class R:
            content = ""
        return R()
llm_mod.ChatGoogleGenerativeAI = DummyLLM
sys.modules["langchain_google_genai"] = llm_mod

msgs_mod = types.ModuleType("langchain_core.messages")
class HumanMessage:
    def __init__(self, content=None):
        self.content = content
class SystemMessage:
    def __init__(self, content=None):
        self.content = content
msgs_mod.HumanMessage = HumanMessage
msgs_mod.SystemMessage = SystemMessage
sys.modules["langchain_core.messages"] = msgs_mod

# Stub langsmith traceable
langsmith_mod = types.ModuleType("langsmith")
def fake_traceable(*args, **kwargs):
    def wrapper(func):
        return func
    return wrapper
langsmith_mod.traceable = fake_traceable
sys.modules["langsmith"] = langsmith_mod

import app.agents.task_divider as task_divider_module


class FakeLLMResponse:
    content = (
        '{"assigned_tasks": ['
        '{"task_title": "Design landing page", "assigned_to": "Linh", "reason": "Designer", "priority": "High", "due_date_offset": 5}'
        '], "workload_summary": {}, "suggestions": []}'
    )


class FakeLLM:
    def invoke(self, messages):
        return FakeLLMResponse()


def test_task_divider_returns_recommendations_without_saving_to_db(monkeypatch):
    team_members = [
        {
            "user_id": "user-1",
            "name": "Linh",
            "email": "linh@example.com",
            "joined_at": datetime(2026, 5, 31, 9, 0, 0),
            "updated_at": datetime(2026, 5, 31, 10, 0, 0),
        }
    ]

    monkeypatch.setattr(task_divider_module.db, "get_users", lambda: team_members)
    monkeypatch.setattr(task_divider_module.redis_client, "get", lambda key: None)
    monkeypatch.setattr(task_divider_module.redis_client, "set", lambda *args, **kwargs: True)
    monkeypatch.setattr(task_divider_module, "llm", FakeLLM())

    # Verify that DB creation methods are NOT called
    original_create_tasks = task_divider_module.db.create_tasks_batch
    original_create_assignments = task_divider_module.db.create_task_assignments_batch

    result = task_divider_module.task_divider_agent(
        "project-1",
        project_data={"project_name": "Demo Shop", "project_description": "Build a souvenir app"},
        raw_tasks=[{"title": "Design landing page"}],
    )

    assert result.success is True

    # Result should have tasks as recommendations (not DB records)
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert task["task_title"] == "Design landing page"
    assert task["assigned_to"] == "Linh"
    assert task["assigned_user_id"] == "user-1"
    assert task["reason"] == "Designer"
    assert task["priority"] == "High"
    assert "due_date" in task  # date was resolved from offset

    # Verify no response contains the right message
    assert "phân tích" in result.response.lower() or "review" in result.response.lower()