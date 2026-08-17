import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick, onMounted, ref } from 'vue'

import CRecordViewCell from '@/components/c-record-view-cell.vue'
import { orderedHiddenColumns, provideRecordViewContext, useRecordViewContext } from '@/record-view'
import type { RecordViewContext } from '@/record-view'

/** A row registering itself as the header's reference, which is how a record's own row behaves. */
const Row = defineComponent({
  setup() {
    const context = useRecordViewContext()
    const element = ref<HTMLElement | null>(null)
    onMounted(() => context.register(element.value!))

    return () =>
      h('tr', { ref: element }, [
        h(CRecordViewCell, { name: 'timestamp', class: 'when' }, () => h('span', 'now')),
        h(CRecordViewCell, { name: 'data' }, () => h('span', 'payload')),
      ])
  },
})

/** A row of two cells over a hidden set the test owns, standing in for a record view. */
function mountRow(hidden: ReturnType<typeof ref<string[]>>) {
  let context: RecordViewContext | null = null

  const host = defineComponent({
    setup() {
      context = provideRecordViewContext(() => hidden.value ?? [])
      return () => h('table', [h('tbody', [h(Row)])])
    },
  })

  const wrapper = mount(host)
  return { wrapper, context: context! }
}

describe('hidden column ordering', () => {
  const columns = [{ name: 'timestamp' }, { name: 'address' }, { name: 'level' }, { name: 'data' }]

  it('stores one set of columns one way whatever order they were hidden in', () => {
    expect(orderedHiddenColumns(columns, ['data', 'level'])).toEqual(['level', 'data'])
    expect(orderedHiddenColumns(columns, ['level', 'data'])).toEqual(['level', 'data'])
  })

  it('drops a name that no longer names a column', () => {
    expect(orderedHiddenColumns(columns, ['direction', 'level'])).toEqual(['level'])
  })

  it('leaves an already ordered set alone', () => {
    expect(orderedHiddenColumns(columns, [])).toEqual([])
    expect(orderedHiddenColumns(columns, ['timestamp', 'data'])).toEqual(['timestamp', 'data'])
  })
})

describe('record view columns', () => {
  it('draws every cell while nothing is hidden', () => {
    const { wrapper } = mountRow(ref([]))
    expect(wrapper.findAll('td')).toHaveLength(2)
  })

  it('passes a cell its class through', () => {
    const { wrapper } = mountRow(ref([]))
    expect(wrapper.findAll('td')[0]!.classes()).toContain('when')
  })

  // The header sizes each column from the cell at the same position, so a hidden column has to
  // leave the row rather than render empty.
  it('drops a hidden column out of the row', async () => {
    const hidden = ref<string[]>([])
    const { wrapper } = mountRow(hidden)

    hidden.value = ['timestamp']
    await nextTick()

    const cells = wrapper.findAll('td')
    expect(cells).toHaveLength(1)
    expect(cells[0]!.text()).toBe('payload')
  })

  it('brings a column back', async () => {
    const hidden = ref<string[]>(['data'])
    const { wrapper } = mountRow(hidden)
    expect(wrapper.findAll('td')).toHaveLength(2 - 1)

    hidden.value = []
    await nextTick()
    expect(wrapper.findAll('td')).toHaveLength(2)
  })

  // Hiding a column leaves the row exactly as wide, so nothing else asks the header to remeasure
  // and it would go on sizing each column from the one that used to follow it.
  it('remeasures once the hidden cell is out of the row', async () => {
    const hidden = ref<string[]>([])
    const { context } = mountRow(hidden)
    expect(context.getColumnWidth(1)).not.toBeNull()

    hidden.value = ['timestamp']
    await flushPromises()

    expect(context.getColumnWidth(1)).toBeNull()
    expect(context.getColumnWidth(0)).not.toBeNull()
  })
})
