-- Pair each record table's address index with its timestamp, and pair the field a record view
-- filters beside an address with both. A single column address index serves the filter alone,
-- leaving the ordering to a separate walk back through every newer row.
--
-- A trailing timestamp orders the rows only when every column ahead of it is pinned by equality,
-- so a wider index does not subsume a narrower one. `(address, timestamp)` serves a view of one
-- component, and `(address, level, timestamp)` serves that view with a level filter on it.
--
-- `ix_messages__connection` stays, being the only index serving a connection filter that carries
-- no address. Each build holds the database while it scans, proportional to row count.

CREATE INDEX IF NOT EXISTS ix_messages__address__timestamp ON messages (address, timestamp);
CREATE INDEX IF NOT EXISTS ix_messages__address__connection__timestamp
    ON messages (address, connection, timestamp);
CREATE INDEX IF NOT EXISTS ix_messages__address__direction__timestamp
    ON messages (address, direction, timestamp);
DROP INDEX IF EXISTS ix_messages__address;

CREATE INDEX IF NOT EXISTS ix_particles__address__timestamp ON particles (address, timestamp);
CREATE INDEX IF NOT EXISTS ix_particles__address__connection__timestamp
    ON particles (address, connection, timestamp);
DROP INDEX IF EXISTS ix_particles__address;

CREATE INDEX IF NOT EXISTS ix_alerts__address__timestamp ON alerts (address, timestamp);
DROP INDEX IF EXISTS ix_alerts__address;

CREATE INDEX IF NOT EXISTS ix_logs__address__timestamp ON logs (address, timestamp);
CREATE INDEX IF NOT EXISTS ix_logs__address__level__timestamp
    ON logs (address, level, timestamp);
DROP INDEX IF EXISTS ix_logs__address;
