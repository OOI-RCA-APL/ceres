import { defineStore } from 'pinia'
import { computed } from 'vue'
import * as z from 'zod'

import { type Address, AddressModel } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient, useQuery } from '@/api/client'
import { LevelModel } from '@/api/shared'
import { usePreferences } from '@/preferences'
import { duration, utc } from '@/time'

export type LevelStatistics = z.infer<typeof LevelStatisticsModel>
export const LevelStatisticsModel = z.object({
  level: LevelModel,
  count: z.number(),
})

export type AlertStatistics = z.infer<typeof AlertStatisticsModel>
export const AlertStatisticsModel = z.object({
  count: z.number(),
  levels: z.array(LevelStatisticsModel),
})

export type Statistics = z.infer<typeof StatisticsModel>
export const StatisticsModel = z.object({
  address: AddressModel,
  alerts: AlertStatisticsModel,
})

export const useStatistics = defineStore('statistics', () => {
  const client = useClient()
  const auth = useAuth()
  const preferences = usePreferences()

  async function getAll(filter: { after?: string; before?: string }): Promise<Statistics[]> {
    return await client.get('/api/statistics', {
      query: filter,
      parse: z.array(StatisticsModel),
    })
  }

  const query = useQuery({
    queryKey: computed(() => [
      'statistics',
      auth.user?.id ?? null,
      preferences.statisticsDuration.asSeconds(),
    ]),
    queryFn: async () => {
      if (auth.user == null) {
        return []
      }

      return await getAll({ after: utc().subtract(preferences.statisticsDuration).format() })
    },
    refetchInterval: duration(15, 's').asMilliseconds(),
  })

  const mapping = $computed(() => {
    if (query.data.value == null) {
      return {}
    }

    return Object.fromEntries(
      query.data.value.map((statistics) => [statistics.address.toString(), statistics]),
    )
  })

  function get(address: Address) {
    return mapping[address.toString()] ?? null
  }

  function getLevel(address: Address) {
    const statistics = get(address)
    if (statistics == null) {
      return null
    }

    return statistics.alerts.levels[statistics.alerts.levels.length - 1] ?? null
  }

  return {
    ...query,
    get,
    getLevel,
  }
})
