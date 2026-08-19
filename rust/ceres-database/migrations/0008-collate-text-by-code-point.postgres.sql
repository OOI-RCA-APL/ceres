-- Collate every text column by code point, so an index can serve the sorts Ceres asks for.
--
-- Ceres names `C` when it orders text, so ordering already does not depend on the collation a
-- database was created with. What does depend on it is whether an index can serve those sorts, and
-- whether `LIKE 'prefix%'` can use an ordinary B-tree, which it can only on a `C` collated column.
--
-- There is no PostgreSQL equivalent for SQLite, which compares text by byte already, so this
-- migration is PostgreSQL only.
--
-- Each statement rewrites its table and reindexes it under an ACCESS EXCLUSIVE lock. That is
-- immediate for the small tables and proportional to row count for `messages`, `particles`,
-- `logs`, and `alerts`. A deployment with a large history should expect this migration to take
-- time and to hold those tables closed while it runs.

ALTER TABLE alerts ALTER COLUMN address TYPE TEXT COLLATE "C";
ALTER TABLE alerts ALTER COLUMN level TYPE VARCHAR COLLATE "C";
ALTER TABLE alerts ALTER COLUMN type TYPE TEXT COLLATE "C";

ALTER TABLE group_permissions ALTER COLUMN target_type TYPE VARCHAR COLLATE "C";
ALTER TABLE group_permissions ALTER COLUMN target TYPE TEXT COLLATE "C";
ALTER TABLE group_permissions ALTER COLUMN level TYPE VARCHAR COLLATE "C";

ALTER TABLE groups ALTER COLUMN name TYPE TEXT COLLATE "C";
ALTER TABLE groups ALTER COLUMN description TYPE TEXT COLLATE "C";

ALTER TABLE logs ALTER COLUMN address TYPE TEXT COLLATE "C";
ALTER TABLE logs ALTER COLUMN level TYPE VARCHAR COLLATE "C";
ALTER TABLE logs ALTER COLUMN content TYPE TEXT COLLATE "C";

ALTER TABLE messages ALTER COLUMN address TYPE TEXT COLLATE "C";
ALTER TABLE messages ALTER COLUMN connection TYPE TEXT COLLATE "C";
ALTER TABLE messages ALTER COLUMN direction TYPE VARCHAR COLLATE "C";

ALTER TABLE particles ALTER COLUMN address TYPE TEXT COLLATE "C";
ALTER TABLE particles ALTER COLUMN type TYPE TEXT COLLATE "C";

ALTER TABLE settings ALTER COLUMN name TYPE TEXT COLLATE "C";

ALTER TABLE user_permissions ALTER COLUMN target_type TYPE VARCHAR COLLATE "C";
ALTER TABLE user_permissions ALTER COLUMN target TYPE TEXT COLLATE "C";
ALTER TABLE user_permissions ALTER COLUMN level TYPE VARCHAR COLLATE "C";

ALTER TABLE users ALTER COLUMN username TYPE TEXT COLLATE "C";
ALTER TABLE users ALTER COLUMN email TYPE TEXT COLLATE "C";
ALTER TABLE users ALTER COLUMN password TYPE TEXT COLLATE "C";

ALTER TABLE variables ALTER COLUMN address TYPE TEXT COLLATE "C";
ALTER TABLE variables ALTER COLUMN name TYPE TEXT COLLATE "C";

ALTER TABLE workspaces ALTER COLUMN name TYPE TEXT COLLATE "C";
ALTER TABLE workspaces ALTER COLUMN scope TYPE TEXT COLLATE "C";
