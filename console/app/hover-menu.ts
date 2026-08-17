import type { InjectionKey } from 'vue'

/** How a submenu reaches the menu it opened from.

A menu closes on a delay, and a pointer crossing the gap into a submenu has left everything its
own menu can see, so the submenu holds its whole ancestry open while the pointer is inside it.
*/
export type HoverMenuContext = {
  /** Report whether the pointer is anywhere inside `child`, which keeps this menu open. */
  setHeld: (child: symbol, held: boolean) => void
}

export const hoverMenuKey: InjectionKey<HoverMenuContext> = Symbol('hover-menu')
