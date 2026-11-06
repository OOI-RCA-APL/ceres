# Exporters

An exporter writes a component's records to files, one file per period of time. The files are the
archive and the product of a deployment. The database is the working copy: a pruner may clear old
rows from it, and the files keep them.

Ceres never removes a record from a file on its own. A live exporter only appends, and a run that
rewrites a file keeps the existing one whenever the database may no longer hold all of its records.
Only a run that asks to purge rewrites a file from the database whatever it held.

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
past every hour it also rewrites the files of the current hour and the hour before it from the
database.

| Field | Meaning |
|---|---|
| `name` | Exporter name, unique within its component. |
| `exports` | Record kind: `message`, `particle`, `alert` or `log-entry`. |
| `filter` | Records to export, in the kind's filter syntax. Every record of the kind at the component when omitted. |
| `type` | Particle class whose data fields become columns. Particle exporters only, and required for `csv` and `netcdf`. |
| `format` | `csv`, `jsonl`, `netcdf`, `raw`, or a writer class with its arguments as `{class, arguments}`, as in [Creating A Custom Writer](#creating-a-custom-writer). |
| `fields` | Columns to write, in order, each optionally renamed, as in [Choosing Columns](#choosing-columns). Every column when omitted. |
| `mount` | Name of the component's mount the files live under, `output` when omitted. |
| `period` | Time one file covers: `hour`, `day`, `month`, or `all` for a single file. |
| `path` | File name of each period, without an extension. A name for the period when omitted. |
| `live` | Whether the exporter writes records as the component stores them. On when omitted, except for `netcdf`. |
| `interval` | Least time between two live writes, 5 seconds when omitted and at least 1 second. |
| `schedule` | Cron or interval expression for scheduled runs. No scheduled runs when omitted, and refused with `period: all`. |
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

`csv` writes one line per record. `jsonl` writes one JSON object per line with the same fields, in
the same order. Both start every line with the record's `timestamp` and `id`, unless `fields` says
otherwise. A `csv` file has no header line unless the format's `header` argument asks for one:

```yaml
format:
  class: csv
  arguments:
    header: true
```

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
the stream a connection received. It holds no IDs or times, so a live `raw` exporter cannot tell
where it left off in a file it finds on start. It writes no columns, so it takes no `fields`.

### Choosing Columns

`fields` picks the columns an exporter writes and their order, and can rename each one. It takes the
same `alias:field` specs as the command line's `--field`: a comma-separated string, a list, or a
mapping of alias to field.

```yaml
fields: time:timestamp, temperature:celsius, flow
fields: [time:timestamp, temperature:celsius, flow]
fields:
  time: timestamp
  temperature: celsius
  flow: ~
```

The three forms above are equal. A spec without a colon, or a mapping entry without a field, keeps
the field's own name. A spec splits at its last colon, so an alias may hold colons. A field naming a
section selects every column nested in it, each renamed under the alias, so `f:flow` writes
`f.rate` and `f.flow_speed`. The configuration is invalid when a field names no column or two
specs give one column name.

`netcdf` applies `fields` to its data variables, joining a renamed section's nested names with `_`
as it does without `fields`. Its `time`, `id` and `connection` variables stay whatever `fields`
names.

A live `csv` or `jsonl` exporter finds where it left off in a file from the `timestamp` and `id` of
its last line. When `fields` does not start with those two under their own names, it treats a file
it finds on start as `raw` does.

A file without a header holds nothing to compare columns with, so an exporter whose `fields` or
particle class changed appends rows of the new shape to an existing file without noticing. When
columns change, give the exporter a `path` that renders new file names, or a new `name` when its
`path` contains `{exporter}`.

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
ahead. A live `netcdf` exporter rewrites and compresses the period's whole file from the database on
every write, so `live` is off unless set. At 10 records a second an hour's file holds 36,000 rows,
each rewritten on every flush, so a high-rate stream wants a period no longer than `hour`, or a
schedule in place of `live`. Two runs over the same rows write identical bytes, though a file
records the library versions that wrote it, so an upgrade changes the bytes of a rewritten file.

## Creating A Custom Writer

A format Ceres lacks is a class the project writes. `format` names it with its arguments, which
become the writer's fields:

```yaml
format:
  class: my_project.exporters.TabWriter
  arguments:
    header_line: true
```

A writer subclasses `ExportLineWriter` for a file of one line per record, or `ExportWriter` for any
other file. This one writes tab-separated values:

```python
from datetime import datetime
from typing import ClassVar, override
from uuid import UUID

from ceres import ExportKey, ExportLineWriter, ExportRecord, ExportSchema


class TabWriter(ExportLineWriter):
    """Tab separated values, optionally with a header line."""

    extension: ClassVar[str] = ".tsv"
    resumable: ClassVar[bool] = True

    header_line: bool = False

    @staticmethod
    def cell(value: object) -> str:
        # A tab or line break inside a value would split its cell or its line.
        text = "" if value is None else str(value)
        return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")

    @override
    def header(self, schema: ExportSchema) -> bytes:
        names = (self.cell(name) for name in schema.names)
        return ("\t".join(names) + "\n").encode() if self.header_line else b""

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        return ("\t".join(self.cell(value) for value in schema.row(record)) + "\n").encode()

    @override
    def key(self, line: bytes) -> ExportKey:
        timestamp, id = line.rstrip(b"\n").split(b"\t", 2)[:2]
        return datetime.fromisoformat(timestamp.decode()), UUID(id.decode())
```

`schema.names` lists the columns in file order after `fields` chose and renamed them, and
`schema.row(record)` returns a record's values in that order, in the JSON form the API serves:
times as text, nested values as lists and objects. `encode` returns one record's bytes with their
line terminator, so a value holding the separator or a line break must be escaped. A line writer
appends records live and leaves an existing file's earlier lines alone. With `resumable` set, `key`
reads the `timestamp` and `id` back from a record, its line terminator included, so a live exporter
restarting on a file continues after its last line and cuts off a torn last line. Without it, the
exporter never reads the file, which suits lines that hold no key. A record spanning several
physical lines needs `split`, which groups the file's lines back into records.

Any other file subclasses `ExportWriter` and writes the whole file at once:

```python
import json
from collections.abc import AsyncIterable
from pathlib import Path
from typing import ClassVar, override

import anyio

from ceres import ExportRecord, ExportSchema, ExportWriter


class SummaryWriter(ExportWriter):
    """One JSON document per file holding every record's row."""

    extension: ClassVar[str] = ".json"

    @override
    async def write(
        self, path: Path, schema: ExportSchema, records: AsyncIterable[ExportRecord]
    ) -> None:
        # Writes each row as it arrives, so a file of any size holds one row in memory.
        async with await anyio.open_file(path, "w") as file:
            await file.write(f'{{"columns": {json.dumps(schema.names)}, "rows": [')
            separator = ""
            async for record in records:
                row = dict(zip(schema.names, schema.row(record), strict=True))
                await file.write(separator + json.dumps(row))
                separator = ", "

            await file.write("]}")
```

A period has no cap on its records, so a writer streams them to the file as they arrive and does
its file work through async IO, since a writer runs on the engine's event loop. A whole-file writer
rewrites its file on every run, and on every live write when `live` is set and the database still
holds every record the file does. `schema.fields` describes the particle class's data fields, their
types and their `Unit()` metadata, for a format that records them.

Every writer keeps to these rules:

- `write` writes a whole file at the path it receives, a temporary file beside the final one,
  which replaces the final file only when `write` returns. A library choosing its behavior from
  the file's suffix needs the format given explicitly. A `write` that raises leaves the old file in
  place.
- `append`, on a writer that sets `appendable`, adds records to the end of the final file itself,
  so records it wrote before raising stay in the file. `ExportLineWriter` provides it, and a
  resumable line writer's next start cuts off a torn last line.
- It reads the records to their end, once, in `timestamp` then `id` order, and closes the file
  before returning.
- It lets exceptions propagate, which fails the run and names the error.
- It touches nothing else: no second file, no network. One exporter file is one artifact, so a
  sidecar file would escape the conflict modes and `purge`.
- Its constructor and `check` stay cheap and free of side effects, since validating the
  configuration creates writers often.

`appendable`, `schema_bound` (a particle exporter must name `type`), `exports` (the record kinds it
writes) and `selects` (whether it takes `fields`) are class variables a writer may set, and `check`
may refuse a schema or name the data fields its files leave out. A dry run plans files and counts
records without calling `write` or `append`, so it cannot show that a write would succeed.

A component can also write a file of particles it computes and never stores, with a writer and
`atomic_write`, which replaces the file only once the block completes:

```python
from ceres import EntityType, ExportSchema, atomic_write

schema = ExportSchema.create(EntityType.PARTICLE, Reading, "daily")
async with atomic_write(self.output / "summary.json") as temporary:
    await SummaryWriter().write(temporary, schema, computed())
```

Two exporters writing one file overwrite each other's records, and nothing checks for it, so each
exporter needs a `path` of its own.

## Live Export

A live exporter writes each batch of records the component stores, at most once per `interval`.
Records that arrive in order append to the end of their period's file. A record no newer than the
last one in its file is late. The exporter leaves it in the database alone and logs one warning per
file naming the `ceres export` command that rewrites the file. A pruner may delete the record
before a run writes it. `raw` holds no keys, so it appends a late record where it arrives. A
failed write logs a warning and retries at every interval.

When it starts, a live exporter checks the files of the current and previous periods, and of every
period back to the newest stored record, at most 100 of them. It writes a missing file from the
database, and appends to a `csv` or `jsonl` file the stored records after its last line, dropping a
final line a crash left half written. A whole-file format such as `netcdf` rewrites a file it wrote
itself, a missing one, or one whose period starts within the stored records. Any other file holding
fewer records than the database takes the same warning as a late record.

A `raw` file has no keys to resume from, so a `raw` exporter that finds stored records in an
existing file's period logs the warning, and a crash can leave a `raw` file ending in part of a
message.

The exporter hears the records the engine stores through `store`. A record written another way, by a
manager's `create` or `update`, by `ceres <entity> load`, or by another process, reaches the files
through the checks above or a run.

## Pruning Exported Records

A pruner deletes on its own filter alone and never waits for an exporter. Keeping the files
complete is the project's job: give a pruner a retention longer than any delay before records
reach their files, and run `ceres export` for records an exporter left in the database, such as
late or offline records it warned about, before the pruner reaches them. A prune never changes
an exported file.

## Re-Running An Exporter

A run rewrites an exporter's files from the database over a range of time, from `after` up to
`before`. Its range mode says how that range meets the files it partly overlaps:

| `range_mode` | Effect |
|---|---|
| `expand` | The default. Widens the range to the whole files it touches. |
| `exact` | Keeps the range, so a file at either end takes only part of its records. |
| `shrink` | Narrows the range to the whole files inside it, writing nothing when none fits. |

A `period: all` exporter has one file, so `expand` covers all time, `shrink` covers nothing, and
`exact` covers part of the file.

Its conflict mode says what it does with a file that already exists:

| `on_conflict` | Effect |
|---|---|
| `overwrite` | The default. Rewrites the file from the database, unless that could lose records only the file holds. |
| `skip` | Leaves the file as it is and writes only missing files. |
| `error` | Refuses the whole run before writing anything. |
| `purge` | Rewrites the file from the database whatever it held, and removes it when the database holds none of its records. |

`overwrite` keeps an existing file when the file's period starts before the oldest record the
exporter selects from the database, since a pruner may have deleted older records the file still
holds. It also keeps a file the range covers only part of, and one the database holds no records
for. `purge` rewrites or removes every such file, so it can discard archived records the database
no longer holds. No mode deletes database records or touches a file outside the range. A missing
file is written from whatever the database holds.

Every file is written to a temporary sibling and moved into place, so a reader never sees a partly
written file. A new file takes the mode the process umask gives it, and a rewritten file keeps its
mode. One run of an exporter writes at a time, a second waits for the first, and a third is
refused. A scheduled run refused this way logs a warning, and the next one's `lookback` covers it.

Start a run through the HTTP API, with operate access to the component:

```text
POST /api/components/@sensor/exporters/messages/runs
{"after": "2026-01-01T00:00:00Z", "before": "2026-01-02T00:00:00Z", "on_conflict": "overwrite", "range_mode": "expand"}
```

The response holds the run's ID at once, and the run goes on in the component. `before` defaults
to the current time. With `"dry_run": true` the response is instead the run's plan, each file it
covers with its bounds, whether it exists, what the run would do with it and why, and its stored
record count, and nothing is written. An `error` run whose files exist answers 422 naming them.
`GET /api/components/@sensor/exporters/messages/runs` lists the exporter's last 20 runs, newest
first, with each one's state, record count and files, to anyone who can view the component.

`ceres export` starts the same run from the command line and waits for it to end, showing its
progress on one line. Without an exporter name, it runs every exporter of the component, and with
`--on-conflict error` it checks every one before starting any. `--dry-run` prints each plan as JSON
to standard output and as a table to standard error. A time without a zone is UTC.

```bash
ceres export @sensor messages --after 2026-01-01 --before 2026-01-02
ceres export @sensor --after 2026-01-01 --on-conflict skip --range-mode shrink --dry-run
```

The console's component page lists each exporter in its "Exporters" section with its last run.
Its "Rebuild" button asks for the range and modes and starts a run, and the section shows the run's
record count while it goes.

### Exporting Loaded Records

Records that `ceres messages load` and its siblings write reach an exporter only when the load
passes `--export`:

```bash
ceres messages load rows.jsonl --export --on-export-conflict skip
```

`--on-conflict` still decides what the load does with a row whose key the database already holds,
and `--on-export-conflict` what its exports do with a file that already exists.

The load then runs every exporter of the kind it loaded on each component holding a loaded address,
over the time from the first loaded record it takes to the last, with `--on-export-conflict` and
`--export-range-mode` as its modes, `overwrite` and `expand` when unset. With no engine running,
the load appends those ranges and modes to `.ceres/pending-exports.jsonl` beside the configuration,
and the engine exports them when it next starts. That file sits on the host running the load, so a
load on another host reaches the engine only while the engine runs. A pending export that fails
logs the `ceres export` command that retries it.

A run keeps going when the page or command that started it closes. Its record counts the files its
range covers in `periods` and the ones it has finished in `periods_done`, a file it keeps or finds
empty included, which the console shows as a progress bar and `ceres export` as its progress line,
redrawn in place on a terminal and one line per change elsewhere. Each run emits
`ExportRunStartedEvent`, one `ExportRunProgressEvent` per file it writes, and then
`ExportRunCompletedEvent` or `ExportRunFailedEvent`. A completed run also writes
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
return annotation or the component's `__particles__`. A range starting before the oldest stored
message a sieve reads starts at that message instead, since particles before it have no messages to
rebuild from, and a range holding no stored messages completes at once without changing anything.

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
starts one from the command line and waits for it to end, showing its progress on one line:

```bash
ceres playback @sensor --after 2026-01-01 --before 2026-01-02 --level full
ceres playback @sensor --after 2026-01-01 --export --export-range-mode exact --dry-run
```

- `level: particles`, the default, stores each particle and emits nothing.
- `level: full` also emits each particle's `ParticleEvent`, so every listener runs as if live,
  actions included. A listener that commands hardware or stores records does so once per replayed
  particle, and a record it builds takes the current time.

With `export`, the playback then runs every particle exporter of the component whose type it
replayed, or that exports every type, over the range, with `on_export_conflict` and
`export_range_mode` as the runs' modes (`--on-export-conflict` and `--export-range-mode`, which
need `--export`). Its range follows the exporters' files: with `expand` the playback widens its
own range to the whole files of every such exporter, so it rebuilds every particle the files it
rewrites hold, and with `exact` or `shrink` it replays the range as given. An `error` playback whose
files exist fails before deleting anything. An exporter of several types loses from its files the
pruned records of the types the playback did not replay. When an exporter already has a run
waiting, the playback fails naming it, the particles stay stored, and a "Rebuild" of that exporter
writes its files. Without `export`, a live exporter's files keep the deleted particles beside the
new ones until a run rewrites them.

With `"dry_run": true` (`--dry-run`) the playback deletes and stores nothing. It runs fresh copies of
the sieves over the stored messages and answers with what it would do, the particles it would
delete, each sieve's message and particle counts, each export run's plan with the particles it
parsed counted into each file, and the first 100 log entries the sieves wrote with a count per
level. A sieve's log entries go only to that answer, never to the log or the database. A sieve
whose parsing depends on state outside it, such as a component variable, may parse differently
when the playback runs.

The live sieves keep running. Readers see the range without particles while the playback runs. A
sieve that buffers bytes across messages may store a particle at `before` from live data after the
delete, so keep `before` behind the newest live messages.

A playback's record reads `progress` from 0 to 1 over its replay, each sieve an equal share, by
the time of the last message the current sieve took (`position`) within the range. It reaches 1
before the exports that follow, whose own runs report their progress. Each playback emits
`PlaybackStartedEvent`, a `PlaybackProgressEvent` about once a second while it replays and when
each sieve finishes, and then `PlaybackCompletedEvent` or `PlaybackFailedEvent`, and a completed
one writes one log entry.
