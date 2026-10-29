# Exporters

An exporter writes a component's records to files, one file per period of time. The files are the
archive and the product of a deployment. The database is the working copy: a pruner may clear old
rows from it, and the files keep them.

Ceres never removes a record from a file on its own. A scheduled run or a manual re-run merges the
database into each file, so a row the database lost stays in the file and a row the database holds
replaces the file's copy. Only a run that asks to replace rewrites a file from the database alone.

## Configuring An Exporter

Exporters belong to a component in `ceres.yaml`. Each one names the records it writes, the format,
and the period one file covers. The files go to one of the component's mounts.

```yaml
components:
  - name: sensor
    class: my_project.SensorDriver
    arguments:
      output:
        path: /data/sensor
        layout: "{yyyy}/{MM}/{dd}"
    exporters:
      - name: messages
        exports: message
        format: csv
        period: hour
        schedule: "5 * * * *"
```

This exporter writes the sensor's messages to `/data/sensor/2026/01/01/messages_20260101T00.csv`
and one file for each later hour. It writes each message within a few seconds of storing it, and five minutes
past every hour it also merges the database into the files of the current hour and the hour before
it.

| Field | Meaning |
|---|---|
| `name` | Exporter name, unique within its component. |
| `exports` | Record kind: `message`, `particle`, `alert` or `log-entry`. |
| `filter` | Records to export, in the kind's filter syntax. Every record of the kind at the component when omitted. |
| `type` | Particle class whose data fields become columns. Particle exporters only, and required for `csv` and `netcdf`. |
| `format` | `csv`, `jsonl`, `netcdf`, `raw`, or a format class with its arguments as `{class, arguments}`. |
| `mount` | Name of the component's mount the files live under, `output` when omitted. |
| `period` | Time one file covers: `hour`, `day`, `month`, or `all` for a single file. |
| `path` | File name of each period, without an extension. A name for the period when omitted. |
| `live` | Whether the exporter writes records as the component stores them. On when omitted, except for `netcdf`. |
| `interval` | Least time between two live writes, 5 seconds when omitted and at least 1 second. |
| `schedule` | Cron or interval expression for scheduled runs. No scheduled runs when omitted. |
| `lookback` | Periods before the current one each scheduled run covers, 1 when omitted. |

A filter selects records and nothing else, so it cannot set `order`, `limit` or `offset`. It also
cannot set `subsample`, `subsample_every`, `subsample_select`, `timespan`, `max_age` or `min_age`,
since a live write and a later run must select the same records. The exporter writes records in
timestamp order, and records with equal timestamps in ID order.

## Paths

The mount must be a writable field the component declares with `Mount.Field`. Each file goes in the
mount's layout folder for its period, the same folder `Mount.file` picks, so the "Files" page finds
it under the day it covers. A `period: all` file sits at the mount's root.

The path is a file name template, as in [File Name Templates](components.md#file-name-templates).
`{exporter}` renders the exporter name, and `{connection}` renders the connection name when the
filter pins exactly one connection. The format adds its extension: `.csv`, `.jsonl`, `.nc` for
`netcdf`, or `.bin` for `raw`. Without a path, the name is the exporter name and the period's start,
`{exporter}_{yyyy}{MM}{dd}T{HH}` for an hour, `{exporter}_{yyyy}{MM}{dd}` for a day,
`{exporter}_{yyyy}{MM}` for a month, and `{exporter}` for all time.

Folder and name render at the period's UTC start, whatever zone the mount names, so a file's name
says which UTC period it holds. On a mount with a `local` zone, a day file can sit in a different
folder from what `Mount.file` picks for the same moment.

A component refuses to start an exporter whose folder and name write two periods to one file, such as
`{yyyy}/{MM}/{dd}` for an hourly exporter on a mount with no layout, or `{yy}` where two centuries
meet. It also refuses a layout that splits folders finer than the period, such as an hour layout
for a day exporter. A `period: all` path takes no time atoms.

## Formats

`csv` writes a header line and one line per record. `jsonl` writes one JSON object per line with the
same fields, in the same order. Both start every line with the record's `timestamp` and `id`.

| Records | Columns |
|---|---|
| `message` | `timestamp`, `id`, `address`, `connection`, `direction`, `data` |
| `particle` | `timestamp`, `id`, `address`, `connection`, `type`, then one column per data field |
| `alert` | `timestamp`, `id`, `address`, `level`, `type`, `data` |
| `log-entry` | `timestamp`, `id`, `address`, `level`, `content` |

Message data is text with each byte as one Latin-1 character. A particle data field nested in a
section becomes a column named `section.field`, a fixed-length tuple becomes one column per item,
and a list of varying length stays one column of JSON text. A particle exporter without a `type`
writes the whole data object as one `data` column, which `jsonl` allows and `csv` refuses.

`raw` writes the bytes of every message back to back with nothing between them, which reproduces
the stream a connection received. It holds no IDs, so a run cannot merge into a `raw` file and must
replace it, and `raw` takes no `schedule`.

### NetCDF

`netcdf` writes one NetCDF-4 file of one particle class, which the `netCDF4` and `xarray` readers
open. Each row is a particle along the `time` dimension.

| Variable | Contents |
|---|---|
| `time` | Seconds since 1970-01-01 UTC, exact to the microsecond through 2106. |
| `id` | The particle's ID as 36 characters. |
| `connection` | Index into `connection_name`, `-1` for a particle with no connection. |
| `connection_name` | The connection names the file's particles arrived on. |

Every data field with a fixed shape becomes a variable. A field nested in a section is named
`section_field`, unless its name already starts with the section's. A fixed-length tuple or a
`PackedSequence(length=N)` sequence gains a dimension for each level. A list, `Sequence`, or
`tuple[X, ...]` without a `PackedSequence` length has no fixed shape, so the file leaves it out along
with any section holding one, and the exporter logs a warning naming every field it leaves out. Two
fields whose names become one variable name make the configuration invalid. A field annotated with
`Unit()` carries a `units` attribute, and datetimes are seconds since the epoch. An absent field
holds the netCDF fill value, except a `str` field, which holds an empty string. The file's
attributes name the `exporter`, its component's `address`, and the `particle_type`.

Pass more attributes as arguments:

```yaml
format:
  class: netcdf
  arguments:
    attributes:
      celsius: { long_name: Water temperature }
    global_attributes:
      institution: Example Lab
```

A NetCDF file cannot take an appended row, so every write rewrites the whole file and holds the
period's rows in memory, about 8 bytes per row per variable, plus at most 4 MiB of rows allocated
ahead. A live `netcdf` exporter reads, merges, and compresses the whole file on every write, so
`live` is off unless set. At 10 records a second an hour's file holds 36,000 rows, each rewritten
on every flush, so a high-rate stream wants a period no longer than `hour`, or a schedule in place
of `live`. Two
runs over the same rows write identical bytes, though a file records the library versions that wrote
it, so an upgrade changes the bytes of a rewritten file.

## Live Export

A live exporter writes each batch of records the component stores, at most once per `interval`.
Records that arrive in order append to the end of their period's file. A record older than the
newest one in its file is late, and the exporter merges it into the file in key order, which reads
and rewrites the whole file. An exporter whose records often arrive late logs a warning after 10
merges into one file, and a longer `interval` merges more of them at once. `raw` holds no keys, so
it appends a late record where it arrives. A failed write logs a warning and retries at every
interval.

When it starts, a live exporter checks the files of the current and previous periods, and of every
period back to the newest stored record, at most 100 of them. It merges in any stored record a file
lacks, such as one stored while the component was stopped, and drops a final record a crash left
half written. One interval after each period ends it checks that period's file the same way.

A `raw` file has no keys to check or heal. It lacks every record stored while its exporter was
stopped, and a `raw` exporter that finds such a record in the current period logs the re-run that
replaces the file. The pruner guard covers only records stored while a `raw` exporter runs, and a
crash can leave a `raw` file ending in part of a message.

The exporter hears the records the engine stores through `store`. A record written another way, by a
manager's `create` or `update`, by `ceres <entity> load`, or by another process, reaches the files
through the checks above or a run.

## Pruning Exported Records

A pruner never deletes a record its component's exporters of that kind have not yet written. It
deletes only records older than the point every such exporter has written through: a live
exporter's newest written record, or the end of another exporter's latest completed run. An
exporter that has written nothing holds every record. A pruner held at one point for two of its
runs in a row logs a warning naming the exporter.

Such a pruner deletes in pages of 1000 records, oldest first. While a page deletes, the engine
keeps the records it stores in memory and writes them once the page ends. On PostgreSQL that
holds a write for under 50 ms. On SQLite it holds one for up to a few seconds, and the prune takes
longer in total than one unbounded delete would. Set `wait_for_exports: false` on a pruner to let
it delete regardless, in one statement.

## Re-Running An Exporter

A run covers every period overlapping a range of time, from `after` up to `before`. It reads each
whole period from the database, so a range ending mid-period still rewrites that period's file in
full. A `period: all` exporter has one file, so its run writes every stored record whatever the
range.

A run merges by default. Records in the file and in the database are written once, from the
database. Records only in the file stay. A period with no records in the database keeps its file
untouched. With `replace`, the run writes each file from the database alone and removes the file of
a period with no records.

Every file is written to a temporary sibling and moved into place, so a reader never sees a partly
written file. A new file takes the mode the process umask gives it, and a rewritten file keeps its
mode. One run of an exporter writes at a time, a second waits for the first, and a third is
refused. A scheduled run refused this way logs a warning, and the next one's `lookback` covers it.

Start a run through the HTTP API, with operate access to the component:

```text
POST /api/components/@sensor/exporters/messages/runs
{"after": "2026-01-01T00:00:00Z", "before": "2026-01-02T00:00:00Z", "replace": false}
```

The response holds the run's ID at once, and the run goes on in the component. `before` defaults
to the current time. `GET /api/components/@sensor/exporters/messages/runs` lists the exporter's last
20 runs, newest first, with each one's state, record count and files, to anyone who can view the
component.

`ceres export` starts the same run from the command line and waits for it to end. Without an
exporter name, it runs every exporter of the component that merges, or every one with
`--replace`. A time without a zone is UTC.

```bash
ceres export @sensor messages --after 2026-01-01 --before 2026-01-02
ceres export @sensor --after 2026-01-01 --replace
```

The console's component page lists each exporter in its "Exporters" section with its last run.
Its "Rebuild" button asks for the range and starts a run, and the section shows the run's record
count while it goes. A format that cannot merge offers no "Replace file contents" choice, since
every run of it replaces.

### Exporting Loaded Records

Records that `ceres messages load` and its siblings write reach an exporter only when the load
passes `--export`:

```bash
ceres messages load rows.jsonl --export
```

The load then runs, as one merge each, every merging exporter of the kind it loaded on each
component holding a loaded address, over the time from the first loaded record it takes to the
last. With no engine running, the load appends those ranges to `.ceres/pending-exports.jsonl`
beside the configuration, and the engine exports them when it next starts. That file sits on the
host running the load, so a load on another host reaches the engine only while the engine runs.

A run keeps going when the page or command that started it closes. Its record counts the periods
its range covers in `periods` and the ones it has finished in `periods_done`, a period with no
records included, which the console shows as a progress bar and `ceres export` as a line each time
it changes. Each run emits `ExportRunStartedEvent`, one `ExportRunProgressEvent` per file it
writes, and then `ExportRunCompletedEvent` or `ExportRunFailedEvent`. A completed run also writes
one log entry naming its range, its record count and its files. With `logging.events` on, every
event becomes a log entry too, so a year of hourly files logs 8760 progress entries. The engine
keeps runs in memory, so a restart stops every running run and forgets them all.

## Playing Back Stored Messages

A playback parses a component's stored messages again, for example after a sieve's fix. It covers
a range from `after` up to `before`, and it runs every sieve of the component that stores its
particles. First it deletes the component's stored particles in the range of every type those
sieves declare, then it runs each sieve over its stored messages in the range and stores what the
sieve yields. While a sieve handles a message, `utc()` returns that message's time, so a particle
built with the current time takes its message's time.

A playback runs only when each storing sieve declares the particle types it yields, through its
return annotation or the component's `__particles__`. It refuses a range starting before the oldest
stored message a sieve reads, and names the range of messages stored, since a playback of less than
the range asked would delete particles it cannot regenerate.

A particle of a replayed type that something other than a sieve stored, such as an action calling
`store`, is lost. Particles of child components stay.

Start a playback through the HTTP API, with manage access to the component:

```text
POST /api/components/@sensor/playbacks
{"after": "2026-01-01T00:00:00Z", "before": "2026-01-02T00:00:00Z", "level": "particles", "export": true}
```

`before` defaults to, and is capped at, the current time. One playback of a component runs at a
time. `GET /api/components/@sensor/playbacks` lists the last 20, newest first. The console's
"Play Back" button in the "Exporters" section asks for the same values, and `ceres playback`
starts one from the command line and waits for it to end:

```bash
ceres playback @sensor --after 2026-01-01 --before 2026-01-02 --level full --no-export
```

- `level: particles`, the default, stores each particle and emits nothing.
- `level: full` also emits each particle's `ParticleEvent`, so every listener runs as if live,
  actions included. A listener that commands hardware or stores records does so once per replayed
  particle, and a record it builds takes the current time.

With `export`, the default, the playback then runs every particle exporter of the component whose
type it replayed, or that exports every type, as a replace over the range. An exporter of several
types loses from its files the pruned records of the types the playback did not replay. When an
exporter already has a run waiting, the playback fails naming it, the particles stay stored, and a
"Rebuild" of that exporter writes its files. Without `export`, a live exporter's files keep the
deleted particles beside the new ones until a replace run.

The live sieves keep running. Readers see the range without particles while the playback runs. A
sieve that buffers bytes across messages may store a particle at `before` from live data after the
delete, so keep `before` behind the newest live messages.

A playback's record reads `progress` from 0 to 1 over its replay, each sieve an equal share, by
the time of the last message the current sieve took (`position`) within the range. It reaches 1
before the exports that follow, whose own runs report their progress. Each playback emits
`PlaybackStartedEvent`, a `PlaybackProgressEvent` about once a second while it replays and when
each sieve finishes, and then `PlaybackCompletedEvent` or `PlaybackFailedEvent`, and a completed
one writes one log entry.
