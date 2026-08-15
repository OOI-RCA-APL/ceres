import { describe, expect, it } from 'vitest'

import { Address } from '@/api/address'
import type { Status } from '@/api/statuses'
import { componentCount, countStatuses } from '@/statuses'

function status(running: boolean, enabled: boolean): Status {
  return {
    address: Address.parse('@one'),
    running,
    enabled,
    connections: [],
  }
}

describe('counting the statuses a badge covers', () => {
  it('reports nothing for an empty scope', () => {
    const counts = countStatuses([])
    expect(counts.total).toBe(0)
    expect(counts.allRunning).toBe(false)
    expect(counts.someRunning).toBe(false)
    expect(counts.anyRunning).toBe(false)
  })

  it('skips a component the engine has no status for', () => {
    expect(countStatuses([{ status: null, operable: true }]).total).toBe(0)
  })

  it('counts running and stopped against the operable total', () => {
    const counts = countStatuses([
      { status: status(true, true), operable: true },
      { status: status(false, true), operable: true },
      { status: status(false, false), operable: true },
    ])

    expect(counts).toMatchObject({
      total: 3,
      running: 1,
      stopped: 2,
      enabled: 2,
      disabled: 1,
      someRunning: true,
      allRunning: false,
      someEnabled: true,
      allEnabled: false,
    })
  })

  it('holds a component the user cannot operate out of the counts', () => {
    const counts = countStatuses([
      { status: status(true, true), operable: true },
      { status: status(true, true), operable: false },
    ])

    expect(counts.total).toBe(1)
    expect(counts.allRunning).toBe(true)
  })

  // The badge reports what is live even where the user may only look, so the flags cover the whole
  // scope while the counts cover what an action would reach.
  it('still reports a component the user cannot operate as live', () => {
    const counts = countStatuses([{ status: status(true, true), operable: false }])

    expect(counts.total).toBe(0)
    expect(counts.anyRunning).toBe(true)
    expect(counts.anyEnabled).toBe(true)
    expect(counts.someRunning).toBe(false)
  })

  it('calls everything running only once every operable component is', () => {
    const running = { status: status(true, false), operable: true }
    expect(countStatuses([running, running]).allRunning).toBe(true)
    expect(
      countStatuses([running, { status: status(false, false), operable: true }]).allRunning,
    ).toBe(false)
  })
})

describe('naming how many components an action affected', () => {
  it('reads singular for one and plural for anything else', () => {
    expect(componentCount(1)).toBe('1 component')
    expect(componentCount(0)).toBe('0 components')
    expect(componentCount(4)).toBe('4 components')
  })
})
