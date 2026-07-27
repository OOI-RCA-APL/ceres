-- A null scope used to mean a global workspace. Every workspace is now placed on something,
-- and the engine root is what global becomes.
UPDATE workspaces SET scope = '~' WHERE scope IS NULL;

-- SQLite cannot alter a column's nullability, so rebuild the table with the placement column
-- required instead. Foreign keys are disabled across the rebuild so dropping the old table does
-- not cascade into workspace_memberships and workspace_edits, which both reference it.
PRAGMA foreign_keys = OFF;

CREATE TABLE workspaces_new (
    id CHAR(32) NOT NULL,
    name TEXT NOT NULL,
    scope TEXT DEFAULT '~' NOT NULL,
    owner_id CHAR(32) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE,
    show_when_logged_out BOOLEAN DEFAULT 0 NOT NULL,
    general_viewership VARCHAR DEFAULT 'private' NOT NULL,
    general_editorship VARCHAR DEFAULT 'private' NOT NULL,
    general_managership VARCHAR DEFAULT 'private' NOT NULL,
    data JSON DEFAULT '{}' NOT NULL,
    CONSTRAINT pk_workspaces PRIMARY KEY (id),
    CONSTRAINT ck_workspaces__general_viewership CHECK (general_viewership IN ('anyone', 'private')),
    CONSTRAINT ck_workspaces__general_editorship CHECK (general_editorship IN ('anyone', 'private')),
    CONSTRAINT ck_workspaces__general_managership CHECK (general_managership IN ('anyone', 'private'))
);

INSERT INTO workspaces_new (
    id, name, scope, owner_id, show_when_logged_out,
    general_viewership, general_editorship, general_managership, data
)
    SELECT
        id, name, scope, owner_id, show_when_logged_out,
        general_viewership, general_editorship, general_managership, data
    FROM workspaces;

DROP TABLE workspaces;
ALTER TABLE workspaces_new RENAME TO workspaces;

PRAGMA foreign_keys = ON;
