-- A particle now records the connection whose messages produced it, the way a message
-- already does. The table is rebuilt rather than altered so the column sits beside the
-- others that identify a record, matching `messages`. PostgreSQL orders columns by their
-- physical position and offers no way to move one.
CREATE TABLE particles_new (
    id UUID NOT NULL,
    address TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    connection TEXT DEFAULT NULL,
    type TEXT NOT NULL,
    data JSON NOT NULL,
    CONSTRAINT pk_particles_new PRIMARY KEY (id)
);

-- Every existing particle predates the column, so its origin is unknown rather than absent.
INSERT INTO particles_new (id, address, timestamp, connection, type, data)
    SELECT id, address, timestamp, NULL, type, data FROM particles;

DROP TABLE particles;
ALTER TABLE particles_new RENAME TO particles;
ALTER TABLE particles RENAME CONSTRAINT pk_particles_new TO pk_particles;

CREATE INDEX IF NOT EXISTS ix_particles__address ON particles (address);

CREATE INDEX IF NOT EXISTS ix_particles__timestamp ON particles (timestamp);

CREATE INDEX IF NOT EXISTS ix_particles__type ON particles USING gin (type gin_trgm_ops);
