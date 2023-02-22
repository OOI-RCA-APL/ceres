import { usePersisted } from '@/persistence'
import { MaybeRef } from '@vueuse/core'
import { computed, inject, InjectionKey, isRef, provide, reactive, watchEffect } from 'vue'
import Zod from 'zod'

type PanelGroupContext = ReturnType<typeof createPanelGroup>

const injectionKey: InjectionKey<PanelGroupContext> = Symbol('panel-group')

type PanelGroupOptions = {
  panels?: string[]
  defaultHeight?: number
  persistenceKey?: string
}

const PanelGroupStateSchema = Zod.object({
  selected: Zod.array(Zod.string()).default(() => []),
  height: Zod.number().nullable().default(null),
})

function createPanelGroup(options?: MaybeRef<PanelGroupOptions>) {
  const reactiveOptions = isRef(options) ? options : computed(() => options ?? {})
  const state = usePersisted({
    schema: PanelGroupStateSchema,
    methods: computed(() =>
      reactiveOptions.value.persistenceKey
        ? [{ type: 'local-storage', key: reactiveOptions.value.persistenceKey }]
        : []
    ),
  })

  if (reactiveOptions.value.defaultHeight != null && state.height == null) {
    state.height = reactiveOptions.value.defaultHeight
  }

  watchEffect(() => {
    if (reactiveOptions.value.panels != null) {
      state.selected = state.selected.filter((current) =>
        reactiveOptions.value.panels?.includes(current)
      )
    }
  })

  function select(panel: string) {
    if (state.selected.includes(panel)) {
      return
    }

    state.selected = [...state.selected, panel]
  }

  function deselect(panel: string) {
    if (state.selected.includes(panel)) {
      state.selected = state.selected.filter((current) => current !== panel)
    }
  }

  function isSelected(panel: string) {
    return state.selected.includes(panel)
  }

  function toggle(panel: string) {
    if (isSelected(panel)) {
      deselect(panel)
    } else {
      select(panel)
    }
  }

  return reactive({
    selected: computed(() => [...state.selected]),
    height: computed({ get: () => state.height, set: (value) => (state.height = value) }),
    select,
    deselect,
    toggle,
    isSelected,
  })
}

export function providePanelGroup(options?: MaybeRef<PanelGroupOptions>) {
  const group = createPanelGroup(options)
  provide(injectionKey, group)
  return group
}

export function usePanelGroup(options?: MaybeRef<PanelGroupOptions>) {
  return inject(injectionKey, null) ?? providePanelGroup(options)
}
