import type { DropdownMenuItem } from '@nuxt/ui'

import { useDialogs } from '@/dialogs'
import {
  arrangedPage,
  type LayoutArrange,
  layoutArrangeOptions,
  type WidgetPage,
} from '@/workspace'

/** Switching a page between rows and flex, shared by every widget that holds pages. */
export function useLayoutArrange() {
  const dialogs = useDialogs()

  /** Arrange `page` as `arrange`, asking first when its rows would run together. */
  function arrange(page: WidgetPage, arrange: LayoutArrange) {
    const arranged = arrangedPage(page, arrange)
    if (arranged == null || arranged === page) {
      return
    }

    const apply = () => {
      page.arrange = arranged.arrange
      page.layout = arranged.layout
    }

    if (arrange === 'flex' && page.layout.length > 1) {
      dialogs
        .confirm({
          title: 'Arrange As Flex',
          message: 'Flex lays every widget out in one wrapping line, so the rows run together.',
          okLabel: 'Arrange',
        })
        .onOk(apply)
    } else {
      apply()
    }
  }

  /** The choices for `page`, with flex unavailable while it holds a widget that cannot fit its
  own width. */
  function options(page: WidgetPage) {
    return layoutArrangeOptions.map((option) => ({
      ...option,
      disabled: arrangedPage(page, option.value) == null,
    }))
  }

  /** The "Arrange" submenu for `page`. */
  function menuItem(page: WidgetPage): DropdownMenuItem {
    return {
      label: 'Arrange',
      children: options(page).map((option) => ({
        label: option.label,
        type: 'checkbox' as const,
        checked: page.arrange === option.value,
        disabled: option.disabled,
        onUpdateChecked: () => arrange(page, option.value),
      })),
    }
  }

  return { arrange, options, menuItem }
}
