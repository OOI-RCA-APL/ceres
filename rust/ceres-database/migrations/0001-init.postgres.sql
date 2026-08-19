-- Frozen baseline schema for PostgreSQL, as it existed when the migrations mechanism was
-- introduced. `IF NOT EXISTS` makes this a no-op on databases that predate the mechanism.
-- Includes the `pg_trgm` extension and `ceres_tokenize_bytes` function the trigram indexes
-- depend on.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION ceres_tokenize_bytes(bytes bytea) RETURNS TEXT
IMMUTABLE
LANGUAGE plpgsql AS $$
    BEGIN
        RETURN regexp_replace(encode($1, 'hex'), '(.{2})', '\1 ', 'g');
    END;
$$;

CREATE TABLE IF NOT EXISTS messages (
    id UUID NOT NULL,
    address TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    connection TEXT DEFAULT NULL,
    direction VARCHAR NOT NULL,
    data BYTEA NOT NULL,
    CONSTRAINT pk_messages PRIMARY KEY (id),
    CONSTRAINT ck_messages__direction CHECK (direction IN ('send', 'receive'))
);

CREATE INDEX IF NOT EXISTS ix_messages__address ON messages (address);

CREATE INDEX IF NOT EXISTS ix_messages__connection ON messages (connection);

CREATE INDEX IF NOT EXISTS ix_messages__data ON messages USING gin (ceres_tokenize_bytes(data) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_messages__timestamp ON messages (timestamp);

CREATE TABLE IF NOT EXISTS particles (
    id UUID NOT NULL,
    address TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    type TEXT NOT NULL,
    data JSON NOT NULL,
    CONSTRAINT pk_particles PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_particles__address ON particles (address);

CREATE INDEX IF NOT EXISTS ix_particles__timestamp ON particles (timestamp);

CREATE INDEX IF NOT EXISTS ix_particles__type ON particles USING gin (type gin_trgm_ops);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID NOT NULL,
    address TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    level VARCHAR NOT NULL,
    type TEXT NOT NULL,
    data JSON DEFAULT '{}' NOT NULL,
    CONSTRAINT pk_alerts PRIMARY KEY (id),
    CONSTRAINT ck_alerts__level CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical'))
);

CREATE INDEX IF NOT EXISTS ix_alerts__address ON alerts (address);

CREATE INDEX IF NOT EXISTS ix_alerts__timestamp ON alerts (timestamp);

CREATE INDEX IF NOT EXISTS ix_alerts__type ON alerts USING gin (type gin_trgm_ops);

CREATE TABLE IF NOT EXISTS logs (
    id UUID NOT NULL,
    address TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    level VARCHAR NOT NULL,
    content TEXT NOT NULL,
    CONSTRAINT pk_logs PRIMARY KEY (id),
    CONSTRAINT ck_logs__level CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical'))
);

CREATE INDEX IF NOT EXISTS ix_logs__address ON logs (address);

CREATE INDEX IF NOT EXISTS ix_logs__content ON logs USING gin (content gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_logs__timestamp ON logs (timestamp);

CREATE TABLE IF NOT EXISTS users (
    id UUID NOT NULL,
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    password TEXT NOT NULL,
    role VARCHAR DEFAULT 'operator' NOT NULL,
    disabled BOOLEAN DEFAULT false NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT uq_users__username UNIQUE (username),
    CONSTRAINT ck_users__role CHECK (role IN ('viewer', 'operator', 'admin'))
);

CREATE TABLE IF NOT EXISTS settings (
    user_id UUID NOT NULL,
    name TEXT NOT NULL,
    value JSON NOT NULL,
    CONSTRAINT pk_settings PRIMARY KEY (user_id, name),
    CONSTRAINT fk_settings__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS variables (
    address TEXT NOT NULL,
    name TEXT NOT NULL,
    value JSON NOT NULL,
    CONSTRAINT pk_variables PRIMARY KEY (address, name)
);

CREATE INDEX IF NOT EXISTS ix_variables__address ON variables (address);

CREATE TABLE IF NOT EXISTS workspaces (
    id UUID NOT NULL,
    name TEXT NOT NULL,
    general_viewership VARCHAR DEFAULT 'private' NOT NULL,
    general_editorship VARCHAR DEFAULT 'private' NOT NULL,
    general_managership VARCHAR DEFAULT 'private' NOT NULL,
    data JSON DEFAULT '{}' NOT NULL,
    CONSTRAINT pk_workspaces PRIMARY KEY (id),
    CONSTRAINT ck_workspaces__general_viewership CHECK (general_viewership IN ('anyone', 'private')),
    CONSTRAINT ck_workspaces__general_editorship CHECK (general_editorship IN ('anyone', 'private')),
    CONSTRAINT ck_workspaces__general_managership CHECK (general_managership IN ('anyone', 'private'))
);

CREATE TABLE IF NOT EXISTS workspace_memberships (
    user_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    role VARCHAR NOT NULL,
    CONSTRAINT pk_workspace_memberships PRIMARY KEY (user_id, workspace_id),
    CONSTRAINT fk_workspace_memberships__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_workspace_memberships__workspace_id__workspaces__id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_workspace_memberships__role CHECK (role IN ('viewer', 'editor', 'manager'))
);

CREATE TABLE IF NOT EXISTS workspace_edits (
    user_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    data JSON NOT NULL,
    CONSTRAINT pk_workspace_edits PRIMARY KEY (workspace_id, user_id),
    CONSTRAINT fk_workspace_edits__workspace_id__workspaces__id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_workspace_edits__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS groups (
    id UUID NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '' NOT NULL,
    CONSTRAINT pk_groups PRIMARY KEY (id),
    CONSTRAINT uq_groups__name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS group_memberships (
    user_id UUID NOT NULL,
    group_id UUID NOT NULL,
    CONSTRAINT pk_group_memberships PRIMARY KEY (user_id, group_id),
    CONSTRAINT fk_group_memberships__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_group_memberships__group_id__groups__id FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id UUID NOT NULL,
    target_type VARCHAR NOT NULL,
    target TEXT NOT NULL,
    level VARCHAR NOT NULL,
    CONSTRAINT pk_user_permissions PRIMARY KEY (user_id, target_type, target),
    CONSTRAINT fk_user_permissions__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_user_permissions__target_type CHECK (target_type IN ('component', 'tag')),
    CONSTRAINT ck_user_permissions__level CHECK (level IN ('view', 'operate', 'manage'))
);

CREATE TABLE IF NOT EXISTS group_permissions (
    group_id UUID NOT NULL,
    target_type VARCHAR NOT NULL,
    target TEXT NOT NULL,
    level VARCHAR NOT NULL,
    CONSTRAINT pk_group_permissions PRIMARY KEY (group_id, target_type, target),
    CONSTRAINT fk_group_permissions__group_id__groups__id FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_group_permissions__target_type CHECK (target_type IN ('component', 'tag')),
    CONSTRAINT ck_group_permissions__level CHECK (level IN ('view', 'operate', 'manage'))
);
