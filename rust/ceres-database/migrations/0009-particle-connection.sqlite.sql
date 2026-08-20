-- A particle now records the connection whose messages produced it, the way a message
-- already does. The table is rebuilt rather than altered so the column sits beside the
-- others that identify a record, matching `messages`, which SQLite cannot do in place.
CREATE TABLE particles_new (
    id CHAR(32) NOT NULL,
    address TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    connection TEXT DEFAULT NULL,
    type TEXT NOT NULL,
    data JSON NOT NULL,
    CONSTRAINT pk_particles PRIMARY KEY (id)
);

-- Every existing particle predates the column, so its origin is unknown rather than absent.
INSERT INTO particles_new (id, address, timestamp, connection, type, data)
    SELECT id, address, timestamp, NULL, type, data FROM particles;

DROP TABLE particles;
ALTER TABLE particles_new RENAME TO particles;

CREATE INDEX IF NOT EXISTS ix_particles__address ON particles (address);

CREATE INDEX IF NOT EXISTS ix_particles__timestamp ON particles (timestamp);

CREATE INDEX IF NOT EXISTS ix_particles__type ON particles (type);
