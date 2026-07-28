import { nextTick } from 'vue'

/** Pointer-driven reordering, the way browser tabs behave.

The held item tracks the pointer, its neighbours slide aside as it passes their midpoints, and it
settles into the gap when released. Positions are measured once when the drag begins and every
offset is derived from those, so nothing depends on layout that is mid-animation.

The same behavior serves a horizontal tab strip and a vertical list, which is why the axis is a
parameter rather than two implementations that drift apart.
*/
export type ReorderAxis = 'horizontal' | 'vertical'

type Placement = { start: number; size: number }

type Drag = {
  index: number
  pointerId: number
  origin: number
  placements: Placement[]
  moved: boolean
}

const dragThreshold = 4
const settleDuration = 140

export function usePointerReorder(options: {
  axis: ReorderAxis
  /** Elements being reordered, in their current visual order. */
  elements: () => HTMLElement[]
  onReorder: (from: number, to: number) => void
}) {
  const horizontal = $computed(() => options.axis === 'horizontal')

  let drag = $ref<Drag | null>(null)
  let offset = $ref(0)
  let target = $ref(0)
  let settling = $ref(false)
  let swapping = $ref(false)
  let suppressClick = false

  function measure(element: HTMLElement): Placement {
    const box = element.getBoundingClientRect()

    if (horizontal) {
      return { start: box.left, size: box.width }
    }

    return { start: box.top, size: box.height }
  }

  function coordinate(event: PointerEvent): number {
    return horizontal ? event.clientX : event.clientY
  }

  function onPointerDown(index: number, event: PointerEvent) {
    suppressClick = false

    // A row's own buttons own their presses, and a drag should only ever start from a plain left
    // press.
    if (event.button !== 0 || (event.target as HTMLElement).closest('button') != null) {
      return
    }

    const elements = options.elements()
    const placements = elements.map(measure)
    if (placements.length === 0) {
      return
    }

    drag = {
      index,
      pointerId: event.pointerId,
      origin: coordinate(event),
      placements,
      moved: false,
    }
    offset = 0
    target = index
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: PointerEvent) {
    if (drag == null || event.pointerId !== drag.pointerId || settling) {
      return
    }

    const delta = coordinate(event) - drag.origin
    if (!drag.moved && Math.abs(delta) < dragThreshold) {
      return
    }

    drag.moved = true
    offset = delta
    target = resolveTarget(delta)
  }

  /** Return the index the held item would land on, given how far it has travelled. */
  function resolveTarget(delta: number): number {
    if (drag == null) {
      return 0
    }

    const { index, placements } = drag
    const center = placements[index].start + placements[index].size / 2 + delta

    let landing = index
    while (
      landing > 0 &&
      center < placements[landing - 1].start + placements[landing - 1].size / 2
    ) {
      landing--
    }
    while (
      landing < placements.length - 1 &&
      center > placements[landing + 1].start + placements[landing + 1].size / 2
    ) {
      landing++
    }

    return landing
  }

  /** Return how far an item slides aside to open the gap the held one is heading for. */
  function shiftFor(index: number): number {
    if (drag == null || index === drag.index) {
      return 0
    }

    const size = drag.placements[drag.index].size
    if (drag.index < target && index > drag.index && index <= target) {
      return -size
    }
    if (drag.index > target && index >= target && index < drag.index) {
      return size
    }

    return 0
  }

  /** Return where the held item comes to rest, which is the near edge of the gap it opened. */
  function settledOffset(): number {
    if (drag == null) {
      return 0
    }

    const { index, placements } = drag
    if (target > index) {
      const landing = placements[target]
      const held = placements[index]
      return landing.start + landing.size - (held.start + held.size)
    }
    if (target < index) {
      return placements[target].start - placements[index].start
    }

    return 0
  }

  function styleFor(index: number) {
    if (drag == null) {
      return undefined
    }

    const distance = index === drag.index ? (settling ? settledOffset() : offset) : shiftFor(index)
    const translate = horizontal ? `translateX(${distance}px)` : `translateY(${distance}px)`
    return { transform: translate }
  }

  async function onPointerUp(event: PointerEvent) {
    if (drag == null || event.pointerId !== drag.pointerId) {
      return
    }

    if (!drag.moved) {
      drag = null
      return
    }

    const from = drag.index
    const to = target

    // Let the held item travel into its gap before the list reorders underneath it, otherwise it
    // jumps the remaining distance the instant the transform is dropped.
    suppressClick = true
    settling = true
    await new Promise((resolve) => setTimeout(resolve, settleDuration))

    // Dropping the offsets and reordering the list happen in the same frame, and the items that
    // slid aside are already standing where the new order puts them. Animating that frame would
    // replay the slide they just finished, so transitions are off across the swap and restored
    // after the browser has painted it.
    settling = false
    swapping = true
    drag = null
    offset = 0

    if (to !== from) {
      options.onReorder(from, to)
    }

    await nextTick()
    requestAnimationFrame(() => requestAnimationFrame(() => (swapping = false)))
  }

  /** Whether the click that follows a drag should be swallowed, so releasing does not also
  activate whatever was being dragged.
  */
  function consumeClick(): boolean {
    if (suppressClick) {
      suppressClick = false
      return true
    }

    return false
  }

  return {
    handlers: (index: number) => ({
      onPointerdown: (event: PointerEvent) => onPointerDown(index, event),
      onPointermove: onPointerMove,
      onPointerup: onPointerUp,
      onPointercancel: onPointerUp,
    }),
    styleFor,
    consumeClick,
    isHeld: (index: number) => drag?.index === index,
    isGrabbed: (index: number) => drag?.index === index && !settling,
    get isDragging() {
      return drag != null
    },
    get isSwapping() {
      return swapping
    },
  }
}

/** Move an item from one index to another, returning a new array. */
export function moved<T>(items: T[], from: number, to: number): T[] {
  const result = [...items]
  const [item] = result.splice(from, 1)
  result.splice(to, 0, item)
  return result
}
