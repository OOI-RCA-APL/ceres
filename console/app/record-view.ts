import { computed, inject, nextTick, onMounted, onUnmounted, provide, reactive, watch } from 'vue'

import { recordViewContextInjectionKey } from '@/symbols'

export type RecordViewContext = ReturnType<typeof createRecordViewContext>

/** Column-width sync between a record view's fixed header and its scrolling rows, and which
columns are drawn at all.

The first drawn row is the reference: its cell widths drive the header's, so the header
lines up with content it does not contain. Both sides read visibility from here so a hidden
column leaves neither a cell nor a header behind, which is what keeps the two in step by
position.
*/
function createRecordViewContext(hiddenColumns: () => readonly string[]) {
  let columnWidths = $shallowRef([] as number[])
  let referenceRecord: HTMLElement | null = null
  const records = new Set<HTMLElement>()
  const observer = new ResizeObserver(() => {
    updateColumnWidths()
  })

  const hidden = computed(() => new Set(hiddenColumns()))

  onMounted(() => {
    updateObserver()
    updateColumnWidths()
  })

  // Hiding a column leaves the row as wide as it was, the last column taking the slack, so the
  // observer never fires and the header would go on sizing each column from its neighbour's.
  watch(hidden, async () => {
    await nextTick()
    updateColumnWidths()
  })

  onUnmounted(() => {
    observer.disconnect()
  })

  function updateColumnWidths() {
    if (referenceRecord == null) {
      columnWidths = []
      return
    }

    columnWidths = Array.from(referenceRecord.querySelectorAll('td')).map(
      (td) => td.getBoundingClientRect().width,
    )
  }

  function updateObserver() {
    if (referenceRecord != null) {
      if (!records.has(referenceRecord)) {
        observer.unobserve(referenceRecord)
      }
    }

    for (const record of records) {
      referenceRecord = record
      observer.observe(referenceRecord)
      break
    }
  }

  function register(record: HTMLElement) {
    records.add(record)
    updateObserver()
  }

  function unregister(record: HTMLElement) {
    records.delete(record)
    updateObserver()
  }

  function getColumnWidth(index: number): number | null {
    return columnWidths[index] ?? null
  }

  function isColumnVisible(name: string): boolean {
    return !hidden.value.has(name)
  }

  return reactive({
    headerWidth: computed(() => columnWidths.reduce((previous, current) => previous + current, 0)),
    getColumnWidth,
    isColumnVisible,
    register,
    unregister,
  })
}

export function provideRecordViewContext(hiddenColumns: () => readonly string[]) {
  const context = createRecordViewContext(hiddenColumns)
  provide(recordViewContextInjectionKey, context)
  return context
}

export function useRecordViewContext() {
  const instance = inject(recordViewContextInjectionKey, null)
  if (instance == null) {
    throw Error(`missing inject for ${String(recordViewContextInjectionKey)}`)
  }

  return instance
}
