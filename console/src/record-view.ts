import { computed, inject, onMounted, onUnmounted, provide, reactive } from 'vue'

import { getter } from '@/getter'
import { recordViewContextInjectionKey } from '@/symbols'

export type RecordViewContext = ReturnType<typeof createRecordViewContext>

function createRecordViewContext() {
  let columnWidths = $shallowRef([] as number[])
  let referenceRecord: HTMLElement | null = null
  const records = new Set<HTMLElement>()
  const observer = new ResizeObserver(() => {
    updateColumnWidths()
  })

  onMounted(() => {
    updateObserver()
    updateColumnWidths()
  })

  onUnmounted(() => {
    observer.disconnect()
  })

  function updateColumnWidths() {
    if (referenceRecord == null) {
      columnWidths = []
    } else {
      columnWidths = Array.from(referenceRecord.querySelectorAll('td')).map(
        (td) => td.getBoundingClientRect().width
      )
    }
  }

  function updateObserver() {
    if (referenceRecord != null) {
      if (!records.has(referenceRecord)) {
        if (referenceRecord != null) {
          observer.unobserve(referenceRecord)
        }
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

  return reactive({
    headerWidth: computed(() => columnWidths.reduce((previous, current) => previous + current, 0)),
    getColumnWidth: getter($$(columnWidths), (index: number) => {
      return columnWidths[index] ?? null
    }),
    register,
    unregister,
  })
}

export function provideRecordViewContext() {
  const context = createRecordViewContext()
  provide(recordViewContextInjectionKey, context)
  return context
}

export function useRecordViewContext() {
  const instance = inject(recordViewContextInjectionKey, null)
  if (instance == null) {
    throw Error(`missing inject for ${recordViewContextInjectionKey}`)
  }

  return instance
}
