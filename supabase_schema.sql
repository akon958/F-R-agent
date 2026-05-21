-- FamilyReader Supabase schema
-- 在 Supabase SQL Editor 中执行本文件。

create table if not exists analysis_history (
    id bigserial primary key,
    family_id text,
    created_at timestamp with time zone default now(),
    holdings_summary text,
    family_cash numeric,
    total_position_value numeric,
    cash_ratio numeric,
    stock_ratio numeric,
    max_position_ratio numeric,
    risk_score numeric,
    risk_level text,
    main_risks jsonb,
    missing_data jsonb,
    data_status jsonb,
    pe_pb_status text,
    financial_status text,
    ai_report_summary text,
    full_agent_result jsonb
);

create table if not exists followup_history (
    id bigserial primary key,
    family_id text,
    created_at timestamp with time zone default now(),
    question text,
    answer text,
    related_analysis_id bigint null
);

create table if not exists feedback_history (
    id bigserial primary key,
    family_id text,
    created_at timestamp with time zone default now(),
    feedback_rating text,
    feedback_tags jsonb,
    feedback_text text,
    selected_followup_question text
);

create table if not exists family_profile (
    id bigserial primary key,
    family_id text unique,
    risk_preference text,
    report_style text,
    focus_topics jsonb,
    explanation_level text,
    updated_at timestamp with time zone default now()
);

create index if not exists idx_analysis_history_family_created
    on analysis_history (family_id, created_at desc);

create index if not exists idx_followup_history_family_created
    on followup_history (family_id, created_at desc);

create index if not exists idx_feedback_history_family_created
    on feedback_history (family_id, created_at desc);


-- ─────────────────────────────────────────────────────────────────
-- 第 2 步：字段对齐  （兼容性 ALTER，重复执行不会报错）
-- ─────────────────────────────────────────────────────────────────

-- analysis_history 新增字段
alter table analysis_history add column if not exists run_id        text;
alter table analysis_history add column if not exists watch_tasks   jsonb;
alter table analysis_history add column if not exists industry_conc numeric;
alter table analysis_history add column if not exists data_credit   numeric;

-- ─────────────────────────────────────────────────────────────────
-- 5. family_comments  家庭成员观察记录（含立场/关注点）
-- ─────────────────────────────────────────────────────────────────
create table if not exists family_comments (
    id                  bigserial primary key,
    family_id           text        not null default 'default_family',
    created_at          timestamptz not null default now(),
    -- 新字段（优先）
    member              text,                          -- 我/爸爸/妈妈/其他
    comment_type        text,                          -- 疑问/担心/观察/备注/已讨论
    focus               text,                          -- cash/concentration/valuation/...
    stance              text,                          -- conservative/aggressive/neutral
    content             text,                          -- 具体观察内容
    run_id              text,
    -- 旧字段（兼容保留）
    author_name         text,
    focus_tag           text,
    comment_text        text,
    -- 关联与 AI
    related_analysis_id bigint      references analysis_history(id) on delete set null,
    ai_summary          text
);

-- 若表已存在（比如用了旧建表），用 add column if not exists 补字段
alter table family_comments add column if not exists member              text;
alter table family_comments add column if not exists family_id           text default 'default_family';
alter table family_comments add column if not exists created_at          timestamptz default now();
alter table family_comments add column if not exists comment_type        text;
alter table family_comments add column if not exists focus               text;
alter table family_comments add column if not exists stance              text;
alter table family_comments add column if not exists content             text;
alter table family_comments add column if not exists run_id              text;
alter table family_comments add column if not exists author_name         text;
alter table family_comments add column if not exists focus_tag           text;
alter table family_comments add column if not exists comment_text        text;
alter table family_comments add column if not exists related_analysis_id bigint;
alter table family_comments add column if not exists ai_summary          text;

create index if not exists idx_family_comments_family_time
    on family_comments (family_id, created_at desc);
create index if not exists idx_family_comments_run_id
    on family_comments (run_id);


-- ─────────────────────────────────────────────────────────────────
-- 权限修复（重要）：关闭 RLS + 显式授权 anon / authenticated 角色
-- 本工具没有用户登录系统，全家庭共用 family_id，不需要行级安全。
-- 如果不执行这段 SQL，anon key 无法写入，会出现"云端同步失败"。
-- ─────────────────────────────────────────────────────────────────

alter table if exists analysis_history  disable row level security;
alter table if exists followup_history  disable row level security;
alter table if exists feedback_history  disable row level security;
alter table if exists family_profile    disable row level security;
alter table if exists family_comments   disable row level security;

grant all on table analysis_history  to anon, authenticated;
grant all on table followup_history  to anon, authenticated;
grant all on table feedback_history  to anon, authenticated;
grant all on table family_profile    to anon, authenticated;
grant all on table family_comments   to anon, authenticated;

grant usage, select on sequence analysis_history_id_seq  to anon, authenticated;
grant usage, select on sequence followup_history_id_seq  to anon, authenticated;
grant usage, select on sequence feedback_history_id_seq  to anon, authenticated;
grant usage, select on sequence family_profile_id_seq    to anon, authenticated;
grant usage, select on sequence family_comments_id_seq   to anon, authenticated;
