-- =============================================================
-- schema.sql — SEED / DEMO DATA ONLY
-- This file is a hypothetical relational schema for vibe-harness.
-- Vibe-Harness itself uses JSON files (kanban.json), not SQL.
-- This file exists solely for the DB Schema view screenshot.
-- =============================================================

-- Projects: one row per registered kanban board
CREATE TABLE projects (
    id          INTEGER     PRIMARY KEY AUTOINCREMENT,
    key         VARCHAR(64) NOT NULL UNIQUE,
    name        VARCHAR(128) NOT NULL,
    kanban_dir  TEXT        NOT NULL,
    git_remote  VARCHAR(255),
    created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_projects_key ON projects (key);

-- Tasks: the core entity — one row per kanban card
CREATE TABLE tasks (
    id            INTEGER      PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER      NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title         VARCHAR(255) NOT NULL,
    description   TEXT         DEFAULT '',
    details       TEXT         DEFAULT '',
    status        VARCHAR(32)  NOT NULL DEFAULT 'todo'
                               CHECK (status IN ('backlog','todo','in_progress','review','done')),
    priority      VARCHAR(16)  NOT NULL DEFAULT 'medium'
                               CHECK (priority IN ('low','medium','high')),
    category      VARCHAR(32)  DEFAULT 'backend',
    phase         VARCHAR(64)  DEFAULT '',
    target_date   DATE,
    started_at    DATETIME,
    completed_at  DATETIME,
    lines_added   INTEGER      NOT NULL DEFAULT 0,
    lines_removed INTEGER      NOT NULL DEFAULT 0,
    tokens_used   INTEGER      NOT NULL DEFAULT 0,
    position      INTEGER      NOT NULL DEFAULT 0,
    created_by    VARCHAR(128) DEFAULT '',
    assigned_to   VARCHAR(128) DEFAULT '',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tasks_project_status   ON tasks (project_id, status);
CREATE INDEX idx_tasks_project_phase    ON tasks (project_id, phase);
CREATE INDEX idx_tasks_completed_at     ON tasks (completed_at);
CREATE INDEX idx_tasks_assigned_to      ON tasks (assigned_to);

-- Task reviews: structured code review findings per task
CREATE TABLE task_reviews (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER  NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    severity    VARCHAR(16) NOT NULL DEFAULT 'medium'
                            CHECK (severity IN ('critical','high','medium','low')),
    body        TEXT     NOT NULL,
    resolved    BOOLEAN  NOT NULL DEFAULT 0,
    resolved_by VARCHAR(128),
    resolved_at DATETIME,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_task_reviews_task_id  ON task_reviews (task_id);
CREATE INDEX idx_task_reviews_resolved ON task_reviews (task_id, resolved);

-- Tags: reusable labels across tasks
CREATE TABLE tags (
    id         INTEGER     PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER     NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       VARCHAR(64) NOT NULL,
    color      VARCHAR(7)  DEFAULT '#58a6ff',
    created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, name)
);

-- Task ↔ Tag join table
CREATE TABLE task_tags (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (task_id, tag_id)
);

CREATE INDEX idx_task_tags_tag_id ON task_tags (tag_id);

-- Archive index: one row per monthly archive file
CREATE TABLE archive_months (
    id          INTEGER    PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER    NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    year_month  CHAR(7)    NOT NULL,               -- e.g. '2026-03'
    task_count  INTEGER    NOT NULL DEFAULT 0,
    file_path   TEXT       NOT NULL,
    archived_at DATETIME   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, year_month)
);

CREATE INDEX idx_archive_months_project ON archive_months (project_id, year_month);

-- Server config: key-value store for runtime settings
CREATE TABLE server_config (
    key        VARCHAR(128) PRIMARY KEY,
    value      TEXT         NOT NULL,
    updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);
