import { defineStore } from 'pinia'
import { computed } from 'vue'
import * as z from 'zod'

/** The part of Nuxt's `builds/latest.json` that names the build an engine serves. */
const ConsoleBuildModel = z.object({ id: z.string() })

/**
Compares the console this page runs with the one the engine serves.

The console's Nuxt build ID is the Ceres version, and the engine serves its own console's
`builds/latest.json`, so the two differ once the engine has been upgraded under an open page. An
outdated page keeps working against an engine it was not built for and can save workspace data it
does not understand, which is why the app asks to reload.
*/
export const useConsoleVersion = defineStore('console-version', () => {
  let running = $ref<string | null>(null)
  let served = $ref<string | null>(null)
  let latestUrl: string | null = null
  let checking: Promise<void> | null = null

  const outdated = $computed(() => running != null && served != null && served !== running)

  /** Start comparing this page's build `version` with the build named at `url`. */
  function start(version: string, url: string) {
    running = version
    latestUrl = url
  }

  async function fetchServed(url: string) {
    try {
      const response = await fetch(url, { cache: 'no-store' })
      if (!response.ok) {
        return
      }

      const build = ConsoleBuildModel.safeParse(await response.json())
      if (build.success) {
        served = build.data.id
      }
    } catch {
      // An engine that is down or restarting answers nothing, and the reconnect that follows
      // checks again.
    }
  }

  /** Ask the engine which build it serves. Calls made while a check runs share it. */
  function check() {
    if (latestUrl == null) {
      return Promise.resolve()
    }

    checking ??= fetchServed(latestUrl).finally(() => {
      checking = null
    })
    return checking
  }

  /** Record the build the engine serves, as Nuxt's own periodic check reports it. */
  function learn(version: string) {
    served = version
  }

  /** Run `write` unless the engine is known to serve another build, since an outdated page can drop
  what a newer console stored. Answers null when skipped. It checks nothing itself, because a
  save on the way out of the page has no time to wait for one. */
  async function unlessOutdated<T>(write: () => Promise<T>): Promise<T | null> {
    return outdated ? null : await write()
  }

  return {
    running: computed(() => running),
    served: computed(() => served),
    outdated: computed(() => outdated),
    start,
    check,
    learn,
    unlessOutdated,
  }
})
