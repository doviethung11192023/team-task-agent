import pytest
import sys
import types

# Stub external LLM modules so tests don't require langchain installs
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

# Stub redis so RedisClient singleton can initialize in tests
redis_mod = types.ModuleType("redis")
class _DummyRedis:
    def __init__(self, *args, **kwargs):
        self._store = {}
    def ping(self):
        return True
    def set(self, k, v, ex=None):
        self._store[k] = v
    def get(self, k):
        return self._store.get(k)
    def delete(self, k):
        self._store.pop(k, None)
    def flushall(self):
        self._store.clear()
    def lrange(self, k, a, b):
        return self._store.get(k, [])
    def keys(self, pattern):
        return []

def _from_url(url, decode_responses=True):
    return _DummyRedis()

def _Redis(*args, **kwargs):
    return _DummyRedis()

redis_mod.from_url = _from_url
redis_mod.Redis = _Redis
sys.modules['redis'] = redis_mod

# Provide lightweight agent stubs so orchestrator import doesn't pull real dependencies
agent_names = [
    'app.agents.task_divider',
    'app.agents.progress_tracker',
    'app.agents.risk_agent',
    'app.agents.reminder_agent',
]
# We will inject specific agent module stubs into sys.modules in the test when needed

from app.graph import orchestrator as orch_module
from app.models.schemas import AgentResponse


def test_none_list_does_not_throw(monkeypatch):
    # Replace risk_agent with a fake that simulates a failure returning default AgentResponse
    # Inject a module `app.agents.risk_agent` so the lazy import inside orchestrator finds it
    risk_mod = types.ModuleType('app.agents.risk_agent')
    def fake_risk_agent(project_id, project_data=None, tasks=None):
        # Return AgentResponse without explicit risks (defaults to empty list)
        return AgentResponse(response="Simulated failure", success=False)
    risk_mod.risk_agent = fake_risk_agent
    sys.modules['app.agents.risk_agent'] = risk_mod

    inputs = {
        "user_input": "rủi ro",
        "user_id": "test-user",
        "project_id": "00000000-0000-0000-0000-000000000000",
        "messages": [],
        "tasks": [],
        "risks": [],
        "current_phase": "ready",
    }

    # Should not raise TypeError
    result = orch_module.orchestrator.invoke(inputs, config={"configurable": {"thread_id": "test-thread"}})

    assert isinstance(result, dict)
    assert "messages" in result
        # End of test case