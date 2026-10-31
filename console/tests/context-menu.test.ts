import { flushPromises, mount } from '@vue/test-utils'
import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuPortal,
  ContextMenuRoot,
  ContextMenuTrigger,
} from 'reka-ui'
import { describe, expect, it } from 'vitest'
import { h } from 'vue'

import { openContextMenu } from '@/utilities'

/** A context menu holding one "Open" entry, around a button that opens it. */
function render() {
  return mount(
    () =>
      h(ContextMenuRoot, () => [
        h(ContextMenuTrigger, () => h('button', { onClick: openContextMenu }, 'More')),
        h(ContextMenuPortal, () => h(ContextMenuContent, () => h(ContextMenuItem, () => 'Open'))),
      ]),
    { attachTo: document.body },
  )
}

describe('openContextMenu', () => {
  it('opens the context menu around the clicked button', async () => {
    const menu = render()

    await menu.get('button').trigger('click')
    await flushPromises()

    expect(document.querySelector('[role="menu"]')?.textContent).toBe('Open')
    menu.unmount()
  })
})
