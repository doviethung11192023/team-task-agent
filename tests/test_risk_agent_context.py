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

import app.agents.risk_agent as risk_module


class FakeLLMResponse:
    content = (
        '{"risks": ['
        '{"title": "Timeline slip", "description": "Deadline may move", "probability": "Medium", "impact": "High", '
        '"mitigation_plan": "Track milestones", "contingency_plan": "Reduce scope"}'
        ']}'
    )


class FakeLLM:
    def invoke(self, messages):
        return FakeLLMResponse()


def test_risk_agent_uses_planner_context_and_serializes_datetimes(monkeypatch):
    project_data = {
        "name": "Demo Shop",
        "description": "Build a souvenir app",
        "end_date": datetime(2026, 7, 15, 0, 0, 0),
        "created_at": datetime(2026, 5, 31, 10, 0, 0),
        "tasks": [
            {
                "title": "Design landing page",
                "due_date": datetime(2026, 6, 5, 0, 0, 0),
                "created_at": datetime(2026, 5, 31, 11, 0, 0),
            }
        ],
    }
    tasks = [
        {
            "title": "Design landing page",
            "due_date": datetime(2026, 6, 5, 0, 0, 0),
            "created_at": datetime(2026, 5, 31, 11, 0, 0),
        }
    ]

    monkeypatch.setattr(risk_module, "llm", FakeLLM())
    monkeypatch.setattr(risk_module.redis_client, "get", lambda key: None)
    monkeypatch.setattr(risk_module.redis_client, "set", lambda *args, **kwargs: True)
    monkeypatch.setattr(risk_module.db, "get_project", lambda project_id: (_ for _ in ()).throw(AssertionError("db.get_project should not be called")))
    monkeypatch.setattr(risk_module.db, "get_tasks_by_project", lambda project_id: (_ for _ in ()).throw(AssertionError("db.get_tasks_by_project should not be called")))
    monkeypatch.setattr(risk_module.db, "create_risks_batch", lambda risks: risks)
    # Phase 6: mock new DB calls used by rule-based detection
    monkeypatch.setattr(risk_module.db, "get_member_workload", lambda project_id: [])
    monkeypatch.setattr(risk_module.db, "calculate_project_progress", lambda project_id: 50)

    result = risk_module.risk_agent("project-1", project_data=project_data, tasks=tasks)

    assert result.success is True
    assert result.risks[0]["title"] == "Timeline slip"