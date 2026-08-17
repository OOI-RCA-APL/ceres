import { beforeEach, describe, expect, it } from 'vitest'

import { createRecordFeed } from '@/records/feed'
import type { RecordFeed } from '@/records/feed'

type TestRecord = { id: string; address: string; timestamp: string }

function record(id: string, timestamp: string): TestRecord {
  return { id, address: '@sensor', timestamp }
}

let clock: number
let filter: Record<string, unknown>
let responses: TestRecord[][]
let requests: Record<string, unknown>[]
let feed: RecordFeed<TestRecord>

beforeEach(() => {
  clock = 0
  filter = {}
  responses = []
  requests = []
  feed = createRecordFeed<TestRecord>({
    getAll: async (requested) => {
      requests.push(requested)
      return responses.shift() ?? []
    },
    filter: () => filter,
    pageSize: () => 100,
    now: () => clock,
  })
})

describe('loadCurrent', () => {
  it('loads the newest page oldest-first', async () => {
    responses.push([record('b', '2026-01-02'), record('a', '2026-01-01')])
    await feed.loadCurrent()

    expect(feed.rows.map((row) => row.id)).toEqual(['a', 'b'])
    expect(feed.isLoadingCurrent.value).toBe(false)
    expect(requests[0]).toMatchObject({ order: 'timestamp:desc', limit: 100 })
  })

  it('marks exhaustion on an empty result', async () => {
    responses.push([])
    await feed.loadCurrent()

    expect(feed.isExhausted.value).toBe(true)
  })

  // The host reads its filter from a computed, which builds a fresh object every time it
  // recomputes, and a workspace still settling recomputes it to the same value. Compared by
  // identity that reads as a filter change, and the first page is thrown away with nothing left
  // to ask for it again.
  it('keeps the page when the filter recomputed to an equal value', async () => {
    feed = createRecordFeed<TestRecord>({
      getAll: async (requested) => {
        requests.push(requested)
        return responses.shift() ?? []
      },
      filter: () => ({ address: '@sensor' }),
      pageSize: () => 100,
      now: () => clock,
    })

    responses.push([record('b', '2026-01-02'), record('a', '2026-01-01')])
    await feed.loadCurrent()

    expect(feed.rows.map((row) => row.id)).toEqual(['a', 'b'])
  })

  it('discards the page when the filter genuinely changed while it was in flight', async () => {
    responses.push([record('b', '2026-01-02'), record('a', '2026-01-01')])

    const loading = feed.loadCurrent()
    filter = { address: '@other' }
    await loading

    expect(feed.rows).toEqual([])
  })

  it('folds in records that streamed during the fetch, without duplicates', async () => {
    responses.push([record('a', '2026-01-01'), record('b', '2026-01-02')].reverse())

    const loading = feed.loadCurrent()
    feed.receive(record('b', '2026-01-02'), false)
    feed.receive(record('c', '2026-01-03'), false)
    await loading

    expect(feed.rows.map((row) => row.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('append and receive', () => {
  it('dedups by record ID', () => {
    feed.append([record('a', '2026-01-01')])
    const fresh = feed.append([record('a', '2026-01-01'), record('b', '2026-01-02')])

    expect(fresh.map((row) => row.id)).toEqual(['b'])
    expect(feed.rows).toHaveLength(2)
  })

  it('resorts when an arrival lands out of order', () => {
    feed.append([record('b', '2026-01-02')])
    feed.append([record('a', '2026-01-01')])

    expect(feed.rows.map((row) => row.id)).toEqual(['a', 'b'])
  })

  it('holds arrivals when asked and flushes them later', async () => {
    responses.push([])
    await feed.loadCurrent()

    expect(feed.receive(record('a', '2026-01-01'), true)).toBe('held')
    expect(feed.rows).toHaveLength(0)
    expect(feed.pendingCount.value).toBe(1)

    const flushed = feed.flushPending()
    expect(flushed.map((row) => row.id)).toEqual(['a'])
    expect(feed.pendingCount.value).toBe(0)
  })
})

describe('fetchPrevious and placePrevious', () => {
  async function loaded(rows: TestRecord[]) {
    responses.push([...rows].reverse())
    await feed.loadCurrent()
    clock += 2000
  }

  it('fetches the page above the oldest held record into the buffer', async () => {
    await loaded([record('c', '2026-01-03')])

    responses.push([record('b', '2026-01-02'), record('a', '2026-01-01')])
    await feed.fetchPrevious()

    expect(requests[1]).toMatchObject({ before: '2026-01-03' })
    expect(feed.bufferedCount.value).toBe(2)
    expect(feed.rows).toHaveLength(1)

    const placed = feed.placePrevious()
    expect(placed).toBe(2)
    expect(feed.rows.map((row) => row.id)).toEqual(['a', 'b', 'c'])
  })

  it('rate limits against the newest and previous loads', async () => {
    responses.push([record('a', '2026-01-01')])
    await feed.loadCurrent()

    // Too soon after the newest load.
    await feed.fetchPrevious()
    expect(requests).toHaveLength(1)

    clock += 2000
    responses.push([record('b', '2025-12-31')])
    await feed.fetchPrevious()
    expect(requests).toHaveLength(2)
    feed.placePrevious()

    // Too soon after the previous fetch.
    await feed.fetchPrevious()
    expect(requests).toHaveLength(2)
  })

  it('does not fetch again while the buffer holds records', async () => {
    await loaded([record('c', '2026-01-03')])

    responses.push([record('b', '2026-01-02')])
    await feed.fetchPrevious()
    clock += 2000

    await feed.fetchPrevious()
    expect(requests).toHaveLength(2)
  })

  it('stops fetching once exhausted', async () => {
    await loaded([record('c', '2026-01-03')])

    responses.push([])
    await feed.fetchPrevious()
    expect(feed.isExhausted.value).toBe(true)

    clock += 2000
    await feed.fetchPrevious()
    expect(requests).toHaveLength(2)
  })

  it('dedups an older page against what is already held', async () => {
    await loaded([record('b', '2026-01-02'), record('c', '2026-01-03')])

    responses.push([record('b', '2026-01-02'), record('a', '2026-01-01')])
    await feed.fetchPrevious()
    feed.placePrevious()

    expect(feed.rows.map((row) => row.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('cull and reset', () => {
  it('drops the oldest rows down to the keep count', () => {
    feed.append([record('a', '2026-01-01'), record('b', '2026-01-02'), record('c', '2026-01-03')])

    expect(feed.cull(1)).toBe(2)
    expect(feed.rows.map((row) => row.id)).toEqual(['c'])

    // Membership rebuilt, so a culled record can come back.
    const fresh = feed.append([record('a', '2026-01-01')])
    expect(fresh).toHaveLength(1)
  })

  it('reset drops rows, buffers, and exhaustion', async () => {
    responses.push([])
    await feed.loadCurrent()
    feed.receive(record('a', '2026-01-01'), true)
    feed.reset()

    expect(feed.rows).toHaveLength(0)
    expect(feed.pendingCount.value).toBe(0)
    expect(feed.isExhausted.value).toBe(false)
    expect(feed.isLoadingCurrent.value).toBe(true)
  })
})
