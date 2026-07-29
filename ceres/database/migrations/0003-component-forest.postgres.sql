ALTER TABLE user_permissions DROP CONSTRAINT ck_user_permissions__target_type;
ALTER TABLE user_permissions ADD CONSTRAINT ck_user_permissions__target_type
    CHECK (target_type IN ('component', 'tag', 'all'));

ALTER TABLE group_permissions DROP CONSTRAINT ck_group_permissions__target_type;
ALTER TABLE group_permissions ADD CONSTRAINT ck_group_permissions__target_type
    CHECK (target_type IN ('component', 'tag', 'all'));

-- Grants on the removed root component become explicit all-grants. The primary key cannot
-- collide because 'all' was not a valid target type before this migration.
UPDATE user_permissions SET target_type = 'all', target = ''
    WHERE target_type = 'component' AND target = '@';

UPDATE group_permissions SET target_type = 'all', target = ''
    WHERE target_type = 'component' AND target = '@';

-- The root component no longer exists, remove its persisted state (chiefly its enabled flag).
DELETE FROM messages WHERE address = '@';
DELETE FROM particles WHERE address = '@';
DELETE FROM alerts WHERE address = '@';
DELETE FROM logs WHERE address = '@';
DELETE FROM variables WHERE address = '@';
