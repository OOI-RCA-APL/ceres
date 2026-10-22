import { describe, expect, it } from 'vitest'

import {
  describeExporter,
  describeExportRun,
  describeExportRunFailure,
  describePlayback,
  describePlaybackFailure,
  type ExporterInfo,
  type ExportRunSummary,
  exportRunRequest,
  exportRunSchema,
  isExportRunning,
  isPlaybackRunning,
  type PlaybackRecord,
  playbackRequest,
} from '@/api/exporters'
import { Failure } from '@/errors'

function exporter(overrides: Partial<ExporterInfo> = {}): ExporterInfo {
  return {
    name: 'abc',
    exports: 'message',
    type: null,
    format: 'csv',
    merges: true,
    directory: 'output',
    period: 'hour',
    path: '%Y/%m/%d/%H',
    live: false,
    interval: 'PT5S',
    schedule: null,
    lookback: null,
    next_run: null,
    last_run: null,
    ...overrides,
  }
}

function run(overrides: Partial<ExportRunSummary> = {}): ExportRunSummary {
  return {
    id: '1',
    after: '2026-01-01T00:00:00Z',
    before: '2026-01-01T03:00:00Z',
    replace: false,
    state: 'completed',
    started: '2026-01-02T04:05:06Z',
    ended: '2026-01-02T04:05:07Z',
    count: 12,
    file_count: 2,
    exception: null,
    ...overrides,
  }
}

function failure(error: Record<string, unknown>): Failure {
  return new Failure({ __error__: true, type: 'validation-failed-error', ...error })
}

describe('describeExporter', () => {
  it('names the records, the format, and where the files go', () => {
    expect(describeExporter(exporter())).toBe(
      'Writes message records as csv, one file per hour at output/%Y/%m/%d/%H.',
    )
  })

  it('names a particle type and one file for all time', () => {
    expect(describeExporter(exporter({ exports: 'particle', type: 'abcd', period: 'all' }))).toBe(
      'Writes particle "abcd" records as csv, one file at output/%Y/%m/%d/%H.',
    )
  })

  it('reads a hyphenated kind as words', () => {
    expect(describeExporter(exporter({ exports: 'log-entry' }))).toMatch(/^Writes log entry/)
  })

  it('says live and the schedule with its lookback', () => {
    expect(describeExporter(exporter({ live: true, schedule: 'every hour', lookback: 2 }))).toMatch(
      / Live\. Schedule "every hour", covering 2 periods back\.$/,
    )
  })
})

describe('describeExportRun', () => {
  it('says a never-run exporter never ran', () => {
    expect(describeExportRun(null)).toBe('Never run.')
  })

  it('counts what a running run wrote so far', () => {
    expect(describeExportRun(run({ state: 'running', count: 1 }))).toBe('Running, 1 record so far.')
  })

  it('says when a completed run started and what it wrote', () => {
    expect(describeExportRun(run())).toBe('2026-01-02 04:05 UTC, 12 records in 2 files.')
  })

  it('shows a failed run the first line of its exception, truncated', () => {
    const exception = `${'x'.repeat(200)}\nsecond`
    expect(describeExportRun(run({ state: 'failed', exception }))).toBe(
      `2026-01-02 04:05 UTC, failed: ${'x'.repeat(117)}...`,
    )
  })
})

describe('isExportRunning', () => {
  it('holds while any last run is running', () => {
    expect(isExportRunning([exporter(), exporter({ last_run: run({ state: 'running' }) })])).toBe(
      true,
    )
  })

  it('stops once every run has ended or none exist', () => {
    expect(isExportRunning([exporter({ last_run: run() })])).toBe(false)
    expect(isExportRunning(undefined)).toBe(false)
  })
})

describe('exportRunSchema', () => {
  it('asks a merging format for a range and whether to replace', () => {
    const schema = exportRunSchema(true)
    expect(Object.keys(schema.properties ?? {})).toEqual(['after', 'before', 'replace'])
    expect(schema.required).toEqual(['after'])
  })

  it('offers a format that cannot merge no choice and says why', () => {
    const schema = exportRunSchema(false)
    expect(Object.keys(schema.properties ?? {})).toEqual(['after', 'before'])
    expect(schema.description).toBe('This format rewrites files from the database.')
  })
})

describe('exportRunRequest', () => {
  it('sends an empty end as now and replace as chosen', () => {
    expect(exportRunRequest({ after: 'a', replace: true }, true)).toEqual({
      after: 'a',
      before: null,
      replace: true,
    })
  })

  it('always replaces for a format that cannot merge', () => {
    expect(exportRunRequest({ after: 'a', before: 'b' }, false)).toEqual({
      after: 'a',
      before: 'b',
      replace: true,
    })
  })
})

describe('describeExportRunFailure', () => {
  it('shows the problems the server found', () => {
    expect(
      describeExportRunFailure(
        failure({ problems: [{ message: '`after` must precede `before`' }] }),
      ),
    ).toBe('`after` must precede `before`')
  })

  it('names a stopped component and a queued run', () => {
    expect(describeExportRunFailure(failure({ type: 'not-running-error' }))).toBe(
      'The component is not running.',
    )
    expect(describeExportRunFailure(failure({ type: 'already-exists-error' }))).toBe(
      'A run of this exporter already waits for another.',
    )
  })
})

function playback(overrides: Partial<PlaybackRecord> = {}): PlaybackRecord {
  return {
    id: '1',
    after: '2026-01-01T00:00:00Z',
    before: '2026-01-01T03:00:00Z',
    level: 'particles',
    export: true,
    state: 'completed',
    started: '2026-01-02T04:05:06Z',
    ended: '2026-01-02T04:05:07Z',
    deleted: 3,
    messages: 1,
    particles: 2,
    export_runs: [],
    exception: null,
    ...overrides,
  }
}

describe('describePlayback', () => {
  it('says a component never played back', () => {
    expect(describePlayback(undefined)).toBe('Never played back.')
  })

  it('counts what a playback replayed and replaced', () => {
    expect(describePlayback(playback())).toBe(
      '2026-01-02 04:05 UTC, 1 message into 2 particles, replacing 3.',
    )
    expect(describePlayback(playback({ state: 'running' }))).toBe(
      'Playing back, 1 message into 2 particles so far.',
    )
  })

  it('shows a failed playback the first line of its exception', () => {
    expect(describePlayback(playback({ state: 'failed', exception: 'abc\ndef' }))).toBe(
      '2026-01-02 04:05 UTC, failed: abc',
    )
  })
})

describe('isPlaybackRunning', () => {
  it('polls only while a playback runs', () => {
    expect(isPlaybackRunning(undefined)).toBe(false)
    expect(isPlaybackRunning([playback()])).toBe(false)
    expect(isPlaybackRunning([playback({ state: 'running' })])).toBe(true)
  })
})

describe('playbackRequest', () => {
  it('sends now for an empty end and defaults the level and export', () => {
    expect(playbackRequest({ after: 'a' })).toEqual({
      after: 'a',
      before: null,
      level: 'particles',
      export: true,
    })
  })
})

describe('describePlaybackFailure', () => {
  it('names a missing manage access and a running playback', () => {
    expect(describePlaybackFailure(failure({ type: 'not-permitted-error' }))).toBe(
      'A playback needs manage access.',
    )
    expect(describePlaybackFailure(failure({ type: 'already-exists-error' }))).toBe(
      'A playback of this component already runs.',
    )
  })
})
