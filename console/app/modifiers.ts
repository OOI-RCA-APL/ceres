import { useEventListener } from '@vueuse/core'
import { computed, effectScope } from 'vue'

import { refreshCursor } from '@/cursor'

/** Whether shift is being held, tracked once for the whole application.

Held here rather than per component because several places offer a second meaning for a click
while it is down, and they must agree. One source also means one set of listeners however many of
those places happen to be on screen.

Keyboard events alone are not enough to stay honest. A key pressed before the window had focus is
never seen, and one released while another window had it never arrives, either of which would
leave this stuck. Every pointer event carries the modifiers with it, so pointer events correct the
state as soon as the mouse moves, and losing focus clears it outright.
*/
let shift = $ref(false)

function set(held: boolean) {
  if (shift === held) {
    return
  }

  shift = held

  // A browser settles the cursor when the pointer moves, so a rule that turns on with a held key
  // needs the browser asked again from where the pointer already is.
  refreshCursor()
}

function fromEvent(event: KeyboardEvent | MouseEvent | PointerEvent) {
  set(event.shiftKey)
}

/** Holds the listeners together so they can be let go of in one move.

Detached because this belongs to the application rather than to whichever component happened to
import it first, which would otherwise take the listeners with it when it unmounted.
*/
const scope = effectScope(true)

scope.run(() => {
  // Captured so a handler that stops an event on its way through cannot also stop this from seeing
  // it, and passive since none of it interferes with the event itself.
  useEventListener(document, ['keydown', 'keyup', 'pointerdown', 'pointermove'], fromEvent, {
    capture: true,
    passive: true,
  })

  useEventListener(window, 'blur', () => set(false))
})

// A full load evaluates this once and the listeners live as long as the page does. Replacing the
// module while developing evaluates it again, so the previous scope is stopped rather than left
// listening behind the new one.
import.meta.hot?.dispose(() => scope.stop())

/** Read the modifier keys currently held. */
export function useModifiers() {
  return { shift: computed(() => shift) }
}
