-- Rebuild the permission tables so the target_type check constraints accept 'all'. SQLite
-- cannot alter a check constraint in place.
PRAGMA foreign_keys = OFF;

CREATE TABLE user_permissions_new (
    user_id CHAR(32) NOT NULL,
    target_type VARCHAR NOT NULL,
    target TEXT NOT NULL,
    level VARCHAR NOT NULL,
    CONSTRAINT pk_user_permissions PRIMARY KEY (user_id, target_type, target),
    CONSTRAINT fk_user_permissions__user_id__users__id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_user_permissions__target_type CHECK (target_type IN ('component', 'tag', 'all')),
    CONSTRAINT ck_user_permissions__level CHECK (level IN ('view', 'operate', 'manage'))
);

INSERT INTO user_permissions_new (user_id, target_type, target, level)
    SELECT user_id, target_type, target, level FROM user_permissions;

DROP TABLE user_permissions;
ALTER TABLE user_permissions_new RENAME TO user_permissions;

CREATE TABLE group_permissions_new (
    group_id CHAR(32) NOT NULL,
    target_type VARCHAR NOT NULL,
    target TEXT NOT NULL,
    level VARCHAR NOT NULL,
    CONSTRAINT pk_group_permissions PRIMARY KEY (group_id, target_type, target),
    CONSTRAINT fk_group_permissions__group_id__groups__id FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_group_permissions__target_type CHECK (target_type IN ('component', 'tag', 'all')),
    CONSTRAINT ck_group_permissions__level CHECK (level IN ('view', 'operate', 'manage'))
);

INSERT INTO group_permissions_new (group_id, target_type, target, level)
    SELECT group_id, target_type, target, level FROM group_permissions;

DROP TABLE group_permissions;
ALTER TABLE group_permissions_new RENAME TO group_permissions;

PRAGMA foreign_keys = ON;

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
