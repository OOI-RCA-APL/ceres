import { getter } from '@/getter'
import { usePersisted } from '@/persistence'
import { panelGroupInjectionKey } from '@/symbols'
import { asRef, MaybeRef } from '@/utilities'
import { computed, inject, provide, reactive, watchEffect } from 'vue'
import Zod from 'zod'

export type PanelGroup = ReturnType<typeof createPanelGroup>
export type PanelGroupOptions = {
  panels?: string[]
  defaultHeight?: number
  persist?: string
}

const PanelGroupStateSchema = Zod.object({
  selected: Zod.array(Zod.string()).default(() => []),
  height: Zod.number().nullable().default(null),
})

function createPanelGroup(options?: MaybeRef<PanelGroupOptions>) {
  const reactiveOptions = asRef(options ?? {})
  const state = usePersisted({
    schema: PanelGroupStateSchema,
    methods: computed(() =>
      reactiveOptions.value.persist
        ? [{ type: 'local-storage', key: reactiveOptions.value.persist }]
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

  function selectAll() {
    state.selected = [...(reactiveOptions.value.panels ?? [])]
  }

  function deselectAll() {
    state.selected = []
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

  function toggleAll() {
    if (state.selected.length === 0) {
      selectAll()
    } else {
      deselectAll()
    }
  }

  return reactive({
    selected: computed(() => [...state.selected]),
    height: computed({ get: () => state.height, set: (value) => (state.height = value) }),
    select,
    deselect,
    toggle,
    selectAll,
    deselectAll,
    toggleAll,
    isSelected: getter(state, isSelected),
    hasSelected: computed(() => state.selected.length > 0),
  })
}

export function providePanelGroup(options?: MaybeRef<PanelGroupOptions>) {
  const group = createPanelGroup(options)
  provide(panelGroupInjectionKey, group)
  return group
}

export function usePanelGroup() {
  const instance = inject(panelGroupInjectionKey, null)
  if (instance == null) {
    throw Error(`missing inject for ${panelGroupInjectionKey}`)
  }

  return instance
}
