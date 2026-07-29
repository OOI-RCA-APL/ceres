ALTER TABLE users ADD COLUMN admin BOOLEAN NOT NULL DEFAULT 0;

UPDATE users SET admin = 1 WHERE role = 'admin';

-- SQLite refuses to drop a column referenced by a CHECK constraint, so rebuild the table
-- without the role column and its check constraint instead.
PRAGMA foreign_keys = OFF;

CREATE TABLE users_new (
    id CHAR(32) NOT NULL,
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    password TEXT NOT NULL,
    admin BOOLEAN DEFAULT 0 NOT NULL,
    disabled BOOLEAN DEFAULT 0 NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT uq_users__username UNIQUE (username)
);

INSERT INTO users_new (id, username, email, password, admin, disabled)
    SELECT id, username, email, password, admin, disabled FROM users;

DROP TABLE users;
ALTER TABLE users_new RENAME TO users;

PRAGMA foreign_keys = ON;

-- These statements only matter for databases that predate the baseline snapshot. The
-- baseline's workspaces check constraints already restrict general_* values to 'anyone' and
-- 'private', so on any database bootstrapped from the baseline the narrowing is a no-op.
UPDATE workspaces SET general_viewership = 'private'
    WHERE general_viewership IN ('operators', 'admins');

UPDATE workspaces SET general_editorship = 'private'
    WHERE general_editorship IN ('operators', 'admins');

UPDATE workspaces SET general_managership = 'private'
    WHERE general_managership IN ('operators', 'admins');

-- SQLite refuses to drop a check constraint directly, so rebuild the table with the
-- narrowed constraints instead. Pre-baseline databases still have the wide 'operators' and
-- 'admins' check constraints on these columns even after the data above is narrowed.
PRAGMA foreign_keys = OFF;

CREATE TABLE workspaces_new (
    id CHAR(32) NOT NULL,
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

INSERT INTO workspaces_new (id, name, general_viewership, general_editorship, general_managership, data)
    SELECT id, name, general_viewership, general_editorship, general_managership, data FROM workspaces;

DROP TABLE workspaces;
ALTER TABLE workspaces_new RENAME TO workspaces;

PRAGMA foreign_keys = ON;
