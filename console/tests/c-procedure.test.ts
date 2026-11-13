import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import { Address } from '@/api/address'
import { ProcedureInfoModel } from '@/api/components'
import CProcedure from '@/components/c-procedure.vue'

const calls = vi.hoisted(() => ({ signals: [] as AbortSignal[] }))
const access = vi.hoisted(() => ({ level: 'operate' as string | null }))
vi.mock('@/api/access', () => ({
  useAccess: () => ({ levelFor: () => access.level }),
}))
vi.mock('@/api/engine', () => ({
  useEngine: () => ({
    components: {
      call: (
        _address: unknown,
        _name: string,
        _args: unknown,
        { signal }: { signal: AbortSignal },
      ) => {
        calls.signals.push(signal)
        return new Promise((_, reject) =>
          signal.addEventListener('abort', () => reject(signal.reason)),
        )
      },
    },
  }),
}))

// Offers the form's submit and the "Abort" the page passes, as buttons to press, and shows why
// submitting is unavailable.
const Controls = defineComponent({
  props: {
    form: { type: Object, required: true },
    cancelLabel: { type: String, default: undefined },
    unavailableReason: { type: String, default: undefined },
  },
  emits: ['cancel'],
  setup(props, { emit }) {
    return () =>
      h('div', [
        h('button', {
          class: 'submit',
          disabled: props.unavailableReason != null,
          title: props.unavailableReason,
          onClick: () => (props.form as { submit(): void }).submit(),
        }),
        props.cancelLabel == null
          ? null
          : h('button', { class: 'abort', onClick: () => emit('cancel') }, props.cancelLabel),
      ])
  },
})

const procedure = ProcedureInfoModel.parse({
  name: 'hold',
  type: 'action',
  live: false,
  permissions: 'operate',
  arguments: { json_schema: { type: 'object', properties: {} }, required: false },
  output: { type: 'value', json_schema: {} },
})

function mounted(level: string | null = 'operate') {
  calls.signals = []
  access.level = level
  setActivePinia(createPinia())
  return mount(CProcedure, {
    props: { address: Address.parse('@device'), procedure },
    global: {
      stubs: {
        'c-schema-form': true,
        'c-schema-form-controls': Controls,
        'c-procedure-output': true,
        'c-text': true,
        'c-description': true,
      },
    },
  })
}

async function running() {
  const page = mounted()
  await page.find('.submit').trigger('click')
  await flushPromises()
  return page
}

describe('c-procedure', () => {
  it('disables executing a procedure the user cannot invoke', () => {
    const page = mounted('view')

    expect(page.find('.submit').attributes('disabled')).toBeDefined()
    expect(page.find('.submit').attributes('title')).toBe('Not available with your access.')
  })

  it('offers "Abort" while a call runs, which aborts the request', async () => {
    const page = await running()

    await page.find('.abort').trigger('click')
    await flushPromises()

    expect(calls.signals[0]!.aborted).toBe(true)
    expect(page.find('.abort').exists()).toBe(false)
  })

  it('aborts the call when the page goes', async () => {
    const page = await running()

    page.unmount()

    expect(calls.signals[0]!.aborted).toBe(true)
  })
})
