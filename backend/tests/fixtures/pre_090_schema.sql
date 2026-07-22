CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    last_login_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    created_by INTEGER,
    updated_by INTEGER,
    is_deleted BOOLEAN NOT NULL
);

CREATE TABLE scripts (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    type VARCHAR(10) NOT NULL,
    latest_version INTEGER NOT NULL,
    config_json TEXT,
    status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    created_by INTEGER,
    updated_by INTEGER,
    is_deleted BOOLEAN NOT NULL
);

CREATE TABLE script_versions (
    id INTEGER PRIMARY KEY,
    script_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    changelog TEXT,
    file_path TEXT NOT NULL,
    config_json TEXT,
    created_by INTEGER,
    created_at DATETIME NOT NULL
);

CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    script_id INTEGER NOT NULL,
    script_version INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    params TEXT,
    error_msg TEXT,
    result_files TEXT,
    started_at DATETIME,
    finished_at DATETIME,
    duration_sec INTEGER,
    log_path TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    is_deleted BOOLEAN NOT NULL
);

CREATE TABLE user_scripts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    script_id INTEGER NOT NULL,
    installed_at DATETIME NOT NULL,
    UNIQUE (user_id, script_id)
);

CREATE TABLE environments (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    browser_port INTEGER,
    browser_path VARCHAR(500),
    output_dir VARCHAR(500),
    proxy VARCHAR(200),
    extra_env TEXT,
    is_default BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    username VARCHAR(50),
    action VARCHAR(50) NOT NULL,
    target_type VARCHAR(50),
    target_id INTEGER,
    detail TEXT,
    ip_address VARCHAR(50),
    created_at DATETIME NOT NULL
);

CREATE TABLE issues (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    script_id INTEGER,
    user_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL,
    resolve_note TEXT,
    resolved_by INTEGER,
    resolved_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    is_deleted BOOLEAN NOT NULL
);

INSERT INTO users (
    id, username, password_hash, display_name, role, status,
    created_at, updated_at, is_deleted
) VALUES (
    1, 'existing', 'hash', 'Existing User', 'admin', 'active',
    '2026-07-01 00:00:00', '2026-07-01 00:00:00', 0
);

INSERT INTO scripts (
    id, name, type, latest_version, status, created_at, updated_at, is_deleted
) VALUES (
    1, 'legacy-script', 'py', 1, 'active',
    '2026-07-01 00:00:00', '2026-07-01 00:00:00', 0
);

INSERT INTO script_versions (
    id, script_id, version, file_path, created_at
) VALUES (1, 1, 1, 'scripts/legacy.py', '2026-07-01 00:00:00');

INSERT INTO environments (
    id, user_id, name, is_default, created_at, updated_at
) VALUES (
    1, 1, 'legacy-environment', 1,
    '2026-07-01 00:00:00', '2026-07-01 00:00:00'
);

INSERT INTO runs (
    id, script_id, script_version, user_id, status,
    created_at, updated_at, is_deleted
) VALUES (
    1, 1, 1, 1, 'succeeded',
    '2026-07-01 00:00:00', '2026-07-01 00:00:00', 0
);
