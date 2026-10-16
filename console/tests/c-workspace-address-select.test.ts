import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import { Address } from '@/api/address'
import CWorkspaceAddressSelect from '@/components/c-workspace-address-select.vue'

vi.mock('@/api/engine', () => ({
  useEngine: () => ({
    components: {
      all: ['@rig', '@rig.arm', '@other'].map((address) => ({ address: Address.parse(address) })),
    },
  }),
}))

const placement = vi.hoisted(() => ({ scope: '@rig' }))
vi.mock('@/workspace', () => ({
  useWorkspace: () => ({
    scope: Address.parse(placement.scope),
    isBound: placement.scope !== '~',
  }),
}))

// Renders the trigger the way the real menu does, and offers each item to pick by its label.
const SelectMenu = defineComponent({
  props: { items: { type: Array, default: () => [] } },
  emits: ['update:modelValue'],
  setup(props, { emit, slots }) {
    const ui = { value: () => 'value', placeholder: () => 'placeholder' }
    return () =>
      h('div', [
        h('span', { class: 'trigger' }, slots.default?.({ ui })),
        ...(props.items as { label: string }[]).map((item) =>
          h('button', { onClick: () => emit('update:modelValue', item) }, item.label),
        ),
      ])
  },
})

function render(modelValue: string | null, at = '@rig') {
  placement.scope = at
  return mount(CWorkspaceAddressSelect, {
    props: { modelValue },
    global: {
      stubs: { 'c-select-menu': SelectMenu, 'c-text': true, 'c-switch': true, 'c-button': true },
    },
  })
}

function pick(select: ReturnType<typeof render>, label: string) {
  return select
    .findAll('button')
    .find((button) => button.text() === label)!
    .trigger('click')
}

describe('c-workspace-address-select', () => {
  it("shows an unset value as the workspace's component, marked as the default", () => {
    expect(render(null).find('.trigger').text()).toBe('@rig(Default)')
  })

  it('shows the placeholder at the engine root, where there is no default', () => {
    expect(render(null, '~').find('.trigger').text()).toBe('Component')
  })

  it('unsets the value when the default is picked and sets any other', async () => {
    const select = render('arm')
    await pick(select, '@rig')
    await pick(select, 'arm')

    expect(select.emitted('update:modelValue')).toEqual([[null], ['arm']])
  })
})
