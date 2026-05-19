-- Family Investment Agent Supabase schema
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
