import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Router } from 'vue-router'
import * as z from 'zod'

import { usePersisted } from '@/persistence'

function at(search: string) {
  window.history.replaceState({}, '', `/components/@scpr${search}`)
}

/** A router that only records where it was asked to go, which is all the URL method uses. */
function recordingRouter() {
  const replace = vi.fn()
  return { router: { replace } as unknown as Router, replace }
}

const schema = z.object({
  workspace: z.array(z.string()).default([]),
  tab: z.string().default(''),
  depth: z.number().default(0),
})

function read(search: string) {
  at(search)
  const { router } = recordingRouter()
  return usePersisted({ schema, methods: [{ type: 'url', router }] })
}

describe('url persistence', () => {
  beforeEach(() => {
    at('')
  })

  it('reads one appearance of a list key as a single entry', () => {
    expect(read('?workspace=w1').workspace).toEqual(['w1'])
  })

  it('reads a repeated key as every entry it names', () => {
    expect(read('?workspace=w1&workspace=w2').workspace).toEqual(['w1', 'w2'])
  })

  it('leaves a list empty when the key is absent', () => {
    expect(read('?tab=main').workspace).toEqual([])
  })

  // A comma belongs to the value, the key being repeated instead, so an identifier carrying one
  // survives the round trip rather than splitting into two.
  it('keeps a value carrying a comma whole', () => {
    expect(read('?workspace=a%2Cb').workspace).toEqual(['a,b'])
  })

  it('writes a list as one appearance of the key per entry', () => {
    at('')
    const { router, replace } = recordingRouter()
    const data = usePersisted({ schema, methods: [{ type: 'url', router }] })

    data.workspace = ['w1', 'w2']
    return vi.waitFor(() => {
      const written = replace.mock.calls.at(-1)?.[0] as string
      expect(written).toContain('workspace=w1')
      expect(written).toContain('workspace=w2')
      expect(written).not.toContain('%2C')
    })
  })

  it('takes an emptied list back out of the address', () => {
    at('?workspace=w1&tab=main')
    const { router, replace } = recordingRouter()
    const data = usePersisted({ schema, methods: [{ type: 'url', router }] })
    expect(data.workspace).toEqual(['w1'])

    data.workspace = []
    return vi.waitFor(() => {
      const written = replace.mock.calls.at(-1)?.[0] as string
      expect(written).not.toContain('workspace')
      expect(written).toContain('tab=main')
    })
  })
})
