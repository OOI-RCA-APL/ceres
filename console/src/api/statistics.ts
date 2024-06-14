import { Address } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { LevelModel } from '@/api/shared'
import { getter } from '@/getter'
import { usePreferences } from '@/preferences'
import { useQuery } from '@tanstack/vue-query'
import moment from 'moment'
import { defineStore } from 'pinia'
import { computed } from 'vue'
import Zod from 'zod'

export type LevelStatistics = Zod.infer<typeof LevelStatisticsModel>
export const LevelStatisticsModel = Zod.object({
  level: LevelModel,
  count: Zod.number(),
})

export type AlertStatistics = Zod.infer<typeof AlertStatisticsModel>
export const AlertStatisticsModel = Zod.object({
  count: Zod.number(),
  levels: Zod.array(LevelStatisticsModel),
})

export type Statistics = Zod.infer<typeof StatisticsModel>
export const StatisticsModel = Zod.object({
  address: Zod.string().transform(Address.parse),
  alerts: AlertStatisticsModel,
})

export const useStatistics = defineStore('statistics', () => {
  const client = useClient()
  const auth = useAuth()
  const preferences = usePreferences()

  async function getAll(filter: { after?: string; before?: string }): Promise<Statistics[]> {
    return await client.get(`/api/statistics`, {
      query: filter,
      parse: Zod.array(StatisticsModel),
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

      return await getAll({ after: moment.utc().subtract(preferences.statisticsDuration).format() })
    },
    refetchInterval: moment.duration(15, 's').asMilliseconds(),
  })

  const mapping = $computed(() => {
    if (query.data.value == null) {
      return {}
    }

    return Object.fromEntries(
      query.data.value.map((statistics) => [statistics.address.toString(), statistics])
    )
  })

  const get = getter($$(mapping), (address: Address) => {
    return mapping[address.toString()] ?? null
  })

  const getLevel = getter(get, (address: Address) => {
    const statistics = get.value(address)
    if (statistics == null) {
      return null
    }

    return statistics.alerts.levels[statistics.alerts.levels.length - 1] ?? null
  })

  return {
    ...query,
    get,
    getLevel,
  }
})
