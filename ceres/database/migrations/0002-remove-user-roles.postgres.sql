ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users__role;

ALTER TABLE users ADD COLUMN admin BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE users SET admin = TRUE WHERE role = 'admin';

ALTER TABLE users DROP COLUMN role;

-- These statements only matter for databases that predate the baseline snapshot. The
-- baseline's workspaces check constraints already restrict general_* values to 'anyone' and
-- 'private', so on any database bootstrapped from the baseline this is a no-op.
UPDATE workspaces SET general_viewership = 'private'
    WHERE general_viewership IN ('operators', 'admins');

UPDATE workspaces SET general_editorship = 'private'
    WHERE general_editorship IN ('operators', 'admins');

UPDATE workspaces SET general_managership = 'private'
    WHERE general_managership IN ('operators', 'admins');

ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS ck_workspaces__general_viewership;
ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS ck_workspaces__general_editorship;
ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS ck_workspaces__general_managership;

ALTER TABLE workspaces ADD CONSTRAINT ck_workspaces__general_viewership
    CHECK (general_viewership IN ('anyone', 'private'));
ALTER TABLE workspaces ADD CONSTRAINT ck_workspaces__general_editorship
    CHECK (general_editorship IN ('anyone', 'private'));
ALTER TABLE workspaces ADD CONSTRAINT ck_workspaces__general_managership
    CHECK (general_managership IN ('anyone', 'private'));
