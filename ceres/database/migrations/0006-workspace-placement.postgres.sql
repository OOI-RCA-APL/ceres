UPDATE workspaces SET scope = '~' WHERE scope IS NULL;
ALTER TABLE workspaces ALTER COLUMN scope SET NOT NULL;
ALTER TABLE workspaces ALTER COLUMN scope SET DEFAULT '~';
