ALTER TABLE workspaces ADD COLUMN owner_id CHAR(32);
ALTER TABLE workspaces ADD CONSTRAINT fk_workspaces__owner_id__users__id
    FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE workspaces ADD COLUMN show_when_logged_out BOOLEAN DEFAULT FALSE NOT NULL;
