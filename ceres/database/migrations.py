"""Ordered schema migrations applied by `Database.migrate`."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "MIGRATIONS",
    "Migration",
    "migration",
]

type UpgradeFunction = Callable[[AsyncConnection], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class Migration:
    """A single ordered schema migration."""

    id: int
    """Unique sequential identifier."""
    description: str
    """Human-readable summary of what the migration does."""
    upgrade: UpgradeFunction
    """Apply the migration's schema changes on the given connection."""


MIGRATIONS: list[Migration] = []
"""Every known migration, in application order."""


def migration(id: int, description: str) -> Callable[[UpgradeFunction], UpgradeFunction]:
    """Declare a schema migration and register it in `MIGRATIONS`.

    Args:
        id: Unique sequential identifier for the migration.
        description: Human-readable summary of what the migration does.

    Raises:
        ValueError: If a migration with the same `id` is already registered.
    """

    def decorate(upgrade: UpgradeFunction) -> UpgradeFunction:
        if any(current.id == id for current in MIGRATIONS):
            raise ValueError(f"A migration with id {id} is already registered.")

        MIGRATIONS.append(Migration(id=id, description=description, upgrade=upgrade))
        MIGRATIONS.sort(key=lambda current: current.id)
        return upgrade

    return decorate


_INITIAL_SCHEMA_SQLITE: list[str] = [
    "CREATE TABLE IF NOT EXISTS messages (\n    id CHAR(32) NOT NULL, \n    address TEXT NOT NULL, \n    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, \n    connection TEXT DEFAULT NULL, \n    direction VARCHAR NOT NULL, \n    data BLOB NOT NULL, \n    CONSTRAINT pk_messages PRIMARY KEY (id), \n    CONSTRAINT ck_messages__direction CHECK (direction IN ('send', 'receive'))\n);",
    "CREATE INDEX IF NOT EXISTS ix_messages__address ON messages (address);",
    "CREATE INDEX IF NOT EXISTS ix_messages__connection ON messages (connection);",
    "CREATE INDEX IF NOT EXISTS ix_messages__data ON messages (data);",
    "CREATE INDEX IF NOT EXISTS ix_messages__timestamp ON messages (timestamp);",
    "CREATE TABLE IF NOT EXISTS particles (\n    id CHAR(32) NOT NULL, \n    address TEXT NOT NULL, \n    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, \n    type TEXT NOT NULL, \n    data JSON NOT NULL, \n    CONSTRAINT pk_particles PRIMARY KEY (id)\n);",
    "CREATE INDEX IF NOT EXISTS ix_particles__address ON particles (address);",
    "CREATE INDEX IF NOT EXISTS ix_particles__timestamp ON particles (timestamp);",
    "CREATE INDEX IF NOT EXISTS ix_particles__type ON particles (type);",
    "CREATE TABLE IF NOT EXISTS alerts (\n    id CHAR(32) NOT NULL, \n    address TEXT NOT NULL, \n    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, \n    level VARCHAR NOT NULL, \n    type TEXT NOT NULL, \n    data JSON DEFAULT '{}' NOT NULL, \n    CONSTRAINT pk_alerts PRIMARY KEY (id), \n    CONSTRAINT ck_alerts__level CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical'))\n);",
    "CREATE INDEX IF NOT EXISTS ix_alerts__address ON alerts (address);",
    "CREATE INDEX IF NOT EXISTS ix_alerts__timestamp ON alerts (timestamp);",
    "CREATE INDEX IF NOT EXISTS ix_alerts__type ON alerts (type);",
    "CREATE TABLE IF NOT EXISTS logs (\n    id CHAR(32) NOT NULL, \n    address TEXT NOT NULL, \n    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, \n    level VARCHAR NOT NULL, \n    content TEXT NOT NULL, \n    CONSTRAINT pk_logs PRIMARY KEY (id), \n    CONSTRAINT ck_logs__level CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical'))\n);",
    "CREATE INDEX IF NOT EXISTS ix_logs__address ON logs (address);",
    "CREATE INDEX IF NOT EXISTS ix_logs__content ON logs (content);",
    "CREATE INDEX IF NOT EXISTS ix_logs__timestamp ON logs (timestamp);",
    "CREATE TABLE IF NOT EXISTS users (\n    id CHAR(32) NOT NULL, \n    username TEXT NOT NULL, \n    email TEXT NOT NULL, \n    password TEXT NOT NULL, \n    role VARCHAR DEFAULT 'operator' NOT NULL, \n    disabled BOOLEAN DEFAULT 0 NOT NULL, \n    CONSTRAINT pk_users PRIMARY KEY (id), \n    CONSTRAINT uq_users__username UNIQUE (username), \n    CONSTRAINT ck_users__role CHECK (role IN ('viewer', 'operator', 'admin'))\n);",
    "CREATE TABLE IF NOT EXISTS settings (\n    user_id CHAR(32) NOT NULL, \n    name TEXT NOT NULL, \n    value JSON NOT NULL, \n    CONSTRAINT pk_settings PRIMARY KEY (user_id, name), \n    CONSTRAINT fk_settings__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE\n);",
    "CREATE TABLE IF NOT EXISTS variables (\n    address TEXT NOT NULL, \n    name TEXT NOT NULL, \n    value JSON NOT NULL, \n    CONSTRAINT pk_variables PRIMARY KEY (address, name)\n);",
    "CREATE INDEX IF NOT EXISTS ix_variables__address ON variables (address);",
    "CREATE TABLE IF NOT EXISTS workspaces (\n    id CHAR(32) NOT NULL, \n    name TEXT NOT NULL, \n    general_viewership VARCHAR DEFAULT 'private' NOT NULL, \n    general_editorship VARCHAR DEFAULT 'private' NOT NULL, \n    general_managership VARCHAR DEFAULT 'private' NOT NULL, \n    data JSON DEFAULT '{}' NOT NULL, \n    CONSTRAINT pk_workspaces PRIMARY KEY (id), \n    CONSTRAINT ck_workspaces__general_viewership CHECK (general_viewership IN ('anyone', 'private')), \n    CONSTRAINT ck_workspaces__general_editorship CHECK (general_editorship IN ('anyone', 'private')), \n    CONSTRAINT ck_workspaces__general_managership CHECK (general_managership IN ('anyone', 'private'))\n);",
    "CREATE TABLE IF NOT EXISTS workspace_memberships (\n    user_id CHAR(32) NOT NULL, \n    workspace_id CHAR(32) NOT NULL, \n    role VARCHAR NOT NULL, \n    CONSTRAINT pk_workspace_memberships PRIMARY KEY (user_id, workspace_id), \n    CONSTRAINT fk_workspace_memberships__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT fk_workspace_memberships__workspace_id__workspaces__id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT ck_workspace_memberships__role CHECK (role IN ('viewer', 'editor', 'manager'))\n);",
    "CREATE TABLE IF NOT EXISTS workspace_edits (\n    user_id CHAR(32) NOT NULL, \n    workspace_id CHAR(32) NOT NULL, \n    data JSON NOT NULL, \n    CONSTRAINT pk_workspace_edits PRIMARY KEY (workspace_id, user_id), \n    CONSTRAINT fk_workspace_edits__workspace_id__workspaces__id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT fk_workspace_edits__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE\n);",
    "CREATE TABLE IF NOT EXISTS groups (\n    id CHAR(32) NOT NULL, \n    name TEXT NOT NULL, \n    description TEXT DEFAULT '' NOT NULL, \n    CONSTRAINT pk_groups PRIMARY KEY (id), \n    CONSTRAINT uq_groups__name UNIQUE (name)\n);",
    "CREATE TABLE IF NOT EXISTS group_memberships (\n    user_id CHAR(32) NOT NULL, \n    group_id CHAR(32) NOT NULL, \n    CONSTRAINT pk_group_memberships PRIMARY KEY (user_id, group_id), \n    CONSTRAINT fk_group_memberships__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT fk_group_memberships__group_id__groups__id FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE ON UPDATE CASCADE\n);",
    "CREATE TABLE IF NOT EXISTS user_permissions (\n    user_id CHAR(32) NOT NULL, \n    target_type VARCHAR NOT NULL, \n    target TEXT NOT NULL, \n    level VARCHAR NOT NULL, \n    CONSTRAINT pk_user_permissions PRIMARY KEY (user_id, target_type, target), \n    CONSTRAINT fk_user_permissions__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT ck_user_permissions__target_type CHECK (target_type IN ('component', 'tag')), \n    CONSTRAINT ck_user_permissions__level CHECK (level IN ('deny', 'view', 'operate', 'manage')), \n    CONSTRAINT ck_user_permissions__level_no_deny CHECK (level IN ('view', 'operate', 'manage'))\n);",
    "CREATE TABLE IF NOT EXISTS group_permissions (\n    group_id CHAR(32) NOT NULL, \n    target_type VARCHAR NOT NULL, \n    target TEXT NOT NULL, \n    level VARCHAR NOT NULL, \n    CONSTRAINT pk_group_permissions PRIMARY KEY (group_id, target_type, target), \n    CONSTRAINT fk_group_permissions__group_id__groups__id FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT ck_group_permissions__target_type CHECK (target_type IN ('component', 'tag')), \n    CONSTRAINT ck_group_permissions__level CHECK (level IN ('deny', 'view', 'operate', 'manage')), \n    CONSTRAINT ck_group_permissions__level_no_deny CHECK (level IN ('view', 'operate', 'manage'))\n);",
]
"""Literal `CREATE TABLE`/`CREATE INDEX` statements for the schema as it existed when the
migrations mechanism was introduced, compiled for SQLite."""

_INITIAL_SCHEMA_POSTGRES: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
    "CREATE OR REPLACE FUNCTION ceres_tokenize_bytes(bytes bytea) RETURNS TEXT\nIMMUTABLE\nLANGUAGE plpgsql AS $$\n    BEGIN\n        RETURN regexp_replace(encode($1, 'hex'), '(.{2})', '\\1 ', 'g');\n    END;\n$$;",
    "CREATE TABLE IF NOT EXISTS messages (\n    id UUID NOT NULL, \n    address TEXT NOT NULL, \n    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n    connection TEXT DEFAULT NULL, \n    direction VARCHAR NOT NULL, \n    data BYTEA NOT NULL, \n    CONSTRAINT pk_messages PRIMARY KEY (id), \n    CONSTRAINT ck_messages__direction CHECK (direction IN ('send', 'receive'))\n);",
    "CREATE INDEX IF NOT EXISTS ix_messages__address ON messages (address);",
    "CREATE INDEX IF NOT EXISTS ix_messages__connection ON messages (connection);",
    "CREATE INDEX IF NOT EXISTS ix_messages__data ON messages USING gin (ceres_tokenize_bytes(data) gin_trgm_ops);",
    "CREATE INDEX IF NOT EXISTS ix_messages__timestamp ON messages (timestamp);",
    "CREATE TABLE IF NOT EXISTS particles (\n    id UUID NOT NULL, \n    address TEXT NOT NULL, \n    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n    type TEXT NOT NULL, \n    data JSON NOT NULL, \n    CONSTRAINT pk_particles PRIMARY KEY (id)\n);",
    "CREATE INDEX IF NOT EXISTS ix_particles__address ON particles (address);",
    "CREATE INDEX IF NOT EXISTS ix_particles__timestamp ON particles (timestamp);",
    "CREATE INDEX IF NOT EXISTS ix_particles__type ON particles USING gin (type gin_trgm_ops);",
    "CREATE TABLE IF NOT EXISTS alerts (\n    id UUID NOT NULL, \n    address TEXT NOT NULL, \n    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n    level VARCHAR NOT NULL, \n    type TEXT NOT NULL, \n    data JSON DEFAULT '{}' NOT NULL, \n    CONSTRAINT pk_alerts PRIMARY KEY (id), \n    CONSTRAINT ck_alerts__level CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical'))\n);",
    "CREATE INDEX IF NOT EXISTS ix_alerts__address ON alerts (address);",
    "CREATE INDEX IF NOT EXISTS ix_alerts__timestamp ON alerts (timestamp);",
    "CREATE INDEX IF NOT EXISTS ix_alerts__type ON alerts USING gin (type gin_trgm_ops);",
    "CREATE TABLE IF NOT EXISTS logs (\n    id UUID NOT NULL, \n    address TEXT NOT NULL, \n    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n    level VARCHAR NOT NULL, \n    content TEXT NOT NULL, \n    CONSTRAINT pk_logs PRIMARY KEY (id), \n    CONSTRAINT ck_logs__level CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical'))\n);",
    "CREATE INDEX IF NOT EXISTS ix_logs__address ON logs (address);",
    "CREATE INDEX IF NOT EXISTS ix_logs__content ON logs USING gin (content gin_trgm_ops);",
    "CREATE INDEX IF NOT EXISTS ix_logs__timestamp ON logs (timestamp);",
    "CREATE TABLE IF NOT EXISTS users (\n    id UUID NOT NULL, \n    username TEXT NOT NULL, \n    email TEXT NOT NULL, \n    password TEXT NOT NULL, \n    role VARCHAR DEFAULT 'operator' NOT NULL, \n    disabled BOOLEAN DEFAULT false NOT NULL, \n    CONSTRAINT pk_users PRIMARY KEY (id), \n    CONSTRAINT uq_users__username UNIQUE (username), \n    CONSTRAINT ck_users__role CHECK (role IN ('viewer', 'operator', 'admin'))\n);",
    "CREATE TABLE IF NOT EXISTS settings (\n    user_id UUID NOT NULL, \n    name TEXT NOT NULL, \n    value JSON NOT NULL, \n    CONSTRAINT pk_settings PRIMARY KEY (user_id, name), \n    CONSTRAINT fk_settings__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE\n);",
    "CREATE TABLE IF NOT EXISTS variables (\n    address TEXT NOT NULL, \n    name TEXT NOT NULL, \n    value JSON NOT NULL, \n    CONSTRAINT pk_variables PRIMARY KEY (address, name)\n);",
    "CREATE INDEX IF NOT EXISTS ix_variables__address ON variables (address);",
    "CREATE TABLE IF NOT EXISTS workspaces (\n    id UUID NOT NULL, \n    name TEXT NOT NULL, \n    general_viewership VARCHAR DEFAULT 'private' NOT NULL, \n    general_editorship VARCHAR DEFAULT 'private' NOT NULL, \n    general_managership VARCHAR DEFAULT 'private' NOT NULL, \n    data JSON DEFAULT '{}' NOT NULL, \n    CONSTRAINT pk_workspaces PRIMARY KEY (id), \n    CONSTRAINT ck_workspaces__general_viewership CHECK (general_viewership IN ('anyone', 'private')), \n    CONSTRAINT ck_workspaces__general_editorship CHECK (general_editorship IN ('anyone', 'private')), \n    CONSTRAINT ck_workspaces__general_managership CHECK (general_managership IN ('anyone', 'private'))\n);",
    "CREATE TABLE IF NOT EXISTS workspace_memberships (\n    user_id UUID NOT NULL, \n    workspace_id UUID NOT NULL, \n    role VARCHAR NOT NULL, \n    CONSTRAINT pk_workspace_memberships PRIMARY KEY (user_id, workspace_id), \n    CONSTRAINT fk_workspace_memberships__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT fk_workspace_memberships__workspace_id__workspaces__id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT ck_workspace_memberships__role CHECK (role IN ('viewer', 'editor', 'manager'))\n);",
    "CREATE TABLE IF NOT EXISTS workspace_edits (\n    user_id UUID NOT NULL, \n    workspace_id UUID NOT NULL, \n    data JSON NOT NULL, \n    CONSTRAINT pk_workspace_edits PRIMARY KEY (workspace_id, user_id), \n    CONSTRAINT fk_workspace_edits__workspace_id__workspaces__id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT fk_workspace_edits__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE\n);",
    "CREATE TABLE IF NOT EXISTS groups (\n    id UUID NOT NULL, \n    name TEXT NOT NULL, \n    description TEXT DEFAULT '' NOT NULL, \n    CONSTRAINT pk_groups PRIMARY KEY (id), \n    CONSTRAINT uq_groups__name UNIQUE (name)\n);",
    "CREATE TABLE IF NOT EXISTS group_memberships (\n    user_id UUID NOT NULL, \n    group_id UUID NOT NULL, \n    CONSTRAINT pk_group_memberships PRIMARY KEY (user_id, group_id), \n    CONSTRAINT fk_group_memberships__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT fk_group_memberships__group_id__groups__id FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE ON UPDATE CASCADE\n);",
    "CREATE TABLE IF NOT EXISTS user_permissions (\n    user_id UUID NOT NULL, \n    target_type VARCHAR NOT NULL, \n    target TEXT NOT NULL, \n    level VARCHAR NOT NULL, \n    CONSTRAINT pk_user_permissions PRIMARY KEY (user_id, target_type, target), \n    CONSTRAINT fk_user_permissions__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT ck_user_permissions__target_type CHECK (target_type IN ('component', 'tag')), \n    CONSTRAINT ck_user_permissions__level CHECK (level IN ('deny', 'view', 'operate', 'manage')), \n    CONSTRAINT ck_user_permissions__level_no_deny CHECK (level IN ('view', 'operate', 'manage'))\n);",
    "CREATE TABLE IF NOT EXISTS group_permissions (\n    group_id UUID NOT NULL, \n    target_type VARCHAR NOT NULL, \n    target TEXT NOT NULL, \n    level VARCHAR NOT NULL, \n    CONSTRAINT pk_group_permissions PRIMARY KEY (group_id, target_type, target), \n    CONSTRAINT fk_group_permissions__group_id__groups__id FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE ON UPDATE CASCADE, \n    CONSTRAINT ck_group_permissions__target_type CHECK (target_type IN ('component', 'tag')), \n    CONSTRAINT ck_group_permissions__level CHECK (level IN ('deny', 'view', 'operate', 'manage')), \n    CONSTRAINT ck_group_permissions__level_no_deny CHECK (level IN ('view', 'operate', 'manage'))\n);",
]
"""Literal `CREATE TABLE`/`CREATE INDEX` statements for the schema as it existed when the
migrations mechanism was introduced, compiled for PostgreSQL, including the `pg_trgm` extension
and `ceres_tokenize_bytes` function the trigram indexes depend on."""


@migration(1, "Create initial schema")
async def create_initial_schema(connection: AsyncConnection) -> None:
    """Create every table and index of the original ceres schema.

    This is a frozen snapshot of the schema as it existed when the migrations mechanism was
    introduced. `IF NOT EXISTS` makes it a no-op on databases that predate the mechanism.
    """
    statements = (
        _INITIAL_SCHEMA_POSTGRES
        if connection.dialect.name == "postgresql"
        else _INITIAL_SCHEMA_SQLITE
    )
    for statement in statements:
        await connection.execute(text(statement))
