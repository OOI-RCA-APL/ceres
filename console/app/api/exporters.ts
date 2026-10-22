import { lowerCase } from 'lodash-es'
import * as z from 'zod'

import { Failure } from '@/errors'
import type { SchemaObject } from '@/schema-form'
import { utc } from '@/time'

export type ExportRunState = z.infer<typeof ExportRunStateModel>
export const ExportRunStateModel = z.enum(['running', 'completed', 'failed'])

/** An export run without its file list, which grows with every period it writes. */
export type ExportRunSummary = z.infer<typeof ExportRunSummaryModel>
export const ExportRunSummaryModel = z.object({
  id: z.string(),
  after: z.string(),
  before: z.string(),
  replace: z.boolean(),
  state: ExportRunStateModel,
  started: z.string(),
  ended: z.string().nullable(),
  /** Records written so far. */
  count: z.number(),
  /** Files written so far. */
  file_count: z.number(),
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
  /** Whether a run can merge stored records into a file, else every run replaces it. */
  merges: z.boolean(),
  /** Name of the component's directory field the files live under. */
  directory: z.string(),
  period: ExporterPeriodModel,
  /** The path template, without the extension the format adds. */
  path: z.string(),
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
  replace: boolean
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
  const sentences = [
    `Writes ${what} as ${exporter.format}, ${files} at ${exporter.directory}/${exporter.path}.`,
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

/** How an exporter's last run went, as one line, or that it never ran. */
export function describeExportRun(run: ExportRunSummary | null): string {
  if (run == null) {
    return 'Never run.'
  }

  switch (run.state) {
    case 'running':
      return `Running, ${counted(run.count, 'record')} so far.`
    case 'completed':
      return `${minute(run.started)}, ${counted(run.count, 'record')} in ${counted(run.file_count, 'file')}.`
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

/** The form a rebuild asks for. A format that cannot merge always replaces, so it gets no
choice. */
export function exportRunSchema(merges: boolean): SchemaObject {
  const range: Record<string, SchemaObject> = {
    after: { type: 'string', format: 'date-time', title: 'After' },
    before: {
      type: 'string',
      format: 'date-time',
      title: 'Before',
      description: 'Now when left empty.',
    },
  }
  if (!merges) {
    return {
      type: 'object',
      description: 'This format rewrites files from the database.',
      properties: range,
      required: ['after'],
    }
  }

  return {
    type: 'object',
    properties: {
      ...range,
      replace: { type: 'boolean', title: 'Replace file contents', default: false },
    },
    required: ['after'],
  }
}

/** The request a rebuild form's values send. */
export function exportRunRequest(
  values: { after: string; before?: string | null; replace?: boolean },
  merges: boolean,
): ExportRunRequest {
  return {
    after: values.after,
    before: values.before ?? null,
    replace: merges ? (values.replace ?? false) : true,
  }
}

/** Why the server refused a run, as a sentence. */
export function describeExportRunFailure(error: unknown): string {
  if (!(error instanceof Failure)) {
    return 'The run failed to start.'
  }

  const info = error.error as { type: string; problems?: { message: string }[] }
  switch (info.type) {
    case 'not-running-error':
      return 'The component is not running.'
    case 'not-permitted-error':
      return 'Starting a run needs operate access.'
    case 'already-exists-error':
      return 'A run of this exporter already waits for another.'
  }

  const messages = info.problems?.map((problem) => problem.message) ?? []
  if (messages.length > 0) {
    return messages.join(' ')
  }

  return `The server responded with "${info.type}".`
}
