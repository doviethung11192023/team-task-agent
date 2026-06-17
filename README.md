# 🤖 AI Team Task Management Agent

> **Hệ thống AI Agent quản lý công việc nhóm thông minh** — hỗ trợ tạo/quản lý dự án thủ công, gợi ý phân công (AI), theo dõi tiến độ phân cấp, nhắc deadline đa mốc và quản lý rủi ro tự động. Xây dựng trên kiến trúc Multi-Agent với LangGraph + Google Gemini.

> **🔄 REFACTORED (v2.0):** Project và Task do **con người tạo** qua UI Form. AI chỉ đóng vai trò trợ lý: gợi ý assignment, phân tích rủi ro, theo dõi tiến độ, nhắc nhở. Planner Agent đã bị loại bỏ hoàn toàn.

---

## 📑 Mục lục

1. [Tổng Quan Kiến Trúc](#-tổng-quan-kiến-trúc)
2. [Công Nghệ Sử Dụng](#-công-nghệ-sử-dụng)
3. [Cấu Trúc Thư Mục](#-cấu-trúc-thư-mục)
4. [Database Schema (PostgreSQL)](#-database-schema-postgresql)
5. [Các Agent](#-các-agent)
6. [LangGraph Orchestrator](#-langgraph-orchestrator)
7. [End-to-End Flows](#-end-to-end-flows)
8. [Frontend (Streamlit)](#-frontend-streamlit)
9. [API Endpoints (FastAPI)](#-api-endpoints-fastapi)
10. [Tools Layer](#-tools-layer)
11. [Background Jobs](#-background-jobs)
12. [Redis Caching](#-redis-caching)
13. [Logging & Monitoring](#-logging--monitoring)
14. [Configuration & Environment](#-configuration--environment)
15. [Testing](#-testing)
16. [Hướng Dẫn Cài Đặt & Chạy](#-hướng-dẫn-cài-đặt--chạy)

---

## 🏗 Tổng Quan Kiến Trúc

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             FRONTEND (Streamlit :8501)                           │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │  Tab 1: Chat với AI Agent          │  Tab 2: Dashboard (6 subtabs)         │  │
│  │  - Chat messages                   │  - Overview (tree + metrics)          │  │
│  │  - Human-in-loop approval          │  - Task Management (CRUD + tree)      │  │
│  │  - User input field                │  - Team Management (members + create) │  │
│  │                                    │  - Risks                              │  │
│  │                                    │  - Assignment Review (AI + approve)   │  │
│  │                                    │  - System Monitoring                  │  │
│  └────────────────────────────────────┴───────────────────────────────────────┘  │
└──────────────────────────┬───────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          BACKEND (FastAPI :8000)                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │  POST /chat  │  REST API (/api/projects/*, /api/tasks/*, /api/users...)   │  │
│  │  POST /start-reminder  │  GET /health                                     │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────┬───────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          LANGGRAPH ORCHESTRATOR                                   │
│                                                                                  │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐                           │
│  │supervisor│───▶│ task_divider │───▶│      END      │  (chỉ recommend)          │
│  └─────┬────┘    └──────────────┘    └──────────────┘                           │
│        │                                                                        │
│        │  ┌──────────────────┐                                                  │
│        ├──▶ progress_tracker │───▶ reminder ──▶ END                             │
│        │  └──────────────────┘                                                  │
│        │                                                                        │
│        │  ┌──────────────────┐                                                  │
│        └──▶risk_assessment───┤                                                  │
│           └────────┬─────────┘                                                  │
│                    │                                                            │
│                    ▼                                                            │
│           ┌──────────────────┐                                                  │
│           │ human_approval   │──▶ (approved) ──▶ reminder ──▶ END               │
│           └──────────────────┘──▶ (rejected) ──▶ END                           │
│                                                                                  │
│   *** PLANNER AGENT ĐÃ BỊ LOẠI BỎ ***                                           │
│   *** Project/Task được tạo thủ công qua UI ***                                 │
└──────────────────────────┬───────────────────────────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
┌─────────────────┐ ┌──────────┐ ┌──────────────┐
│  PostgreSQL DB  │ │  Redis   │ │  Slack API   │
│  (psycopg2)     │ │  Cache   │ │  Notifications│
└─────────────────┘ └──────────┘ └──────────────┘
```

### Luồng dữ liệu tổng quát:

1. **Human PM** tạo project/task thủ công qua **Dashboard UI** (hoặc REST API)
2. **User** chat với AI Agent qua Streamlit (hoặc FastAPI `/chat`)
3. **FastAPI** nhận request → gọi `orchestrator.invoke()`
4. **Supervisor Node** xác định intent → route tới agent phù hợp
5. **Agent** gọi **Gemini LLM** với system prompt chuyên biệt
6. **Kết quả** được lưu xuống **PostgreSQL**, cache vào **Redis**
7. Nếu AI Task Divider gợi ý assignment → **PM Review** trước khi lưu
8. Nếu có rủi ro cao (score >= 7) → chờ **Human-in-the-Loop** approve/reject
9. Cuối cùng **Reminder** kiểm tra deadline đa mốc (7/3/1 ngày) và gửi **Slack notification**

---

## 🛠 Công Nghệ Sử Dụng

| Layer | Công Nghệ | Version |
|-------|-----------|---------|
| **Runtime** | Python 3.10+ | - |
| **Backend Framework** | FastAPI | 0.115.0 |
| **ASGI Server** | Uvicorn | 0.30.6 |
| **AI Orchestration** | LangGraph | 0.2.0 |
| **LLM Framework** | LangChain | 0.2.16 |
| **LLM Model** | Google Gemini 2.5 Flash | gemini-2.5-flash |
| **Database** | PostgreSQL (Supabase) | - |
| **Cache** | Redis (Docker: redis:7-alpine) | 5.2.1 |
| **Frontend** | Streamlit | 1.38.0 |
| **Tracing** | LangSmith | - |
| **Notifications** | Slack SDK | 3.31.0 |
| **Validation** | Pydantic v2 | 2.9.2 |
| **Scheduling** | schedule | 1.2.2 |

---

## 📁 Cấu Trúc Thư Mục Chi Tiết

```
E:\agent\ai-team-task-agent\
│
├── app/                                    # Backend source code
│   ├── main.py                             # FastAPI entry point (port 8000)
│   │
│   ├── agents/                             # Các AI Agent (4 agents)
│   │   ├── task_divider.py                 # Task Divider: gợi ý assignment (top-3)
│   │   ├── risk_agent.py                   # Risk: phân tích rủi ro (rule + LLM)
│   │   ├── progress_tracker.py             # Progress: theo dõi tiến độ phân cấp
│   │   └── reminder_agent.py              # Reminder: nhắc deadline Slack (7/3/1 ngày)
│   │
│   ├── database/                           # Database clients
│   │   ├── supabase_client.py              # PostgreSQL direct (psycopg2)
│   │   └── redis_client.py                 # Redis caching (singleton)
│   │
│   ├── graph/                              # LangGraph orchestration
│   │   └── orchestrator.py                 # State graph, nodes, edges, routing
│   │
│   ├── jobs/                               # Background jobs
│   │   └── reminder_job.py                 # ReminderJob: scheduled reminders
│   │
│   ├── models/                             # Pydantic data models
│   │   └── schemas.py                      # User, Project, Task, Risk, State, Response
│   │
│   ├── prompts/                            # LLM system prompts (split)
│   │   ├── task_divider_prompts.py          # TASK_DIVIDER_SYSTEM_PROMPT
│   │   ├── risk_prompts.py                  # RISK_SYSTEM_PROMPT
│   │
│   ├── tools/                              # Tool functions cho agents
│   │   ├── task_tools.py                   # create_project, create_tasks_batch, etc.
│   │   ├── risk_tools.py                   # RiskTools class
│   │   └── notification_tools.py           # NotificationTools (Slack)
│   │
│   └── utils/                              # Utilities
│       ├── serialization.py                # serialize_for_json (datetime, UUID, Decimal)
│       ├── logger.py                       # JSON logger + event helpers
│       ├── helpers.py                      # log_audit, build_graph_config
│       └── slack_client.py                 # send_slack_notification wrapper
│
├── frontend/                               # Streamlit UI
│   ├── streamlit_app.py                    # Main UI (2 tabs, 6 subtabs)
│   ├── components/
│   │   ├── chat.py                         # [PLACEHOLDER] chưa triển khai
│   │   └── dashboard.py                    # [PLACEHOLDER] chưa triển khai
│
├── langgraph/                              # Test stubs (khi không có langgraph thật)
│   ├── graph/
│   │   └── __init__.py                     # StateGraph stub với invoke()
│   └── checkpoint/
│       └── memory.py                       # MemorySaver stub (no-op)
│
├── supabase/                               # Database SQL
│   ├── schema.sql                          # 7 tables, indexes, triggers
│   └── seed_data.sql                       # Seed data (trống)
│
├── tests/                                  # Pytest tests (3 files, all pass)
│   ├── test_none_list_regression.py        # None-list edge case
│   ├── test_risk_agent_context.py          # Risk agent context + datetime serialization
│   └── test_task_divider_serialization.py  # Task divider recommendation output
│
├── config.py                               # Config singleton từ .env
├── requirements.txt                        # Python dependencies
├── docker-compose.yml                      # Redis service
├── .env                                    # [GITIGNORED] Secrets
└── README.md                               # This file (project brain)
```

---

## 🗄 Database Schema (PostgreSQL)

### 7 Tables

#### 1. `users`
| Column | Type | Notes |
|--------|------|-------|
| `user_id` | UUID PK | Default: `gen_random_uuid()` |
| `name` | VARCHAR(255) NOT NULL | |
| `email` | VARCHAR(255) UNIQUE NOT NULL | |
| `role` | VARCHAR(50) | Default: 'member' |
| `avatar_url` | TEXT | Nullable |
| `skill_notes` | TEXT | Lưu kỹ năng thành viên |
| `created_at` | TIMESTAMPTZ | Default: NOW() |
| `updated_at` | TIMESTAMPTZ | Default: NOW() |

#### 2. `projects`
| Column | Type | Notes |
|--------|------|-------|
| `project_id` | UUID PK | |
| `name` | VARCHAR(255) NOT NULL | |
| `description` | TEXT | |
| `start_date` | DATE | |
| `end_date` | DATE | Overall deadline |
| `status` | VARCHAR(50) | Planning, InProgress, Completed, Cancelled |
| `owner_id` | UUID FK → users | |
| `progress_percentage` | INTEGER | Default: 0, tính từ % task Done |
| `created_at` / `updated_at` | TIMESTAMPTZ | Trigger auto-update |

#### 3. `project_members`
| Column | Type | Notes |
|--------|------|-------|
| `project_member_id` | UUID PK | |
| `project_id` | UUID FK → projects (CASCADE) | |
| `user_id` | UUID FK → users (CASCADE) | |
| `role_in_project` | VARCHAR(100) | PM, Developer, Designer, Tester... |
| `workload_capacity` | INTEGER | Default: 100 (= full capacity) |
| `joined_at` | TIMESTAMPTZ | Default: NOW() |
| **UNIQUE** | `(project_id, user_id)` | |

#### 4. `tasks`
| Column | Type | Notes |
|--------|------|-------|
| `task_id` | UUID PK | |
| `project_id` | UUID FK → projects (CASCADE) | |
| `title` | VARCHAR(255) NOT NULL | |
| `description` | TEXT | |
| `status` | VARCHAR(50) | Todo, InProgress, Review, Done |
| `priority` | VARCHAR(20) | Low, Medium, High |
| `estimated_hours` | DECIMAL(5,2) | |
| `actual_hours` | DECIMAL(5,2) | |
| `start_date` | DATE | |
| `due_date` | DATE NOT NULL | |
| `parent_task_id` | UUID FK → tasks (self) | Subtask support |
| `created_at` / `updated_at` | TIMESTAMPTZ | Trigger auto-update |

#### 5. `task_assignments`
| Column | Type | Notes |
|--------|------|-------|
| `assignment_id` | UUID PK | |
| `task_id` | UUID FK → tasks (CASCADE) | |
| `user_id` | UUID FK → users (CASCADE) | |
| `assigned_at` | TIMESTAMPTZ | Default: NOW() |
| `assigned_by` | UUID FK → users | |
| **UNIQUE** | `(task_id, user_id)` | |

#### 6. `risks`
| Column | Type | Notes |
|--------|------|-------|
| `risk_id` | UUID PK | |
| `project_id` | UUID FK → projects (CASCADE) | |
| `title` | VARCHAR(255) NOT NULL | |
| `description` | TEXT | |
| `probability` | VARCHAR(20) NOT NULL | Low, Medium, High |
| `impact` | VARCHAR(20) NOT NULL | Low, Medium, High |
| `risk_score` | INTEGER **GENERATED ALWAYS** | Auto-computed: High+High=9, High+Medium=6, Medium+High=6, else=3 |
| `status` | VARCHAR(50) | Open, Mitigating, Closed |
| `owner_id` | UUID FK → users | |
| `mitigation_plan` | TEXT | |
| `contingency_plan` | TEXT | |
| `detected_at` / `resolved_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | Default: NOW() |

#### 7. `audit_logs`
| Column | Type | Notes |
|--------|------|-------|
| `log_id` | UUID PK | |
| `action` | VARCHAR(100) NOT NULL | create_project, assign_task... |
| `entity_type` | VARCHAR(50) | Project, Task, Risk |
| `entity_id` | UUID | |
| `performed_by` | UUID FK → users | |
| `details` | JSONB | Chi tiết linh hoạt |
| `created_at` | TIMESTAMPTZ | Default: NOW() |

### Indexes
- `idx_projects_owner` ON projects(owner_id)
- `idx_tasks_project` ON tasks(project_id)
- `idx_tasks_due_date` ON tasks(due_date)
- `idx_tasks_status` ON tasks(status)
- `idx_risks_project` ON risks(project_id)
- `idx_risks_score` ON risks(risk_score)
- `idx_audit_logs_entity` ON audit_logs(entity_type, entity_id)

### Triggers
- `update_timestamp()` — BEFORE UPDATE on projects, tasks → tự động cập nhật `updated_at`

### Database Methods (`SupabaseDB` class)

**File:** `app/database/supabase_client.py`

| Category | Method | Purpose |
|----------|--------|---------|
| **CRUD** | `get_users()`, `get_user(id)` | Users |
| | `get_projects()`, `get_project(id)`, `create_project()` | Projects |
| | `get_tasks_by_project(id)`, `create_tasks_batch()`, `update_task_status()` | Tasks |
| | `get_project_members(id)`, `create_project_member()`, `delete_project_member()` | Members |
| | `get_risks_by_project(id)`, `create_risks_batch()`, `update_risk_status()` | Risks |
| **Assign** | `get_task_assignments_by_project(id)`, `create_task_assignments_batch()` | Assignments |
| | `get_task_assignee(task_id)` | **NEW** — Lấy assignee hiện tại của 1 task |
| | `get_task_children(task_id)` | **NEW** — Lấy children trực tiếp của task |
| | `get_all_task_children_recursive(task_id)` | **NEW** — BFS lấy tất cả children đệ quy |
| | `assign_task_with_children(task_id, user_id, assigned_by)` | **NEW** — Gán task + propagate xuống tất cả children |
| **Cache** | `redis_client.delete_pattern(pattern)` | **NEW** — SCAN + DELETE keys matching glob pattern |
| **Metrics** | `get_task_status_summary(id)`, `get_overdue_tasks(id)` | Summary |
| | `get_member_workload(id)`, `get_risk_summary(id)` | Workload & Risks |
| | `calculate_project_progress(id)` | Flat % Done (legacy) |
| **Audit** | `log_audit()`, `get_audit_logs()` | Audit trail |

---

## 🤖 Các Agent

Tất cả agent đều dùng **ChatGoogleGenerativeAI** với model **gemini-2.5-flash**, và được decorate với `@traceable` (LangSmith).

| Agent | File | Temperature | Cache TTL | Mô tả |
|-------|------|-------------|-----------|-------|
| **Task Divider** | `task_divider.py` | 0.2 | 20 min | Gợi ý assignment top-3/task dựa trên kỹ năng & workload (KHÔNG tạo task) |
| **Risk Agent** | `risk_agent.py` | 0.3 | 15 min | Phát hiện rủi ro bằng rule (overdue, workload, progress) + LLM bổ sung |
| **Progress Tracker** | `progress_tracker.py` | 0.3 | No cache | Tính % hoàn thành phân cấp (parent = avg children), cập nhật DB |
| **Reminder** | `reminder_agent.py` | N/A | No cache | Check deadline 4 mốc (7/3/1 ngày + quá hạn), gửi Slack + assignee-aware |

### Chi tiết từng Agent:

#### 1. Task Divider Agent (REFACTORED)
- **Vai trò:** Chỉ **gợi ý assignment**, KHÔNG tạo task, KHÔNG lưu DB
- **Input:** `project_id`, `project_data`, `raw_tasks`
- **Output:** `AgentResponse` với danh sách recommendations (top-3 user/task)
- **Cache key:** `task_divider:{project_id}` (20 min)
- **Cache note:** Cache dùng `project_id` thuần — không hash task content. Nếu LLM fail (rate limit), cache lưu kết quả rỗng. Khi DB có task mới, cache vẫn cũ → cần xóa cache thủ công hoặc đợi TTL.
- **Flow:**
  1. Check cache — nếu hit → return ngay
  2. Nếu miss: load team_members từ DB, load tasks từ DB (fallback), load project data từ DB (fallback)
  3. Build prompt với `TASK_DIVIDER_SYSTEM_PROMPT`
  4. LLM trả về JSON: assigned_tasks (mỗi task có `assigned_to` + `reason`)
  5. Parse JSON, resolve assignee user_id
  6. Trả về recommendations → **PM Review** trong Dashboard trước khi lưu
  7. Cache result 20 phút

#### 2. Risk Agent (REFACTORED)
- **Vai trò:** Phát hiện rủi ro bằng **rule-based + LLM**
- **Input:** `project_id`, `project_data`, `tasks`
- **Output:** `AgentResponse` với danh sách risks (merged rule + LLM)
- **Cache key:** `risk:{project_id}` (15 min)
- **Rule-based detection:**
  - Task overdue (>= 2 overdue → High risk)
  - High workload (>= 5 tasks assigned)
  - Progress thấp (< 20%)
- **Flow:**
  1. Check cache
  2. Load project + tasks từ project_data hoặc DB fallback
  3. Chạy rule-based detection trước
  4. Build prompt với `RISK_SYSTEM_PROMPT` (từ `risk_prompts.py`) + rule results
  5. LLM trả về JSON: risks array (bổ sung, không trùng lặp)
  6. Merge + dedup risks by title
  7. `db.create_risks_batch()` (max 10 risks)
  8. Cache result

#### 3. Progress Tracker Agent (REFACTORED)
- **Vai trò:** Tính tiến độ **phân cấp** từ subtask lên task cha
- **Input:** `project_id`, `user_input`
- **Output:** `AgentResponse` với progress %, phân tích chi tiết
- **Flow:**
  1. Guard: cần valid project_id
  2. Lấy tasks từ DB, build task tree
  3. Tính hierarchical progress: leaf = từ status (Done=100%, InProgress=50%), parent = average children
  4. `db.update_project_progress()`
  5. LLM tạo response phân tích (có context tree structure)
  6. Response bao gồm: overall %, completed leaves, overdue/blocked counts

#### 4. Reminder Agent (REFACTORED)
- **Vai trò:** Nhắc deadline đa mốc, bao gồm tên người được gán
- **Input:** `project_id` (optional — nếu None thì check all active projects)
- **Output:** `AgentResponse` với thông báo tổng kết
- **Deadline thresholds:**
  - `days_left == 7` → 📋 Nhắc sớm
  - `days_left == 3` → ⏰ Sắp đến hạn
  - `days_left == 1` → 🚨 Cảnh báo khẩn
  - `days_left < 0` → ❌ Quá hạn
- **Flow:**
  1. Load project(s)
  2. Với mỗi project, load tasks + task_assignments
  3. Build assignee map (task_id → assignee_name)
  4. Check từng task's due_date, gửi notification theo threshold
  5. Mỗi notification → `notification_tools.send_notification()` (Slack) + log
  6. Push summary log vào Redis list `reminder_logs` (max 100)

---

## 🔄 LangGraph Orchestrator

**File:** `app/graph/orchestrator.py`

### State Definition (`AgentState` — TypedDict)

```python
class AgentState(TypedDict):
    user_input: str                    # Input từ user
    user_id: str                       # User ID
    project_id: Optional[str]          # Project hiện tại
    messages: Annotated[List[dict], merge_messages]  # Lịch sử chat (max 20)
    project_data: Optional[dict]       # Data project từ planner
    tasks: List[dict]                  # Danh sách tasks
    risks: List[dict]                  # Danh sách risks
    next_step: str                     # Node tiếp theo
    needs_human_approval: bool         # Cần phê duyệt?
    approval_response: Optional[str]   # "approved" | "rejected"
    current_phase: str                 # ready | risk_assessment | execution | monitoring
    error: Optional[str]               # Error message
```

### Message Reducer (`merge_messages`)
- Custom reducer để trộn message lists
- Chống duplicate messages (prefix matching)
- Giới hạn `MAX_MESSAGE_HISTORY = 20`

### Nodes (6 nodes)

| Node | Function | Responsibility |
|------|----------|----------------|
| `supervisor` | `supervisor_node()` | Entry point — route dựa trên intent keywords |
| `task_divider` | `task_divider_node()` | Gọi Task Divider Agent (chỉ recommend, không lưu DB) |
| `risk_assessment` | `risk_assessment_node()` | Gọi Risk Agent (rule + LLM), set needs_human_approval |
| `progress_tracker` | `progress_tracker_node()` | Gọi Progress Tracker (hierarchical), update progress |
| `reminder` | `reminder_node()` | Gọi Reminder Agent (7/3/1 ngày + quá hạn), có guard chống re-entry |
| `human_approval` | `human_approval_node()` | Xử lý approval/rejection rủi ro cao |

**Lưu ý:** `planner_node` đã bị **xóa hoàn toàn** khỏi graph. Project/task được tạo thủ công qua UI, không qua AI.

### Routing Logic (Supervisor)

```
SUPERVISOR ROUTING (REFACTORED — đã xóa planner):
├── needs_human_approval & chưa có response → human_approval
├── approval_response == "approved"/"rejected" → human_approval
├── KHÔNG có project_id → END (yêu cầu tạo project từ Dashboard UI)
└── CÓ project_id:
    ├── "update" / "tiến độ" / "progress" → progress_tracker
    ├── "rủi ro" / "risk" / "phân tích" → risk_assessment
    ├── "gợi ý" / "đề xuất" / "assign" / "phân công" → task_divider
    ├── "nhắc" / "remind" / "deadline" / "hạn" → reminder
    └── fallback → END (hướng dẫn user dùng Dashboard UI)
```

### Graph Edges

```
supervisor → [conditional] → task_divider / progress_tracker / risk_assessment / human_approval / END
task_divider → END  (chỉ recommend, không tự động chain)
progress_tracker → reminder → END
risk_assessment → [conditional] → human_approval (nếu rủi ro >= 7) / reminder (nếu an toàn) / END (nếu reject)
human_approval → [conditional] → reminder (approve) / END (reject)
```

**Lưu ý:** `planner → task_divider` edge đã bị xóa. `task_divider → END` (không còn tự động chạy risk assessment sau khi divide).

### Thresholds
- `HIGH_RISK_THRESHOLD = 7` — risk_score >= 7 → cần human approval
- `risk_requires_approval()` — fallback: probability="High" AND impact="High"

### Checkpointer
- `MemorySaver()` — optional, chỉ init khi `config.LANGSMITH_TRACING == True`

### Conditional Edge Functions
- `route_next(state)` — router chính cho supervisor
- `route_after_risk(state)` — sau risk assessment
- `route_after_approval(state)` — sau human approval

### Intent Keywords (`CREATE_INTENT_KEYWORDS`)
Đã **xóa** toàn bộ — project không còn được tạo qua chat.

---

## 🔄 End-to-End Flows

### Flow 1: PM Tạo Project + Task (Human — không AI)
```
Human PM → Dashboard UI (Quản lý Task)
  → Điền form: name, description, start_date, end_date
  → db.create_project() — trực tiếp, KHÔNG LLM
  → Tạo tasks: title, priority, due_date, estimated_hours, parent_task_id
  → db.create_tasks_batch() — trực tiếp
  → Tạo subtask: chọn parent_task_id → task tree
  → Thêm members: chọn user + role → db.create_project_member()
```

### Flow 2: AI Gợi ý Assignment (Task Divider)
```
User: "Gợi ý assignment cho project này"
  → supervisor: detect "gợi ý" / "assign" / "phân công" → "task_divider"
  → task_divider: task_divider_agent()
      → LLM phân tích tasks top-level (parent_task_id IS NULL)
      → LLM phân tích skill_notes + workload từ DB
      → Output: recommendations top-3 user/task (score, reason, workload)
      → Redis cache (20 min)
  → PM Review trong Dashboard subtab "Assignment Review"
      → Approve 1 trong 3 gợi ý (hoặc chọn manual override)
      → db.create_task_assignments_batch() — chỉ lưu khi PM approve
  → END
```

### Flow 3: Theo Dõi Tiến Độ (Hierarchical)
```
User: "Cập nhật tiến độ dự án"
  → supervisor: detect "tiến độ" / "progress" → "progress_tracker"
  → progress_tracker: progress_tracker_agent()
      → db.get_tasks_by_project() → build task tree
      → _calculate_hierarchical_progress():
          leaf task: Done=100%, InProgress=50%, Todo=0%
          parent task: average of children
      → db.update_project_progress(overall%)
      → LLM tạo response với tree context
      → Response: overall %, leaf completed/overdue/blocked counts
  → reminder: reminder_agent()
      → Kiểm tra deadline đa mốc
      → Slack notifications
  → END
```

### Flow 4: Phân Tích Rủi Ro (Rule + LLM)
```
User: "Phân tích rủi ro"
  → supervisor: detect "rủi ro" / "risk" → "risk_assessment"
  → risk_assessment: risk_agent()
      → Step 1: Rule-based detection
          → Task overdue → risk_score=6 hoặc 9
          → High workload (>5 tasks) → risk_score=7
          → Progress thấp (<20%) → risk_score=7
      → Step 2: LLM bổ sung rủi ro (không trùng lặp)
      → Merge + dedup by title
      → db.create_risks_batch() (max 10)
      → Nếu risk_score >= 7: needs_human_approval = True
  → Nếu cần approval:
      → human_approval: Approve/Reject
      → [approved] → reminder → END
      → [rejected] → END
  → Nếu không cần approval: reminder → END
```

### Flow 5: Background Reminder (Job tự động)
```
  → ReminderJob.run_reminder() (mỗi 30 phút, daemon thread)
  → reminder_agent(project_id=None)
      → Load tất cả active projects
      → Với mỗi project, load tasks + task_assignments
      → Build assignee map (task_id → assignee_name)
      → Check due_date vs today:
          7 ngày → 📋 Nhắc sớm
          3 ngày → ⏰ Sắp đến hạn
          1 ngày → 🚨 Gần hạn
          Quá hạn → ❌ Overdue
      → Slack message có: task name, assignee, deadline, days remaining
      → Push log vào Redis reminder_logs
```

### Flow 6: Chat Khi Chưa Có Project
```
User: "Làm gì đó" (không có project_id)
  → supervisor: no project_id, không còn route tới planner
  → END
  → Response: "Vui lòng chọn project ở sidebar Dashboard hoặc tạo project mới từ Dashboard."
```

---

## 👪 Assignment Inheritance (NEW)

Khi gán task cha, toàn bộ children (đệ quy) sẽ tự động được gán cùng user. Tính năng này giúp PM chỉ cần assign 1 lần duy nhất.

### Rules

1. **Parent assign → propagate children:** Khi gán user cho task cha → `assign_task_with_children()` lấy tất cả children đệ quy (BFS) → gán cùng user cho mỗi task → set status `InProgress` nếu đang `Todo`
2. **New subtask → inherit:** Khi tạo subtask mới (qua API `POST /api/tasks/{id}/subtasks` hoặc UI quick form) → kiểm tra parent có assignee không → nếu có, auto-assign luôn
3. **Unassign cha:** Không ảnh hưởng đến children (giữ nguyên assignment hiện tại)

### Key Methods

| Method | Description |
|--------|-------------|
| `db.get_task_children(task_id)` | Lấy children trực tiếp (1 level) |
| `db.get_all_task_children_recursive(task_id)` | BFS lấy tất cả children đệ quy |
| `db.get_task_assignee(task_id)` | Lấy assignment mới nhất của 1 task |
| `db.assign_task_with_children(task_id, user_id, assigned_by)` | Gán task + tất cả children. DELETE cũ, INSERT mới |
| `db.delete_task_assignments(task_id)` | Xóa tất cả assignments của 1 task |

### API Endpoint

```
POST /api/tasks/{task_id}/assign
Body: { "user_id": "uuid", "assigned_by": "uuid", "propagate_to_children": true }
```

- `propagate_to_children: true` (default) → gán task cha + tất cả children
- `propagate_to_children: false` → chỉ gán 1 task, không propagate

---

## 🖥 Frontend (Streamlit)

**File:** `frontend/streamlit_app.py`

### Session State Variables
| Variable | Type | Mục đích |
|----------|------|----------|
| `thread_id` | str | Thread ID cho LangGraph config |
| `selected_user_id` | str | User đang dùng |
| `messages` | list[dict] | Lịch sử chat |
| `current_project_id` | str | Project hiện tại |
| `pending_approval` | dict | Dữ liệu chờ human approval |
| `project_scope` | str | "Theo user" hoặc "Tất cả" |
| `dashboard_snapshot` | dict | Cache dữ liệu dashboard |
| `dashboard_snapshot_project_id` | str | Project ID của snapshot |
| `task_recommendations` | dict | AI recommendations cho assignment review |

### Sidebar
- **User Selector:** Dropdown chọn user từ DB (hoặc fallback text input)
- **Project Scope:** Radio "Theo user" / "Tất cả"
- **Project Selector:** Dropdown dự án, hiển thị `[Tên] [Status] [Progress%] | [ID]`
- **Buttons:** Refresh Project List, Reset Conversation
- **Background Jobs:** Start/Stop Reminder Job, Xem Reminder Logs

### Tab 1: Chat với AI Agent (`💬`)
- Hiển thị messages history
- Human-in-the-loop approval panel (Approve ✅ / Reject ⛔)
- Chat input → `orchestrator.invoke()`
- Xử lý `needs_human_approval` flag

### Tab 2: Dashboard (`📊`) — 6 subtabs

#### Subtabs:
1. **📈 Tổng quan (Overview)**
   - 4 metrics: Tiến độ %, Tổng Task, Chưa hoàn thành, Quá hạn
   - Status summary: Todo / InProgress / Review / Done counts
   - 🌳 **Task Tree** hierarchical display (parent → children nesting)
   - DataTable task list với assignees + parent_task indicator

2. **📋 Quản lý Task**
   - **Tạo Project Form:** name, description, start_date, end_date → manual DB insert
   - **Tạo Task Form:** title, description, priority, due_date, estimated_hours, parent_task_id
   - **Tạo Subtask nhanh:** chọn parent task → form inline
   - **Inline Status Update:** selectbox per task → db.update_task_status()
   - **Delete Task:** nút xóa từng task
   - Hiển thị danh sách tất cả tasks của project

3. **👥 Quản lý Team**
   - Form tạo User mới (name, email, role, skill)
   - **Thêm Member vào Project:** chọn user từ dropdown → db.create_project_member()
   - Danh sách thành viên (có nút xóa)
   - Workload Summary table (member, role, capacity, tasks, hours)

4. **⚠️ Rủi Ro**
   - 4 metrics: Tổng Risks, Open, Mitigating, Avg Score
   - Risk list với color coding (🔴 >=7, 🟠 >=4, 🟢 <4)

5. **✅ Assignment Review** (NEW)
   - **🤖 Gợi ý Assignment** button → gọi AI Task Divider
   - Hiển thị recommendations top-3/task với score và reason
   - **Batch Assignment:** Chọn user dropdown cho từng task chưa gán → 1 nút **💾 Gán tất cả (N tasks)** → 1 DB batch write
   - **Assignment Inheritance:** Khi gán task cha → tự động propagate xuống tất cả children (đệ quy)
   - **Subtask Auto-Assign:** Khi tạo subtask mới, nếu task cha đã có assignee → auto gán luôn
   - Manual assign cho tasks chưa assigned
   - Hiển thị assignments hiện tại dạng table

6. **📊 System Monitoring**
   - Redis Status (🟢/🔴)
   - Cache statistics (`task_divider:*` + `risk:*` + `dashboard:*` + `users:*` keys)
   - Recent Reminder Logs
   - Cache management buttons (Clear All, View Keys, Refresh Metrics)
   - Orchestrator Event Log viewer (filter by event prefix)
   - Audit Timeline

### Dashboard Data Snapshot
`_build_dashboard_snapshot(project_id)` — gọi 10 DB queries **và cache vào Redis 30s**:
1. `get_project()`
2. `get_tasks_by_project()`
3. `get_project_members()`
4. `get_task_assignments_by_project()`
5. `get_task_status_summary()`
6. `get_overdue_tasks()`
7. `get_risks_by_project()`
8. `get_risk_summary()`
9. `get_member_workload()`
10. `get_audit_logs(project_id=project_id, limit=30)`

**Redis cache key:** `dashboard:{project_id}` (TTL 30s) — giảm tải DB khi nhiều users xem cùng project. Clear khi CRUD task/assign qua `redis_client.delete_pattern()`.

**Composite API endpoint:** `/api/projects/{id}/dashboard` — frontend có thể dùng 1 request thay 10+ nếu cần.

---

## 📡 API Endpoints (FastAPI)

**File:** `app/main.py`

### `POST /chat`
- **Request body:** `ChatRequest { user_input, user_id?, project_id? }`
- **Logic:**
  - `_ensure_user()` — auto-tạo user nếu chưa tồn tại
  - `orchestrator.invoke()` với thread config (current_phase="ready")
- **Response:** `{ response, project_id, success }`

### REST API — Project Management (PHASE 2)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/users` | Danh sách users |
| `POST` | `/api/projects` | Tạo project mới (manual, không LLM) |
| `GET` | `/api/projects` | Danh sách projects (filter by owner_id) |
| `GET` | `/api/projects/{id}` | Chi tiết project |
| `PUT` | `/api/projects/{id}` | Cập nhật project |
| `DELETE` | `/api/projects/{id}` | Xóa project |
| `POST` | `/api/projects/{id}/members` | Thêm member vào project |
| `DELETE` | `/api/projects/{id}/members/{uid}` | Xóa member |
| `GET` | `/api/projects/{id}/members` | Danh sách members |
| `GET` | `/api/projects/{id}/workload` | Workload của members |

### REST API — Task Management (PHASE 3)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/projects/{id}/tasks` | Tạo task mới |
| `GET` | `/api/projects/{id}/tasks` | Danh sách tasks (flat) |
| `GET` | `/api/projects/{id}/tasks/tree` | Task tree (hierarchical) |
| `GET` | `/api/tasks/{id}` | Chi tiết task |
| `PUT` | `/api/tasks/{id}` | Cập nhật task |
| `DELETE` | `/api/tasks/{id}` | Xóa task |
| `PUT` | `/api/tasks/{id}/status` | Cập nhật trạng thái task |
| `POST` | `/api/tasks/{id}/subtasks` | Tạo subtask — **auto-inherit assignee** từ task cha nếu có |

### REST API — Composite Dashboard (NEW)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/projects/{id}/dashboard` | **Composite endpoint** — 1 request thay 10+ queries (project + tasks + tree + members + assignments + risks + workload + audit) |

### REST API — Assign with Propagation (NEW)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/tasks/{id}/assign` | Gán task cho user — **mặc định propagate xuống tất cả children** (đệ quy). Body: `AssignTaskRequest { user_id, assigned_by?, propagate_to_children?: true }` |

### REST API — Assignments & Risks (PHASE 3/4b/6)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/projects/{id}/assignments` | Lưu assignments (sau PM approve) |
| `GET` | `/api/projects/{id}/assignments` | Lấy assignments |
| `GET` | `/api/projects/{id}/risks` | Danh sách rủi ro |
| `GET` | `/api/projects/{id}/risks/summary` | Tổng quan rủi ro |
| `GET` | `/api/projects/{id}/progress` | Tiến độ project (progress% + summary + overdue) |

### `POST /start-reminder`
- Start `ReminderJob.start_background(interval_seconds=1800)` (30 phút)
- **Response:** `{ status: "Reminder job started" }`

### `GET /health`
- **Response:** `{ status: "healthy", message: "AI Team Task Agent is running" }`

---

## 🧰 Tools Layer

### Task Tools (`app/tools/task_tools.py`)
| Function | Purpose |
|----------|---------|
| `create_project_tool()` | Tạo project + audit log |
| `create_tasks_batch_tool()` | Batch tạo tasks |
| `update_task_status_tool()` | Update task status |
| `get_project_tasks_tool()` | Fetch tasks |
| `get_project_risks_tool()` | Fetch risks |

### Risk Tools (`app/tools/risk_tools.py` — class `RiskTools`)
| Method | Purpose |
|--------|---------|
| `create_risks()` | Batch tạo risks |
| `get_project_risks()` | Fetch risks |
| `update_risk_status()` | Update risk status |

### Notification Tools (`app/tools/notification_tools.py` — class `NotificationTools`)
| Method | Purpose |
|--------|---------|
| `send_notification()` | Gửi Slack message + Redis log |
| `send_risk_alert()` | Gửi alert nếu risk_score >= 7 |
| `get_recent_notifications()` | Fetch notification history từ Redis |

---

## ⏰ Background Jobs

**File:** `app/jobs/reminder_job.py`

### Class `ReminderJob` (Singleton)
- `run_reminder()` — gọi `reminder_agent()` → push log vào Redis `reminder_logs` (trim 100)
- `start_background(interval_seconds=3600)` — daemon thread dùng `schedule` library
- `stop()` — set `is_running = False`

**UI controls:** Start / Stop từ sidebar Streamlit, interval mặc định 30 phút.

---

## ⚡ Redis Caching

**File:** `app/database/redis_client.py`

### Class `RedisClient` (Singleton via `__new__`)
- **Connection priority:** `REDIS_URL` > `REDIS_HOST` + `REDIS_PORT` + `REDIS_PASSWORD`
- **Graceful degradation:** Nếu Redis unavailable → `self.client = None`, all methods return safe defaults

### Cache Strategy
| Cache Key | TTL | Set by | Purpose |
|-----------|-----|--------|---------|
| `task_divider:{project_id}` | 20 min | Task Divider | Tránh gọi LLM lại cho cùng project |
| `risk:{project_id}` | 15 min | Risk Agent | Tránh phân tích rủi ro lại |
| `dashboard:{project_id}` | 30s | Frontend + Composite API | Cache snapshot dashboard — clear khi CRUD |
| `users:all` | 60s | Frontend sidebar | Danh sách users (ít thay đổi) |
| `reminder_logs` | N/A (list) | Reminder Agent + ReminderJob | Log lịch sử reminder (max 100) |
| `notification_logs` | N/A (list) | NotificationTools | Log lịch sử notification (max 100) |

**Lưu ý:** Cache key `dashboard:{project_id}` tự động bị clear khi CRUD task/assign (qua `redis_client.delete_pattern(f"dashboard:{project_id}")`).

### Methods
| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `set(key, value, expire=3600)` | key, value, expire | bool | JSON-serialized với TTL |
| `get(key)` | key | Any | JSON-deserialized, None nếu miss |
| `delete(key)` | key | bool | Xóa 1 key |
| `delete_pattern(pattern)` | pattern (glob) | int (count) | **NEW** — Dùng SCAN để xóa tất cả keys matching pattern (không block Redis) |
| `clear_cache()` | — | bool | flushall |
| `get_reminder_logs(limit=20)` | limit | list | Lấy logs từ list |

---

## 📝 Logging & Monitoring

**File:** `app/utils/logger.py`

### Structured JSON Logger
- Tất cả log đều là JSON với format: `{ "ts": ISO datetime, "event": event_name, ...fields }`
- `get_logger(name)` — tạo/retrieve named logger
- `log_event(logger, event, level, **fields)` — ghi structured log
- Output: stream + file (`logs/app.log`)

### Helper Functions
- `truncate_text(value, limit=200)` — safe truncation
- `summarize_sequence(items, sample_key, sample_size)` — tạo sample-based summaries
- `summarize_graph_state(state)` — extract key fields từ state cho log
- `read_recent_log_events(limit, event_prefix)` — đọc lại từ file log với bộ lọc

### Audit Logging (`app/utils/helpers.py`)
- `log_audit(action, entity_type, entity_id, performed_by, details)` — ghi vào `audit_logs` table

### Log Events (prefix conventions)
- `supervisor.enter / supervisor.exit / supervisor.route`
- `task_divider.enter / task_divider.llm.response / task_divider.parse.fallback / task_divider.exception`
- `risk.enter / risk.llm.response / risk.rule_based.detected / risk.db.risks_created / risk.cache.hit|save`
- `progress.enter / progress.db.progress_updated / progress.llm.response`
- `reminder.enter / reminder.tasks.loaded / reminder.notification.sent / reminder.exception`
- `api.project.created|updated|deleted / api.task.created|updated|deleted / api.assignments.saved`
- `redis.connect.success|failure / redis.set.success|failure`
- `audit.write.enter|exit|exception`

---

## ⚙ Configuration & Environment

**File:** `config.py`

### Class `Config` (singleton instance: `config`)

| Variable | Default | Mô tả |
|----------|---------|-------|
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `DB_HOST` | — | PostgreSQL host |
| `DB_PORT` | 6543 | PostgreSQL port |
| `DB_NAME` | — | Database name |
| `DB_USER` | — | Database user |
| `DB_PASSWORD` | — | Database password |
| `DB_SSLMODE` | "require" | SSL mode |
| `SUPABASE_URL` | — | (Legacy) |
| `SUPABASE_KEY` | — | (Legacy) |
| `SLACK_BOT_TOKEN` | — | Slack bot token |
| `SLACK_CHANNEL_ID` | — | Slack channel ID |
| `REDIS_HOST` | "localhost" | Redis host |
| `REDIS_PORT` | 6379 | Redis port |
| `REDIS_PASSWORD` | — | Redis password |
| `REDIS_URL` | — | Full Redis URL (ưu tiên cao nhất) |
| `LANGSMITH_API_KEY` | — | LangSmith API key |
| `LANGSMITH_TRACING` | false | Enable/disable tracing |
| `LANGSMITH_PROJECT` | "ai-team-task-agent" | LangSmith project name |
| `ENV` | "development" | Environment |
| `DEBUG` | true | Debug mode |

### Runtime env vars
- `APP_LOG_LEVEL` (default "INFO")
- `APP_LOG_TO_FILE` (default "true")
- `PYTEST_CURRENT_TEST` / `ENV=test` — tắt Slack notifications

---

## 🧪 Testing

**Framework:** pytest với monkeypatch

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `test_none_list_regression.py` | 1 test | Risk agent returns no risks (None-list edge case) |
| `test_risk_agent_context.py` | 1 test | Risk agent uses project context + datetime serialization |
| `test_task_divider_serialization.py` | 1 test | Task divider returns recommendations (no DB writes) |

### Testing Patterns

1. **FakeLLM classes** — mocks `ChatGoogleGenerativeAI` với hardcoded JSON responses
2. **Monkeypatch DB calls** — replace `db.create_tasks_batch()`, `db.get_users()`, etc.
3. **Monkeypatch Redis** — `redis_client.get()` / `redis_client.set()` with no-op
4. **Module stubs** — `langgraph/graph/__init__.py` cung cấp `StateGraph` stub với `invoke()`
5. **Runtime stubbing** — `test_none_list_regression.py` dùng `types.ModuleType` để tạo synthetic modules
6. **Environment control:** tests set `APP_LOG_TO_FILE=false`, `APP_LOG_LEVEL=CRITICAL`

### Test Stubs (langgraph/)
- `langgraph/graph/__init__.py`: `StateGraph` stub với `add_node()`, `add_conditional_edges()`, `compile()` → `App.invoke()`
- `langgraph/checkpoint/memory.py`: `MemorySaver` stub (no-op)

### Chưa có test cho:
- Streamlit frontend (not tested)
- `reminder_agent`
- `ReminderJob`
- DB update operations (`update_task_status`, `update_risk_status`)

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy

### 1. Yêu Cầu Hệ Thống
- Python 3.9+
- Docker & Docker Compose (cho Redis)
- Tài khoản Supabase (PostgreSQL)
- API Keys: Gemini, Slack (tùy chọn), LangSmith (tùy chọn)

### 2. Clone & Setup
```bash
git clone <repo-url>
cd ai-team-task-agent
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 3. Cấu Hình .env
```env
GEMINI_API_KEY=your_key
DB_HOST=your_db_host
DB_PORT=6543
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_password

SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C...

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=yourpassword123
REDIS_URL=redis://:yourpassword123@localhost:6379

LANGSMITH_API_KEY=...    # Optional
LANGSMITH_TRACING=false
```

### 4. Start Redis
```bash
docker-compose up -d
```

### 5. Database Setup
Chạy `supabase/schema.sql` trong SQL Editor của Supabase.

### 6. Run Backend
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# API Docs: http://localhost:8000/docs
```

### 7. Run Frontend
```bash
streamlit run frontend/streamlit_app.py
# UI: http://localhost:8501
```

### 8. Run Tests
```bash
pytest tests/ -v
```

---

## 🔧 Ghi Chú Kỹ Thuật

### Serialization
- `app/utils/serialization.py`: `serialize_for_json()` — chuyển đổi `datetime→ISO`, `UUID→str`, `Decimal→str`, đệ quy qua dict/list/tuple
- Dùng ở: DB queries, Redis cache, LLM prompt building

### Error Handling Patterns
- **Agent-level:** `try/except Exception` → `log_event(level="error")` → `AgentResponse(success=False)`
- **DB:** `_ensure_connection()` → reconnect nếu closed; `conn.rollback()` trên lỗi
- **Redis:** Graceful degradation — nếu Redis offline, trả về safe defaults
- **Graph:** Reminder node guard chống re-entry qua `_visited_nodes`

### Key Design Decisions
- **Lazy imports** trong orchestrator nodes — tránh import-time dependencies nặng
- **Direct PostgreSQL** (psycopg2) thay vì Supabase client — bypass rate limits
- **`normalize_agent_result()`** — xử lý cả dict và Pydantic model output
- **`serialize_for_json()`** — dùng ở DB layer thay vì model layer
- **Test stubs** trong `langgraph/` — cho phép chạy test không cần langgraph thật
- **REST API endpoints** cho phép frontend gọi DB trực tiếp không qua LangGraph
- **`FRONTEND/components/chat.py`** và **`dashboard.py`** — đang là placeholder, code chính vẫn trong `streamlit_app.py`

---

## 📈 Trạng Thái Dự Án (6/2026)

- **Branch hiện tại:** `refactor/remove-planner-agent`
- **Kiến trúc mới:** Human tạo project/task thủ công, AI chỉ recommend/analyze/remind
- **Trạng thái:** ✅ Phase 1-8 hoàn thành (xóa planner, phân tích rủi ro 2 lớp, progress phân cấp, reminder 4 mốc)
- **Modified files:** Hầu hết agents, orchestrator, frontend (6 subtabs), main.py (REST API), tests
- **New files:** `app/utils/serialization.py`, `app/prompts/task_divider_prompts.py`, `app/prompts/risk_prompts.py`
- **Deleted files:** `planner_agent.py`, `planner_prompts.py`, `test_chat_flow_routing.py`
- **All 3 tests pass:** test_none_list_regression, test_risk_agent_context, test_task_divider_serialization
- **Hoạt động:** Backend + Frontend + Database + Redis đều kết nối được
- **Cần cải thiện:**
  - Tách `streamlit_app.py` thành components riêng
  - Thêm tests cho progress_tracker, reminder_agent, reminder_job
  - CI/CD pipeline
  - Dockerfile cho toàn bộ app (không chỉ Redis)

---

> *Last updated: 2026-06-02 | Maintained as the central brain document for the AI Team Task Agent project.*
