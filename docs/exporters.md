# Exporters

An exporter writes a component's records to files, one file per period of time. The files are the
archive and the product of a deployment. The database is the working copy: a pruner may clear old
rows from it, and the files keep them.

Ceres never removes a record from a file on its own. A scheduled run or a manual re-run merges the
database into each file, so a row the database lost stays in the file and a row the database holds
replaces the file's copy. Only a run that asks to replace rewrites a file from the database alone.

## Configuring An Exporter

Exporters belong to a component in `ceres.yaml`. Each one names the records it writes, the format,
the period one file covers, and a path template for the files.

```yaml
components:
  - name: sensor
    class: my_project.SensorDriver
    arguments:
      output: /data/sensor
    exporters:
      - name: messages
        exports: message
        format: csv
        period: hour
        path: "{exporter}/%Y/%m/%d/%H"
        schedule: "5 * * * *"
```

This exporter writes the sensor's messages to `/data/sensor/messages/2026/01/01/00.csv` and one
file for each later hour. It writes each message within a few seconds of storing it, and five minutes
past every hour it also merges the database into the files of the current hour and the hour before
it.

| Field | Meaning |
|---|---|
| `name` | Exporter name, unique within its component. |
| `exports` | Record kind: `message`, `particle`, `alert` or `log-entry`. |
| `filter` | Records to export, in the kind's filter syntax. Every record of the kind at the component when omitted. |
| `type` | Particle class whose data fields become columns. Particle exporters only, and required for `csv`. |
| `format` | `csv`, `jsonl`, `raw`, or a custom format as `{class, arguments}`. |
| `directory` | Name of the component's `Directory` field the files live under, `output` when omitted. |
| `period` | Time one file covers: `hour`, `day`, `month`, or `all` for a single file. |
| `path` | Path template of each file, relative to the directory, without an extension. |
| `live` | Whether the exporter writes records as the component stores them. On for every built-in format when omitted. |
| `interval` | Least time between two live writes, 5 seconds when omitted and at least 1 second. |
| `schedule` | Cron or interval expression for scheduled runs. No scheduled runs when omitted. |
| `lookback` | Periods before the current one each scheduled run covers, 1 when omitted. |

A filter selects records and nothing else, so it cannot set `order`, `limit` or `offset`. It also
cannot set `subsample`, `subsample_every`, `subsample_select`, `timespan`, `max_age` or `min_age`,
since a live write and a later run must select the same records. The exporter writes records in
timestamp order, and records with equal timestamps in ID order.

## Paths

The path is a `strftime` template of the period's UTC start. `{exporter}` renders the exporter
name, and `{connection}` renders the connection name when the filter pins exactly one connection.
The format adds its extension: `.csv`, `.jsonl`, or `.bin` for `raw`.

Ceres refuses a path that writes two periods to one file, such as `%Y/%m/%d` for an hourly exporter
or `%y` where two centuries meet. A `period: all` path takes no time directives, apart from `%%` for
a literal `%`. A path must stay inside the directory, so it cannot start with `/` or contain `..`.

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

Each run emits `ExportRunStartedEvent`, one `ExportRunProgressEvent` per file it writes, and then
`ExportRunCompletedEvent` or `ExportRunFailedEvent`. A completed run also writes one log entry
naming its range, its record count and its files. With `logging.events` on, every event becomes a
log entry too, so a year of hourly files logs 8760 progress entries.
