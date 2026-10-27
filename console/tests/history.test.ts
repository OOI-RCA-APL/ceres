import { afterEach, describe, expect, it } from 'vitest'
import { effectScope } from 'vue'

import { useFileHistory } from '@/api/files'
import { createHistory } from '@/history'

function historyOf(values: string[], limit = 10) {
  const history = createHistory<string>({ limit })
  for (const value of values) {
    history.record(value)
  }
  return history
}

describe('createHistory', () => {
  it('goes back and forward through what it recorded', () => {
    const history = historyOf(['a', 'b', 'c'])

    expect(history.back()).toBe('b')
    expect(history.back()).toBe('a')
    expect(history.canBack).toBe(false)
    expect(history.back()).toBeUndefined()
    expect(history.forward()).toBe('b')
    expect(history.canForward).toBe(true)
  })

  it('drops the entries ahead when a new one is recorded', () => {
    const history = historyOf(['a', 'b', 'c'])
    history.back()
    history.back()
    history.record('d')

    expect(history.canForward).toBe(false)
    expect(history.back()).toBe('a')
  })

  it('records nothing for a value equal to the current entry', () => {
    const history = historyOf(['a', 'b'])
    history.record(history.back()!)

    expect(history.forward()).toBe('b')
  })

  it('replaces the current entry and keeps the ones around it', () => {
    const history = historyOf(['a', 'b', 'c'])
    history.back()
    history.replace('d')

    expect(history.forward()).toBe('c')
    expect(history.back()).toBe('d')
    expect(history.back()).toBe('a')
  })

  it('keeps at most its limit, dropping the oldest', () => {
    const history = historyOf(['a', 'b', 'c', 'd'], 3)

    expect(history.back()).toBe('c')
    expect(history.back()).toBe('b')
    expect(history.canBack).toBe(false)
  })

  it('starts over on reset and empties on clear', () => {
    const history = historyOf(['a', 'b'])
    history.reset('c')

    expect(history.canBack).toBe(false)

    history.clear()
    history.record('d')
    expect(history.canBack).toBe(false)
  })

  it('compares and copies with the functions it is given', () => {
    const history = createHistory<string[]>({
      limit: 10,
      equal: (left, right) => left.join('/') === right.join('/'),
      clone: (value) => [...value],
    })
    const first = ['a']
    history.record(first)
    history.record(['a', 'b'])
    first.push('changed')

    expect(history.back()).toEqual(['a'])
  })
})

describe('useFileHistory', () => {
  afterEach(() => localStorage.clear())

  function inScope<T>(run: () => T) {
    const scope = effectScope()
    const result = scope.run(run)!
    return { result, stop: () => scope.stop() }
  }

  it('keeps its places for the next view with the same key', () => {
    const first = inScope(() => useFileHistory('abc'))
    first.result.record({ mount: 'a', path: [] })
    first.result.record({ mount: 'a', path: ['b'] })
    first.stop()

    const next = inScope(() => useFileHistory('abc')).result
    expect(next.back()).toEqual({ mount: 'a', path: [] })
    expect(inScope(() => useFileHistory('abcd')).result.canBack).toBe(false)
  })
})
