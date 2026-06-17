-- =============================================
-- AI TEAM TASK AGENT - DATABASE SCHEMA
-- =============================================

-- 1. Users Table
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(50) DEFAULT 'member', -- leader, member
    avatar_url TEXT,
    skill_notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Projects Table
CREATE TABLE projects (
    project_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    start_date DATE,
    end_date DATE,                    -- Overall deadline
    status VARCHAR(50) DEFAULT 'Planning', -- Planning, InProgress, Completed, Cancelled
    owner_id UUID REFERENCES users(user_id),
    progress_percentage INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Project Members (Many-to-Many)
CREATE TABLE project_members (
    project_member_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    role_in_project VARCHAR(100),     -- PM, Developer, Designer, Tester...
    workload_capacity INTEGER DEFAULT 100, -- 100 = full capacity
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(project_id, user_id)
);

-- 4. Tasks Table
CREATE TABLE tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'Todo', -- Todo, InProgress, Review, Done
    priority VARCHAR(20) DEFAULT 'Medium', -- Low, Medium, High
    estimated_hours DECIMAL(5,2),
    actual_hours DECIMAL(5,2),
    start_date DATE,
    due_date DATE NOT NULL,
    parent_task_id UUID REFERENCES tasks(task_id), -- Support subtask
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. Task Assignments
CREATE TABLE task_assignments (
    assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES tasks(task_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    assigned_by UUID REFERENCES users(user_id),
    UNIQUE(task_id, user_id)
);

-- 6. Risks Table (Risk Register)
CREATE TABLE risks (
    risk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    probability VARCHAR(20) NOT NULL,     -- Low, Medium, High
    impact VARCHAR(20) NOT NULL,          -- Low, Medium, High
    risk_score INTEGER GENERATED ALWAYS AS (
        CASE 
            WHEN probability = 'High' AND impact = 'High' THEN 9
            WHEN probability = 'High' AND impact = 'Medium' THEN 6
            WHEN probability = 'Medium' AND impact = 'High' THEN 6
            -- ... (có thể tinh chỉnh sau)
            ELSE 3
        END
    ) STORED,
    status VARCHAR(50) DEFAULT 'Open',    -- Open, Mitigating, Closed
    owner_id UUID REFERENCES users(user_id),
    mitigation_plan TEXT,
    contingency_plan TEXT,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 7. Audit Logs (Harness Engineering)
CREATE TABLE audit_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action VARCHAR(100) NOT NULL,         -- create_project, assign_task, update_status, etc.
    entity_type VARCHAR(50),              -- Project, Task, Risk
    entity_id UUID,
    performed_by UUID REFERENCES users(user_id),
    details JSONB,                        -- Chi tiết linh hoạt
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- INDEXES (Tăng tốc query)
-- =============================================
CREATE INDEX idx_projects_owner ON projects(owner_id);
CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_tasks_due_date ON tasks(due_date);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_risks_project ON risks(project_id);
CREATE INDEX idx_risks_score ON risks(risk_score);
CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_type, entity_id);

-- =============================================
-- TRIGGERS (Tự động cập nhật)
-- =============================================
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Áp dụng trigger cho các bảng chính
CREATE TRIGGER update_projects_timestamp 
BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER update_tasks_timestamp 
BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION update_timestamp();