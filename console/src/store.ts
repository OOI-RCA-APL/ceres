import { Address } from '@/address'
import { ComponentInfo, LevelStatistics, Statistics, Status } from '@/api/models'
import {
  getComponent as getComponentBase,
  getConsoleConfig,
  getStatistics as getStatisticsBase,
  useStatusesStream,
} from '@/api/operations'
import { useAuth } from '@/auth'
import { getter } from '@/getter'
import { usePreferences } from '@/preferences'
import { useIntervalFn } from '@vueuse/core'
import moment from 'moment'
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { UseQueryReturnType, useQuery } from 'vue-query'

export const useStore = defineStore('store', () => {
  const auth = useAuth()
  const preferences = usePreferences()

  async function fetchQuery(query: UseQueryReturnType<unknown, unknown>) {
    if (query.isIdle.value) {
      await query.refetch.value()
    } else {
      await query.suspense()
    }
  }

  async function refetchQuery(query: UseQueryReturnType<unknown, unknown>) {
    await query.refetch.value()
  }

  function getUpdatedAt(query: UseQueryReturnType<unknown, unknown>) {
    return query.dataUpdatedAt.value ? Object.freeze(moment.utc(query.dataUpdatedAt.value)) : null
  }

  const configQuery = useQuery(['console-config'], getConsoleConfig, { retry: false })
  const config = computed(() => configQuery.data.value ?? null)

  const configFields = {
    config,
    fetchConfig: () => fetchQuery(configQuery),
    refetchConfig: () => refetchQuery(configQuery),
    isLoadingConfig: computed(() => configQuery.isLoading.value),
  }

  const componentsQuery = useQuery(
    ['components'],
    async () => {
      if (auth.user == null) {
        return null
      }

      return await getComponentBase(new Address('@'))
    },
    {
      retry: false,
    }
  )
  const componentsError = computed(() => componentsQuery.error.value)
  const componentRoot = computed(() => componentsQuery.data.value ?? null)

  const componentMapping = computed<Record<string, ComponentInfo>>(() => {
    if (componentsQuery.data.value == null) {
      return {}
    }

    const componentMapping: Record<string, ComponentInfo> = {}

    function traverse(current: ComponentInfo) {
      componentMapping[current.address.toString()] = current
      for (const child of current.components) {
        traverse(child)
      }
    }

    traverse(componentsQuery.data.value)
    return componentMapping
  })

  const getComponent = getter(
    componentMapping,
    function getComponent(address: Address | string): ComponentInfo | null {
      return componentMapping.value[address.toString()] ?? null
    }
  )

  const getComponents = getter(componentMapping, function getComponents(): ComponentInfo[] {
    return Object.values(componentMapping.value)
  })

  const componentFields = {
    componentRoot,
    componentsError,
    componentsUpdatedAt: computed(() => getUpdatedAt(componentsQuery)),
    getComponent,
    getComponents,
    fetchComponents: () => fetchQuery(componentsQuery),
    refetchComponents: () => refetchQuery(componentsQuery),
    isLoadingComponents: computed(() => componentsQuery.isLoading.value),
  }

  const statisticsQuery = useQuery(
    ['store/statistics'],
    async () => {
      if (auth.user == null) {
        return []
      }

      return await getStatisticsBase({ within: preferences.statisticsDuration.asSeconds() })
    },
    { retry: false }
  )

  const statisticsError = computed(() => statisticsQuery.error.value)

  const statisticsMapping = computed(() => {
    if (statisticsQuery.data.value == null) {
      return {}
    }

    return Object.fromEntries(
      statisticsQuery.data.value.map((statistics) => [statistics.address.toString(), statistics])
    )
  })

  const getStatistics = getter(
    statisticsMapping,
    function getStatistics(address: Address): Statistics | null {
      return statisticsMapping.value[address.toString()] ?? null
    }
  )

  const getStatisticsAlertLevel = getter(
    getStatistics,
    function getAlertLevel(address: Address): LevelStatistics | null {
      const statistics = getStatistics.value(address)
      if (statistics == null) {
        return null
      }

      return statistics.alerts.levels[statistics.alerts.levels.length - 1] ?? null
    }
  )

  useIntervalFn(async () => {
    await statisticsQuery.refetch.value()
  }, moment.duration(15, 's').asMilliseconds())

  watch(
    computed(() => preferences.statisticsDuration.asSeconds()),
    async () => {
      statisticsQuery.refetch.value()
    }
  )

  const statisticsFields = {
    statisticsError,
    statisticsUpdatedAt: computed(() => getUpdatedAt(statisticsQuery)),
    getStatistics,
    getStatisticsAlertLevel,
    fetchStatistics: () => fetchQuery(statisticsQuery),
    refetchStatistics: () => refetchQuery(statisticsQuery),
    isLoadingStatistics: computed(() => statisticsQuery.isLoading.value),
  }

  const statusesMapping = ref<Record<string, Status>>({})

  useStatusesStream(
    {},
    (next) => {
      statusesMapping.value = Object.fromEntries(
        next.map((status) => [status.address.toString(), status])
      )
    },
    computed(() => ({ disable: auth.user == null }))
  )

  const getStatus = getter($$(statusesMapping), function getStatus(address: Address) {
    return statusesMapping.value[address.toString()] ?? null
  })

  const statusFields = {
    getStatus,
  }

  const isLoading = computed(
    () =>
      configQuery.isLoading.value ||
      componentsQuery.isLoading.value ||
      statisticsQuery.isLoading.value
  )

  async function load() {
    await Promise.all([
      fetchQuery(configQuery),
      fetchQuery(componentsQuery),
      fetchQuery(statisticsQuery),
    ])
  }

  watch(
    computed(() => auth.user == null),
    async () => {
      await load()
    }
  )

  return {
    ...configFields,
    ...componentFields,
    ...statisticsFields,
    ...statusFields,
    load,
    isLoading,
  }
})
