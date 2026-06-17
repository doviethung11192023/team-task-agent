"""Lightweight stub of langgraph.graph for tests.
Provides a minimal StateGraph and END sentinel used by the orchestrator.
This is intentionally small and only for unit tests; real langgraph has much more.
"""
from typing import Any, Callable, Dict

END = "__END__"

class StateGraph:
    def __init__(self, state_type: Any = None):
        self.state_type = state_type
        self.nodes: Dict[str, Callable] = {}
        self.entry_point: str | None = None

    def add_node(self, name: str, func: Callable):
        self.nodes[name] = func

    def set_entry_point(self, name: str):
        self.entry_point = name

    def add_conditional_edges(self, *args, **kwargs):
        # no-op for stub; orchestrator nodes set state['next_step'] directly
        return None

    def add_edge(self, *args, **kwargs):
        # no-op for stub
        return None

    def compile(self, checkpointer=None):
        nodes = dict(self.nodes)
        entry = self.entry_point or next(iter(nodes))

        class App:
            def __init__(self, nodes, entry):
                self.nodes = nodes
                self.entry = entry

            def invoke(self, inputs: dict, config: dict = None):
                # Ensure lists exist
                state = dict(inputs)
                state.setdefault('messages', [])
                state.setdefault('tasks', [])
                state.setdefault('risks', [])

                current = self.entry
                # run until END or no next_step
                visits: dict[str, int] = {}
                MAX_VISITS = 50
                while current and current != END:
                    node = self.nodes.get(current)
                    if not node:
                        break
                    try:
                        node(state)
                    except Exception:
                        # swallow node errors in test stub
                        state.setdefault('error', 'node_error')

                    # track visits to prevent infinite loops in tests
                    visits[current] = visits.get(current, 0) + 1
                    if visits[current] > MAX_VISITS:
                        state.setdefault('error', f'visit_limit_exceeded:{current}')
                        break

                    nxt = state.get('next_step')
                    if not nxt or nxt == END:
                        break
                    current = nxt

                return state

        return App(nodes, entry)
