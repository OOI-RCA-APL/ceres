import { Address } from '@/address'
import { useAuth } from '@/api/auth'
import { LevelModel, createQueryParams, get } from '@/api/shared'
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

export async function getStatistics(params: {
  within?: number
  after?: string
  before?: string
}): Promise<Statistics[]> {
  return await get(`/api/statistics${createQueryParams(params)}`, Zod.array(StatisticsModel))
}

export const useStatistics = defineStore('statistics', () => {
  const auth = useAuth()
  const preferences = usePreferences()

  const query = useQuery({
    queryKey: ['statistics', auth.user?.id ?? null, preferences.statisticsDuration.asSeconds()],
    queryFn: async () => {
      if (auth.user == null) {
        return []
      }

      return await getStatistics({ within: preferences.statisticsDuration.asSeconds() })
    },
    refetchInterval: moment.duration(15, 's').asMilliseconds(),
  })

  const mapping = computed(() => {
    if (query.data.value == null) {
      return {}
    }

    return Object.fromEntries(
      query.data.value.map((statistics) => [statistics.address.toString(), statistics])
    )
  })

  const get = getter(mapping, function getStatistics(address: Address): Statistics | null {
    return mapping.value[address.toString()] ?? null
  })

  const getLevel = getter(get, function getAlertLevel(address: Address): LevelStatistics | null {
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
