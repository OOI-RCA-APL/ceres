import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useConsoleVersion } from '@/console-version'

const url = '/_nuxt/builds/latest.json'

function serve(...answers: (unknown | Error)[]) {
  const fetch = vi.fn(async () => {
    const answer = answers.shift()
    if (answer instanceof Error) {
      throw answer
    }

    return new Response(JSON.stringify(answer))
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function started() {
  const consoleVersion = useConsoleVersion()
  consoleVersion.start('1.0.0', url)
  return consoleVersion
}

describe('useConsoleVersion', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('stays current while the engine serves the same build', async () => {
    serve({ id: '1.0.0' })
    const consoleVersion = started()

    await consoleVersion.check()

    expect(consoleVersion.served).toBe('1.0.0')
    expect(consoleVersion.outdated).toBe(false)
  })

  it('turns outdated once the engine serves another build', async () => {
    serve({ id: '1.1.0' })
    const consoleVersion = started()

    await consoleVersion.check()

    expect(consoleVersion.outdated).toBe(true)
  })

  it('shares one request between checks made while it runs', async () => {
    const fetch = serve({ id: '1.0.0' })
    const consoleVersion = started()

    await Promise.all([consoleVersion.check(), consoleVersion.check()])

    expect(fetch).toHaveBeenCalledOnce()
    expect(fetch).toHaveBeenCalledWith(url, { cache: 'no-store' })
  })

  it('keeps what it knew when the engine answers nothing usable', async () => {
    serve({ id: '1.0.0' }, new TypeError('offline'), { name: 'abc' })
    const consoleVersion = started()

    await consoleVersion.check()
    await consoleVersion.check()
    await consoleVersion.check()

    expect(consoleVersion.served).toBe('1.0.0')
  })

  it('takes the build Nuxt reports', () => {
    const consoleVersion = started()

    consoleVersion.learn('1.1.0')

    expect(consoleVersion.outdated).toBe(true)
  })

  it('writes while the engine serves this build', async () => {
    const consoleVersion = started()
    consoleVersion.learn('1.0.0')

    expect(await consoleVersion.unlessOutdated(async () => 'abc')).toBe('abc')
  })

  it('skips a write once the engine serves another build', async () => {
    const consoleVersion = started()
    const write = vi.fn(async () => 'abc')
    consoleVersion.learn('1.1.0')

    expect(await consoleVersion.unlessOutdated(write)).toBeNull()
    expect(write).not.toHaveBeenCalled()
  })

  it('checks nothing before it starts', async () => {
    const fetch = serve()

    await useConsoleVersion().check()

    expect(fetch).not.toHaveBeenCalled()
  })
})
