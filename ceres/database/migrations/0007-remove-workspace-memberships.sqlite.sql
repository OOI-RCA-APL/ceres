DROP TABLE IF EXISTS workspace_memberships;

-- SQLite refuses to drop a column referenced by a CHECK constraint, so rebuild the table without
-- the general access columns and their constraints instead. Foreign keys are disabled across the
-- rebuild so dropping the old table does not cascade into workspace_edits, which references it.
PRAGMA foreign_keys = OFF;

CREATE TABLE workspaces_new (
    id CHAR(32) NOT NULL,
    name TEXT NOT NULL,
    scope TEXT DEFAULT '~' NOT NULL,
    owner_id CHAR(32) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE,
    show_when_logged_out BOOLEAN DEFAULT 0 NOT NULL,
    data JSON DEFAULT '{}' NOT NULL,
    CONSTRAINT pk_workspaces PRIMARY KEY (id)
);

INSERT INTO workspaces_new (id, name, scope, owner_id, show_when_logged_out, data)
    SELECT id, name, scope, owner_id, show_when_logged_out, data FROM workspaces;

DROP TABLE workspaces;
ALTER TABLE workspaces_new RENAME TO workspaces;

PRAGMA foreign_keys = ON;
