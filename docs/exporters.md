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
file for each later hour. Five minutes past every hour it merges the database into the files of the
current hour and the hour before it.

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
| `schedule` | Cron or interval expression for scheduled runs. No scheduled runs when omitted. |
| `lookback` | Periods before the current one each scheduled run covers, 1 when omitted. |

A filter selects records and nothing else, so it cannot set `order`, `limit` or `offset`. The
exporter writes records in timestamp order, and records with equal timestamps in ID order.

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

## Re-Running An Exporter

A run covers every period overlapping a range of time, from `after` up to `before`. It reads each
whole period from the database, so a range ending mid-period still rewrites that period's file in
full.

A run merges by default. Records in the file and in the database are written once, from the
database. Records only in the file stay. A period with no records in the database keeps its file
untouched. With `replace`, the run writes each file from the database alone and removes the file of
a period with no records.

Every file is written to a temporary sibling and moved into place, so a reader never sees a partly
written file. One run of an exporter writes at a time, and a second waits for the first.

Start a run through the HTTP API, with operate access to the component:

```text
POST /api/components/@sensor/exporters/messages/runs
{"after": "2026-01-01T00:00:00Z", "before": "2026-01-02T00:00:00Z", "replace": false}
```

The response holds the run's ID at once, and the run goes on in the component. `before` defaults
to the current time. `GET /api/components/@sensor/exporters/messages/runs` lists the exporter's last
20 runs, newest first, with each one's state, record count and files.

Each run emits `ExportRunStartedEvent`, one `ExportRunProgressEvent` per file it writes, and then
`ExportRunCompletedEvent` or `ExportRunFailedEvent`. A completed run also writes one log entry
naming its range, its record count and its files.
