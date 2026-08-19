DROP TABLE IF EXISTS workspace_memberships;

ALTER TABLE workspaces DROP COLUMN general_viewership;
ALTER TABLE workspaces DROP COLUMN general_editorship;
ALTER TABLE workspaces DROP COLUMN general_managership;
