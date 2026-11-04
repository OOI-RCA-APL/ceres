import { lowerCase } from 'lodash-es'
import * as z from 'zod'

import { Failure } from '@/errors'
import type { SchemaObject } from '@/schema-form'
import { type Datetime, displayDuration, utc } from '@/time'

export type ExportRunState = z.infer<typeof ExportRunStateModel>
export const ExportRunStateModel = z.enum(['running', 'completed', 'failed'])

/** What a run does with a file that already exists. */
export type ExportConflict = z.infer<typeof ExportConflictModel>
export const ExportConflictModel = z.enum(['overwrite', 'skip', 'error', 'purge'])

/** How a run aligns its range with the exporter's files. */
export type ExportRangeMode = z.infer<typeof ExportRangeModeModel>
export const ExportRangeModeModel = z.enum(['expand', 'exact', 'shrink'])

/** An export run without its file list, which grows with every period it writes. */
export type ExportRunSummary = z.infer<typeof ExportRunSummaryModel>
export const ExportRunSummaryModel = z.object({
  id: z.string(),
  after: z.string(),
  before: z.string(),
  on_conflict: ExportConflictModel,
  range_mode: ExportRangeModeModel,
  /** Start of the range the run covers, null for the start of time. */
  effective_after: z.string().nullable(),
  /** End of the range the run covers, null for the end of time. */
  effective_before: z.string().nullable(),
  state: ExportRunStateModel,
  started: z.string(),
  ended: z.string().nullable(),
  /** Records written so far. */
  count: z.number(),
  /** Files written so far. */
  file_count: z.number(),
  /** Existing files the run left as they were. */
  kept: z.number(),
  /** Existing files the run removed. */
  removed: z.number(),
  /** Files the run covers. */
  periods: z.number(),
  /** Files finished so far, written, kept, removed or found empty. */
  periods_done: z.number(),
  exception: z.string().nullable(),
})

export type ExporterPeriod = z.infer<typeof ExporterPeriodModel>
export const ExporterPeriodModel = z.enum(['hour', 'day', 'month', 'all'])

export type ExporterInfo = z.infer<typeof ExporterInfoModel>
export const ExporterInfoModel = z.object({
  name: z.string(),
  exports: z.string(),
  /** The exported particle type, null for every type or another kind. */
  type: z.string().nullable(),
  format: z.string(),
  /** Name of the component's mount the files live under. */
  mount: z.string(),
  period: ExporterPeriodModel,
  /** The file name template, without the extension the format adds. */
  path: z.string(),
  /** The current period's file relative to the mount, null when the mount is missing. */
  file: z.string().nullable(),
  live: z.boolean(),
  /** An ISO 8601 duration. */
  interval: z.string(),
  schedule: z.string().nullable(),
  lookback: z.number().nullable(),
  next_run: z.string().nullable(),
  last_run: ExportRunSummaryModel.nullable(),
})

/** Body of a request to start an export run over `[after, before)`, `before` defaulting to now. */
export type ExportRunRequest = {
  after: string
  before?: string | null
  on_conflict: ExportConflict
  range_mode: ExportRangeMode
}

function counted(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

function minute(timestamp: string): string {
  return `${utc(timestamp).format('YYYY-MM-DD HH:mm')} UTC`
}

/** What an exporter writes and when, as the sentences under its name. */
export function describeExporter(exporter: ExporterInfo): string {
  const kind = lowerCase(exporter.exports)
  const what = exporter.type == null ? `${kind} records` : `${kind} "${exporter.type}" records`
  const files = exporter.period === 'all' ? 'one file' : `one file per ${exporter.period}`
  const place = exporter.file ?? exporter.path
  const sentences = [
    `Writes ${what} as ${exporter.format}, ${files} like ${exporter.mount}/${place}.`,
  ]
  if (exporter.live) {
    sentences.push('Live.')
  }

  if (exporter.schedule != null) {
    const lookback =
      exporter.lookback == null ? '' : `, covering ${counted(exporter.lookback, 'period')} back`
    sentences.push(`Schedule "${exporter.schedule}"${lookback}.`)
  }

  return sentences.join(' ')
}

const exceptionLength = 120

/** How long a run has been going at `now`, such as "3m". */
function elapsed(started: string, now: Datetime): string {
  return displayDuration(Math.max(now.diff(utc(started), 'second'), 0), {
    short: true,
    decimals: 0,
  })
}

/** How far a running export run has got, as a percentage. */
export function exportRunPercent(run: ExportRunSummary): number {
  return run.periods === 0 ? 0 : Math.floor((100 * run.periods_done) / run.periods)
}

/** How an exporter's last run went, as one line, or that it never ran. */
export function describeExportRun(run: ExportRunSummary | null, now: Datetime): string {
  if (run == null) {
    return 'Never run.'
  }

  switch (run.state) {
    case 'running':
      return (
        `${run.periods_done} of ${counted(run.periods, 'file')}, ` +
        `${counted(run.count, 'record')} so far, running ${elapsed(run.started, now)}.`
      )
    case 'completed': {
      const kept = run.kept > 0 ? `, kept ${counted(run.kept, 'file')}` : ''
      const removed = run.removed > 0 ? `, removed ${counted(run.removed, 'file')}` : ''
      return (
        `${minute(run.started)}, ${counted(run.count, 'record')} in ` +
        `${counted(run.file_count, 'file')}${kept}${removed}.`
      )
    }
    case 'failed': {
      const [first = ''] = (run.exception ?? 'unknown error').split('\n')
      const shown =
        first.length > exceptionLength ? `${first.slice(0, exceptionLength - 3)}...` : first
      return `${minute(run.started)}, failed: ${shown}`
    }
  }
}

/** Whether any exporter's last run is still going, which keeps its listing polled. */
export function isExportRunning(exporters: ExporterInfo[] | undefined): boolean {
  return exporters?.some((exporter) => exporter.last_run?.state === 'running') ?? false
}

const dateRange: Record<string, SchemaObject> = {
  after: { type: 'string', format: 'date-time', title: 'After' },
  before: {
    type: 'string',
    format: 'date-time',
    title: 'Before',
    description: 'Now when left empty.',
  },
}

function conflictSchema(title: string): SchemaObject {
  return {
    type: 'string',
    title,
    enum: [...ExportConflictModel.options],
    enumLabels: ['Overwrite', 'Skip', 'Error', 'Purge'],
    default: 'overwrite',
    description:
      'Overwrite keeps a file that may hold records the database no longer does. ' +
      'Purge rewrites it anyway and can lose them.',
  }
}

function rangeModeSchema(title: string): SchemaObject {
  return {
    type: 'string',
    title,
    enum: [...ExportRangeModeModel.options],
    enumLabels: ['Expand', 'Exact', 'Shrink'],
    default: 'expand',
    description:
      'Expand widens the range to whole files, exact writes only the range, ' +
      'shrink keeps only the whole files inside it.',
  }
}

/** The form a rebuild asks for. */
export function exportRunSchema(): SchemaObject {
  return {
    type: 'object',
    properties: {
      ...dateRange,
      on_conflict: conflictSchema('Existing Files'),
      range_mode: rangeModeSchema('Range Mode'),
    },
    required: ['after'],
  }
}

/** The request a rebuild form's values send. */
export function exportRunRequest(values: {
  after: string
  before?: string | null
  on_conflict?: ExportConflict
  range_mode?: ExportRangeMode
}): ExportRunRequest {
  return {
    after: values.after,
    before: values.before ?? null,
    on_conflict: values.on_conflict ?? 'overwrite',
    range_mode: values.range_mode ?? 'expand',
  }
}

/** Why the server refused a run, as a sentence. */
export function describeExportRunFailure(error: unknown): string {
  return describeRefusal(error, {
    'failed-to-start': 'The run failed to start.',
    'not-permitted-error': 'Starting a run needs operate access.',
    'already-exists-error': 'A run of this exporter already waits for another.',
  })
}

/** Why the server refused a playback, as a sentence. */
export function describePlaybackFailure(error: unknown): string {
  return describeRefusal(error, {
    'failed-to-start': 'The playback failed to start.',
    'not-permitted-error': 'A playback needs manage access.',
    'already-exists-error': 'A playback of this component already runs.',
  })
}

function describeRefusal(
  error: unknown,
  sentences: Record<'failed-to-start' | 'not-permitted-error' | 'already-exists-error', string>,
): string {
  if (!(error instanceof Failure)) {
    return sentences['failed-to-start']
  }

  const info = error.error as { type: string; problems?: { message: string }[] }
  switch (info.type) {
    case 'not-running-error':
      return 'The component is not running.'
    case 'not-permitted-error':
    case 'already-exists-error':
      return sentences[info.type]
  }

  const messages = info.problems?.map((problem) => problem.message) ?? []
  if (messages.length > 0) {
    return messages.join(' ')
  }

  return `The server responded with "${info.type}".`
}

export type PlaybackLevel = z.infer<typeof PlaybackLevelModel>
export const PlaybackLevelModel = z.enum(['particles', 'full'])

/** One playback of a component's stored messages through its stored sieves. */
export type PlaybackRecord = z.infer<typeof PlaybackRecordModel>
export const PlaybackRecordModel = z.object({
  id: z.string(),
  /** Start of the range the request named. */
  requested_after: z.string(),
  /** End of the range the request named. */
  requested_before: z.string(),
  /** Start of the replayed range, aligned to the exporters' files and the stored messages. */
  after: z.string(),
  before: z.string(),
  level: PlaybackLevelModel,
  export: z.boolean(),
  on_export_conflict: ExportConflictModel,
  export_range_mode: ExportRangeModeModel,
  state: ExportRunStateModel,
  started: z.string(),
  ended: z.string().nullable(),
  /** Stored particles deleted before the replay. */
  deleted: z.number(),
  messages: z.number(),
  /** Particles stored so far. */
  particles: z.number(),
  sieves: z.number(),
  sieves_done: z.number(),
  /** The sieve replaying now. */
  sieve: z.string().nullable(),
  /** Timestamp of the last message the current sieve took. */
  position: z.string().nullable(),
  /** Fraction of the replay done, from 0 to 1, which reaches 1 before the exports that follow. */
  progress: z.number(),
  export_runs: z.array(z.string()),
  exception: z.string().nullable(),
})

/** Body of a request to start a playback over `[after, before)`, `before` defaulting to now. The
export modes go only with `export`, which the server requires of them. */
export type PlaybackRequest = {
  after: string
  before: string | null
  level: PlaybackLevel
  export: boolean
  on_export_conflict?: ExportConflict
  export_range_mode?: ExportRangeMode
}

/** How far a running playback's replay has got, as a percentage. */
export function playbackPercent(run: PlaybackRecord): number {
  return Math.floor(100 * run.progress)
}

/** How a component's last playback went, as one line, or that it never ran. */
export function describePlayback(run: PlaybackRecord | undefined, now: Datetime): string {
  if (run == null) {
    return 'Never played back.'
  }

  const counts = `${counted(run.messages, 'message')} into ${counted(run.particles, 'particle')}`
  switch (run.state) {
    case 'running': {
      const time = `running ${elapsed(run.started, now)}`
      if (run.sieves_done === run.sieves) {
        return `Rebuilding exporter files, ${counts}, ${time}.`
      }

      const through = run.position == null ? '' : ` through ${minute(run.position)}`
      return `${playbackPercent(run)}%${through}, ${counts} so far, ${time}.`
    }
    case 'completed':
      return `${minute(run.started)}, ${counts}, replacing ${run.deleted}.`
    case 'failed': {
      const [first = ''] = (run.exception ?? 'unknown error').split('\n')
      const shown =
        first.length > exceptionLength ? `${first.slice(0, exceptionLength - 3)}...` : first
      return `${minute(run.started)}, failed: ${shown}`
    }
  }
}

/** Whether a playback is still going, which keeps the listing polled. */
export function isPlaybackRunning(runs: PlaybackRecord[] | undefined): boolean {
  return runs?.some((run) => run.state === 'running') ?? false
}

/** The form a playback asks for. */
export function playbackSchema(): SchemaObject {
  return {
    type: 'object',
    description:
      'Replaces the stored particles in the range with ones parsed again from stored messages.',
    properties: {
      ...dateRange,
      level: {
        type: 'string',
        title: 'Level',
        enum: ['particles', 'full'],
        default: 'particles',
        description: 'Full also runs every particle listener as if live.',
      },
      export: {
        type: 'boolean',
        title: 'Rebuild Exporter Files',
        default: false,
      },
      on_export_conflict: {
        ...conflictSchema('Existing Files'),
        description: 'Applies only when rebuilding exporter files.',
      },
      export_range_mode: {
        ...rangeModeSchema('Range Mode'),
        description:
          'Applies only when rebuilding exporter files. Expand widens the playback to the ' +
          'whole files it touches, so the files hold every particle it parses.',
      },
    },
    required: ['after'],
  }
}

/** The request a playback form's values send. */
export function playbackRequest(values: {
  after: string
  before?: string | null
  level?: PlaybackLevel
  export?: boolean
  on_export_conflict?: ExportConflict
  export_range_mode?: ExportRangeMode
}): PlaybackRequest {
  const request: PlaybackRequest = {
    after: values.after,
    before: values.before ?? null,
    level: values.level ?? 'particles',
    export: values.export ?? false,
  }
  if (request.export) {
    request.on_export_conflict = values.on_export_conflict ?? 'overwrite'
    request.export_range_mode = values.export_range_mode ?? 'expand'
  }

  return request
}
