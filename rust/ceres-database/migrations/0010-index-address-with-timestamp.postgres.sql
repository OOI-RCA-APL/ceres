-- Pair each record table's address index with its timestamp, and pair the field a record view
-- filters beside an address with both.
--
-- A record view filters by address and orders by timestamp, and a single column address index
-- serves only the filter. PostgreSQL keeps no correlation statistics between a filter column and a
-- sort column, so it walks the timestamp index back from the newest row and bets on finding a page
-- of matches quickly. Where a component stopped producing records months ago, that walk crosses
-- every newer row in the table first.
--
-- A trailing timestamp orders the rows only when every column ahead of it is pinned by equality,
-- so a wider index does not subsume a narrower one. `(address, timestamp)` serves a view of one
-- component, and `(address, level, timestamp)` serves that view with a level filter on it, which
-- the first would answer by reading the component's whole history and sorting it.
--
-- `ix_messages__connection` stays, being the only index serving a connection filter that carries
-- no address.
--
-- Each CREATE INDEX holds a SHARE lock, blocking writes to its table while it scans. That is
-- immediate for a small table and proportional to row count for `messages`, `particles`, and
-- `logs`, so a deployment with a large history should expect this migration to take time and to
-- hold those tables closed to writes while it runs. CONCURRENTLY is unavailable here, the runner
-- sending each migration as one batch, which PostgreSQL treats as an implicit transaction.

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
