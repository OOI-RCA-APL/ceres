import { reactive } from 'vue'

import { guard } from '@/errors'
import { useNotify } from '@/notify'

/** Shared state and behavior for the status badge hover menu and its flyout submenus.

The menu opens on hover or click anywhere over the badge cluster. Each state row flies its
actions out in a submenu, which follows the pointer, the submenu closes once the pointer rests
anywhere other than its own row or itself. Both the menu and its submenus close on their own
short grace period, long enough for the pointer to cross the gaps between them.
*/
/** The menu currently showing, tracked so opening one closes any other without waiting out its
grace period. */
let openMenu: { close(): void } | null = null

export function useStatusMenu() {
  const notify = useNotify()

  let closeTimer: ReturnType<typeof setTimeout> | null = null
  let submenuCloseTimer: ReturnType<typeof setTimeout> | null = null

  const menu = reactive({
    isOpen: false,
    runSubmenuIsOpen: false,
    enableSubmenuIsOpen: false,
    cancelClose,
    close,
    onEnter,
    onLeave,
    onRowLeave,
    onSubmenuEnter,
    onSubmenuLeave,
    openSubmenu,
    perform,
  })

  function cancelClose() {
    if (closeTimer != null) {
      clearTimeout(closeTimer)
      closeTimer = null
    }
  }

  function cancelSubmenuClose() {
    if (submenuCloseTimer != null) {
      clearTimeout(submenuCloseTimer)
      submenuCloseTimer = null
    }
  }

  function closeSubmenus() {
    cancelSubmenuClose()
    menu.runSubmenuIsOpen = false
    menu.enableSubmenuIsOpen = false
  }

  function close() {
    cancelClose()
    closeSubmenus()
    menu.isOpen = false
    if (openMenu === menu) {
      openMenu = null
    }
  }

  function onEnter() {
    cancelClose()
    if (openMenu != null && openMenu !== menu) {
      openMenu.close()
    }

    openMenu = menu
    menu.isOpen = true
  }

  function onLeave() {
    cancelClose()
    closeTimer = setTimeout(close, 200)
  }

  function openSubmenu(kind: 'run' | 'enable') {
    cancelSubmenuClose()
    menu.runSubmenuIsOpen = kind === 'run'
    menu.enableSubmenuIsOpen = kind === 'enable'
  }

  // Leaving a state row closes its submenu unless the pointer lands on the submenu itself or on
  // the other state row.
  function onRowLeave() {
    cancelSubmenuClose()
    submenuCloseTimer = setTimeout(closeSubmenus, 150)
  }

  function onSubmenuEnter() {
    cancelClose()
    cancelSubmenuClose()
  }

  function onSubmenuLeave() {
    onLeave()
    onRowLeave()
  }

  // The menu stays open through an action so several can be run in a row, the outcome of each
  // one is reported as a toast.
  async function perform(action: () => unknown, success: string, failure: string) {
    await guard(Promise.resolve(action()), () => {
      notify.error(failure)
    })
    notify.success(success)
  }

  return menu
}
